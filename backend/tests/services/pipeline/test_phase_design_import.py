"""The shared import phase writes one PageV2 schema per design page, from
whichever markup kind the provider returns, and never clobbers a page it
could not import."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.design_source import DesignMarkup, DesignSourceError
from services.pipeline.phase_design_import import design_pages, phase_design_import


class _Source:
    provider = "uxpilot"
    container = "pg"

    def __init__(self, markup_by_ref, reachable=True):
        self._m = markup_by_ref
        self._reachable = reachable
        self.asset_calls = []

    async def reachable(self):
        return self._reachable

    async def markup(self, ref):
        v = self._m.get(ref)
        if isinstance(v, Exception):
            raise v
        return v

    async def assets(self, urls, output_dir, project_id=None):
        self.asset_calls.append(list(urls))
        return {u: f"/api/asset/{project_id}/figma/{i}.png" for i, u in enumerate(urls)}


_PLAN = {"pages": [
    {"route": "/", "name": "Home", "design_ref": "d1", "file": "src/schemas/home.json"},
    {"route": "/orders", "name": "Orders", "design_ref": "d2"},
    {"route": "/settings", "name": "Settings", "figma_node_id": "1:2"},
    {"route": "/about", "name": "About"},
]}


def test_design_pages_honours_both_ref_keys():
    assert [p["route"] for p in design_pages(_PLAN)] == ["/", "/orders", "/settings"]


async def _run(source, plan, tmp_path):
    imported = set()
    events = []
    async for evt in phase_design_import(None, plan, source=source, output_dir=str(tmp_path),
                                         project_id="p1", imported_routes=imported):
        events.append(evt)
    return imported, events


@pytest.mark.asyncio
async def test_writes_schemas_from_html_and_jsx(tmp_path):
    (tmp_path / "src/schemas").mkdir(parents=True)
    (tmp_path / "src/schemas/settings.json").write_text(json.dumps({"kept": True}))
    src = _Source({
        "d1": DesignMarkup("d1", "html", '<div style="display:flex"><h1>Home</h1><img src="https://x/hero.png"></div>',
                           asset_urls=("https://x/hero.png",)),
        "d2": DesignMarkup("d2", "jsx", '<div className="flex flex-col"><p className="font-bold">Orders</p></div>'),
        "1:2": DesignSourceError("boom"),
    })
    imported, events = await _run(src, json.loads(json.dumps(_PLAN)), tmp_path)
    assert imported == {"/", "/orders"}
    home = json.loads((tmp_path / "src/schemas/home.json").read_text())
    assert home["id"] == "home" and home["_figmaDerived"] is True
    assert home["_designOrigin"] == {"provider": "uxpilot", "ref": "d1", "container": "pg"}
    assert "/api/asset/p1/figma/0.png" in json.dumps(home)
    orders = json.loads((tmp_path / "src/schemas/orders.json").read_text())
    assert orders["children"][0]["type"] == "Stack"
    # The failed page kept whatever was there.
    assert json.loads((tmp_path / "src/schemas/settings.json").read_text()) == {"kept": True}
    nav = json.loads((tmp_path / "src/contracts/nav-flow.json").read_text())
    assert {p["route"] for p in nav["pages"]} == {"/", "/orders"}
    texts = [json.loads(e["data"])["text"] for e in events if e["event"] == "log"]
    assert any("2/3 page(s) imported" in t for t in texts)
    assert src.asset_calls == [["https://x/hero.png"]]


@pytest.mark.asyncio
async def test_unreachable_source_imports_nothing(tmp_path):
    src = _Source({"d1": DesignMarkup("d1", "html", "<div>x</div>")}, reachable=False)
    imported, events = await _run(src, _PLAN, tmp_path)
    assert imported == set()
    assert not (tmp_path / "src/schemas/home.json").exists()


@pytest.mark.asyncio
async def test_plan_without_refs_is_a_noop(tmp_path):
    imported, events = await _run(_Source({}), {"pages": [{"route": "/x"}]}, tmp_path)
    assert imported == set() and len(events) == 1


@pytest.mark.asyncio
async def test_schema_kind_is_written_then_refined_with_the_preview(tmp_path, monkeypatch):
    """A provider-mapped tree lands as-is, then the refiner restructures it,
    seeing the page's preview; the origin markers survive the refine."""
    import agents.figma_schema_refiner as refiner
    import services.schema_prompt as sp

    seen = {}

    async def fake_refine(det_schema, shot_path, descriptor):
        seen["shot"] = shot_path
        seen["descriptor"] = descriptor
        return {"schemaVersion": "2", "id": "x", "children": [{"type": "Stack", "props": {}, "children": []}]}

    monkeypatch.setattr(refiner, "run_figma_schema_refiner", fake_refine)
    monkeypatch.setattr(sp, "_format_library_descriptor", lambda: "DESCRIPTOR")

    class _Mapped(_Source):
        def theme_tokens(self):
            return {"colors": {"brand": "#123456"}, "typography": {"body": "Inter"}}

    src = _Mapped({
        "d1": DesignMarkup("d1", "schema",
                           json.dumps({"schemaVersion": "2.0", "children": [{"type": "Container", "props": {}, "children": []}]}),
                           preview_url="https://cdn/preview.png", incomplete=2),
    })
    (tmp_path / "src/theme").mkdir(parents=True)
    (tmp_path / "src/theme/tokens.custom.json").write_text(json.dumps({"colors": {"accent": "#ABCDEF"}, "spacing": {"md": 8}}))

    imported, events = await _run(src, {"pages": [{"route": "/", "name": "Home", "design_ref": "d1"}]}, tmp_path)
    assert imported == {"/"}
    home = json.loads((tmp_path / "src/schemas/home.json").read_text())
    assert home["children"][0]["type"] == "Stack"            # refined tree
    assert home["_designOrigin"]["ref"] == "d1" and home["_figmaDerived"] is True
    assert seen["descriptor"] == "DESCRIPTOR"
    assert src.asset_calls[-1] == ["https://cdn/preview.png"]  # the preview was fetched for the refiner
    tokens = json.loads((tmp_path / "src/theme/tokens.custom.json").read_text())
    assert tokens["colors"] == {"accent": "#ABCDEF", "brand": "#123456"}   # merged per category
    assert tokens["spacing"] == {"md": 8} and tokens["typography"] == {"body": "Inter"}
    texts = [json.loads(e["data"])["text"] for e in events if e["event"] == "log"]
    assert any("mapped from the node tree, 2 unclassified" in t for t in texts)
    assert any("responsive schema" in t for t in texts)


@pytest.mark.asyncio
async def test_refiner_failure_keeps_the_mapped_tree(tmp_path, monkeypatch):
    import agents.figma_schema_refiner as refiner
    import services.schema_prompt as sp

    async def boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(refiner, "run_figma_schema_refiner", boom)
    monkeypatch.setattr(sp, "_format_library_descriptor", lambda: "D")
    src = _Source({"d1": DesignMarkup("d1", "schema", json.dumps({"schemaVersion": "2.0", "children": [{"type": "Container", "props": {}, "children": []}]}))})
    imported, events = await _run(src, {"pages": [{"route": "/", "design_ref": "d1"}]}, tmp_path)
    home = json.loads((tmp_path / "src/schemas/home.json").read_text())
    assert imported == {"/"} and home["children"][0]["type"] == "Container"

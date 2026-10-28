"""A design of hundreds of screens is read whole, held as several designs, and
built a group at a time.

Three walls stood in front of a 500-frame Figma file:

* one connect read at most forty frames — covers and icon sheets counted —
  and only the file's first page when the link named no node;
* every connect was `FIGMA-001`, so a second link replaced the first;
* nothing grouped the screens, so the module-at-a-time build had nothing to
  hold them by.

Now the whole file is listed, screens are read in rounds (one REST request
per round once the MCP is out of the picture) and kept as they land, so a
cut-off read carries on; each link is its own design; and the designer's
Figma pages and sections become the modules the screens are built in.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.figma import store
from services.figma.gateway import FigmaGatewayError
from services.figma.reference import ROUND, _screens_from_metadata, extract
from services.figma.url import FigmaTarget

TARGET = FigmaTarget(file_key="BIGFILE", source_url="https://figma.com/design/BIGFILE/Big")


def _frame(i: int, name: str | None = None) -> dict:
    return {"id": f"10:{i}", "type": "FRAME", "name": name or f"Screen {i}",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 900},
            "children": [{"id": f"10:{i}:t", "type": "FRAME", "name": "Inner",
                          "absoluteBoundingBox": {"x": 10, "y": 10, "width": 100, "height": 20}}]}


def _file(pages: dict[str, list[dict]]) -> dict:
    return {"document": {"id": "0:0", "type": "DOCUMENT", "children": [
        {"id": f"0:{n}", "type": "CANVAS", "name": name, "children": kids}
        for n, (name, kids) in enumerate(pages.items(), start=1)]}}


def _doc(node_id: str) -> dict:
    return {"id": node_id, "type": "FRAME", "name": node_id,
            "absoluteBoundingBox": {"x": 100, "y": 0, "width": 1440, "height": 900},
            "children": [{"id": node_id + ":h", "type": "TEXT", "characters": "Heading " + node_id,
                          "absoluteBoundingBox": {"x": 124, "y": 24, "width": 400, "height": 32}}]}


class RestGateway:
    """The production shape: the MCP refused, the REST API answers in batches."""

    rest_preferred = True

    def __init__(self, metadata: dict, *, fail_after_rounds: int | None = None):
        self.metadata = metadata
        self.node_batches: list[list[str]] = []
        self.image_batches: list[list[str]] = []
        self.fail_after_rounds = fail_after_rounds

    async def call(self, tool, *, file_key, node_id=None, **kw):
        if tool == "get_metadata":
            return [{"type": "structured", "data": self.metadata}]
        raise FigmaGatewayError("tool_error", f"{tool} unavailable")

    async def rest_nodes(self, *, file_key, node_ids):
        if self.fail_after_rounds is not None and len(self.node_batches) >= self.fail_after_rounds:
            raise FigmaGatewayError("rate_limited", "429 after six tries")
        self.node_batches.append(list(node_ids))
        return {n: _doc(n) for n in node_ids}

    async def rest_images(self, *, file_key, node_ids):
        self.image_batches.append(list(node_ids))
        return {n: b"\x89PNG" + n.encode() for n in node_ids}


# -- every frame, every page, sections as groups -----------------------------

def test_every_frame_is_read_not_the_first_forty():
    meta = _file({"Cover": [_frame(0, "Cover")], "App": [_frame(i) for i in range(1, 121)]})
    gw = RestGateway(meta)
    ref = asyncio.run(extract(gw, TARGET))
    assert ref.summary()["screens"] == 120
    # one REST request per round, not one per screen
    assert len(gw.node_batches) == -(-120 // ROUND) and len(gw.image_batches) == len(gw.node_batches)
    screen = ref.screen("10:77")
    assert screen.structure["source"] == "rest_node_document"
    assert screen.image.startswith("data:image/png;base64,")
    # the boxes come from the frame's own tree, not the shallow listing
    assert screen.structure["boxes"][0]["id"] == "10:77:h"


def test_a_limit_counts_screens_only():
    meta = _file({"P": [_frame(0, "Cover"), _frame(1, "Logo"), _frame(2), _frame(3), _frame(4)]})
    screens = _screens_from_metadata([{"type": "structured", "data": meta}], limit=2)
    assert [s.name for s in screens if s.looks_like_screen] == ["Screen 2", "Screen 3"]


def test_a_section_holding_frames_is_their_group_not_a_screen():
    meta = _file({
        "Billing": [{"id": "5:1", "type": "SECTION", "name": "Invoices",
                     "children": [_frame(1, "Invoice List"), _frame(2, "Invoice Detail"),
                                  {"id": "5:2", "type": "SECTION", "name": "Refunds",
                                   "children": [_frame(3, "Refund Queue")]}]},
                    _frame(4, "Billing Home")],
        "Notes": [{"id": "6:1", "type": "SECTION", "name": "Sticky", "children": [
            {"id": "6:2", "type": "TEXT", "name": "a note"}]}],
    })
    screens = {s.name: s for s in _screens_from_metadata([{"type": "structured", "data": meta}])}
    assert "Invoices" not in screens and "Refunds" not in screens
    assert screens["Invoice List"].group == "Invoices"
    assert screens["Refund Queue"].group == "Invoices / Refunds"
    assert screens["Billing Home"].group == "Billing"          # straight on the page
    assert screens["Sticky"].canvas == "Notes"                 # drawing only: still a screen
    # a frame's insides are never screens of their own
    assert not any(s.node_id.endswith(":t") for s in screens.values())


def test_the_markup_listing_reads_sections_the_same_way():
    markup = ('<canvas id="0:1" name="Billing"><section id="5:1" name="Invoices">'
              '<frame id="10:1" name="Invoice List" width="1440" height="900"><frame id="10:9" name="Inner"/></frame>'
              '</section></canvas>')
    (screen,) = _screens_from_metadata([{"type": "text", "text": markup}])
    assert (screen.name, screen.group) == ("Invoice List", "Invoices")


def test_a_link_without_a_node_lists_the_whole_file():
    from services.figma.credentials import FigmaCredential
    from services.figma.gateway import LISTING_DEPTH_FILE, FigmaGateway

    class _R:
        def resolve(self, ref):
            return "figd_test"

    asked = {}

    async def fake_file(file_key, token, depth=2):
        asked["depth"] = depth
        return _file({"One": [_frame(1)], "Two": [_frame(2)]})

    gw = FigmaGateway(credential=FigmaCredential(ref="FIGMA_TOKEN"), resolver=_R())
    with patch("services.figma_client.fetch_figma_file", fake_file):
        blocks = asyncio.run(gw._rest_fallback("get_metadata", "KEY", None))
    assert asked["depth"] == LISTING_DEPTH_FILE
    assert {s.canvas for s in _screens_from_metadata(blocks)} == {"One", "Two"}


def test_the_mcp_is_asked_for_code_once_not_once_a_screen():
    meta = _file({"App": [_frame(i) for i in range(1, 30)]})

    class Gated(RestGateway):
        rest_preferred = False
        asks = 0

        async def call(self, tool, *, file_key, node_id=None, **kw):
            if tool == "get_design_context":
                Gated.asks += 1
                raise FigmaGatewayError("unreachable", "gated to partners")
            return await super().call(tool, file_key=file_key, node_id=node_id, **kw)

    gw = Gated(meta)
    ref = asyncio.run(extract(gw, TARGET, with_images=False))
    assert ref.summary()["screens"] == 29 and all(s.structure.get("document") for s in ref.screens)
    # the first round asks a handful at once; after the refusal nobody asks again
    assert Gated.asks <= 4


# -- a cut-off read carries on -----------------------------------------------

def test_a_read_cut_off_by_the_rate_limit_carries_on(tmp_path):
    meta = _file({"App": [_frame(i) for i in range(1, 61)]})
    done, keep, finish, resumed = store.reader(tmp_path, "FIGMA-001", TARGET)
    assert resumed == 0
    first = RestGateway(meta, fail_after_rounds=2)
    with pytest.raises(FigmaGatewayError) as err:
        asyncio.run(extract(first, TARGET, done=done, keep=keep))
    assert err.value.kind == "rate_limited"

    done, keep, finish, resumed = store.reader(tmp_path, "FIGMA-001", TARGET)
    assert resumed == 2 * ROUND
    second = RestGateway(meta)
    ref = asyncio.run(extract(second, TARGET, done=done, keep=keep))
    asked = [n for batch in second.node_batches for n in batch]
    assert len(asked) == 60 - 2 * ROUND and "10:1" not in asked
    assert all(s.structure.get("document") for s in ref.screens)
    finish()
    # a finished read is the design as it was: the next connect reads afresh
    done, keep, finish, resumed = store.reader(tmp_path, "FIGMA-001", TARGET)
    assert resumed == 0 and done("10:1") is None


def test_figma_saying_too_many_is_waited_out():
    from services import figma_client as C

    busy = MagicMock(status_code=429, headers={"Retry-After": "7"})
    ok = MagicMock(status_code=200, json=MagicMock(return_value={"nodes": {
        "1:2": {"document": {"id": "1:2"}}}}))
    slept = []

    async def nap(s):
        slept.append(s)

    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=[busy, busy, ok])), \
         patch("services.figma_client.asyncio.sleep", nap):
        out = asyncio.run(C.fetch_figma_nodes("K", ["1:2"], "t"))
    assert out == {"1:2": {"id": "1:2"}} and slept == [7.0, 7.0]

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=busy)), \
         patch("services.figma_client.asyncio.sleep", nap), \
         pytest.raises(C.FigmaRateLimited):
        asyncio.run(C.fetch_figma_nodes("K", ["1:2"], "t"))


def test_a_batch_too_big_to_answer_is_halved():
    from services import figma_client as C

    def answer(url, params=None, headers=None):
        ids = params["ids"].split(",")
        if len(ids) > 2:
            return MagicMock(status_code=400, text="too large", headers={})
        return MagicMock(status_code=200, json=MagicMock(return_value={
            "nodes": {i: {"document": {"id": i}} for i in ids}}))

    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=answer)):
        out = asyncio.run(C.fetch_figma_nodes("K", [f"1:{i}" for i in range(8)], "t", batch_size=8))
    assert sorted(out) == [f"1:{i}" for i in range(8)] and all(out.values())


# -- stored a screen at a time -------------------------------------------------

def test_the_store_is_an_index_and_a_file_per_screen(tmp_path):
    meta = _file({"App": [_frame(i) for i in range(1, 6)]})
    ref = asyncio.run(extract(RestGateway(meta), TARGET))
    index = store.save(ref, tmp_path)
    assert index.stat().st_size < 4000                       # names and sizes, not trees
    assert (tmp_path / ".forge/figma/FIGMA-001/screens/10_3.png").read_bytes().startswith(b"\x89PNG")
    one = store.load_screen("FIGMA-001", "10:3", tmp_path)
    assert one.structure["document"]["id"] == "10:3" and one.image == "FIGMA-001/screens/10_3.png"
    whole = store.load("FIGMA-001", tmp_path)
    assert all(s.structure.get("document") for s in whole.screens)
    assert store.load("FIGMA-001", tmp_path, screens=False).screens[0].structure == {}


def test_a_store_written_whole_still_reads(tmp_path):
    import json
    from dataclasses import asdict

    ref = asyncio.run(extract(RestGateway(_file({"App": [_frame(1)]})), TARGET, with_images=False))
    folder = tmp_path / ".forge/figma"
    folder.mkdir(parents=True)
    (folder / "FIGMA-001.json").write_text(json.dumps(asdict(ref)))
    assert store.load_screen("FIGMA-001", "10:1", tmp_path).structure["document"]["id"] == "10:1"


# -- several designs ---------------------------------------------------------

def test_another_link_is_another_design_and_the_same_link_is_the_same_one():
    from services.figma.url import parse
    from services.smith.figma_connect import source_id_for

    doc = {"designSources": [{"id": "FIGMA-001", "type": "figma", "fileKey": "BIGFILE", "nodeId": "1-2"}]}
    assert source_id_for(doc, FigmaTarget(file_key="BIGFILE", node_id="1-2")) == "FIGMA-001"
    assert source_id_for(doc, FigmaTarget(file_key="BIGFILE", node_id="3-4")) == "FIGMA-002"
    assert source_id_for(doc, FigmaTarget(file_key="OTHER")) == "FIGMA-002"
    assert parse("https://www.figma.com/design/zYxW9876VuTs/x") is not None


def test_a_second_designs_frames_name_their_design(tmp_path):
    from services.blueprint import figma_layout as F

    a = asyncio.run(extract(RestGateway(_file({"A": [_frame(1)]})), TARGET, with_images=False))
    b = asyncio.run(extract(RestGateway(_file({"B": [_frame(1, "Other one")]})),
                            FigmaTarget(file_key="OTHER"), source_id="FIGMA-002", with_images=False))
    store.save(a, tmp_path)
    store.save(b, tmp_path)
    assert store.frame_ref("FIGMA-001", "10:1") == "10:1"
    assert store.frame_ref("FIGMA-002", "10:1") == "FIGMA-002/10:1"
    doc = {"designSources": [{"id": "FIGMA-001", "fileKey": "BIGFILE"}, {"id": "FIGMA-002", "fileKey": "OTHER"}]}
    source, screen = F.locate(doc, tmp_path, "FIGMA-002/10:1")
    assert source["fileKey"] == "OTHER" and screen.name == "Other one"
    assert F.locate(doc, tmp_path, "10:1")[1].name == "Screen 1"


def _two_designs(tmp_path):
    from services.blueprint.service import BlueprintService

    svc = BlueprintService.create(output_dir=str(tmp_path), app_id="t", name="T",
                                  domain="unknown", description="a case tracker")
    svc.doc["designSources"] = [
        {"id": "FIGMA-001", "type": "figma", "fileKey": "A", "url": "https://www.figma.com/design/A/a",
         "name": "Admin", "treatAs": "specification", "frames": [{"nodeId": "1:2", "name": "Users", "group": "Admin"}]},
        {"id": "FIGMA-002", "type": "figma", "fileKey": "zYxW9876VuTs", "url": "https://www.figma.com/design/zYxW9876VuTs/b",
         "name": "Shop", "treatAs": "specification", "frames": [{"nodeId": "1:2", "name": "Cart", "group": "Shop"}]},
    ]
    svc.doc["modules"] = [
        {"id": "MODULE-001", "name": "Admin", "designGroup": "Admin", "status": "PROPOSED"},
        {"id": "MODULE-002", "name": "Shop", "designGroup": "Shop", "status": "PROPOSED"},
    ]
    svc.doc["pages"] = [
        {"id": "PAGE-001", "name": "Users", "route": "/users", "pattern": "entity_list", "purpose": "u",
         "access": "authenticated", "figmaFrame": "1:2", "module": "MODULE-001", "status": "PROPOSED"},
        {"id": "PAGE-002", "name": "Cart", "route": "/cart", "pattern": "entity_list", "purpose": "c",
         "access": "authenticated", "figmaFrame": "FIGMA-002/1:2", "module": "MODULE-002", "status": "PROPOSED"},
    ]
    svc.doc["pageLayouts"] = [
        {"page": "PAGE-001", "composedBy": "figma", "root": {"type": "Text", "props": {"content": "x"}, "children": []}, "dataSources": []},
        {"page": "PAGE-002", "composedBy": "figma", "root": {"type": "Text", "props": {"content": "y"}, "children": []}, "dataSources": []},
    ]
    svc.save()
    return svc


def test_one_design_of_several_is_disconnected_alone(tmp_path):
    from services.smith import design_disconnect as D

    svc = _two_designs(tmp_path)
    assert D.which(svc, "drop https://www.figma.com/design/zYxW9876VuTs/b please")[0] == "FIGMA-002"
    out = D.disconnect(svc, "disconnect FIGMA-002", source="FIGMA-002")
    assert out["unbound"] == ["PAGE-002"] and out["dropped_layouts"] == 1
    assert [s["id"] for s in svc.doc["designSources"]] == ["FIGMA-001"]
    pages = {p["id"]: p for p in svc.doc["pages"]}
    assert pages["PAGE-001"]["figmaFrame"] == "1:2" and "figmaFrame" not in pages["PAGE-002"]
    assert [l["page"] for l in svc.doc["pageLayouts"]] == ["PAGE-001"]
    mods = {m["id"]: m for m in svc.doc["modules"]}
    assert mods["MODULE-001"]["designGroup"] == "Admin" and "designGroup" not in mods["MODULE-002"]


def test_with_several_designs_and_none_named_smith_asks_which(tmp_path):
    from services.smith4.verbs import Ctx, disconnect_design

    _two_designs(tmp_path)
    out = disconnect_design(Ctx(output_dir=str(tmp_path), project_id="p", message="disconnect the design", ask="disconnect the design"), {})
    assert out.status == "asked" and "All of them" in out.options
    assert any(o.startswith("FIGMA-002") for o in out.options)


# -- groups become modules -----------------------------------------------------

def test_a_drawn_frame_lands_in_its_groups_module(tmp_path):
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal
    from services.blueprint.executors import pin_page_set
    from services.blueprint.page_planner import design_groups, page_slots

    doc = _two_designs(tmp_path).doc
    assert design_groups(doc) == ["Admin", "Shop"]
    slots = {s["figmaFrame"]: s for s in page_slots(doc)}
    assert slots["FIGMA-002/1:2"]["module"] == "MODULE-002" and slots["1:2"]["module"] == "MODULE-001"
    result = AgentResult(task_id="t", agent="page_design", proposals=[
        ArtifactProposal(section="pages", natural_key="/cart",
                         body={"name": "Cart", "route": "/cart", "figmaFrame": "FIGMA-002/1:2",
                               "module": "MODULE-001"})])
    pin_page_set(result, doc)
    assert result.proposals[0].body["module"] == "MODULE-002"


def test_a_module_set_that_leaves_a_group_out_is_refused(tmp_path):
    from services.blueprint.agent_contract import (
        AgentResult, ArtifactProposal, InvalidDesignModules, check_design_modules,
    )

    doc = _two_designs(tmp_path).doc
    doc["modules"] = []

    def modules(*bodies):
        return AgentResult(task_id="t", agent="solution_architecture", proposals=[
            ArtifactProposal(section="modules", natural_key=b["name"], body=b) for b in bodies])

    with pytest.raises(InvalidDesignModules, match='"Shop"'):
        check_design_modules(modules({"name": "Admin", "designGroup": "Admin"}, {"name": "Settings"}), doc)
    with pytest.raises(InvalidDesignModules, match="not one of the design's groups"):
        check_design_modules(modules({"name": "X", "designGroup": "Nope"}), doc)
    check_design_modules(modules({"name": "Admin", "designGroup": "Admin"},
                                 {"name": "Shop", "designGroup": "Shop"}), doc)
    # a one-module edit is not asked about groups it never touched
    check_design_modules(modules({"name": "Reports"}), doc)


def test_the_architect_is_told_the_groups(tmp_path):
    from services.blueprint.executors import build_prompt

    user = build_prompt(_two_designs(tmp_path).doc, "ux_architecture")[1]
    assert "DRAWN IN GROUPS" in user and "  - Shop (1 screens)" in user


def test_a_large_designs_brief_shares_one_label_budget():
    from services.figma.brief import labels_per_screen

    assert labels_per_screen(10) == 40
    assert labels_per_screen(500) == 8
    assert labels_per_screen(5000) == 6

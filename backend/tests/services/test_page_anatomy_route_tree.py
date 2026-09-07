"""page_anatomy must see the app's real routes, not just its schemas.

The module's own docstring states the rule it exists to enforce: "a
detail page without a way back is a dead end on mobile where browser
chrome is hidden". It then iterated ``src/schemas/*.json``.

Measured across 173 generated apps: 921 real ``[id]`` detail routes
live under ``src/app``, but exactly ONE page schema carries a dynamic
route. So the rule fired on ~1 of 921 detail pages. Most detail pages
are template-injected .tsx (runtime_injector._inject_task_inbox_pages)
or served by the ``[...slug]`` catch-all — invisible to a schema walk.

Two consequences this file pins down:

1. A detail route that exists only as .tsx must be REPORTED, not
   silently skipped. We can't patch a hand-written page from here, but
   an unreachable dead-end must show up in the contract rather than
   vanish because we looked in the wrong directory.

2. The back target must come from the route tree's nearest EXISTING
   ancestor. The old code did ``route.rsplit("/", 1)[0]``, so a page at
   ``/products/[id]/edit`` in an app with no ``/products/[id]`` route
   reported "parent not in registry" and injected nothing — even though
   ``/products`` was right there and perfectly linkable.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.page_anatomy import apply_page_anatomy


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _mk(tmp_path: Path, *, routes: list[str], schemas: dict[str, dict],
        app_pages: tuple[str, ...] = (), tables=("products",)) -> Path:
    root = tmp_path / "app"
    _write(root, "src/db/schema/entities.ts", "\n".join(
        f'export const {t} = pgTable("{t}", {{ id: uuid("id").primaryKey() }});'
        for t in tables))
    reg = ",\n".join(f'  "{r}": () => import("./x.json")' for r in routes)
    _write(root, "src/schemas/registry.ts", "export const s = {\n" + reg + "\n};\n")
    _write(root, "src/contracts/plan.json", "{}")
    for rel, doc in schemas.items():
        _write(root, f"src/schemas/{rel}", json.dumps(doc))
    for rel in app_pages:
        _write(root, f"src/app/{rel}/page.tsx", "export default function P(){return null}")
    return root


def _detail(children: list | None = None) -> dict:
    return {"dataSources": [{"name": "p", "entity": "Product", "op": "get"}],
            "root": {"type": "Stack", "children": children or [
                {"type": "Heading", "props": {"text": "Product"}}]}}


class TestTsxOnlyDetailRoutesAreVisible:
    """The 920-of-921 case: no schema file, so the old walk never saw it."""

    def test_a_tsx_only_detail_route_is_reported(self, tmp_path):
        root = _mk(tmp_path, routes=["/products"], schemas={},
                   app_pages=("products", "products/[id]"))
        rep = apply_page_anatomy(root)
        hits = [f for f in rep["findings"] if f["route"] == "/products/[id]"]
        assert hits, "a detail route with no schema must not vanish from the contract"

    def test_it_is_reported_not_injected(self, tmp_path):
        """We cannot patch hand-written .tsx from a JSON pass — say so."""
        root = _mk(tmp_path, routes=["/products"], schemas={},
                   app_pages=("products", "products/[id]"))
        rep = apply_page_anatomy(root)
        f = next(f for f in rep["findings"] if f["route"] == "/products/[id]")
        assert f["action"] == "reported"

    def test_the_reachable_parent_is_named_in_the_report(self, tmp_path):
        root = _mk(tmp_path, routes=["/products"], schemas={},
                   app_pages=("products", "products/[id]"))
        rep = apply_page_anatomy(root)
        f = next(f for f in rep["findings"] if f["route"] == "/products/[id]")
        assert "/products" in json.dumps(f)


class TestBackTargetUsesNearestExistingAncestor:
    def test_missing_intermediate_no_longer_blocks_the_repair(self, tmp_path):
        """/products/[id] doesn't exist; /products does — link to it."""
        root = _mk(tmp_path, routes=["/products", "/products/[id]/edit"],
                   schemas={"products/[id]/edit.json": _detail()})
        rep = apply_page_anatomy(root)
        f = next(f for f in rep["findings"]
                 if f["slot"] == "detail_back" and f["route"] == "/products/[id]/edit")
        assert f["action"] == "injected"
        assert f["target"] == "/products"

    def test_the_injected_button_points_at_the_real_route(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/[id]/edit"],
                   schemas={"products/[id]/edit.json": _detail()})
        apply_page_anatomy(root)
        doc = json.loads((root / "src/schemas/products/[id]/edit.json").read_text(encoding="utf-8"))
        btn = doc["root"]["children"][0]
        assert btn["props"]["onClick"]["target"] == "/products"

    def test_a_route_with_no_real_ancestor_is_still_only_reported(self, tmp_path):
        root = _mk(tmp_path, routes=["/products/[id]"],
                   schemas={"products/[id].json": _detail()})
        rep = apply_page_anatomy(root)
        f = next(f for f in rep["findings"] if f["slot"] == "detail_back")
        assert f["action"] == "reported"


class TestSchemaBackedBehaviourIsUnchanged:
    def test_normal_detail_page_still_repaired(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/[id]"],
                   schemas={"products/[id].json": _detail()})
        rep = apply_page_anatomy(root)
        f = next(f for f in rep["findings"] if f["slot"] == "detail_back")
        assert f["action"] == "injected" and f["target"] == "/products"

    def test_rerun_is_idempotent_across_the_new_driver(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/[id]"],
                   schemas={"products/[id].json": _detail()})
        apply_page_anatomy(root)
        rep2 = apply_page_anatomy(root)
        assert rep2["summary"]["injected"] == 0

"""The route tree must be readable by the running app, not just the pipeline.

300 nested routes across the corpus ship as hand-written .tsx with no
breadcrumb and no back affordance. A JSON pass cannot patch those, and
regex-rewriting 300 hand-written React files to inject a crumb would be
fragile and would have to be redone every regeneration.

The durable seam is the app shell: (dashboard)/layout.tsx wraps every
page and is a server component that already reads files. If it can read
the route hierarchy, one client component renders the crumb for any
route the schema layer doesn't own — covering tsx pages today and any
route added later, with no per-file surgery.

That requires the tree as a shipped artifact. Two rules it must honour:

* `parent` is the nearest EXISTING route, matching RouteTree.ancestors,
  so the shell can never render a crumb that 404s.
* `owned_by_schema` marks routes whose page schema already carries an
  injected Breadcrumb, so the shell stays out of their way and the app
  never shows two breadcrumb trails.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.page_nav import write_route_tree_contract


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _mk(tmp_path: Path, *, routes: list[str], schemas: dict[str, dict] | None = None,
        app_pages: tuple[str, ...] = ()) -> Path:
    root = tmp_path / "app"
    reg = ",\n".join(f'  "{r}": () => import("./x.json")' for r in routes)
    _write(root, "src/schemas/registry.ts", "export const s = {\n" + reg + "\n};\n")
    for rel, doc in (schemas or {}).items():
        _write(root, f"src/schemas/{rel}", json.dumps(doc))
    for rel in app_pages:
        _write(root, f"src/app/{rel}/page.tsx", "export default function P(){return null}")
    return root


def _contract(root: Path) -> dict:
    return json.loads((root / "src/contracts/route-tree.json").read_text())


def _page(children: list | None = None) -> dict:
    return {"root": {"type": "Stack", "children": children if children is not None else []}}


class TestContractShape:
    def test_it_is_written_where_the_shell_can_read_it(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/[id]"])
        write_route_tree_contract(root)
        assert (root / "src/contracts/route-tree.json").is_file()

    def test_every_route_carries_parent_and_label(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/[id]"])
        write_route_tree_contract(root)
        node = _contract(root)["routes"]["/products/[id]"]
        assert node["parent"] == "/products"
        assert node["label"] == "Product"

    def test_top_level_parent_is_null(self, tmp_path):
        root = _mk(tmp_path, routes=["/products"])
        write_route_tree_contract(root)
        assert _contract(root)["routes"]["/products"]["parent"] is None


class TestParentIsAlwaysReachable:
    def test_a_missing_intermediate_is_skipped(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/[id]/edit"])
        write_route_tree_contract(root)
        assert _contract(root)["routes"]["/products/[id]/edit"]["parent"] == "/products"

    def test_every_declared_parent_exists_as_a_route(self, tmp_path):
        root = _mk(tmp_path, routes=["/a", "/a/b/c", "/x/[id]/y"])
        write_route_tree_contract(root)
        routes = _contract(root)["routes"]
        for r, n in routes.items():
            if n["parent"] is not None:
                assert n["parent"] in routes, f"{r} points at a non-existent parent"


class TestSchemaOwnershipPreventsDoubleCrumbs:
    def test_a_schema_with_a_breadcrumb_is_marked_owned(self, tmp_path):
        crumb = {"type": "Breadcrumb", "props": {"items": [{"label": "X"}]}}
        root = _mk(tmp_path, routes=["/products", "/products/new"],
                   schemas={"products/new.json": _page([crumb])})
        write_route_tree_contract(root)
        assert _contract(root)["routes"]["/products/new"]["owned_by_schema"] is True

    def test_a_schema_without_one_is_not_owned(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/new"],
                   schemas={"products/new.json": _page([])})
        write_route_tree_contract(root)
        assert _contract(root)["routes"]["/products/new"]["owned_by_schema"] is False

    def test_a_tsx_only_route_is_not_owned(self, tmp_path):
        root = _mk(tmp_path, routes=["/products"],
                   app_pages=("products", "products/[id]"))
        write_route_tree_contract(root)
        assert _contract(root)["routes"]["/products/[id]"]["owned_by_schema"] is False


class TestDegenerate:
    def test_empty_app_writes_nothing_and_does_not_crash(self, tmp_path):
        assert write_route_tree_contract(tmp_path / "nope")["routes"] == 0

    def test_rerun_is_stable(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/[id]"])
        write_route_tree_contract(root)
        first = (root / "src/contracts/route-tree.json").read_text()
        write_route_tree_contract(root)
        assert (root / "src/contracts/route-tree.json").read_text() == first

"""Nested pages must say where they are and offer a way up.

Measured across 173 generated apps: 3365 page schemas sit at depth >= 2
and only 6.3% carry a Breadcrumb. The component has existed in the
library the whole time — nothing was emitting it, because no pass knew
the app had a hierarchy to express.

Two things this pass must not do:

* Never link a crumb to a route that doesn't exist. Breadcrumbs built
  by splitting a path produce `/products/[id]` in apps that never
  registered it; a crumb that 404s is worse than no crumb. Ancestors
  come from the route tree, which only returns real routes.
* Never label a crumb with a binding. `{{product.name}}` in a crumb
  renders as literal braces on first paint, so the current-page label
  falls back to something static.

Pagination is deliberately NOT here: Table paginates internally
(pageSize defaults to 25, its own pager renders once rows exceed it),
so emitting a standalone Pagination node would be dead chrome.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.page_nav import apply_page_nav


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _mk(tmp_path: Path, *, routes: list[str], schemas: dict[str, dict]) -> Path:
    root = tmp_path / "app"
    reg = ",\n".join(f'  "{r}": () => import("./x.json")' for r in routes)
    _write(root, "src/schemas/registry.ts", "export const s = {\n" + reg + "\n};\n")
    for rel, doc in schemas.items():
        _write(root, f"src/schemas/{rel}", json.dumps(doc))
    return root


def _page(children: list | None = None) -> dict:
    # `children is not None`, not `children or ...` — an explicitly empty
    # list means "this page has no heading", which is exactly the case the
    # dynamic-leaf fallback test needs.
    kids = children if children is not None else [
        {"type": "Heading", "props": {"text": "Hello"}}]
    return {"root": {"type": "Stack", "children": kids}}


def _read(root: Path, rel: str) -> dict:
    return json.loads((root / "src/schemas" / rel).read_text())


def _crumb(root: Path, rel: str) -> dict | None:
    kids = _read(root, rel)["root"]["children"]
    return next((k for k in kids if k.get("type") == "Breadcrumb"), None)


class TestBreadcrumbIsInjectedOnNestedPages:
    def test_a_nested_page_gets_one(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/new"],
                   schemas={"products/new.json": _page()})
        apply_page_nav(root)
        assert _crumb(root, "products/new.json") is not None

    def test_it_is_the_first_child(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/new"],
                   schemas={"products/new.json": _page()})
        apply_page_nav(root)
        assert _read(root, "products/new.json")["root"]["children"][0]["type"] == "Breadcrumb"

    def test_top_level_pages_get_none(self, tmp_path):
        """`/products` has nowhere to go up to."""
        root = _mk(tmp_path, routes=["/products"], schemas={"products.json": _page()})
        apply_page_nav(root)
        assert _crumb(root, "products.json") is None

    def test_auth_pages_are_skipped(self, tmp_path):
        root = _mk(tmp_path, routes=["/auth", "/auth/login"],
                   schemas={"auth/login.json": _page()})
        apply_page_nav(root)
        assert _crumb(root, "auth/login.json") is None


class TestCrumbsPointAtRealRoutes:
    def test_ancestor_href_is_the_parent_route(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/new"],
                   schemas={"products/new.json": _page()})
        apply_page_nav(root)
        items = _crumb(root, "products/new.json")["props"]["items"]
        assert items[0] == {"label": "Products", "href": "/products"}

    def test_a_missing_intermediate_is_skipped_not_invented(self, tmp_path):
        """No `/products/[id]` route — the trail must not link to it."""
        root = _mk(tmp_path, routes=["/products", "/products/[id]/edit"],
                   schemas={"products/[id]/edit.json": _page()})
        apply_page_nav(root)
        hrefs = [i.get("href") for i in _crumb(root, "products/[id]/edit.json")["props"]["items"]]
        assert "/products/[id]" not in hrefs
        assert "/products" in hrefs

    def test_no_real_ancestor_means_no_breadcrumb(self, tmp_path):
        root = _mk(tmp_path, routes=["/a/b/c"], schemas={"a/b/c.json": _page()})
        apply_page_nav(root)
        assert _crumb(root, "a/b/c.json") is None

    def test_the_last_crumb_has_no_href(self, tmp_path):
        """The current page is not a link."""
        root = _mk(tmp_path, routes=["/products", "/products/new"],
                   schemas={"products/new.json": _page()})
        apply_page_nav(root)
        assert "href" not in _crumb(root, "products/new.json")["props"]["items"][-1]


class TestLabels:
    def test_current_page_uses_its_heading(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/new"],
                   schemas={"products/new.json": _page(
                       [{"type": "Heading", "props": {"text": "Add Product"}}])})
        apply_page_nav(root)
        assert _crumb(root, "products/new.json")["props"]["items"][-1]["label"] == "Add Product"

    def test_a_binding_heading_is_never_used_as_a_label(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/[id]"],
                   schemas={"products/[id].json": _page(
                       [{"type": "Heading", "props": {"text": "{{product.name}}"}}])})
        apply_page_nav(root)
        label = _crumb(root, "products/[id].json")["props"]["items"][-1]["label"]
        assert "{{" not in label

    def test_a_dynamic_leaf_falls_back_to_details(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/[id]"],
                   schemas={"products/[id].json": _page([])})
        apply_page_nav(root)
        assert _crumb(root, "products/[id].json")["props"]["items"][-1]["label"] == "Details"

    def test_hyphenated_segments_are_humanised(self, tmp_path):
        root = _mk(tmp_path, routes=["/purchase-orders", "/purchase-orders/new"],
                   schemas={"purchase-orders/new.json": _page([])})
        apply_page_nav(root)
        assert _crumb(root, "purchase-orders/new.json")["props"]["items"][0]["label"] \
            == "Purchase Orders"


class TestDynamicAncestorLabels:
    """A crumb reading `[id]` is worse than the raw route it came from.

    `/categories/[id]/edit` has `/categories/[id]` as a real ancestor, and
    naive humanising labelled that crumb `[id]` — 19 of them across the
    sample corpus. The record detail page is "Category", derived from the
    collection segment above it.
    """

    def test_a_dynamic_ancestor_is_labelled_from_its_collection(self, tmp_path):
        root = _mk(tmp_path, routes=["/categories", "/categories/[id]",
                                     "/categories/[id]/edit"],
                   schemas={"categories/[id]/edit.json": _page([])})
        apply_page_nav(root)
        labels = [i["label"] for i in _crumb(root, "categories/[id]/edit.json")["props"]["items"]]
        assert "[id]" not in labels
        assert labels[:2] == ["Categories", "Category"]

    def test_express_style_colon_params_are_also_dynamic(self, tmp_path):
        """Some routes ship `:id` rather than `[id]`."""
        root = _mk(tmp_path, routes=["/admins", "/admins/:id", "/admins/:id/edit"],
                   schemas={"admins/:id/edit.json": _page([])})
        apply_page_nav(root)
        labels = [i["label"] for i in _crumb(root, "admins/:id/edit.json")["props"]["items"]]
        assert ":id" not in labels
        assert labels[1] == "Admin"

    def test_no_crumb_label_is_ever_a_raw_param(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/[id]",
                                     "/products/[id]/edit"],
                   schemas={"products/[id]/edit.json": _page([])})
        apply_page_nav(root)
        for i in _crumb(root, "products/[id]/edit.json")["props"]["items"]:
            assert "[" not in i["label"] and ":" not in i["label"]


class TestIdempotencyAndSafety:
    def test_rerun_does_not_duplicate(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/new"],
                   schemas={"products/new.json": _page()})
        apply_page_nav(root)
        apply_page_nav(root)
        kids = _read(root, "products/new.json")["root"]["children"]
        assert sum(1 for k in kids if k.get("type") == "Breadcrumb") == 1

    def test_an_authored_breadcrumb_is_left_alone(self, tmp_path):
        mine = {"type": "Breadcrumb", "props": {"items": [{"label": "Custom"}]}}
        root = _mk(tmp_path, routes=["/products", "/products/new"],
                   schemas={"products/new.json": _page([mine])})
        apply_page_nav(root)
        assert _crumb(root, "products/new.json")["props"]["items"] == [{"label": "Custom"}]

    def test_report_is_written(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/new"],
                   schemas={"products/new.json": _page()})
        apply_page_nav(root)
        rep = json.loads((root / "contracts" / "page-nav.json").read_text())
        assert rep["summary"]["breadcrumbs_injected"] == 1

    def test_empty_app_no_crash(self, tmp_path):
        assert apply_page_nav(tmp_path / "nope")["findings"] == []

    def test_malformed_schema_is_skipped(self, tmp_path):
        root = _mk(tmp_path, routes=["/products", "/products/new"],
                   schemas={"products/new.json": _page()})
        _write(root, "src/schemas/broken.json", "{not json")
        apply_page_nav(root)
        assert _crumb(root, "products/new.json") is not None

"""The nav layer must read the ROUTE TREE, not the schema directory.

Measured on the 173-app corpus: 921 real `[id]` detail routes and 203
three-segment routes exist on disk under src/app — but only ONE page
schema carries a dynamic route. Every page-nav contract we have is
keyed to src/schemas/*.json, so:

  - page_anatomy's back-affordance rule ("a detail page without a way
    back is a dead end") iterates schemas and therefore fires on ~1 of
    921 detail routes;
  - 0 of 86 nested schema routes carry a Breadcrumb;
  - 1 of 714 list pages carries Pagination.

The components all exist in the library. The layer that would emit
them believes the app is 1365 flat top-level pages, because detail
pages are template-injected .tsx (runtime_injector._inject_task_inbox_pages)
or rendered through the [...slug] catch-all — neither of which lands
in src/schemas.

This module is the missing input: one tree that knows the app has
depth, unioned from all three sources that actually define routes.

The rule that matters most: `ancestors()` returns only routes that
EXIST. A breadcrumb built from string-splitting a path links to
`/products/[id]` even when no such route is registered — a crumb that
404s is worse than no crumb.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.route_tree import build_route_tree


def _app(tmp_path: Path, pages: list[str], *, registry: list[str] | None = None,
         schemas: dict[str, dict] | None = None) -> Path:
    """Materialize a generated-app skeleton on disk."""
    for rel in pages:
        p = tmp_path / "src" / "app" / rel / "page.tsx"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("export default function P(){return null}", encoding="utf-8")
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True, exist_ok=True)
    if registry is not None:
        body = ",\n".join(f'  "{r}": () => import("./x.json")' for r in registry)
        (sdir / "registry.ts").write_text(
            "export const routesRegistry = {\n" + body + "\n};", encoding="utf-8")
    for name, doc in (schemas or {}).items():
        (sdir / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


class TestSourcesAreUnioned:
    """Routes live in three places; the tree must see all of them."""

    def test_app_dir_pages_are_found(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["products", "products/[id]"]))
        assert "/products" in t.nodes
        assert "/products/[id]" in t.nodes

    def test_registry_routes_are_found(self, tmp_path):
        t = build_route_tree(_app(tmp_path, [], registry=["/bills", "/bills/new"]))
        assert {"/bills", "/bills/new"} <= set(t.nodes)

    def test_schema_route_field_is_found(self, tmp_path):
        t = build_route_tree(_app(tmp_path, [], schemas={
            "login": {"route": "/login", "root": {}}}))
        assert "/login" in t.nodes

    def test_a_route_in_two_sources_appears_once(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["orders"], registry=["/orders"]))
        assert len([r for r in t.nodes if r == "/orders"]) == 1


class TestNextConventionsAreStripped:
    """src/app carries framework scaffolding that is not route structure."""

    def test_route_groups_do_not_become_segments(self, tmp_path):
        """`(dashboard)/products` is served at `/products`."""
        t = build_route_tree(_app(tmp_path, ["(dashboard)/products"]))
        assert "/products" in t.nodes
        assert not any("(" in r for r in t.nodes)

    def test_nested_route_groups_are_stripped(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["(app)/(admin)/settings"]))
        assert "/settings" in t.nodes

    def test_catch_all_is_not_a_route(self, tmp_path):
        """`[...slug]` is the schema-page renderer, not a destination."""
        t = build_route_tree(_app(tmp_path, ["[...slug]", "products"]))
        assert "/[...slug]" not in t.nodes
        assert "/products" in t.nodes

    def test_api_handlers_are_not_pages(self, tmp_path):
        (tmp_path / "src/app/api/data").mkdir(parents=True)
        (tmp_path / "src/app/api/data/route.ts").write_text("export {}", encoding="utf-8")
        t = build_route_tree(_app(tmp_path, ["products"]))
        assert not any(r.startswith("/api") for r in t.nodes)

    def test_a_leading_dynamic_segment_is_infrastructure_not_a_page(self, tmp_path):
        """`/[entity]` and `/[entity]/[id]` are the generic schema router.

        Real apps ship these alongside [...slug] to render any entity's
        list/detail from a schema. They are parameterised by entity NAME,
        so they are not destinations in the IA — treating them as detail
        pages made page_anatomy report three phantom dead ends per app.
        """
        t = build_route_tree(_app(tmp_path, ["[entity]", "[entity]/[id]",
                                             "products", "products/[id]"]))
        assert "/[entity]" not in t.nodes
        assert "/[entity]/[id]" not in t.nodes
        assert {"/products", "/products/[id]"} <= set(t.nodes)

    def test_a_dynamic_segment_below_a_real_one_is_kept(self, tmp_path):
        """Only the LEADING segment signals a generic renderer."""
        t = build_route_tree(_app(tmp_path, ["products/[id]/[tab]"]))
        assert "/products/[id]/[tab]" in t.nodes

    def test_private_underscore_folders_are_skipped(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["_components/widget", "products"]))
        assert "/products" in t.nodes
        assert not any(r.startswith("/_") for r in t.nodes)


class TestHierarchy:
    def test_parent_is_the_route_above(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["products", "products/[id]"]))
        assert t.nodes["/products/[id]"].parent == "/products"

    def test_top_level_has_no_parent(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["products"]))
        assert t.nodes["/products"].parent is None

    def test_depth_counts_segments(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["products/[id]/edit"]))
        assert t.nodes["/products/[id]/edit"].depth == 3

    def test_children_are_listed(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["products", "products/[id]", "products/new"]))
        assert set(t.children("/products")) == {"/products/[id]", "/products/new"}


class TestAncestorsOnlyReturnsRealRoutes:
    """The rule that keeps breadcrumbs from 404ing."""

    def test_ancestors_are_ordered_root_first(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["products", "products/[id]", "products/[id]/edit"]))
        assert t.ancestors("/products/[id]/edit") == ["/products", "/products/[id]"]

    def test_a_missing_intermediate_is_SKIPPED_not_invented(self, tmp_path):
        """No `/products/[id]` route exists — the crumb must not link to it."""
        t = build_route_tree(_app(tmp_path, ["products", "products/[id]/edit"]))
        assert t.ancestors("/products/[id]/edit") == ["/products"]

    def test_parent_falls_back_to_nearest_EXISTING_ancestor(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["products", "products/[id]/edit"]))
        assert t.nodes["/products/[id]/edit"].parent == "/products"

    def test_no_real_ancestor_means_no_crumbs(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["a/b/c"]))
        assert t.ancestors("/a/b/c") == []

    def test_unknown_route_yields_no_ancestors(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["products"]))
        assert t.ancestors("/nope") == []


class TestKindClassification:
    """Each nav rule keys off kind, so kind must be right."""

    @pytest.mark.parametrize("rel,route,kind", [
        ("products", "/products", "list"),
        ("products/[id]", "/products/[id]", "detail"),
        ("products/new", "/products/new", "create"),
        ("products/[id]/edit", "/products/[id]/edit", "edit"),
        ("login", "/login", "auth"),
        ("signup", "/signup", "auth"),
    ])
    def test_kinds(self, tmp_path, rel, route, kind):
        t = build_route_tree(_app(tmp_path, [rel]))
        assert t.nodes[route].kind == kind

    def test_root_is_its_own_kind(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["."]))
        assert t.nodes["/"].kind == "root"

    def test_sub_resource_of_a_detail_page(self, tmp_path):
        """`/sessions/[id]/votes` is a child collection, not a detail."""
        t = build_route_tree(_app(tmp_path, ["sessions/[id]/votes"]))
        assert t.nodes["/sessions/[id]/votes"].kind == "sub"

    def test_dynamic_flag(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["products/[id]", "products"]))
        assert t.nodes["/products/[id]"].dynamic is True
        assert t.nodes["/products"].dynamic is False


class TestQueryHelpers:
    def test_detail_routes(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["products", "products/[id]", "orders/[id]"]))
        assert set(t.detail_routes()) == {"/products/[id]", "/orders/[id]"}

    def test_nested_routes_excludes_top_level(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["products", "products/[id]"]))
        assert set(t.nested_routes()) == {"/products/[id]"}

    def test_schema_backed_routes_are_marked(self, tmp_path):
        t = build_route_tree(_app(tmp_path, ["products"],
                                  schemas={"products": {"route": "/products", "root": {}}}))
        assert t.nodes["/products"].schema_name == "products"

    def test_template_tsx_routes_are_marked_as_such(self, tmp_path):
        """tasks/[id] ships as hand-written .tsx — no schema to patch."""
        t = build_route_tree(_app(tmp_path, ["tasks/[id]"]))
        assert t.nodes["/tasks/[id]"].schema_name is None
        assert t.nodes["/tasks/[id]"].has_page_file is True


class TestDegenerate:
    def test_missing_app_dir(self, tmp_path):
        assert build_route_tree(tmp_path).nodes == {}

    def test_children_of_unknown_route(self, tmp_path):
        assert build_route_tree(tmp_path).children("/nope") == []

    def test_malformed_schema_is_skipped(self, tmp_path):
        root = _app(tmp_path, ["products"])
        (root / "src" / "schemas" / "broken.json").write_text("{not json", encoding="utf-8")
        assert "/products" in build_route_tree(root).nodes

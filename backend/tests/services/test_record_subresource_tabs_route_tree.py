"""Sub-resource tabs must be discovered from real routes, not nav-flow.

The pass makes an aggregate root a hub: a detail page whose route has
static nested children (`/events/[id]/sessions`, `/events/[id]/agenda`)
gets a tab row linking to each. It found those children by scanning
`nav-flow.json` and matching `^/{slug}/\\[id\\]/(\\w+)$`.

Measured on the corpus: 13 aggregate roots have >= 2 sub-resources and 8
of them have a patchable detail schema — but only 2 apps ever got a tab
row. nav-flow is a derived persona/job view, not the route inventory, so
the children were frequently absent from it (and the pass returns early
outright when nav-flow.json is unreadable). The routes were always there
in src/app and the registry.

Also pinned here: the `:id` param flavour. Some emitted routes use
`/admins/:id/...` rather than `[id]`, and a regex hardcoded to `\\[id\\]`
silently skipped every one.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.record_subresource_tabs import inject_subresource_tabs


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _detail_schema() -> dict:
    return {"dataSources": [{"name": "record", "entity": "Event", "op": "get"}],
            "root": {"type": "Stack", "children": [
                {"type": "Heading", "props": {"text": "Event"}},
                {"type": "Card", "children": []}]}}


def _mk(tmp_path: Path, *, routes: list[str], detail_rel: str,
        nav_flow: dict | None = None) -> Path:
    root = tmp_path / "app"
    reg = ",\n".join(f'  "{r}": () => import("./x.json")' for r in routes)
    _write(root, "src/schemas/registry.ts", "export const s = {\n" + reg + "\n};\n")
    _write(root, f"src/schemas/{detail_rel}", json.dumps(_detail_schema()))
    if nav_flow is not None:
        _write(root, "src/contracts/nav-flow.json", json.dumps(nav_flow))
    return root


def _tab_row(root: Path, detail_rel: str) -> dict | None:
    doc = json.loads((root / "src/schemas" / detail_rel).read_text())
    for c in doc["root"]["children"]:
        if isinstance(c, dict) and (c.get("props") or {}).get("data-subresource-tabs"):
            return c
    return None


def _labels(row: dict) -> list[str]:
    return [(c.get("props") or {}).get("label") for c in row["children"]]


class TestDiscoveryDoesNotDependOnNavFlow:
    def test_children_are_found_with_no_nav_flow_at_all(self, tmp_path):
        """The old pass returned early when nav-flow.json was unreadable."""
        root = _mk(tmp_path, detail_rel="events/[id].json", routes=[
            "/events", "/events/[id]",
            "/events/[id]/sessions", "/events/[id]/agenda"])
        inject_subresource_tabs(str(root))
        row = _tab_row(root, "events/[id].json")
        assert row is not None
        assert _labels(row) == ["Overview", "Agenda", "Sessions"]

    def test_children_absent_from_nav_flow_are_still_found(self, tmp_path):
        root = _mk(tmp_path, detail_rel="events/[id].json",
                   routes=["/events", "/events/[id]",
                           "/events/[id]/sessions", "/events/[id]/agenda"],
                   nav_flow={"pages": [{"route": "/events"}]})
        inject_subresource_tabs(str(root))
        assert _tab_row(root, "events/[id].json") is not None

    def test_a_single_child_is_still_not_a_workspace(self, tmp_path):
        root = _mk(tmp_path, detail_rel="events/[id].json",
                   routes=["/events", "/events/[id]", "/events/[id]/sessions"])
        inject_subresource_tabs(str(root))
        assert _tab_row(root, "events/[id].json") is None

    def test_create_and_edit_are_actions_not_workspaces(self, tmp_path):
        root = _mk(tmp_path, detail_rel="events/[id].json", routes=[
            "/events", "/events/[id]", "/events/[id]/edit",
            "/events/[id]/new", "/events/[id]/agenda", "/events/[id]/sessions"])
        inject_subresource_tabs(str(root))
        labels = _labels(_tab_row(root, "events/[id].json"))
        assert "Edit" not in labels and "New" not in labels


class TestOrdering:
    """nav-flow order is authored intent; tree-only extras are appended."""

    def test_nav_flow_declaration_order_wins(self, tmp_path):
        root = _mk(tmp_path, detail_rel="events/[id].json",
                   routes=["/events", "/events/[id]"],
                   nav_flow={"pages": [
                       {"route": "/events/[id]/sessions"},
                       {"route": "/events/[id]/attendees"},
                       {"route": "/events/[id]/check-in"}]})
        inject_subresource_tabs(str(root))
        assert _labels(_tab_row(root, "events/[id].json")) == [
            "Overview", "Sessions", "Attendees", "Check In"]

    def test_tree_only_children_are_appended_after_declared_ones(self, tmp_path):
        root = _mk(tmp_path, detail_rel="events/[id].json",
                   routes=["/events", "/events/[id]",
                           "/events/[id]/agenda", "/events/[id]/sessions"],
                   nav_flow={"pages": [{"route": "/events/[id]/sessions"}]})
        inject_subresource_tabs(str(root))
        assert _labels(_tab_row(root, "events/[id].json")) == [
            "Overview", "Sessions", "Agenda"]


class TestColonParamRoutes:
    def test_express_style_detail_routes_are_handled(self, tmp_path):
        root = _mk(tmp_path, detail_rel="admins/:id.json", routes=[
            "/admins", "/admins/:id",
            "/admins/:id/roles", "/admins/:id/audit"])
        inject_subresource_tabs(str(root))
        row = _tab_row(root, "admins/:id.json")
        assert row is not None
        assert _labels(row) == ["Overview", "Audit", "Roles"]

    def test_navigate_targets_interpolate_the_record_id(self, tmp_path):
        root = _mk(tmp_path, detail_rel="admins/:id.json", routes=[
            "/admins", "/admins/:id",
            "/admins/:id/roles", "/admins/:id/audit"])
        inject_subresource_tabs(str(root))
        navs = [(c.get("props") or {}).get("navigate")
                for c in _tab_row(root, "admins/:id.json")["children"]]
        assert navs[0] == "/admins/{{record.id}}"
        assert "/admins/{{record.id}}/roles" in navs


class TestUnchangedGuarantees:
    def test_rerun_replaces_rather_than_stacks(self, tmp_path):
        root = _mk(tmp_path, detail_rel="events/[id].json", routes=[
            "/events", "/events/[id]",
            "/events/[id]/sessions", "/events/[id]/agenda"])
        inject_subresource_tabs(str(root))
        inject_subresource_tabs(str(root))
        doc = json.loads((root / "src/schemas/events/[id].json").read_text())
        rows = [c for c in doc["root"]["children"]
                if isinstance(c, dict) and (c.get("props") or {}).get("data-subresource-tabs")]
        assert len(rows) == 1

    def test_row_sits_above_the_first_content_surface(self, tmp_path):
        root = _mk(tmp_path, detail_rel="events/[id].json", routes=[
            "/events", "/events/[id]",
            "/events/[id]/sessions", "/events/[id]/agenda"])
        inject_subresource_tabs(str(root))
        kids = json.loads((root / "src/schemas/events/[id].json").read_text())["root"]["children"]
        types = [c.get("type") for c in kids]
        assert types.index("Row") < types.index("Card")

    def test_no_detail_schema_means_no_crash(self, tmp_path):
        root = tmp_path / "app"
        _write(root, "src/schemas/registry.ts",
               'export const s = {\n  "/events/[id]/a": () => import("./x.json"),\n'
               '  "/events/[id]/b": () => import("./x.json")\n};\n')
        assert inject_subresource_tabs(str(root))["tabs"] == 0

    def test_empty_app_no_crash(self, tmp_path):
        assert inject_subresource_tabs(str(tmp_path / "nope"))["tabs"] == 0

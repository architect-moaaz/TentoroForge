"""`navigation.tree` reaches the app's rail, grouped, through `shell.json`.

The scaffold's layout builds its sidebar from `shell.json` — `findSideNav`
walks the file for a `SideNav` node and reads `props.groups` — and falls back
to a flat list of page titles from nav-flow only when that file is absent. No
Blueprint projection wrote it, so every application got the fallback, and
when a connected design's own groups arrived in `navigation.tree` they had
nowhere to go: the rail stayed the generic seven titles.

Written only for a grouped tree: a flat tree IS the fallback, and writing it
too would be a second representation of one fact.
"""
import json

from services.blueprint.projection import project_shell

PAGES = [{"id": "PAGE-002", "route": "/"}, {"id": "PAGE-003", "route": "/front-desk"},
         {"id": "PAGE-005", "route": "/cases/new"}]
TREE = [
    {"label": "Overview", "children": [
        {"label": "Dashboard", "page": "PAGE-002", "icon": "layout-dashboard"},
        {"label": "Front Desk", "page": "PAGE-003"}]},
    {"label": "Cases", "children": [
        {"label": "New Case", "page": "PAGE-005"},
        {"label": "Guest Self-Service"}]},               # drawn, no page yet
]


def _find_sidenav(node):
    if isinstance(node, dict):
        if node.get("type") == "SideNav":
            return node
        for c in node.get("children") or []:
            hit = _find_sidenav(c)
            if hit:
                return hit
    return None


def test_a_grouped_tree_becomes_the_rail(tmp_path):
    doc = {"application": {"name": "Criterion"}, "pages": PAGES,
           "navigation": {"style": "sidebar", "tree": TREE}}
    out = project_shell(doc, tmp_path)
    assert out["files"] == ["src/schemas/shell.json"] and out["groups"] == 2
    shell = json.loads((tmp_path / "src/schemas/shell.json").read_text())
    nav = _find_sidenav(shell)
    assert nav is not None, "the layout's walk would not find a SideNav"
    assert shell["frame"] == "sidebar"
    groups = nav["props"]["groups"]
    assert [g["label"] for g in groups] == ["Overview", "Cases"]
    assert groups[0]["items"][0] == {"label": "Dashboard", "route": "/", "icon": "layout-dashboard"}


def test_a_destination_without_a_page_is_kept_route_less(tmp_path):
    """Visible in the rail rather than silently dropped (§49)."""
    doc = {"application": {"name": "X"}, "pages": PAGES,
           "navigation": {"style": "sidebar", "tree": TREE}}
    project_shell(doc, tmp_path)
    shell = json.loads((tmp_path / "src/schemas/shell.json").read_text())
    cases = _find_sidenav(shell)["props"]["groups"][1]["items"]
    assert {"label": "Guest Self-Service"} in cases


def test_a_flat_tree_writes_nothing(tmp_path):
    """The fallback already renders it; a second copy would drift."""
    doc = {"application": {"name": "X"}, "pages": PAGES,
           "navigation": {"tree": [{"label": "Home", "page": "PAGE-002"}]}}
    out = project_shell(doc, tmp_path)
    assert out["files"] == [] and not (tmp_path / "src/schemas/shell.json").exists()


def test_no_navigation_writes_nothing(tmp_path):
    assert project_shell({"pages": PAGES}, tmp_path)["files"] == []


def test_routes_resolve_through_page_ids(tmp_path):
    """A rename of a route in `pages` must not strand the rail."""
    doc = {"application": {"name": "X"},
           "pages": [{"id": "PAGE-002", "route": "/home-renamed"}],
           "navigation": {"tree": [{"label": "G", "children": [{"label": "Home", "page": "PAGE-002"}]}]}}
    project_shell(doc, tmp_path)
    shell = json.loads((tmp_path / "src/schemas/shell.json").read_text())
    assert _find_sidenav(shell)["props"]["groups"][0]["items"][0]["route"] == "/home-renamed"

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


def test_a_flat_tree_still_writes_the_shell(tmp_path):
    """A flat rail is still a rail. This used to write nothing and leave the
    layout's fallback to render it, and a one-screen application then had no
    shell file at all — and the root page, which reads the initial route off
    the shell, failed to compile."""
    doc = {"application": {"name": "X"}, "pages": PAGES,
           "navigation": {"tree": [{"label": "Home", "page": "PAGE-002"}]}}
    out = project_shell(doc, tmp_path)
    assert out["files"] == ["src/schemas/shell.json"]
    shell = json.loads((tmp_path / "src/schemas/shell.json").read_text())
    assert shell["children"][0]["props"]["groups"][0]["label"] == "Home"


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


# ── a dynamic route is not a rail destination ────────────────────────────────
#
# `/rentals/[id]/return` is reached through a row/action that fills a concrete
# id, never from the rail: Next's <Link> refuses a literal "[id]" href ("Dynamic
# href … not supported"), and landing there passes "[id]" to the DB as a uuid.

def test_a_dynamic_route_is_dropped_from_the_rail_and_initial(tmp_path):
    doc = {
        "application": {"name": "Test Gen 2"},
        "pages": [
            {"id": "P-RET", "route": "/rentals/[id]/return"},
            {"id": "P-NEW", "route": "/support-requests/new"},
        ],
        "navigation": {"style": "sidebar", "tree": [
            {"label": "Return Rental", "page": "P-RET"},
            {"label": "New Support Request", "page": "P-NEW"},
        ]},
    }
    project_shell(doc, tmp_path)
    shell = json.loads((tmp_path / "src/schemas/shell.json").read_text())
    routes = [g.get("route") for g in _find_sidenav(shell)["props"]["groups"]]
    assert "/rentals/[id]/return" not in routes
    assert routes == ["/support-requests/new"]
    # the landing route is concrete, never the dynamic one
    assert shell.get("initialRoute") == "/support-requests/new"


def test_a_page_less_destination_is_still_kept_route_less(tmp_path):
    # Regression guard: the dynamic-route drop must NOT also drop a §49
    # destination that simply has no page yet.
    doc = {"application": {"name": "X"},
           "pages": [{"id": "P1", "route": "/rentals/[id]/return"}],
           "navigation": {"style": "sidebar", "tree": [
               {"label": "Coming soon"},                 # no page — kept
               {"label": "Return", "page": "P1"},        # dynamic — dropped
           ]}}
    project_shell(doc, tmp_path)
    shell = json.loads((tmp_path / "src/schemas/shell.json").read_text())
    groups = _find_sidenav(shell)["props"]["groups"]
    labels = [g.get("label") for g in groups]
    assert "Coming soon" in labels
    assert all(g.get("route") != "/rentals/[id]/return" for g in groups)

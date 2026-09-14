import json
from pathlib import Path


def test_the_shell_names_where_the_application_opens(tmp_path):
    """The scaffold's root page redirected to a hard-coded /home that no
    application has; the shell now carries the Blueprint's initial route, and
    falls back to the rail's first destination when the Blueprint says none."""
    from services.blueprint.projection import project_shell
    doc = {"application": {"name": "PLC"}, "pages": [{"id": "PAGE-001", "route": "/dashboard", "name": "Dashboard"}],
           "navigation": {"style": "sidebar", "initialRoute": {"default": "/dashboard"},
                          "tree": [{"label": "Overview", "children": [{"label": "Dashboard", "page": "PAGE-001", "href": "/dashboard"}]}]}}
    project_shell(doc, tmp_path)
    shell = json.loads((Path(tmp_path) / "src" / "schemas" / "shell.json").read_text())
    assert shell["initialRoute"] == "/dashboard"
    doc["navigation"]["initialRoute"] = {"default": "/home"}
    project_shell(doc, tmp_path)
    shell = json.loads((Path(tmp_path) / "src" / "schemas" / "shell.json").read_text())
    assert shell["initialRoute"] == "/dashboard"


def test_a_one_screen_application_still_gets_its_shell(tmp_path):
    from services.blueprint.projection import project_shell
    doc = {"application": {"name": "PLC"}, "pages": [{"id": "PAGE-002", "route": "/", "name": "لوحة التحكم"}],
           "navigation": {"style": "sidebar", "initialRoute": {"default": "/"},
                          "tree": [{"label": "لوحة التحكم", "page": "PAGE-002", "icon": "layout-dashboard"}]}}
    out = project_shell(doc, tmp_path)
    shell = json.loads((Path(tmp_path) / "src" / "schemas" / "shell.json").read_text())
    assert out["files"] == ["src/schemas/shell.json"]
    assert shell["children"][0]["props"]["groups"][0]["label"] == "لوحة التحكم"
    assert shell["initialRoute"] == "/"


def test_a_dynamic_initial_route_falls_back_to_a_concrete_one(tmp_path):
    """A dynamic `initialRoute` cannot be a landing page — no id to fill. The
    shell rejects it and opens on the first concrete rail destination instead."""
    from services.blueprint.projection import project_shell
    doc = {"application": {"name": "Test Gen 2"},
           "pages": [{"id": "P-RET", "route": "/rentals/[id]/return"},
                     {"id": "P-NEW", "route": "/support-requests/new"}],
           "navigation": {"style": "sidebar",
                          "initialRoute": {"default": "/rentals/[id]/return"},
                          "tree": [{"label": "Return", "page": "P-RET"},
                                   {"label": "New Request", "page": "P-NEW"}]}}
    project_shell(doc, tmp_path)
    shell = json.loads((Path(tmp_path) / "src" / "schemas" / "shell.json").read_text())
    assert shell["initialRoute"] == "/support-requests/new"


def test_the_gated_entry_is_never_a_dynamic_route(tmp_path):
    """A page flagged `entry` on a dynamic route cannot be the login redirect;
    the gated entry falls back to the first concrete gated route."""
    from services.blueprint.projection import project_nav_flow
    doc = {"application": {"name": "Test Gen 2"}, "roles": [{"id": "R1", "name": "Member"}],
           "pages": [
               {"id": "P-RET", "route": "/rentals/[id]/return", "access": "authenticated",
                "entry": True, "users": ["R1"]},
               {"id": "P-NEW", "route": "/support-requests/new", "access": "authenticated",
                "users": ["R1"]},
           ]}
    project_nav_flow(doc, tmp_path)
    nav = json.loads((Path(tmp_path) / "src" / "contracts" / "nav-flow.json").read_text())
    assert "[" not in (nav.get("gatedEntry") or "")
    assert nav["gatedEntry"] == "/support-requests/new"
    assert nav["entries"].get("authenticated") == "/support-requests/new"

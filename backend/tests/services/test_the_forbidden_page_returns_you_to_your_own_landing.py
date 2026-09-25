"""The 403 page's "Return to" link goes where the signed-in person lands.

It pointed every role at one route, taken from the app's first page. On
nlwtcyz5 that page was the doctor's, so an administrator or a parent pressing
"Return" arrived straight back on the 403 — the page reviewer recorded the
link as doing nothing. The scaffold now inlines the per-role landing map the
root redirect already reads (nav-flow's ``initialFor``) and falls back to the
signed-in front door (``entries.authenticated``).
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from services.app_emitter import (
    _TEMPLATE_DIR, derive_root_redirect, emit_standalone_app, landing_for,
)
from services.blueprint import assembly
from services.blueprint.projection import project_nav_flow
from services.edge_page_customizer import customize_edge_pages

_FORBIDDEN = "src/app/forbidden.tsx"


def _three_role_doc() -> dict:
    return {
        "application": {"name": "Clinic Companion"},
        "roles": [{"id": "ROLE-001", "name": "Admin"},
                  {"id": "ROLE-002", "name": "Doctor"},
                  {"id": "ROLE-003", "name": "Parent"}],
        "navigation": {"style": "sidebar",
                       "initialRoute": {"default": "/", "admin": "/admin",
                                        "doctor": "/doctor", "parent": "/"}},
        "pages": [
            {"id": "PAGE-001", "route": "/doctor", "name": "Doctor Home",
             "access": "role_restricted", "users": ["ROLE-002"]},
            {"id": "PAGE-002", "route": "/admin", "name": "Admin Home",
             "access": "role_restricted", "users": ["ROLE-001"]},
            {"id": "PAGE-003", "route": "/", "name": "Parent Home",
             "access": "authenticated", "entry": True, "users": ["ROLE-003"]},
            {"id": "PAGE-004", "route": "/children/[id]", "name": "Child",
             "access": "authenticated"},
        ],
    }


def _lay_down_forbidden(app: Path) -> Path:
    dst = app / _FORBIDDEN
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_TEMPLATE_DIR / _FORBIDDEN, dst)
    return dst


def _landing_map(page: str) -> dict[str, str]:
    body = re.search(r"const LANDING_FOR: Record<string, string> = (\{.*?\});", page, re.S)
    assert body, page
    return json.loads(body.group(1))


def test_a_forbidden_page_links_each_role_to_its_own_route(tmp_path):
    """Blueprint path: `project_nav_flow` projects the per-role map, the
    assembly fills the scaffold from it. Three roles, three landings; the
    fallback is the signed-in front door, never the doctor's page."""
    app = tmp_path / "app"
    doc = _three_role_doc()
    project_nav_flow(doc, app)
    page_path = _lay_down_forbidden(app)

    touched = assembly.interpolate_edge_pages(app, doc)
    page = page_path.read_text()

    assert _FORBIDDEN in touched
    assert _landing_map(page) == {"Admin": "/admin", "Doctor": "/doctor", "Parent": "/"}
    assert 'const LANDING = "/";' in page
    assert "{{" not in page and "}}" not in page
    # the link is computed from the session, not a literal
    assert "<Link href={home}" in page
    assert "await auth()" in page


def test_nav_flow_carries_the_landing_map_by_role_name(tmp_path):
    """The session carries the role's NAME ("Admin"), the Blueprint keys its
    map by whatever the agent wrote ("admin"). The projection resolves one to
    the other; `default` and a key naming no role are not a person's landing."""
    app = tmp_path / "app"
    doc = _three_role_doc()
    doc["navigation"]["initialRoute"]["guest"] = "/welcome"
    project_nav_flow(doc, app)
    nav = json.loads((app / "src" / "contracts" / "nav-flow.json").read_text())
    assert nav["initialFor"] == {"Admin": "/admin", "Doctor": "/doctor", "Parent": "/"}
    assert nav["entries"]["authenticated"] == "/"


def test_a_dynamic_landing_never_reaches_the_link(tmp_path):
    """`/children/[id]` has no id to fill; Next refuses it as an href."""
    app = tmp_path / "app"
    doc = _three_role_doc()
    doc["navigation"]["initialRoute"]["parent"] = "/children/[id]"
    project_nav_flow(doc, app)
    nav = json.loads((app / "src" / "contracts" / "nav-flow.json").read_text())
    assert nav["initialFor"] == {"Admin": "/admin", "Doctor": "/doctor"}


def test_without_a_map_the_page_still_fills_and_falls_back(tmp_path):
    """Before nav-flow exists (the scaffold is laid down at second zero) the
    map is empty and the door is derived from the pages, as it always was.
    Nothing is left unsubstituted: a `{{token}}` in JSX is a ReferenceError."""
    app = tmp_path / "app"
    page_path = _lay_down_forbidden(app)
    assembly.interpolate_edge_pages(app, {
        "application": {"name": "Recruitment Tracker"},
        "pages": [{"route": "/sign-in"}, {"route": "/overview"}],
    })
    page = page_path.read_text()
    assert _landing_map(page) == {}
    assert 'const LANDING = "/overview";' in page
    assert "{{" not in page


def test_the_legacy_emitter_fills_the_same_map(tmp_path):
    """The plan-driven pipeline writes `initialFor` itself; its edge-page
    substituter reads the map through the emitter's one reader."""
    contracts = tmp_path / "src" / "contracts"
    contracts.mkdir(parents=True)
    (contracts / "nav-flow.json").write_text(json.dumps({
        "initialPage": "dashboard",
        "initialFor": {"admin": "/dashboard", "candidate": "/profile", "viewer": "/jobs/[id]"},
        "pages": [{"id": "dashboard", "route": "/dashboard", "shell": True},
                  {"id": "profile", "route": "/profile", "shell": True}],
    }))
    emit_standalone_app(output_dir=tmp_path, project_short_id="x")
    customize_edge_pages(str(tmp_path), app_name="Hiring")
    page = (tmp_path / _FORBIDDEN).read_text()
    assert _landing_map(page) == {"admin": "/dashboard", "candidate": "/profile"}
    assert "{{" not in page


def test_the_root_redirect_reads_the_same_map_and_still_refuses_the_root():
    """One reader, two consumers. The 403 link may send a parent to "/"; the
    root redirect may not, because a redirect from "/" to "/" loops."""
    nav = {"initialFor": {"Admin": "/admin", "Parent": "/", "Child": "/kids/[id]"},
           "pages": [{"id": "admin", "route": "/admin", "shell": True},
                     {"id": "home", "route": "/", "shell": True}]}
    assert landing_for(nav) == {"Admin": "/admin", "Parent": "/"}
    initial_for, _ = derive_root_redirect(nav)
    assert initial_for == {"Admin": "/admin"}

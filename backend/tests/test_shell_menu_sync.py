"""MENU-2 — derive shell.json's sidebar groups from nav-flow.json.

The pre-existing shell menu was a hand-generated array on shell.json
that never updated when refine added new pages, so the sidebar quietly
diverged from the app's real routes. This module makes shell.json a
derivative — one nav-flow, one shell menu."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from services.shell_menu_sync import derive_shell_groups, sync_shell_menu


_FIXTURE = Path("/Users/m/Work/code/poc/design2ui-forge-v3/output/bpxr6hsv")


@pytest.fixture
def app_root(tmp_path: Path) -> Path:
    if not _FIXTURE.exists():
        pytest.skip("bpxr6hsv fixture app not present")
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    shutil.copy(_FIXTURE / "src/contracts/nav-flow.json",
                tmp_path / "src/contracts/nav-flow.json")
    shutil.copy(_FIXTURE / "src/schemas/shell.json",
                tmp_path / "src/schemas/shell.json")
    return tmp_path


# --------------------------------------------------------------------------- #
# derive_shell_groups — the pure step
# --------------------------------------------------------------------------- #

def test_derives_group_per_top_level_route(app_root):
    """Every distinct first-segment route with ``shell=true`` becomes
    exactly one group in the sidebar — /candidates + /candidates/[id]
    + /candidates/apply all collapse to ONE 'Candidates' item."""
    nav_flow = json.load(open(app_root / "src/contracts/nav-flow.json"))
    groups = derive_shell_groups(nav_flow)
    routes = [g["route"] for g in groups]
    assert routes.count("/candidates") == 1
    assert routes.count("/drives") == 1
    assert routes.count("/interviews") == 1
    # Nothing under a detail/edit segment leaks in.
    assert "/candidates/[id]" not in routes
    assert "/drives/[id]/edit" not in routes


def test_excludes_shell_false_pages(app_root):
    """A page with ``shell: false`` (login, signup, error) never appears
    in the sidebar even if its route is top-level."""
    nav_flow = json.load(open(app_root / "src/contracts/nav-flow.json"))
    # Add a synthetic non-shell page.
    nav_flow["pages"].append({
        "id": "login", "route": "/login", "title": "LoginPage", "shell": False,
    })
    groups = derive_shell_groups(nav_flow)
    assert "/login" not in [g["route"] for g in groups]


def test_recruiters_shows_up_after_refine_added_the_pages(app_root):
    """The whole reason we're building this: refine added recruiter
    pages to nav-flow, and the sidebar must reflect them without any
    hand edit."""
    nav_flow = json.load(open(app_root / "src/contracts/nav-flow.json"))
    groups = derive_shell_groups(nav_flow)
    recruit = next((g for g in groups if g["route"] == "/recruiters"), None)
    assert recruit is not None, "Recruiters group missing from derived menu"
    # Icon comes from the label; recruiters → user (people-shaped noun).
    assert recruit["icon"] == "user"


def test_home_route_is_first_when_present(app_root):
    """UX rule — the ``/`` route is always the first item, so the
    sidebar reads left-to-right / top-to-bottom the way users expect."""
    nav_flow = json.load(open(app_root / "src/contracts/nav-flow.json"))
    groups = derive_shell_groups(nav_flow)
    if any(g["route"] == "/" for g in groups):
        assert groups[0]["route"] == "/"


def test_label_is_human_readable_not_pageclass_suffix(app_root):
    """A raw title like 'CandidateListPage' is a codebase name; the
    sidebar label must be the plain noun."""
    nav_flow = json.load(open(app_root / "src/contracts/nav-flow.json"))
    groups = derive_shell_groups(nav_flow)
    cand = next(g for g in groups if g["route"] == "/candidates")
    assert cand["label"] == "Candidates"
    drive = next(g for g in groups if g["route"] == "/drives")
    assert drive["label"] == "Drives"


def test_every_group_has_the_expected_keys(app_root):
    nav_flow = json.load(open(app_root / "src/contracts/nav-flow.json"))
    groups = derive_shell_groups(nav_flow)
    for g in groups:
        assert set(g.keys()) >= {"label", "route", "icon"}, g


# --------------------------------------------------------------------------- #
# sync_shell_menu — read → derive → write
# --------------------------------------------------------------------------- #

def test_sync_replaces_stale_groups_in_shell(app_root):
    """The pre-refine shell.json has a stale menu (missing recruiters).
    After sync, the groups match derive_shell_groups exactly."""
    sync_shell_menu(str(app_root))

    shell = json.load(open(app_root / "src/schemas/shell.json"))
    # Find the groups prop (deep in the tree — the walker in the
    # helper finds it wherever it lives).
    def _find_groups(n):
        if isinstance(n, dict):
            g = n.get("props", {}).get("groups")
            if isinstance(g, list):
                return g
            for v in n.values():
                found = _find_groups(v)
                if found is not None: return found
        elif isinstance(n, list):
            for v in n:
                found = _find_groups(v)
                if found is not None: return found
        return None
    entry = shell.get("root") if isinstance(shell.get("root"), dict) else shell
    groups = _find_groups(entry)
    assert groups is not None, "shell.json has no props.groups"
    routes = [g.get("route") for g in groups if isinstance(g, dict)]
    assert "/recruiters" in routes


def test_sync_is_idempotent(app_root):
    sync_shell_menu(str(app_root))
    first = (app_root / "src/schemas/shell.json").read_text()
    sync_shell_menu(str(app_root))
    second = (app_root / "src/schemas/shell.json").read_text()
    assert first == second


def test_sync_no_nav_flow_is_noop(tmp_path):
    """A project without a nav-flow (fresh scaffold, imported app) is
    ignored — sync doesn't touch shell.json, doesn't crash."""
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "src/schemas/shell.json").write_text('{"root":{"type":"Stack"}}')
    before = (tmp_path / "src/schemas/shell.json").read_text()
    result = sync_shell_menu(str(tmp_path))
    after = (tmp_path / "src/schemas/shell.json").read_text()
    assert before == after
    assert result["synced"] is False


def test_auth_routes_excluded_from_menu_via_hint():
    """Pages listed in nav-flow.auth_routes must never appear as sidebar items,
    even when their page entry has shell=True (planners occasionally slip)."""
    from services.shell_menu_sync import derive_shell_groups
    nav = {
        "pages": [
            {"id": "dashboard", "route": "/dashboard", "shell": True},
            # /signup got shell=True but is listed as an auth route -> skip.
            {"id": "signup",    "route": "/signup",    "shell": True},
        ],
        "auth_routes": ["/signup"],
    }
    routes = [g["route"] for g in derive_shell_groups(nav)]
    assert "/signup" not in routes
    assert "/dashboard" in routes


def test_auth_routes_excluded_by_hardcoded_names():
    """Even when nav-flow.auth_routes is empty, /login and /signup are still
    kept out of the sidebar — the safety net for plans that forgot to mark
    them (real defect on cabin-crew-ATS: /signup with shell=True and no
    auth_routes hint leaked into the menu)."""
    from services.shell_menu_sync import derive_shell_groups
    nav = {
        "pages": [
            {"id": "dashboard", "route": "/dashboard", "shell": True},
            {"id": "signup",    "route": "/signup",    "shell": True},
            {"id": "login",     "route": "/login",     "shell": True},
        ],
        # auth_routes missing on purpose
    }
    routes = [g["route"] for g in derive_shell_groups(nav)]
    assert routes == ["/dashboard"]


def test_dynamic_only_top_route_dropped_from_menu():
    """A top-level route that ONLY exists as a dynamic child (no plain
    landing page) must not appear in the sidebar — clicking it would 404.
    Real cabin-crew-ATS defect: /apply and /pipeline only had
    /apply/[role-id] and /pipeline/[role-id] entries, so the sidebar
    linked to plain /apply which had no schema."""
    from services.shell_menu_sync import derive_shell_groups
    nav = {
        "pages": [
            {"id": "dashboard",       "route": "/dashboard",         "shell": True},
            {"id": "apply-detail",    "route": "/apply/[role-id]",   "shell": True},
            {"id": "pipeline-detail", "route": "/pipeline/[role-id]","shell": True},
            {"id": "drives",          "route": "/drives",            "shell": True},
        ],
    }
    routes = [g["route"] for g in derive_shell_groups(nav)]
    assert routes == ["/dashboard", "/drives"]


def test_dynamic_child_included_when_plain_top_also_exists():
    """When both the plain top and the dynamic child exist, the top stays
    in the sidebar (dedup keeps only the plain top)."""
    from services.shell_menu_sync import derive_shell_groups
    nav = {
        "pages": [
            {"id": "drives",        "route": "/drives",         "shell": True},
            {"id": "drives-detail", "route": "/drives/[id]",    "shell": True},
        ],
    }
    routes = [g["route"] for g in derive_shell_groups(nav)]
    assert routes == ["/drives"]


def test_plan_declared_sidebar_wins(tmp_path):
    """Plan-declared `nav.sidebar` overrides the nav-flow derivation.

    The LLM's grouping ("Candidate" → children, "Recruitment" → children)
    survives verbatim. Bug precursor: sync flattened LLM groups because it
    only knew how to derive from routes; now the plan speaks."""
    import json as _json
    from services.shell_menu_sync import _plan_declared_sidebar

    plan = {
        "nav": {"sidebar": [
            {"label": "Candidate", "icon": "user", "items": [
                {"label": "Dashboard", "route": "/dashboard"},
                {"label": "Roles",     "route": "/roles"},
            ]},
            {"label": "Recruitment", "icon": "briefcase", "items": [
                {"label": "Drives", "route": "/drives"},
            ]},
            # Auth-route slip — must be filtered.
            {"label": "Sign up", "route": "/signup"},
        ]},
    }
    groups = _plan_declared_sidebar(plan)
    assert groups is not None
    labels = [g["label"] for g in groups]
    assert labels == ["Candidate", "Recruitment"]   # /signup filtered out
    assert groups[0]["items"][0] == {"label": "Dashboard", "route": "/dashboard",
                                     "icon": groups[0]["items"][0]["icon"]}


def test_plan_silent_returns_none(tmp_path):
    from services.shell_menu_sync import _plan_declared_sidebar
    assert _plan_declared_sidebar({}) is None
    assert _plan_declared_sidebar({"nav": {}}) is None
    assert _plan_declared_sidebar({"nav": {"sidebar": []}}) is None
    assert _plan_declared_sidebar(None) is None


def test_per_role_sidebar_flattened_to_union(tmp_path):
    """The planner emits sidebar as `[{role, items: [routes]}]`. My reader
    flattens across roles into a first-seen-order deduplicated union so
    the shell.json (single sidebar) is populated correctly. Order:
    admin's items first, then recruiter's new ones, then candidate's."""
    from services.shell_menu_sync import _plan_declared_sidebar

    plan = {
        "nav": {"sidebar": [
            {"role": "admin",     "items": ["/dashboard", "/roles", "/drives"]},
            {"role": "recruiter", "items": ["/recruiter/dashboard", "/drives", "/pipeline"]},
            {"role": "candidate", "items": ["/profile/cv-upload", "/my-applications", "/signup"]},
        ]},
    }
    groups = _plan_declared_sidebar(plan)
    routes = [g["route"] for g in groups]
    assert routes == [
        "/dashboard", "/roles", "/drives",           # admin
        "/recruiter/dashboard", "/pipeline",           # recruiter (drives already seen)
        "/profile/cv-upload", "/my-applications",       # candidate (signup filtered)
    ]
    # /signup filtered from candidate items
    assert "/signup" not in routes
    # Labels + icons humanised from the route
    dash = next(g for g in groups if g["route"] == "/dashboard")
    assert dash["label"] == "Dashboard"
    assert isinstance(dash["icon"], str) and dash["icon"]


def test_blueprint_reads_entities_from_normalized_plan(tmp_path):
    """The record_plan hook historically read plan['models'] (never
    emitted), so blueprint.json always showed entities=0. Now it reads
    from `data_models` (raw) and `entities` (post-normalize dict) too."""
    import json as _json, uuid
    from services.blueprint_pipeline_hooks import record_plan
    from services.smith_blueprint import Blueprint

    project_id = str(uuid.uuid4())
    plan = {
        "entities": {
            "Application": {"name": "Application", "table": "applications",
                            "fields": [{"name": "id"}, {"name": "status"}]},
            "Candidate":   {"name": "Candidate", "table": "candidates",
                            "fields": [{"name": "id"}, {"name": "email"}]},
        },
        "workflows": [],
        "pages": [],
    }
    record_plan(output_dir=str(tmp_path), project_id=project_id, plan=plan)
    bp = Blueprint.load(project_id=project_id, output_dir=str(tmp_path))
    names = {e.get("name") for e in bp.entities}
    assert names == {"Application", "Candidate"}, (
        f"blueprint should read from `entities` dict; got {names}"
    )


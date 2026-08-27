"""Tests for nav_flow_emitter."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

from services.nav_flow_emitter import emit_nav_flow


def _seed_schema(dir_: Path, slug: str, content: dict) -> None:
    p = dir_ / "src" / "schemas" / f"{slug}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(content))


def test_emit_with_two_pages_one_transition():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _seed_schema(out, "home", {
            "schemaVersion": "2", "id": "home",
            "root": {"type": "Button", "id": "b1",
                     "props": {"label": "Sign up",
                               "onClick": {"action": "navigate",
                                           "trigger": "signupClicked",
                                           "to": "signup"}}}
        })
        _seed_schema(out, "signup", {
            "schemaVersion": "2", "id": "signup",
            "root": {"type": "Form", "id": "f1"}
        })
        plan = {
            "pages": [
                {"name": "Home",   "route": "/",       "type": "dashboard"},
                {"name": "Signup", "route": "/signup", "type": "form"},
            ]
        }
        emit_nav_flow(str(out), plan)
        nav = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text())
        assert nav["initialPage"] == "home"
        assert len(nav["pages"]) == 2
        assert len(nav["transitions"]) == 1
        assert nav["transitions"][0]["trigger"] == "signupClicked"
        assert nav["transitions"][0]["to"] == "signup"


def test_emit_handles_auth_guard_from_plan():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _seed_schema(out, "dashboard", {"schemaVersion": "2", "id": "dashboard"})
        plan = {"pages": [{"name": "Dashboard", "route": "/dashboard",
                          "type": "dashboard", "requires_auth": True}]}
        emit_nav_flow(str(out), plan)
        nav = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text())
        page = next(p for p in nav["pages"] if p["id"] == "dashboard")
        assert page["guard"] == "requiresAuth"
        assert "requiresAuth" in nav["guards"]
        assert nav["guards"]["requiresAuth"]["redirectTo"] == "login"


def test_emit_picks_root_route_as_initial():
    """Page with route '/' is the initial page even if listed second."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _seed_schema(out, "home", {"schemaVersion": "2", "id": "home"})
        _seed_schema(out, "other", {"schemaVersion": "2", "id": "other"})
        plan = {"pages": [
            {"name": "Other", "route": "/other", "type": "generic"},
            {"name": "Home",  "route": "/",      "type": "dashboard"},
        ]}
        emit_nav_flow(str(out), plan)
        nav = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text())
        assert nav["initialPage"] == "home"


def test_emit_extracts_route_params():
    """`/users/[id]` page has params=['id']."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _seed_schema(out, "users-detail", {"schemaVersion": "2", "id": "users-detail"})
        plan = {"pages": [
            {"name": "User Detail", "route": "/users/[id]", "type": "detail"},
        ]}
        emit_nav_flow(str(out), plan)
        nav = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text())
        page = next(p for p in nav["pages"] if "[id]" in p["route"])
        assert page["params"] == ["id"]


def test_emit_is_idempotent():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _seed_schema(out, "home", {"schemaVersion": "2", "id": "home"})
        plan = {"pages": [{"name": "Home", "route": "/", "type": "dashboard"}]}
        emit_nav_flow(str(out), plan)
        first = (out / "src" / "contracts" / "nav-flow.json").read_text()
        emit_nav_flow(str(out), plan)
        second = (out / "src" / "contracts" / "nav-flow.json").read_text()
        assert first == second


def test_emit_skips_transitions_referencing_unknown_pages():
    """If onClick navigates to a slug not in plan.pages, drop the transition."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _seed_schema(out, "home", {
            "schemaVersion": "2", "id": "home",
            "root": {"type":"Button", "id":"b",
                     "props":{"onClick":{"action":"navigate","trigger":"go","to":"nowhere"}}}
        })
        plan = {"pages": [{"name":"Home","route":"/","type":"dashboard"}]}
        emit_nav_flow(str(out), plan)
        nav = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text())
        assert nav["transitions"] == []


def test_emit_auth_page_has_shell_false_and_populates_auth_routes():
    """Auth-type pages must have shell=False and appear in authRoutes.

    The app shell (nav, sidebar) must NOT wrap login/signup pages.
    Non-auth pages must keep shell=True (default).
    transitions + guards keys must still be present (regression guard).
    """
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        plan = {"pages": [
            {"route": "/", "name": "Home", "type": "dashboard"},
            {"route": "/login", "name": "Login", "type": "auth"},
            {"route": "/items", "name": "Items", "type": "list"},
        ]}
        emit_nav_flow(str(out), plan)
        nav = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text())

        pages_by_route = {p["route"]: p for p in nav["pages"]}

        # Auth page must be bare (no shell)
        assert pages_by_route["/login"]["shell"] is False, \
            "login page must have shell=False so it is not wrapped in the app shell"

        # Non-auth pages must keep default shell=True
        assert pages_by_route["/"]["shell"] is True, \
            "dashboard page must keep shell=True"
        assert pages_by_route["/items"]["shell"] is True, \
            "list page must keep shell=True"

        # auth_routes must be snake_case — that's the key the render scaffold reads
        # (apps/render-scaffold .../page.tsx: navFlowAny?.auth_routes).
        assert "/login" in nav["auth_routes"], \
            "/login must appear in auth_routes (snake_case, the consumer's key)"
        assert "authRoutes" not in nav, \
            "auth_routes must NOT be camelCase — the render scaffold reads snake_case"

        # Structural regression guard — transitions + guards still emitted
        assert "transitions" in nav
        assert "guards" in nav


# ---------------------------------------------------------------------------
# Tests for _schema_file_from_route (Fix 2: folder-layout schemaFile)
# ---------------------------------------------------------------------------

from services.nav_flow_emitter import _schema_file_from_route


def test_root_route_maps_to_home():
    assert _schema_file_from_route("/") == "src/schemas/home.json"


def test_simple_route_preserves_name():
    assert _schema_file_from_route("/requests") == "src/schemas/requests.json"


def test_nested_route_uses_folder_layout():
    """The schema agent writes /requests/new at requests/new.json — not kebab."""
    assert _schema_file_from_route("/requests/new") == "src/schemas/requests/new.json"


def test_dynamic_route_collapses_to_detail():
    assert _schema_file_from_route("/users/[id]") == "src/schemas/users/detail.json"


def test_empty_route_treated_as_root():
    assert _schema_file_from_route("") == "src/schemas/home.json"

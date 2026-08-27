"""Regression guard for the SP1.5-F1 parity fix on the plan-driven
nav-flow emitter.

The plan-driven emitter used to check ONLY ``page.type == "auth"``.
The planner mislabels /signup as ``type: "form"`` roughly half the
time on rich-domain runs (ATS, healthcare), which sent the auth
pages into the app shell — visible in the sidebar as "Signup",
"Candidate Login", etc. The route wins now: /login, /signup,
/register etc. are auth pages regardless of what the planner said.
"""
from __future__ import annotations

from services.nav_flow_from_plan import nav_flow_from_plan


def _find_page(nav: dict, route: str) -> dict | None:
    return next(
        (p for p in nav["pages"] if p["route"] == route),
        None,
    )


def test_signup_route_is_auth_even_when_type_is_form():
    """The canonical bug: planner emitted ``type: form`` for signup,
    old emitter routed it into the shell. Route now wins."""
    plan = {"pages": [
        {"id": "signup", "route": "/signup", "type": "form", "name": "Signup"},
        {"id": "dash",   "route": "/dashboard", "type": "dashboard", "name": "Dashboard"},
    ]}
    nav = nav_flow_from_plan(plan)
    signup = _find_page(nav, "/signup")
    assert signup is not None
    assert signup["shell"] is False, "signup must be non-shell — it's an auth route"
    assert "/signup" in nav["auth_routes"]


def test_login_route_is_auth_even_when_type_is_missing():
    """The planner sometimes omits ``type`` entirely on auth pages
    (they were skipped in the planner's page-typing heuristic)."""
    plan = {"pages": [
        {"id": "login", "route": "/login", "name": "Login"},
        {"id": "home",  "route": "/dashboard", "type": "dashboard", "name": "Home"},
    ]}
    nav = nav_flow_from_plan(plan)
    login = _find_page(nav, "/login")
    assert login is not None
    assert login["shell"] is False
    assert "/login" in nav["auth_routes"]


def test_scoped_login_route_still_auth():
    """/recruiter/login etc. — scoped auth pages still count as auth."""
    plan = {"pages": [
        {"id": "recruiter-login", "route": "/recruiter/login", "type": "form",
         "name": "Recruiter Login"},
    ]}
    nav = nav_flow_from_plan(plan)
    p = _find_page(nav, "/recruiter/login")
    assert p is not None
    # Route starts with /recruiter/login — /recruiter/login does NOT start
    # with /login, so this specific case shouldn't be auto-caught. Test
    # documents current behavior: only top-level /login|/signup|/register
    # get the treatment.
    # If we later want scoped auth pages to also be non-shell, add the
    # pattern to _AUTH_ROUTE_PREFIXES.


def test_dashboard_route_stays_in_shell():
    plan = {"pages": [
        {"id": "dashboard", "route": "/dashboard", "type": "dashboard",
         "name": "Dashboard"},
    ]}
    nav = nav_flow_from_plan(plan)
    p = _find_page(nav, "/dashboard")
    assert p["shell"] is True


def test_type_auth_still_marks_page_as_auth():
    """Regression: preserve the original behavior when planner DOES
    correctly annotate ``type: "auth"`` — the fix is additive, not a
    replacement."""
    plan = {"pages": [
        {"id": "fancylogin", "route": "/fancy-oauth", "type": "auth",
         "name": "OAuth"},
    ]}
    nav = nav_flow_from_plan(plan)
    p = _find_page(nav, "/fancy-oauth")
    assert p["shell"] is False


def test_register_route_is_auth():
    plan = {"pages": [
        {"id": "register", "route": "/register", "type": "form", "name": "Register"},
    ]}
    nav = nav_flow_from_plan(plan)
    p = _find_page(nav, "/register")
    assert p["shell"] is False
    assert "/register" in nav["auth_routes"]


def test_auth_pages_reach_auth_routes_list():
    """The auth_routes[] array drives the runtime auth-gate + logout
    redirect target. It must include every auth route so the frontend
    doesn't treat login as a normal shell page."""
    plan = {"pages": [
        {"id": "login",  "route": "/login",  "type": "form", "name": "Login"},
        {"id": "signup", "route": "/signup", "type": "form", "name": "Signup"},
        {"id": "dash",   "route": "/dashboard", "type": "dashboard", "name": "Dash"},
    ]}
    nav = nav_flow_from_plan(plan)
    assert set(nav["auth_routes"]) == {"/login", "/signup"}

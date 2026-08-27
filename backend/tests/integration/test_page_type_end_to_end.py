"""Integration: classifier + planner annotation + prompt-builder chain.

NOT a real LLM call — just confirms the chain wires correctly so a /login
route ends up with PAGE TYPE: AUTH in its prompt, and /requests/new ends
up with PAGE TYPE: FORM.
"""
from agents.planner import _annotate_page_types
from services.schema_prompt import build_schema_prompt


def _prompt_for(plan, route):
    """Run annotation, find the page, build the prompt."""
    _annotate_page_types(plan)
    page = next(p for p in plan["pages"] if p["route"] == route)
    page_brief = {
        "route": page["route"],
        "role": "",
        "archetype": page["type"],
        "page_type": page["type"],
    }
    page_plan = {
        **plan,
        "page_type": page["type"],
        "page": page,
        "entity": {"name": page.get("entity") or "Thing", "fields": []},
        "description": "integration test",
    }
    return build_schema_prompt(page_plan, page_brief=page_brief, domain="general"), page


def test_login_chain():
    plan = {
        "pages": [
            {"route": "/login", "name": "Login", "description": "Login page", "entity": None},
        ]
    }
    prompt, page = _prompt_for(plan, "/login")
    assert page["type"] == "auth"
    assert "PAGE TYPE: AUTH" in prompt


def test_signup_chain():
    plan = {
        "pages": [
            {"route": "/signup", "name": "Signup", "description": "Signup page", "entity": None},
        ]
    }
    prompt, page = _prompt_for(plan, "/signup")
    assert page["type"] == "auth"
    assert "PAGE TYPE: AUTH" in prompt


def test_new_request_form_chain():
    """The original bug — /requests/new used to be classified as a dashboard."""
    plan = {
        "pages": [
            {"route": "/requests/new", "name": "New Request", "description": "", "entity": "LeaveRequest"},
        ]
    }
    prompt, page = _prompt_for(plan, "/requests/new")
    assert page["type"] == "form"
    assert "PAGE TYPE: FORM" in prompt
    # Explicit anti-pattern guard
    assert "MetricTile" in prompt  # mentioned in DO-NOT clause


def test_users_list_chain():
    plan = {
        "pages": [
            {"route": "/users", "name": "Users", "description": "Browse users", "entity": "User"},
        ]
    }
    prompt, page = _prompt_for(plan, "/users")
    assert page["type"] == "list"
    assert "PAGE TYPE: LIST" in prompt


def test_user_detail_chain():
    plan = {
        "pages": [
            {"route": "/users/[id]", "name": "User detail", "description": "", "entity": "User"},
        ]
    }
    prompt, page = _prompt_for(plan, "/users/[id]")
    assert page["type"] == "detail"
    assert "PAGE TYPE: DETAIL" in prompt


def test_root_dashboard_chain():
    plan = {
        "pages": [
            {"route": "/", "name": "Home", "description": "Overview", "entity": None},
        ]
    }
    prompt, page = _prompt_for(plan, "/")
    assert page["type"] == "dashboard"
    assert "PAGE TYPE: DASHBOARD" in prompt


def test_error_chain():
    plan = {
        "pages": [
            {"route": "/not-found", "name": "Not Found", "description": "", "entity": None},
        ]
    }
    prompt, page = _prompt_for(plan, "/not-found")
    assert page["type"] == "error"
    assert "PAGE TYPE: ERROR" in prompt


def test_multi_page_plan_each_gets_correct_type():
    """The realistic case — 5 different routes, each ends up with a different template."""
    plan = {
        "pages": [
            {"route": "/", "name": "Home", "description": "Dashboard", "entity": None},
            {"route": "/login", "name": "Login", "description": "", "entity": None},
            {"route": "/requests", "name": "Requests", "description": "Browse leave requests", "entity": "LeaveRequest"},
            {"route": "/requests/new", "name": "New", "description": "", "entity": "LeaveRequest"},
            {"route": "/requests/[id]", "name": "Detail", "description": "", "entity": "LeaveRequest"},
        ]
    }
    _annotate_page_types(plan)
    types = {p["route"]: p["type"] for p in plan["pages"]}
    assert types == {
        "/": "dashboard",
        "/login": "auth",
        "/requests": "list",
        "/requests/new": "form",
        "/requests/[id]": "detail",
    }

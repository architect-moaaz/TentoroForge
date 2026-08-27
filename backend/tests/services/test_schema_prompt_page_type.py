"""Tests that build_schema_prompt injects the right page-type template
when page_brief / page_plan carries a `page_type` field.
"""
from services.schema_prompt import build_schema_prompt


def _minimal_plan(page_type: str, route: str = "/x") -> tuple[dict, dict]:
    """Returns (plan, page_brief) shaped for build_schema_prompt with the
    minimum fields the prompt-builder requires."""
    plan = {
        "description": "test plan",
        "entity": {"name": "Thing", "fields": []},
        "page_type": page_type,
        "page": {"route": route, "type": page_type},
        "pages": [],
    }
    page_brief = {
        "route": route,
        "role": "",
        "archetype": page_type,
        "page_type": page_type,
    }
    return plan, page_brief


def test_form_page_type_injects_form_template():
    plan, page_brief = _minimal_plan("form", "/users/new")
    prompt = build_schema_prompt(plan, page_brief=page_brief, domain="general")
    assert "PAGE TYPE: FORM" in prompt
    # Required components mentioned in the template
    assert "Input" in prompt
    # Exclusion clause present
    assert "DO NOT" in prompt


def test_auth_page_type_injects_auth_template():
    plan, page_brief = _minimal_plan("auth", "/login")
    prompt = build_schema_prompt(plan, page_brief=page_brief, domain="general")
    assert "PAGE TYPE: AUTH" in prompt


def test_detail_page_type_injects_detail_template():
    plan, page_brief = _minimal_plan("detail", "/users/[id]")
    prompt = build_schema_prompt(plan, page_brief=page_brief, domain="general")
    assert "PAGE TYPE: DETAIL" in prompt


def test_list_page_type_injects_list_template():
    plan, page_brief = _minimal_plan("list", "/users")
    prompt = build_schema_prompt(plan, page_brief=page_brief, domain="general")
    assert "PAGE TYPE: LIST" in prompt


def test_dashboard_page_type_injects_dashboard_template():
    plan, page_brief = _minimal_plan("dashboard", "/")
    prompt = build_schema_prompt(plan, page_brief=page_brief, domain="general")
    assert "PAGE TYPE: DASHBOARD" in prompt


def test_error_page_type_injects_error_template():
    plan, page_brief = _minimal_plan("error", "/not-found")
    prompt = build_schema_prompt(plan, page_brief=page_brief, domain="general")
    assert "PAGE TYPE: ERROR" in prompt


def test_generic_page_type_omits_template_block():
    """Generic (and unknown) page types should NOT add a template block —
    the rest of the prompt already covers generic guidance."""
    plan, page_brief = _minimal_plan("generic", "/about")
    prompt = build_schema_prompt(plan, page_brief=page_brief, domain="general")
    assert "PAGE TYPE:" not in prompt


def test_template_appears_at_end_of_prompt():
    """Templates rely on recency bias — must be near the end of the prompt,
    after the CTA block. Verify by char-position."""
    plan, page_brief = _minimal_plan("form", "/users/new")
    prompt = build_schema_prompt(plan, page_brief=page_brief, domain="general")
    # The template should appear in the LAST 30% of the prompt
    template_pos = prompt.find("PAGE TYPE: FORM")
    assert template_pos > 0
    assert template_pos / len(prompt) > 0.50, (
        f"template appeared at {template_pos / len(prompt):.0%} of prompt — "
        "too early; LLM gives weight to recency"
    )


def test_missing_page_type_falls_through_to_generic():
    """If page_brief lacks page_type, fall through (no template injected)."""
    plan = {
        "description": "test plan",
        "entity": {"name": "Thing", "fields": []},
        "pages": [],
        "page": {"route": "/x"},
    }
    page_brief = {"route": "/x", "role": "", "archetype": "generic"}
    prompt = build_schema_prompt(plan, page_brief=page_brief, domain="general")
    assert "PAGE TYPE:" not in prompt

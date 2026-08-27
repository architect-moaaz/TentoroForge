"""Tests for Form component contract in schema_prompt.py and schema_rules.py."""

from services.schema_prompt import build_schema_prompt


def test_form_prompt_includes_declarative_guidance():
    plan = {"entity": {"name": "Note", "fields": []}, "page_type": "form"}
    design_spec = {"register": "default"}
    prompt = build_schema_prompt(plan, design_spec=design_spec)
    # Declarative mode marker must be present
    assert "DECLARATIVE" in prompt or "declarative" in prompt
    # workflow prop must be taught
    assert "workflow" in prompt
    # kind enumeration must be visible
    assert "kind" in prompt
    # Container mode must be mentioned as the alternative
    assert "container" in prompt.lower() or "CONTAINER" in prompt


def test_form_rule_in_schema_rules():
    from services.schema_rules import RULES
    form_rule = next(
        (r for r in RULES if r.name == "form-declarative-default"), None
    )
    assert form_rule is not None, "form-declarative-default rule must exist"
    # Rule fires on form pages
    assert form_rule.applies_when({"name": "X", "fields": []}, "form") is True
    # Rule must NOT fire on non-form pages
    assert form_rule.applies_when({"name": "X", "fields": []}, "list") is False
    assert form_rule.applies_when({"name": "X", "fields": []}, "detail") is False

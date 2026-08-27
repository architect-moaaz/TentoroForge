"""Tests for the progressive-disclosure rule block + exemplar inlining
injected by build_schema_prompt.

Task 19: verify that form pages get the wide-form-accordion exemplar
inlined, and that the rule block ('Container choice (binding)') is
present for every page_type.
"""
from services.schema_prompt import build_schema_prompt


def test_form_prompt_includes_accordion_exemplar():
    plan = {"entity": {"name": "Lead", "fields": []}, "page_type": "form"}
    design_spec = {"register": "default"}
    prompt = build_schema_prompt(plan, design_spec=design_spec)
    # Either the exemplar's filename reference (in the rule block) or
    # the inlined JSON containing an Accordion must appear.
    assert "wide-form-accordion" in prompt or "Accordion" in prompt
    assert "exemplar" in prompt.lower()


def test_detail_prompt_includes_detail_tabs_exemplar():
    plan = {"entity": {"name": "Lead", "fields": []}, "page_type": "detail"}
    design_spec = {"register": "default"}
    prompt = build_schema_prompt(plan, design_spec=design_spec)
    assert "detail-tabs" in prompt or "TabPanel" in prompt
    assert "Container choice" in prompt


def test_list_prompt_has_rule_block_without_inlined_exemplar():
    """Non-form/non-detail page types should still see the binding rule
    block — only the inlined JSON exemplar is skipped to keep the prompt
    lean."""
    plan = {"entity": {"name": "Lead", "fields": []}, "page_type": "list"}
    design_spec = {"register": "default"}
    prompt = build_schema_prompt(plan, design_spec=design_spec)
    assert "Container choice (binding)" in prompt
    # The rule block references the exemplars by name as reference
    # patterns, so "wide-form-accordion" appears even without inlining.
    assert "Reference patterns" in prompt

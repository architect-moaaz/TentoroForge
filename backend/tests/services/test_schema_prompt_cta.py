"""Tests for the CTA hierarchy block injected by build_schema_prompt.

Task 17: verify that design_spec.cta_hierarchy is read and emitted as a
binding rule block, and that the function falls back to cta_defaults when
the spec carries no cta_hierarchy.
"""
from services.schema_prompt import build_schema_prompt


def _minimal_plan(page_type: str = "list") -> dict:
    return {
        "entity": {"name": "Task", "fields": []},
        "page_type": page_type,
        "description": "Task management app",
    }


def test_cta_block_in_prompt():
    """CTA block is present and contains the spec's variant names + cap."""
    plan = _minimal_plan()
    design_spec = {
        "register": "linear",
        "cta_hierarchy": {
            "primary":   {"variant": "primary",   "max_per_page": 1,    "min_per_page": 1},
            "secondary": {"variant": "secondary", "max_per_page": 2,    "min_per_page": 0},
            "tertiary":  {"variant": "ghost",     "max_per_page": None, "min_per_page": 0},
        },
    }
    prompt = build_schema_prompt(plan, design_spec=design_spec)
    assert "CTA hierarchy (binding)" in prompt
    assert 'variant="primary"' in prompt
    assert "Cap: 2 per page" in prompt
    assert 'variant="ghost"' in prompt


def test_cta_block_uses_defaults_when_no_cta_hierarchy():
    """Falls back to cta_defaults when design_spec has no cta_hierarchy key."""
    plan = _minimal_plan()
    # "linear" register → secondary.max_per_page == 2
    design_spec = {"register": "linear"}
    prompt = build_schema_prompt(plan, design_spec=design_spec)
    assert "CTA hierarchy (binding)" in prompt
    assert "Cap: 2 per page" in prompt


def test_cta_block_uses_defaults_when_design_spec_empty():
    """Empty design_spec falls back to default register defaults."""
    plan = _minimal_plan()
    prompt = build_schema_prompt(plan, design_spec={})
    assert "CTA hierarchy (binding)" in prompt
    # default register has secondary.max_per_page == 3
    assert "Cap: 3 per page" in prompt


def test_cta_block_present_without_design_spec_kwarg(monkeypatch):
    """CTA block is always appended even when design_spec kwarg is omitted
    (the fidelity-mode path still falls back to defaults)."""
    # Monkeypatch _load_design_spec to return empty dict so the test is
    # hermetic (no real output_dir needed).
    import services.schema_prompt as sp
    monkeypatch.setattr(sp, "_load_design_spec", lambda _: {})
    prompt = build_schema_prompt(_minimal_plan())
    assert "CTA hierarchy (binding)" in prompt


def test_cta_block_reflects_custom_variants():
    """Custom variant names from the spec appear verbatim in the block."""
    plan = _minimal_plan(page_type="form")
    design_spec = {
        "register": "workday",
        "cta_hierarchy": {
            "primary":   {"variant": "filled",   "max_per_page": 1,    "min_per_page": 1},
            "secondary": {"variant": "outlined",  "max_per_page": 4,    "min_per_page": 0},
            "tertiary":  {"variant": "text",      "max_per_page": None, "min_per_page": 0},
        },
    }
    prompt = build_schema_prompt(plan, design_spec=design_spec)
    assert 'variant="filled"' in prompt
    assert 'variant="outlined"' in prompt
    assert 'variant="text"' in prompt
    assert "Cap: 4 per page" in prompt

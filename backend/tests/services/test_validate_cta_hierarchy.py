import pytest
from services.schema_validator import validate_cta_hierarchy

CTA = {
    "primary":   {"variant": "primary",   "max_per_page": 1, "min_per_page": 1},
    "secondary": {"variant": "secondary", "max_per_page": 3, "min_per_page": 0},
    "tertiary":  {"variant": "ghost",     "max_per_page": None, "min_per_page": 0},
}

def _btn(variant: str):
    return {"type": "Button", "props": {"label": "x", "variant": variant}}

def _page(buttons: list[dict], page_type: str = "list"):
    return {
        "schemaVersion": "2", "id": "p", "route": "/p", "layout": "main",
        "root": {"type": "Stack", "children": buttons},
        "page_type": page_type,
    }

def test_one_primary_passes():
    errors = validate_cta_hierarchy(_page([_btn("primary"), _btn("ghost")]), CTA)
    assert errors == []

def test_zero_primary_fails():
    errors = validate_cta_hierarchy(_page([_btn("ghost")]), CTA)
    assert len(errors) == 1
    assert "primary" in errors[0].lower()

def test_two_primary_fails():
    errors = validate_cta_hierarchy(_page([_btn("primary"), _btn("primary")]), CTA)
    assert len(errors) == 1
    assert "primary" in errors[0].lower()

def test_too_many_secondary_fails():
    buttons = [_btn("primary")] + [_btn("secondary")] * 4
    errors = validate_cta_hierarchy(_page(buttons), CTA)
    assert any("secondary" in e.lower() for e in errors)

def test_form_page_skips_primary_count():
    page = _page([], page_type="form")
    page["root"] = {"type": "Form", "children": []}
    errors = validate_cta_hierarchy(page, CTA)
    assert not any("primary count" in e.lower() and "0" in e for e in errors)

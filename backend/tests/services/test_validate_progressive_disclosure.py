"""Tests for validate_progressive_disclosure.

The validator flags Forms with > 7 user-editable fields not nested inside
an Accordion or Tabs partition. Forms below the threshold pass; forms
above the threshold pass only when their fields are wrapped in one of
the recognised partition containers.
"""
from services.schema_validator import validate_progressive_disclosure


def _input(name: str) -> dict:
    return {"type": "Input", "props": {"label": name, "name": name}}


def _form_with_n_fields(n: int, container: str | None = None) -> dict:
    fields = [_input(f"f{i}") for i in range(n)]
    if container is None:
        return {
            "schemaVersion": "2", "id": "p", "route": "/", "layout": "m",
            "root": {"type": "Form", "children": fields},
            "page_type": "form",
        }
    return {
        "schemaVersion": "2", "id": "p", "route": "/", "layout": "m",
        "root": {"type": "Form", "children": [
            {"type": container, "children": fields},
        ]},
        "page_type": "form",
    }


def test_flat_form_with_5_fields_ok():
    errors = validate_progressive_disclosure(_form_with_n_fields(5))
    assert errors == []


def test_flat_form_with_8_fields_fails():
    errors = validate_progressive_disclosure(_form_with_n_fields(8))
    assert any(
        "accordion" in e.lower() or "tabs" in e.lower() for e in errors
    )


def test_form_with_8_fields_in_accordion_passes():
    errors = validate_progressive_disclosure(
        _form_with_n_fields(8, container="Accordion")
    )
    assert errors == []


def test_form_with_8_fields_in_tabs_passes():
    errors = validate_progressive_disclosure(
        _form_with_n_fields(8, container="Tabs")
    )
    assert errors == []

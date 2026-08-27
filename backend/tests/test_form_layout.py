# backend/tests/test_form_layout.py
"""build_form_page layout: full-width structured fields + light sectioning + modal dedup."""
import json

from services.deterministic_pages import build_form_page

_WIDE_TYPES = {"Textarea", "KeyValueInput"}


def _find(page, pred):
    out = []
    def walk(n):
        if isinstance(n, dict):
            if pred(n):
                out.append(n)
            for c in (n.get("children") or []):
                walk(c)
            if n.get("root"):
                walk(n["root"])
        elif isinstance(n, list):
            for c in n:
                walk(c)
    walk(page)
    return out


def _grids(page):
    return _find(page, lambda n: n.get("type") == "Grid")


def _inputs_under(node, types):
    return _find(node, lambda n: n.get("type") in types)


# 6 compact + a long-text (Textarea) + a jsonb (KeyValueInput) = 8 total, 2 wide.
_COLS = {
    "id": {"type": "uuid", "primaryKey": True},
    "title": {"type": "varchar", "nullable": False},
    "slug": {"type": "varchar"},
    "priority": {"type": "integer"},
    "category": {"type": "varchar"},
    "email": {"type": "varchar"},
    "phone": {"type": "varchar"},
    "description": {"type": "text"},          # → Textarea (wide)
    "settings": {"type": "jsonb"},            # → KeyValueInput (wide)
}

# 3 compact, no wide.
_SMALL_COLS = {
    "id": {"type": "uuid", "primaryKey": True},
    "title": {"type": "varchar", "nullable": False},
    "priority": {"type": "integer"},
    "category": {"type": "varchar"},
}


def test_wide_fields_are_full_width():
    page = build_form_page("Ticket", _COLS, "/tickets/new", None, op="create")
    grids = _grids(page)
    assert grids, "expected a 2-col Grid for the compact inputs"
    # Wide inputs must NOT live inside any Grid.
    for g in grids:
        assert not _inputs_under(g, _WIDE_TYPES), "Textarea/KeyValueInput leaked into the Grid"
    # Compact inputs ARE inside a Grid.
    compact_in_grid = []
    for g in grids:
        compact_in_grid += _inputs_under(g, {"Input", "NumberInput"})
    assert compact_in_grid, "compact Inputs should be inside the Grid"
    # The wide nodes still exist in the page (as full-width direct children of a Stack).
    wide = _find(page, lambda n: n.get("type") in _WIDE_TYPES)
    assert {n["type"] for n in wide} == _WIDE_TYPES


def test_large_form_gets_section_headings():
    page = build_form_page("Ticket", _COLS, "/tickets/new", None, op="create")
    h3 = _find(page, lambda n: n.get("type") == "Heading" and n.get("props", {}).get("level") == 3)
    contents = {n["props"].get("content") for n in h3}
    assert "Details" in contents
    assert "Additional information" in contents


def test_small_form_no_section_headings():
    page = build_form_page("Ticket", _SMALL_COLS, "/tickets/new", None, op="create")
    h3 = _find(page, lambda n: n.get("type") == "Heading" and n.get("props", {}).get("level") == 3)
    assert not h3, "small form should not have sub-section headings"
    h1 = _find(page, lambda n: n.get("type") == "Heading" and n.get("props", {}).get("level") == 1)
    assert h1, "small form still has the level:1 page title"


def test_modal_skips_page_heading():
    modal = build_form_page("Ticket", _COLS, "/tickets/new", None, op="create", modal=True)
    assert not _find(modal, lambda n: n.get("type") == "Heading" and n.get("props", {}).get("level") == 1)
    page = build_form_page("Ticket", _COLS, "/tickets/new", None, op="create", modal=False)
    assert _find(page, lambda n: n.get("type") == "Heading" and n.get("props", {}).get("level") == 1)


def test_regression_small_form_card_and_submit_intact():
    page = build_form_page("Ticket", _SMALL_COLS, "/tickets/new", None, op="create")
    dumped = json.dumps(page)
    assert '"Card"' in dumped
    submit = _find(page, lambda n: n.get("type") == "Button" and n.get("props", {}).get("submit") is True)
    assert submit, "submit button present"
    cancel = _find(page, lambda n: n.get("type") == "Button" and n.get("props", {}).get("label") == "Cancel")
    assert cancel, "cancel button present"

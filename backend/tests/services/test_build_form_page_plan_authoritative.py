"""Pin: when the planner authored `page.fields`, build_form_page emits
EXACTLY those fields — never the registry-column backstop.

Regression test for the RentPayment / auth-field leak observed on live
run upsvs9w9: the form scaffolded with plan-declared 5 payment fields,
BUT the emitted form contained 14 (payment + auth). Root cause was
build_form_page merging plan spec OVER the full registry column set
and treating registry as an "add anything the plan omitted" backstop.

New contract: plan wins verbatim. Registry is a lookup for types + FK
targets, never an additive source. Unknown-column specs are dropped
silently. When plan doesn't spec fields, registry-drive behaviour is
preserved (opt-in, legacy path).
"""
from __future__ import annotations

import pytest

from services.deterministic_pages import build_form_page


# Real-shape registry column dict (subset of what the drizzle schema builder
# emits into registry.json.entities.<Entity>.fields).
_RENT_PAYMENT_COLS = {
    "id":                {"type": "uuid",      "nullable": False, "primaryKey": True, "hasDefault": True},
    "leaseId":           {"type": "uuid",      "nullable": True,  "primaryKey": False},
    "amountDue":         {"type": "integer",   "nullable": True,  "primaryKey": False},
    "amountPaid":        {"type": "integer",   "nullable": True,  "primaryKey": False},
    "dueDate":           {"type": "timestamp", "nullable": True,  "primaryKey": False},
    "method":            {"type": "varchar",   "nullable": True,  "primaryKey": False},
    "transactionToken":  {"type": "varchar",   "nullable": True,  "primaryKey": False},
    "status":            {"type": "varchar",   "nullable": True,  "primaryKey": False},
    "gracePeriodDays":   {"type": "integer",   "nullable": True,  "primaryKey": False},
    "createdAt":         {"type": "timestamp", "nullable": True,  "primaryKey": False},
    "updatedAt":         {"type": "timestamp", "nullable": True,  "primaryKey": False},
}

_ENTITIES = {"RentPayment": {"fields": _RENT_PAYMENT_COLS}}


def _field_names_in_form(page: dict) -> list[str]:
    """Extract the ordered list of `props.name` for every field-shaped
    node under the emitted page (dive into any Stack/Grid/Card wrappers)."""
    field_types = {"Input", "NumberInput", "Textarea", "Select", "Combobox",
                   "DatePicker", "TimePicker", "Switch", "Checkbox", "RadioGroup",
                   "FileUpload", "Slider", "ColorPicker"}
    out: list[str] = []
    def _walk(n):
        if isinstance(n, dict):
            if n.get("type") in field_types:
                nm = (n.get("props") or {}).get("name")
                if nm:
                    out.append(nm)
            for k in ("children", "child"):
                v = n.get(k)
                if isinstance(v, list):
                    for c in v: _walk(c)
                elif isinstance(v, dict):
                    _walk(v)
        elif isinstance(n, list):
            for c in n: _walk(c)
    _walk(page.get("root") or page)
    return out


# ── Contract 1: plan wins verbatim ─────────────────────────────────────

def test_plan_field_specs_are_authoritative():
    """5 planner fields → form has exactly those 5, in that order."""
    field_specs = [
        {"name": "leaseId",    "order": 1},
        {"name": "amountDue",  "order": 2},
        {"name": "amountPaid", "order": 3},
        {"name": "dueDate",    "order": 4},
        {"name": "method",     "order": 5},
    ]
    page = build_form_page(
        entity="RentPayment",
        columns=_RENT_PAYMENT_COLS,
        route="/payments/new",
        design_spec=None,
        field_specs=field_specs,
        entities=_ENTITIES,
    )
    names = _field_names_in_form(page)
    assert names == ["leaseId", "amountDue", "amountPaid", "dueDate", "method"]


def test_registry_backstop_never_adds_undeclared_columns():
    """Registry has 8 editable cols; plan declares only 3 → form has 3.
    The extra 5 (transactionToken, status, gracePeriodDays, ...) MUST NOT
    appear. This is the killer of the RentPayment/auth leak class."""
    field_specs = [
        {"name": "leaseId"},
        {"name": "amountDue"},
        {"name": "method"},
    ]
    page = build_form_page(
        entity="RentPayment",
        columns=_RENT_PAYMENT_COLS,
        route="/payments/new",
        design_spec=None,
        field_specs=field_specs,
        entities=_ENTITIES,
    )
    names = _field_names_in_form(page)
    assert set(names) == {"leaseId", "amountDue", "method"}
    for surprise in ("transactionToken", "status", "gracePeriodDays"):
        assert surprise not in names, f"registry backstop leaked {surprise!r}"


def test_cross_entity_columns_never_leak_into_form():
    """The exact live bug — auth columns (email/password/isActive/role)
    passed through the `columns` arg (via a wrong entity resolution
    somewhere upstream) MUST NOT reach the form when the plan authored
    only payment fields."""
    contaminated_cols = dict(_RENT_PAYMENT_COLS)
    contaminated_cols.update({
        "email":    {"type": "text",    "nullable": False, "primaryKey": False, "unique": True},
        "password": {"type": "text",    "nullable": False, "primaryKey": False},
        "isActive": {"type": "boolean", "nullable": True,  "primaryKey": False},
        "role":     {"type": "varchar", "nullable": True,  "primaryKey": False},
        "phone":    {"type": "varchar", "nullable": True,  "primaryKey": False},
    })
    field_specs = [
        {"name": "leaseId"},
        {"name": "amountDue"},
        {"name": "amountPaid"},
        {"name": "dueDate"},
        {"name": "method"},
    ]
    page = build_form_page(
        entity="RentPayment",
        columns=contaminated_cols,
        route="/payments/new",
        design_spec=None,
        field_specs=field_specs,
        entities=_ENTITIES,
    )
    names = _field_names_in_form(page)
    for auth_leak in ("email", "password", "isActive", "role", "phone"):
        assert auth_leak not in names, (
            f"auth column {auth_leak!r} leaked into a rent-payment form"
        )
    assert set(names) == {"leaseId", "amountDue", "amountPaid", "dueDate", "method"}


def test_unknown_spec_columns_are_dropped_silently():
    """Plan names a column that doesn't exist on the entity → dropped,
    no phantom Input emitted (that would blow up at bind-time)."""
    field_specs = [
        {"name": "leaseId"},                    # real
        {"name": "totallyMadeUpColumn"},         # phantom
        {"name": "amountDue"},                  # real
    ]
    page = build_form_page(
        entity="RentPayment",
        columns=_RENT_PAYMENT_COLS,
        route="/payments/new",
        design_spec=None,
        field_specs=field_specs,
        entities=_ENTITIES,
    )
    names = _field_names_in_form(page)
    assert names == ["leaseId", "amountDue"]


def test_order_field_honoured_when_specs_are_out_of_document_order():
    field_specs = [
        {"name": "method",    "order": 3},
        {"name": "leaseId",   "order": 1},
        {"name": "amountDue", "order": 2},
    ]
    page = build_form_page(
        entity="RentPayment",
        columns=_RENT_PAYMENT_COLS,
        route="/payments/new",
        design_spec=None,
        field_specs=field_specs,
        entities=_ENTITIES,
    )
    assert _field_names_in_form(page) == ["leaseId", "amountDue", "method"]


# ── Contract 2: no field_specs → legacy registry-drive still works ────

def test_no_field_specs_falls_back_to_registry_columns():
    """When the caller passes no `field_specs` (legacy paths), the
    registry-drive behaviour is preserved so we don't silently break
    the small set of non-plan-authored pages."""
    page = build_form_page(
        entity="RentPayment",
        columns=_RENT_PAYMENT_COLS,
        route="/payments/new",
        design_spec=None,
        field_specs=None,
        entities=_ENTITIES,
    )
    names = _field_names_in_form(page)
    # Registry-drive emits every editable column (skips PK + lifecycle timestamps).
    assert "leaseId" in names
    assert "amountDue" in names
    # And the previously-appearing columns still show up on this path.
    assert "transactionToken" in names
    assert "gracePeriodDays" in names

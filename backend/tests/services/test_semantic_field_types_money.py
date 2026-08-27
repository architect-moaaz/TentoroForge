"""`type: "money"` MUST decide MoneyInput — not NumberInput, not Input, not
Select — because the banking form needs both the amount + the currency in a
single control. Runs BEFORE the numeric/date/varchar branches so a money column
still wins even when the registry reports the SQL type as `decimal` /
`numeric`.
"""
from __future__ import annotations

from services.semantic_field_types import _FIELD_TYPES, _decide
from services.field_controls import resolve_control


def test_field_types_includes_money_pair():
    assert "MoneyInput" in _FIELD_TYPES
    assert "MoneyDisplay" in _FIELD_TYPES


def test_decide_money_sql_type_returns_MoneyInput():
    control, props = _decide("amount", "money", None)
    assert control == "MoneyInput"
    assert props == {}


def test_decide_currency_alias_also_returns_MoneyInput():
    control, props = _decide("price", "currency", None)
    assert control == "MoneyInput"
    assert props == {}


def test_decide_money_beats_the_numeric_stepper_branch():
    # A `money` type is also in _NUMERIC_TYPES; step 3 (numeric) MUST NOT win.
    # Prior to Slice 2 this returned ("NumberInput", {..., "prefix": "$"}).
    control, _props = _decide("amount", "money", None)
    assert control == "MoneyInput"


def test_resolve_control_money_type_returns_MoneyInput():
    control, props = resolve_control(name="amount", sql_type="money")
    assert control == "MoneyInput"
    assert props == {}


def test_resolve_control_semantic_money_hint_promotes_varchar_to_MoneyInput():
    # A plan that stored money on a legacy varchar column can still opt in via
    # semantic_type — this is what a self-heal or migration pass would use.
    control, _props = resolve_control(
        name="amount", sql_type="varchar", semantic_type="money"
    )
    assert control == "MoneyInput"


def test_resolve_control_semantic_currency_hint_also_MoneyInput():
    control, _props = resolve_control(
        name="fee", sql_type="", semantic_type="currency"
    )
    assert control == "MoneyInput"


def test_resolve_control_numeric_money_named_stays_NumberInput_when_no_money_type():
    # No `money` sql type, no semantic hint — the existing NumberInput+$
    # heuristic must still kick in so we don't regress non-banking apps.
    control, props = resolve_control(name="dailyRate", sql_type="numeric")
    assert control == "NumberInput"
    assert props.get("prefix") == "$"

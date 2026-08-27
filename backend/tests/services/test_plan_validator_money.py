"""A money column auto-emits `<field>_currency`; declaring a DIFFERENT alias
for the same amount is ambiguous and MUST fail the plan validator."""
from __future__ import annotations

from services.plan_validator import validate_plan


def _plan(fields: list[dict]) -> dict:
    return {
        "data_models": [
            {"name": "Transaction", "fields": [{"name": "id", "type": "uuid"}, *fields]}
        ]
    }


def _has(rule: str, violations: list[dict]) -> bool:
    return any(v.get("rule") == rule for v in violations)


def test_money_alone_passes():
    v = validate_plan(_plan([{"name": "amount", "type": "money"}]))
    assert not _has("money_currency_ambiguous", v)


def test_money_with_matching_sibling_passes():
    # `amount_currency` is exactly the derived sibling — silent accept.
    v = validate_plan(
        _plan([
            {"name": "amount", "type": "money"},
            {"name": "amount_currency", "type": "char"},
        ])
    )
    assert not _has("money_currency_ambiguous", v)


def test_money_with_alternate_currency_alias_fails():
    v = validate_plan(
        _plan([
            {"name": "amount", "type": "money"},
            {"name": "ccyCode", "type": "varchar"},
        ])
    )
    matching = [x for x in v if x["rule"] == "money_currency_ambiguous"]
    assert matching, v
    assert matching[0]["severity"] == "error"


def test_totalAmount_with_totalCurrency_predeclared_passes():
    v = validate_plan(
        _plan([
            {"name": "totalAmount", "type": "money"},
            {"name": "totalCurrency", "type": "char"},
        ])
    )
    assert not _has("money_currency_ambiguous", v)

"""Tests for the money-column contract in the deterministic schema builder.

`type: "money"` MUST always land as:
  * amount:   decimal(19,4).notNull() (or nullable when the plan says so)
  * sibling:  char(3).notNull().default('USD') — currency code

Sibling name derivation (all snake_case at the SQL column level, camelCase kept
at the TS field level):
  * `amount`        → sibling field `amount_currency`, column `amount_currency`
  * `totalAmount`   → sibling field `totalCurrency`,   column `total_currency`
  * `price_amount`  → sibling field `price_currency`,  column `price_currency`
  * `fee`           → sibling field `fee_currency`,    column `fee_currency`

Idempotent — the plan may pre-declare the derived sibling name.
"""
from __future__ import annotations

from services.schema_builder import (
    build_schema_files,
    _builder_for,
    _derive_currency_sibling_name,
    _default_currency_literal,
)


def _plan(fields: list[dict]) -> dict:
    return {
        "data_models": [
            {
                "name": "Transaction",
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    *fields,
                ],
            }
        ],
    }


# ── unit-level: type-mapper + sibling-name helper ─────────────────────────

def test_builder_for_money_emits_decimal_19_4():
    builder, args = _builder_for({"name": "amount", "type": "money"})
    assert builder == "decimal"
    assert args == '"amount", { precision: 19, scale: 4 }'


def test_builder_for_currency_alias_also_hits_money_branch():
    builder, args = _builder_for({"name": "price", "type": "currency"})
    assert builder == "decimal"
    assert "precision: 19" in args and "scale: 4" in args


def test_derive_currency_sibling_name_variants():
    assert _derive_currency_sibling_name("amount") == "amount_currency"
    assert _derive_currency_sibling_name("fee") == "fee_currency"
    assert _derive_currency_sibling_name("totalAmount") == "totalCurrency"
    assert _derive_currency_sibling_name("subtotalAmount") == "subtotalCurrency"
    assert _derive_currency_sibling_name("price_amount") == "price_currency"
    # Bare `Amount` / `_amount` (the whole name IS the token) → append, not swap
    # (avoids emitting a bare `Currency`/`_currency` root sibling).
    assert _derive_currency_sibling_name("Amount") == "Amount_currency"
    assert _derive_currency_sibling_name("_amount") == "_amount_currency"


def test_default_currency_literal_defaults_to_USD_and_honours_override():
    assert _default_currency_literal({}) == "USD"
    assert _default_currency_literal({"type": "money"}) == "USD"
    assert _default_currency_literal({"defaultCurrency": "eur"}) == "EUR"
    assert _default_currency_literal({"default_currency": "GBP"}) == "GBP"
    # 4-letter garbage falls back to USD.
    assert _default_currency_literal({"defaultCurrency": "XXXX"}) == "USD"


# ── integration: build_schema_files against a real plan ────────────────────

def test_money_column_emits_decimal_19_4(tmp_path):
    build_schema_files(_plan([{"name": "amount", "type": "money"}]), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "transactions.ts").read_text()
    assert 'decimal("amount", { precision: 19, scale: 4 })' in src


def test_money_column_emits_sibling_currency_column_defaulting_USD(tmp_path):
    build_schema_files(_plan([{"name": "amount", "type": "money"}]), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "transactions.ts").read_text()
    # sibling: char(3).notNull().default('USD') — banking's ISO-4217 slot
    assert 'amount_currency: char("amount_currency", { length: 3 }).notNull().default("USD")' in src
    # char is imported into the drizzle-orm/pg-core import line
    header = src.splitlines()[0]
    assert "char" in header


def test_money_sibling_name_swaps_trailing_Amount(tmp_path):
    build_schema_files(
        _plan([{"name": "totalAmount", "type": "money"}]), str(tmp_path)
    )
    src = (tmp_path / "src" / "db" / "schema" / "transactions.ts").read_text()
    assert 'totalCurrency: char("total_currency", { length: 3 })' in src
    # No stray `totalAmount_currency` — swap, not append.
    assert "totalAmount_currency" not in src


def test_money_sibling_name_swaps_trailing_snake_amount(tmp_path):
    build_schema_files(
        _plan([{"name": "price_amount", "type": "money"}]), str(tmp_path)
    )
    src = (tmp_path / "src" / "db" / "schema" / "transactions.ts").read_text()
    assert 'price_currency: char("price_currency", { length: 3 })' in src
    assert "price_amount_currency" not in src


def test_defaultCurrency_override_applies_to_sibling(tmp_path):
    build_schema_files(
        _plan([{"name": "amount", "type": "money", "defaultCurrency": "EUR"}]),
        str(tmp_path),
    )
    src = (tmp_path / "src" / "db" / "schema" / "transactions.ts").read_text()
    assert 'default("EUR")' in src


def test_money_amount_column_default_is_notNull(tmp_path):
    # The plan omits `nullable`/`not_null` — the AMOUNT column stays as the
    # planner wrote it (schema builder only forces .notNull() when the plan
    # explicitly says so, per the existing convention); the SIBLING is always
    # NOT NULL because a currency-less amount is a bank data-quality bug.
    build_schema_files(
        _plan([{"name": "amount", "type": "money", "nullable": False}]),
        str(tmp_path),
    )
    src = (tmp_path / "src" / "db" / "schema" / "transactions.ts").read_text()
    # amount is nullable:false → .notNull() present on the decimal line
    assert 'decimal("amount", { precision: 19, scale: 4 }).notNull()' in src
    # sibling always notNull
    assert 'char("amount_currency", { length: 3 }).notNull()' in src


def test_money_is_idempotent_when_plan_predeclares_sibling(tmp_path):
    # Plan already models an `amount_currency` char(3) → builder must NOT
    # emit a second currency column (that would be a duplicate identifier).
    build_schema_files(
        _plan([
            {"name": "amount", "type": "money"},
            {"name": "amount_currency", "type": "char", "length": 3, "nullable": False},
        ]),
        str(tmp_path),
    )
    src = (tmp_path / "src" / "db" / "schema" / "transactions.ts").read_text()
    # Only ONE amount_currency: line.
    assert src.count("amount_currency:") == 1

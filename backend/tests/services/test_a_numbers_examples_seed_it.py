"""A numeric field is seeded from its examples, as a text field is.

Only text took its examples; an integer was seeded as the row number, so a
price in minor units with examples 12500, 4500 became 1, 2, 3 cents and a
cart line with examples 1, 2, 1, 3 held 14 of a 7-stock coat — the subtotal
read US$0.00 and checkout was blocked (ECom L4, 7ttp60zi, 2026-10-11)."""
from __future__ import annotations

from services.blueprint.projection import _number, _seed_value


def test_an_integers_examples_are_its_seed_values():
    f = {"name": "priceOverrideCents", "type": "integer", "examples": ["8900", "3400", "12500"]}
    assert [_seed_value(f, "ProductVariant", r) for r in (1, 2, 3, 4)] == [8900, 3400, 12500, 8900]
    q = {"name": "quantity", "type": "integer", "examples": ["1", "2", "1", "3"]}
    assert [_seed_value(q, "CartItem", r) for r in (1, 2, 3, 4, 5)] == [1, 2, 1, 3, 1]


def test_a_decimals_examples_and_prose_examples():
    f = {"name": "commissionRate", "type": "decimal", "examples": ["12.5", "US$1,250.00"]}
    assert [_seed_value(f, "Vendor", r) for r in (1, 2)] == [12.5, 1250.0]
    assert _number("about ten") is None
    g = {"name": "count", "type": "integer", "examples": ["many"]}
    assert _seed_value(g, "X", 3) == 3                      # no number in the examples: the row, as before

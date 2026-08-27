"""The slug resolver must match an entity to its table in BOTH directions.

Folding only to singular cannot match an acronym entity to its table:
``SKU`` folds to ``sku`` (no trailing 's' to strip) while the table
``skus`` folds to ``skus`` (``-us`` reads as an already-singular latinate
ending, as it must for ``status`` and ``bus``). The two never meet.

Trying the plural direction as well closes it without touching
``entity_names.singularize``, whose ``-us`` pass-through is correct for the
words it protects. Live on pkiuqdrq, ``SKU`` accounted for 13 of the 39
quarantined bindings.
"""
from __future__ import annotations

import pytest

from services.binding_validator import _SlugResolver


def _tables(*consts):
    return [{"const": c, "arg": c, "columns": {}} for c in consts]


@pytest.fixture
def resolver():
    return _SlugResolver(_tables(
        "skus", "warehouses", "products", "categories",
        "stock_levels", "statuses", "buses",
    ))


@pytest.mark.parametrize("ref,expected", [
    ("SKU",         "skus"),          # acronym — only the plural direction matches
    ("sku",         "skus"),
    ("Warehouse",   "warehouses"),    # -e stem — needs the singularize fix
    ("Product",     "products"),
    ("Category",    "categories"),    # irregular y→ies
    ("StockLevel",  "stock_levels"),  # multi-word, separator-insensitive
    ("stock-levels", "stock_levels"),
    ("Status",      "statuses"),      # latinate -us stem
    ("Bus",         "buses"),
])
def test_entity_reference_resolves_to_its_table(resolver, ref, expected):
    assert resolver.resolve(ref) == expected


@pytest.mark.parametrize("ref", ["Nonexistent", "widgets", "", None, 42])
def test_unknown_references_stay_unresolved(resolver, ref):
    assert resolver.resolve(ref) is None


def test_plural_direction_does_not_invent_matches():
    """Pluralizing a ref must not collide with an unrelated table."""
    r = _SlugResolver(_tables("buses"))
    assert r.resolve("Bu") is None

"""singularize must be the inverse of pluralize — the property the module claims.

``entity_names`` documents itself as the single naming authority, and
``singularize``'s docstring promises the round-trip
``singularize(pluralize(w)) == singularize(w)`` "holds for every word this
module can produce, which is what lets entity_key join an entity to its
table without either side knowing how the other was spelled."

That promise was not kept for ``-e``-final stems: ``warehouse`` pluralized
to ``warehouses`` and singularized back to ``warehous``, so
``binding_validator``'s slug resolver could never match the entity
``Warehouse`` to the table ``warehouses``. Live on pkiuqdrq that was 11 of
39 quarantined bindings.
"""
from __future__ import annotations

import pytest

from services.entity_names import pluralize, singularize


# (singular, expected plural) — every shape the pluralizer handles.
ROUND_TRIP_WORDS = [
    ("product",   "products"),     # plain +s
    ("warehouse", "warehouses"),   # -e stem, plain +s  ← the regression
    ("location",  "locations"),
    ("supplier",  "suppliers"),
    ("category",  "categories"),   # consonant-y → ies
    ("day",       "days"),         # vowel-y → plain +s
    ("address",   "addresses"),    # -ss → es
    ("box",       "boxes"),        # -x → es
    ("dish",      "dishes"),       # -sh → es
    ("batch",     "batches"),      # -ch → es
    ("bus",       "buses"),        # single -s stem → es
    ("status",    "statuses"),     # latinate -us → es
]


@pytest.mark.parametrize("singular,plural", ROUND_TRIP_WORDS)
def test_pluralize_produces_the_expected_plural(singular, plural):
    assert pluralize(singular) == plural


@pytest.mark.parametrize("singular,plural", ROUND_TRIP_WORDS)
def test_singularize_inverts_pluralize(singular, plural):
    assert singularize(plural) == singular


@pytest.mark.parametrize("singular,plural", ROUND_TRIP_WORDS)
def test_round_trip_property_holds(singular, plural):
    # The exact property the docstring claims.
    assert singularize(pluralize(singular)) == singularize(singular)


# Words whose singular form ends in 's' must survive untouched — stripping
# them is what would turn 'status' into 'statu' and break the other
# direction. These are NOT plurals; passing them through is correct.
@pytest.mark.parametrize("word", ["status", "bus", "class", "address",
                                  "analysis", "basis", "campus", "virus"])
def test_already_singular_words_pass_through(word):
    assert singularize(word) == word


def test_warehouses_is_the_live_regression():
    """The specific failure behind the pkiuqdrq quarantine."""
    assert singularize("warehouses") == "warehouse"
    assert singularize("warehous") == "warehous"   # never re-strip

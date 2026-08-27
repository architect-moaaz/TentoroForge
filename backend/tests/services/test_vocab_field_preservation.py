"""Every vocabulary field survives a rebuild.

``ArchetypeVocabulary`` is a frozen dataclass whose every field defaults
to empty, and five places rebuild it field-by-field. That combination
fails silently: ``dashboard_recipe`` and ``page_recipes`` were added to
the dataclass and to the archetype files, but none of the five rebuilds
were updated, so both arrived empty at every consumer. The domain's
dashboard recipe and its per-entity column/sort recipes were authored,
cached to disk, and then dropped on the way back in.

Nothing failed — the fields just defaulted. So this guards the property
directly: populate every field, push it through each rebuild, and
require it back.
"""
from __future__ import annotations

from dataclasses import asdict, fields

import pytest

from services.archetype_vocabulary import ArchetypeVocabulary, ComponentPreference
from services.vocab_composer_pipeline import _deserialize_vocab as composer_load
from services.vocab_modifier_pipeline import _deserialize_vocab as modifier_load


def _fully_populated() -> ArchetypeVocabulary:
    """Every field non-empty, so an omission shows up as a loss."""
    return ArchetypeVocabulary(
        id="test-platform",
        primary_screens_per_persona={"picker": ["stock"]},
        section_recipes={"stock": ["low", "healthy"]},
        component_preferences={"stock": ComponentPreference(shape="table")},
        signature_states={"empty_stock": "Nothing on hand"},
        status_badges={"low": {"variant": "warning"}},
        section_filters={"low": {"status": "low"}},
        dashboard_recipe={"kpis": [{"label": "On hand", "entity": "stock",
                                    "op": "sum", "field": "qty"}]},
        page_recipes={"stock": {"list_columns": ["sku", "qty"],
                                "list_order": {"field": "qty", "dir": "asc"}}},
    )


def test_the_fixture_really_does_populate_every_field():
    """Guards the guard: a field added later must be added here too, or
    these round-trip tests would pass while ignoring it."""
    v = _fully_populated()
    empty = [f.name for f in fields(ArchetypeVocabulary)
             if not getattr(v, f.name)]
    assert empty == [], f"fixture leaves {empty} empty — extend it"


@pytest.mark.parametrize("load", [composer_load, modifier_load],
                         ids=["composer-cache", "modifier-cache"])
def test_cache_round_trip_loses_nothing(load):
    """The write side is ``asdict`` — it always wrote all nine fields.
    Only the read side dropped them, so a disk cache written before this
    fix already holds the data a re-read will now recover."""
    original = _fully_populated()
    restored = load(asdict(original))
    for f in fields(ArchetypeVocabulary):
        assert getattr(restored, f.name) == getattr(original, f.name), (
            f"{f.name} did not survive {load.__module__}")


def test_modifier_passes_through_what_it_does_not_modify():
    """The modifier rewrites personas/screens/badges; it has no opinion
    on the two recipe fields and must hand them back untouched."""
    from services.vocab_modifier import _merge_and_validate

    base = _fully_populated()
    modified, _changes = _merge_and_validate(base, {})
    assert modified.dashboard_recipe == base.dashboard_recipe
    assert modified.page_recipes == base.page_recipes

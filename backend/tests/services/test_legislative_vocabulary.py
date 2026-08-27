"""The legislative vocabulary, and the slug gap it exposed.

A vocabulary file is inert until three things are true: it is in the
registry, the keyword detector can name it, and the name the detector
emits actually resolves. The third was false for every archetype — the
detector says "inventory" and "legislative" while the registry is keyed
"inventory-platform", so load_vocabulary returned None and callers took
the silent no-vocabulary path.
"""
from __future__ import annotations

import pytest

from services.archetype_vocabulary import (
    KNOWN_SHAPES, load_vocabulary, known_archetypes, match_entity_name,
)
from services.page_vocabulary import resolve_page_recipe
from services.plan_directive_parser import _ARCHETYPE_KEYWORDS, detect_vocab_archetype

VOCAB_ID = "legislative-platform"


def _vocab():
    v = load_vocabulary(VOCAB_ID)
    assert v is not None, "legislative vocabulary is not registered"
    return v


# ── the three registration points ──────────────────────────────────

def test_it_is_in_the_registry():
    assert VOCAB_ID in known_archetypes()


@pytest.mark.parametrize("prompt", [
    "a city council agenda management system",
    "bill tracking for the state legislature",
    "ordinance and public meeting portal",
    "municipal clerk minutes and roll call vote records",
])
def test_the_detector_recognises_the_domain(prompt):
    """Returns the canonical registry id, not the short slug it used to.

    The short slug only reached the registry through a suffix fallback in
    load_vocabulary; every consumer now gets the id the registry is
    actually keyed on."""
    assert detect_vocab_archetype(prompt) == VOCAB_ID


def test_every_detector_slug_resolves_to_a_vocabulary():
    """The gap this file exists for. The detector's key and the
    registry's key are different strings for every archetype; if the
    loader does not bridge them the whole archetype layer looks wired
    and silently is not."""
    unresolved = [s for s in _ARCHETYPE_KEYWORDS if load_vocabulary(s) is None]
    assert unresolved == [], f"detector slugs that resolve to nothing: {unresolved}"


def test_the_short_slug_and_the_full_id_reach_the_same_vocabulary():
    assert load_vocabulary("legislative") is load_vocabulary(VOCAB_ID)


def test_an_unknown_archetype_still_returns_none():
    """The suffix fallback must not turn every typo into a match."""
    assert load_vocabulary("not-a-real-domain") is None
    assert load_vocabulary("") is None
    assert load_vocabulary(None) is None


# ── the content is legal ───────────────────────────────────────────

def test_every_declared_shape_is_one_the_composer_knows():
    bad = {e: p.shape for e, p in _vocab().component_preferences.items()
           if p.shape not in KNOWN_SHAPES}
    assert bad == {}, f"unknown shapes: {bad}"


def test_every_section_named_in_a_recipe_has_a_filter_entry():
    """A section with no filter entry renders as an unfiltered dupe of
    the list above it."""
    v = _vocab()
    named = {s for sections in v.section_recipes.values() for s in sections}
    missing = sorted(named - set(v.section_filters))
    assert missing == [], f"sections with no filter declared: {missing}"


def test_all_nine_fields_are_populated():
    """This is the "cover everything" contract — a vocabulary with holes
    silently falls back to generic composition for whatever it omits."""
    v = _vocab()
    for field in ("primary_screens_per_persona", "section_recipes",
                  "component_preferences", "signature_states",
                  "status_badges", "section_filters", "dashboard_recipe",
                  "page_recipes"):
        assert getattr(v, field), f"{field} is empty"


# ── the domain decisions, pinned ───────────────────────────────────

def test_bills_are_a_stage_pipeline():
    """The defining choice. A legislative app that renders bills as a
    flat table has lost the plot."""
    assert _vocab().component_preferences["bills"].shape == "kanban"


def test_votes_are_an_append_only_ledger():
    assert _vocab().component_preferences["votes"].shape == "ledger-list"


def test_agenda_items_declare_no_sort_order():
    """Item 1, 2, 3 is a sequence the clerk sets. A domain default here
    would silently reorder a legal document."""
    assert "list_order" not in _vocab().page_recipes["agenda_items"]


def test_bills_lead_with_what_is_about_to_lapse():
    order = _vocab().page_recipes["bills"]["list_order"]
    assert order["dir"] == "asc"
    assert "nextActionDate" in order["field"]


def test_votes_lead_with_recency_because_that_is_the_question():
    """Proves list_order is a domain judgement, not a standing bias
    against dates."""
    order = _vocab().page_recipes["votes"]["list_order"]
    assert order["dir"] == "desc"
    assert "voteDate" in order["field"]


def test_both_halves_of_the_domain_are_named():
    """Legislature and municipal council share a shape and diverge on
    words; an app will use one set or the other."""
    recipes = _vocab().page_recipes
    for legislature, council in (("bills", "ordinances"),
                                 ("hearings", "meetings")):
        assert legislature in recipes and council in recipes


def test_the_public_gets_real_screens():
    """Sunshine laws make the public record an obligation, not a page."""
    screens = _vocab().primary_screens_per_persona.get("public") or []
    assert len(screens) >= 3


# ── it binds to a real app ─────────────────────────────────────────

def test_a_recipe_binds_to_an_app_that_spells_the_entity_its_own_way():
    entity = {"fields": [{"name": n, "type": "text"} for n in
                         ("id", "billNumber", "title", "sponsor", "stage",
                          "committee", "nextActionDate")]}
    r = resolve_page_recipe(_vocab(), "Bill", entity)
    assert r["list_columns"][0] == "billNumber"
    assert r["list_order"] == {"field": "nextActionDate", "dir": "asc"}


def test_a_column_the_app_lacks_is_dropped_from_the_order():
    entity = {"fields": [{"name": n, "type": "text"}
                         for n in ("id", "billNumber", "title")]}
    r = resolve_page_recipe(_vocab(), "Bill", entity)
    assert not r.get("list_order")


def test_entity_name_matching_reaches_the_recipe():
    keys = list(_vocab().page_recipes)
    assert match_entity_name("AgendaItem", keys) == "agenda_items"
    assert match_entity_name("Vote", keys) == "votes"

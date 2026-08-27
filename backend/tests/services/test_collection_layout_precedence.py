"""Who decides a collection's layout — the author or the vocabulary?

Both, and that was the problem. The archetype vocabulary reaches the maquette
author at authoring time (``resolve_page_recipe`` puts its reading order in
the prompt) and then overrode the result again at apply time. One authority,
two votes: the author was briefed by the vocabulary, made a judgment shaped
by it, and the same vocabulary overwrote the judgment it had just caused.
Anything the author added on top — a montage-informed shape, a data-shaped
call — was flattened.

The rule now: the vocabulary briefs, and it still decides when the author
expressed nothing. ``"table"`` is what a maquette carries when its author had
no opinion, so a vocabulary preference still wins there — which keeps every
existing convention working (a booking-platform's ``bookings`` still becomes
a card-list). But a deliberate pick — kanban, calendar, cards, timeline — is
a real judgment about this app's data, and it stands.

Data fitness is a separate, later veto and still outranks both: a kanban with
no status column falls back to a table downstream regardless of who chose it.
"""
from __future__ import annotations

import pytest

from services.apply_collection_maquette import _resolve_layout


class TestTheVocabularyStillDecidesWhenTheAuthorDidNot:
    def test_default_table_yields_to_a_vocabulary_preference(self):
        layout, _ = _resolve_layout("table", "card-list")
        assert layout == "card-list"

    def test_a_missing_layout_yields_too(self):
        layout, _ = _resolve_layout(None, "schedule-grid")
        assert layout == "schedule-grid"

    def test_the_booking_convention_still_holds(self):
        """SL2-2's whole point: bookings become a card-list, not a table."""
        assert _resolve_layout("table", "card-list")[0] == "card-list"


class TestADeliberatePickSurvives:
    @pytest.mark.parametrize("authored", ["kanban", "calendar", "cards", "timeline"])
    def test_the_author_beats_the_vocabulary(self, authored):
        layout, _ = _resolve_layout(authored, "card-list")
        assert layout == authored

    def test_the_reason_names_the_preference_that_was_declined(self):
        """The override used to be logged; declining to override must be too,
        or a surprising layout becomes unexplainable."""
        _, why = _resolve_layout("kanban", "card-list")
        assert "card-list" in why


class TestNoPreferenceChangesNothing:
    def test_authored_layout_passes_through(self):
        assert _resolve_layout("calendar", None)[0] == "calendar"

    def test_nothing_at_all_is_a_table(self):
        assert _resolve_layout(None, None)[0] == "table"

    def test_an_empty_preference_is_not_a_preference(self):
        assert _resolve_layout("table", "")[0] == "table"

    def test_a_preference_identical_to_the_layout_is_a_no_op(self):
        layout, why = _resolve_layout("cards", "cards")
        assert layout == "cards"
        assert "declined" not in why

"""Tests for services.empty_state_library — SL2-3.

Pins the resolver contract composers rely on: route slug wins over
entity slug, dict-shape values pass through, string values split
into (headline, subhead) on the first sentence boundary, and every
"vocabulary absent / entry absent" path returns an empty dict so
callers keep their legacy default behaviour.
"""
from __future__ import annotations

import pytest

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    load_vocabulary,
)
from services.empty_state_library import (
    _extract_route_slug,
    _resolve_state_key,
    _split_headline_subhead,
    resolve_empty_state,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _vocab_with(**states: str) -> ArchetypeVocabulary:
    return ArchetypeVocabulary(id="test", signature_states=dict(states))


# ── _extract_route_slug ──────────────────────────────────────────────


class TestExtractRouteSlug:
    def test_leading_slash_stripped(self):
        assert _extract_route_slug("/my-bookings") == "my-bookings"

    def test_nested_path_returns_first_segment(self):
        # Parent scope wins — deeper role-scoping is done by the caller
        # via the parent slug, not by looking at the leaf.
        assert _extract_route_slug("/admin/classes") == "admin"

    def test_bare_slug(self):
        assert _extract_route_slug("schedule") == "schedule"

    def test_trailing_slash_trimmed(self):
        assert _extract_route_slug("/reviews/") == "reviews"

    def test_uppercase_lowered(self):
        assert _extract_route_slug("/Bookings") == "bookings"

    def test_none_or_empty_returns_empty_string(self):
        assert _extract_route_slug(None) == ""
        assert _extract_route_slug("") == ""
        assert _extract_route_slug("   ") == ""
        assert _extract_route_slug("/") == ""


# ── _resolve_state_key ───────────────────────────────────────────────


class TestResolveStateKey:
    def test_explicit_key_wins(self):
        # Explicit key beats route + entity lookups.
        assert (_resolve_state_key("bookings", "/schedule",
                                   explicit_key="empty_membership")
                == "empty_membership")

    def test_explicit_key_stripped(self):
        assert (_resolve_state_key("", None, explicit_key="  empty_x  ")
                == "empty_x")

    def test_route_beats_entity(self):
        # Entity slug "bookings" would resolve to empty_bookings, but a
        # route of /schedule should give empty_schedule instead — route
        # is more specific about the *screen* than entity about the
        # *domain*.
        assert (_resolve_state_key("bookings", "/schedule",
                                   explicit_key=None)
                == "empty_schedule")

    def test_entity_used_when_route_absent(self):
        assert (_resolve_state_key("bookings", None, explicit_key=None)
                == "empty_bookings")
        assert (_resolve_state_key("reviews", "", explicit_key=None)
                == "empty_reviews")

    def test_snake_case_entity_normalises(self):
        # class_sessions doesn't match a route key but "class-sessions"
        # after normalisation still doesn't. Instead we exercise a slug
        # that DOES match — the normaliser handles hyphen/underscore.
        assert (_resolve_state_key("My_Bookings", None, explicit_key=None)
                == "empty_bookings")

    def test_unknown_returns_none(self):
        assert _resolve_state_key("widgets", "/random", None) is None

    def test_empty_inputs_return_none(self):
        assert _resolve_state_key("", "", None) is None
        assert _resolve_state_key("", None, None) is None


# ── _split_headline_subhead ──────────────────────────────────────────


class TestSplitHeadlineSubhead:
    def test_two_sentence_split(self):
        out = _split_headline_subhead(
            "No sessions this day. Try another date — new sessions "
            "are added weekly."
        )
        assert out["headline"] == "No sessions this day."
        assert out["subhead"].startswith("Try another date")

    def test_split_preserves_headline_punctuation(self):
        out = _split_headline_subhead("Wow! It works. Great.")
        # First sentence ends at "Wow!" — the split happens on the
        # first sentence terminator followed by whitespace.
        assert out["headline"] == "Wow!"

    def test_single_sentence_has_no_subhead(self):
        out = _split_headline_subhead("Nothing here yet.")
        assert out["headline"] == "Nothing here yet."
        assert "subhead" not in out

    def test_question_terminator_splits(self):
        out = _split_headline_subhead("Where did they go? Check the archive.")
        assert out["headline"] == "Where did they go?"
        assert out["subhead"] == "Check the archive."

    def test_no_terminator_stays_whole(self):
        # No period → treat as single headline.
        out = _split_headline_subhead("No sessions this day")
        assert out == {"headline": "No sessions this day"}

    def test_trailing_whitespace_trimmed(self):
        out = _split_headline_subhead("A. B  ")
        assert out["headline"] == "A."
        assert out["subhead"] == "B"


# ── resolve_empty_state ──────────────────────────────────────────────


class TestResolveEmptyState:
    def test_none_vocab_returns_empty(self):
        assert resolve_empty_state(None, "bookings", "/bookings") == {}

    def test_vocab_without_states_returns_empty(self):
        v = ArchetypeVocabulary(id="test")  # signature_states={}
        assert resolve_empty_state(v, "bookings", "/bookings") == {}

    def test_string_copy_splits_into_headline_subhead(self):
        v = _vocab_with(empty_bookings="No bookings yet. Browse the schedule.")
        out = resolve_empty_state(v, "bookings", None)
        assert out["headline"] == "No bookings yet."
        assert out["subhead"] == "Browse the schedule."

    def test_dict_copy_passes_through(self):
        # Vocabularies may store structured entries per key. All four
        # allowed fields must round-trip.
        v = ArchetypeVocabulary(id="test", signature_states={
            "empty_bookings": {
                "headline": "Nothing on your list.",
                "subhead": "Reserve your first spot.",
                "cta_label": "Browse schedule",
                "cta_action": "/schedule",
            },
        })
        out = resolve_empty_state(v, "bookings", None)
        assert out == {
            "headline": "Nothing on your list.",
            "subhead": "Reserve your first spot.",
            "cta_label": "Browse schedule",
            "cta_action": "/schedule",
        }

    def test_dict_copy_drops_non_string_and_blank_fields(self):
        v = ArchetypeVocabulary(id="test", signature_states={
            "empty_bookings": {
                "headline": "Real headline.",
                "subhead": "",            # blank drops
                "cta_label": None,        # None drops
                "cta_action": 42,         # non-string drops
                "unrelated": "leave me",  # unknown key drops
            },
        })
        out = resolve_empty_state(v, "bookings", None)
        assert out == {"headline": "Real headline."}

    def test_route_slug_wins_over_entity(self):
        v = _vocab_with(
            empty_schedule="No sessions this day. Try another date.",
            empty_bookings="No bookings yet. Browse the schedule.",
        )
        # Entity=bookings, route=/schedule → should get schedule copy.
        out = resolve_empty_state(v, "bookings", "/schedule")
        assert out["headline"] == "No sessions this day."

    def test_explicit_key_wins_over_both(self):
        v = _vocab_with(
            empty_schedule="Schedule copy. Yes.",
            empty_bookings="Bookings copy. Yes.",
            no_results="No matches. Widen filters.",
        )
        out = resolve_empty_state(v, "bookings", "/schedule",
                                  explicit_key="no_results")
        assert out["headline"] == "No matches."

    def test_missing_key_returns_empty(self):
        # Entity + route both resolve to keys we haven't populated.
        v = _vocab_with(empty_schedule="Copy.")
        out = resolve_empty_state(v, "widgets", "/widgets")
        assert out == {}

    def test_string_with_only_headline_no_subhead(self):
        v = _vocab_with(empty_bookings="No bookings yet")
        out = resolve_empty_state(v, "bookings", None)
        assert out == {"headline": "No bookings yet"}


# ── Integration: reference booking-platform vocabulary ───────────────


class TestBookingPlatformResolution:
    """Pins that the shipped booking-platform vocabulary + resolver
    combine to produce the copy we want on the yoga app."""

    def _vocab(self):
        v = load_vocabulary("booking-platform")
        assert v is not None
        return v

    def test_schedule_route_gets_schedule_copy(self):
        out = resolve_empty_state(self._vocab(), "class_sessions", "/schedule")
        assert out["headline"].startswith("No sessions")
        assert "subhead" in out

    def test_my_bookings_route_gets_bookings_copy(self):
        out = resolve_empty_state(self._vocab(), "bookings", "/my-bookings")
        assert "haven't booked" in out["headline"] or "haven't booked" in out.get("subhead", "")

    def test_reviews_route_gets_reviews_copy(self):
        out = resolve_empty_state(self._vocab(), "reviews", "/reviews")
        assert "review" in out["headline"].lower()

    def test_no_results_via_explicit_key(self):
        # A filter-chip widening scenario: composer knows the moment.
        out = resolve_empty_state(self._vocab(), "bookings", "/bookings",
                                  explicit_key="no_results")
        assert "No matches" in out["headline"]

    def test_unknown_entity_and_route_returns_empty(self):
        # A random entity the vocabulary doesn't cover — composer
        # falls back to its legacy default (mechanical TXT-1 copy).
        out = resolve_empty_state(self._vocab(), "widgets", "/widgets")
        assert out == {}

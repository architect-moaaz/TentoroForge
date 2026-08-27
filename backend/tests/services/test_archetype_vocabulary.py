"""Tests for services.archetype_vocabulary — SL2-1.

The vocabulary module is the load-bearing input for every Slice 2
composer patch. These tests pin the contract each downstream consumer
relies on:

  - canonical slug lookup (case + separator normalisation)
  - safe defaults on empty vocabulary + missing entries
  - context-scoped component preferences (admin vs member on the
    same entity)
  - the reference booking-platform vocabulary declares the entries
    the yoga app needs
"""
from __future__ import annotations

import pytest

from services import archetype_vocabulary as av
from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
    KNOWN_SHAPES,
    _canonical_slug,
    clear_cache,
    component_preference,
    known_archetypes,
    load_vocabulary,
)


class TestCanonicalSlug:
    def test_lowercase_hyphenated(self):
        assert _canonical_slug("Booking Platform") == "booking-platform"

    def test_snake_case_maps_to_kebab(self):
        assert _canonical_slug("booking_platform") == "booking-platform"

    def test_already_kebab_kept(self):
        assert _canonical_slug("booking-platform") == "booking-platform"

    def test_mixed_punctuation_collapsed(self):
        assert _canonical_slug("Booking / Platform!") == "booking-platform"

    def test_empty_and_none_safe(self):
        assert _canonical_slug("") == ""
        assert _canonical_slug(None) == ""  # type: ignore
        assert _canonical_slug("   ") == ""


class TestRegistry:
    def setup_method(self):
        clear_cache()

    def test_booking_platform_registered(self):
        assert "booking-platform" in known_archetypes()

    def test_load_by_canonical_slug(self):
        vocab = load_vocabulary("booking-platform")
        assert vocab is not None
        assert vocab.id == "booking-platform"

    def test_load_normalises_input(self):
        # "Booking Platform" / "booking_platform" / "Booking-Platform"
        # all resolve to the same vocabulary.
        for input_str in ("Booking Platform", "booking_platform",
                          "Booking-Platform", "BOOKING PLATFORM"):
            vocab = load_vocabulary(input_str)
            assert vocab is not None, input_str
            assert vocab.id == "booking-platform", input_str

    def test_load_unknown_returns_none(self):
        # An archetype we haven't built a vocabulary for yet → None,
        # not an exception. Callers branch on this.
        #
        # "crm" used to be one of these examples and no longer is: a CRM
        # vocabulary exists, and the loader now bridges the short slug
        # callers actually pass ("crm", "inventory", "legislative") to
        # the registry's full id. Both halves of that are deliberate, so
        # the examples here have to be domains nobody has built.
        assert load_vocabulary("ecommerce") is None
        assert load_vocabulary("legal-case-mgmt") is None
        assert load_vocabulary("veterinary") is None

    def test_the_short_slug_bridge_is_not_a_wildcard(self):
        """The -platform fallback must only fire for real vocabularies,
        never turn an unknown domain into a wrong match."""
        assert load_vocabulary("crm") is not None      # crm-platform
        assert load_vocabulary("nonsense") is None

    def test_load_empty_input_returns_none(self):
        assert load_vocabulary("") is None
        assert load_vocabulary(None) is None
        assert load_vocabulary("   ") is None


class TestArchetypeVocabularyDataClass:
    def test_defaults_are_empty_dicts(self):
        v = ArchetypeVocabulary(id="test")
        assert v.primary_screens_per_persona == {}
        assert v.section_recipes == {}
        assert v.component_preferences == {}
        assert v.signature_states == {}
        assert v.status_badges == {}

    def test_frozen(self):
        v = ArchetypeVocabulary(id="test")
        with pytest.raises(Exception):
            v.id = "modified"  # type: ignore


class TestComponentPreferenceHelper:
    def _vocab_with_admin_scoped(self) -> ArchetypeVocabulary:
        return ArchetypeVocabulary(
            id="test",
            component_preferences={
                "members": ComponentPreference(shape="table", context="studio_admin"),
                "bookings": ComponentPreference(shape="card-list", primary_field="name"),
            },
        )

    def test_none_vocab_returns_none(self):
        assert component_preference(None, "anything") is None

    def test_unknown_entity_returns_none(self):
        v = self._vocab_with_admin_scoped()
        assert component_preference(v, "widgets") is None

    def test_context_free_entity_returns_for_any_role(self):
        v = self._vocab_with_admin_scoped()
        assert component_preference(v, "bookings", persona_role="member") is not None
        assert component_preference(v, "bookings", persona_role="admin") is not None
        assert component_preference(v, "bookings", persona_role="") is not None

    def test_admin_scoped_entity_hides_from_other_roles(self):
        v = self._vocab_with_admin_scoped()
        # Members table meant for admin: a Member persona should NOT
        # pick up "table" here — the composer will fall back to its
        # own default.
        assert component_preference(v, "members", persona_role="member") is None
        assert component_preference(v, "members", persona_role="instructor") is None

    def test_admin_scoped_entity_returns_for_matching_role(self):
        v = self._vocab_with_admin_scoped()
        pref = component_preference(v, "members", persona_role="studio_admin")
        assert pref is not None
        assert pref.shape == "table"

    def test_context_matching_is_case_insensitive(self):
        v = self._vocab_with_admin_scoped()
        assert component_preference(v, "members", persona_role="STUDIO_ADMIN") is not None
        assert component_preference(v, "members", persona_role="Studio_Admin") is not None


class TestEntityLookupNormalization:
    """Planners emit entity names in varied casing/inflection.

    The vocabulary keys are the canonical lowercase plural.
    ``component_preference`` must match all of these to the same key.
    """

    def _vocab(self) -> ArchetypeVocabulary:
        return ArchetypeVocabulary(
            id="test",
            component_preferences={
                "bookings":       ComponentPreference(shape="card-list"),
                "class_sessions": ComponentPreference(shape="schedule-grid"),
                "instructors":    ComponentPreference(shape="card-grid"),
            },
        )

    def test_capitalized_singular_matches(self):
        # `Booking` (planner-emitted) → vocab key `bookings`.
        v = self._vocab()
        assert component_preference(v, "Booking").shape == "card-list"
        assert component_preference(v, "Instructor").shape == "card-grid"

    def test_lowercase_singular_matches(self):
        v = self._vocab()
        assert component_preference(v, "booking").shape == "card-list"

    def test_camelcase_matches_snake_case_key(self):
        # `ClassSession` → snake_case `class_session` → +s → `class_sessions`.
        v = self._vocab()
        assert component_preference(v, "ClassSession").shape == "schedule-grid"

    def test_camelcase_plural_still_matches(self):
        v = self._vocab()
        assert component_preference(v, "ClassSessions").shape == "schedule-grid"

    def test_direct_hit_still_works(self):
        v = self._vocab()
        assert component_preference(v, "bookings").shape == "card-list"

    def test_totally_unknown_returns_none(self):
        v = self._vocab()
        assert component_preference(v, "Widget") is None


class TestBookingPlatformReferenceContent:
    """Pins that the reference vocabulary declares what the yoga app needs.

    If any of these fail, either the vocabulary lost content OR a
    real downstream consumer stopped needing it (in which case remove
    the test with the change).
    """

    def setup_method(self):
        clear_cache()

    def _vocab(self) -> ArchetypeVocabulary:
        v = load_vocabulary("booking-platform")
        assert v is not None
        return v

    def test_all_three_personas_have_screens(self):
        v = self._vocab()
        assert "member" in v.primary_screens_per_persona
        assert "instructor" in v.primary_screens_per_persona
        assert ("studio_admin" in v.primary_screens_per_persona
                or "admin" in v.primary_screens_per_persona)

    def test_member_primary_screens_match_claude_demo(self):
        # The four member tabs from the Claude yoga demo:
        # Schedule / My Bookings / Membership / My Reviews.
        v = self._vocab()
        screens = v.primary_screens_per_persona["member"]
        assert "schedule" in screens
        assert "my-bookings" in screens
        assert "membership" in screens
        assert "reviews" in screens

    def test_bookings_shape_is_card_list(self):
        v = self._vocab()
        pref = v.component_preferences.get("bookings")
        assert pref is not None
        assert pref.shape == "card-list"

    def test_instructors_shape_is_card_grid(self):
        v = self._vocab()
        pref = v.component_preferences.get("instructors")
        assert pref is not None
        assert pref.shape == "card-grid"

    def test_sessions_shape_is_schedule_grid(self):
        # class_sessions is the yoga app's actual entity name.
        v = self._vocab()
        pref = (v.component_preferences.get("class_sessions")
                or v.component_preferences.get("sessions"))
        assert pref is not None
        assert pref.shape == "schedule-grid"

    def test_members_stays_a_table_but_only_for_admin(self):
        v = self._vocab()
        pref = v.component_preferences.get("members")
        assert pref is not None
        assert pref.shape == "table"
        assert pref.context.lower() in ("admin", "studio_admin")

    def test_my_bookings_splits_upcoming_past(self):
        v = self._vocab()
        sections = v.section_recipes.get("my-bookings")
        assert sections is not None
        assert "upcoming" in sections
        assert "past" in sections
        # Order matters — upcoming should be shown first.
        assert sections.index("upcoming") < sections.index("past")

    def test_empty_state_copy_is_present_for_common_screens(self):
        v = self._vocab()
        # These are the empty states any booking-app member view can hit.
        for key in ("empty_schedule", "empty_bookings", "empty_reviews",
                    "empty_upcoming", "empty_past", "no_results"):
            assert key in v.signature_states, key
            assert v.signature_states[key], f"{key} has empty copy"

    def test_status_badges_cover_lifecycle(self):
        v = self._vocab()
        # These are the visible statuses on booking rows.
        for status in ("attended", "no_show", "cancelled",
                       "confirmed", "waitlisted"):
            assert status in v.status_badges, status
            assert "variant" in v.status_badges[status]

    def test_all_declared_shapes_are_known(self):
        # Guard: a typo in the vocabulary (e.g. "card_list" instead of
        # "card-list") would silently make the composer fall back to
        # table. Fail fast on unknown shapes.
        v = self._vocab()
        for entity, pref in v.component_preferences.items():
            assert pref.shape in KNOWN_SHAPES, (
                f"entity {entity!r} declares unknown shape {pref.shape!r} "
                f"— must be one of {sorted(KNOWN_SHAPES)}"
            )

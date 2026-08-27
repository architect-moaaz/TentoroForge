"""Tests for services.product_brief — PB-1.

The product brief is the missing input for "beautiful app" generation
(Path B commitment). Every test pins one behaviour so a regression
reads as a single legible failure. Focus areas:

- ``_humanize_role``: RBAC role slugs → product-friendly labels
- ``_slug``: label → kebab-case id (matches downstream key style)
- ``_jobs_from_responsibilities``: prose + journeys → deduped Job list
- ``_personas_from_plan``: end-to-end derivation from realistic plan
- ``_voice_from_design_brief``: brief tone → copy-voice adjectives
- ``derive_from_plan``: full ProductBrief composition
- Persistence round-trip on disk
- Env-gate helper
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import product_brief
from services.product_brief import (
    Brand,
    Job,
    Persona,
    ProductBrief,
    VoiceNotes,
    _humanize_role,
    _jobs_from_responsibilities,
    _personas_from_plan,
    _slug,
    _voice_from_design_brief,
    derive_from_plan,
    is_product_brief_enabled,
    load_product_brief_from_disk,
    save_product_brief,
)


# ── env gate ─────────────────────────────────────────────────────────


class TestFlag:
    def test_off_by_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("FORGE_PRODUCT_BRIEF", raising=False)
        assert is_product_brief_enabled() is False

    def test_on_with_truthy_values(self, monkeypatch: pytest.MonkeyPatch):
        for val in ("1", "true", "yes", "on", "TRUE", "On"):
            monkeypatch.setenv("FORGE_PRODUCT_BRIEF", val)
            assert is_product_brief_enabled() is True, val

    def test_off_with_falsy_values(self, monkeypatch: pytest.MonkeyPatch):
        for val in ("0", "false", "no", "off", "", "  "):
            monkeypatch.setenv("FORGE_PRODUCT_BRIEF", val)
            assert is_product_brief_enabled() is False, val


# ── humanize + slug ──────────────────────────────────────────────────


class TestHumanize:
    def test_snake_case_role(self):
        assert _humanize_role("studio_admin") == "Studio Admin"

    def test_camel_case_role(self):
        assert _humanize_role("studioAdmin") == "Studio Admin"

    def test_synonym_lookup(self):
        # "admin" maps through the synonym table to "Admin", not "admin"
        assert _humanize_role("admin") == "Admin"
        assert _humanize_role("member") == "Member"
        assert _humanize_role("instructor") == "Instructor"

    def test_unknown_role_capitalizes(self):
        assert _humanize_role("physiotherapist") == "Physiotherapist"

    def test_empty_or_none_defaults_to_user(self):
        assert _humanize_role("") == "User"
        assert _humanize_role("   ") == "User"
        assert _humanize_role(None) == "User"  # type: ignore

    def test_multi_word_synonyms(self):
        # front-desk staff → "Front Desk Staff"
        assert _humanize_role("front-desk-staff") == "Front Desk Staff"


class TestSlug:
    def test_basic(self):
        assert _slug("Book a Class") == "book-a-class"

    def test_punctuation(self):
        assert _slug("Manage / Configure Rooms") == "manage-configure-rooms"

    def test_empty(self):
        assert _slug("") == "x"


# ── jobs from responsibilities + journeys ───────────────────────────


class TestJobsFromResponsibilities:
    def test_verb_hints_matched(self):
        resp = [
            "Browse the class schedule",
            "Book a Vinyasa session with their preferred instructor",
            "Leave post-class reviews",
        ]
        jobs = _jobs_from_responsibilities(resp, [])
        job_ids = {j.id for j in jobs}
        assert "browse" in job_ids
        assert "book" in job_ids
        assert "reviews" in job_ids

    def test_no_matches_returns_empty(self):
        # No known verb hint fires — no jobs from responsibilities.
        jobs = _jobs_from_responsibilities(["Exists in the system"], [])
        assert jobs == []

    def test_journeys_become_jobs(self):
        journeys = [
            {"name": "Book a class", "steps": [{"page": "/classes"}, {"page": "/checkout"}]},
            {"name": "Cancel a booking", "steps": [{"page": "/bookings"}]},
        ]
        jobs = _jobs_from_responsibilities([], journeys)
        job_ids = {j.id for j in jobs}
        assert "book-a-class" in job_ids
        assert "cancel-a-booking" in job_ids

    def test_journey_primary_entities_extracted_from_step_pages(self):
        journeys = [{
            "name": "Manage bookings",
            "steps": [
                {"page": "/bookings"},
                {"page": "/bookings/new"},
                {"page": "/schedule"},
            ],
        }]
        jobs = _jobs_from_responsibilities([], journeys)
        j = jobs[0]
        # First-segment slugs from the pages, deduped, preserving order.
        assert j.primary_entities == ["bookings", "schedule"]

    def test_capped_at_five(self):
        # Too many verbs + journeys → capped to keep nav-tabs legible
        resp = [
            "browse the schedule",
            "book classes",
            "manage bookings",
            "leave reviews",
            "track attendance",
            "monitor progress",
            "view analytics",
        ]
        jobs = _jobs_from_responsibilities(resp, [])
        assert len(jobs) <= 5

    def test_dedupe_between_responsibility_and_journey(self):
        # A responsibility mentions "review" AND a journey named "Reviews"
        # should NOT produce two Review jobs — the id de-dupes them.
        resp = ["Leave a review after class"]
        journeys = [{"name": "Reviews", "steps": [{"page": "/reviews"}]}]
        jobs = _jobs_from_responsibilities(resp, journeys)
        review_jobs = [j for j in jobs if j.id == "reviews"]
        assert len(review_jobs) == 1


# ── personas from plan ──────────────────────────────────────────────


class TestPersonasFromPlan:
    def _yoga_plan(self) -> dict:
        # Miniature of a realistic yoga-studio plan (mirrors what
        # ACTORS-B + JT-T1 would emit).
        return {
            "actors": [
                {
                    "name": "Member",
                    "role": "member",
                    "responsibilities": [
                        "Browse the class schedule",
                        "Book classes with their preferred instructor",
                        "Manage their bookings and membership plan",
                        "Leave post-class reviews",
                    ],
                },
                {
                    "name": "Instructor",
                    "role": "instructor",
                    "responsibilities": [
                        "Set their weekly availability",
                        "View their upcoming classes",
                        "Track student attendance",
                    ],
                },
                {
                    "name": "Studio Admin",
                    "role": "studio_admin",
                    "responsibilities": [
                        "Manage instructors, class sessions, rooms, membership plans",
                        "View analytics on bookings and revenue",
                    ],
                },
            ],
            "journeys": [
                {"name": "Book a class", "primary_actor": "member",
                 "steps": [{"page": "/schedule"}, {"page": "/bookings/new"}]},
                {"name": "Leave a review", "primary_actor": "member",
                 "steps": [{"page": "/bookings"}, {"page": "/reviews/new"}]},
                {"name": "Set availability", "primary_actor": "instructor",
                 "steps": [{"page": "/instructor/availability"}]},
            ],
        }

    def test_one_persona_per_actor(self):
        personas = _personas_from_plan(self._yoga_plan())
        assert len(personas) == 3
        assert {p.name for p in personas} == {"Member", "Instructor", "Studio Admin"}

    def test_persona_id_matches_role_slug(self):
        personas = _personas_from_plan(self._yoga_plan())
        by_name = {p.name: p for p in personas}
        assert by_name["Studio Admin"].id == "studio-admin"
        assert by_name["Studio Admin"].role == "studio_admin"

    def test_member_persona_has_expected_jobs(self):
        personas = _personas_from_plan(self._yoga_plan())
        member = next(p for p in personas if p.name == "Member")
        job_ids = {j.id for j in member.jobs}
        # verb-hint matches (browse, book, manage, reviews) + journey names
        assert "browse" in job_ids or "book-a-class" in job_ids
        assert "reviews" in job_ids or "leave-a-review" in job_ids

    def test_instructor_journeys_scoped_to_instructor(self):
        # The "Set availability" journey has primary_actor=instructor
        # → should appear as a Job on the Instructor persona, NOT on
        # the Member persona.
        personas = _personas_from_plan(self._yoga_plan())
        member = next(p for p in personas if p.name == "Member")
        instr = next(p for p in personas if p.name == "Instructor")
        assert not any("availability" in j.id for j in member.jobs)
        assert any("availability" in j.id or "set-availability" in j.id
                   for j in instr.jobs)

    def test_one_liner_from_first_responsibility(self):
        personas = _personas_from_plan(self._yoga_plan())
        member = next(p for p in personas if p.name == "Member")
        assert member.one_liner.startswith("Browse the class schedule")

    def test_no_actors_returns_empty_list(self):
        assert _personas_from_plan({}) == []
        assert _personas_from_plan({"actors": None}) == []
        assert _personas_from_plan({"actors": []}) == []


# ── voice from design brief ─────────────────────────────────────────


class TestVoiceFromDesignBrief:
    def test_no_brief_returns_empty(self):
        v = _voice_from_design_brief(None)
        assert v.adjectives == []
        assert v.sample_ctas == []
        assert v.avoid == []

    def test_snake_case_register_split(self):
        brief = {"identity": {
            "register": ["grounded_calm", "purposeful_clear"],
            "voice": "warm_precise",
        }}
        v = _voice_from_design_brief(brief)
        assert "grounded" in v.adjectives
        assert "calm" in v.adjectives
        assert "purposeful" in v.adjectives
        assert "warm" in v.adjectives

    def test_voice_free_mines_adjectives(self):
        brief = {"identity": {
            "register": [],
            "voice_free": "grounded warmth, quietly intentional",
        }}
        v = _voice_from_design_brief(brief)
        # 4+ letter lowercase words from voice_free
        assert "grounded" in v.adjectives
        assert "warmth" in v.adjectives
        assert "quietly" in v.adjectives
        assert "intentional" in v.adjectives

    def test_capped_at_six(self):
        brief = {"identity": {"register": [
            "one_two", "three_four", "five_six", "seven_eight",
            "nine_ten", "eleven_twelve",
        ]}}
        v = _voice_from_design_brief(brief)
        assert len(v.adjectives) <= 6

    def test_pydantic_model_style_brief(self):
        # Also works on attribute-access (pydantic model) shape.
        class _I:
            register = ["warm", "welcoming"]
            voice = "friendly"
            voice_free = None
        class _B:
            identity = _I()
        v = _voice_from_design_brief(_B())
        assert "warm" in v.adjectives
        assert "welcoming" in v.adjectives
        assert "friendly" in v.adjectives


# ── derive_from_plan (integration) ──────────────────────────────────


class TestDeriveFromPlan:
    def _yoga_plan(self) -> dict:
        return {
            "archetype": "booking-platform",
            "actors": [
                {"name": "Member", "role": "member",
                 "responsibilities": ["Browse the class schedule", "Book classes"]},
                {"name": "Instructor", "role": "instructor",
                 "responsibilities": ["Set availability"]},
            ],
            "journeys": [
                {"name": "Book a class", "primary_actor": "member",
                 "steps": [{"page": "/schedule"}]},
            ],
        }

    def test_derives_brand_empty_by_default(self):
        # Brand is LLM-enriched separately; derive_from_plan leaves it empty.
        pb = derive_from_plan(self._yoga_plan())
        assert isinstance(pb.brand, Brand)
        assert pb.brand.name == ""

    def test_personas_populated(self):
        pb = derive_from_plan(self._yoga_plan())
        assert len(pb.personas) == 2

    def test_archetype_read_from_plan(self):
        pb = derive_from_plan(self._yoga_plan())
        assert pb.archetype == "booking-platform"

    def test_archetype_missing_is_empty_not_error(self):
        pb = derive_from_plan({"actors": []})
        assert pb.archetype == ""

    def test_voice_from_supplied_brief(self):
        brief = {"identity": {"register": ["warm_precise"]}}
        pb = derive_from_plan(self._yoga_plan(), design_brief=brief)
        assert "warm" in pb.voice_notes.adjectives
        assert "precise" in pb.voice_notes.adjectives

    def test_empty_plan_returns_empty_but_valid_brief(self):
        pb = derive_from_plan({})
        assert isinstance(pb, ProductBrief)
        assert pb.personas == []
        assert pb.archetype == ""

    def test_non_dict_plan_is_safe(self):
        pb = derive_from_plan(None)  # type: ignore
        assert isinstance(pb, ProductBrief)

    def test_archetype_from_app_shape_fallback(self):
        # Plan uses app_shape.identity.archetype instead of top-level archetype.
        plan = {
            "actors": [],
            "app_shape": {"identity": {"archetype": "crm"}},
        }
        pb = derive_from_plan(plan)
        assert pb.archetype == "crm"


# ── disk round-trip ─────────────────────────────────────────────────


class TestPersistence:
    def _sample_brief(self) -> ProductBrief:
        return ProductBrief(
            brand=Brand(name="Taĩa Vinyasa", tagline="Studio & Booking", glyph="🌬️"),
            personas=[
                Persona(
                    id="member", name="Member", role="member",
                    one_liner="Books classes and manages membership.",
                    jobs=[
                        Job(id="browse", label="Browse", primary_entities=["sessions"]),
                        Job(id="book", label="Book"),
                    ],
                ),
            ],
            archetype="booking-platform",
            voice_notes=VoiceNotes(adjectives=["warm", "grounded"]),
        )

    def test_save_and_load_round_trip(self, tmp_path: Path):
        pb = self._sample_brief()
        p = save_product_brief(tmp_path, pb)
        assert p.exists()
        loaded = load_product_brief_from_disk(tmp_path)
        assert loaded is not None
        assert loaded.brand.name == "Taĩa Vinyasa"
        assert loaded.brand.glyph == "🌬️"
        assert len(loaded.personas) == 1
        assert loaded.personas[0].jobs[0].id == "browse"

    def test_save_creates_contracts_dir(self, tmp_path: Path):
        # contracts/ doesn't pre-exist
        p = save_product_brief(tmp_path, self._sample_brief())
        assert p == tmp_path / "contracts" / "product-brief.json"
        assert p.parent.is_dir()

    def test_load_missing_returns_none(self, tmp_path: Path):
        assert load_product_brief_from_disk(tmp_path) is None

    def test_load_malformed_json_returns_none_not_raises(self, tmp_path: Path):
        (tmp_path / "contracts").mkdir()
        (tmp_path / "contracts" / "product-brief.json").write_text(
            "{ this is not json", encoding="utf-8"
        )
        # Does not raise
        assert load_product_brief_from_disk(tmp_path) is None

    def test_load_schema_invalid_returns_none_not_raises(self, tmp_path: Path):
        # Valid JSON but wrong shape (personas is a string, not a list)
        (tmp_path / "contracts").mkdir()
        (tmp_path / "contracts" / "product-brief.json").write_text(
            json.dumps({"personas": "wrong-type"}), encoding="utf-8"
        )
        assert load_product_brief_from_disk(tmp_path) is None

    def test_save_atomic_on_string_output_dir(self, tmp_path: Path):
        # Accepts str, not just Path (matches other services in the codebase).
        p = save_product_brief(str(tmp_path), self._sample_brief())
        assert p.exists()

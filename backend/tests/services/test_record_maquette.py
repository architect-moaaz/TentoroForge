"""Tests for services.record_maquette."""
from __future__ import annotations

import asyncio

import pytest

from services.record_maquette import (
    FIELD_CONTROL_HINTS,
    RECORD_HERO_KINDS,
    RECORD_MODES,
    SECTION_TONES,
    RecordFooterSpec,
    RecordHeroSpec,
    RecordMaquette,
    SectionSpec,
    _build_system_prompt,
    _build_user_prompt,
    _extract_json_object,
    _valid_columns_from,
    author_record_maquette,
    meets_richness_contract,
)


# ─────────────────────────── vocabulary ────────────────────────────────


class TestVocabulary:
    def test_modes_are_disjoint(self):
        assert set(RECORD_MODES) == {"view", "edit", "create"}

    def test_section_tones_are_disjoint(self):
        assert set(SECTION_TONES) == {"primary", "secondary", "advanced", "meta", "danger"}

    def test_hero_kinds_are_disjoint(self):
        assert set(RECORD_HERO_KINDS) == {
            "page-header", "media-lead", "status-led", "editorial", "breadcrumbs",
        }

    def test_control_hints_cover_domain_shapes(self):
        # These hints don't exist in the renderer just to look pretty —
        # each maps to a real component. Sanity-check the common ones.
        for h in ("rating", "signature", "camera-capture", "slider",
                  "date-range", "file-upload", "rich-text"):
            assert h in FIELD_CONTROL_HINTS


# ─────────────────────────── small dataclasses ─────────────────────────


class TestSectionSpec:
    def test_minimal_to_dict(self):
        assert SectionSpec(label="Contact", fields=["email"]).to_dict() == {
            "label": "Contact", "fields": ["email"], "tone": "primary",
        }

    def test_full_to_dict(self):
        assert SectionSpec(
            label="Advanced",
            fields=["debug", "raw_json"],
            tone="advanced",
            collapsible=True,
            subhead="For power users",
        ).to_dict() == {
            "label": "Advanced",
            "fields": ["debug", "raw_json"],
            "tone": "advanced",
            "collapsible": True,
            "subhead": "For power users",
        }

    def test_collapsible_none_omitted(self):
        out = SectionSpec(label="a", fields=["x"]).to_dict()
        assert "collapsible" not in out


class TestRecordHeroSpec:
    def test_minimal(self):
        # kind + title only.
        assert RecordHeroSpec(kind="page-header", title="Add booking").to_dict() == {
            "kind": "page-header", "title": "Add booking",
        }

    def test_status_led_carries_status_field(self):
        assert RecordHeroSpec(
            kind="status-led", title="Review claim", status_field="status",
        ).to_dict() == {
            "kind": "status-led", "title": "Review claim", "status_field": "status",
        }

    def test_media_lead_carries_media_field(self):
        assert RecordHeroSpec(
            kind="media-lead", title="Edit product", media_field="photo_url",
        ).to_dict() == {
            "kind": "media-lead", "title": "Edit product", "media_field": "photo_url",
        }


class TestRecordFooterSpec:
    def test_bare_kind(self):
        assert RecordFooterSpec(kind="timestamps").to_dict() == {"kind": "timestamps"}

    def test_with_content(self):
        assert RecordFooterSpec(kind="danger-zone", content="Deleting is permanent").to_dict() == {
            "kind": "danger-zone", "content": "Deleting is permanent",
        }


# ─────────────────────────── RecordMaquette from_dict ──────────────────


class TestRecordMaquetteRequired:
    def test_non_dict_returns_none(self):
        assert RecordMaquette.from_dict("nope") is None  # type: ignore
        assert RecordMaquette.from_dict(None) is None  # type: ignore

    def test_missing_entity_or_route_returns_none(self):
        assert RecordMaquette.from_dict({"entity": "x"}) is None
        assert RecordMaquette.from_dict({"route": "/x"}) is None

    def test_route_must_start_with_slash(self):
        # Guards against LLM emitting raw entity name as route.
        assert RecordMaquette.from_dict({"entity": "x", "route": "bookings"}) is None

    def test_minimal_valid(self):
        m = RecordMaquette.from_dict({"entity": "bookings", "route": "/bookings/new"})
        assert m is not None
        assert m.entity == "bookings"
        assert m.route == "/bookings/new"
        assert m.mode == "edit"  # default


class TestRecordMaquetteMode:
    def test_unknown_mode_falls_back(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b", "mode": "publish",
        })
        assert m is not None
        assert m.mode == "edit"

    def test_known_modes_kept(self):
        for mode in RECORD_MODES:
            m = RecordMaquette.from_dict({
                "entity": "b", "route": "/b", "mode": mode,
            })
            assert m is not None
            assert m.mode == mode


class TestRecordMaquetteSectionGrouping:
    def test_empty_sections_dropped(self):
        # A section with no valid fields is a bug — the composer would
        # render a heading with no content. Drop it.
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "section_grouping": [
                {"label": "Empty", "fields": []},
                {"label": "Only bad", "fields": ["nonexistent"]},
                {"label": "Good", "fields": ["email"]},
            ],
        }, valid_columns={"email"})
        assert m is not None
        assert len(m.section_grouping) == 1
        assert m.section_grouping[0].label == "Good"

    def test_hallucinated_fields_dropped(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "section_grouping": [
                {"label": "Contact", "fields": ["email", "invented"]},
            ],
        }, valid_columns={"email"})
        assert m is not None
        assert m.section_grouping[0].fields == ["email"]

    def test_no_valid_columns_no_filter(self):
        # Without a registry, the parser trusts the LLM. Later
        # validators catch drift.
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "section_grouping": [{"label": "X", "fields": ["anything"]}],
        })
        assert m is not None
        assert m.section_grouping[0].fields == ["anything"]

    def test_unknown_tone_falls_back(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "section_grouping": [{"label": "X", "fields": ["a"], "tone": "spicy"}],
        })
        assert m is not None
        assert m.section_grouping[0].tone == "primary"

    def test_collapsible_and_subhead_pass_through(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "section_grouping": [
                {"label": "Advanced", "fields": ["x"], "tone": "advanced",
                 "collapsible": True, "subhead": "For admins"},
            ],
        })
        assert m is not None
        s = m.section_grouping[0]
        assert s.collapsible is True
        assert s.subhead == "For admins"


class TestRecordMaquetteFieldOrdering:
    def test_hallucinated_fields_dropped(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "field_ordering": ["a", "invented", "b"],
        }, valid_columns={"a", "b"})
        assert m is not None
        assert m.field_ordering == ["a", "b"]

    def test_non_string_ignored(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "field_ordering": ["a", None, 42, ""],
        })
        assert m is not None
        assert m.field_ordering == ["a"]


class TestRecordMaquetteControlHints:
    def test_unknown_hint_dropped(self):
        # Composer would otherwise emit a broken component for
        # invented control types.
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "control_hints": {"email": "email", "notes": "gooey-editor"},
        })
        assert m is not None
        assert m.control_hints == {"email": "email"}

    def test_hallucinated_field_dropped(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "control_hints": {"email": "email", "invented": "select"},
        }, valid_columns={"email"})
        assert m is not None
        assert m.control_hints == {"email": "email"}

    def test_non_dict_hints_ignored(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "control_hints": "not-a-dict",
        })
        assert m is not None
        assert m.control_hints == {}


class TestRecordMaquetteHero:
    def test_unknown_kind_falls_back(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "hero": {"kind": "spicy-header", "title": "T"},
        })
        assert m is not None and m.hero is not None
        assert m.hero.kind == "page-header"

    def test_missing_title_drops_hero(self):
        # No point rendering a hero without a title.
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "hero": {"kind": "page-header"},
        })
        assert m is not None
        assert m.hero is None

    def test_hallucinated_status_field_dropped(self):
        # Composer would otherwise try to render a status pill from a
        # non-existent column.
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "hero": {"kind": "status-led", "title": "T", "status_field": "invented"},
        }, valid_columns={"status"})
        assert m is not None and m.hero is not None
        assert m.hero.status_field is None

    def test_hallucinated_media_field_dropped(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "hero": {"kind": "media-lead", "title": "T", "media_field": "not_real"},
        }, valid_columns={"photo_url"})
        assert m is not None and m.hero is not None
        assert m.hero.media_field is None

    def test_full_hero(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "hero": {
                "kind": "editorial", "title": "Register",
                "subtitle": "Sub", "eyebrow": "New",
            },
        })
        assert m is not None and m.hero is not None
        assert m.hero.kind == "editorial"
        assert m.hero.eyebrow == "New"


class TestRecordMaquetteFooter:
    def test_unknown_kind_dropped(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "footer": {"kind": "kitchen-sink"},
        })
        assert m is not None
        assert m.footer is None

    def test_known_kinds_kept(self):
        for kind in ("timestamps", "danger-zone", "audit", "related"):
            m = RecordMaquette.from_dict({
                "entity": "b", "route": "/b",
                "footer": {"kind": kind},
            })
            assert m is not None and m.footer is not None
            assert m.footer.kind == kind


class TestRecordMaquetteSignatureMoves:
    def test_strips_and_drops(self):
        m = RecordMaquette.from_dict({
            "entity": "b", "route": "/b",
            "signature_moves": ["  sticky-save-bar ", "", "field-focus-guide", None, 42],
        })
        assert m is not None
        assert m.signature_moves == ["sticky-save-bar", "field-focus-guide"]


class TestRecordMaquetteRoundTrip:
    def test_full_shape_roundtrips(self):
        m = RecordMaquette(
            entity="bookings", route="/bookings/new", mode="create",
            section_grouping=[
                SectionSpec(label="Contact", fields=["email", "phone"]),
                SectionSpec(label="Advanced", fields=["notes"], tone="advanced",
                            collapsible=True),
            ],
            field_ordering=["email", "phone", "notes"],
            control_hints={"notes": "rich-text"},
            hero=RecordHeroSpec(kind="page-header", title="Book a class"),
            footer=RecordFooterSpec(kind="timestamps"),
            signature_moves=["sticky-save-bar"],
        )
        d = m.to_dict()
        assert d["entity"] == "bookings"
        assert d["mode"] == "create"
        assert len(d["section_grouping"]) == 2
        assert d["control_hints"] == {"notes": "rich-text"}
        assert d["hero"]["kind"] == "page-header"
        assert d["footer"]["kind"] == "timestamps"


# ─────────────────────────── richness contract ─────────────────────────


class TestRichnessContract:
    def _sections(self, n_fields: int) -> list[SectionSpec]:
        # Split n fields across 2 sections.
        half = n_fields // 2
        return [
            SectionSpec(label="A", fields=[f"f{i}" for i in range(half)]),
            SectionSpec(label="B", fields=[f"g{i}" for i in range(n_fields - half)]),
        ]

    def test_meets_when_grouped_and_hero(self):
        m = RecordMaquette(
            entity="b", route="/b",
            section_grouping=self._sections(6),
            hero=RecordHeroSpec(kind="page-header", title="Edit"),
        )
        assert meets_richness_contract(m) == []

    def test_missing_hero_reported(self):
        m = RecordMaquette(entity="b", route="/b",
                           section_grouping=self._sections(6))
        assert meets_richness_contract(m) == ["hero"]

    def test_missing_section_grouping_reported(self):
        m = RecordMaquette(entity="b", route="/b",
                           hero=RecordHeroSpec(kind="page-header", title="X"))
        assert "section_grouping" in meets_richness_contract(m)

    def test_too_few_grouped_fields_reported(self):
        m = RecordMaquette(
            entity="b", route="/b",
            section_grouping=self._sections(2),  # 2 < 3
            hero=RecordHeroSpec(kind="page-header", title="X"),
        )
        missing = meets_richness_contract(m)
        assert any("section_grouping.fields" in x for x in missing)

    def test_hero_optional_when_disabled(self):
        m = RecordMaquette(entity="b", route="/b",
                           section_grouping=self._sections(6))
        assert meets_richness_contract(m, require_hero=False) == []


# ─────────────────────────── valid_columns helper ──────────────────────


class TestValidColumnsFrom:
    def test_list_of_dicts(self):
        assert _valid_columns_from({"fields": [{"name": "a"}, {"name": "b"}]}) == {"a", "b"}

    def test_dict_of_columns(self):
        assert _valid_columns_from({"fields": {"a": {"type": "text"}}}) == {"a"}

    def test_falls_back_to_columns_key(self):
        assert _valid_columns_from({"columns": [{"name": "x"}]}) == {"x"}

    def test_empty(self):
        assert _valid_columns_from({}) == set()


# ─────────────────────────── JSON extract ──────────────────────────────


class TestExtractJsonObject:
    def test_plain(self):
        assert _extract_json_object('{"a": 1}') == {"a": 1}

    def test_none_and_empty(self):
        assert _extract_json_object(None) is None
        assert _extract_json_object("") is None

    def test_fenced(self):
        assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    def test_prose_wrapped(self):
        assert _extract_json_object('Here you go:\n{"a": 1}\nDone.') == {"a": 1}

    def test_braces_in_string_do_not_confuse(self):
        text = '{"a": "text with { and \\" here", "b": 2}'
        assert _extract_json_object(text) == {"a": 'text with { and " here', "b": 2}

    def test_array_root_returns_none(self):
        assert _extract_json_object("[1, 2]") is None


# ─────────────────────────── prompts ───────────────────────────────────


class TestSystemPrompt:
    def test_lists_modes(self):
        prompt = _build_system_prompt()
        for m in RECORD_MODES:
            assert m in prompt

    def test_lists_hero_kinds(self):
        prompt = _build_system_prompt()
        for k in RECORD_HERO_KINDS:
            assert k in prompt

    def test_lists_control_hints(self):
        prompt = _build_system_prompt()
        for h in ("rating", "signature", "slider", "file-upload"):
            assert h in prompt

    def test_says_no_prose(self):
        prompt = _build_system_prompt().lower()
        assert "return json only" in prompt or "no prose" in prompt

    def test_calls_out_field_hallucination_rule(self):
        prompt = _build_system_prompt().lower()
        assert "real column" in prompt or "must be a real" in prompt


class TestUserPrompt:
    def _plan(self, description: str = "yoga studio") -> dict:
        return {
            "description": description,
            "module_name": "Rania",
            "domain": "wellness",
            "entities": {
                "bookings": {
                    "fields": [
                        {"name": "email", "type": "text", "required": True},
                        {"name": "sessionId", "type": "uuid", "references": "sessions"},
                        {"name": "notes", "type": "text"},
                    ],
                },
            },
        }

    def test_includes_entity_route_mode(self):
        p = self._plan()
        prompt = _build_user_prompt(p, "bookings", p["entities"]["bookings"],
                                     "/bookings/new", "create", None)
        assert "bookings" in prompt
        assert "/bookings/new" in prompt
        assert "mode:   create" in prompt or "mode: create" in prompt or "create" in prompt

    def test_includes_columns_with_types(self):
        p = self._plan()
        prompt = _build_user_prompt(p, "bookings", p["entities"]["bookings"],
                                     "/bookings/new", "create", None)
        assert "email" in prompt
        assert "sessionId" in prompt

    def test_fk_note_present_when_column_has_reference(self):
        # The LLM benefits from knowing which columns are FKs — it
        # steers the hero kind (never media-lead on a bare FK column).
        p = self._plan()
        prompt = _build_user_prompt(p, "bookings", p["entities"]["bookings"],
                                     "/bookings/new", "create", None)
        assert "FK→sessions" in prompt

    def test_variance_hint_present_with_identity(self):
        p = self._plan()
        prompt = _build_user_prompt(p, "bookings", p["entities"]["bookings"],
                                     "/bookings/new", "create", None)
        assert "VARIANCE HINT" in prompt

    def test_variance_absent_when_plan_empty(self):
        empty = {"entities": {"b": {"fields": []}}}
        prompt = _build_user_prompt(empty, "b", empty["entities"]["b"],
                                     "/b", "edit", None)
        assert "VARIANCE HINT" not in prompt

    def test_different_briefs_diverge(self):
        a = self._plan("warm boutique yoga")
        b = self._plan("high-density admin console")
        pa = _build_user_prompt(a, "bookings", a["entities"]["bookings"],
                                "/bookings/new", "create", "warm boutique")
        pb = _build_user_prompt(b, "bookings", b["entities"]["bookings"],
                                "/bookings/new", "create", "dense admin")
        assert pa != pb


# ─────────────────────────── author_record_maquette ────────────────────


class TestAuthorRecordMaquette:
    def _plan(self) -> dict:
        return {
            "description": "yoga studio",
            "module_name": "Rania",
            "entities": {
                "bookings": {
                    "fields": [
                        {"name": "email", "type": "text"},
                        {"name": "sessionId", "type": "uuid"},
                        {"name": "notes", "type": "text"},
                    ],
                },
            },
        }

    def _run(self, coro):
        return asyncio.run(coro)

    def _make_query_fn(self, response: str):
        async def _fn(system: str, user: str) -> str:  # noqa: ARG001
            return response
        return _fn

    def test_non_dict_plan_returns_none(self):
        assert self._run(author_record_maquette("nope", "b", "/b")) is None  # type: ignore

    def test_missing_entities_returns_none(self):
        assert self._run(author_record_maquette({"description": "x"}, "b", "/b")) is None

    def test_unknown_entity_returns_none(self):
        assert self._run(author_record_maquette(
            self._plan(), "unknown", "/x",
            query_fn=self._make_query_fn('{"entity": "unknown", "route": "/x"}'),
        )) is None

    def test_uses_injected_query_fn(self):
        response = ('{"entity": "bookings", "route": "/bookings/new", "mode": "create", '
                    '"section_grouping": [{"label": "Contact", "fields": ["email"]}]}')
        m = self._run(author_record_maquette(
            self._plan(), "bookings", "/bookings/new", mode="create",
            query_fn=self._make_query_fn(response),
        ))
        assert m is not None
        assert m.mode == "create"
        assert m.section_grouping[0].label == "Contact"

    def test_query_fn_exception_returns_none(self):
        async def _boom(system: str, user: str) -> str:  # noqa: ARG001
            raise RuntimeError("LLM died")
        assert self._run(author_record_maquette(
            self._plan(), "bookings", "/bookings/new", query_fn=_boom,
        )) is None

    def test_malformed_response_returns_none(self):
        assert self._run(author_record_maquette(
            self._plan(), "bookings", "/bookings/new",
            query_fn=self._make_query_fn("just prose, no json"),
        )) is None

    def test_hallucinated_fields_dropped_end_to_end(self):
        response = ('{"entity": "bookings", "route": "/bookings/new", '
                    '"section_grouping": [{"label": "Contact", "fields": ["email", "invented"]}]}')
        m = self._run(author_record_maquette(
            self._plan(), "bookings", "/bookings/new",
            query_fn=self._make_query_fn(response),
        ))
        assert m is not None
        assert m.section_grouping[0].fields == ["email"]

    def test_unknown_mode_normalizes_to_edit(self):
        # `mode` passed to author() must be valid too — the LLM sees it.
        m = self._run(author_record_maquette(
            self._plan(), "bookings", "/bookings/new", mode="publish",
            query_fn=self._make_query_fn('{"entity": "bookings", "route": "/bookings/new"}'),
        ))
        assert m is not None
        # from_dict decides — LLM didn't specify mode, so default "edit".
        assert m.mode == "edit"

    def test_missing_api_key_without_query_fn(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        assert self._run(author_record_maquette(
            self._plan(), "bookings", "/bookings/new",
        )) is None

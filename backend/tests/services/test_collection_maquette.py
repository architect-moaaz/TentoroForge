"""Tests for services.collection_maquette.

The collection maquette is the LLM-authored decisions layer for one
collection page (list / kanban / calendar / cards / timeline). This
suite covers:

- data-shape parsing (drops invalid fields, never raises)
- ``valid_columns`` hallucination guard
- richness contract (missing-fields report)
- prompt construction (variance/personality/references propagation)
- ``author_collection_maquette`` orchestration with injected query_fn
- JSON extraction from LLM responses (fences, prose-wrapped)
"""
from __future__ import annotations

import asyncio

import pytest

from services.collection_maquette import (
    COLLECTION_LAYOUTS,
    ROW_TREATMENTS,
    EMPTY_STATE_ILLUSTRATIONS,
    ColumnSpec,
    CollectionFooterSpec,
    CollectionHeroSpec,
    CollectionMaquette,
    EmptyStateSpec,
    FilterPresetSpec,
    _build_system_prompt,
    _build_user_prompt,
    _extract_json_object,
    _valid_columns_from,
    author_collection_maquette,
    meets_richness_contract,
)


# ─────────────────────────── vocabulary ────────────────────────────────


class TestVocabulary:
    def test_layouts_are_disjoint_kinds(self):
        assert set(COLLECTION_LAYOUTS) == {"table", "kanban", "calendar", "cards", "timeline"}

    def test_row_treatments_are_disjoint(self):
        assert set(ROW_TREATMENTS) == {"compact", "cozy", "photo-forward", "status-led", "narrative"}

    def test_empty_state_illustrations_are_catalog_keys(self):
        # These must map to real SVGs in the deterministic_strings /
        # IllustratedEmpty catalog. If this list changes, the composer
        # + IllustratedEmpty registry both need updating.
        assert "welcome-mat" in EMPTY_STATE_ILLUSTRATIONS
        assert "empty-calendar" in EMPTY_STATE_ILLUSTRATIONS
        assert "empty-inbox" in EMPTY_STATE_ILLUSTRATIONS


# ─────────────────────────── small dataclasses ─────────────────────────


class TestColumnSpec:
    def test_to_dict_minimal(self):
        assert ColumnSpec(name="title", label="Title").to_dict() == {
            "name": "title",
            "label": "Title",
        }

    def test_to_dict_with_kind_and_emphasis(self):
        assert ColumnSpec(name="name", label="Name", kind="text", emphasis=True).to_dict() == {
            "name": "name",
            "label": "Name",
            "kind": "text",
            "emphasis": True,
        }

    def test_emphasis_false_omitted(self):
        # emphasis defaults to False and should not clutter output when unused.
        out = ColumnSpec(name="x", label="X").to_dict()
        assert "emphasis" not in out


class TestFilterPresetSpec:
    def test_to_dict(self):
        assert FilterPresetSpec(label="Overdue", expr="dueAt < now").to_dict() == {
            "label": "Overdue",
            "expr": "dueAt < now",
        }


class TestEmptyStateSpec:
    def test_to_dict_full(self):
        out = EmptyStateSpec(
            illustration="planted-seed",
            headline="Your practice starts here",
            subhead="Book your first class",
            cta_label="Browse classes",
            cta_action="/sessions",
        ).to_dict()
        assert out == {
            "illustration": "planted-seed",
            "headline": "Your practice starts here",
            "subhead": "Book your first class",
            "cta_label": "Browse classes",
            "cta_action": "/sessions",
        }

    def test_to_dict_minimal_omits_nulls(self):
        out = EmptyStateSpec(illustration="welcome-mat", headline="Nothing yet").to_dict()
        assert out == {"illustration": "welcome-mat", "headline": "Nothing yet"}


class TestCollectionHeroSpec:
    def test_to_dict_minimal(self):
        assert CollectionHeroSpec(title="Bookings").to_dict() == {"title": "Bookings"}

    def test_to_dict_full(self):
        assert CollectionHeroSpec(
            title="Bookings", subtitle="This week", badge="12 open",
        ).to_dict() == {"title": "Bookings", "subtitle": "This week", "badge": "12 open"}


class TestCollectionFooterSpec:
    def test_to_dict_minimal(self):
        assert CollectionFooterSpec(kind="total-row").to_dict() == {"kind": "total-row"}

    def test_to_dict_with_content(self):
        assert CollectionFooterSpec(kind="insight", content="Peak day: Tuesday").to_dict() == {
            "kind": "insight",
            "content": "Peak day: Tuesday",
        }


# ─────────────────────────── CollectionMaquette ────────────────────────


class TestCollectionMaquetteToDict:
    def test_full_shape_roundtrips(self):
        m = CollectionMaquette(
            entity="sessions",
            route="/sessions",
            layout="calendar",
            columns=[
                ColumnSpec(name="title", label="Class", emphasis=True),
                ColumnSpec(name="startAt", label="When", kind="date"),
            ],
            row_treatment="photo-forward",
            filter_presets=[FilterPresetSpec(label="This week", expr="startAt < 7d")],
            hero=CollectionHeroSpec(title="Sessions", badge="12 open"),
            empty_state=EmptyStateSpec(illustration="empty-calendar", headline="No sessions yet"),
            footer=CollectionFooterSpec(kind="insight", content="Peak: Tuesday"),
            signature_moves=["column-headers-with-counts", "grouped-by-day"],
        )
        d = m.to_dict()
        assert d["entity"] == "sessions"
        assert d["route"] == "/sessions"
        assert d["layout"] == "calendar"
        assert len(d["columns"]) == 2
        assert d["row_treatment"] == "photo-forward"
        assert d["filter_presets"] == [{"label": "This week", "expr": "startAt < 7d"}]
        assert d["hero"] == {"title": "Sessions", "badge": "12 open"}
        assert d["empty_state"]["illustration"] == "empty-calendar"
        assert d["footer"] == {"kind": "insight", "content": "Peak: Tuesday"}
        assert d["signature_moves"] == ["column-headers-with-counts", "grouped-by-day"]

    def test_optional_fields_serialize_as_none(self):
        m = CollectionMaquette(entity="a", route="/a")
        d = m.to_dict()
        assert d["hero"] is None
        assert d["empty_state"] is None
        assert d["footer"] is None
        assert d["signature_moves"] == []
        assert d["columns"] == []
        assert d["filter_presets"] == []


class TestCollectionMaquetteFromDictBasics:
    def test_non_dict_returns_none(self):
        assert CollectionMaquette.from_dict("nope") is None  # type: ignore
        assert CollectionMaquette.from_dict(None) is None  # type: ignore
        assert CollectionMaquette.from_dict(["list"]) is None  # type: ignore

    def test_missing_entity_returns_none(self):
        # Required fields — without them the composer has nowhere to write.
        assert CollectionMaquette.from_dict({"route": "/x"}) is None

    def test_missing_route_returns_none(self):
        assert CollectionMaquette.from_dict({"entity": "x"}) is None

    def test_route_must_start_with_slash(self):
        # Guards against LLM emitting a raw entity name in the route slot.
        assert CollectionMaquette.from_dict({"entity": "x", "route": "sessions"}) is None

    def test_minimal_valid_input(self):
        m = CollectionMaquette.from_dict({"entity": "sessions", "route": "/sessions"})
        assert m is not None
        assert m.entity == "sessions"
        assert m.route == "/sessions"
        # Defaults kick in for everything the LLM omitted.
        assert m.layout == "table"
        assert m.row_treatment == "cozy"
        assert m.columns == []


class TestCollectionMaquetteFromDictLayout:
    def test_unknown_layout_falls_back_to_default(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s", "layout": "grid",
        })
        assert m is not None
        # Unknown layout must not crash — falls back to table so the
        # composer always has a valid dispatch target.
        assert m.layout == "table"

    def test_known_layouts_are_kept(self):
        for layout in COLLECTION_LAYOUTS:
            m = CollectionMaquette.from_dict({
                "entity": "s", "route": "/s", "layout": layout,
            })
            assert m is not None
            assert m.layout == layout


class TestCollectionMaquetteFromDictColumns:
    def test_columns_without_names_dropped(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s",
            "columns": [{"label": "Nameless"}, {"name": "title", "label": "Title"}],
        })
        assert m is not None
        assert len(m.columns) == 1
        assert m.columns[0].name == "title"

    def test_columns_default_label_to_name_when_missing(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s",
            "columns": [{"name": "createdAt"}],
        })
        assert m is not None
        assert m.columns[0].label == "createdAt"

    def test_columns_emphasis_normalized_to_bool(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s",
            "columns": [
                {"name": "a", "label": "A", "emphasis": True},
                {"name": "b", "label": "B", "emphasis": "yes"},  # truthy → True
                {"name": "c", "label": "C"},                    # absent  → False
            ],
        })
        assert m is not None
        assert [c.emphasis for c in m.columns] == [True, True, False]

    def test_valid_columns_drops_hallucinated_names(self):
        # The LLM sometimes proposes a column name that doesn't exist on
        # the entity. valid_columns is the registry safety net: unknown
        # names get silently dropped rather than reaching the composer.
        m = CollectionMaquette.from_dict(
            {
                "entity": "s", "route": "/s",
                "columns": [
                    {"name": "title", "label": "Title"},
                    {"name": "made_up", "label": "Bogus"},
                ],
            },
            valid_columns={"title", "id"},
        )
        assert m is not None
        assert [c.name for c in m.columns] == ["title"]

    def test_no_valid_columns_no_filter(self):
        # When callers can't supply a registry the parser trusts the LLM.
        # Later validators (binding gate) catch drift.
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s",
            "columns": [{"name": "anything", "label": "X"}],
        })
        assert m is not None
        assert m.columns[0].name == "anything"

    def test_non_list_columns_ignored(self):
        # Guards against LLM emitting `columns: {...}` or `columns: "bad"`.
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s", "columns": "not-a-list",
        })
        assert m is not None
        assert m.columns == []


class TestCollectionMaquetteFromDictRowTreatment:
    def test_unknown_row_treatment_falls_back(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s", "row_treatment": "chunky",
        })
        assert m is not None
        assert m.row_treatment == "cozy"

    def test_known_row_treatments_kept(self):
        for rt in ROW_TREATMENTS:
            m = CollectionMaquette.from_dict({
                "entity": "s", "route": "/s", "row_treatment": rt,
            })
            assert m is not None
            assert m.row_treatment == rt


class TestCollectionMaquetteFromDictFilters:
    def test_incomplete_filters_dropped(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s",
            "filter_presets": [
                {"label": "Only label"},
                {"expr": "only expr"},
                {"label": "Good", "expr": "status=open"},
                {},
            ],
        })
        assert m is not None
        assert len(m.filter_presets) == 1
        assert m.filter_presets[0].label == "Good"

    def test_empty_string_label_or_expr_dropped(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s",
            "filter_presets": [
                {"label": "", "expr": "e"},
                {"label": "l", "expr": ""},
            ],
        })
        assert m is not None
        assert m.filter_presets == []


class TestCollectionMaquetteFromDictHero:
    def test_hero_without_title_dropped(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s", "hero": {"subtitle": "s"},
        })
        assert m is not None
        assert m.hero is None

    def test_hero_full(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s",
            "hero": {"title": "Bookings", "subtitle": "this week", "badge": "12 open"},
        })
        assert m is not None and m.hero is not None
        assert m.hero.title == "Bookings"
        assert m.hero.subtitle == "this week"
        assert m.hero.badge == "12 open"


class TestCollectionMaquetteFromDictEmptyState:
    def test_missing_headline_drops_empty_state(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s",
            "empty_state": {"illustration": "welcome-mat"},
        })
        assert m is not None
        assert m.empty_state is None

    def test_unknown_illustration_falls_back_to_welcome_mat(self):
        # Guards against LLM inventing an illustration name — composer
        # would otherwise render a broken asset.
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s",
            "empty_state": {"illustration": "space-cowboy", "headline": "Nothing yet"},
        })
        assert m is not None and m.empty_state is not None
        assert m.empty_state.illustration == "welcome-mat"

    def test_full_empty_state(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s",
            "empty_state": {
                "illustration": "planted-seed",
                "headline": "Nothing yet",
                "subhead": "Add your first",
                "cta_label": "Add",
                "cta_action": "/sessions/new",
            },
        })
        assert m is not None and m.empty_state is not None
        assert m.empty_state.illustration == "planted-seed"
        assert m.empty_state.cta_action == "/sessions/new"


class TestCollectionMaquetteFromDictFooter:
    def test_unknown_footer_kind_dropped(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s", "footer": {"kind": "kitchen-sink"},
        })
        assert m is not None
        assert m.footer is None

    def test_known_kinds_kept(self):
        for kind in ("total-row", "batch-actions", "insight", "add-affordance"):
            m = CollectionMaquette.from_dict({
                "entity": "s", "route": "/s", "footer": {"kind": kind},
            })
            assert m is not None and m.footer is not None
            assert m.footer.kind == kind


class TestCollectionMaquetteFromDictSignatureMoves:
    def test_strips_and_drops_empty(self):
        m = CollectionMaquette.from_dict({
            "entity": "s", "route": "/s",
            "signature_moves": ["  sparkline-preview  ", "", "photo-forward-row", None, 42],
        })
        assert m is not None
        assert m.signature_moves == ["sparkline-preview", "photo-forward-row"]


# ─────────────────────────── richness contract ─────────────────────────


class TestRichnessContract:
    def test_meets_when_populated(self):
        m = CollectionMaquette(
            entity="s", route="/s",
            columns=[ColumnSpec("a", "A"), ColumnSpec("b", "B"), ColumnSpec("c", "C")],
            empty_state=EmptyStateSpec(illustration="welcome-mat", headline="Nothing yet"),
        )
        assert meets_richness_contract(m) == []

    def test_reports_missing_columns(self):
        m = CollectionMaquette(entity="s", route="/s",
                               empty_state=EmptyStateSpec("welcome-mat", "Nothing"))
        missing = meets_richness_contract(m)
        assert any("columns" in x for x in missing)

    def test_reports_missing_empty_state(self):
        m = CollectionMaquette(entity="s", route="/s",
                               columns=[ColumnSpec("a", "A"), ColumnSpec("b", "B"),
                                        ColumnSpec("c", "C")])
        assert "empty_state" in meets_richness_contract(m)

    def test_reports_missing_hero_when_required(self):
        m = CollectionMaquette(
            entity="s", route="/s",
            columns=[ColumnSpec("a", "A"), ColumnSpec("b", "B"), ColumnSpec("c", "C")],
            empty_state=EmptyStateSpec("welcome-mat", "Nothing"),
        )
        assert meets_richness_contract(m, require_hero=True) == ["hero"]

    def test_empty_state_can_be_disabled(self):
        # Some downstream builders may not need empty-state (e.g. a
        # dashboard-adjacent list that always seeds itself with sample
        # rows). Contract-check should honor the caller's floor.
        m = CollectionMaquette(entity="s", route="/s",
                               columns=[ColumnSpec("a", "A"), ColumnSpec("b", "B"),
                                        ColumnSpec("c", "C")])
        assert meets_richness_contract(m, require_empty_state=False) == []


# ─────────────────────────── valid_columns helper ──────────────────────


class TestValidColumnsFrom:
    def test_extract_from_list_of_dicts(self):
        assert _valid_columns_from({"fields": [
            {"name": "a", "type": "text"},
            {"name": "b", "type": "int"},
        ]}) == {"a", "b"}

    def test_extract_from_dict_of_columns(self):
        assert _valid_columns_from({"fields": {"a": {"type": "text"}, "b": {"type": "int"}}}) == {"a", "b"}

    def test_falls_back_to_columns_key(self):
        assert _valid_columns_from({"columns": [{"name": "x"}]}) == {"x"}

    def test_empty_when_no_metadata(self):
        assert _valid_columns_from({}) == set()

    def test_skips_dicts_without_name(self):
        assert _valid_columns_from({"fields": [{"label": "L"}, {"name": "y"}]}) == {"y"}


# ─────────────────────────── JSON extraction ───────────────────────────


class TestExtractJsonObject:
    def test_plain_object(self):
        assert _extract_json_object('{"a": 1}') == {"a": 1}

    def test_none_and_empty(self):
        assert _extract_json_object(None) is None
        assert _extract_json_object("") is None
        assert _extract_json_object("   ") is None

    def test_fenced_json(self):
        text = '```json\n{"a": 1}\n```'
        assert _extract_json_object(text) == {"a": 1}

    def test_prose_wrapped_json_balance_scan(self):
        text = 'Here is the maquette you asked for:\n{"a": 1, "b": [2, 3]}\nHope this helps.'
        assert _extract_json_object(text) == {"a": 1, "b": [2, 3]}

    def test_braces_inside_string_do_not_confuse(self):
        text = '{"a": "text with { brace and \\" quote", "b": 2}'
        assert _extract_json_object(text) == {"a": 'text with { brace and " quote', "b": 2}

    def test_returns_none_for_non_object_root(self):
        # If the LLM produced a JSON array instead of an object we
        # return None — the caller doesn't have a decisions shape to work with.
        assert _extract_json_object("[1, 2, 3]") is None

    def test_returns_none_for_unbalanced(self):
        assert _extract_json_object('{"a": 1') is None


# ─────────────────────────── prompts ───────────────────────────────────


class TestSystemPrompt:
    def test_lists_layouts(self):
        prompt = _build_system_prompt()
        for l in COLLECTION_LAYOUTS:
            assert l in prompt

    def test_lists_row_treatments(self):
        prompt = _build_system_prompt()
        for r in ROW_TREATMENTS:
            assert r in prompt

    def test_lists_illustration_keys(self):
        prompt = _build_system_prompt()
        for i in EMPTY_STATE_ILLUSTRATIONS:
            assert i in prompt

    def test_says_no_prose(self):
        # The composer relies on JSON-only output. Guard the contract.
        prompt = _build_system_prompt().lower()
        assert "return json only" in prompt or "no prose" in prompt

    def test_calls_out_column_hallucination_rule(self):
        prompt = _build_system_prompt().lower()
        # Must tell the LLM columns come from the entity, not made up.
        assert "real column" in prompt or "must be a real" in prompt


class TestUserPrompt:
    def _plan(self, description: str = "yoga studio for booking classes") -> dict:
        return {
            "description": description,
            "module_name": "Rania",
            "domain": "wellness",
            "entities": {
                "sessions": {
                    "fields": [
                        {"name": "title", "type": "text", "required": True},
                        {"name": "startAt", "type": "timestamp", "required": True},
                        {"name": "capacity", "type": "int"},
                    ],
                },
            },
        }

    def test_includes_entity_and_route(self):
        prompt = _build_user_prompt(
            self._plan(), "sessions",
            self._plan()["entities"]["sessions"], "/sessions", None,
        )
        assert "sessions" in prompt
        assert "/sessions" in prompt

    def test_includes_columns_with_types(self):
        prompt = _build_user_prompt(
            self._plan(), "sessions",
            self._plan()["entities"]["sessions"], "/sessions", None,
        )
        assert "title" in prompt
        assert "startAt" in prompt
        assert "capacity" in prompt
        # SQL type surfaces so the LLM picks kind hints correctly.
        assert "timestamp" in prompt or "int" in prompt

    def test_includes_brief_when_provided(self):
        prompt = _build_user_prompt(
            self._plan(), "sessions",
            self._plan()["entities"]["sessions"], "/sessions",
            brief_text="A warm boutique studio for adult beginners.",
        )
        assert "warm boutique" in prompt

    def test_no_brief_line_when_none(self):
        prompt = _build_user_prompt(
            self._plan(), "sessions",
            self._plan()["entities"]["sessions"], "/sessions", None,
        )
        assert "User's brief:" not in prompt

    def test_variance_hint_present_when_plan_has_identity(self):
        # Same plan-identity contract as dashboard — steers tiebreaks
        # so two same-domain apps diverge.
        prompt = _build_user_prompt(
            self._plan(), "sessions",
            self._plan()["entities"]["sessions"], "/sessions", None,
        )
        assert "VARIANCE HINT" in prompt

    def test_variance_absent_when_plan_empty(self):
        empty_plan = {"entities": {"s": {"fields": []}}}
        prompt = _build_user_prompt(
            empty_plan, "s", empty_plan["entities"]["s"], "/s", None,
        )
        assert "VARIANCE HINT" not in prompt

    def test_different_briefs_produce_different_prompts(self):
        # This is the whole Phase 2 promise for collections — same
        # domain, different briefs → different LLM prompts → different
        # column/moment picks.
        a_plan = self._plan("yoga studio, warm boutique feel")
        b_plan = self._plan("yoga studio chain, high-density admin")
        a = _build_user_prompt(
            a_plan, "sessions", a_plan["entities"]["sessions"], "/sessions",
            brief_text="warm boutique",
        )
        b = _build_user_prompt(
            b_plan, "sessions", b_plan["entities"]["sessions"], "/sessions",
            brief_text="high-density admin",
        )
        assert a != b

    def test_personality_signals_propagate(self):
        # dashboard_maquette._extract_personality_signals matches on
        # keyword categories (warm/dense/etc). The signal MUST reach
        # the prompt so the LLM can steer picks.
        plan = self._plan()
        prompt = _build_user_prompt(
            plan, "sessions", plan["entities"]["sessions"], "/sessions",
            brief_text="warm boutique studio for beginners",
        )
        assert "PERSONALITY SIGNALS" in prompt


# ─────────────────────────── author_collection_maquette ────────────────


class TestAuthorCollectionMaquette:
    def _plan(self) -> dict:
        return {
            "description": "yoga studio for booking classes",
            "module_name": "Rania",
            "entities": {
                "sessions": {
                    "fields": [
                        {"name": "title", "type": "text"},
                        {"name": "startAt", "type": "timestamp"},
                        {"name": "capacity", "type": "int"},
                    ],
                },
            },
        }

    def _run(self, coro):
        return asyncio.run(coro)

    def test_returns_none_for_non_dict_plan(self):
        assert self._run(author_collection_maquette("nope", "sessions", "/sessions")) is None  # type: ignore

    def test_returns_none_for_missing_entities(self):
        assert self._run(author_collection_maquette({"description": "x"}, "sessions", "/sessions")) is None

    def test_returns_none_for_unknown_entity(self):
        # Guard against callers passing an entity that isn't in the plan.
        # We don't want the composer trying to rewrite a schema that
        # doesn't exist.
        assert self._run(author_collection_maquette(
            self._plan(), "unknown-entity", "/x",
            query_fn=self._make_query_fn('{"entity": "unknown-entity", "route": "/x"}'),
        )) is None

    def _make_query_fn(self, response: str):
        async def _fn(system: str, user: str) -> str:  # noqa: ARG001
            return response
        return _fn

    def test_uses_injected_query_fn(self):
        response = '{"entity": "sessions", "route": "/sessions", "layout": "calendar", "columns": [{"name": "title", "label": "Class", "emphasis": true}]}'
        m = self._run(author_collection_maquette(
            self._plan(), "sessions", "/sessions",
            query_fn=self._make_query_fn(response),
        ))
        assert m is not None
        assert m.entity == "sessions"
        assert m.layout == "calendar"
        assert m.columns[0].name == "title"

    def test_query_fn_exception_returns_none(self):
        async def _boom(system: str, user: str) -> str:  # noqa: ARG001
            raise RuntimeError("LLM died")
        assert self._run(author_collection_maquette(
            self._plan(), "sessions", "/sessions", query_fn=_boom,
        )) is None

    def test_malformed_llm_response_returns_none(self):
        m = self._run(author_collection_maquette(
            self._plan(), "sessions", "/sessions",
            query_fn=self._make_query_fn("this is not JSON at all"),
        ))
        assert m is None

    def test_hallucinated_columns_dropped(self):
        # This is the important integration between author_* and
        # from_dict + _valid_columns_from — hallucinated column names
        # must NOT reach the composer.
        response = (
            '{"entity": "sessions", "route": "/sessions", "columns": ['
            '{"name": "title", "label": "T"},'
            '{"name": "invented", "label": "Fake"}'
            ']}'
        )
        m = self._run(author_collection_maquette(
            self._plan(), "sessions", "/sessions",
            query_fn=self._make_query_fn(response),
        ))
        assert m is not None
        assert [c.name for c in m.columns] == ["title"]

    def test_fenced_llm_response_is_parsed(self):
        response = '```json\n{"entity": "sessions", "route": "/sessions"}\n```'
        m = self._run(author_collection_maquette(
            self._plan(), "sessions", "/sessions",
            query_fn=self._make_query_fn(response),
        ))
        assert m is not None
        assert m.entity == "sessions"

    def test_missing_api_key_returns_none_without_query_fn(self, monkeypatch: pytest.MonkeyPatch):
        # No injected query_fn + no API key → don't crash, just skip.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        assert self._run(author_collection_maquette(
            self._plan(), "sessions", "/sessions",
        )) is None

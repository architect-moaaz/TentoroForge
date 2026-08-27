"""CREATIVE-6a — page_composer tests.

Unit + fixture-driven-integration tests for :mod:`services.page_composer`.
The LLM seam ``services.page_composer._call_llm`` is monkeypatched in the
integration cases so tests never touch the network.
"""
from __future__ import annotations

import json

import pytest

from schemas.design_brief import VisualLock
from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)
from services import page_composer
from services.page_composer import (
    _ensure_node_ids,
    _filter_manifest_for_page,
    _validate_page_schema,
    cache_key,
    compose_page,
)


# --------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _clear_cache():
    """Prevent cross-test cache leakage."""
    page_composer._reset_cache_for_tests()
    yield
    page_composer._reset_cache_for_tests()


@pytest.fixture
def manifest() -> dict:
    """Minimal cross-category manifest — one component per category.

    Real manifest has ~157 entries; a stripped-down fixture is enough for
    the subsetting + validator unit tests and keeps them fast/readable.
    """
    return {
        "components": {
            # layout
            "Stack": {"category": "layout", "data_shape": "none", "summary": ""},
            "Card":  {"category": "layout", "data_shape": "none", "summary": ""},
            "Row":   {"category": "layout", "data_shape": "none", "summary": ""},
            "Grid":  {"category": "layout", "data_shape": "none", "summary": ""},
            # display
            "Heading": {"category": "display", "data_shape": "scalar", "summary": ""},
            "Text":    {"category": "display", "data_shape": "scalar", "summary": ""},
            "Badge":   {"category": "display", "data_shape": "scalar", "summary": ""},
            # action
            "Button": {"category": "action", "data_shape": "none", "summary": ""},
            # nav
            "NavLink": {"category": "nav", "data_shape": "none", "summary": ""},
            # input
            "Input":  {"category": "input", "data_shape": "scalar", "summary": ""},
            "Select": {"category": "input", "data_shape": "scalar", "summary": ""},
            "Form":   {"category": "input", "data_shape": "none",   "summary": ""},
            # data
            "Table":            {"category": "data", "data_shape": "tabular", "summary": ""},
            "DescriptionList":  {"category": "data", "data_shape": "list",    "summary": ""},
            # chart
            "MetricTile": {"category": "chart", "data_shape": "scalar", "summary": ""},
            "Chart":      {"category": "chart", "data_shape": "series", "summary": ""},
        },
    }


@pytest.fixture
def plan() -> dict:
    """A pared-down plan that mirrors the shape of real plan.json — enough
    to exercise entity-name + field validation."""
    return {
        "description": "Small demo app for tests",
        "entities": {
            "Transaction": {
                "name": "Transaction",
                "fields": [
                    {"name": "id", "type": "uuid"},
                    {"name": "amount", "type": "numeric"},
                    {"name": "status", "type": "text"},
                    {"name": "createdAt", "type": "timestamp"},
                ],
            },
            "Customer": {
                "name": "Customer",
                "fields": [
                    {"name": "id", "type": "uuid"},
                    {"name": "fullName", "type": "text"},
                ],
            },
        },
    }


@pytest.fixture
def vocab() -> ArchetypeVocabulary:
    return ArchetypeVocabulary(
        id="banking-platform",
        section_recipes={"list": ["pending", "posted"]},
        component_preferences={
            "transactions": ComponentPreference(
                shape="ledger-list",
                primary_field="amount",
                primary_component="Table",
            ),
        },
        signature_states={
            "empty_pending": "No pending transactions.",
            "empty_posted": "No posted transactions yet.",
        },
        status_badges={
            "pending":  {"variant": "warning", "label": "Pending"},
            "posted":   {"variant": "success", "label": "Posted"},
            "disputed": {"variant": "danger",  "label": "Disputed"},
        },
        section_filters={
            "pending": {"status": "pending"},
            "posted":  {"status": "posted"},
        },
    )


@pytest.fixture
def preset() -> VisualLock:
    return VisualLock(
        palette={"bg": "#FFFFFF", "fg": "#111111", "accent": "#0055FF"},
        typography={"display": "Inter", "body": "Inter", "mono": "JetBrains Mono"},
        radius={"sm": 4, "md": 8, "lg": 16},
        shadow={"sm": "0 1px 2px rgba(0,0,0,0.08)", "md": "0 2px 6px rgba(0,0,0,0.10)"},
        preset_name="trust-navy",
    )


@pytest.fixture
def list_page() -> dict:
    return {
        "id": "transactions-list",
        "route": "/transactions",
        "kind": "list",
        "entity": "Transaction",
        "title": "Transactions",
    }


@pytest.fixture
def valid_list_schema() -> dict:
    """Hand-crafted valid Page-v2 schema the composer might plausibly emit."""
    return {
        "schemaVersion": "2",
        "id": "transactions-list",
        "route": "/transactions",
        "layout": "main",
        "dataSources": [
            {"name": "transactions", "entity": "Transaction", "op": "list"},
        ],
        "root": {
            "type": "Stack",
            "props": {"gap": "tokens.spacing.6"},
            "children": [
                {
                    "type": "Heading",
                    "props": {"content": "Transactions", "level": 1},
                },
                {
                    "type": "Table",
                    "props": {
                        "rows": "{{transactions}}",
                        "columns": [
                            {"key": "amount", "label": "Amount"},
                            {"key": "status", "label": "Status"},
                        ],
                    },
                },
            ],
        },
    }


# --------------------------------------------------------------------- #
# Manifest subsetting
# --------------------------------------------------------------------- #

class TestManifestSubsetting:
    def test_list_page_includes_data_category(self, manifest):
        subset = _filter_manifest_for_page(manifest, "list")
        names = set(subset["components"].keys())
        assert "Table" in names
        assert "DescriptionList" in names
        assert "Stack" in names            # always-include layout
        assert "Heading" in names          # always-include display

    def test_form_page_includes_input_and_excludes_data(self, manifest):
        subset = _filter_manifest_for_page(manifest, "form")
        names = set(subset["components"].keys())
        assert "Input" in names
        assert "Select" in names
        assert "Form" in names
        # data + chart are OFF for form pages
        assert "Table" not in names
        assert "Chart" not in names
        assert "MetricTile" not in names
        # layout still included
        assert "Stack" in names

    def test_dashboard_page_includes_chart(self, manifest):
        subset = _filter_manifest_for_page(manifest, "dashboard")
        names = set(subset["components"].keys())
        assert "Chart" in names
        assert "MetricTile" in names
        assert "Table" in names

    def test_settings_page_includes_input_display_no_data(self, manifest):
        subset = _filter_manifest_for_page(manifest, "settings")
        names = set(subset["components"].keys())
        assert "Input" in names
        assert "Heading" in names
        assert "Table" not in names
        assert "Chart" not in names

    def test_unknown_kind_returns_full_manifest(self, manifest):
        subset = _filter_manifest_for_page(manifest, "totally-unknown")
        # Full pass-through — better to spend tokens than to strip a
        # category the LLM legitimately needs.
        assert set(subset["components"].keys()) == set(manifest["components"].keys())

    def test_empty_manifest_is_safe(self):
        assert _filter_manifest_for_page({}, "list") == {"components": {}}
        assert _filter_manifest_for_page(None, "list") == {"components": {}}


# --------------------------------------------------------------------- #
# Validator
# --------------------------------------------------------------------- #

class TestValidator:
    def test_valid_page_passes(self, manifest, plan, valid_list_schema):
        subset = _filter_manifest_for_page(manifest, "list")
        ok, errors, warnings = _validate_page_schema(valid_list_schema, plan, subset)
        assert ok, errors
        assert errors == []

    def test_unknown_type_fails(self, manifest, plan, valid_list_schema):
        subset = _filter_manifest_for_page(manifest, "list")
        valid_list_schema["root"]["children"][1]["type"] = "TotallyMadeUp"
        ok, errors, _ = _validate_page_schema(valid_list_schema, plan, subset)
        assert not ok
        assert any("TotallyMadeUp" in e for e in errors)

    def test_unknown_datasource_entity_fails(self, manifest, plan, valid_list_schema):
        subset = _filter_manifest_for_page(manifest, "list")
        valid_list_schema["dataSources"][0]["entity"] = "GhostEntity"
        ok, errors, _ = _validate_page_schema(valid_list_schema, plan, subset)
        assert not ok
        assert any("GhostEntity" in e for e in errors)

    def test_missing_stack_root_fails(self, manifest, plan, valid_list_schema):
        subset = _filter_manifest_for_page(manifest, "list")
        valid_list_schema["root"]["type"] = "Card"
        ok, errors, _ = _validate_page_schema(valid_list_schema, plan, subset)
        assert not ok
        assert any("Stack" in e for e in errors)

    def test_unresolvable_binding_fails(self, manifest, plan, valid_list_schema):
        subset = _filter_manifest_for_page(manifest, "list")
        # Change the Table row binding to reference a non-existent source.
        valid_list_schema["root"]["children"][1]["props"]["rows"] = "{{ghosts}}"
        ok, errors, _ = _validate_page_schema(valid_list_schema, plan, subset)
        assert not ok
        assert any("ghosts" in e for e in errors)

    def test_missing_gap_on_root_is_warning_not_error(self, manifest, plan, valid_list_schema):
        subset = _filter_manifest_for_page(manifest, "list")
        del valid_list_schema["root"]["props"]["gap"]
        ok, errors, warnings = _validate_page_schema(valid_list_schema, plan, subset)
        assert ok, errors
        assert any("gap" in w for w in warnings)

    def test_field_typo_binding_is_warning(self, manifest, plan, valid_list_schema):
        """`{{transactions.wibble}}` — dataSource exists, field is not on
        the entity. Downgraded to warning because nested/relational hops
        would otherwise false-positive."""
        subset = _filter_manifest_for_page(manifest, "list")
        valid_list_schema["root"]["children"][0]["props"]["content"] = "{{transactions.wibble}}"
        ok, errors, warnings = _validate_page_schema(valid_list_schema, plan, subset)
        assert ok, errors
        assert any("wibble" in w for w in warnings)

    def test_reserved_binding_roots_pass(self, manifest, plan, valid_list_schema):
        """`{{route.id}}` / `{{now}}` / `{{tokens.spacing.6}}` must not
        register as unknown dataSources."""
        subset = _filter_manifest_for_page(manifest, "list")
        valid_list_schema["root"]["children"][0]["props"]["content"] = "Row {{route.id}} at {{now}}"
        ok, errors, _ = _validate_page_schema(valid_list_schema, plan, subset)
        assert ok, errors

    def test_repeat_alias_is_accepted_as_binding_root(self, manifest, plan, valid_list_schema):
        """A Repeat's ``props.as`` declares a per-row local alias; text
        inside the loop referencing that alias must not fail validation."""
        subset = _filter_manifest_for_page(manifest, "list")
        # Replace the Table child with a Repeat body referencing `plan`.
        valid_list_schema["root"]["children"][1] = {
            "type": "Repeat",
            "props": {"source": "transactions", "as": "plan"},
            "children": [
                {"type": "Text", "props": {"content": "{{plan.amount}}"}},
            ],
        }
        # `Repeat` + `Text` aren't in the small fixture manifest — add them
        # temporarily so ONLY the binding check is on trial.
        subset["components"]["Repeat"] = {"category": "layout", "data_shape": "none"}
        ok, errors, _ = _validate_page_schema(valid_list_schema, plan, subset)
        assert ok, errors

    def test_configuration_dict_in_props_is_not_a_node(self, manifest, plan, valid_list_schema):
        """Table.props.columns items carry ``{type: "select"}`` filter
        configuration — those are prop config, not library components,
        so the validator must not test them against the manifest."""
        subset = _filter_manifest_for_page(manifest, "list")
        valid_list_schema["root"]["children"][1]["props"]["columns"] = [
            # {type: "select"} here is a column filter spec, NOT a Node.
            {"key": "status", "label": "Status", "filter": {"type": "select", "options": []}},
        ]
        ok, errors, _ = _validate_page_schema(valid_list_schema, plan, subset)
        assert ok, errors


# --------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------- #

class TestCacheKey:
    def test_same_inputs_produce_same_key(
        self, list_page, plan, vocab, preset, manifest,
    ):
        subset = _filter_manifest_for_page(manifest, "list")
        k1 = cache_key(list_page, plan, vocab, preset, subset, variance_seed=42)
        k2 = cache_key(list_page, plan, vocab, preset, subset, variance_seed=42)
        assert k1 == k2

    def test_different_variance_seed_misses(
        self, list_page, plan, vocab, preset, manifest,
    ):
        subset = _filter_manifest_for_page(manifest, "list")
        k1 = cache_key(list_page, plan, vocab, preset, subset, variance_seed=42)
        k2 = cache_key(list_page, plan, vocab, preset, subset, variance_seed=99)
        assert k1 != k2

    def test_different_page_route_misses(
        self, list_page, plan, vocab, preset, manifest,
    ):
        subset = _filter_manifest_for_page(manifest, "list")
        k1 = cache_key(list_page, plan, vocab, preset, subset)
        other = {**list_page, "route": "/somewhere/else"}
        k2 = cache_key(other, plan, vocab, preset, subset)
        assert k1 != k2


# --------------------------------------------------------------------- #
# Integration — compose_page with a mocked LLM
# --------------------------------------------------------------------- #

class TestComposePage:
    @pytest.mark.asyncio
    async def test_valid_composition_succeeds(
        self, monkeypatch, list_page, plan, vocab, preset, manifest, valid_list_schema,
    ):
        async def _fake(prompt, **_kw):
            return valid_list_schema

        monkeypatch.setattr(page_composer, "_call_llm", _fake)
        schema, prov = await compose_page(
            list_page, plan, vocab, preset, manifest,
            patterns=[{"name": "ledger-density"}], variance_seed=7,
        )
        assert schema is not None
        assert prov["source"] == "composed"
        assert prov["route"] == "/transactions"
        assert prov["changes"]["data_sources_emitted"] == 1
        assert prov["validation"]["errors"] == []

    @pytest.mark.asyncio
    async def test_cache_hit_second_call(
        self, monkeypatch, list_page, plan, vocab, preset, manifest, valid_list_schema,
    ):
        calls = {"n": 0}

        async def _fake(prompt, **_kw):
            calls["n"] += 1
            return valid_list_schema

        monkeypatch.setattr(page_composer, "_call_llm", _fake)
        schema1, prov1 = await compose_page(
            list_page, plan, vocab, preset, manifest, variance_seed=7,
        )
        schema2, prov2 = await compose_page(
            list_page, plan, vocab, preset, manifest, variance_seed=7,
        )
        assert schema1 is not None and schema2 is not None
        assert calls["n"] == 1
        assert prov1["source"] == "composed"
        assert prov2["source"] == "cached"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(
        self, monkeypatch, list_page, plan, vocab, preset, manifest,
    ):
        async def _fake(prompt, **_kw):
            raise json.JSONDecodeError("expecting value", "broken", 0)

        monkeypatch.setattr(page_composer, "_call_llm", _fake)
        schema, prov = await compose_page(
            list_page, plan, vocab, preset, manifest,
        )
        assert schema is None
        assert prov["source"] == "failed"
        assert prov["reason"] == "invalid_json"

    @pytest.mark.asyncio
    async def test_unknown_component_fails_validation(
        self, monkeypatch, list_page, plan, vocab, preset, manifest, valid_list_schema,
    ):
        bad = json.loads(json.dumps(valid_list_schema))
        bad["root"]["children"][1]["type"] = "NotAComponent"

        async def _fake(prompt, **_kw):
            return bad

        monkeypatch.setattr(page_composer, "_call_llm", _fake)
        schema, prov = await compose_page(
            list_page, plan, vocab, preset, manifest,
        )
        assert schema is None
        assert prov["source"] == "failed"
        assert prov["reason"] == "validation_failed"
        assert any("NotAComponent" in e for e in prov["validation"]["errors"])

    @pytest.mark.asyncio
    async def test_timeout_returns_none(
        self, monkeypatch, list_page, plan, vocab, preset, manifest,
    ):
        import asyncio as _aio

        async def _fake(prompt, **_kw):
            raise _aio.TimeoutError()

        monkeypatch.setattr(page_composer, "_call_llm", _fake)
        schema, prov = await compose_page(
            list_page, plan, vocab, preset, manifest,
        )
        assert schema is None
        assert prov["source"] == "failed"
        assert prov["reason"] == "timeout"

    @pytest.mark.asyncio
    async def test_non_object_response_fails(
        self, monkeypatch, list_page, plan, vocab, preset, manifest,
    ):
        async def _fake(prompt, **_kw):
            return ["not", "an", "object"]

        monkeypatch.setattr(page_composer, "_call_llm", _fake)
        schema, prov = await compose_page(
            list_page, plan, vocab, preset, manifest,
        )
        assert schema is None
        assert prov["source"] == "failed"
        assert prov["reason"] == "non_object"


# --------------------------------------------------------------------- #
# Auto-id — every composed node gets a stable ``id`` at compose time so
# LLM-composed schemas don't drop React "unique key" warnings into the
# generated app's dev console.
# --------------------------------------------------------------------- #

class TestEnsureNodeIds:
    def test_assigns_ids_to_every_node_when_none_present(self):
        schema = {
            "root": {
                "type": "Stack",
                "children": [
                    {"type": "Heading", "props": {"content": "T"}},
                    {"type": "Text", "props": {"content": "b"}},
                    {"type": "Stack", "children": [
                        {"type": "Text", "props": {"content": "nested"}},
                    ]},
                ],
            },
        }
        n = _ensure_node_ids(schema)
        # root + 3 top-level children + 1 nested = 5 nodes
        assert n == 5
        assert schema["root"]["id"] == "root"
        ids = [c["id"] for c in schema["root"]["children"]]
        assert ids == [
            "root-Heading-0",
            "root-Text-0",
            "root-Stack-0",
        ]
        assert schema["root"]["children"][2]["children"][0]["id"] == "root-Stack-0-Text-0"

    def test_never_overwrites_existing_ids(self):
        schema = {
            "root": {
                "type": "Stack",
                "id": "keep-me",
                "children": [
                    {"type": "Text", "id": "text-preserved", "props": {}},
                    {"type": "Text", "props": {}},
                ],
            },
        }
        n = _ensure_node_ids(schema)
        assert n == 1  # only the un-id'd Text
        assert schema["root"]["id"] == "keep-me"
        assert schema["root"]["children"][0]["id"] == "text-preserved"
        # Path is derived from the fixed "root" prefix (not the parent's
        # kept id) — deterministic + simple. The kept ids on ancestors
        # aren't retroactively rewired into descendant paths.
        assert schema["root"]["children"][1]["id"] == "root-Text-1"

    def test_deterministic_across_calls(self):
        def _mk():
            return {
                "root": {
                    "type": "Stack",
                    "children": [
                        {"type": "Text", "props": {"content": "a"}},
                        {"type": "Text", "props": {"content": "b"}},
                    ],
                }
            }
        a = _mk(); b = _mk()
        _ensure_node_ids(a); _ensure_node_ids(b)
        assert a == b

    def test_siblings_with_same_type_get_unique_ids(self):
        """The bug we're fixing: two <Text> siblings without ids used to
        collapse to the same synthetic React key. Ids must differ."""
        schema = {
            "root": {
                "type": "Stack",
                "children": [
                    {"type": "Text", "props": {}},
                    {"type": "Text", "props": {}},
                    {"type": "Text", "props": {}},
                ],
            },
        }
        _ensure_node_ids(schema)
        ids = [c["id"] for c in schema["root"]["children"]]
        assert len(set(ids)) == 3, f"expected unique ids, got {ids}"

    def test_ignores_props_dicts_with_type_field(self):
        """Table.props.columns carries {type: "select"} — filter config,
        not a library component. Must not receive an id."""
        schema = {
            "root": {
                "type": "Stack",
                "children": [
                    {
                        "type": "Table",
                        "props": {
                            "columns": [
                                {"key": "status", "filter": {"type": "select"}},
                            ],
                        },
                    },
                ],
            },
        }
        _ensure_node_ids(schema)
        col = schema["root"]["children"][0]["props"]["columns"][0]
        assert "id" not in col
        assert "id" not in col["filter"]

    def test_no_root_key_is_safe(self):
        assert _ensure_node_ids({}) == 0
        assert _ensure_node_ids({"root": None}) == 0
        assert _ensure_node_ids("not a dict") == 0

    @pytest.mark.asyncio
    async def test_compose_page_output_has_ids_on_every_node(
        self, monkeypatch, list_page, plan, vocab, preset, manifest,
    ):
        # Craft a valid schema deliberately WITHOUT any ids — mirrors the
        # actual LLM output on disk (see output/ugsy63ed/src/schemas/*.json).
        schema_no_ids = {
            "schemaVersion": "2",
            "id": "transactions-list",
            "route": "/transactions",
            "layout": "main",
            "dataSources": [
                {"name": "transactions", "entity": "Transaction", "op": "list"},
            ],
            "root": {
                "type": "Stack",
                "props": {"gap": "tokens.spacing.6"},
                "children": [
                    {"type": "Heading", "props": {"content": "Transactions", "level": 1}},
                    {"type": "Table", "props": {"rows": "{{transactions}}", "columns": []}},
                ],
            },
        }

        async def _fake(prompt, **_kw):
            return schema_no_ids

        monkeypatch.setattr(page_composer, "_call_llm", _fake)
        schema, prov = await compose_page(
            list_page, plan, vocab, preset, manifest,
        )
        assert schema is not None
        assert prov["source"] == "composed"
        # Every node in the tree must carry an id after composition.
        def _all_have_ids(node):
            if not isinstance(node, dict):
                return True
            if isinstance(node.get("type"), str) and not node.get("id"):
                return False
            for c in (node.get("children") or []):
                if not _all_have_ids(c):
                    return False
            return True
        assert _all_have_ids(schema["root"])
        assert prov["changes"]["ids_assigned"] >= 3  # root + heading + table

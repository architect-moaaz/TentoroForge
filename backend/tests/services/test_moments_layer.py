"""Phase 2 slice — dashboard moments layer.

Tests for the moments-layer extensions to DashboardMaquette:
- HeroSpec.kind variants (photo-greeting, personalised-greeting,
  editorial-quote, kpi-strip, balance-rings)
- signature_moves list
- section_rhythm density hint

Pins the decision-object shape + parser + composer behaviour so future
Phase 2 work doesn't drift the contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.dashboard_maquette import (
    DashboardMaquette,
    HeroSpec,
    HERO_KINDS,
    SECTION_RHYTHMS,
    _build_user_prompt,
    _extract_personality_signals,
    _read_21st_references,
)
from services.apply_dashboard_maquette import _build_hero_node


# ---------------------------------------------------------------------------
# HeroSpec + parser
# ---------------------------------------------------------------------------


class TestHeroSpecKinds:
    def test_default_kind_is_photo_greeting(self):
        h = HeroSpec()
        assert h.kind == "photo-greeting"

    def test_allowed_kinds(self):
        # Anti-regression: composer branches on exactly these values.
        # Adding a new kind = also add a branch in _build_hero_node.
        assert set(HERO_KINDS) == {
            "photo-greeting",
            "personalised-greeting",
            "editorial-quote",
            "kpi-strip",
            "balance-rings",
        }

    def test_editorial_quote_fields_survive_to_dict(self):
        h = HeroSpec(
            kind="editorial-quote",
            quote="Show up for yourself.",
            attribution="— Rania, founder",
        )
        d = h.to_dict()
        assert d["kind"] == "editorial-quote"
        assert d["quote"] == "Show up for yourself."
        assert d["attribution"] == "— Rania, founder"
        # No greeting → not emitted (empty strings suppressed).
        assert "greeting" not in d
        assert "photo_subject" not in d


class TestFromDictParsesNewFields:
    def test_hero_kind_photo_greeting_legacy_shape(self):
        # Pre-Phase-2 payloads without `kind` still parse as
        # photo-greeting (back-compat contract).
        m = DashboardMaquette.from_dict({
            "hero": {
                "photo_subject": "yoga studio at dawn",
                "greeting": "Welcome back",
            },
        })
        assert m.hero is not None
        assert m.hero.kind == "photo-greeting"
        assert m.hero.photo_subject == "yoga studio at dawn"
        assert m.hero.greeting == "Welcome back"

    def test_hero_kind_editorial_quote(self):
        m = DashboardMaquette.from_dict({
            "hero": {
                "kind": "editorial-quote",
                "quote": "Show up for yourself.",
                "attribution": "— Rania",
            },
        })
        assert m.hero is not None
        assert m.hero.kind == "editorial-quote"
        assert m.hero.quote == "Show up for yourself."
        assert m.hero.attribution == "— Rania"

    def test_hero_kind_personalised_greeting_no_photo_needed(self):
        m = DashboardMaquette.from_dict({
            "hero": {
                "kind": "personalised-greeting",
                "greeting": "Welcome back, {firstName}",
            },
        })
        assert m.hero is not None
        assert m.hero.kind == "personalised-greeting"

    def test_hero_kind_editorial_quote_without_quote_dropped(self):
        # Required field missing for the chosen kind → hero dropped
        # (rather than emit a broken node the composer can't render).
        m = DashboardMaquette.from_dict({
            "hero": {"kind": "editorial-quote"},  # no `quote`
        })
        assert m.hero is None

    def test_hero_kind_photo_greeting_without_photo_dropped(self):
        m = DashboardMaquette.from_dict({
            "hero": {"kind": "photo-greeting", "greeting": "Hi"},  # no photo_subject
        })
        assert m.hero is None

    def test_unknown_kind_falls_back_to_photo_greeting(self):
        m = DashboardMaquette.from_dict({
            "hero": {
                "kind": "space-station",   # not in HERO_KINDS
                "photo_subject": "x",
                "greeting": "y",
            },
        })
        # Falls back to photo-greeting (the safe default the composer
        # always knows how to render).
        assert m.hero is not None
        assert m.hero.kind == "photo-greeting"

    def test_signature_moves_parse_from_list(self):
        m = DashboardMaquette.from_dict({
            "signature_moves": ["personalised-greeting", "activity-avatar-strip", 42, ""],
        })
        # Strings only; empties + non-strings dropped.
        assert m.signature_moves == ["personalised-greeting", "activity-avatar-strip"]

    def test_signature_moves_default_empty(self):
        m = DashboardMaquette.from_dict({})
        assert m.signature_moves == []

    def test_signature_moves_trimmed(self):
        m = DashboardMaquette.from_dict({
            "signature_moves": ["  sparkline-preview  ", "  "],
        })
        assert m.signature_moves == ["sparkline-preview"]

    def test_section_rhythm_valid_value(self):
        for r in SECTION_RHYTHMS:
            m = DashboardMaquette.from_dict({"section_rhythm": r})
            assert m.section_rhythm == r

    def test_section_rhythm_invalid_falls_back_to_cozy(self):
        m = DashboardMaquette.from_dict({"section_rhythm": "extreme"})
        assert m.section_rhythm == "cozy"

    def test_section_rhythm_default_cozy(self):
        m = DashboardMaquette.from_dict({})
        assert m.section_rhythm == "cozy"


class TestToDict:
    def test_new_fields_appear_in_output(self):
        m = DashboardMaquette(
            signature_moves=["a", "b"],
            section_rhythm="generous",
        )
        d = m.to_dict()
        assert d["signature_moves"] == ["a", "b"]
        assert d["section_rhythm"] == "generous"

    def test_default_maquette_dict_shape(self):
        m = DashboardMaquette()
        d = m.to_dict()
        # Every declared field appears (even when empty) — the composer
        # relies on the presence of keys, not just non-empty values.
        assert set(d.keys()) == {
            "kpis", "primary_chart", "activity", "hero",
            "signature_moves", "section_rhythm",
            # Phase 2 slot extensions — always present, null when unset.
            "empty_state", "ornament", "footer",
            # Slice C chrome — subtitle + filter bar + reset chip.
            "subtitle", "filters", "reset_filters",
        }
        assert d["kpis"] == []
        assert d["signature_moves"] == []
        assert d["section_rhythm"] == "cozy"
        assert d["empty_state"] is None
        assert d["ornament"] is None
        assert d["footer"] is None
        assert d["subtitle"] is None
        assert d["filters"] == []
        assert d["reset_filters"] is False


# ---------------------------------------------------------------------------
# Composer — _build_hero_node
# ---------------------------------------------------------------------------


class TestBuildHeroNode:
    def test_photo_greeting_emits_legacy_hero(self):
        node = _build_hero_node({
            "kind": "photo-greeting",
            "photo_subject": "yoga at dawn",
            "greeting": "Welcome back",
            "subhead": "3 classes today",
        })
        assert node is not None
        assert node["type"] == "Hero"
        assert node["props"]["title"] == "Welcome back"
        assert node["props"]["subtitle"] == "3 classes today"
        assert node["props"]["photoSubject"] == "yoga at dawn"
        assert node["props"]["data-hero-kind"] == "photo-greeting"

    def test_personalised_greeting_no_photo(self):
        node = _build_hero_node({
            "kind": "personalised-greeting",
            "greeting": "Welcome back, {firstName}",
        })
        assert node is not None
        assert node["type"] == "Hero"
        assert node["props"]["title"] == "Welcome back, {firstName}"
        assert node["props"]["photoSubject"] == ""
        assert node["props"]["data-hero-kind"] == "personalised-greeting"

    def test_editorial_quote_wraps_in_card(self):
        node = _build_hero_node({
            "kind": "editorial-quote",
            "quote": "Show up for yourself.",
            "attribution": "— Rania",
        })
        assert node is not None
        assert node["type"] == "Card"
        assert node["props"]["data-hero-kind"] == "editorial-quote"
        # Padded surface so the quote reads as a moment.
        assert "padding" in node["props"]
        # Children: Heading (quote) + Text (attribution).
        assert len(node["children"]) == 2
        assert node["children"][0]["type"] == "Heading"
        assert node["children"][0]["props"]["content"] == "Show up for yourself."
        assert node["children"][1]["type"] == "Text"
        assert "Rania" in node["children"][1]["props"]["content"]

    def test_editorial_quote_without_attribution(self):
        node = _build_hero_node({
            "kind": "editorial-quote",
            "quote": "Ship it.",
        })
        assert node is not None
        # Just the quote heading, no attribution Text.
        assert len(node["children"]) == 1
        assert node["children"][0]["type"] == "Heading"

    def test_editorial_quote_missing_quote_returns_none(self):
        node = _build_hero_node({"kind": "editorial-quote"})
        assert node is None

    def test_kpi_strip_marks_hero(self):
        node = _build_hero_node({
            "kind": "kpi-strip",
            "greeting": "Today at a glance",
        })
        assert node is not None
        assert node["type"] == "Hero"
        assert node["props"]["data-hero-kind"] == "kpi-strip"

    def test_balance_rings_marks_hero(self):
        node = _build_hero_node({
            "kind": "balance-rings",
            "greeting": "Your balance",
        })
        assert node is not None
        assert node["props"]["data-hero-kind"] == "balance-rings"

    def test_missing_greeting_for_text_hero_returns_none(self):
        for kind in ("personalised-greeting", "kpi-strip", "balance-rings"):
            node = _build_hero_node({"kind": kind})
            assert node is None, f"{kind} should require greeting"

    def test_unknown_kind_falls_back_to_photo_greeting(self):
        node = _build_hero_node({
            "kind": "totally-invented",
            "greeting": "Hi",
            "photo_subject": "x",
        })
        assert node is not None
        # Renders as the safe default; data-hero-kind reflects that.
        assert node["props"]["data-hero-kind"] == "photo-greeting"


# ---------------------------------------------------------------------------
# End-to-end: apply_maquette_to_dashboard threads new fields into the schema
# ---------------------------------------------------------------------------


class TestApplyThreadsNewFields:
    def _setup(self, tmp_path: Path, maquette: dict) -> Path:
        contracts = tmp_path / "src" / "contracts"
        schemas = tmp_path / "src" / "schemas"
        contracts.mkdir(parents=True)
        schemas.mkdir(parents=True)
        (contracts / "dashboard-maquette.json").write_text(json.dumps(maquette), encoding="utf-8")
        (contracts / "plan.json").write_text(json.dumps({
            "pages": [{"route": "/dashboard", "type": "dashboard"}],
        }), encoding="utf-8")
        (schemas / "dashboard.json").write_text("{}", encoding="utf-8")
        return schemas / "dashboard.json"

    def test_section_rhythm_generous_maps_to_larger_gap(self, tmp_path):
        from services.apply_dashboard_maquette import apply_maquette_to_dashboard
        schema_path = self._setup(tmp_path, {
            "hero": {
                "kind": "photo-greeting",
                "photo_subject": "x", "greeting": "y",
            },
            "section_rhythm": "generous",
        })
        result = apply_maquette_to_dashboard(str(tmp_path))
        assert result["applied"]
        written = json.loads(schema_path.read_text(encoding="utf-8"))
        assert written["root"]["props"]["gap"] == "tokens.spacing.10"

    def test_section_rhythm_tight_maps_to_smaller_gap(self, tmp_path):
        from services.apply_dashboard_maquette import apply_maquette_to_dashboard
        schema_path = self._setup(tmp_path, {
            "hero": {
                "kind": "photo-greeting",
                "photo_subject": "x", "greeting": "y",
            },
            "section_rhythm": "tight",
        })
        result = apply_maquette_to_dashboard(str(tmp_path))
        assert result["applied"]
        written = json.loads(schema_path.read_text(encoding="utf-8"))
        # "tight" floors at spacing.4 — 12px between full sections read as
        # cramped on every live review (cwx1stzz), so density stays
        # relative (below the cozy spacing.6) without fusing sections.
        assert written["root"]["props"]["gap"] == "tokens.spacing.4"

    def test_signature_moves_emitted_as_data_attr(self, tmp_path):
        from services.apply_dashboard_maquette import apply_maquette_to_dashboard
        schema_path = self._setup(tmp_path, {
            "hero": {
                "kind": "photo-greeting",
                "photo_subject": "x", "greeting": "y",
            },
            "signature_moves": ["sparkline-preview", "activity-avatar-strip"],
        })
        result = apply_maquette_to_dashboard(str(tmp_path))
        assert result["applied"]
        written = json.loads(schema_path.read_text(encoding="utf-8"))
        sig = written["root"]["props"].get("data-signature-move", "")
        assert "sparkline-preview" in sig
        assert "activity-avatar-strip" in sig


# ---------------------------------------------------------------------------
# Brief propagation (Phase 2 slice C — personality signal extraction)
# ---------------------------------------------------------------------------


class TestPersonalitySignalExtraction:
    def test_warm_editorial_signal(self):
        signals = _extract_personality_signals(
            "A warm, boutique yoga studio with an editorial feel."
        )
        assert "warm / boutique / editorial" in signals

    def test_dense_admin_signal(self):
        signals = _extract_personality_signals(
            "Dense admin dashboard for power users."
        )
        assert "dense / admin / efficient" in signals

    def test_multiple_signals_all_hit(self):
        # A brief mixing warm + modern should surface BOTH signals so the
        # LLM has room to balance them.
        signals = _extract_personality_signals(
            "Modern, minimal yoga studio with warm, hand-crafted photography."
        )
        assert "warm / boutique / editorial" in signals
        assert "modern / minimal / techy" in signals

    def test_empty_brief_returns_no_signals(self):
        assert _extract_personality_signals(None) == []
        assert _extract_personality_signals("") == []

    def test_no_matches_returns_empty(self):
        assert _extract_personality_signals(
            "A basic CRUD app for tracking items."
        ) == []

    def test_case_insensitive(self):
        # Keyword match must not care about brief-writing case.
        signals = _extract_personality_signals("PLAYFUL CONSUMER APP")
        assert "playful / consumer / bright" in signals


class TestReferencePropagation:
    def test_empty_when_no_output_dir(self):
        # Plan without _output_dir (unit-test path) never reads disk.
        assert _read_21st_references({}) == []
        assert _read_21st_references(None) == []  # type: ignore
        assert _read_21st_references("not a plan") == []  # type: ignore

    def test_empty_when_dir_missing(self, tmp_path):
        assert _read_21st_references({"_output_dir": str(tmp_path)}) == []

    def test_reads_reference_names(self, tmp_path):
        ref_dir = tmp_path / "src" / "contracts" / "references"
        ref_dir.mkdir(parents=True)
        (ref_dir / "a.json").write_text(json.dumps({
            "name": "Balance Rings Dashboard",
            "description": "Circular progress rings with ambient background.",
        }), encoding="utf-8")
        (ref_dir / "b.json").write_text(json.dumps({
            "name": "Editorial Hero",
        }), encoding="utf-8")
        refs = _read_21st_references({"_output_dir": str(tmp_path)})
        assert len(refs) == 2
        assert any("Balance Rings" in r for r in refs)
        assert any("Editorial Hero" == r for r in refs)  # no description = just name

    def test_ignores_bad_json_files(self, tmp_path):
        ref_dir = tmp_path / "src" / "contracts" / "references"
        ref_dir.mkdir(parents=True)
        (ref_dir / "bad.json").write_text("not json {{{", encoding="utf-8")
        (ref_dir / "ok.json").write_text(json.dumps({"name": "Good One"}), encoding="utf-8")
        refs = _read_21st_references({"_output_dir": str(tmp_path)})
        assert refs == ["Good One"]


class TestUserPromptComposition:
    def test_variance_seed_appears_in_prompt(self):
        # The seed must be visible to the LLM so it can key tiebreaks off it.
        prompt = _build_user_prompt(
            {"description": "yoga studio", "module_name": "Rania", "entities": {"session": {}}},
            brief_text=None,
        )
        assert "VARIANCE HINT" in prompt
        # And the actual seed value is embedded so different briefs → visibly different prompts.
        from services.pipeline.variance import variance_seed_for
        seed = variance_seed_for({"description": "yoga studio", "module_name": "Rania"})
        assert str(seed) in prompt

    def test_personality_signals_render_when_brief_has_keywords(self):
        prompt = _build_user_prompt(
            {"description": "x", "entities": {"e": {}}},
            brief_text="A warm, boutique yoga studio.",
        )
        assert "PERSONALITY SIGNALS" in prompt
        assert "warm / boutique / editorial" in prompt

    def test_personality_block_absent_when_no_signals(self):
        prompt = _build_user_prompt(
            {"description": "x", "entities": {"e": {}}},
            brief_text="Just a basic app.",  # no trigger words
        )
        assert "PERSONALITY SIGNALS" not in prompt

    def test_references_block_absent_without_output_dir(self):
        prompt = _build_user_prompt(
            {"description": "x", "entities": {"e": {}}},
            brief_text=None,
        )
        assert "DESIGN REFERENCES" not in prompt

    def test_references_block_appears_when_refs_on_disk(self, tmp_path):
        ref_dir = tmp_path / "src" / "contracts" / "references"
        ref_dir.mkdir(parents=True)
        (ref_dir / "hero.json").write_text(json.dumps({"name": "Aurora Hero"}), encoding="utf-8")
        prompt = _build_user_prompt(
            {"description": "x", "entities": {"e": {}}, "_output_dir": str(tmp_path)},
            brief_text=None,
        )
        assert "DESIGN REFERENCES" in prompt
        assert "Aurora Hero" in prompt

    def test_different_briefs_produce_different_prompts(self):
        # End-to-end: two yoga apps with different descriptions produce
        # measurably different prompts (variance seeds + personality
        # signals both diverge them). This is the core Phase 2 contract.
        p1 = _build_user_prompt(
            {"description": "Rania's boutique yoga studio", "entities": {"s": {}}},
            brief_text="Warm, hand-crafted feel.",
        )
        p2 = _build_user_prompt(
            {"description": "YogaFlex chain admin dashboard", "entities": {"s": {}}},
            brief_text="Dense, efficient, power-user oriented.",
        )
        assert p1 != p2
        # And the divergence isn't just field values — the personality
        # signals differ too.
        assert "warm / boutique / editorial" in p1
        assert "dense / admin / efficient" in p2

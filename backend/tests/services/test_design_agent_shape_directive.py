"""Tests for M3-T7: design_agent reads plan.app_shape.layout.hero + density.

The substrate's layout.hero (8 values) and layout.density (spacious | comfortable
| dense) become a hard-constraint prompt block appended to the design agent's
user prompt. Density maps `dense` → `compact` for design-spec compatibility."""
from __future__ import annotations

import pytest

from services.design_agent_shape_directive import (
    _DENSITY_GUIDANCE,
    _DENSITY_TO_SPEC,
    _HERO_GUIDANCE,
    build_directive,
    read_density,
    read_hero,
    spec_density_for,
)


def _shape(hero: str | None = None, density: str | None = None) -> dict:
    layout: dict = {
        "shell": "sidebar",
        "primaryInteraction": "data-grid",
    }
    if hero is not None:
        layout["hero"] = hero
    if density is not None:
        layout["density"] = density
    return {"app_shape": {"layout": layout}}


# ══════════════════════════════════════════════════════════════════
# read_hero — the pure reader
# ══════════════════════════════════════════════════════════════════


class TestReadHero:
    def test_returns_none_when_plan_missing(self):
        assert read_hero(None) is None
        assert read_hero({}) is None
        assert read_hero("plan?") is None

    def test_returns_none_when_shape_missing(self):
        assert read_hero({"industry": "x"}) is None

    def test_returns_none_when_layout_missing(self):
        assert read_hero({"app_shape": {"auth": {}}}) is None

    def test_returns_none_when_hero_missing(self):
        assert read_hero({"app_shape": {"layout": {"shell": "sidebar"}}}) is None

    def test_returns_all_valid_hero_values(self):
        # Every value in vocabulary.json:layout.hero has a guidance line and
        # is passed through by the reader.
        for hero in _HERO_GUIDANCE.keys():
            plan = _shape(hero=hero)
            assert read_hero(plan) == hero

    def test_unknown_hero_returns_none(self):
        # LLM emits a value not in the vocabulary → silent fallback (no crash,
        # no directive line for hero).
        plan = _shape(hero="chocolate")
        assert read_hero(plan) is None


# ══════════════════════════════════════════════════════════════════
# read_density — the pure reader
# ══════════════════════════════════════════════════════════════════


class TestReadDensity:
    def test_returns_none_when_plan_missing(self):
        assert read_density(None) is None
        assert read_density({}) is None

    def test_returns_all_three_densities(self):
        for d in ("dense", "comfortable", "spacious"):
            assert read_density(_shape(density=d)) == d

    def test_unknown_density_returns_none(self):
        assert read_density(_shape(density="loose")) is None


# ══════════════════════════════════════════════════════════════════
# spec_density_for — vocabulary → design-spec token
# ══════════════════════════════════════════════════════════════════


class TestSpecDensityFor:
    def test_dense_maps_to_compact(self):
        # Substrate says `dense`; design-spec already speaks `compact`.
        assert spec_density_for("dense") == "compact"

    def test_comfortable_and_spacious_passthrough(self):
        assert spec_density_for("comfortable") == "comfortable"
        assert spec_density_for("spacious") == "spacious"

    def test_none_or_unknown_returns_none(self):
        assert spec_density_for(None) is None
        assert spec_density_for("loose") is None


# ══════════════════════════════════════════════════════════════════
# build_directive — the prompt block
# ══════════════════════════════════════════════════════════════════


class TestBuildDirective:
    def test_no_shape_returns_empty(self):
        # Byte-identical prompt behavior when no substrate is present.
        assert build_directive(None) == ""
        assert build_directive({}) == ""
        assert build_directive({"industry": "x"}) == ""

    def test_only_hero_no_density(self):
        block = build_directive(_shape(hero="full-bleed-gradient"))
        assert "hero = `full-bleed-gradient`" in block
        assert "Full-bleed gradient hero" in block
        # No density line when density isn't in the plan
        assert "density =" not in block

    def test_only_density_no_hero(self):
        block = build_directive(_shape(density="dense"))
        assert "density = `dense`" in block
        # Maps to compact for design-spec
        assert 'layout.density: "compact"' in block
        assert "hero =" not in block

    def test_both_hero_and_density(self):
        block = build_directive(_shape(hero="metric-row", density="comfortable"))
        assert "hero = `metric-row`" in block
        assert "Metric-row hero" in block
        assert "density = `comfortable`" in block
        assert 'layout.density: "comfortable"' in block

    def test_directive_header_present(self):
        block = build_directive(_shape(hero="none"))
        assert "Shape Directive" in block
        assert "HARD CONSTRAINTS" in block

    def test_all_hero_values_produce_directive(self):
        # Round-trip: every valid hero value emits a directive line naming it.
        for hero in _HERO_GUIDANCE.keys():
            block = build_directive(_shape(hero=hero))
            assert f"hero = `{hero}`" in block, f"missing hero directive for {hero}"

    def test_all_density_values_produce_directive(self):
        for density, spec in _DENSITY_TO_SPEC.items():
            block = build_directive(_shape(density=density))
            assert f"density = `{density}`" in block
            assert f'layout.density: "{spec}"' in block


# ══════════════════════════════════════════════════════════════════
# End-to-end: Snap2App vs enterprise workspace
# ══════════════════════════════════════════════════════════════════


class TestShapeEndToEnd:
    def test_snap2app_full_bleed_gradient_spacious(self):
        # Snap2App-style hero page: full-bleed gradient + spacious density
        plan = {
            "app_shape": {
                "layout": {
                    "shell": "none",
                    "hero": "full-bleed-gradient",
                    "primaryInteraction": "capture",
                    "density": "spacious",
                },
            }
        }
        block = build_directive(plan)
        assert "Full-bleed gradient hero" in block
        assert "SPACIOUS density" in block

    def test_enterprise_workspace_metric_row_dense(self):
        # Data-heavy workspace: KPI strip + tight rows
        plan = {
            "app_shape": {
                "layout": {
                    "shell": "sidebar",
                    "hero": "metric-row",
                    "primaryInteraction": "data-grid",
                    "density": "dense",
                },
            }
        }
        block = build_directive(plan)
        assert "Metric-row hero" in block
        assert "COMPACT density" in block
        assert 'layout.density: "compact"' in block

    def test_music_now_playing(self):
        # Now-playing app: player-focused hero
        plan = _shape(hero="now-playing", density="comfortable")
        block = build_directive(plan)
        assert "Now-playing hero" in block

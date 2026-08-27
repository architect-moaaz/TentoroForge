"""Tests for services.shape_profile — the four-axis substrate.

Covers IRF-M0-T9 (types + loaders) + IRF-M1-T2/T3/T4/T5 (validators).
"""
from __future__ import annotations

import pytest

from services import shape_profile as sp


# ══════════════════════════════════════════════════════════════════
# Vocabulary loaders
# ══════════════════════════════════════════════════════════════════


class TestVocabularyLoaders:
    def test_shape_primitive_values_returns_closed_set(self):
        values = sp.shape_primitive_values("layout.shell")
        assert "none" in values
        assert "sidebar" in values
        assert "map-canvas" in values
        assert "not-a-real-value" not in values

    def test_shape_primitive_values_unknown_primitive_raises(self):
        with pytest.raises(KeyError):
            sp.shape_primitive_values("layout.made_up")

    def test_capability_primitive_values(self):
        values = sp.capability_primitive_values("read.pattern")
        assert "board" in values
        assert "map-pins" in values

    def test_runtime_capabilities_contains_expected(self):
        caps = sp.runtime_capabilities()
        assert "geo" in caps
        assert "camera" in caps
        assert "push_notifications" in caps
        assert "biometric_auth" in caps

    def test_known_recipes_covers_common_patterns(self):
        recipes = sp.known_recipes()
        for expected in ("visual_product_search", "catalog", "checkout", "chat", "wizard", "kanban", "cart"):
            assert expected in recipes

    def test_recipe_capabilities_resolves_to_primitives(self):
        caps = sp.recipe_capabilities("kanban")
        assert caps is not None
        assert caps.read.pattern == "board"
        assert caps.write.pattern == "drag"
        assert "drag-between-groups" in caps.interactions

    def test_recipe_capabilities_unknown_returns_none(self):
        assert sp.recipe_capabilities("no_such_recipe") is None


# ══════════════════════════════════════════════════════════════════
# Fixture data — a valid plan.json fragment based on Snap2App
# ══════════════════════════════════════════════════════════════════


def _valid_shape() -> dict:
    return {
        "layout": {"shell": "none", "hero": "full-bleed-gradient", "primaryInteraction": "capture", "density": "spacious"},
        "auth": {"surface": "modal", "gating": "on-action"},
        "nav": {"menu": "none", "back": "history"},
        "workflows": {"executionMode": "fire-and-forget"},
        "data": {"readShape": "list", "denormalization": "aggressive"},
        "identity": {"usageMode": "single-session"},
    }


def _valid_archetypes() -> list[dict]:
    return [
        {
            "name": "scan",
            "recipe": "visual_product_search",
            "entities": ["scan_session"],
            "routes": ["/", "/scan"],
        }
    ]


def _valid_plan() -> dict:
    return {
        "app_shape": _valid_shape(),
        "archetypes": _valid_archetypes(),
        "industry": "consumer-retail",
        "runtime_context": ["camera"],
        "coverage_verdict": {
            "status": "in_scope",
            "reason": "Standard consumer capture utility.",
        },
    }


# ══════════════════════════════════════════════════════════════════
# validate_shape_profile — IRF-M1-T2
# ══════════════════════════════════════════════════════════════════


class TestValidateShapeProfile:
    def test_valid_profile_returns_empty(self):
        assert sp.validate_shape_profile(_valid_shape()) == []

    def test_missing_returns_missing_finding(self):
        findings = sp.validate_shape_profile(None)
        assert any(f.rule == "shape_profile.missing" for f in findings)

    def test_missing_slice_returns_finding(self):
        raw = _valid_shape()
        del raw["auth"]
        findings = sp.validate_shape_profile(raw)
        assert any(f.rule == "shape_profile.auth.missing" for f in findings)

    def test_missing_field_within_slice_returns_finding(self):
        raw = _valid_shape()
        del raw["layout"]["hero"]
        findings = sp.validate_shape_profile(raw)
        assert any(f.rule == "shape_profile.layout.hero.missing" for f in findings)

    def test_invalid_value_returns_finding(self):
        raw = _valid_shape()
        raw["layout"]["shell"] = "chocolate"
        findings = sp.validate_shape_profile(raw)
        assert any(
            f.rule == "shape_profile.layout.shell.invalid_value" and "chocolate" in f.message
            for f in findings
        )

    def test_all_findings_report_axis(self):
        raw = _valid_shape()
        raw["layout"]["shell"] = "chocolate"
        raw["nav"]["menu"] = "hamburger"
        for f in sp.validate_shape_profile(raw):
            assert f.axis == "app_shape"


# ══════════════════════════════════════════════════════════════════
# validate_archetypes — IRF-M1-T3
# ══════════════════════════════════════════════════════════════════


class TestValidateArchetypes:
    def test_valid_recipe_returns_empty(self):
        assert sp.validate_archetypes(_valid_archetypes()) == []

    def test_valid_capabilities_returns_empty(self):
        raw = [
            {
                "name": "custom_module",
                "entities": ["thing"],
                "routes": ["/things"],
                "capabilities": {
                    "read": {"pattern": "list", "grouping": "none"},
                    "write": {"pattern": "create-form", "integrity": "direct"},
                    "interactions": ["filter"],
                    "presentation": {"itemShape": "row"},
                    "state": {"realtime": "none"},
                },
            }
        ]
        assert sp.validate_archetypes(raw) == []

    def test_missing_returns_finding(self):
        assert any(f.rule == "archetypes.missing" for f in sp.validate_archetypes(None))
        assert any(f.rule == "archetypes.missing" for f in sp.validate_archetypes([]))

    def test_missing_name_returns_finding(self):
        raw = [{"recipe": "crud", "entities": [], "routes": []}]
        findings = sp.validate_archetypes(raw)
        assert any("name_missing" in f.rule for f in findings)

    def test_duplicate_names_return_finding(self):
        raw = [
            {"name": "dup", "recipe": "crud", "entities": [], "routes": []},
            {"name": "dup", "recipe": "crud", "entities": [], "routes": []},
        ]
        findings = sp.validate_archetypes(raw)
        assert any("name_duplicate" in f.rule for f in findings)

    def test_neither_recipe_nor_capabilities_returns_finding(self):
        raw = [{"name": "bare", "entities": [], "routes": []}]
        findings = sp.validate_archetypes(raw)
        assert any("recipe_or_capabilities_required" in f.rule for f in findings)

    def test_unknown_recipe_returns_finding(self):
        raw = [{"name": "x", "recipe": "made_up_recipe", "entities": [], "routes": []}]
        findings = sp.validate_archetypes(raw)
        assert any("recipe_unknown" in f.rule for f in findings)

    def test_capabilities_missing_read_pattern_returns_finding(self):
        raw = [
            {
                "name": "x",
                "entities": [], "routes": [],
                "capabilities": {
                    "read": {"grouping": "none"},
                    "write": {"pattern": "none", "integrity": "direct"},
                    "interactions": [],
                    "presentation": {"itemShape": "row"},
                    "state": {"realtime": "none"},
                },
            }
        ]
        findings = sp.validate_archetypes(raw)
        assert any("read.pattern.missing" in f.rule for f in findings)

    def test_capabilities_invalid_read_pattern_returns_finding(self):
        raw = [
            {
                "name": "x",
                "entities": [], "routes": [],
                "capabilities": {
                    "read": {"pattern": "spiral"},
                    "write": {"pattern": "none", "integrity": "direct"},
                    "interactions": [],
                    "presentation": {"itemShape": "row"},
                    "state": {"realtime": "none"},
                },
            }
        ]
        findings = sp.validate_archetypes(raw)
        assert any("read.pattern.invalid_value" in f.rule and "spiral" in f.message for f in findings)

    def test_capabilities_invalid_interaction_returns_finding(self):
        raw = [
            {
                "name": "x",
                "entities": [], "routes": [],
                "capabilities": {
                    "read": {"pattern": "list"},
                    "write": {"pattern": "none", "integrity": "direct"},
                    "interactions": ["telepathy"],
                    "presentation": {"itemShape": "row"},
                    "state": {"realtime": "none"},
                },
            }
        ]
        findings = sp.validate_archetypes(raw)
        assert any("interactions.invalid_value" in f.rule and "telepathy" in f.message for f in findings)


# ══════════════════════════════════════════════════════════════════
# validate_runtime_context — IRF-M1-T4
# ══════════════════════════════════════════════════════════════════


class TestValidateRuntimeContext:
    def test_valid_list_returns_empty(self):
        assert sp.validate_runtime_context(["geo", "camera"]) == []

    def test_empty_list_valid(self):
        assert sp.validate_runtime_context([]) == []

    def test_missing_field_tolerated(self):
        # Absent = same effect as empty. Pipeline is tolerant.
        assert sp.validate_runtime_context(None) == []

    def test_unknown_capability_returns_finding(self):
        findings = sp.validate_runtime_context(["telepathy"])
        assert any(f.rule == "runtime_context.unknown_capability" for f in findings)

    def test_duplicate_returns_warning(self):
        findings = sp.validate_runtime_context(["geo", "geo"])
        dupes = [f for f in findings if f.rule == "runtime_context.duplicate"]
        assert dupes and dupes[0].severity == "warning"

    def test_wrong_type_returns_finding(self):
        findings = sp.validate_runtime_context("geo")  # type: ignore[arg-type]
        assert any(f.rule == "runtime_context.wrong_type" for f in findings)


# ══════════════════════════════════════════════════════════════════
# validate_coverage_verdict — IRF-M1-T5
# ══════════════════════════════════════════════════════════════════


class TestValidateCoverageVerdict:
    def test_valid_in_scope(self):
        assert sp.validate_coverage_verdict({"status": "in_scope", "reason": "fits"}) == []

    def test_valid_out_of_scope(self):
        raw = {
            "status": "out_of_scope",
            "reason": "Multiplayer game engine requested; Forge builds data-driven apps.",
            "nearest_supported": "game-catalog + leaderboard app",
        }
        assert sp.validate_coverage_verdict(raw) == []

    def test_valid_extension_needed(self):
        raw = {
            "status": "extension_needed",
            "reason": "Chrome extension deployment target not in axes.",
            "nearest_supported": "web app with a bookmarklet",
            "missing_dimensions": ["deployment_target=extension"],
        }
        assert sp.validate_coverage_verdict(raw) == []

    def test_missing_returns_finding(self):
        assert any(f.rule == "coverage_verdict.missing" for f in sp.validate_coverage_verdict(None))

    def test_invalid_status_returns_finding(self):
        findings = sp.validate_coverage_verdict({"status": "yes", "reason": "sure"})
        assert any(f.rule == "coverage_verdict.status.invalid" for f in findings)

    def test_out_of_scope_without_nearest_returns_finding(self):
        findings = sp.validate_coverage_verdict({"status": "out_of_scope", "reason": "no"})
        assert any(f.rule == "coverage_verdict.nearest_supported.missing" for f in findings)

    def test_extension_needed_without_missing_dimensions_returns_finding(self):
        findings = sp.validate_coverage_verdict({
            "status": "extension_needed",
            "reason": "close",
            "nearest_supported": "x",
        })
        assert any(f.rule == "coverage_verdict.missing_dimensions.empty" for f in findings)

    def test_missing_reason_returns_finding(self):
        findings = sp.validate_coverage_verdict({"status": "in_scope"})
        assert any(f.rule == "coverage_verdict.reason.missing" for f in findings)


# ══════════════════════════════════════════════════════════════════
# validate_all — convenience aggregator
# ══════════════════════════════════════════════════════════════════


class TestValidateAll:
    def test_valid_plan_zero_findings(self):
        assert sp.validate_all(_valid_plan()) == []

    def test_broken_plan_returns_findings_across_axes(self):
        plan = _valid_plan()
        plan["app_shape"]["layout"]["shell"] = "chocolate"
        plan["runtime_context"] = ["telepathy"]
        plan["coverage_verdict"] = {"status": "in_scope", "reason": ""}
        findings = sp.validate_all(plan)
        axes = {f.axis for f in findings}
        assert "app_shape" in axes
        assert "runtime_context" in axes
        assert "coverage_verdict" in axes


# ══════════════════════════════════════════════════════════════════
# Parsers
# ══════════════════════════════════════════════════════════════════


class TestParsers:
    def test_parse_shape_profile_roundtrip(self):
        raw = _valid_shape()
        parsed = sp.parse_shape_profile(raw)
        assert parsed.layout.shell == "none"
        assert parsed.identity.usageMode == "single-session"

    def test_parse_archetype_with_recipe_only(self):
        raw = {"name": "x", "recipe": "crud", "entities": [], "routes": []}
        parsed = sp.parse_archetype_instance(raw)
        assert parsed.recipe == "crud"
        assert parsed.capabilities is None

    def test_parse_archetype_with_capabilities_only(self):
        raw = {
            "name": "x",
            "entities": [], "routes": [],
            "capabilities": {
                "read": {"pattern": "board", "grouping": "status"},
                "write": {"pattern": "drag", "integrity": "audit-logged"},
                "interactions": ["drag-between-groups"],
                "presentation": {"itemShape": "card"},
                "state": {"realtime": "poll"},
            },
        }
        parsed = sp.parse_archetype_instance(raw)
        assert parsed.recipe is None
        assert parsed.capabilities is not None
        assert parsed.capabilities.read.pattern == "board"
        assert "drag-between-groups" in parsed.capabilities.interactions

    def test_parse_coverage_verdict(self):
        raw = {"status": "in_scope", "reason": "fits", "missing_dimensions": ["x"]}
        parsed = sp.parse_coverage_verdict(raw)
        assert parsed.status == "in_scope"
        assert parsed.missing_dimensions == ("x",)


# ══════════════════════════════════════════════════════════════════
# Fallback detectors — safe defaults
# ══════════════════════════════════════════════════════════════════


class TestFallbackDetectors:
    def test_safe_default_shape_profile_parses(self):
        raw = sp.safe_default_shape_profile()
        # Must be a valid profile itself — the safety net can't produce
        # something that would then fail validation.
        assert sp.validate_shape_profile(raw) == []

    def test_safe_default_capabilities_parses(self):
        raw = sp.safe_default_capabilities()
        parsed = sp._parse_capabilities(raw)
        assert parsed.read.pattern in sp.capability_primitive_values("read.pattern")


# ══════════════════════════════════════════════════════════════════
# Reference apps — every one must be valid against the vocabulary
# ══════════════════════════════════════════════════════════════════


class TestReferenceApps:
    """Every reference_apps.json entry MUST validate cleanly. If this fails
    after a vocabulary edit, the vocabulary and the reference apps have
    drifted."""

    def _apps(self):
        return sp._reference_apps()["reference_apps"]

    def test_at_least_ten_reference_apps(self):
        assert len(self._apps()) >= 10

    def test_every_reference_app_shape_validates(self):
        for entry in self._apps():
            findings = sp.validate_shape_profile(entry["app_shape"])
            assert findings == [], f"{entry['name']}: {[f.message for f in findings]}"

    def test_every_reference_app_archetypes_validate(self):
        for entry in self._apps():
            findings = sp.validate_archetypes(entry["archetypes"])
            assert findings == [], f"{entry['name']}: {[f.message for f in findings]}"

    def test_every_reference_app_runtime_context_validates(self):
        for entry in self._apps():
            findings = sp.validate_runtime_context(entry.get("runtime_context", []))
            assert findings == [], f"{entry['name']}: {[f.message for f in findings]}"


# ══════════════════════════════════════════════════════════════════
# Prompt renderers — smoke tests for the strings the planner injects
# ══════════════════════════════════════════════════════════════════


class TestPromptRenderers:
    def test_shape_vocabulary_prompt_lists_all_primitives(self):
        block = sp.render_planner_prompt_vocabulary()
        for primitive in ("layout.shell", "auth.surface", "identity.usageMode"):
            assert primitive in block

    def test_capabilities_prompt_lists_known_recipes(self):
        block = sp.render_planner_prompt_capabilities()
        assert "KNOWN RECIPES" in block
        assert "checkout" in block

    def test_runtime_capabilities_prompt_includes_glosses(self):
        block = sp.render_planner_prompt_runtime_capabilities()
        assert "geo" in block
        assert "push_notifications" in block

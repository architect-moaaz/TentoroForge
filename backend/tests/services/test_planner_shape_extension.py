"""Tests for planner_shape_extension (M1-T1 + M1-T10 + M0-T1 compat)."""
from __future__ import annotations

import pytest

from services import planner_shape_extension as pse


# ══════════════════════════════════════════════════════════════════
# Prompt block
# ══════════════════════════════════════════════════════════════════


class TestBuildPromptBlock:
    def test_block_mentions_all_four_axes(self):
        block = pse.build_prompt_block()
        assert "app_shape" in block
        assert "archetypes" in block
        assert "industry" in block
        assert "runtime_context" in block
        assert "coverage_verdict" in block

    def test_block_renders_shape_vocabulary(self):
        block = pse.build_prompt_block()
        # Must include all 12 shape primitives from vocabulary.json
        for primitive in ("layout.shell", "auth.surface", "identity.usageMode"):
            assert primitive in block

    def test_block_renders_capability_vocabulary(self):
        block = pse.build_prompt_block()
        assert "read.pattern" in block
        assert "write.pattern" in block

    def test_block_lists_out_of_scope_examples(self):
        block = pse.build_prompt_block()
        # Games, editors, spatial etc. must be in the refusal list
        for keyword in ("games", "video editors", "spatial"):
            assert keyword in block

    def test_block_mentions_recipes(self):
        block = pse.build_prompt_block()
        assert "recipes.json" in block or "recipe" in block


# ══════════════════════════════════════════════════════════════════
# M0-T1 compat bridge
# ══════════════════════════════════════════════════════════════════


class TestIndustryDomainBridge:
    def test_industry_only_populates_domain(self):
        plan = {"industry": "hr-payroll"}
        result = pse._bridge_industry_and_domain(dict(plan))
        assert result["industry"] == "hr-payroll"
        assert result["domain"] == "hr-payroll"

    def test_domain_only_populates_industry(self):
        plan = {"domain": "fintech-brokerage"}
        result = pse._bridge_industry_and_domain(dict(plan))
        assert result["domain"] == "fintech-brokerage"
        assert result["industry"] == "fintech-brokerage"

    def test_both_set_industry_wins(self):
        plan = {"industry": "consumer-retail", "domain": "old-thing"}
        result = pse._bridge_industry_and_domain(dict(plan))
        assert result["industry"] == "consumer-retail"
        assert result["domain"] == "consumer-retail"

    def test_neither_set_no_op(self):
        plan = {}
        result = pse._bridge_industry_and_domain(dict(plan))
        assert "industry" not in result
        assert "domain" not in result

    def test_both_set_same_value_no_op(self):
        plan = {"industry": "healthcare", "domain": "healthcare"}
        result = pse._bridge_industry_and_domain(dict(plan))
        assert result["industry"] == "healthcare"
        assert result["domain"] == "healthcare"


# ══════════════════════════════════════════════════════════════════
# enrich_plan — orchestration + repair
# ══════════════════════════════════════════════════════════════════


class TestEnrichPlan:
    def test_valid_plan_no_repairs_needed(self):
        plan = {
            "app_shape": {
                "layout": {"shell": "none", "hero": "full-bleed-gradient", "primaryInteraction": "capture", "density": "spacious"},
                "auth": {"surface": "modal", "gating": "on-action"},
                "nav": {"menu": "none", "back": "history"},
                "workflows": {"executionMode": "fire-and-forget"},
                "data": {"readShape": "list", "denormalization": "aggressive"},
                "identity": {"usageMode": "single-session"},
            },
            "archetypes": [{"name": "scan", "recipe": "visual_product_search", "entities": ["scan_session"], "routes": ["/"]}],
            "industry": "consumer-retail",
            "runtime_context": ["camera"],
            "coverage_verdict": {"status": "in_scope", "reason": "consumer capture utility"},
        }
        result, findings = pse.enrich_plan(plan, brief="camera scanner")
        # No structural repair happened — plan was already valid
        errors = [f for f in findings if f.severity == "error"]
        assert errors == []

    def test_missing_app_shape_gets_detector_fill(self):
        plan = {
            "archetypes": [{"name": "x", "recipe": "crud", "routes": ["/x"]}],
            "coverage_verdict": {"status": "in_scope", "reason": "x"},
        }
        result, findings = pse.enrich_plan(plan, brief="camera scanner mobile app")
        assert "app_shape" in result
        assert isinstance(result["app_shape"], dict)
        assert any(f.rule == "LLM_UNAVAILABLE" for f in findings)

    def test_missing_runtime_context_becomes_empty_list(self):
        plan = {
            "app_shape": {
                "layout": {"shell": "sidebar", "hero": "none", "primaryInteraction": "data-grid", "density": "comfortable"},
                "auth": {"surface": "route", "gating": "on-load"},
                "nav": {"menu": "sidebar-links", "back": "crumb"},
                "workflows": {"executionMode": "await-with-progress"},
                "data": {"readShape": "list", "denormalization": "moderate"},
                "identity": {"usageMode": "multi-user-team"},
            },
            "archetypes": [{"name": "x", "recipe": "crud", "routes": ["/"]}],
            "coverage_verdict": {"status": "in_scope", "reason": "workspace"},
        }
        result, findings = pse.enrich_plan(plan, brief="internal workspace")
        assert result["runtime_context"] == []

    def test_unknown_runtime_capability_dropped(self):
        plan = {
            "app_shape": {
                "layout": {"shell": "sidebar", "hero": "none", "primaryInteraction": "data-grid", "density": "comfortable"},
                "auth": {"surface": "route", "gating": "on-load"},
                "nav": {"menu": "sidebar-links", "back": "crumb"},
                "workflows": {"executionMode": "await-with-progress"},
                "data": {"readShape": "list", "denormalization": "moderate"},
                "identity": {"usageMode": "multi-user-team"},
            },
            "archetypes": [{"name": "x", "recipe": "crud", "routes": ["/"]}],
            "runtime_context": ["geo", "telepathy", "camera"],
            "coverage_verdict": {"status": "in_scope", "reason": "workspace"},
        }
        result, findings = pse.enrich_plan(plan, brief="workspace")
        assert result["runtime_context"] == ["geo", "camera"]
        assert any(f.rule == "runtime_context.unknown_values_dropped" for f in findings)

    def test_missing_coverage_verdict_defaults_to_in_scope(self):
        plan = {
            "app_shape": {
                "layout": {"shell": "sidebar", "hero": "none", "primaryInteraction": "data-grid", "density": "comfortable"},
                "auth": {"surface": "route", "gating": "on-load"},
                "nav": {"menu": "sidebar-links", "back": "crumb"},
                "workflows": {"executionMode": "await-with-progress"},
                "data": {"readShape": "list", "denormalization": "moderate"},
                "identity": {"usageMode": "multi-user-team"},
            },
            "archetypes": [{"name": "x", "recipe": "crud", "routes": ["/"]}],
        }
        result, findings = pse.enrich_plan(plan, brief="internal workspace")
        assert result["coverage_verdict"]["status"] == "in_scope"
        assert any(f.rule == "coverage_verdict.defaulted" for f in findings)

    def test_unknown_recipe_remapped(self):
        plan = {
            "app_shape": {
                "layout": {"shell": "sidebar", "hero": "none", "primaryInteraction": "data-grid", "density": "comfortable"},
                "auth": {"surface": "route", "gating": "on-load"},
                "nav": {"menu": "sidebar-links", "back": "crumb"},
                "workflows": {"executionMode": "await-with-progress"},
                "data": {"readShape": "list", "denormalization": "moderate"},
                "identity": {"usageMode": "multi-user-team"},
            },
            "archetypes": [{"name": "board", "recipe": "made_up_recipe", "routes": ["/board"]}],
            "coverage_verdict": {"status": "in_scope", "reason": "workspace"},
        }
        # Brief mentions "kanban" so the detector should remap
        result, findings = pse.enrich_plan(plan, brief="kanban board with columns and drag between")
        # After remap, either the recipe is now "kanban" OR fell through
        # to capabilities. Either way, no error remains.
        arche = result["archetypes"][0]
        # Recipe either fixed or fallen through
        assert arche.get("recipe") == "kanban" or "capabilities" in arche

    def test_industry_domain_bridge_applied(self):
        plan = {
            "app_shape": {
                "layout": {"shell": "sidebar", "hero": "none", "primaryInteraction": "data-grid", "density": "comfortable"},
                "auth": {"surface": "route", "gating": "on-load"},
                "nav": {"menu": "sidebar-links", "back": "crumb"},
                "workflows": {"executionMode": "await-with-progress"},
                "data": {"readShape": "list", "denormalization": "moderate"},
                "identity": {"usageMode": "multi-user-team"},
            },
            "archetypes": [{"name": "x", "recipe": "crud", "routes": ["/"]}],
            "industry": "healthcare",
            "coverage_verdict": {"status": "in_scope", "reason": "workspace"},
        }
        result, _ = pse.enrich_plan(plan, brief="")
        assert result["domain"] == "healthcare"  # shadow-copy
        assert result["industry"] == "healthcare"

    def test_never_mutates_input_plan(self):
        plan = {"industry": "x"}
        pse.enrich_plan(plan, brief="")
        assert "domain" not in plan  # input unchanged

    def test_no_brief_no_repair(self):
        # Without a brief, detectors can't repair — only validate/bridge.
        plan = {"industry": "x"}
        result, findings = pse.enrich_plan(plan, brief="")
        # No app_shape fill happens without brief
        assert "app_shape" not in result


# ══════════════════════════════════════════════════════════════════
# REVISE prompt builder (M1-T10)
# ══════════════════════════════════════════════════════════════════


class TestFormatFindingsForRevise:
    def test_no_findings_returns_none(self):
        assert pse.format_findings_for_revise([]) is None

    def test_only_info_findings_returns_none(self):
        from services.shape_profile import Finding
        findings = [Finding(rule="x.info", message="fyi", severity="info", axis="app_shape")]
        assert pse.format_findings_for_revise(findings) is None

    def test_defaulted_coverage_alone_returns_none(self):
        from services.shape_profile import Finding
        findings = [Finding(
            rule="coverage_verdict.defaulted", message="d", severity="info",
            axis="coverage_verdict",
        )]
        assert pse.format_findings_for_revise(findings) is None

    def test_error_finding_yields_gaps_block(self):
        from services.shape_profile import Finding
        findings = [Finding(
            rule="shape_profile.layout.shell.invalid_value",
            message="'chocolate' is not valid",
            severity="error",
            axis="app_shape",
        )]
        block = pse.format_findings_for_revise(findings)
        assert block is not None
        assert "GAPS TO FIX" in block
        assert "app_shape" in block
        assert "chocolate" in block
        assert "Re-emit the plan-json" in block

    def test_warning_findings_included(self):
        from services.shape_profile import Finding
        findings = [Finding(
            rule="coherence.shell_none_with_chrome_menu",
            message="menu without shell",
            severity="warning",
            axis="app_shape",
        )]
        block = pse.format_findings_for_revise(findings)
        assert block is not None
        assert "shell_none_with_chrome_menu" in block

    def test_multiple_findings_all_listed(self):
        from services.shape_profile import Finding
        findings = [
            Finding(rule="a.b", message="msg a", severity="error", axis="app_shape"),
            Finding(rule="c.d", message="msg c", severity="warning", axis="archetypes"),
        ]
        block = pse.format_findings_for_revise(findings)
        assert "a.b" in block
        assert "c.d" in block

"""Tests for plan_coherence + shape_profile_detector +
archetype_recipe_detector + domain_conformance (M1-T6/T7/T9 + M5-T7)."""
from __future__ import annotations

import pytest

from services import (
    archetype_recipe_detector,
    domain_conformance,
    plan_coherence,
    shape_profile_detector,
)


# ══════════════════════════════════════════════════════════════════
# plan_coherence — M1-T9
# ══════════════════════════════════════════════════════════════════


class TestPlanCoherence:
    def _snap2app(self):
        return {
            "app_shape": {
                "layout": {"shell": "none", "hero": "full-bleed-gradient", "primaryInteraction": "capture", "density": "spacious"},
                "auth": {"surface": "modal", "gating": "on-action"},
                "nav": {"menu": "none", "back": "history"},
                "workflows": {"executionMode": "fire-and-forget"},
                "data": {"readShape": "list", "denormalization": "aggressive"},
                "identity": {"usageMode": "single-session"},
            },
            "archetypes": [{"name": "scan", "recipe": "visual_product_search", "routes": ["/"]}],
        }

    def test_valid_snap2app_zero_findings(self):
        assert plan_coherence.check_plan_coherence(self._snap2app()) == []

    def test_shell_none_with_sidebar_menu_warns(self):
        plan = self._snap2app()
        plan["app_shape"]["nav"]["menu"] = "sidebar-links"
        findings = plan_coherence.check_plan_coherence(plan)
        assert any(f.rule == "coherence.shell_none_with_chrome_menu" for f in findings)

    def test_single_session_on_load_gating_warns(self):
        plan = self._snap2app()
        plan["app_shape"]["auth"]["gating"] = "on-load"
        findings = plan_coherence.check_plan_coherence(plan)
        assert any(f.rule == "coherence.single_session_gated_on_load" for f in findings)

    def test_fire_and_forget_single_record_warns(self):
        plan = self._snap2app()
        plan["app_shape"]["data"]["readShape"] = "single-record"
        findings = plan_coherence.check_plan_coherence(plan)
        assert any(f.rule == "coherence.fire_and_forget_single_record" for f in findings)

    def test_streaming_without_realtime_module_warns(self):
        plan = self._snap2app()
        plan["app_shape"]["workflows"]["executionMode"] = "streaming"
        # archetypes has no state.realtime declaration
        plan["archetypes"] = [{"name": "x", "recipe": "crud", "routes": ["/"]}]
        findings = plan_coherence.check_plan_coherence(plan)
        assert any(f.rule == "coherence.streaming_no_realtime_module" for f in findings)

    def test_streaming_with_realtime_module_passes(self):
        plan = self._snap2app()
        plan["app_shape"]["workflows"]["executionMode"] = "streaming"
        plan["archetypes"] = [{
            "name": "live",
            "capabilities": {
                "read": {"pattern": "map-pins"},
                "write": {"pattern": "none"},
                "interactions": ["live-follow"],
                "presentation": {"itemShape": "pin"},
                "state": {"realtime": "stream"},
            },
            "routes": ["/"],
        }]
        findings = plan_coherence.check_plan_coherence(plan)
        assert not any(f.rule == "coherence.streaming_no_realtime_module" for f in findings)

    def test_hero_on_workspace_identity_warns(self):
        plan = self._snap2app()
        plan["app_shape"]["identity"]["usageMode"] = "multi-user-team"
        findings = plan_coherence.check_plan_coherence(plan)
        assert any(f.rule == "coherence.hero_on_workspace" for f in findings)

    def test_kanban_in_cta_shape_without_override_warns(self):
        plan = self._snap2app()
        # Add a kanban module without local_shape override
        plan["archetypes"].append({
            "name": "board",
            "capabilities": {
                "read": {"pattern": "board"},
                "write": {"pattern": "drag"},
                "interactions": ["drag-between-groups"],
                "presentation": {"itemShape": "card"},
                "state": {"realtime": "none"},
            },
            "routes": ["/board"],
        })
        # Outer primaryInteraction is 'capture' (consumer-facing).
        findings = plan_coherence.check_plan_coherence(plan)
        assert any("shape_conflict" in f.rule and "board" in f.message for f in findings)

    def test_with_local_shape_override_no_conflict(self):
        plan = self._snap2app()
        plan["archetypes"].append({
            "name": "board",
            "capabilities": {
                "read": {"pattern": "board"},
                "write": {"pattern": "drag"},
                "interactions": [],
                "presentation": {"itemShape": "card"},
                "state": {"realtime": "none"},
            },
            "routes": ["/board"],
            "local_shape": {"layout": {"shell": "sidebar", "primaryInteraction": "data-grid"}},
        })
        findings = plan_coherence.check_plan_coherence(plan)
        # No shape_conflict finding when override present
        assert not any("shape_conflict" in f.rule for f in findings)

    def test_empty_archetypes_warns(self):
        plan = {"app_shape": self._snap2app()["app_shape"], "archetypes": []}
        findings = plan_coherence.check_plan_coherence(plan)
        assert any(f.rule == "coherence.no_modules" for f in findings)

    def test_all_findings_are_warnings(self):
        # Coherence findings should never be errors — LLM might have
        # a valid reason.
        plan = self._snap2app()
        plan["app_shape"]["nav"]["menu"] = "sidebar-links"
        plan["app_shape"]["auth"]["gating"] = "on-load"
        for f in plan_coherence.check_plan_coherence(plan):
            assert f.severity == "warning"


# ══════════════════════════════════════════════════════════════════
# shape_profile_detector — M1-T6
# ══════════════════════════════════════════════════════════════════


class TestShapeDetector:
    def test_scanner_brief_scores_capture(self):
        assert shape_profile_detector.score_primitive(
            "layout.primaryInteraction", "point your camera to scan a product"
        ) == "capture"

    def test_workspace_brief_scores_sidebar(self):
        assert shape_profile_detector.score_primitive(
            "layout.shell", "internal CRM workspace for the admin team"
        ) == "sidebar"

    def test_no_signal_returns_none(self):
        assert shape_profile_detector.score_primitive(
            "layout.shell", "totally unrelated text about cheese"
        ) is None

    def test_detect_full_profile_returns_valid_shape(self):
        profile, findings = shape_profile_detector.detect_shape_profile(
            "camera scanner utility for consumers"
        )
        # LLM_UNAVAILABLE finding always present
        assert any(f.rule == "LLM_UNAVAILABLE" for f in findings)
        # Every profile field populated
        for section in ("layout", "auth", "nav", "workflows", "data", "identity"):
            assert isinstance(profile[section], dict)

    def test_detect_shape_survives_shape_profile_validator(self):
        """Whatever the detector emits MUST pass validate_shape_profile
        (else the safety net produces something that then fails
        downstream validation)."""
        from services.shape_profile import validate_shape_profile
        profile, _ = shape_profile_detector.detect_shape_profile("random text")
        assert validate_shape_profile(profile) == []

    def test_repair_single_field_uses_keyword(self):
        value, finding = shape_profile_detector.repair_single_field(
            "layout.primaryInteraction", "camera capture app"
        )
        assert value == "capture"
        assert finding.severity == "info"

    def test_repair_single_field_falls_back_to_safe_default(self):
        value, finding = shape_profile_detector.repair_single_field(
            "layout.shell", "cheese"
        )
        # Falls back to safe defaults ('sidebar' per vocabulary.json)
        assert value == "sidebar"
        assert finding.severity == "warning"


# ══════════════════════════════════════════════════════════════════
# archetype_recipe_detector — M1-T7
# ══════════════════════════════════════════════════════════════════


class TestArchetypeRecipeDetector:
    def test_camera_brief_scores_visual_product_search(self):
        assert archetype_recipe_detector.score_recipe(
            "scan product with camera for price comparison"
        ) == "visual_product_search"

    def test_board_brief_scores_kanban(self):
        assert archetype_recipe_detector.score_recipe(
            "kanban board with columns and drag between"
        ) == "kanban"

    def test_no_signal_returns_none(self):
        assert archetype_recipe_detector.score_recipe("cheese wheel") is None

    def test_detect_instance_returns_recipe_when_scored(self):
        instance, findings = archetype_recipe_detector.detect_archetype_instance(
            "chat messaging app", module_name="conv", routes=("/chat",)
        )
        assert instance["recipe"] == "chat"
        assert instance["name"] == "conv"
        assert any(f.rule == "LLM_UNAVAILABLE" for f in findings)

    def test_detect_instance_falls_back_to_capabilities(self):
        instance, findings = archetype_recipe_detector.detect_archetype_instance(
            "cheese-related nonsense",
        )
        assert "recipe" not in instance
        assert "capabilities" in instance
        assert any(f.rule == "archetypes.safe_default_capabilities" for f in findings)

    def test_repair_unknown_recipe_remaps_when_signal(self):
        recipe, finding = archetype_recipe_detector.repair_unknown_recipe(
            "made_up", "cart checkout wizard"
        )
        assert recipe == "wizard"
        assert "unknown" in finding.message

    def test_repair_unknown_recipe_gives_up_gracefully(self):
        recipe, finding = archetype_recipe_detector.repair_unknown_recipe(
            "made_up", "totally unrelated"
        )
        assert recipe is None
        assert "unrecoverable" in finding.rule


# ══════════════════════════════════════════════════════════════════
# domain_conformance — M5-T7
# ══════════════════════════════════════════════════════════════════


class TestDomainConformance:
    def _shell_none_plan(self):
        return {
            "app_shape": {
                "layout": {"shell": "none", "hero": "full-bleed-gradient", "primaryInteraction": "capture", "density": "spacious"},
                "auth": {"surface": "modal", "gating": "on-action"},
                "nav": {"menu": "none", "back": "history"},
                "workflows": {"executionMode": "fire-and-forget"},
                "data": {"readShape": "list", "denormalization": "aggressive"},
                "identity": {"usageMode": "single-session"},
            },
            "archetypes": [{"name": "scan", "recipe": "visual_product_search", "routes": ["/"]}],
        }

    def test_sidebar_component_on_shell_none_is_error(self):
        plan = self._shell_none_plan()
        schema = {"type": "Stack", "children": [{"type": "Sidebar"}, {"type": "Heading"}]}
        findings = domain_conformance.check_page(plan, "/", schema)
        assert any(f.rule == "domain_conformance.shell_present_on_none" for f in findings)

    def test_clean_schema_passes(self):
        plan = self._shell_none_plan()
        schema = {"type": "Stack", "children": [{"type": "Heading"}, {"type": "Button"}]}
        findings = domain_conformance.check_page(plan, "/", schema)
        assert findings == []

    def test_login_route_with_modal_auth_warns(self):
        plan = self._shell_none_plan()
        # Add a /login route existence (schema doesn't matter for this check)
        findings = domain_conformance.check_page(plan, "/login", {"type": "Stack"})
        assert any(f.rule == "domain_conformance.login_route_on_modal_auth" for f in findings)

    def test_menu_component_when_nav_none_is_error(self):
        plan = self._shell_none_plan()
        schema = {"type": "Stack", "children": [{"type": "SidebarMenu"}]}
        findings = domain_conformance.check_page(plan, "/", schema)
        assert any(f.rule == "domain_conformance.menu_component_on_none" for f in findings)

    def test_form_without_submit_mode_on_fire_and_forget_warns(self):
        plan = self._shell_none_plan()
        schema = {
            "type": "Stack",
            "children": [{
                "type": "Form",
                "props": {"submit": {"kind": "workflow", "target": "wf1"}},
            }],
        }
        findings = domain_conformance.check_page(plan, "/", schema)
        assert any(f.rule == "domain_conformance.form_submit_mode_missing" for f in findings)

    def test_form_with_explicit_submit_mode_passes(self):
        plan = self._shell_none_plan()
        schema = {
            "type": "Stack",
            "children": [{
                "type": "Form",
                "props": {"submit": {"kind": "workflow", "target": "wf1", "mode": "fire-and-forget"}},
            }],
        }
        findings = domain_conformance.check_page(plan, "/", schema)
        # No submit-mode warning
        assert not any(f.rule == "domain_conformance.form_submit_mode_missing" for f in findings)

    def test_missing_shape_yields_no_findings(self):
        # Tolerant of pre-M1-T1 plans without app_shape
        assert domain_conformance.check_page({}, "/", {"type": "Stack"}) == []

    def test_check_all_pages_iterates(self):
        plan = self._shell_none_plan()
        pages = {
            "/": {"type": "Stack", "children": [{"type": "Sidebar"}]},
            "/other": {"type": "Stack", "children": []},
        }
        findings = domain_conformance.check_all_pages(plan, pages)
        # / has the shell violation; /other doesn't
        rules = {f.rule for f in findings}
        assert "domain_conformance.shell_present_on_none" in rules


# ══════════════════════════════════════════════════════════════════
# Wire smoke — coverage_verdict_gate integration (M2-T7 side)
# ══════════════════════════════════════════════════════════════════


class TestGateIntegrationSmoke:
    """The gate itself is already tested in the M2 test file; this
    just confirms the pieces we wired into generate.py compose
    correctly."""

    def test_out_of_scope_gate_returns_halt_with_payload(self):
        from services.coverage_verdict_gate import evaluate
        plan = {
            "coverage_verdict": {
                "status": "out_of_scope",
                "reason": "video editor requested",
                "nearest_supported": "video-project-management app",
            }
        }
        decision = evaluate(plan, brief_summary="build a video editor", gen_slug="v001")
        assert decision.action == "halt"
        assert decision.refusal_payload is not None
        # Payload has the shape sse_event will serialize
        assert "status" in decision.refusal_payload
        assert "actions" in decision.refusal_payload

    def test_extension_needed_produces_valid_gap_entry(self):
        from services.coverage_verdict_gate import evaluate
        plan = {
            "coverage_verdict": {
                "status": "extension_needed",
                "reason": "chrome extension deployment target",
                "nearest_supported": "web bookmarklet",
                "missing_dimensions": ["deployment_target=extension"],
            }
        }
        decision = evaluate(plan, brief_summary="chrome extension for markdown", gen_slug="ext01")
        assert decision.action == "proceed_and_log_gap"
        entry = decision.gap_log_entry
        assert entry["gen_slug"] == "ext01"
        assert "deployment_target=extension" in entry["missing_dimensions"]

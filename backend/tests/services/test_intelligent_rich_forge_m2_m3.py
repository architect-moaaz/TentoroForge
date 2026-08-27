"""Tests for M2 (coverage-verdict gate + gap log) and M3-T1/T8
(derived shape helpers + runtime-context wire pass).

All modules under test are pure functions / data classes — the
plumbing surgery (SSE, frontend, pipeline surgery) lands in a
follow-up PR. See docs/superpowers/plans/2026-08-11-intelligent-rich-forge.md.
"""
from __future__ import annotations

import json

import pytest

from services import (
    coverage_verdict_gate,
    runtime_context_wire,
    shape_profile_derived as spd,
    substrate_gap_log,
)


# ══════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════


def _snap2app_shape():
    return {
        "layout": {"shell": "none", "hero": "full-bleed-gradient", "primaryInteraction": "capture", "density": "spacious"},
        "auth": {"surface": "modal", "gating": "on-action"},
        "nav": {"menu": "none", "back": "history"},
        "workflows": {"executionMode": "fire-and-forget"},
        "data": {"readShape": "list", "denormalization": "aggressive"},
        "identity": {"usageMode": "single-session"},
    }


def _uber_shape():
    return {
        "layout": {"shell": "map-canvas", "hero": "map-canvas", "primaryInteraction": "map", "density": "spacious"},
        "auth": {"surface": "route", "gating": "on-load"},
        "nav": {"menu": "drawer", "back": "history"},
        "workflows": {"executionMode": "streaming"},
        "data": {"readShape": "map-pins", "denormalization": "aggressive"},
        "identity": {"usageMode": "returning-personal"},
    }


def _uber_plan():
    return {
        "app_shape": _uber_shape(),
        "archetypes": [
            {"name": "active_ride", "recipe": "map_pins", "routes": ["/", "/active"]},
            {
                "name": "payment_methods",
                "recipe": "crud",
                "routes": ["/pay", "/pay/[id]"],
                "local_shape": {"layout": {"shell": "header", "primaryInteraction": "form"}, "nav": {"menu": "none"}},
            },
            {
                "name": "chat",
                "recipe": "chat",
                "routes": ["/chat"],
                "local_shape": {"layout": {"shell": "three-pane"}},
            },
        ],
    }


# ══════════════════════════════════════════════════════════════════
# shape_profile_derived — resolve_shape + derived properties (M3-T1)
# ══════════════════════════════════════════════════════════════════


class TestResolveShape:
    def test_no_route_returns_outer_shape(self):
        plan = {"app_shape": _snap2app_shape(), "archetypes": []}
        assert spd.resolve_shape(plan, "") == _snap2app_shape()

    def test_route_not_owned_returns_outer_shape(self):
        plan = _uber_plan()
        result = spd.resolve_shape(plan, "/unknown")
        assert result == _uber_shape()

    def test_module_without_local_shape_returns_outer(self):
        plan = _uber_plan()
        result = spd.resolve_shape(plan, "/active")
        assert result == _uber_shape()

    def test_local_shape_overrides_specific_fields(self):
        plan = _uber_plan()
        result = spd.resolve_shape(plan, "/pay")
        # local_shape flips shell to header + primaryInteraction to form
        assert result["layout"]["shell"] == "header"
        assert result["layout"]["primaryInteraction"] == "form"
        # unset outer fields survive
        assert result["layout"]["density"] == "spacious"
        assert result["workflows"]["executionMode"] == "streaming"
        # nav.menu overridden to none
        assert result["nav"]["menu"] == "none"

    def test_dynamic_route_segment_matches(self):
        plan = _uber_plan()
        result = spd.resolve_shape(plan, "/pay/abc-123")
        # /pay/[id] matches /pay/abc-123
        assert result["layout"]["shell"] == "header"

    def test_returns_fresh_dict_not_reference(self):
        plan = _uber_plan()
        result = spd.resolve_shape(plan, "/pay")
        result["layout"]["shell"] = "MUTATED"
        # Original plan.app_shape untouched
        assert plan["app_shape"]["layout"]["shell"] == "map-canvas"

    def test_missing_app_shape_returns_empty(self):
        assert spd.resolve_shape({}, "/anywhere") == {}


class TestNeedsRootToaster:
    def test_true_when_shell_none(self):
        shape = {"layout": {"shell": "none"}, "auth": {}, "workflows": {}}
        assert spd.needs_root_toaster(shape) is True

    def test_true_when_auth_modal(self):
        shape = {"layout": {"shell": "sidebar"}, "auth": {"surface": "modal"}, "workflows": {}}
        assert spd.needs_root_toaster(shape) is True

    def test_true_when_workflows_fire_and_forget(self):
        shape = {"layout": {"shell": "sidebar"}, "auth": {"surface": "route"}, "workflows": {"executionMode": "fire-and-forget"}}
        assert spd.needs_root_toaster(shape) is True

    def test_false_when_boring_workspace(self):
        shape = {"layout": {"shell": "sidebar"}, "auth": {"surface": "route"}, "workflows": {"executionMode": "await-with-progress"}}
        assert spd.needs_root_toaster(shape) is False

    def test_true_for_snap2app_shape(self):
        assert spd.needs_root_toaster(_snap2app_shape()) is True


class TestShouldGenerateLoginRoute:
    def test_true_when_auth_surface_route(self):
        assert spd.should_generate_login_route({"auth": {"surface": "route"}}) is True

    def test_false_when_modal(self):
        assert spd.should_generate_login_route({"auth": {"surface": "modal"}}) is False

    def test_false_when_none(self):
        assert spd.should_generate_login_route({"auth": {"surface": "none"}}) is False

    def test_false_when_missing(self):
        assert spd.should_generate_login_route({}) is False


class TestFormSubmitPattern:
    def test_fire_and_forget_pattern(self):
        shape = {"workflows": {"executionMode": "fire-and-forget"}}
        assert spd.form_submit_pattern(shape) == "fire-and-forget-with-toast-nav"

    def test_streaming_pattern(self):
        shape = {"workflows": {"executionMode": "streaming"}}
        assert spd.form_submit_pattern(shape) == "in-place-progress"

    def test_background_pattern(self):
        shape = {"workflows": {"executionMode": "background-with-notification"}}
        assert spd.form_submit_pattern(shape) == "background-with-notification"

    def test_default_await_with_spinner(self):
        assert spd.form_submit_pattern({}) == "await-with-spinner"
        assert spd.form_submit_pattern({"workflows": {"executionMode": "await-with-progress"}}) == "await-with-spinner"


class TestOtherDerivedHelpers:
    def test_denorm_columns_needed_true_for_aggressive(self):
        assert spd.denorm_columns_needed({"data": {"denormalization": "aggressive"}}) is True

    def test_denorm_columns_needed_false_for_none(self):
        assert spd.denorm_columns_needed({"data": {"denormalization": "none"}}) is False

    def test_synth_shell_menu_false_when_menu_none(self):
        assert spd.synth_shell_menu({"nav": {"menu": "none"}}) is False

    def test_synth_shell_menu_true_when_menu_sidebar_links(self):
        assert spd.synth_shell_menu({"nav": {"menu": "sidebar-links"}}) is True

    def test_shell_kind_tolerant_default(self):
        assert spd.shell_kind({}) == "sidebar"
        assert spd.shell_kind({"layout": {"shell": "unknown-value"}}) == "sidebar"

    def test_shell_kind_returns_declared(self):
        assert spd.shell_kind({"layout": {"shell": "map-canvas"}}) == "map-canvas"


class TestModuleHelpers:
    def test_is_realtime_module_true(self):
        inst = {"capabilities": {"state": {"realtime": "stream"}}}
        assert spd.is_realtime_module(inst) is True

    def test_is_realtime_module_false(self):
        inst = {"capabilities": {"state": {"realtime": "none"}}}
        assert spd.is_realtime_module(inst) is False
        assert spd.is_realtime_module({}) is False

    def test_module_interactions_returns_tuple(self):
        inst = {"capabilities": {"interactions": ["filter", "sort"]}}
        assert spd.module_interactions(inst) == ("filter", "sort")

    def test_module_interactions_empty_when_missing(self):
        assert spd.module_interactions({}) == ()


# ══════════════════════════════════════════════════════════════════
# coverage_verdict_gate — pure decision function (M2-T1)
# ══════════════════════════════════════════════════════════════════


class TestCoverageVerdictGate:
    def test_in_scope_proceeds(self):
        plan = {"coverage_verdict": {"status": "in_scope", "reason": "fits"}}
        decision = coverage_verdict_gate.evaluate(plan)
        assert decision.action == "proceed"
        assert decision.gap_log_entry is None
        assert decision.refusal_payload is None

    def test_missing_verdict_tolerated_as_in_scope(self):
        # M2 lands before M1-T1 planner emission — must be tolerant.
        decision = coverage_verdict_gate.evaluate({})
        assert decision.action == "proceed"

    def test_malformed_verdict_tolerated(self):
        decision = coverage_verdict_gate.evaluate({"coverage_verdict": "not a dict"})
        assert decision.action == "proceed"

    def test_unknown_status_tolerated(self):
        decision = coverage_verdict_gate.evaluate({"coverage_verdict": {"status": "made-up", "reason": "x"}})
        assert decision.action == "proceed"

    def test_extension_needed_proceeds_and_returns_gap_entry(self):
        plan = {
            "coverage_verdict": {
                "status": "extension_needed",
                "reason": "Chrome extension deployment target not in axes.",
                "nearest_supported": "web app with a bookmarklet",
                "missing_dimensions": ["deployment_target=extension"],
                "suggested_extensions": ["add deployment_target axis"],
            }
        }
        decision = coverage_verdict_gate.evaluate(
            plan, brief_summary="a chrome extension", gen_slug="ext001"
        )
        assert decision.action == "proceed_and_log_gap"
        assert decision.gap_log_entry is not None
        entry = decision.gap_log_entry
        assert entry["gen_slug"] == "ext001"
        assert entry["brief_summary"] == "a chrome extension"
        assert entry["missing_dimensions"] == ["deployment_target=extension"]
        assert entry["nearest_supported"] == "web app with a bookmarklet"

    def test_out_of_scope_halts_with_refusal_payload(self):
        plan = {
            "coverage_verdict": {
                "status": "out_of_scope",
                "reason": "Multiplayer game engine requested; Forge builds data-driven apps.",
                "nearest_supported": "game-catalog + leaderboard app",
            }
        }
        decision = coverage_verdict_gate.evaluate(plan)
        assert decision.action == "halt"
        assert decision.refusal_payload is not None
        payload = decision.refusal_payload
        assert payload["status"] == "out_of_scope"
        assert payload["nearest_supported"] == "game-catalog + leaderboard app"
        assert len(payload["actions"]) == 3
        action_ids = {a["id"] for a in payload["actions"]}
        assert action_ids == {"generate_nearest", "refine_brief", "cancel"}

    def test_out_of_scope_action_label_names_nearest(self):
        plan = {
            "coverage_verdict": {
                "status": "out_of_scope",
                "reason": "no",
                "nearest_supported": "video-project-management app",
            }
        }
        decision = coverage_verdict_gate.evaluate(plan)
        gen_action = next(a for a in decision.refusal_payload["actions"] if a["id"] == "generate_nearest")
        assert "video-project-management app" in gen_action["label"]


# ══════════════════════════════════════════════════════════════════
# substrate_gap_log — append-only JSONL (M2-T2)
# ══════════════════════════════════════════════════════════════════


class TestSubstrateGapLog:
    @pytest.fixture(autouse=True)
    def _isolated_log(self, tmp_path, monkeypatch):
        log_path = tmp_path / "substrate_gap_log.jsonl"
        monkeypatch.setenv("FORGE_SUBSTRATE_GAP_LOG", str(log_path))
        yield log_path

    def test_read_all_empty_when_no_file(self, _isolated_log):
        assert substrate_gap_log.read_all() == []

    def test_append_writes_line_with_timestamp(self, _isolated_log):
        substrate_gap_log.append({"reason": "close", "missing_dimensions": ["x"]})
        entries = substrate_gap_log.read_all()
        assert len(entries) == 1
        assert entries[0]["reason"] == "close"
        assert entries[0]["missing_dimensions"] == ["x"]
        assert "ts" in entries[0]

    def test_append_creates_parent_directory(self, tmp_path, monkeypatch):
        deep = tmp_path / "a" / "b" / "log.jsonl"
        monkeypatch.setenv("FORGE_SUBSTRATE_GAP_LOG", str(deep))
        substrate_gap_log.append({"x": 1})
        assert deep.exists()

    def test_multiple_appends_preserve_order(self, _isolated_log):
        for i in range(5):
            substrate_gap_log.append({"seq": i})
        entries = substrate_gap_log.read_all()
        assert [e["seq"] for e in entries] == [0, 1, 2, 3, 4]

    def test_malformed_lines_are_skipped(self, _isolated_log):
        _isolated_log.write_text('{"ok": 1}\n{not json}\n{"ok": 2}\n', encoding="utf-8")
        entries = substrate_gap_log.read_all()
        assert [e["ok"] for e in entries] == [1, 2]

    def test_iter_entries_lazy(self, _isolated_log):
        for i in range(3):
            substrate_gap_log.append({"i": i})
        got = [e["i"] for e in substrate_gap_log.iter_entries()]
        assert got == [0, 1, 2]

    def test_clear_truncates(self, _isolated_log):
        substrate_gap_log.append({"x": 1})
        substrate_gap_log.clear()
        assert substrate_gap_log.read_all() == []


# ══════════════════════════════════════════════════════════════════
# runtime_context_wire — compute_wire_plan + merge_into_app_json (M3-T8)
# ══════════════════════════════════════════════════════════════════


class TestComputeWirePlan:
    def test_empty_context_yields_empty_plan(self):
        plan = runtime_context_wire.compute_wire_plan([])
        assert plan.capabilities == ()
        assert plan.permissions_ios == {}
        assert plan.permissions_android == ()
        assert plan.providers == ()
        assert plan.integration_keys_required == ()
        assert plan.missing_bundles == ()

    def test_none_context_yields_empty_plan(self):
        plan = runtime_context_wire.compute_wire_plan(None)
        assert plan.capabilities == ()

    def test_geo_only_produces_geo_bundle(self):
        plan = runtime_context_wire.compute_wire_plan(["geo"])
        assert plan.capabilities == ("geo",)
        assert "NSLocationWhenInUseUsageDescription" in plan.permissions_ios
        assert "android.permission.ACCESS_FINE_LOCATION" in plan.permissions_android
        assert "expo-location" in plan.expo_plugins
        assert "expo-location" in plan.native_imports_expo
        assert any(p.capability == "geo" for p in plan.providers)

    def test_push_notifications_declares_integration_keys(self):
        plan = runtime_context_wire.compute_wire_plan(["push_notifications"])
        env_vars = {k.env_var for k in plan.integration_keys_required}
        assert "FCM_SERVER_KEY" in env_vars

    def test_multiple_capabilities_dedupe_permissions(self):
        # geo + camera + push + biometric — no duplicate Android perms.
        plan = runtime_context_wire.compute_wire_plan(["geo", "camera", "push_notifications", "biometric_auth"])
        assert plan.capabilities == ("geo", "camera", "push_notifications", "biometric_auth")
        # No repeats
        assert len(plan.permissions_android) == len(set(plan.permissions_android))
        assert len(plan.expo_plugins) == len(set(plan.expo_plugins))
        # Each capability contributes at least one plugin.
        for expected in ("expo-location", "expo-camera", "expo-notifications", "expo-local-authentication"):
            assert expected in plan.expo_plugins

    def test_unknown_capability_recorded_in_missing_bundles(self):
        plan = runtime_context_wire.compute_wire_plan(["geo", "made_up_capability"])
        assert "made_up_capability" in plan.missing_bundles
        assert "geo" in plan.capabilities
        # made_up_capability is NOT in resolved capabilities
        assert "made_up_capability" not in plan.capabilities

    def test_deep_linking_extras_land_in_app_json_extras(self):
        plan = runtime_context_wire.compute_wire_plan(["deep_linking"])
        # The deep_linking bundle declares app_json_extras.scheme = "${APP_SCHEME}"
        assert plan.app_json_extras.get("scheme") == "${APP_SCHEME}"
        assert plan.app_json_extras.get("ios_associated_domains") is True or "ios_associated_domains" in plan.app_json_extras

    def test_provider_hook_names_preserved(self):
        plan = runtime_context_wire.compute_wire_plan(["geo"])
        geo_provider = next(p for p in plan.providers if p.capability == "geo")
        assert "useGeo" in geo_provider.hook_names


class TestMergeIntoAppJson:
    def test_merge_adds_ios_permissions_without_overwrite(self):
        existing = {"expo": {"ios": {"infoPlist": {"CFBundleName": "MyApp"}}}}
        plan = runtime_context_wire.compute_wire_plan(["camera"])
        merged = runtime_context_wire.merge_into_app_json(existing, plan)
        info = merged["expo"]["ios"]["infoPlist"]
        assert info["CFBundleName"] == "MyApp"  # untouched
        assert info["NSCameraUsageDescription"]  # added

    def test_merge_adds_android_permissions(self):
        existing = {}
        plan = runtime_context_wire.compute_wire_plan(["push_notifications"])
        merged = runtime_context_wire.merge_into_app_json(existing, plan)
        assert "android.permission.POST_NOTIFICATIONS" in merged["expo"]["android"]["permissions"]

    def test_merge_dedupes_plugins(self):
        existing = {"expo": {"plugins": ["expo-location"]}}
        plan = runtime_context_wire.compute_wire_plan(["geo"])
        merged = runtime_context_wire.merge_into_app_json(existing, plan)
        assert merged["expo"]["plugins"].count("expo-location") == 1

    def test_merge_preserves_input(self):
        existing = {"expo": {"ios": {"infoPlist": {}}}}
        plan = runtime_context_wire.compute_wire_plan(["camera"])
        _ = runtime_context_wire.merge_into_app_json(existing, plan)
        # Original untouched
        assert "NSCameraUsageDescription" not in existing["expo"]["ios"]["infoPlist"]

    def test_merge_scheme_from_deep_linking(self):
        existing = {}
        plan = runtime_context_wire.compute_wire_plan(["deep_linking"])
        merged = runtime_context_wire.merge_into_app_json(existing, plan)
        # deep_linking bundle sets app_json_extras.scheme
        assert merged["expo"]["scheme"] == "${APP_SCHEME}"

    def test_existing_scheme_not_overwritten(self):
        existing = {"expo": {"scheme": "myapp"}}
        plan = runtime_context_wire.compute_wire_plan(["deep_linking"])
        merged = runtime_context_wire.merge_into_app_json(existing, plan)
        assert merged["expo"]["scheme"] == "myapp"


# ══════════════════════════════════════════════════════════════════
# End-to-end sanity — a valid Snap2App-shaped plan flows through
# all four modules cleanly.
# ══════════════════════════════════════════════════════════════════


class TestE2EIntegration:
    def test_snap2app_plan_flows_through_all_modules(self):
        plan = {
            "app_shape": _snap2app_shape(),
            "archetypes": [
                {"name": "scan", "recipe": "visual_product_search", "routes": ["/"]}
            ],
            "runtime_context": ["camera"],
            "coverage_verdict": {"status": "in_scope", "reason": "consumer capture utility"},
        }

        # 1. Gate proceeds
        decision = coverage_verdict_gate.evaluate(plan)
        assert decision.action == "proceed"

        # 2. Derived helpers give consistent answers
        shape = spd.resolve_shape(plan, "/")
        assert spd.needs_root_toaster(shape) is True  # shell:none + modal auth + fire-and-forget
        assert spd.should_generate_login_route(shape) is False  # modal
        assert spd.form_submit_pattern(shape) == "fire-and-forget-with-toast-nav"
        assert spd.denorm_columns_needed(shape) is True  # data.denormalization: aggressive
        assert spd.synth_shell_menu(shape) is False  # nav.menu: none
        assert spd.shell_kind(shape) == "none"

        # 3. Runtime wire produces camera bundle
        wire = runtime_context_wire.compute_wire_plan(plan["runtime_context"])
        assert "camera" in wire.capabilities
        assert "expo-camera" in wire.expo_plugins

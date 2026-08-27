"""Tests for M4 batch — T1 (route_shape_directive) + T2 (build_form_page
submitMode) + T3 (translate_workflow executionMode) + T5 (post_gen_route_shape)
+ T6 (signature_move_resolver + shape_signature_enforcer)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import (
    post_gen_route_shape,
    route_context,
    route_shape_directive,
    shape_signature_enforcer,
    signature_move_resolver,
)


# ══════════════════════════════════════════════════════════════════
# route_context — shared helper
# ══════════════════════════════════════════════════════════════════


def _snap2app_plan_with_module() -> dict:
    return {
        "app_shape": {
            "layout": {"shell": "none", "hero": "full-bleed-gradient",
                       "primaryInteraction": "capture", "density": "spacious"},
            "auth": {"surface": "modal", "gating": "on-action"},
            "nav": {"menu": "none", "back": "history"},
            "workflows": {"executionMode": "fire-and-forget"},
            "data": {"readShape": "list", "denormalization": "aggressive"},
            "identity": {"usageMode": "single-session"},
        },
        "runtime_context": ["camera", "geo"],
        "archetypes": [
            {
                "name": "scan-app",
                "recipe": "visual-product-search",
                "routes": ["/", "/scan", "/history"],
                "capabilities": {
                    "read": {"pattern": "list"},
                    "write": {"pattern": "capture"},
                    "interactions": ["swipe-to-dismiss"],
                    "presentation": {"itemShape": "card"},
                    "state": {"realtime": "poll"},
                },
            },
        ],
    }


class TestRouteContextFor:
    def test_empty_plan_returns_empty_context(self):
        ctx = route_context.route_context_for(None, "/x")
        assert ctx.route == "/x"
        assert ctx.shape == {}
        assert ctx.owning_archetype is None
        assert ctx.runtime_context == ()

    def test_returns_shape_and_owning_module(self):
        plan = _snap2app_plan_with_module()
        ctx = route_context.route_context_for(plan, "/scan")
        assert ctx.owning_module_name == "scan-app"
        assert ctx.shape["layout"]["shell"] == "none"
        assert "camera" in ctx.runtime_context

    def test_route_not_owned_returns_no_module(self):
        plan = _snap2app_plan_with_module()
        ctx = route_context.route_context_for(plan, "/other")
        assert ctx.owning_archetype is None
        # But shape still comes from plan.app_shape
        assert ctx.shape["layout"]["shell"] == "none"

    def test_runtime_context_dedup_and_type_filter(self):
        plan = {"runtime_context": ["camera", 42, None, "camera"]}
        ctx = route_context.route_context_for(plan, "")
        assert set(ctx.runtime_context) == {"camera"}  # dupes + non-str dropped


# ══════════════════════════════════════════════════════════════════
# T1 — route_shape_directive
# ══════════════════════════════════════════════════════════════════


class TestRouteShapeDirective:
    def test_no_shape_returns_empty(self):
        assert route_shape_directive.build_directive({}, "/x") == ""
        assert route_shape_directive.build_directive(None, "/x") == ""

    def test_renders_shape_slices(self):
        block = route_shape_directive.build_directive(
            _snap2app_plan_with_module(), "/scan")
        assert "Route Substrate" in block
        assert "HARD CONSTRAINTS" in block
        assert "`none`" in block  # shell value
        assert "`full-bleed-gradient`" in block
        assert "`fire-and-forget`" in block  # executionMode

    def test_renders_owning_module(self):
        block = route_shape_directive.build_directive(
            _snap2app_plan_with_module(), "/scan")
        assert "scan-app" in block
        assert "visual-product-search" in block
        assert "write.pattern" in block
        assert "capture" in block

    def test_renders_runtime_context(self):
        block = route_shape_directive.build_directive(
            _snap2app_plan_with_module(), "/scan")
        assert "runtime_context" in block
        assert "`camera`" in block
        assert "`geo`" in block


# ══════════════════════════════════════════════════════════════════
# T2 — build_form_page reads form_submit_pattern
# ══════════════════════════════════════════════════════════════════


class TestBuildFormPageSubmitMode:
    @staticmethod
    def _mini_columns():
        return {
            "title": {"data_type": "varchar", "nullable": False},
            "amount": {"data_type": "numeric", "nullable": True},
        }

    def _find_form_props(self, page):
        # Walk the schema to find the Form node
        def _walk(node):
            if isinstance(node, dict):
                if node.get("type") == "Form":
                    return node.get("props") or {}
                for v in node.values():
                    r = _walk(v)
                    if r is not None:
                        return r
            elif isinstance(node, list):
                for i in node:
                    r = _walk(i)
                    if r is not None:
                        return r
            return None
        return _walk(page.get("root"))

    def test_no_plan_emits_no_submit_mode(self):
        from services.deterministic_pages import build_form_page
        page = build_form_page(
            entity="Task",
            columns=self._mini_columns(),
            route="/tasks/new",
            design_spec=None,
        )
        props = self._find_form_props(page)
        assert props is not None
        assert "submitMode" not in props  # historic behavior preserved

    def test_plan_with_fire_and_forget_shape(self):
        from services.deterministic_pages import build_form_page
        plan = {"app_shape": {"workflows": {"executionMode": "fire-and-forget"}}}
        page = build_form_page(
            entity="Task",
            columns=self._mini_columns(),
            route="/tasks/new",
            design_spec=None,
            plan=plan,
        )
        props = self._find_form_props(page)
        assert props.get("submitMode") == "fire-and-forget-with-toast-nav"

    def test_plan_with_await_shape(self):
        from services.deterministic_pages import build_form_page
        plan = {"app_shape": {"workflows": {"executionMode": "await-with-progress"}}}
        page = build_form_page(
            entity="Task",
            columns=self._mini_columns(),
            route="/tasks/new",
            design_spec=None,
            plan=plan,
        )
        props = self._find_form_props(page)
        assert props.get("submitMode") == "await-with-spinner"

    def test_plan_with_streaming_shape(self):
        from services.deterministic_pages import build_form_page
        plan = {"app_shape": {"workflows": {"executionMode": "streaming"}}}
        page = build_form_page(
            entity="Task",
            columns=self._mini_columns(),
            route="/tasks/new",
            design_spec=None,
            plan=plan,
        )
        props = self._find_form_props(page)
        assert props.get("submitMode") == "in-place-progress"

    def test_local_shape_override_wins(self):
        from services.deterministic_pages import build_form_page
        # App-level shape says await; module local_shape overrides to fire-and-forget on /pay
        plan = {
            "app_shape": {"workflows": {"executionMode": "await-with-progress"}},
            "archetypes": [
                {
                    "name": "pay-app",
                    "routes": ["/pay"],
                    "local_shape": {"workflows": {"executionMode": "fire-and-forget"}},
                },
            ],
        }
        page = build_form_page(
            entity="Payment",
            columns=self._mini_columns(),
            route="/pay",
            design_spec=None,
            plan=plan,
        )
        props = self._find_form_props(page)
        assert props.get("submitMode") == "fire-and-forget-with-toast-nav"


# ══════════════════════════════════════════════════════════════════
# T3 — translate_workflow reads executionMode via owning_route
# ══════════════════════════════════════════════════════════════════


class TestTranslateWorkflowSubmitMode:
    @staticmethod
    def _rich_wf(name: str, owning_route: str | None = None):
        wf = {
            "name": name,
            "steps": [
                {"id": "start", "type": "trigger", "next": "insert"},
                {"id": "insert", "type": "db_insert",
                 "config": {"table": "payments", "fields": {"amount": 10}}},
                {"id": "end", "type": "end"},
            ],
        }
        if owning_route:
            wf["owning_route"] = owning_route
        return wf

    def test_no_plan_no_submit_mode(self):
        from services.workflow_step_translator import translate_workflow
        result = translate_workflow(self._rich_wf("Charge"))
        assert result is not None
        assert "submitMode" not in result["definition"]["trigger"]

    def test_plan_and_owning_route_emits_submit_mode(self):
        from services.workflow_step_translator import translate_workflow
        plan = {"app_shape": {"workflows": {"executionMode": "fire-and-forget"}}}
        result = translate_workflow(
            self._rich_wf("Charge", owning_route="/pay"), plan=plan)
        assert result["definition"]["trigger"]["submitMode"] == "fire-and-forget"

    def test_local_shape_at_owning_route_wins(self):
        from services.workflow_step_translator import translate_workflow
        plan = {
            "app_shape": {"workflows": {"executionMode": "await-with-progress"}},
            "archetypes": [
                {"name": "pay-app", "routes": ["/pay"],
                 "local_shape": {"workflows": {"executionMode": "streaming"}}},
            ],
        }
        result = translate_workflow(
            self._rich_wf("Charge", owning_route="/pay"), plan=plan)
        assert result["definition"]["trigger"]["submitMode"] == "streaming"

    def test_plan_but_no_owning_route_no_mode(self):
        from services.workflow_step_translator import translate_workflow
        plan = {"app_shape": {"workflows": {"executionMode": "fire-and-forget"}}}
        result = translate_workflow(self._rich_wf("Charge"), plan=plan)
        assert "submitMode" not in result["definition"]["trigger"]

    def test_unknown_mode_dropped(self):
        from services.workflow_step_translator import translate_workflow
        plan = {"app_shape": {"workflows": {"executionMode": "telepathy"}}}
        result = translate_workflow(
            self._rich_wf("Charge", owning_route="/pay"), plan=plan)
        assert "submitMode" not in result["definition"]["trigger"]


# ══════════════════════════════════════════════════════════════════
# T5 — post_gen_route_shape
# ══════════════════════════════════════════════════════════════════


class TestPostGenRouteShape:
    def test_missing_plan_json_returns_empty(self, tmp_path):
        assert post_gen_route_shape.shape_for_route(tmp_path, "/x") == {}

    def test_reads_shape_from_plan_json(self, tmp_path):
        contracts = tmp_path / "src" / "contracts"
        contracts.mkdir(parents=True)
        plan = _snap2app_plan_with_module()
        (contracts / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        shape = post_gen_route_shape.shape_for_route(tmp_path, "/scan")
        assert shape["layout"]["shell"] == "none"

    def test_context_for_route_carries_module(self, tmp_path):
        contracts = tmp_path / "src" / "contracts"
        contracts.mkdir(parents=True)
        plan = _snap2app_plan_with_module()
        (contracts / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        ctx = post_gen_route_shape.context_for_route(tmp_path, "/scan")
        assert ctx.owning_module_name == "scan-app"
        assert "camera" in ctx.runtime_context


# ══════════════════════════════════════════════════════════════════
# T6 — signature_move_resolver + shape_signature_enforcer
# ══════════════════════════════════════════════════════════════════


class TestSignatureMoveResolver:
    def test_unknown_signature_returns_none(self):
        assert signature_move_resolver.resolve("not-a-real-signature") is None

    def test_known_substrate_signatures_nonempty(self):
        names = signature_move_resolver.known_substrate_signatures()
        # signature_moves.json declares many triggers; catalog should be non-empty
        assert len(names) > 5
        assert "lane-swap-animation" in names
        assert "pulsing-scan-orb" in names

    def test_unresolvable_is_full_gap_list(self):
        # No renderer mappings shipped yet; every catalog signature is a gap
        unresolvable = set(signature_move_resolver.unresolvable_signatures())
        known = set(signature_move_resolver.known_substrate_signatures())
        resolvable = set(signature_move_resolver.resolvable_signatures())
        assert unresolvable == known - resolvable


class TestShapeSignatureEnforcer:
    def test_empty_plan_no_report(self, tmp_path):
        report = shape_signature_enforcer.enforce({}, tmp_path)
        assert report.per_route == ()
        assert report.unresolvable_across_app == ()

    def test_plan_with_kanban_recipe_produces_requirements(self, tmp_path):
        plan = {
            "archetypes": [
                {"name": "board", "recipe": "kanban", "routes": ["/board"]},
            ],
        }
        report = shape_signature_enforcer.enforce(plan, tmp_path)
        # Kanban recipe caps include interactions=drag-between-groups →
        # lane-swap-animation family, all currently unresolvable.
        assert report.has_gaps
        # per_route has entries for /board
        routes = {r.route for r in report.per_route}
        assert "/board" in routes

    def test_snap2app_capture_shape_produces_pulsing_orb_requirement(self, tmp_path):
        plan = _snap2app_plan_with_module()
        report = shape_signature_enforcer.enforce(plan, tmp_path)
        # The write.pattern=capture trigger fires → pulsing-scan-orb signature
        all_required: set[str] = set()
        for r in report.per_route:
            all_required.update(r.required)
        assert "pulsing-scan-orb" in all_required

    def test_report_lists_unresolvable(self, tmp_path):
        plan = {
            "archetypes": [
                {"name": "board", "recipe": "kanban", "routes": ["/board"]},
            ],
        }
        report = shape_signature_enforcer.enforce(plan, tmp_path)
        # Since no renderers are mapped, everything is unresolvable
        assert report.unresolvable_across_app  # non-empty

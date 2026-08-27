"""Tests for the plan_and_apply feature-builder seam.

Three pieces:
  1. ``validate_plan`` rejects garbage LLM output.
  2. ``apply_plan`` walks a plan, dispatches each step, halts on failure.
  3. ``plan_and_apply`` composes 1+2 and returns a caller-friendly shape.
"""

from __future__ import annotations

import json

import pytest

from services.smith_plan_and_apply import (
    PlanValidationError,
    apply_plan,
    plan_and_apply,
    plan_feature_ask,
    validate_plan,
)


# --------------------------------------------------------------------------- #
# validate_plan                                                                #
# --------------------------------------------------------------------------- #

class TestValidatePlan:
    def test_accepts_well_formed(self):
        p = [
            {"kind": "add_entity", "args": {"name": "Message", "fields": []}},
            {"kind": "add_page",
             "args": {"archetype": "list", "entity": "Message", "route": "/messages"}},
        ]
        assert len(validate_plan(p)) == 2

    def test_rejects_non_list(self):
        with pytest.raises(PlanValidationError):
            validate_plan({"kind": "add_entity"})  # type: ignore[arg-type]

    def test_rejects_empty(self):
        with pytest.raises(PlanValidationError, match="empty"):
            validate_plan([])

    def test_rejects_too_many_steps(self):
        many = [{"kind": "add_entity", "args": {"name": f"E{i}"}} for i in range(9)]
        with pytest.raises(PlanValidationError, match="too many"):
            validate_plan(many)

    def test_rejects_unknown_kind(self):
        with pytest.raises(PlanValidationError, match="unsupported kind"):
            validate_plan([{"kind": "publish_app", "args": {}}])

    def test_rejects_missing_args(self):
        with pytest.raises(PlanValidationError, match="'args'"):
            validate_plan([{"kind": "add_entity"}])


# --------------------------------------------------------------------------- #
# apply_plan                                                                   #
# --------------------------------------------------------------------------- #

class TestApplyPlan:
    def _monkeypatch_dispatch(self, monkeypatch, script: dict[str, dict]):
        """Replace the seam dispatcher with a scripted map — each seam
        kind returns its stub result."""
        from services import smith_plan_and_apply as m
        calls: list[tuple[str, dict]] = []

        def _dispatch(kind, output_dir, args):
            calls.append((kind, args))
            return script.get(kind, {"success": True})

        monkeypatch.setattr(m, "_dispatch_step", _dispatch)
        return calls

    def test_walks_all_steps_on_success(self, monkeypatch):
        script = {
            "add_entity": {"applied": True, "edited_paths": ["src/db/schema/msg.ts"]},
            "add_page":   {"success": True, "written": [{"path": "src/schemas/messages.json"}]},
        }
        self._monkeypatch_dispatch(monkeypatch, script)
        plan = [
            {"kind": "add_entity", "args": {"name": "Message"}, "label": "Add entity"},
            {"kind": "add_page",   "args": {"archetype": "list", "entity": "Message",
                                             "route": "/messages"}, "label": "Add list page"},
        ]
        result = apply_plan(plan, output_dir="/nowhere")
        assert result["status"] == "ok"
        assert len(result["steps"]) == 2
        assert all(s["ok"] for s in result["steps"])
        # Paths union from both success signals.
        assert "src/db/schema/msg.ts" in result["edited_paths"]
        assert "src/schemas/messages.json" in result["edited_paths"]

    def test_halts_on_first_failure(self, monkeypatch):
        script = {
            "add_entity": {"applied": True},
            "add_page":   {"success": False, "error": "invalid archetype"},
            "add_workflow": {"success": True},  # SHOULD NOT be called
        }
        calls = self._monkeypatch_dispatch(monkeypatch, script)
        plan = [
            {"kind": "add_entity", "args": {"name": "X"}},
            {"kind": "add_page",   "args": {}},
            {"kind": "add_workflow", "args": {}},
        ]
        result = apply_plan(plan, output_dir="/nowhere")
        assert result["status"] == "partial"
        assert result["failed_at"] == 1
        # Third step must not have been dispatched.
        kinds_dispatched = [c[0] for c in calls]
        assert kinds_dispatched == ["add_entity", "add_page"]

    def test_progress_callback_receives_events(self, monkeypatch):
        self._monkeypatch_dispatch(monkeypatch, {"add_entity": {"applied": True}})
        events: list[dict] = []
        plan = [{"kind": "add_entity", "args": {"name": "X"}, "label": "Add X"}]
        apply_plan(plan, output_dir="/nowhere", on_progress=lambda e: events.append(e))
        stages = [e["stage"] for e in events]
        assert "start" in stages and "done" in stages


# --------------------------------------------------------------------------- #
# plan_and_apply                                                               #
# --------------------------------------------------------------------------- #

class TestPlanAndApply:
    def test_end_to_end_with_stubbed_planner_and_dispatch(self, monkeypatch):
        # Stub planner LLM: return a 2-step plan for the messaging feature.
        def _fake_plan_query(sysp, userp):
            return json.dumps([
                {"kind": "add_entity", "args": {"name": "Message", "fields": []},
                 "label": "Add Message entity"},
                {"kind": "add_page",
                 "args": {"archetype": "list", "entity": "Message", "route": "/messages"},
                 "label": "Add /messages list"},
            ])

        # Stub seam dispatch — everything succeeds.
        from services import smith_plan_and_apply as m
        monkeypatch.setattr(m, "_dispatch_step",
                             lambda kind, o, a: {"success": True, "applied": True})

        r = plan_and_apply(
            "add candidate messaging",
            output_dir="/nowhere",
            query_fn=_fake_plan_query,
        )
        assert r["status"] == "ok"
        assert len(r["plan"]) == 2
        assert r["plan"][0]["kind"] == "add_entity"
        assert r["plan"][1]["label"] == "Add /messages list"

    def test_plan_error_when_llm_output_is_garbage(self):
        def _bad(sysp, userp):
            return "not json at all"
        r = plan_and_apply("add stuff", "/nowhere", query_fn=_bad)
        assert r["status"] == "plan_error"
        assert "not valid JSON" in r["error"]
        assert r["plan"] is None

    def test_plan_error_when_kind_unknown(self):
        def _bad(sysp, userp):
            return json.dumps([{"kind": "publish_the_app", "args": {}}])
        r = plan_and_apply("do it", "/nowhere", query_fn=_bad)
        assert r["status"] == "plan_error"
        assert "unsupported kind" in r["error"]

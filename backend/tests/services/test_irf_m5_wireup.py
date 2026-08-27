"""Tests for M5-T3 + M5-T4 + M5-T5 wire-ups.

T3 wire — smith_memory.read_smith_memory populates
    ``SmithMemory.session_context_block`` from persisted history +
    ambient SessionContext, and to_prompt_block() renders it.
T4 wire — services.stage_plan_emitter.preview / record_after emit an
    SSE-shaped dict and append an EditRecord to the ambient
    SessionContext.
T5 wire — stage_verify_ladder now uses the verify_stack composition
    primitive (per-check records land in verify_history)."""
from __future__ import annotations

import json

import pytest

from services import session_context as sc
from services import smith_memory as sm
from services import stage_check_registry as scr
from services import stage_plan_emitter as spe
from services import stage_verify_ladder as svl


# ══════════════════════════════════════════════════════════════════
# T3 wire — SmithMemory carries + renders session_context_block
# ══════════════════════════════════════════════════════════════════


class TestSmithMemoryCarriesSessionContext:
    def test_new_field_is_empty_by_default(self):
        mem = sm.SmithMemory()
        assert mem.session_context_block == ""
        # empty everything is still is_empty()
        assert mem.is_empty() is True

    def test_is_empty_false_when_only_session_context_block(self):
        mem = sm.SmithMemory(session_context_block="**Shape:** layout(shell=`none`)")
        assert mem.is_empty() is False

    def test_to_prompt_block_renders_substrate_section(self):
        mem = sm.SmithMemory(
            session_context_block="**Shape:** layout(shell=`sidebar`)",
        )
        rendered = mem.to_prompt_block()
        assert "## Substrate context" in rendered
        assert "shell=`sidebar`" in rendered

    def test_to_prompt_block_omits_section_when_empty(self):
        mem = sm.SmithMemory(state_lines=["some state"])
        rendered = mem.to_prompt_block()
        assert "## Substrate context" not in rendered


# ══════════════════════════════════════════════════════════════════
# T4 wire — stage_plan_emitter
# ══════════════════════════════════════════════════════════════════


def _install_ctx(plan: dict):
    sc.set_current(None)
    ctx = sc.from_plan(plan)
    sc.set_current(ctx)
    return ctx


class TestStagePlanEmitterPreview:
    def test_unknown_stage_returns_error_dict(self):
        result = spe.preview("nope-stage", ctx=sc.from_plan({}))
        assert "unknown stage" in (result.get("error") or "")

    def test_no_context_returns_empty_intent(self):
        sc.set_current(None)
        result = spe.preview("planner")  # ambient is None
        assert result["stage"] == "planner"
        assert result["intent"] == ""

    def test_planner_returns_populated_dict(self):
        ctx = _install_ctx({
            "industry": "recruitment",
            "data_models": [{"name": "Candidate"}, {"name": "Job"}],
        })
        result = spe.preview("planner")
        assert result["stage"] == "planner"
        assert "recruitment" in result["intent"]
        assert "src/contracts/plan.json" in result["files_to_touch"]
        sc.set_current(None)

    def test_page_schema_agent_carries_bindings_and_workflows(self):
        _install_ctx({
            "pages": [
                {"id": "form", "route": "/new",
                 "root": {"type": "Form", "props": {"workflow": "CreateThing"}}},
            ],
        })
        result = spe.preview("page_schema_agent")
        assert "CreateThing" in result["expected_workflows"]
        assert "src/schemas/form.json" in result["files_to_touch"]
        sc.set_current(None)

    def test_workflow_author_populates_file_paths(self):
        _install_ctx({
            "workflows": [{"name": "CreateThing"}, {"name": "ApproveTask"}],
        })
        result = spe.preview("workflow_author")
        assert result["stage"] == "workflow_author"
        assert "src/workflows/creatething.json" in result["files_to_touch"]
        assert "src/workflows/approvetask.json" in result["files_to_touch"]
        sc.set_current(None)


class TestStagePlanEmitterRecord:
    def test_unknown_stage_returns_none(self):
        _install_ctx({})
        assert spe.record_after("nope") is None
        sc.set_current(None)

    def test_no_context_returns_none(self):
        sc.set_current(None)
        assert spe.record_after("planner") is None

    def test_appends_edit_record_to_ambient_context(self):
        ctx = _install_ctx({
            "workflows": [{"name": "CreateCandidate"}],
        })
        record = spe.record_after("workflow_author", reason="pipeline run")
        assert record is not None
        assert record.stage == "workflow_author"
        assert "createcandidate.json" in record.files_touched[0]
        # And it made it into the SessionContext
        assert len(ctx.edit_history) == 1
        assert ctx.edit_history[0].stage == "workflow_author"
        assert ctx.edit_history[0].reason == "pipeline run"
        sc.set_current(None)


# ══════════════════════════════════════════════════════════════════
# T5 wire — stage_verify_ladder → verify_stack (per-check records)
# ══════════════════════════════════════════════════════════════════


class TestStageVerifyLadderUsesRunStack:
    def _snap2app_plan(self):
        return {
            "app_shape": {
                "layout": {"shell": "none"},
                "nav": {"menu": "none"},
            },
        }

    def test_clean_page_records_per_check_entries(self, monkeypatch):
        monkeypatch.delenv("FORGE_RECOVER_LADDER", raising=False)
        ctx = _install_ctx(self._snap2app_plan())

        clean_page = {
            "schemaVersion": "2",
            "id": "scan",
            "route": "/scan",
            "root": {"type": "Stack", "children": [{"type": "CameraCapture"}]},
        }
        svl.run_page_ladder(
            stage_name="page_schema_agent",
            plan=self._snap2app_plan(),
            route="/scan",
            attempt_1=lambda: clean_page,
        )
        # verify_history now contains one entry per cheap check + one aggregate
        checks_seen = {v.check for v in ctx.verify_history}
        assert "static" in checks_seen
        assert "structural" in checks_seen
        assert "domain_conformance" in checks_seen
        assert "aggregate" in checks_seen
        sc.set_current(None)

    def test_dirty_page_flags_domain_conformance(self, monkeypatch):
        monkeypatch.delenv("FORGE_RECOVER_LADDER", raising=False)
        ctx = _install_ctx(self._snap2app_plan())
        dirty_page = {
            "schemaVersion": "2",
            "id": "scan",
            "route": "/scan",
            # Sidebar on shell:none — violates domain_conformance
            "root": {"type": "Stack", "children": [{"type": "Sidebar"}]},
        }
        svl.run_page_ladder(
            stage_name="page_schema_agent",
            plan=self._snap2app_plan(),
            route="/scan",
            attempt_1=lambda: dirty_page,
        )
        # Find the domain_conformance record
        dc_records = [v for v in ctx.verify_history if v.check == "domain_conformance"]
        assert dc_records
        assert dc_records[0].passed is False
        # And the aggregate failed too
        agg = [v for v in ctx.verify_history if v.check == "aggregate"]
        assert agg and agg[0].passed is False
        sc.set_current(None)

    def test_missing_root_flags_structural(self, monkeypatch):
        monkeypatch.delenv("FORGE_RECOVER_LADDER", raising=False)
        ctx = _install_ctx(self._snap2app_plan())
        bad = {"schemaVersion": "2", "id": "x"}  # no root
        svl.run_page_ladder(
            stage_name="page_schema_agent",
            plan=self._snap2app_plan(),
            route="/x",
            attempt_1=lambda: bad,
        )
        struct = [v for v in ctx.verify_history if v.check == "structural"]
        assert struct
        # missing_root fired
        assert any(f.get("rule", "").endswith("missing_root")
                   for f in struct[0].findings)
        sc.set_current(None)

    def test_no_ambient_context_falls_back(self, monkeypatch):
        """Old behavior preserved when no SessionContext is set."""
        monkeypatch.delenv("FORGE_RECOVER_LADDER", raising=False)
        sc.set_current(None)
        clean_page = {
            "schemaVersion": "2", "id": "x", "route": "/x",
            "root": {"type": "Stack"},
        }
        result = svl.run_page_ladder(
            stage_name="page_schema_agent",
            plan={"app_shape": {"layout": {"shell": "sidebar"}}},
            route="/x",
            attempt_1=lambda: clean_page,
        )
        assert result.succeeded is True


# ══════════════════════════════════════════════════════════════════
# T5 module — stage_check_registry direct tests
# ══════════════════════════════════════════════════════════════════


class TestStageCheckRegistry:
    def test_static_flags_non_dict(self):
        r = scr.PAGE_SCHEMA_REGISTRY["static"]({"schema": "not a dict"}, None)
        assert r["findings"]
        assert r["findings"][0]["rule"] == "static.schema_not_dict"

    def test_static_passes_on_dict(self):
        r = scr.PAGE_SCHEMA_REGISTRY["static"]({"schema": {}}, None)
        assert r["findings"] == []

    def test_structural_flags_missing_root(self):
        r = scr.PAGE_SCHEMA_REGISTRY["structural"](
            {"schema": {"schemaVersion": "2", "id": "x"}}, None)
        assert any(f["rule"].endswith("missing_root") for f in r["findings"])

    def test_structural_flags_root_not_dict(self):
        r = scr.PAGE_SCHEMA_REGISTRY["structural"](
            {"schema": {"schemaVersion": "2", "id": "x", "root": "hello"}}, None)
        assert any(f["rule"] == "structural.root_not_dict" for f in r["findings"])

    def test_domain_conformance_returns_empty_without_shape(self):
        r = scr.PAGE_SCHEMA_REGISTRY["domain_conformance"](
            {"plan": {}, "route": "/x", "schema": {"root": {}}}, None)
        assert r["findings"] == []

    def test_domain_conformance_flags_shell_violation(self):
        r = scr.PAGE_SCHEMA_REGISTRY["domain_conformance"]({
            "plan": {"app_shape": {"layout": {"shell": "none"}}},
            "route": "/x",
            "schema": {"root": {"type": "Sidebar"}},
        }, None)
        assert any(f["rule"] == "domain_conformance.shell_present_on_none"
                   for f in r["findings"])

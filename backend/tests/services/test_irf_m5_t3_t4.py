"""Tests for M5 T3 (smith_memory substrate view) + T4 (StagePlan
protocol + 3 stage authors)."""
from __future__ import annotations

import pytest

from services import session_context as sc
from services import smith_memory as sm
from services import stage_plan as sp


# ══════════════════════════════════════════════════════════════════
# T3 — smith_memory.render_session_context_block + build_memory_block wire
# ══════════════════════════════════════════════════════════════════


class TestRenderSessionContextBlock:
    def test_none_returns_empty(self):
        assert sm.render_session_context_block(None) == ""

    def test_empty_ctx_returns_empty(self):
        ctx = sc.from_plan({})
        assert sm.render_session_context_block(ctx) == ""

    def test_renders_shape_slices(self):
        ctx = sc.from_plan({
            "app_shape": {
                "layout": {"shell": "none", "hero": "full-bleed-gradient"},
                "workflows": {"executionMode": "fire-and-forget"},
            },
        })
        block = sm.render_session_context_block(ctx)
        assert "Shape:" in block
        assert "layout" in block
        assert "shell=`none`" in block
        assert "hero=`full-bleed-gradient`" in block
        assert "executionMode=`fire-and-forget`" in block

    def test_renders_verify_history_pass_and_fail(self):
        ctx = sc.from_plan({})
        # Passed record
        ctx.record_verify(sc.VerifyRecord(
            stage="page_schema_agent:llm_first",
            check="domain_conformance",
            passed=True,
        ))
        # Failed record with a finding
        ctx.record_verify(sc.VerifyRecord(
            stage="page_schema_agent:llm_first",
            check="domain_conformance",
            passed=False,
            findings=[{"rule": "domain_conformance.shell_present_on_none",
                       "message": "Sidebar on shell:none route",
                       "severity": "error"}],
        ))
        block = sm.render_session_context_block(ctx)
        assert "Recent verify" in block
        assert "✗" in block  # failed one
        assert "✓" in block  # passed one
        assert "shell_present_on_none" in block

    def test_renders_edit_history(self):
        ctx = sc.from_plan({})
        ctx.record_edit(sc.EditRecord(
            stage="edit_page",
            intent="rename button label",
            files_touched=["src/schemas/tasks.json", "src/schemas/users.json"],
            reason="user asked",
        ))
        block = sm.render_session_context_block(ctx)
        assert "Recent edits" in block
        assert "edit_page: rename button label" in block
        assert "src/schemas/tasks.json" in block

    def test_caps_verify_and_edit_lists(self):
        ctx = sc.from_plan({})
        for i in range(20):
            ctx.record_verify(sc.VerifyRecord(
                stage=f"stage_{i}", check="c", passed=True))
            ctx.record_edit(sc.EditRecord(
                stage=f"e_{i}", intent=f"intent_{i}"))
        block = sm.render_session_context_block(ctx)
        # Header says "5 of 20"
        assert "5 of 20" in block

    def test_accepts_plain_dict(self):
        """Duck-type: renderer accepts a loaded-history dict too."""
        loaded = {
            "verify_history": [{
                "stage": "page_schema_agent:llm_first",
                "check": "domain_conformance",
                "passed": True,
                "findings": [],
            }],
            "edit_history": [],
            "shape_profile": {"layout": {"shell": "sidebar"}},
        }
        block = sm.render_session_context_block(loaded)
        assert "shell=`sidebar`" in block
        assert "✓" in block


class TestBuildMemoryBlockWiring:
    def test_session_context_block_appears_when_supplied(self):
        block = sm.build_memory_block(
            verbatim=[],
            state_lines=[],
            session_context_block="**Shape:** layout(shell=`none`)",
        )
        assert "## Substrate context" in block
        assert "shell=`none`" in block

    def test_omitted_when_empty(self):
        block = sm.build_memory_block(
            verbatim=[],
            state_lines=[],
        )
        assert "## Substrate context" not in block


# ══════════════════════════════════════════════════════════════════
# T4 — StagePlan authors
# ══════════════════════════════════════════════════════════════════


class TestPlanForPlanner:
    def test_empty_ctx(self):
        plan = sp.plan_for_planner(sc.from_plan({}))
        assert plan.stage_name == "planner"
        assert "src/contracts/plan.json" in plan.files_to_touch
        assert "src/contracts/brief.json" in plan.files_to_read

    def test_intent_includes_industry_and_entity_count(self):
        plan_dict = {
            "industry": "recruitment",
            "data_models": [{"name": "Candidate"}, {"name": "Job"}],
        }
        plan = sp.plan_for_planner(sc.from_plan(plan_dict))
        assert "recruitment" in plan.intent
        assert "2 entities" in plan.intent

    def test_accepts_plain_plan_dict(self):
        plan = sp.plan_for_planner({"industry": "x", "data_models": [{"n": 1}]})
        assert plan.stage_name == "planner"


class TestPlanForPageSchemaAgent:
    def test_no_pages(self):
        result = sp.plan_for_page_schema_agent(sc.from_plan({}))
        assert result.stage_name == "page_schema_agent"
        assert result.files_to_touch == ()
        assert "0 page" in result.intent

    def test_per_page_file_paths(self):
        result = sp.plan_for_page_schema_agent(sc.from_plan({
            "pages": [
                {"id": "dashboard", "route": "/dashboard"},
                {"id": "candidates", "route": "/candidates"},
                {"id": "candidate-detail", "route": "/candidates/[id]"},
            ],
        }))
        assert "src/schemas/dashboard.json" in result.files_to_touch
        assert "src/schemas/candidates.json" in result.files_to_touch
        assert "src/schemas/candidate-detail.json" in result.files_to_touch

    def test_derives_expected_bindings_from_dataSources(self):
        result = sp.plan_for_page_schema_agent(sc.from_plan({
            "pages": [
                {"id": "list", "route": "/x",
                 "dataSources": [{"name": "candidates", "entity": "Candidate"}]},
            ],
        }))
        assert "candidates" in result.expected_bindings

    def test_derives_expected_workflows_from_forms_and_buttons(self):
        result = sp.plan_for_page_schema_agent(sc.from_plan({
            "pages": [
                {"id": "form", "route": "/new",
                 "root": {"type": "Form", "props": {"workflow": "CreateCandidate"}}},
                {"id": "approve", "route": "/approve",
                 "root": {"type": "Stack", "children": [
                     {"type": "Button", "props": {"action": {"workflow": "ApproveTask"}}},
                 ]}},
            ],
        }))
        assert "CreateCandidate" in result.expected_workflows
        assert "ApproveTask" in result.expected_workflows

    def test_slug_falls_through_id_route_name(self):
        # id wins
        assert sp._slug_for({"id": "foo", "route": "/x", "name": "N"}) == "foo"
        # route tail when no id
        assert sp._slug_for({"route": "/candidates/[id]"}) == "id"
        # name when no id/route
        assert sp._slug_for({"name": "Some Page"}) == "some-page"
        # default when nothing
        assert sp._slug_for({}) == "page"


class TestPlanForWorkflowAuthor:
    def test_no_workflows(self):
        result = sp.plan_for_workflow_author(sc.from_plan({}))
        assert result.stage_name == "workflow_author"
        assert result.files_to_touch == ()

    def test_files_derived_from_workflow_names(self):
        result = sp.plan_for_workflow_author(sc.from_plan({
            "workflows": [
                {"name": "CreateCandidate", "steps": []},
                {"name": "Approve Task", "steps": []},
            ],
        }))
        assert "src/workflows/createcandidate.json" in result.files_to_touch
        assert "src/workflows/approve-task.json" in result.files_to_touch
        assert "CreateCandidate" in result.expected_workflows

    def test_ignores_unnamed_workflows(self):
        result = sp.plan_for_workflow_author(sc.from_plan({
            "workflows": [{"name": ""}, {"steps": []}, {"name": "Real"}],
        }))
        assert result.expected_workflows == ("Real",)


class TestStageProtocol:
    """Duck-typed protocol check — any callable returning a StagePlan works."""

    def test_stage_plan_frozen(self):
        p = sp.StagePlan(stage_name="x", intent="y")
        with pytest.raises(Exception):
            p.stage_name = "z"  # type: ignore[misc]

    def test_stage_plan_defaults_are_empty_tuples(self):
        p = sp.StagePlan(stage_name="x", intent="y")
        assert p.files_to_touch == ()
        assert p.files_to_read == ()
        assert p.expected_bindings == ()
        assert p.expected_workflows == ()

    def test_three_authors_satisfy_protocol(self):
        # A protocol Stage has plan(ctx) -> StagePlan. Verify each free
        # function returns a StagePlan for an empty context.
        for fn in (sp.plan_for_planner, sp.plan_for_page_schema_agent,
                   sp.plan_for_workflow_author):
            result = fn(sc.from_plan({}))
            assert isinstance(result, sp.StagePlan)
            assert result.stage_name
            assert result.intent

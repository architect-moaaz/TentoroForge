"""The UI engineer: pages as React, accepted only once they compile, and the
floor kept when they never do."""

import json

import pytest

from services.blueprint import ui_engineer
from services.blueprint.agent_contract import apply_agent_result, AgentResult, ArtifactProposal
from services.blueprint.orchestrator import DAG, completed_nodes, pending_subjects
from services.blueprint.service import BlueprintService
from services.blueprint.ui_engineer import CompileError, compose_page, system_prompt

GOOD_VIEW = '"use client";\nexport default function View() { return <div className="p-6" />; }\n'
GOOD_LOAD = 'import type { PageContext } from "@/sdk/server";\nexport async function load(ctx: PageContext) { return {}; }\n'


def _doc():
    return {
        "application": {"id": "t", "name": "Desk", "description": "Cases for a hotel."},
        "data": {"entities": [{"id": "ENTITY-001", "name": "Case", "fields": [
            {"name": "title", "type": "string", "required": True}]}]},
        "pages": [{"id": "PAGE-001", "name": "All Cases", "route": "/cases", "purpose": "Every case.",
                   "data": {"primaryEntity": "ENTITY-001"}}],
        "workflows": [],
        "composition": {"vision": "Calm and dense.", "conventions": [{"topic": "header", "rule": "Title left"}]},
    }


class _Client:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, *, system, user, schema):
        self.calls.append(user)
        return json.dumps(self.replies.pop(0))


def test_the_prompt_carries_the_sdk_the_kit_and_the_direction():
    s = system_prompt(_doc())
    assert "export interface Case {" in s                         # this app's entities
    assert "@/components/ui/card" in s and "@tentoroforge/library" in s
    assert "Calm and dense." in s and "header: Title left" in s
    assert "https://" not in s


def test_a_page_that_compiles_is_accepted(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    client = _Client([{"rationale": "List first.", "load": GOOD_LOAD, "view": GOOD_VIEW}])
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, client)
    assert body["page"] == "PAGE-001" and body["view"] == GOOD_VIEW
    assert len(client.calls) == 1


def test_the_compilers_errors_go_back_to_the_author(monkeypatch, tmp_path):
    seen = iter([["view.tsx(3,5): error TS2339: Property 'cases' does not exist on type pages."], []])
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: next(seen))
    client = _Client([{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW}] * 2)
    compose_page(_doc(), _doc()["pages"][0], tmp_path, client)
    assert len(client.calls) == 2
    assert "Property 'cases' does not exist" in client.calls[1]
    assert GOOD_VIEW.strip() in client.calls[1], "the retry is shown the code it wrote"


def test_rules_the_compiler_cannot_see_are_refused_too(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    bad = 'export default function View() { return <div style={{ color: "#ff0000" }} />; }'
    client = _Client([{"rationale": "", "load": GOOD_LOAD, "view": bad}] * ui_engineer.COMPILE_ROUNDS)
    with pytest.raises(CompileError) as e:
        compose_page(_doc(), _doc()["pages"][0], tmp_path, client)
    assert "use client" in str(e.value) and "hex colour" in str(e.value)


def test_the_designed_page_sits_on_its_floor():
    node = DAG["page_code"]
    assert node.optional and node.fanout == "pages"
    assert {"page_layouts", "install", "ui_direction", "workflow_steps"} <= node.depends_on
    assert "page_code" in DAG["frontend"].depends_on
    assert DAG["ui_direction"].optional and DAG["ui_direction"].produces == frozenset({"composition"})
    assert DAG["page_review"].depends_on == frozenset({"assemble"}) and DAG["page_review"].optional


def test_resume_writes_only_the_pages_without_code():
    doc = {"pages": [{"id": "PAGE-001"}, {"id": "PAGE-002"}],
           "pageCode": [{"page": "PAGE-001", "load": "l", "view": "v"}]}
    assert pending_subjects(DAG["page_code"], doc) == ["PAGE-002"]
    assert "page_code" not in completed_nodes(doc)


def test_a_page_code_row_is_accepted_by_the_contract(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Desk", domain="ops")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "All Cases", "route": "/cases", "purpose": "x"}]
    svc.save()
    result = AgentResult(task_id="t", agent="ui_engineer", confidence=0.9, proposals=[ArtifactProposal(
        section="pageCode", natural_key="PAGE-001",
        body={"page": "PAGE-001", "rationale": "r", "load": GOOD_LOAD, "view": GOOD_VIEW})])
    assert apply_agent_result(svc, result).applied
    again = AgentResult(task_id="t2", agent="ui_engineer", confidence=0.9, proposals=[ArtifactProposal(
        section="pageCode", natural_key="PAGE-001",
        body={"page": "PAGE-001", "rationale": "r2", "load": GOOD_LOAD, "view": GOOD_VIEW})])
    apply_agent_result(svc, again)
    assert [r["rationale"] for r in svc.doc["pageCode"]] == ["r2"], "one row per page, replaced"

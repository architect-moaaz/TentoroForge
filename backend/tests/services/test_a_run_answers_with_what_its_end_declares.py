"""An `end` declares what the page that ran the workflow may read back
(`reply`, a few named templates) and where the person goes next
(`redirect`). The run's reply is a receipt — its variables are stripped on
the way out, since a 20 MB reply once broke the page that started it — so
a checkout URL a step produced had no way back to the page (2026-10-12).

The contract carries both; the author is refused when they are prose, on
a step that is not an end, or on a refused end; the execute route passes
them through; the page follows the redirect."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidWorkflowStep, check_workflow_steps

ROOT = Path(__file__).resolve().parents[2]
DOC = {"data": {"entities": []}, "workflows": []}


def _flow(end_config: dict, end_type: str = "end") -> AgentResult:
    return AgentResult(task_id="T", agent="workflow", proposals=[ArtifactProposal(
        section="workflows", natural_key="Place order",
        body={"name": "Place order", "trigger": {"kind": "manual"}, "inputs": [{"name": "title", "kind": "field", "type": "string"}], "steps": [
            {"key": "insert_order", "type": "action", "config": {"actionType": "db_insert", "table": "orders",
                                                                  "values": {"title": "{{title}}"}}},
            {"key": "done", "type": end_type, "config": end_config}]})])


def test_the_contract_declares_reply_and_redirect_on_a_step():
    schema = json.loads((ROOT / "contracts" / "blueprint.schema.json").read_text())
    text = json.dumps(schema)
    assert '"reply"' in text and '"redirect"' in text


def test_a_declared_reply_and_an_in_app_redirect_are_accepted():
    check_workflow_steps(_flow({"refused": False, "reply": {"id": "{{insert_order.id}}"},
                                "redirect": "/orders/{{insert_order.id}}"}), DOC)
    check_workflow_steps(_flow({"refused": False, "redirect": "/pay/{{insert_order.id}}"}), DOC)


@pytest.mark.parametrize("end_config,end_type,said", [
    ({"redirect": "go to the orders page"}, "end", "route of this application"),
    ({"reply": "the order id"}, "end", "`reply` maps names"),
    ({"refused": True, "message": "No stock", "redirect": "/orders"}, "end", "refused end tells the person"),
    ({"redirect": "/orders"}, "action", "belong on an `end`"),
])
def test_prose_a_wrong_step_or_a_refused_end_is_refused(end_config, end_type, said):
    if end_type == "action":
        end_config = {**end_config, "actionType": "db_query", "table": "orders"}
    with pytest.raises(InvalidWorkflowStep, match=said):
        check_workflow_steps(_flow(end_config, end_type), DOC)


def test_the_route_passes_the_receipt_through_and_the_page_follows_it():
    injector = (ROOT / "services" / "runtime_injector.py").read_text()
    assert "const { output: _vars, log: _log, ..._rest }" in injector, "the run's variables stay stripped; the rest rides"
    engine = (ROOT / "templates" / "runtime" / "workflows" / "engine.ts").read_text()
    assert "said.redirect" in engine and "said.reply" in engine
    types = (ROOT / "templates" / "runtime" / "workflows" / "types.ts").read_text()
    assert "redirect?: string;" in types and "reply?: Record<string, unknown>;" in types
    client = (ROOT / "templates" / "app-foundation" / "src" / "sdk" / "client.tsx").read_text()
    assert "result.redirect" in client and "window.location.assign(go)" in client
    dispatch = (ROOT / "templates" / "app-foundation" / "src" / "lib" / "WorkflowDispatchProvider.tsx").read_text()
    assert "window.location.assign(go)" in dispatch
    prompt = (ROOT / "services" / "blueprint" / "executors.py").read_text()
    assert "`config.reply` maps a few names" in prompt and "`config.redirect` is where the person is" in prompt

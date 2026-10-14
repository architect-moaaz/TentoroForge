"""An `http_call` carries `auth` naming the secret; the runtime reads the
value from its environment and never writes it anywhere a template or a
log could reach. A name no integration declares is refused at the author
(2026-10-12)."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidTrigger, check_workflow_triggers

DOC = {"roles": [], "data": {"entities": []},
       "integrations": [{"id": "INT-002", "name": "Xero", "status": "APPROVED", "secretRefs": ["XERO_API_KEY"]}]}


def _flow(auth: dict | None) -> AgentResult:
    cfg = {"actionType": "http_call", "url": "https://api.xero.test/invoices", "method": "POST"}
    if auth is not None:
        cfg["auth"] = auth
    return AgentResult(task_id="T", agent="workflow", proposals=[ArtifactProposal(
        section="workflows", natural_key="Sync invoice", body={"name": "Sync invoice", "trigger": {"kind": "manual"},
                                                               "steps": [{"key": "push", "name": "Push", "type": "action", "config": cfg}]})])


def test_a_declared_name_passes_and_an_undeclared_one_is_refused():
    check_workflow_triggers(_flow({"secretRef": "XERO_API_KEY", "in": "bearer"}), DOC)
    with pytest.raises(InvalidTrigger, match="declared by no integration"):
        check_workflow_triggers(_flow({"secretRef": "STRIPE_KEY"}), DOC)
    with pytest.raises(InvalidTrigger, match="names the secret as `secretRef`"):
        check_workflow_triggers(_flow({"in": "bearer"}), DOC)


def test_the_runtime_reads_the_value_by_name_and_keeps_it_out_of_the_log():
    src = (Path(__file__).resolve().parents[2] / "templates" / "runtime" / "workflows" / "index.ts").read_text()
    block = src.split('registerActionHandler("http_call"', 1)[1].split("registerActionHandler(", 1)[0]
    assert "process.env[name]" in block and "is not set in this environment" in block
    assert 'headers["Authorization"] = `Bearer ${value}`' in block
    assert "ctx.variables" not in block.split("const auth =", 1)[1].split("const controller", 1)[0], "the value never enters the run's variables"
    resolver = src.split("export function _resolveRef(", 1)[1].split("\n}\n", 1)[0]
    assert "process.env" not in resolver, "a template cannot reach the environment"
    contract = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "workflow" / "actionContracts.ts").read_text()
    assert 'name: "auth"' in contract


def test_a_process_whose_secret_the_copy_lacks_is_untried_not_red(tmp_path, monkeypatch):
    """The copy a trial runs on holds no real keys; a step that answers
    "<NAME> is not set in this environment" is the check's shortfall, named,
    never a red for Smith to fix."""
    from services.blueprint import process_trials as pt
    from tests.services.test_a_tooling_fault_is_not_a_repair import _Svc
    from tests.services.test_every_process_runs_through import DOC as PDOC, _client

    class _Bench:
        guest = "g"
        last_written = None

        def __init__(self, *a, **k):
            self.extra_env = {}

        def app(self):
            return object()

        def close(self):
            return None
    monkeypatch.setattr(pt, "_records", lambda app, doc: {})
    monkeypatch.setattr(pt, "attach_files", lambda *a, **k: None)
    monkeypatch.setattr("services.smith.trials.run", lambda name, args, *, bench, doc:
                        "`try_workflow` failed\nstep push: XERO_API_KEY is not set in this environment")
    svc = _Svc(tmp_path, PDOC)
    turns = []
    out = pt.prove_processes(svc, str(tmp_path), client=_client([]), bench_factory=_Bench,
                             run_turn=lambda *a, **k: turns.append(a) or {})
    assert out["left"] == [] and turns == []
    assert len(out["untried"]) == 2 and out["untried"][0]["reason"].startswith("step push: XERO_API_KEY is not set")

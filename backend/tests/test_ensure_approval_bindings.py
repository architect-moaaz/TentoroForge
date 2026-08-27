"""Seam-1 relocation: event-bindings.json is LLM-authored, so ensure_approval_bindings
patches it in the LIVE path — adding <entity>_created→approval-workflow bindings that
were missing (the original fix lived in an unwired module)."""
import json
from services.contract_generator import ensure_approval_bindings

PLAN = {
    "entities": [{"name": "LeaveRequest"}],
    "workflows": [{
        "name": "LeaveReviewWorkflow",
        "trigger": "Manager approves or rejects a leave request",
        "description": "Updates leave request status",
        "steps": [],
    }],
}

def _bindings(tmp): return json.loads((tmp/"src/contracts/event-bindings.json").read_text())["bindings"]

def test_creates_file_and_binding_when_missing(tmp_path):
    r = ensure_approval_bindings(tmp_path, PLAN)
    assert r["added"] == 1
    b = _bindings(tmp_path)
    assert any(x["event"] == "leaverequest_created" and "LeaveReviewWorkflow" in x["workflows"] for x in b)

def test_patches_existing_llm_file_without_clobbering(tmp_path):
    p = tmp_path/"src/contracts"; p.mkdir(parents=True)
    (p/"event-bindings.json").write_text(json.dumps({"bindings":[
        {"event":"other_event","source":"x","workflows":["Other"]}]}))
    r = ensure_approval_bindings(tmp_path, PLAN)
    assert r["added"] == 1
    b = _bindings(tmp_path)
    assert any(x["event"]=="other_event" for x in b)             # kept
    assert any(x["event"]=="leaverequest_created" for x in b)    # added

def test_idempotent(tmp_path):
    ensure_approval_bindings(tmp_path, PLAN)
    r2 = ensure_approval_bindings(tmp_path, PLAN)
    assert r2["added"] == 0

def test_non_approval_workflow_not_bound(tmp_path):
    plan = {"entities":[{"name":"Invoice"}], "workflows":[
        {"name":"NightlyJob","trigger":"cron","description":"emails report","steps":[]}]}
    ensure_approval_bindings(tmp_path, plan)
    assert not [x for x in _bindings(tmp_path) if x["event"].endswith("_created")]

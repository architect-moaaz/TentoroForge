# backend/tests/test_workflow_faithful_e2e.py
import json
import os
from routers.generate import _sync_workflows_from_plan
from services.workflow_executability import is_executable_workflow

_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "ewn5ue3r_plan_workflows.json")


def test_sync_writes_executable_domain_workflows(tmp_path):
    plan = {"workflows": list(json.load(open(_FIX)).values())}
    _sync_workflows_from_plan(str(tmp_path), plan)
    files = list((tmp_path / "workflows").glob("*.json"))
    assert len(files) == 6
    execu = 0
    for f in files:
        d = json.loads(f.read_text())
        if is_executable_workflow(d):
            execu += 1
    assert execu == 6, f"only {execu}/6 domain workflows executable"


def test_sync_duplicate_named_rich_workflows_do_not_clobber(tmp_path):
    """Two rich workflows whose names slug to the same value must produce two
    distinct files — the slug-based id must not silently overwrite.

    The skip set used to be two things at once — names another writer had left
    on disk, AND names this loop had just written — so the second of two
    same-named workflows was read as "already there" and dropped. The plan
    declared two and the application got one, silently.

    Asserted on CONTENT, not on a file count: a count cannot tell
    dedup-of-identical-twins from losing a workflow. The two below differ —
    one writes `records`, the other `audit_entries` — so both have to survive
    for this to pass.
    """
    def _steps(table):
        return [
            {"id": "trigger", "type": "trigger", "next": "ins"},
            {"id": "ins", "type": "action", "next": "end",
             "config": {"actionType": "db_insert", "table": table,
                        "fields": ["email"]}},
            {"id": "end", "type": "end"},
        ]

    plan = {"workflows": [
        {"name": "Approval Workflow", "steps": _steps("records")},
        {"name": "Approval Workflow", "steps": _steps("audit_entries")},
    ]}
    _sync_workflows_from_plan(str(tmp_path), plan)
    written = "\n".join(f.read_text() for f in (tmp_path / "workflows").glob("*.json"))
    assert "records" in written, "the first workflow was lost"
    assert "audit_entries" in written, (
        "the second same-named workflow was dropped — the plan declared two "
        "and the app has one"
    )


def test_all_six_domain_workflows_intelligent(tmp_path):
    plan = {"workflows": list(json.load(open(_FIX)).values())}
    _sync_workflows_from_plan(str(tmp_path), plan)
    wf_dir = tmp_path / "workflows"
    by_name = {}
    for f in wf_dir.glob("*.json"):
        d = json.loads(f.read_text())
        by_name[d["name"]] = d

    # 1) every domain workflow is executable (no no-op custom chains)
    for name, d in by_name.items():
        assert is_executable_workflow(d), f"{name} not executable"

    # 2) CV parsing actually uses AI extraction + scoring
    cv = by_name["CVParsingWorkflow"]
    ats = [((n["data"].get("config") or {}).get("actionType"))
           for n in cv["definition"]["nodes"] if n["type"] == "action"]
    assert "ai_extract" in ats and "ai_decide" in ats

    # 3) feedback flow branches on the Hire predicate
    fb = by_name["FeedbackSubmissionWorkflow"]
    assert any(n["type"] == "exclusive_gateway" for n in fb["definition"]["nodes"])
    gw = next(n for n in fb["definition"]["nodes"] if n["type"] == "exclusive_gateway")
    outs = {e["data"]["edgeType"] for e in fb["definition"]["edges"] if e["source"] == gw["id"]}
    assert {"then", "else"} <= outs


def test_sync_wires_db_insert_after_extract_without_persist(tmp_path):
    """A rich workflow that ai_extracts but declares NO db_insert must still get a
    db_insert spliced in on the sync (live) path — persist-wiring runs there too."""
    plan = {
        "data_models": [{"name": "Applicant",
                         "fields": [{"name": "name"}, {"name": "email"}]}],
        "workflows": [{
            "name": "Applicant Intake",
            "description": "Parse an applicant CV and store the applicant",
            "steps": [
                {"id": "trigger", "type": "trigger", "next": "extract"},
                {"id": "extract", "type": "ai_extract", "next": "end",
                 "config": {"actionType": "ai_extract",
                            "prompt": "Extract applicant details",
                            "fields": ["name", "email"]}},
                {"id": "end", "type": "end"},
            ],
        }],
    }
    _sync_workflows_from_plan(str(tmp_path), plan)
    files = list((tmp_path / "workflows").glob("*.json"))
    assert len(files) == 1
    d = json.loads(files[0].read_text())
    nodes = d["definition"]["nodes"]
    insert_nodes = [n for n in nodes
                    if n["type"] == "action"
                    and ((n.get("data") or {}).get("config") or {}).get("actionType") == "db_insert"]
    assert insert_nodes, "persist-wiring did not splice a db_insert after ai_extract"


def test_graph_gate_is_idempotent_on_translated(tmp_path):
    """The deterministic graph gate must find nothing to repair in faithfully
    translated workflows (proves the graph is well-formed: reachable, terminated)."""
    from services.workflow_graph_gate import run_workflow_gate
    plan = {"workflows": list(json.load(open(_FIX)).values())}
    _sync_workflows_from_plan(str(tmp_path), plan)
    report = run_workflow_gate(str(tmp_path), plan)
    # run_workflow_gate returns {checked, repaired, warnings, reports:{stem:{fixed,...}}}.
    # "0 repairs" == no file needed rewriting AND no per-workflow fix was applied.
    total_fixes = sum(len(r.get("fixed", []))
                      for r in (report or {}).get("reports", {}).values())
    assert report.get("repaired", 0) == 0 and total_fixes == 0, \
        f"graph gate had to repair translated workflows: {report}"


def test_a_workflow_another_writer_already_left_is_not_overwritten(tmp_path):
    """The other half of that set, which had no test and is the reason it
    exists: a CRUD scaffold or archetype emitter may write a workflow before
    the plan sync reaches it, and the plan must not stamp over it.

    Without this, "keep both same-named workflows" could be implemented by
    dropping the skip altogether, and the file another writer owns would be
    replaced by the plan's version on every run.
    """
    (tmp_path / "workflows").mkdir(parents=True)
    mine = tmp_path / "workflows" / "approval-workflow.json"
    mine.write_text(json.dumps({"id": "approval-workflow",
                                "name": "Approval Workflow",
                                "writtenByAnotherPass": True}))

    _sync_workflows_from_plan(str(tmp_path), {"workflows": [{
        "name": "Approval Workflow",
        "steps": [
            {"id": "trigger", "type": "trigger", "next": "ins"},
            {"id": "ins", "type": "action", "next": "end",
             "config": {"actionType": "db_insert", "table": "records",
                        "fields": ["email"]}},
            {"id": "end", "type": "end"},
        ]}]})

    assert json.loads(mine.read_text())["writtenByAnotherPass"] is True
    assert len(list((tmp_path / "workflows").glob("*.json"))) == 1

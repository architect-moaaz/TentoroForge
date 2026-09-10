"""Tests for the deterministic workflow executability gate + auto-repair."""
from services.workflow_graph_gate import validate_and_repair


def _wf(nodes, edges, trigger=None):
    return {
        "id": "w1", "name": "W",
        "definition": {
            "trigger": trigger or {"type": "api_event", "event": "x_created"},
            "nodes": nodes, "edges": edges,
        },
    }


def _n(nid, ntype, config=None):
    return {"id": nid, "type": ntype, "data": {"nodeType": ntype, "config": config or {}}}


def test_drops_dangling_edges():
    wf = _wf(
        [_n("trigger", "trigger"), _n("s0", "action", {"actionType": "db_query"}), _n("end", "end")],
        [{"source": "trigger", "target": "s0"}, {"source": "s0", "target": "ghost"}, {"source": "s0", "target": "end"}],
    )
    _, rep = validate_and_repair(wf)
    assert any("dangling edge" in f for f in rep["fixed"])
    assert all(e["target"] != "ghost" for e in wf["definition"]["edges"])


def test_adds_missing_terminal_and_connects_deadends():
    wf = _wf(
        [_n("trigger", "trigger"), _n("s0", "action", {"actionType": "db_query"})],
        [{"source": "trigger", "target": "s0"}],
    )
    wf2, rep = validate_and_repair(wf)
    assert any("terminal" in f for f in rep["fixed"])
    assert any(n["type"] == "end" for n in wf2["definition"]["nodes"])
    # s0 (a dead-end) now connects to the end node
    assert any(e["source"] == "s0" for e in wf2["definition"]["edges"])


def test_normalizes_planner_node_types():
    wf = _wf(
        [_n("trigger", "trigger"), _n("s0", "assignment"), _n("s1", "escalation"), _n("end", "end")],
        [{"source": "trigger", "target": "s0"}, {"source": "s0", "target": "s1"}, {"source": "s1", "target": "end"}],
    )
    wf2, rep = validate_and_repair(wf)
    types = {n["id"]: n["type"] for n in wf2["definition"]["nodes"]}
    assert types["s0"] == "user_task"
    assert types["s1"] == "action"


def test_coerces_unknown_action_type():
    wf = _wf(
        [_n("trigger", "trigger"), _n("s0", "action", {"actionType": "frobnicate"}), _n("end", "end")],
        [{"source": "trigger", "target": "s0"}, {"source": "s0", "target": "end"}],
    )
    wf2, rep = validate_and_repair(wf)
    cfg = wf2["definition"]["nodes"][1]["data"]["config"]
    assert cfg["actionType"] == "set_variable"
    assert any("coerced unknown actionType" in f for f in rep["fixed"])


def test_defaults_missing_assignee():
    wf = _wf(
        [_n("trigger", "trigger"), _n("s0", "approval", {}), _n("end", "end")],
        [{"source": "trigger", "target": "s0"}, {"source": "s0", "target": "end"}],
    )
    wf2, rep = validate_and_repair(wf)
    assert wf2["definition"]["nodes"][1]["data"]["config"]["assigneeRole"] == "admin"


def test_drops_unreachable_nodes():
    wf = _wf(
        [_n("trigger", "trigger"), _n("s0", "action", {"actionType": "db_query"}), _n("orphan", "action", {"actionType": "db_query"}), _n("end", "end")],
        [{"source": "trigger", "target": "s0"}, {"source": "s0", "target": "end"}],  # orphan has no incoming edge
    )
    wf2, rep = validate_and_repair(wf)
    assert any("unreachable" in f for f in rep["fixed"])
    assert all(n["id"] != "orphan" for n in wf2["definition"]["nodes"])


def test_clean_workflow_is_idempotent():
    wf = _wf(
        [_n("trigger", "trigger"), _n("s0", "action", {"actionType": "send_notification", "message": "hi"}), _n("end", "end")],
        [{"source": "trigger", "target": "s0"}, {"source": "s0", "target": "end"}],
    )
    wf2, rep = validate_and_repair(wf)
    assert rep["fixed"] == [], f"clean workflow should need no fixes, got {rep['fixed']}"
    # second pass is also a no-op
    _, rep2 = validate_and_repair(wf2)
    assert rep2["fixed"] == []


def test_warns_on_forward_variable_reference():
    wf = _wf(
        [_n("trigger", "trigger"),
         _n("s0", "action", {"actionType": "db_update", "table": "x", "values": {"a": "{{s1.output}}"}}),
         _n("s1", "action", {"actionType": "db_query"}),
         _n("end", "end")],
        [{"source": "trigger", "target": "s0"}, {"source": "s0", "target": "s1"}, {"source": "s1", "target": "end"}],
    )
    _, rep = validate_and_repair(wf)
    assert any("later/self node" in w for w in rep["warnings"])


def test_flags_unproduced_gateway_variable():
    """A gateway branching on a variable no upstream node produces surfaces both
    as a warning and as a structured `unproduced_vars` finding."""
    wf = _wf(
        [_n("trigger", "trigger", {"entity": "InterviewFeedback"}),
         _n("set", "action", {"actionType": "set_variable", "variableName": "done", "value": True}),
         _n("gw", "exclusive_gateway", {"expression": "overallRecommendation = 'Hire'"}),
         _n("end", "end")],
        [{"source": "trigger", "target": "set"},
         {"source": "set", "target": "gw"},
         {"source": "gw", "target": "end"}],
    )
    _, rep = validate_and_repair(wf)
    assert rep["unproduced_vars"], "expected an unproduced-gateway-var finding"
    assert any(f["variable"] == "overallRecommendation" for f in rep["unproduced_vars"])
    assert any("overallRecommendation" in w and "produce" in w.lower() for w in rep["warnings"])


def test_no_unproduced_finding_when_set_variable_supplies_var():
    wf = _wf(
        [_n("trigger", "trigger"),
         _n("set", "action", {"actionType": "set_variable", "variableName": "overallRecommendation", "value": "Hire"}),
         _n("gw", "exclusive_gateway", {"expression": "overallRecommendation = 'Hire'"}),
         _n("end", "end")],
        [{"source": "trigger", "target": "set"},
         {"source": "set", "target": "gw"},
         {"source": "gw", "target": "end"}],
    )
    _, rep = validate_and_repair(wf)
    assert rep["unproduced_vars"] == []


def test_run_workflow_gate_aggregates_unproduced_vars(tmp_path):
    import json
    from services.workflow_graph_gate import run_workflow_gate

    wf = _wf(
        [_n("trigger", "trigger"),
         _n("gw", "exclusive_gateway", {"expression": "missingVar = 'x'"}),
         _n("end", "end")],
        [{"source": "trigger", "target": "gw"}, {"source": "gw", "target": "end"}],
    )
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "w1.json").write_text(json.dumps(wf), encoding="utf-8")
    summary = run_workflow_gate(str(tmp_path))
    assert summary["unproduced_vars"] >= 1
    assert any(f["variable"] == "missingVar" for f in summary["unproduced_var_findings"])

"""Fix-Assistant A/B log — entry builders + summarizer are pure and easy to test.
The wiring into /chat is exercised by the surrounding orchestration tests."""
from __future__ import annotations

from types import SimpleNamespace

from services.fix_ab_log import (
    build_applied_entry,
    build_clarify_entry,
    build_error_entry,
    build_propose_entry,
    summarize,
)


def _conv(entry: dict):
    return SimpleNamespace(metadata_={"fix_ab": entry})


def test_propose_entry_captures_iterations_and_seam():
    diag = {
        "confidence": 0.82,
        "artifact": {"kind": "workflow", "path": "workflows/x.json"},
        "proposedFix": {"seam": "workflow_node_config", "patch": {"values": {"c": "{{c}}"}}},
    }
    trace = [{"tool": "read_workflow", "args": {}, "result_summary": "..."},
             {"tool": "analyze_workflow_values", "args": {}, "result_summary": "..."},
             {"tool": "propose_fix", "args": {}, "result_summary": "..."}]
    e = build_propose_entry(mode="agent", symptom="Scheduling fails to save",
                            diagnosis=diag, trace=trace, elapsed_ms=1500)
    assert e["mode"] == "agent"
    assert e["phase"] == "propose"
    assert e["outcome"] == "proposal"
    assert e["confidence"] == 0.82
    assert e["seam"] == "workflow_node_config"
    assert e["artifact_kind"] == "workflow"
    assert e["iterations"] == 3
    assert e["tools_used"] == ["read_workflow", "analyze_workflow_values", "propose_fix"]
    assert e["elapsed_ms"] == 1500
    assert e["symptom_len"] == len("Scheduling fails to save")


def test_propose_entry_single_shot_defaults_iterations_to_1():
    diag = {"confidence": 0.5, "artifact": {"kind": "workflow"},
            "proposedFix": {"seam": "workflow_node_config"}}
    e = build_propose_entry(mode="single_shot", symptom="x", diagnosis=diag)
    assert e["mode"] == "single_shot" and e["iterations"] == 1 and e["tools_used"] == []


def test_reemit_phase_survives_the_builder():
    diag = {"confidence": 0.82, "artifact": {"kind": "workflow"},
            "proposedFix": {"seam": "workflow_node_config"}}
    e = build_propose_entry(mode="single_shot", symptom="x", diagnosis=diag, phase="reemit")
    assert e["phase"] == "reemit" and e["outcome"] == "proposal"


def test_clarify_and_error_entries():
    c = build_clarify_entry(mode="agent", symptom="hmm", elapsed_ms=800,
                            trace=[{"tool": "recall"}, {"tool": "ask_user"}])
    assert c["outcome"] == "clarify" and c["iterations"] == 2

    err = build_error_entry(mode="single_shot", symptom="x", elapsed_ms=250)
    assert err["outcome"] == "error" and err["iterations"] == 1


def test_applied_entry_reflects_verify_result():
    diag = {"artifact": {"kind": "workflow"},
            "proposedFix": {"seam": "workflow_node_config"}}
    ok = build_applied_entry(
        mode="agent", diagnosis=diag,
        apply_result={"applied": True, "seam": "workflow_node_config",
                      "verify": {"resolved": True, "remaining": []},
                      "committed": True},
        elapsed_ms=1200,
    )
    assert ok["applied"] is True and ok["resolved"] is True and ok["committed"] is True
    assert ok["remaining_count"] == 0 and ok["seam"] == "workflow_node_config"

    unresolved = build_applied_entry(
        mode="single_shot", diagnosis=diag,
        apply_result={"applied": True, "verify": {"resolved": False, "remaining": ["x", "y"]},
                      "committed": True},
    )
    assert unresolved["applied"] is True and unresolved["resolved"] is False
    assert unresolved["remaining_count"] == 2


def test_summarize_buckets_by_mode_and_computes_rates():
    entries = [
        # agent: 2 proposals, 1 apply (resolved), avg iters (3+2)/2 = 2.5
        build_propose_entry(mode="agent", symptom="a", elapsed_ms=1000,
                            trace=[{"tool": "read_workflow"}, {"tool": "analyze_workflow_values"}, {"tool": "propose_fix"}],
                            diagnosis={"confidence": 0.9, "artifact": {"kind": "workflow"},
                                       "proposedFix": {"seam": "workflow_node_config"}}),
        build_propose_entry(mode="agent", symptom="b", elapsed_ms=800,
                            trace=[{"tool": "recall"}, {"tool": "propose_fix"}],
                            diagnosis={"confidence": 0.7, "artifact": {"kind": "workflow"},
                                       "proposedFix": {"seam": "workflow_node_config"}}),
        build_applied_entry(mode="agent",
                            apply_result={"applied": True, "verify": {"resolved": True, "remaining": []},
                                          "committed": True, "seam": "workflow_node_config"}),
        # single_shot: 3 proposals, 2 applies (1 resolved)
        build_propose_entry(mode="single_shot", symptom="c", elapsed_ms=200,
                            diagnosis={"confidence": 0.8, "artifact": {"kind": "workflow"},
                                       "proposedFix": {"seam": "workflow_node_config"}}),
        build_propose_entry(mode="single_shot", symptom="d", elapsed_ms=250,
                            diagnosis={"confidence": 0.6, "artifact": {"kind": "page"},
                                       "proposedFix": {"seam": "page_schema_patch"}}),
        build_propose_entry(mode="single_shot", symptom="e", elapsed_ms=180,
                            diagnosis={"confidence": 0.75, "artifact": {"kind": "workflow"},
                                       "proposedFix": {"seam": "workflow_node_config"}}),
        build_applied_entry(mode="single_shot",
                            apply_result={"applied": True, "verify": {"resolved": True, "remaining": []},
                                          "committed": True, "seam": "workflow_node_config"}),
        build_applied_entry(mode="single_shot",
                            apply_result={"applied": True, "verify": {"resolved": False, "remaining": ["x"]},
                                          "committed": True, "seam": "workflow_node_config"}),
        # a clarify from the agent
        build_clarify_entry(mode="agent", symptom="hm", trace=[{"tool": "ask_user"}]),
    ]
    conversations = [_conv(e) for e in entries]
    s = summarize(conversations)

    assert s["totals"]["entries"] == len(entries)
    assert s["totals"]["by_phase"]["propose"] == 5
    assert s["totals"]["by_phase"]["applied"] == 3
    assert s["totals"]["by_phase"]["clarify"] == 1

    a = s["modes"]["agent"]
    assert a["proposals"] == 2 and a["applies"] == 1
    assert a["approval_rate"] == 0.5 and a["resolve_rate"] == 1.0
    assert a["avg_iterations"] == 2.5 and a["avg_elapsed_ms"] == 900.0
    assert a["seams"] == {"workflow_node_config": 2}
    assert a["counts"]["clarify"] == 1

    ss = s["modes"]["single_shot"]
    assert ss["proposals"] == 3 and ss["applies"] == 2
    assert ss["approval_rate"] == round(2 / 3, 3)  # 0.667
    assert ss["resolve_rate"] == 0.5
    assert ss["avg_iterations"] == 1.0
    assert ss["seams"] == {"workflow_node_config": 2, "page_schema_patch": 1}


def test_summarize_tolerates_empty_and_malformed():
    assert summarize([]) == {"modes": {}, "totals": {"by_phase": {"propose": 0, "reemit": 0,
                                                                    "clarify": 0, "error": 0,
                                                                    "applied": 0}, "entries": 0}}
    bad = [SimpleNamespace(metadata_=None), SimpleNamespace(metadata_={"fix_ab": "nope"}),
           SimpleNamespace(metadata_={"other": 1}), {"metadata_": {"fix_ab": {"mode": "agent",
                                                                                 "phase": "propose"}}}]
    s = summarize(bad)
    assert s["totals"]["entries"] == 1
    assert s["modes"]["agent"]["counts"]["propose"] == 1

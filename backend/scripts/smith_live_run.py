"""Smith slice-1 live acceptance runner.

Loads the mc2xgclv app's recall + a synthetic <smith-memory> block that
mirrors what the router would build, invokes run_smith_agent with the
REAL Anthropic SDK, and reports the trace + terminal outcome.

Does NOT touch the DB, does NOT apply the fix — just proves the loop
converges on the Schedule-button bug and emits a well-formed
propose_fix diagnosis.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path("/Users/m/Work/code/poc/design2ui-forge-v3/backend")
sys.path.insert(0, str(BACKEND))

# Load .env for ANTHROPIC_API_KEY (never printed).
from dotenv import load_dotenv
load_dotenv(BACKEND / ".env")

# APP defaults to any $SMITH_ACCEPT_APP override, else output/mc2xgclv.
APP = os.environ.get("SMITH_ACCEPT_APP") or str(BACKEND.parent / "output" / "mc2xgclv")

from services.app_recall import assemble_recall
from services.smith_memory import build_smith_memory, MemoryTurn
from agents.smith_agent import run_smith_agent


def main() -> int:
    print(f"=== Smith live acceptance ===")
    print(f"App: {APP}")
    print(f"Symptom: 'The Schedule button on the Assessment Scheduling page is not working'")
    print()

    # --- Recall block ------------------------------------------------------
    t0 = time.monotonic()
    recall = assemble_recall(APP)
    recall_block = recall.to_prompt_block()
    print(f"[recall] {len(recall_block)} chars, {round(time.monotonic()-t0, 2)}s")
    print("  " + recall_block[:200].replace("\n", "\n  "))
    print()

    # --- Memory block: synthesize a 'no pending' fresh conversation --------
    # (a real run would read this from the DB via read_smith_memory)
    memory = build_smith_memory([])  # empty history — fresh conversation
    memory_block = memory.to_prompt_block()
    print(f"[memory] fresh (no prior turns)")
    print()

    # --- Run the loop ------------------------------------------------------
    t1 = time.monotonic()
    result = run_smith_agent(
        user_message=(
            "The Schedule button on the Assessment Scheduling page is not "
            "working — nothing happens when I click it."
        ),
        output_dir=APP,
        recall_block=recall_block,
        memory_block=memory_block,
    )
    elapsed = round(time.monotonic() - t1, 2)
    print(f"[loop] terminated after {elapsed}s")
    print()

    trace = result.get("trace") or []
    print(f"[trace] {len(trace)} steps")
    for i, step in enumerate(trace, 1):
        tool = step.get("tool")
        summary = (step.get("result_summary") or "")[:120]
        print(f"  {i:2d}. {tool:32s} → {summary}")
    print()

    # --- Terminal ----------------------------------------------------------
    diag = result.get("diagnosis")
    answer = result.get("answer")
    question = result.get("question")

    if diag:
        print("[terminal] propose_fix")
        print(f"  feature:    {diag.get('feature')}")
        print(f"  artifact:   {(diag.get('artifact') or {}).get('path')}")
        print(f"  seam:       {(diag.get('proposedFix') or {}).get('seam')}")
        print(f"  nodeId:     {(diag.get('locator') or {}).get('nodeId')}")
        print(f"  confidence: {diag.get('confidence')}")
        patch = (diag.get("proposedFix") or {}).get("patch") or {}
        values = patch.get("values") if isinstance(patch, dict) else None
        if isinstance(values, dict):
            print(f"  proposed values:")
            for k, v in values.items():
                print(f"    {k}: {v}")
        print()

        # Acceptance criteria:
        wf_path = (diag.get("artifact") or {}).get("path", "") or ""
        node_id = (diag.get("locator") or {}).get("nodeId", "") or ""
        expected = {
            "workflow_matches": "assessmentscheduling" in wf_path.lower(),
            "node_matches":     "create_assessment_record" in node_id.lower() or "assessment" in node_id.lower(),
            "seam_correct":     (diag.get("proposedFix") or {}).get("seam") == "workflow_node_config",
            "candidateId_rebound": isinstance(values, dict) and "{{" in str(values.get("candidateId", "")),
        }
        print("[acceptance]")
        all_pass = True
        for k, v in expected.items():
            mark = "PASS" if v else "FAIL"
            if not v: all_pass = False
            print(f"  [{mark}] {k}")
        return 0 if all_pass else 2

    if answer:
        print("[terminal] answer")
        print(f"  {answer[:400]}")
        print("[acceptance] FAIL — expected propose_fix on a real bug, got answer()")
        return 2

    if question:
        print("[terminal] ask_user")
        print(f"  {question[:400]}")
        print("[acceptance] FAIL — Smith couldn't localize a known bug; ask_user is a regression from fix_chat_agent")
        return 2

    print("[acceptance] FAIL — no terminal at all")
    return 2


if __name__ == "__main__":
    sys.exit(main())

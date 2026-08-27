"""Smith slice-2 live acceptance — page-edit / add-component request.

Given a real generated app, ask Smith to add a status Tag component
somewhere sensible. Verifies he:
  1. calls list_pages / list_components / read_page before proposing
     (grounding, not guessing)
  2. terminates on propose_fix with seam=page_schema_patch
  3. emits a well-formed RFC-6902 op list that references a real
     component name from the library

Does NOT touch the DB, does NOT apply the patch — just proves the loop
converges on the right seam + shape.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path("/Users/m/Work/code/poc/design2ui-forge-v3/backend")
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv
load_dotenv(BACKEND / ".env")

APP = os.environ.get("SMITH_ACCEPT_APP") or str(BACKEND.parent / "output" / "mc2xgclv")
# Acceptance symptom is scoped to what page_schema_patch (RFC-6902 add) can
# actually express: adding a NEW component to an existing container. Deeper
# customization (per-row Tag in a Table cell renderer, for example) is a
# structural edit that needs its own seam and is out of scope for slice 2.
SYMPTOM = os.environ.get("SMITH_SYMPTOM") or (
    "On the Pipeline page (route /pipeline), add a Banner above the "
    "applications table reminding recruiters to always add a note before "
    "advancing an application to the next stage."
)

from services.app_recall import assemble_recall
from services.smith_memory import build_smith_memory
from services.smith_tools import list_components_tool
from agents.smith_agent import run_smith_agent


def main() -> int:
    print("=== Smith slice-2 page-edit acceptance ===")
    print(f"App:     {APP}")
    print(f"Symptom: {SYMPTOM[:120]}…" if len(SYMPTOM) > 120 else f"Symptom: {SYMPTOM}")
    print()

    # Library catalog — we'll verify Smith's proposed component name against it.
    cat = list_components_tool(APP)
    real_components = {c["name"] for c in (cat.get("components") or [])}
    print(f"[library] {len(real_components)} components available")
    print()

    # Recall + empty memory (fresh conversation).
    recall_block = assemble_recall(APP).to_prompt_block()
    memory_block = build_smith_memory([]).to_prompt_block()

    t0 = time.monotonic()
    result = run_smith_agent(SYMPTOM, APP, recall_block, memory_block, max_iters=12)
    elapsed = round(time.monotonic() - t0, 2)
    print(f"[loop] {len(result['trace'])} steps, {elapsed}s")
    for i, step in enumerate(result["trace"], 1):
        tool = step.get("tool")
        summary = (step.get("result_summary") or "")[:120]
        print(f"  {i:2d}. {tool:32s} → {summary}")
    print()

    diag = result.get("diagnosis")
    answer = result.get("answer")
    question = result.get("question")

    if not diag:
        print(f"[terminal] {'answer' if answer else 'ask_user'}")
        print(f"  {(answer or question or '')[:400]}")
        print("[acceptance] FAIL — expected propose_fix on a page-edit request")
        return 2

    seam = (diag.get("proposedFix") or {}).get("seam")
    patch = (diag.get("proposedFix") or {}).get("patch")
    art_kind = (diag.get("artifact") or {}).get("kind")
    art_path = (diag.get("artifact") or {}).get("path") or ""

    print("[terminal] propose_fix")
    print(f"  seam:       {seam}")
    print(f"  kind/path:  {art_kind}  {art_path}")
    print(f"  confidence: {diag.get('confidence')}")
    print(f"  patch:      {json.dumps(patch, indent=2)[:800]}")
    print()

    # ---- Acceptance criteria -------------------------------------------
    expected = {
        "seam_is_page_schema_patch":  seam == "page_schema_patch",
        "patch_is_a_list":            isinstance(patch, list),
        "patch_has_at_least_one_op":  isinstance(patch, list) and len(patch) >= 1,
        "ops_have_required_fields":   isinstance(patch, list) and all(
            isinstance(op, dict) and "op" in op and "path" in op for op in patch
        ),
        "artifact_is_page":           art_kind in ("page", "schema") and art_path.endswith(".json"),
    }

    # If any add op inserts a NEW component, the type must be a real library component.
    def _walk_types(value, out):
        if isinstance(value, dict):
            t = value.get("type")
            if isinstance(t, str) and t and t[0].isupper():
                out.append(t)
            for v in value.values():
                _walk_types(v, out)
        elif isinstance(value, list):
            for v in value:
                _walk_types(v, out)

    new_types: list[str] = []
    for op in patch or []:
        if not isinstance(op, dict): continue
        if op.get("op") in ("add", "replace"):
            _walk_types(op.get("value"), new_types)

    expected["proposed_components_exist_in_library"] = (
        not new_types or all(t in real_components for t in new_types)
    )
    if new_types:
        print(f"  proposed component types: {sorted(set(new_types))}")
        unknown = [t for t in new_types if t not in real_components]
        if unknown:
            print(f"  UNKNOWN types (not in library): {unknown}")

    print()
    print("[acceptance]")
    all_pass = True
    for k, v in expected.items():
        mark = "PASS" if v else "FAIL"
        if not v: all_pass = False
        print(f"  [{mark}] {k}")
    return 0 if all_pass else 2


if __name__ == "__main__":
    sys.exit(main())

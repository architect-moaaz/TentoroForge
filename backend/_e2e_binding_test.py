"""TEMP E2E driver: planner -> full relay pipeline, prompt path.

Validates the LLM-path binding work end-to-end: the planner emits per-page
actions[], the schema pipeline binding hook wires buttons, and the app is
emitted with the dependency/runtime fixes. Run from backend/ with a clean env.
"""
import asyncio
import json
import os
import sys
import traceback

DESC = (
    "An employee leave request management system. Employees submit leave "
    "requests with a date range and reason. Managers review pending requests "
    "and can approve or reject them. Show a list of leave requests with their "
    "status, a detail view, and a dashboard summarizing pending vs approved."
)
OUTDIR = os.path.abspath("output/e2e-leave-bind")


async def main():
    from agents.planner import run_planner_oneshot
    from routers import generate as gen

    print("=== STEP 1: planner ===", flush=True)
    plan = await run_planner_oneshot(DESC)
    os.makedirs(OUTDIR, exist_ok=True)
    json.dump(plan, open(os.path.join(OUTDIR, "plan.json"), "w"), indent=2)

    pages = plan.get("pages", [])
    print(f"plan: {len(pages)} pages, {len(plan.get('workflows', []))} workflows, "
          f"{len(plan.get('data_models', plan.get('entities', [])) or [])} models", flush=True)
    for p in pages:
        acts = p.get("actions")
        if acts:
            print(f"  ACTIONS {p.get('route')}: "
                  f"{[(a.get('label'), a.get('workflow'), a.get('kind')) for a in acts]}", flush=True)
    total_actions = sum(len(p.get("actions") or []) for p in pages)
    print(f"TOTAL planner actions declared: {total_actions}", flush=True)

    print("=== STEP 2: relay pipeline (full build) ===", flush=True)
    n = 0
    async for evt in gen._run_relay_pipeline(OUTDIR, plan, DESC):
        n += 1
        t = evt.get("type") if isinstance(evt, dict) else None
        d = evt.get("data", {}) if isinstance(evt, dict) else {}
        msg = (d.get("text") or d.get("message") or d.get("phase") or "") if isinstance(d, dict) else ""
        if t in ("log", "status", "phase", "error", "complete") and msg:
            print(f"[{t}] {msg}"[:240], flush=True)
        elif t in ("error", "complete"):
            print(f"[{t}] {str(d)[:240]}", flush=True)
    print(f"=== DONE: {n} events, outdir={OUTDIR} ===", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)

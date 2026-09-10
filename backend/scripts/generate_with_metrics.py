"""One-shot generation harness with per-phase timing + token telemetry.

Bypasses the HTTP layer so we can run a fresh generation without auth
plumbing. Mirrors what `routers/generate.py:generate_project` does end-to-end:

  1. Run the planner against `--description` to produce app-model.json.
  2. Pipe the plan into `_run_relay_pipeline` (the same one the route uses).
  3. Stream SSE events, tag each event with a phase + timestamp.
  4. Capture token usage from any `result` event the agents emit.
  5. Print a per-phase summary (wall-clock + tokens + cost) at the end.

Run with:
  cd backend
  set -a; source .env; set +a
  python -m scripts.generate_with_metrics \\
      --description "team task tracker with comments" \\
      --short-id genmetrics-$(date +%s)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_ROOT = _REPO_ROOT / "output"


# Map common SSE event-text prefixes to phase names. The pipeline emits
# `[Plan]`, `[Design]`, `[Schema]`, … prefixes via `sse_event("log", ...)`,
# so we can derive phase from text. Where no prefix matches, we keep the
# previous phase.
_PHASE_PREFIXES = [
    ("[Discovery]",   "discovery"),
    ("[Plan]",        "planner"),
    ("[Design]",      "design"),
    ("[Contract",     "contracts"),
    ("[Schema",       "schema"),
    ("[Auth]",        "auth"),
    ("[API]",         "api"),
    ("[Biz",          "business_logic"),
    ("[IR]",          "ir_frontend"),
    ("[Component",    "components"),
    ("[Page",         "pages"),
    ("[Seed]",        "seed"),
    ("[QA]",          "qa"),
    ("[Validate",     "validation"),
    ("[Validator]",   "validation"),
    ("[Fidelity",     "fidelity_loop"),
    ("[Patch",        "fidelity_loop"),
    ("[Index]",       "index"),
    ("[Indexer]",     "index"),
    ("[Rules]",       "rules"),
    ("[Office]",      "office_bridge"),
]


def _classify_phase(text: str, current: str) -> str:
    for prefix, phase in _PHASE_PREFIXES:
        if prefix in text:
            return phase
    return current


def _extract_token_usage(data: dict) -> dict[str, int] | None:
    """Pull token + cost numbers from a `result` event payload, if present.
    Different agents emit slightly different shapes; we try the common ones."""
    if not isinstance(data, dict):
        return None
    # Common keys we've seen in this codebase
    for key in ("usage", "tokens", "cost"):
        v = data.get(key)
        if isinstance(v, dict):
            return {
                "input_tokens":  int(v.get("input_tokens",  v.get("input",  0)) or 0),
                "output_tokens": int(v.get("output_tokens", v.get("output", 0)) or 0),
                "cost_usd": float(v.get("cost_usd", v.get("total_cost_usd", 0.0)) or 0.0),
            }
    # Top-level shape (some agents put numbers directly on the result)
    if "input_tokens" in data or "output_tokens" in data:
        return {
            "input_tokens":  int(data.get("input_tokens",  0) or 0),
            "output_tokens": int(data.get("output_tokens", 0) or 0),
            "cost_usd": float(data.get("total_cost_usd", data.get("cost_usd", 0.0)) or 0.0),
        }
    return None


async def run(description: str, short_id: str) -> int:
    output_dir = _OUTPUT_ROOT / short_id
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"┌─ generation start ──────────────────────────────────────")
    print(f"│ description : {description}")
    print(f"│ short_id    : {short_id}")
    print(f"│ output_dir  : {output_dir}")
    print(f"└─────────────────────────────────────────────────────────")

    sys.path.insert(0, str(_REPO_ROOT / "backend"))
    from agents.planner import run_planner_oneshot, classify_register_llm
    from services.domain_context import detect_domain
    from routers.generate import _run_relay_pipeline

    # Per-phase aggregator
    phase_stats: dict[str, dict[str, Any]] = {}
    current_phase = "init"
    phase_start_ts: dict[str, float] = {current_phase: time.time()}
    overall_start = time.time()

    def log_event(phase: str, text: str, kind: str) -> None:
        elapsed = time.time() - overall_start
        print(f"  [{elapsed:6.1f}s] [{phase:<14}] [{kind}] {text[:140]}")

    def bump_phase(new_phase: str) -> None:
        nonlocal current_phase
        if new_phase == current_phase:
            return
        # Close the prior phase
        if current_phase in phase_start_ts:
            duration = time.time() - phase_start_ts[current_phase]
            phase_stats.setdefault(current_phase, {
                "duration_s": 0.0, "events": 0,
                "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            })
            phase_stats[current_phase]["duration_s"] += duration
        # Open the new phase
        phase_start_ts[new_phase] = time.time()
        phase_stats.setdefault(new_phase, {
            "duration_s": 0.0, "events": 0,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
        })
        current_phase = new_phase

    def record_event(text: str, kind: str, data: dict) -> None:
        nonlocal current_phase
        # Phase classification by text prefix
        new_phase = _classify_phase(text, current_phase)
        bump_phase(new_phase)
        phase_stats.setdefault(current_phase, {
            "duration_s": 0.0, "events": 0,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
        })
        phase_stats[current_phase]["events"] += 1
        usage = _extract_token_usage(data)
        if usage:
            phase_stats[current_phase]["input_tokens"]  += usage["input_tokens"]
            phase_stats[current_phase]["output_tokens"] += usage["output_tokens"]
            phase_stats[current_phase]["cost_usd"]      += usage["cost_usd"]
        log_event(current_phase, text, kind)

    # ── Phase 1: planner (one-shot, headless) ───────────────────────
    bump_phase("planner")
    domain_ctx = detect_domain(description)

    plan_t0 = time.time()
    try:
        plan = await run_planner_oneshot(description, domain_ctx)
    except Exception as e:
        print(f"\n[!] one-shot planner failed: {e}")
        return 1
    plan_elapsed = time.time() - plan_t0
    record_event(
        f"plan-ready entities={list(plan.get('entities', {}).keys())} "
        f"domain={plan.get('domain')!r}",
        "plan_ready",
        {},
    )
    phase_stats["planner"]["duration_s"] = plan_elapsed
    print(f"\n[planner] one-shot completed in {plan_elapsed:.1f}s — "
          f"{len(plan.get('entities', {}))} entities, domain={plan.get('domain')!r}")

    # Inject register classification (LLM-driven, the change we just shipped)
    plan["register"] = await classify_register_llm(description, plan.get("domain", ""), plan)
    print(f"[register] LLM picked: {plan['register']!r}")

    # Persist plan for the relay pipeline
    contracts = output_dir / "src" / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    (contracts / "app-model.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    # ── Phase 2: relay pipeline ──────────────────────────────────────
    bump_phase("design")
    async for evt in _run_relay_pipeline(
        output_dir=str(output_dir),
        plan=plan,
        description=description,
        figma_context=None,
        project_id=None,
    ):
        kind = evt.get("event", "?")
        raw = evt.get("data", "{}")
        data = json.loads(raw) if isinstance(raw, str) else raw
        text = data.get("text", "") if isinstance(data, dict) else str(data)
        record_event(text or kind, kind, data if isinstance(data, dict) else {})

    # Close final phase
    bump_phase("__done__")
    overall = time.time() - overall_start

    # ── Phase summary ────────────────────────────────────────────────
    print()
    print("=" * 78)
    print(f"GENERATION COMPLETE — {overall:.1f}s wall-clock — output at {output_dir}")
    print("=" * 78)
    print(f"{'phase':<18} {'duration':>10}  {'events':>7}  {'in tokens':>11}  {'out tokens':>11}  {'cost USD':>10}")
    print("-" * 78)
    total_in = total_out = 0
    total_cost = 0.0
    for phase, s in phase_stats.items():
        if phase in ("init", "__done__"):
            continue
        print(f"{phase:<18} {s['duration_s']:>9.1f}s  {s['events']:>7}  "
              f"{s['input_tokens']:>11,}  {s['output_tokens']:>11,}  ${s['cost_usd']:>9.4f}")
        total_in  += s["input_tokens"]
        total_out += s["output_tokens"]
        total_cost += s["cost_usd"]
    print("-" * 78)
    print(f"{'TOTAL':<18} {overall:>9.1f}s  {sum(s['events'] for p, s in phase_stats.items() if p not in ('init','__done__')):>7}  "
          f"{total_in:>11,}  {total_out:>11,}  ${total_cost:>9.4f}")
    print()
    print(f"Note: tokens/cost numbers reflect what individual agents publish via 'result' events.")
    print(f"Agents using claude_agent_sdk (most of generation) report cost via ResultMessage.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--description", required=True)
    ap.add_argument("--short-id", required=True)
    args = ap.parse_args()
    return asyncio.run(run(args.description, args.short_id))


if __name__ == "__main__":
    sys.exit(main())

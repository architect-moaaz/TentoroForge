"""One-shot generation harness with per-phase timing — variant that takes a
pre-built plan via --plan-file instead of invoking the conversational planner.

The conversational planner is multi-turn and doesn't reliably emit plan-json
in a single shot. For metric runs and CI smoke tests, hand a structured plan
directly to `_run_relay_pipeline` and skip the planner phase entirely.

Run with:
  cd backend
  set -a; source .env; set +a
  python -m scripts.generate_with_metrics_v2 \\
      --description "team task tracker" \\
      --plan-file /tmp/plan-tasktracker.json \\
      --short-id genmetrics-v2-$(date +%s)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_ROOT = _REPO_ROOT / "output"

# Reuse the phase classification + token extraction from v1.
from scripts.generate_with_metrics import _classify_phase, _extract_token_usage  # type: ignore


async def run(description: str, plan_path: Path, short_id: str) -> int:
    output_dir = _OUTPUT_ROOT / short_id
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = json.loads(plan_path.read_text())

    print(f"┌─ generation start ──────────────────────────────────────")
    print(f"│ description : {description}")
    print(f"│ short_id    : {short_id}")
    print(f"│ output_dir  : {output_dir}")
    print(f"│ plan_file   : {plan_path}")
    print(f"│ entities    : {list((plan.get('entities') or {}).keys())}")
    print(f"└─────────────────────────────────────────────────────────")

    sys.path.insert(0, str(_REPO_ROOT / "backend"))
    from routers.generate import _run_relay_pipeline
    from agents.planner import classify_register_llm

    # Inject LLM-classified register so the design agent + downstream see it
    plan["register"] = await classify_register_llm(description, plan.get("domain", ""), plan)
    print(f"\n[register] LLM picked: {plan['register']!r}\n")

    # Persist plan into the project so downstream loaders find it
    contracts = output_dir / "src" / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    (contracts / "app-model.json").write_text(json.dumps(plan, indent=2))

    # Per-phase aggregator
    phase_stats: dict[str, dict[str, Any]] = {}
    current_phase = "init"
    phase_start_ts: dict[str, float] = {current_phase: time.time()}
    overall_start = time.time()

    def bump_phase(new_phase: str) -> None:
        nonlocal current_phase
        if new_phase == current_phase:
            return
        if current_phase in phase_start_ts:
            duration = time.time() - phase_start_ts[current_phase]
            phase_stats.setdefault(current_phase, {
                "duration_s": 0.0, "events": 0,
                "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            })
            phase_stats[current_phase]["duration_s"] += duration
        phase_start_ts[new_phase] = time.time()
        phase_stats.setdefault(new_phase, {
            "duration_s": 0.0, "events": 0,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
        })
        current_phase = new_phase

    def record_event(text: str, kind: str, data: dict) -> None:
        nonlocal current_phase
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
        elapsed = time.time() - overall_start
        print(f"  [{elapsed:6.1f}s] [{current_phase:<14}] [{kind}] {text[:140]}")

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

    bump_phase("__done__")
    overall = time.time() - overall_start

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
    total_events = sum(s['events'] for p, s in phase_stats.items() if p not in ('init', '__done__'))
    print(f"{'TOTAL':<18} {overall:>9.1f}s  {total_events:>7}  "
          f"{total_in:>11,}  {total_out:>11,}  ${total_cost:>9.4f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--description", required=True)
    ap.add_argument("--plan-file", required=True, type=Path)
    ap.add_argument("--short-id", required=True)
    args = ap.parse_args()
    return asyncio.run(run(args.description, args.plan_file, args.short_id))


if __name__ == "__main__":
    sys.exit(main())

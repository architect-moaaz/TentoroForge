"""Fixture-fleet runner — regenerate the standing fixtures and score them.

    cd backend
    set -a; source .env; set +a
    python -m scripts.fleet run [--only doc-intel,banking] [--runtime] [--replan]

Per fixture (serial — LLM cost/rate limits): wipe ``output/fleet-<name>``,
persist the fixture's generation profile, drive
``services.pipeline.spine.run_pipeline`` with the FROZEN plan +
description (no auth, no platform DB — ``project_id=None``), then read
the scorecard the post-gen tail wrote. ``--runtime`` additionally boots
each app through the journey gate and re-scores at the runtime tier.
``--replan`` runs the one-shot planner from the description instead of
the frozen plan (and SEEDS ``plan.json`` for plan-less fixtures like
leave-management).

Results aggregate to ``fleet-results/<run-ts>/summary.json`` + a
Markdown table (printed and saved). Baselines (``fleet/baselines.json``,
S5 bless/compare) show as a Δ column when present.

Spec: docs/superpowers/plans/2026-08-17-fixture-fleet-scorecard.md (S4).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND.parent
FIXTURES_DIR = _BACKEND / "fleet" / "fixtures"
BASELINES_PATH = _BACKEND / "fleet" / "baselines.json"
RESULTS_DIR = _BACKEND / "fleet-results"
OUTPUT_ROOT = _REPO_ROOT / "output"


# ───────────────────────── fixture loading ──────────────────────────

def load_fixture(name: str) -> dict:
    d = FIXTURES_DIR / name
    if not d.is_dir():
        raise SystemExit(f"unknown fixture {name!r} (see fleet/fixtures/)")
    plan_p = d / "plan.json"
    return {
        "name": name,
        "dir": d,
        "plan": json.loads(plan_p.read_text(encoding="utf-8")) if plan_p.is_file() else None,
        "description": (d / "description.txt").read_text(encoding="utf-8").strip(),
        "meta": json.loads((d / "meta.json").read_text(encoding="utf-8")),
    }


def select_fixtures(only: str | None) -> list[str]:
    all_names = sorted(p.name for p in FIXTURES_DIR.iterdir() if p.is_dir())
    if not only:
        return all_names
    wanted = [n.strip() for n in only.split(",") if n.strip()]
    unknown = [n for n in wanted if n not in all_names]
    if unknown:
        raise SystemExit(f"unknown fixture(s): {unknown}; have {all_names}")
    return wanted


# ───────────────────────── one fixture run ──────────────────────────

async def _replan(description: str) -> dict:
    from agents.planner import run_planner_oneshot
    from services.plan_canonicalizer import canonicalize_plan
    plan = await run_planner_oneshot(description)
    canonical, _ = canonicalize_plan(plan)
    return canonical


async def run_fixture(fx: dict, *, runtime: bool, replan: bool) -> dict:
    from services.generation_profile import get_profile, persist_profile
    from services.pipeline.source import PlanSource
    from services.pipeline.spine import run_pipeline
    from services.scorecard import SCORECARD_REL, write_scorecard

    name = fx["name"]
    out = OUTPUT_ROOT / f"fleet-{name}"
    started = time.time()

    plan = fx["plan"]
    if replan or plan is None:
        if plan is None and not replan:
            return {"fixture": name, "status": "skipped",
                    "reason": "no plan.json — run with --replan to seed"}
        print(f"[{name}] replanning from description…")
        plan = await _replan(fx["description"])
        if fx["plan"] is None:
            # seed the fixture so future runs are deterministic
            (fx["dir"] / "plan.json").write_text(
                json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            print(f"[{name}] seeded fleet/fixtures/{name}/plan.json")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    persist_profile(str(out), get_profile(fx["meta"].get("profile", "fast")))

    print(f"[{name}] generating → {out}")
    events = 0
    try:
        async for evt in run_pipeline(
            output_dir=str(out),
            plan=plan,
            description=fx["description"],
            source=PlanSource.text(),
            project_id=None,
        ):
            events += 1
            data = evt.get("data", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:  # noqa: BLE001
                    data = {}
            text = data.get("text", "") if isinstance(data, dict) else ""
            if text:
                print(f"  [{name} {time.time() - started:6.0f}s] {text[:110]}")
    except Exception as e:  # noqa: BLE001 — one broken fixture must not kill the fleet
        return {"fixture": name, "status": "failed",
                "error": f"{type(e).__name__}: {e}", "events": events,
                "wall_s": round(time.time() - started, 1)}

    tier = "static"
    if runtime:
        tier = "runtime"
        try:
            from services.journey_gate import run_journey_gate
            print(f"[{name}] runtime tier: journey gate…")
            async for _evt in run_journey_gate(str(out), force_mode="warn"):
                pass
        except Exception as e:  # noqa: BLE001
            print(f"[{name}] journey gate failed ({e}) — scoring static "
                  f"artifacts only")

    card = write_scorecard(out, tier=tier)
    return {
        "fixture": name,
        "status": "ok",
        "functional": card.get("functional_score"),
        "design": card.get("design_score"),
        "composite": card.get("composite"),
        "tier": card.get("tier"),
        "events": events,
        "wall_s": round(time.time() - started, 1),
        "scorecard": str(out / SCORECARD_REL),
    }


# ─────────────────────── aggregation + output ───────────────────────

def load_baselines() -> dict:
    if BASELINES_PATH.is_file():
        try:
            return json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def render_table(results: list[dict], baselines: dict) -> str:
    lines = [
        "| fixture | status | functional | design | composite | Δ base | wall |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r["status"] != "ok":
            lines.append(f"| {r['fixture']} | {r['status']} "
                         f"({r.get('reason') or r.get('error', '')}) "
                         f"| — | — | — | — | — |")
            continue
        base = (baselines.get(r["fixture"]) or {}).get("composite")
        delta = "—" if base is None else f"{r['composite'] - base:+.1f}"
        lines.append(
            f"| {r['fixture']} | ok | {r['functional']} | {r['design']} "
            f"| {r['composite']} | {delta} | {r['wall_s']}s |")
    return "\n".join(lines)


async def cmd_run(args: argparse.Namespace) -> int:
    names = select_fixtures(args.only)
    print(f"fleet run — {len(names)} fixture(s): {', '.join(names)}"
          f"{' [runtime]' if args.runtime else ''}"
          f"{' [replan]' if args.replan else ''}\n")

    results: list[dict] = []
    for name in names:
        fx = load_fixture(name)
        results.append(await run_fixture(fx, runtime=args.runtime,
                                         replan=args.replan))

    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RESULTS_DIR / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)
    baselines = load_baselines()
    table = render_table(results, baselines)
    summary: dict[str, Any] = {
        "run_ts": run_ts,
        "runtime_tier": args.runtime,
        "replan": args.replan,
        "results": results,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (run_dir / "summary.md").write_text(table + "\n", encoding="utf-8")

    print("\n" + table)
    print(f"\nresults saved: {run_dir.relative_to(_BACKEND)}/")
    return 0 if all(r["status"] == "ok" for r in results) else 1


# ───────────────────── S5: bless + compare ──────────────────────────

def latest_run_dir() -> Path | None:
    if not RESULTS_DIR.is_dir():
        return None
    runs = sorted(d for d in RESULTS_DIR.iterdir()
                  if d.is_dir() and (d / "summary.json").is_file())
    return runs[-1] if runs else None


def _resolve_run_dir(run_ts: str | None) -> Path:
    if run_ts:
        d = RESULTS_DIR / run_ts
        if not (d / "summary.json").is_file():
            raise SystemExit(f"no summary.json under fleet-results/{run_ts}/")
        return d
    d = latest_run_dir()
    if d is None:
        raise SystemExit("no fleet runs found — run `scripts.fleet run` first")
    return d


def _read_scorecard_for(result: dict) -> dict:
    """Full scorecard for a run result (breakdown lives there, not in
    summary.json). Falls back to {} when the app dir has been wiped by
    a later run."""
    p = result.get("scorecard")
    if p and Path(p).is_file():
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def build_baselines(summary: dict, card_reader=_read_scorecard_for) -> dict:
    """Baselines from one run: headline scores + per-source penalties
    (so compare can NAME the source that regressed)."""
    blessed_at = datetime.now(timezone.utc).isoformat()
    baselines: dict[str, dict] = {}
    for r in summary.get("results", []):
        if r.get("status") != "ok":
            continue
        card = card_reader(r)
        baselines[r["fixture"]] = {
            "functional": r.get("functional"),
            "design": r.get("design"),
            "composite": r.get("composite"),
            "tier": r.get("tier"),
            "wall_s": r.get("wall_s"),
            "breakdown": {k: v.get("penalty", 0)
                          for k, v in (card.get("breakdown") or {}).items()},
            "run_ts": summary.get("run_ts"),
            "blessed_at": blessed_at,
        }
    return baselines


def compare_results(results: list[dict], baselines: dict,
                    tolerance: float) -> list[dict]:
    """Regressions of a run vs blessed baselines. A fixture regresses
    when functional OR design dropped more than `tolerance` points, or
    when it failed/skipped outright. Fixtures without a baseline are
    informational, never regressions (bless will pick them up)."""
    regressions: list[dict] = []
    for r in results:
        name = r.get("fixture")
        if r.get("status") != "ok":
            regressions.append({"fixture": name, "kind": "not_ok",
                                "detail": r.get("error") or r.get("reason")})
            continue
        base = baselines.get(name)
        if not base:
            continue
        for metric in ("functional", "design"):
            b, cur = base.get(metric), r.get(metric)
            if b is None or cur is None:
                continue
            drop = round(b - cur, 1)
            if drop > tolerance:
                regressions.append({"fixture": name, "kind": metric,
                                    "from": b, "to": cur, "drop": drop})
    return regressions


def attribute_sources(card: dict, base: dict) -> list[str]:
    """Which penalty sources got worse vs the baseline, worst first —
    'proof +16.0' means the proof penalty grew by 16 points."""
    base_pen = base.get("breakdown") or {}
    cur_pen = {k: v.get("penalty", 0)
               for k, v in (card.get("breakdown") or {}).items()}
    deltas = []
    for src in set(cur_pen) | set(base_pen):
        d = round(cur_pen.get(src, 0) - base_pen.get(src, 0), 1)
        if d > 0:
            deltas.append((d, src))
    return [f"{src} +{d}" for d, src in sorted(deltas, reverse=True)]


def cmd_bless(args: argparse.Namespace) -> int:
    run_dir = _resolve_run_dir(args.run)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    baselines = build_baselines(summary)
    if not baselines:
        raise SystemExit(f"nothing to bless — no ok results in {run_dir.name}")
    skipped = [r["fixture"] for r in summary.get("results", [])
               if r.get("status") != "ok"]
    # MERGE with existing baselines — a partial run (--only) must update
    # just its own fixtures, never wipe the rest of the fleet's ratchet.
    merged = {**load_baselines(), **baselines}
    BASELINES_PATH.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    print(f"blessed {len(baselines)} fixture(s) from run {summary['run_ts']}"
          f" ({len(merged)} total in baselines)"
          f" → {BASELINES_PATH.relative_to(_BACKEND)}")
    for name, b in sorted(baselines.items()):
        print(f"  {name}: functional={b['functional']} design={b['design']}"
              f" composite={b['composite']}")
    if skipped:
        print(f"  (not blessed — not ok this run: {', '.join(skipped)})")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    baselines = load_baselines()
    if not baselines:
        raise SystemExit("no baselines — run `scripts.fleet bless` first")
    run_dir = _resolve_run_dir(args.run)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = summary.get("results", [])
    regressions = compare_results(results, baselines, args.tolerance)

    print(render_table(results, baselines))
    if not regressions:
        print(f"\ncompare: OK — no fixture dropped more than "
              f"{args.tolerance} point(s) vs baseline")
        return 0
    print(f"\ncompare: {len(regressions)} regression(s):")
    by_fixture = {r["fixture"]: r for r in results}
    for reg in regressions:
        if reg["kind"] == "not_ok":
            print(f"  ✗ {reg['fixture']}: did not complete "
                  f"({reg['detail']})")
            continue
        srcs = attribute_sources(
            _read_scorecard_for(by_fixture.get(reg["fixture"], {})),
            baselines.get(reg["fixture"], {}))
        blame = f" — worse sources: {', '.join(srcs)}" if srcs else ""
        print(f"  ✗ {reg['fixture']}: {reg['kind']} "
              f"{reg['from']} → {reg['to']} (-{reg['drop']}){blame}")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts.fleet")
    sub = ap.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="regenerate + score fixtures")
    run_p.add_argument("--only", help="comma-separated fixture names")
    run_p.add_argument("--runtime", action="store_true",
                       help="boot each app via journey gate + runtime score")
    run_p.add_argument("--replan", action="store_true",
                       help="run the one-shot planner instead of the frozen "
                            "plan (seeds plan-less fixtures)")

    bless_p = sub.add_parser(
        "bless", help="write fleet/baselines.json from a run")
    bless_p.add_argument("--run", help="run timestamp (default: latest)")

    cmp_p = sub.add_parser(
        "compare", help="compare a run vs baselines; exit 1 on regression")
    cmp_p.add_argument("--run", help="run timestamp (default: latest)")
    cmp_p.add_argument("--tolerance", type=float, default=2.0,
                       help="allowed score drop in points (default 2.0)")

    args = ap.parse_args(argv)
    if args.cmd == "run":
        return asyncio.run(cmd_run(args))
    if args.cmd == "bless":
        return cmd_bless(args)
    if args.cmd == "compare":
        return cmd_compare(args)
    ap.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

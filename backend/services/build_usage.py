"""Build-usage ledger — tokens + cost per agent phase per app build.

Every pipeline agent streams through ``sse_helpers.stream_agent_messages``;
its terminal ``ResultMessage`` carries ``total_cost_usd`` and ``usage``
(input/output/cache token counts). This module is the single sink for
those numbers: an append-only JSONL ledger plus the aggregation queries
the admin usage dashboard renders.

Design notes:
  * JSONL over a DB table — same pattern as fidelity_log / smith-outcomes:
    zero migration risk, survives DB resets, trivially greppable. The
    dashboard reads aggregates, not rows, so file-scan cost is fine at
    this volume (one row per agent phase per build).
  * ``record_usage`` NEVER raises — usage accounting must not be the
    thing that fails a build.
  * When the SDK reports cost (CLI-billed runs) we keep it; API-key runs
    report 0.0, so we also compute an estimate from the token counts and
    a per-model price table. The dashboard shows whichever is non-zero
    and labels estimates as such.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_LEDGER = _BACKEND_ROOT / "data" / "build-usage.jsonl"


def _ledger_path() -> Path:
    return Path(os.environ.get("FORGE_USAGE_LOG", str(_DEFAULT_LEDGER)))


# --------------------------------------------------------------------------- #
# Pricing (USD per million tokens). Matched by substring on the model id so
# dated ids ("claude-sonnet-4-5-20250929") hit their family row. cache_read
# is billed at 0.1x input; cache_write at 1.25x input (Anthropic standard).
# --------------------------------------------------------------------------- #
#: Exact model id -> (input $/MTok, output $/MTok). Checked before the
#: substring table so a current model is never priced by family guess.
#: Source: the claude-api reference (cached 2026-06-24). Prices move — when
#: they do, this table is the one place to correct.
_PRICING_EXACT: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-3-opus-20240229": (15.0, 75.0),
}

#: Substring fallback for dated or unlisted ids within a known family.
#: NOTE the opus row: every current Opus is $5/$25, not the $15/$75 that
#: applied to Claude 3 Opus. Pricing the modern family by that old row
#: overstated every Opus call threefold.
_PRICING_PER_MTOK: list[tuple[str, float, float]] = [
    ("fable", 10.0, 50.0),
    ("mythos", 10.0, 50.0),
    ("opus", 5.0, 25.0),
    ("sonnet", 3.0, 15.0),
    ("haiku", 1.0, 5.0),
]
_DEFAULT_PRICE = (3.0, 15.0)  # unknown model → priced as sonnet-class


def is_priced(model: str | None) -> bool:
    """True when we hold a real price for this model.

    False means :func:`estimate_cost_usd` is returning a *placeholder*, not a
    measurement — every non-Anthropic model lands here. Report unpriced spend
    separately rather than folding a fabricated number into a total.
    """
    m = (model or "").lower()
    if m in _PRICING_EXACT:
        return True
    return any(needle in m for needle, _, _ in _PRICING_PER_MTOK)


def _price_for(model: str | None) -> tuple[float, float]:
    m = (model or "").lower()
    if m in _PRICING_EXACT:
        return _PRICING_EXACT[m]
    for needle, p_in, p_out in _PRICING_PER_MTOK:
        if needle in m:
            return (p_in, p_out)
    return _DEFAULT_PRICE


def estimate_cost_usd(model: str | None, usage: dict[str, Any] | None) -> float:
    """Token-count cost estimate. Zero when usage is absent/empty."""
    if not isinstance(usage, dict):
        return 0.0
    p_in, p_out = _price_for(model)
    inp = float(usage.get("input_tokens") or 0)
    out = float(usage.get("output_tokens") or 0)
    c_read = float(usage.get("cache_read_input_tokens") or 0)
    c_write = float(usage.get("cache_creation_input_tokens") or 0)
    cost = (
        inp * p_in
        + out * p_out
        + c_read * p_in * 0.1
        + c_write * p_in * 1.25
    ) / 1_000_000.0
    return round(cost, 6)


def record_usage(
    *,
    project: str,
    agent: str,
    model: str | None = None,
    usage: dict[str, Any] | None = None,
    sdk_cost_usd: float | None = None,
    duration_ms: int | None = None,
    num_turns: int | None = None,
    kind: str = "generation",
) -> None:
    """Append one agent-phase usage entry. Fail-open: never raises."""
    try:
        usage = usage if isinstance(usage, dict) else {}
        entry = {
            "ts": round(time.time(), 2),
            "project": str(project or "unknown"),
            "agent": str(agent or "agent"),
            "kind": kind,
            "model": model,
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_read_tokens": int(usage.get("cache_read_input_tokens") or 0),
            "cache_write_tokens": int(usage.get("cache_creation_input_tokens") or 0),
            "sdk_cost_usd": round(float(sdk_cost_usd or 0.0), 6),
            "est_cost_usd": estimate_cost_usd(model, usage),
            "duration_ms": int(duration_ms or 0),
            "num_turns": int(num_turns or 0),
        }
        # A row with no tokens AND no cost is noise (synthetic results) —
        # skip so the dashboard's event counts mean something.
        if not (entry["input_tokens"] or entry["output_tokens"]
                or entry["sdk_cost_usd"]):
            return
        path = _ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:  # noqa: BLE001 — accounting must never break a build
        logger.debug("[build-usage] record failed", exc_info=True)


def _entry_cost(e: dict[str, Any]) -> float:
    """SDK-reported cost wins when present; else the token estimate."""
    sdk = float(e.get("sdk_cost_usd") or 0.0)
    return sdk if sdk > 0 else float(e.get("est_cost_usd") or 0.0)


def read_ledger() -> list[dict[str, Any]]:
    path = _ledger_path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return out


def usage_summary() -> dict[str, Any]:
    """Aggregates the dashboard renders. Empty ledger → zeroed shape."""
    entries = read_ledger()

    totals = {
        "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
        "events": 0, "projects": 0, "estimated_events": 0,
    }
    by_project: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                 "events": 0, "last_ts": 0.0})
    by_agent: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                 "events": 0})
    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                 "events": 0})
    daily: dict[str, float] = defaultdict(float)

    for e in entries:
        cost = _entry_cost(e)
        inp = int(e.get("input_tokens") or 0)
        out = int(e.get("output_tokens") or 0)
        totals["cost_usd"] += cost
        totals["input_tokens"] += inp
        totals["output_tokens"] += out
        totals["cache_read_tokens"] += int(e.get("cache_read_tokens") or 0)
        totals["cache_write_tokens"] += int(e.get("cache_write_tokens") or 0)
        totals["events"] += 1
        if not float(e.get("sdk_cost_usd") or 0.0):
            totals["estimated_events"] += 1

        p = by_project[e.get("project") or "unknown"]
        p["cost_usd"] += cost; p["input_tokens"] += inp
        p["output_tokens"] += out; p["events"] += 1
        p["last_ts"] = max(p["last_ts"], float(e.get("ts") or 0))

        a = by_agent[e.get("agent") or "agent"]
        a["cost_usd"] += cost; a["input_tokens"] += inp
        a["output_tokens"] += out; a["events"] += 1

        m = by_model[e.get("model") or "unknown"]
        m["cost_usd"] += cost; m["input_tokens"] += inp
        m["output_tokens"] += out; m["events"] += 1

        day = datetime.fromtimestamp(
            float(e.get("ts") or 0), tz=timezone.utc).strftime("%Y-%m-%d")
        daily[day] += cost

    totals["cost_usd"] = round(totals["cost_usd"], 4)
    totals["projects"] = len(by_project)

    def _rows(d: dict, key_name: str) -> list[dict[str, Any]]:
        rows = [{key_name: k, **{kk: (round(vv, 4) if kk == "cost_usd" else vv)
                                 for kk, vv in v.items()}}
                for k, v in d.items()]
        rows.sort(key=lambda r: r["cost_usd"], reverse=True)
        return rows

    return {
        "totals": totals,
        "by_project": _rows(by_project, "project"),
        "by_agent": _rows(by_agent, "agent"),
        "by_model": _rows(by_model, "model"),
        "daily": sorted(
            ({"day": d, "cost_usd": round(c, 4)} for d, c in daily.items()),
            key=lambda r: r["day"],
        ),
    }

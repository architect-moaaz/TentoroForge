"""How an agent is doing in the connected development app: what it costs and how good it is. The platform's side.

The generated app keeps one row per assistant turn and answers ``GET /api/agent/insights`` (guarded like the live-run debug route: it
needs the platform's secret header, so the browser never sees it; the platform asks, then passes the answer on). This module asks
the app the same safe way Watch live does (services/agent_debug.py), then makes the numbers worth looking at:

* the app's JSON is treated as untrusted: every field is checked and clamped, unknown keys are dropped, lists are capped, and an odd
  value becomes a harmless zero or null instead of an error;
* ``cost``: an ESTIMATE in US dollars from list prices (the table below), never a guess for a model it has no price for;
* ``quality``: each rate comes with its counts, so the screen can say "3 of 40";
* ``tips``: a few plain-English suggestions from fixed rules, never blaming a person.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime
from typing import Any

from services import agent_debug
from services.agent_debug import DebugError

# ---------------------------------------------------------------------------
# prices
# ---------------------------------------------------------------------------

#: US dollars per MILLION tokens, (input, output), matched against the start of the model's name (the longest match wins).
#: A trailing ``$`` means "exactly this name" (so the plain alias ``claude-opus-4`` is priced, but a model that only starts the
#: same way, like a newer ``claude-opus-4-6``, is not mistaken for the oldest Opus 4).
#: These are LIST prices and they change: this table is an estimate, not a bill. Edit it here, or set the environment variable
#: FORGE_MODEL_PRICES to a JSON object like {"claude-sonnet-": [3, 15]} to add to or replace entries without a code change.
PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "claude-sonnet-": (3.0, 15.0),
    "claude-haiku-4": (1.0, 5.0),
    "claude-haiku-5": (1.0, 5.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-opus-4-0": (15.0, 75.0),
    "claude-opus-4-2025": (15.0, 75.0),  # the dated ids of the first Opus 4, e.g. claude-opus-4-20250514
    "claude-opus-4$": (15.0, 75.0),
}

COST_NOTE = "Estimated from list prices; your bill may differ."

# Limits on what the app may send: more than this is dropped, not an error.
MAX_DAYS = 92
MAX_MODELS = 20
MAX_TOOLS = 50
MAX_PROBLEMS = 50
MAX_TIPS = 5
_BIG = 10 ** 12

# Thresholds for the tips. Written as numbers here so they are easy to change.
TOOL_FAIL_MIN_CALLS = 5
TOOL_FAIL_RATE = 0.20
THUMBS_DOWN_MIN = 3
THUMBS_DOWN_RATE = 0.25
HANDOFF_MIN_TURNS = 10
HANDOFF_RATE = 0.30
ERROR_MIN_TURNS = 10
ERROR_RATE = 0.10
BLOCKED_MIN_TURNS = 10
BLOCKED_RATE = 0.20
SLOW_P95_MS = 30_000
INPUT_HEAVY_RATIO = 10
INPUT_HEAVY_MIN_TURNS = 5

REASONS = ("error", "blocked", "thumbs_down", "tool_failed", "handed_off", "slow")


def price_table() -> dict[str, tuple[float, float]]:
    """The built-in prices, with any from FORGE_MODEL_PRICES laid over them. A bad value there is ignored, never an error."""
    table = dict(PRICES_PER_MILLION)
    try:
        extra = json.loads(os.getenv("FORGE_MODEL_PRICES") or "{}")
    except ValueError:
        extra = {}
    if isinstance(extra, dict):
        for prefix, pair in extra.items():
            if (isinstance(prefix, str) and prefix and isinstance(pair, (list, tuple)) and len(pair) == 2
                    and all(isinstance(p, (int, float)) and not isinstance(p, bool) and math.isfinite(p) and p >= 0 for p in pair)):
                table[prefix] = (float(pair[0]), float(pair[1]))
    return table


def price_for(model: str, table: dict[str, tuple[float, float]] | None = None) -> tuple[float, float] | None:
    """(input, output) dollars per million tokens for this model, or None when the table has no entry for it."""
    name = (model or "").strip().lower()
    best: tuple[int, tuple[float, float]] | None = None
    for key, pair in (table if table is not None else price_table()).items():
        k = key.lower()
        hit = name == k[:-1] if k.endswith("$") else name.startswith(k)
        if hit and (best is None or len(k) > best[0]):
            best = (len(k), pair)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# taming what the app sent
# ---------------------------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _int(v: Any, hi: int = _BIG) -> int:
    """A whole number from 0 to ``hi``; anything else (text, a boolean, nan, a negative) is 0."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)):
        return 0
    return max(0, min(int(v), hi))


def _num(v: Any, hi: float = 1e9) -> float | None:
    """A finite number from 0 to ``hi``, or None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return max(0.0, min(float(v), hi))


def _text(v: Any, limit: int) -> str:
    """Text on one line, cut to ``limit`` characters. Anything that is not text is empty."""
    if not isinstance(v, str):
        return ""
    s = _CONTROL.sub(" ", v).strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _iso(v: Any) -> str | None:
    """A timestamp the app sent, only if it really is one; kept as sent."""
    if not isinstance(v, str) or len(v) > 40:
        return None
    try:
        datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return v.strip()


def _items(v: Any, cap: int) -> list[dict[str, Any]]:
    return [x for x in v[:cap] if isinstance(x, dict)] if isinstance(v, list) else []


def _pct(count: int, of: int) -> float | None:
    return round(100.0 * count / of, 1) if of > 0 else None


def _rate(count: int, of: int) -> dict[str, Any]:
    """A share with the counts behind it, so the screen can say "3 of 40"."""
    count = min(count, of)
    return {"pct": _pct(count, of), "count": count, "of": of}


def _clean_totals(raw: Any) -> dict[str, int]:
    t = raw if isinstance(raw, dict) else {}
    keys = ("conversations", "turns", "users", "inputTokens", "outputTokens", "toolCalls", "toolErrors", "blocked", "errors",
            "handedOff", "rated", "up", "down")
    out = {k: _int(t.get(k)) for k in keys}
    # a share can never be larger than what it is a share of
    for k in ("blocked", "errors", "handedOff"):
        out[k] = min(out[k], out["turns"])
    out["toolErrors"] = min(out["toolErrors"], out["toolCalls"])
    out["conversations"] = min(out["conversations"], out["turns"]) if out["turns"] else out["conversations"]
    out["rated"] = max(out["rated"], out["up"] + out["down"])
    return out


def _clean_models(raw: Any) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for m in _items(raw, MAX_MODELS * 3):
        name = _text(m.get("model"), 100) or "unknown"
        row = merged.setdefault(name, {"model": name, "turns": 0, "inputTokens": 0, "outputTokens": 0})
        row["turns"] += _int(m.get("turns"))
        row["inputTokens"] += _int(m.get("inputTokens"))
        row["outputTokens"] += _int(m.get("outputTokens"))
    # A turn that never reached a model (refused by the assistant's own rules before asking, or the AI call failed) used no tokens,
    # so it has nothing to cost and is not a model to price: left in, a real run showed a model called "unknown" and a tip asking
    # for its price.
    return [r for r in merged.values() if r["inputTokens"] or r["outputTokens"]][:MAX_MODELS]


def _clean_days(raw: Any) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for d in _items(raw, MAX_DAYS):
        day = d.get("day")
        if not isinstance(day, str) or not _DAY.match(day):
            continue
        row = {"day": day, **{k: _int(d.get(k)) for k in ("turns", "inputTokens", "outputTokens", "errors", "up", "down")}}
        seen[day] = row
    return [seen[k] for k in sorted(seen)]


def _clean_tools(raw: Any) -> list[dict[str, Any]]:
    out = []
    for t in _items(raw, MAX_TOOLS):
        name = _text(t.get("name"), 80)
        if not name:
            continue
        calls = _int(t.get("calls"))
        errors = min(_int(t.get("errors")), calls)
        avg = _num(t.get("avgMs"))
        out.append({"name": name, "calls": calls, "errors": errors, "avgMs": round(avg) if avg is not None else None,
                    "failurePct": _pct(errors, calls)})
    return out


def _clean_problems(raw: Any) -> list[dict[str, Any]]:
    out = []
    for p in _items(raw, MAX_PROBLEMS):
        reason = p.get("reason")
        out.append({
            "conversationId": _text(p.get("conversationId"), 80),
            "at": _iso(p.get("at")),
            "message": _text(p.get("message"), 300),
            "reason": reason if reason in REASONS else "other",
            "detail": _text(p.get("detail"), 300),
        })
    # newest first; a row with no usable time goes last
    out.sort(key=lambda p: p["at"] or "", reverse=True)
    return out


def _clean_handoffs(raw: Any) -> dict[str, Any]:
    h = raw if isinstance(raw, dict) else {}
    mins = _num(h.get("avgResolveMinutes"), 10_000_000)
    return {**{k: _int(h.get(k)) for k in ("total", "open", "claimed", "resolved")},
            "avgResolveMinutes": round(mins, 1) if mins is not None else None}


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------

def _usd(tokens_in: int, tokens_out: int, price: tuple[float, float]) -> float:
    return (tokens_in * price[0] + tokens_out * price[1]) / 1_000_000


def _cost(totals: dict[str, int], models: list[dict[str, Any]], days: list[dict[str, Any]]) -> dict[str, Any]:
    table = price_table()
    priced_models, unpriced, prices = [], [], []
    for m in models:
        price = price_for(m["model"], table)
        usd = round(_usd(m["inputTokens"], m["outputTokens"], price), 6) if price else None
        priced_models.append({**m, "usd": usd, "priced": price is not None})
        if price is None:
            unpriced.append(m["model"])
        else:
            prices.append((m, price))
    has_tokens = totals["inputTokens"] + totals["outputTokens"] > 0
    # Dollars are only ever the sum of models that have a price. With tokens but no priced model at all, the cost is unknown
    # (null), not zero.
    estimated = round(sum(m["usd"] for m in priced_models if m["priced"]), 6) if prices else (None if has_tokens else 0.0)
    per_chat = round(estimated / totals["conversations"], 6) if estimated is not None and totals["conversations"] else None
    per_turn = round(estimated / totals["turns"], 6) if estimated is not None and totals["turns"] else None

    # The app does not say which model each day's tokens went to, so a day's cost is its tokens at the average price of the
    # models used (weighted by how many tokens each used). Only worked out when every model has a price: otherwise unknown.
    if models and not unpriced:
        tin, tout = sum(m["inputTokens"] for m, _ in prices), sum(m["outputTokens"] for m, _ in prices)
        pin = sum(m["inputTokens"] * p[0] for m, p in prices) / tin if tin else 0.0
        pout = sum(m["outputTokens"] * p[1] for m, p in prices) / tout if tout else 0.0
        by_day = [{"day": d["day"], "usd": round(_usd(d["inputTokens"], d["outputTokens"], (pin, pout)), 6)} for d in days]
    else:
        by_day = [{"day": d["day"], "usd": None if has_tokens else 0.0} for d in days]
    return {
        "estimatedUsd": estimated, "partial": bool(unpriced) and bool(prices), "perChatUsd": per_chat, "perTurnUsd": per_turn,
        "byModel": priced_models, "byDay": by_day, "unpricedModels": unpriced, "note": COST_NOTE,
    }


# ---------------------------------------------------------------------------
# quality and tips
# ---------------------------------------------------------------------------

def _quality(t: dict[str, int], latency: dict[str, int | None]) -> dict[str, Any]:
    rated = t["rated"]
    p95 = latency.get("p95")
    return {
        # a turn that was not handed to a person was answered by the assistant alone
        "answeredWithoutPerson": _rate(t["turns"] - min(t["handedOff"], t["turns"]), t["turns"]),
        "thumbsUp": _rate(t["up"], rated),
        "errors": _rate(t["errors"], t["turns"]),
        "blocked": _rate(t["blocked"], t["turns"]),
        "toolFailures": _rate(t["toolErrors"], t["toolCalls"]),
        # how long a reply takes, not how many are slow: the app does not say how many passed any one limit
        "speed": {"p50Ms": latency.get("p50"), "p95Ms": p95, "avgMs": latency.get("avg"), "slow": bool(p95 and p95 > SLOW_P95_MS)},
    }


def _tips(t: dict[str, int], tools: list[dict[str, Any]], latency: dict[str, int | None], cost: dict[str, Any],
          days: int) -> list[dict[str, str]]:
    if t["turns"] == 0:
        return [{"id": "no-data", "severity": "info",
                 "text": f"No chats have been recorded in the last {days} days yet. Talk to the agent in your app, then press Refresh."}]
    tips: list[dict[str, str]] = []

    def add(id_: str, severity: str, text: str) -> None:
        tips.append({"id": id_, "severity": severity, "text": text})

    for tool in sorted(tools, key=lambda x: -(x["failurePct"] or 0)):
        if tool["calls"] >= TOOL_FAIL_MIN_CALLS and tool["errors"] / tool["calls"] > TOOL_FAIL_RATE:
            add(f"tool-failing:{tool['name']}", "warn",
                f"The tool {tool['name']} failed {tool['errors']} of {tool['calls']} times: look at its description or the app route it calls.")
    if t["errors"] / t["turns"] > ERROR_RATE and t["turns"] >= ERROR_MIN_TURNS:
        add("errors", "warn", f"{t['errors']} of {t['turns']} replies failed with an error. Open Chats that went wrong to see what happened.")
    if t["down"] >= THUMBS_DOWN_MIN and t["rated"] and t["down"] / t["rated"] >= THUMBS_DOWN_RATE:
        add("thumbs-down", "warn", f"{t['down']} of {t['rated']} rated replies got a thumbs down. Read those chats to see what was missing.")
    if t["turns"] >= HANDOFF_MIN_TURNS and t["handedOff"] / t["turns"] > HANDOFF_RATE:
        add("handoff-rate", "warn", f"{t['handedOff']} of {t['turns']} replies were passed to a person. Look at which questions the agent cannot answer yet.")
    p95 = latency.get("p95")
    if p95 and p95 > SLOW_P95_MS:
        add("slow", "warn", f"The slowest 1 in 20 replies took {p95 / 1000:.0f} seconds or more. Check which tool or model call is taking the time.")
    if t["turns"] >= BLOCKED_MIN_TURNS and t["blocked"] / t["turns"] > BLOCKED_RATE:
        add("blocked", "info", f"The assistant's rules refused {t['blocked']} of {t['turns']} messages. Check the rules are not stricter than you meant.")
    if t["turns"] >= INPUT_HEAVY_MIN_TURNS and t["outputTokens"] > 0 and t["inputTokens"] > INPUT_HEAVY_RATIO * t["outputTokens"]:
        add("input-heavy", "info", "Most of the cost is the assistant re-reading its instructions and history: shorten the instructions or memory.")
    if cost["unpricedModels"]:
        names = ", ".join(cost["unpricedModels"][:3])
        many = len(cost["unpricedModels"]) > 1
        add("unpriced-models", "info", f"No price is on file for {names}, so {'their' if many else 'its'} cost is not counted. "
                                       f"Only {'their' if many else 'its'} tokens are shown.")

    tips.sort(key=lambda x: x["severity"] != "warn")  # warnings first; the order within each stays as built
    return tips[:MAX_TIPS]


# ---------------------------------------------------------------------------
# the whole answer
# ---------------------------------------------------------------------------

def enrich(raw: Any, days: int) -> dict[str, Any]:
    """The app's insights, checked and clamped, with cost, quality and tips added. Raises ``DebugError`` only when what came back
    is not an insights answer at all (not an object, or no totals)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("totals"), dict):
        raise DebugError("Something answered, but it is not one of your apps: it did not answer the way a generated app does.")
    shown_days = _int(raw.get("days"), MAX_DAYS) or _int(days, MAX_DAYS) or 7
    totals = _clean_totals(raw["totals"])
    lat_raw = raw.get("latencyMs") if isinstance(raw.get("latencyMs"), dict) else {}
    latency: dict[str, int | None] = {}
    for k in ("p50", "p95", "avg"):
        v = _num(lat_raw.get(k))
        latency[k] = round(v) if v is not None else None
    by_day = _clean_days(raw.get("byDay"))
    models = _clean_models(raw.get("byModel"))
    tools = _clean_tools(raw.get("tools"))
    cost = _cost(totals, models, by_day)
    agent = _text(raw.get("agentId"), 100) or None
    out: dict[str, Any] = {
        "generatedAt": _iso(raw.get("generatedAt")), "days": shown_days, "agentId": agent,
        "since": _iso(raw.get("since")), "firstTurnAt": _iso(raw.get("firstTurnAt")),
        "totals": totals, "latencyMs": latency, "byDay": by_day,
        "byModel": [{k: m[k] for k in ("model", "turns", "inputTokens", "outputTokens")} for m in models],
        "tools": tools, "problems": _clean_problems(raw.get("problems")), "handoffs": _clean_handoffs(raw.get("handoffs")),
        "cost": cost, "quality": _quality(totals, latency), "tips": _tips(totals, tools, latency, cost, shown_days),
    }
    warning = _text(raw.get("warning"), 300)
    if warning:
        out["warning"] = warning
    return out


async def fetch(project_id: str, app_url: str, local_secret: str | None, days: int, agent_id: str | None = None) -> dict[str, Any]:
    """Ask the connected development app how its agent is doing. ``app_url`` is ``"tunnel"`` (the builder's computer, behind its reverse
    SSH tunnel: the platform's own address and the secret the connector made) or a localhost address typed by the builder (sent
    ``local_secret``, the one in the project's own app folder). Returns ``{"ok": True, "insights": ...}``, or ``{"ok": False, "reason":
    <one plain sentence>}``: never raises for an app that cannot be reached."""
    params: dict[str, Any] = {"days": max(1, min(int(days), 90))}
    if agent_id and agent_id.strip():
        params["agent"] = agent_id.strip()[:100]
    try:
        if (app_url or "").strip().lower() == "tunnel":
            url, secret, port = await agent_debug.tunnel_target(project_id)
            raw = await agent_debug.app_get_json(url, secret, "/api/agent/insights", params, trusted=True, app_port=port)
        else:
            raw = await agent_debug.app_get_json(app_url, local_secret, "/api/agent/insights", params)
        return {"ok": True, "insights": enrich(raw, params["days"])}
    except DebugError as e:
        return {"ok": False, "reason": str(e)}

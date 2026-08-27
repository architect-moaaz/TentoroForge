"""Plan Critic agent — Actor-Critic loop's Critic half.

The critic reviews a plan produced by the planner and returns a
structured verdict (approve / revise / reject), a list of gaps with
severity + evidence, and dimension scores. See
:mod:`services.plan_critic_prompt` for the prompt itself and the
five discipline layers.

This module is thin: it composes the prompt via the prompt-builder,
calls the LLM through the existing SDK boundary, parses the
JSON reply, and normalises the shape so downstream code can trust
every field. All parsing / validation is defensive — a malformed
reply degrades to `verdict: "approve"` with a note, so a broken
critic never blocks a generation.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable

from services.plan_critic_prompt import build_critic_prompt


logger = logging.getLogger(__name__)


CriticQueryFn = Callable[[str, str], Awaitable[str]]
"""LLM boundary — (system_prompt, user_message) → assistant text."""


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #

async def critique_plan(
    *,
    plan: dict[str, Any],
    user_brief: str,
    deterministic_violations: list[dict[str, Any]] | None = None,
    prior_critic_gaps: list[dict[str, Any]] | None = None,
    query_fn: CriticQueryFn | None = None,
) -> dict[str, Any]:
    """Return the critic's structured verdict for ``plan``.

    Shape guarantees::

        {
          "inferred_domain":     str,
          "inferred_confidence": float in [0, 1],
          "scores":              {entities, relationships, workflows,
                                  user_journeys, data_integrity},
          "verdict":             "approve" | "revise" | "reject",
          "gaps":                [{severity, lens, dimension,
                                   suggestion, evidence, confidence}],
          "future_considerations": [str],
          "kept":                  [str],
          "raw_reply":             str,   # for logging / debugging
        }

    Never raises. On any failure (LLM error, JSON parse error,
    schema mismatch) returns a defensive ``verdict: "approve"``
    envelope with a note under ``kept`` explaining the fallback.
    """
    prompt = build_critic_prompt(
        user_brief=user_brief,
        plan=plan,
        deterministic_violations=deterministic_violations,
        prior_critic_gaps=prior_critic_gaps,
    )

    fn = query_fn or _default_query
    try:
        raw_reply = await fn(prompt, "")
    except Exception as exc:  # noqa: BLE001 — critic must never crash the pipeline
        logger.exception("[plan-critic] LLM call failed; defaulting to approve")
        return _fallback_verdict(f"critic LLM error: {exc!r}")

    parsed = _parse_reply(raw_reply)
    if parsed is None:
        logger.warning(
            "[plan-critic] could not parse critic reply; defaulting to approve. "
            "First 200 chars: %s",
            (raw_reply or "")[:200],
        )
        return _fallback_verdict("critic reply not parseable")

    normalised = _normalise(parsed)
    normalised["raw_reply"] = raw_reply
    logger.info(
        "[plan-critic] verdict=%s blockers=%d important=%d nice=%d domain=%s",
        normalised["verdict"],
        sum(1 for g in normalised["gaps"] if g["severity"] == "blocker"),
        sum(1 for g in normalised["gaps"] if g["severity"] == "important"),
        sum(1 for g in normalised["gaps"] if g["severity"] == "nice"),
        normalised["inferred_domain"][:60],
    )
    return normalised


# --------------------------------------------------------------------------- #
# Parsing — tolerant to fenced code blocks + prose wrappers
# --------------------------------------------------------------------------- #

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _parse_reply(text: str) -> dict[str, Any] | None:
    """Extract the JSON object from a critic reply that may be
    wrapped in a fenced code block or prefixed with prose."""
    if not isinstance(text, str) or not text.strip():
        return None
    stripped = text.strip()

    # 1. Straight JSON object.
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # 2. Fenced ```json { ... } ```
    m = _JSON_FENCE_RE.search(stripped)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Last-resort: locate the outermost balanced-brace object.
    start = stripped.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(stripped)):
        c = stripped[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stripped[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# --------------------------------------------------------------------------- #
# Normalisation — enforce the caps and default the shape
# --------------------------------------------------------------------------- #

_VALID_VERDICTS = {"approve", "revise", "reject"}
_VALID_SEVERITIES = ("blocker", "important", "nice")
_SEVERITY_CAP = {"blocker": 3, "important": 5, "nice": 3}
_VALID_LENSES = {"business", "architecture"}
_VALID_DIMENSIONS = {
    "entities", "relationships", "workflows",
    "user_journeys", "data_integrity",
}
_SCORE_KEYS = tuple(_VALID_DIMENSIONS)


def _normalise(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce a critic reply to the guaranteed shape, applying the
    hard caps by severity (over-emitted lists get trimmed)."""
    out: dict[str, Any] = {
        "inferred_domain": _as_str(raw.get("inferred_domain"), "unknown domain"),
        "inferred_confidence": _clamp01(raw.get("inferred_confidence"), 0.5),
        "scores": _normalise_scores(raw.get("scores")),
        "verdict": _normalise_verdict(raw.get("verdict")),
        "gaps": _normalise_gaps(raw.get("gaps")),
        "future_considerations": _normalise_future(raw.get("future_considerations")),
        "kept": _normalise_kept(raw.get("kept")),
    }
    # If the LLM returned verdict="approve" but blockers exist,
    # override to revise — the LLM was inconsistent with its own
    # rules and we prefer the safer read.
    n_blockers = sum(1 for g in out["gaps"] if g["severity"] == "blocker")
    if out["verdict"] == "approve" and n_blockers > 0:
        out["verdict"] = "revise"
    return out


def _normalise_scores(raw: Any) -> dict[str, int]:
    scores: dict[str, int] = {}
    if isinstance(raw, dict):
        for k in _SCORE_KEYS:
            v = raw.get(k)
            if isinstance(v, (int, float)):
                scores[k] = max(0, min(10, int(v)))
    for k in _SCORE_KEYS:
        scores.setdefault(k, 5)  # neutral default
    return scores


def _normalise_verdict(raw: Any) -> str:
    v = str(raw or "").strip().lower()
    if v in _VALID_VERDICTS:
        return v
    return "revise"  # unknown → play it safe (retry)


def _normalise_gaps(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for g in raw:
        if not isinstance(g, dict):
            continue
        sev = str(g.get("severity", "")).strip().lower()
        if sev not in _VALID_SEVERITIES:
            continue
        suggestion = _as_str(g.get("suggestion"), "").strip()
        evidence = _as_str(g.get("evidence"), "").strip()
        if not suggestion or not evidence:
            continue  # rule 4 — no evidence, drop
        lens = str(g.get("lens", "")).strip().lower()
        if lens not in _VALID_LENSES:
            lens = "business"
        dim = str(g.get("dimension", "")).strip().lower()
        if dim not in _VALID_DIMENSIONS:
            dim = "entities"
        cleaned.append({
            "severity": sev,
            "lens": lens,
            "dimension": dim,
            "suggestion": suggestion[:500],
            "evidence": evidence[:800],
            "confidence": _clamp01(g.get("confidence"), 0.7),
        })

    # Apply hard caps by severity (rule 3).
    bucketed: dict[str, list[dict[str, Any]]] = {s: [] for s in _VALID_SEVERITIES}
    for g in cleaned:
        bucketed[g["severity"]].append(g)
    out: list[dict[str, Any]] = []
    for sev in _VALID_SEVERITIES:
        cap = _SEVERITY_CAP[sev]
        # Prefer high-confidence entries when trimming.
        sorted_bucket = sorted(bucketed[sev],
                                key=lambda g: g["confidence"],
                                reverse=True)
        out.extend(sorted_bucket[:cap])
    return out


def _normalise_future(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip()[:200] for x in raw if isinstance(x, str) and x.strip()][:3]


def _normalise_kept(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip()[:200] for x in raw if isinstance(x, str) and x.strip()][:3]


def _clamp01(v: Any, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, f))


def _as_str(v: Any, default: str) -> str:
    return v if isinstance(v, str) and v.strip() else default


# --------------------------------------------------------------------------- #
# Fallback verdict — used when the critic can't be trusted
# --------------------------------------------------------------------------- #

def _fallback_verdict(reason: str) -> dict[str, Any]:
    """Never block a generation on a broken critic — default to
    approve so downstream code keeps flowing. The reason is
    logged and surfaced under ``kept`` for observability."""
    return {
        "inferred_domain": "unknown",
        "inferred_confidence": 0.0,
        "scores": {k: 5 for k in _SCORE_KEYS},
        "verdict": "approve",
        "gaps": [],
        "future_considerations": [],
        "kept": [f"critic-skipped: {reason}"],
        "raw_reply": "",
    }


# --------------------------------------------------------------------------- #
# Default LLM boundary — the same SDK the planner uses
# --------------------------------------------------------------------------- #

async def _default_query(system_prompt: str, user_message: str) -> str:
    """Call the Anthropic SDK directly — same shape run_planner_oneshot
    uses (client.messages.create with model + system + one user turn).
    The critic is a single-turn reviewer with no tools, so the raw
    SDK is a better fit than the agent tool-loop SDK."""
    import asyncio
    import os

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("plan_critic requires ANTHROPIC_API_KEY")

    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
    client = llm_client.AsyncAnthropic(api_key=api_key)

    msg = await asyncio.wait_for(
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8000,
            # The critic prompt is the WHOLE thing — persona, rules,
            # passes, plan, brief — so pass it as the user turn.
            # A short `system` anchors the JSON-only contract without
            # duplicating the persona (which is already at the top of
            # the user message).
            system=(
                "You are a plan critic. Respond with strict JSON per "
                "the OUTPUT CONTRACT in the user message. No prose "
                "before or after the JSON object."
            ),
            messages=[{"role": "user", "content": system_prompt}],
        ),
        timeout=180.0,
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text")).strip()

"""Expand a sparse user prompt into a rich domain narrative.

Motivation
----------
The planner authors what its plan schema has slots for. When the input
prompt is one paragraph, the planner produces a shallow app. When the
input is a rich domain doc (actors, journeys, per-stage rules, edge
cases, industry patterns), the planner picks up more detail — even
though the plan schema hasn't changed. The bottleneck is the *brief*,
not the schema.

This module inserts a *narrative expansion* pass BEFORE the planner
runs. It takes:
  * the user's original prompt (may be one sentence)
  * the structured brief from discovery (actors, journeys — if any)

...and produces a Markdown domain narrative that reads like the kind
of doc a senior product manager would write: primary users, end-to-
end journeys, stage-by-stage screens, key system rules, dashboard
metrics. Free-form — nothing here is validated against the plan
schema. The planner receives it as pure context.

Contract
--------
The pass is *purely additive*. It never mutates the brief, never
overrides the user prompt, never causes generation to fail. Any error
in the LLM call returns an empty string so the planner still runs on
the original inputs (byte-unchanged fallback).

Env gate
--------
Off by default. Set ``FORGE_NARRATIVE_EXPANSION=1`` to enable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_NARRATIVE_SYSTEM_PROMPT = """You are a senior product designer helping a
domain expert scope out an internal application. You will receive a
short user prompt (usually 1-3 sentences describing the app they want)
and, if available, a structured brief listing the actors and journeys
discovery has already extracted.

Your job is to produce a comprehensive DOMAIN NARRATIVE — a Markdown
document (about 200-600 lines) that describes:

  1. PRIMARY USERS — every role that touches the system, with a
     one-line responsibility for each.
  2. END-TO-END JOURNEYS — for each primary role, a stage-by-stage
     narrative from discovery through completion. Every stage names:
       - the user's action
       - the fields/inputs on that screen
       - the system's response (validations, notifications, transitions)
       - edge cases (rescheduling, rejection, override, retry)
  3. KEY SCREENS — one bulleted list per role.
  4. IMPORTANT SYSTEM RULES — the invariants (immutability, RBAC,
     stage gating, duplicate detection, audit) the app must enforce.
  5. DASHBOARD METRICS — the numbers each role's landing screen
     should surface, and why.

Style rules:
  * Write in the *domain's* vocabulary — if the prompt is an ATS,
    say "candidate", "recruiter", "recruitment drive", not "user
    A" / "user B".
  * Cover the entire journey, including edge cases the prompt does
    NOT mention. Rescheduling, offer decline, background verification
    failure, duplicate applications — infer them from industry
    convention when the prompt is silent.
  * Do NOT invent components, page layouts, database columns, or
    workflow node types. This is a domain doc, not a plan.
  * Prefer bullet lists and short headings over prose walls.
  * If the structured brief already names actors/journeys, expand
    those. Do not contradict them.

Output ONLY the Markdown narrative. No preamble, no code fences, no
"Here is..." intro — start directly with the first heading."""


def build_narrative_prompt(
    user_prompt: str,
    structured_brief: dict[str, Any] | None,
) -> str:
    """Return the user-role prompt for the narrative expansion call.

    Pure function — no IO, no LLM. Tests exercise this directly to
    confirm the brief information is faithfully passed to the model.
    """
    parts: list[str] = []
    parts.append("USER PROMPT (verbatim):")
    parts.append(user_prompt.strip() or "(empty)")

    if structured_brief:
        parts.append("")
        parts.append(
            "STRUCTURED BRIEF FROM DISCOVERY (frozen contract — expand, "
            "do not contradict):"
        )
        parts.append("```json")
        parts.append(json.dumps(structured_brief, indent=2, sort_keys=True))
        parts.append("```")

    parts.append("")
    parts.append(
        "Produce the DOMAIN NARRATIVE now. Cover every role, every "
        "journey stage, every edge case. Use the domain's vocabulary."
    )
    return "\n".join(parts)


async def expand_prompt_to_narrative(
    user_prompt: str,
    structured_brief: dict[str, Any] | None = None,
    *,
    timeout_seconds: int = 300,
    _client: Any = None,
    _model: str = "claude-sonnet-4-6",
    emit_fn: Any = None,
) -> str:
    """Run the narrative expansion LLM call. Returns Markdown or "".

    Never raises. Any transport or API failure returns an empty string
    so the planner continues on the original brief (byte-unchanged
    fallback path). Callers that want to detect a failure explicitly
    can check the return value for emptiness.

    ``_client`` is an injectable Anthropic-like client for tests. When
    absent, a real ``anthropic.AsyncAnthropic`` is constructed from
    ``ANTHROPIC_API_KEY``; if that env var is unset, the pass no-ops.
    """
    if not (user_prompt and user_prompt.strip()):
        return ""

    prompt_text = build_narrative_prompt(user_prompt, structured_brief)

    client = _client
    if client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.info("[narrative] ANTHROPIC_API_KEY not set — skipping expansion")
            return ""
        try:
            from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
            client = llm_client.AsyncAnthropic(api_key=api_key)
        except Exception:  # noqa: BLE001
            logger.exception("[narrative] anthropic SDK unavailable — skipping")
            return ""

    try:
        # Stream the response so the user sees typewriter-style progress
        # SSE events during the ~30-90s Sonnet call. Falls back to a
        # single-await create() when the client doesn't support streaming
        # (test fakes without a .messages.stream method).
        from services.streaming_llm import stream_and_emit
        if hasattr(client, "messages") and hasattr(client.messages, "stream"):
            text = await stream_and_emit(
                client,
                stage="narrative_expansion",
                model=_model,
                max_tokens=16000,
                system=_NARRATIVE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt_text}],
                timeout_seconds=timeout_seconds,
                emit_fn=emit_fn,
                started_text="Expanding domain narrative…",
            )
        else:
            msg = await asyncio.wait_for(
                client.messages.create(
                    model=_model,
                    max_tokens=16000,
                    system=_NARRATIVE_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt_text}],
                ),
                timeout=timeout_seconds,
            )
            text = "".join(
                getattr(b, "text", "") for b in getattr(msg, "content", []) or []
            )
    except Exception:  # noqa: BLE001
        logger.exception("[narrative] LLM call failed — planner continues without")
        return ""

    return text.strip()


# ────────────────────────────────────────────────────────────
# Persistence
# ────────────────────────────────────────────────────────────

NARRATIVE_FILENAME = "domain-narrative.md"


def persist_narrative(output_dir: str | Path, narrative: str) -> Path | None:
    """Write the narrative to ``<output_dir>/contracts/domain-narrative.md``.

    Silent on empty narrative (nothing to persist). Returns the Path
    written, or None on empty/error.
    """
    if not narrative or not narrative.strip():
        return None
    try:
        root = Path(output_dir) / "contracts"
        root.mkdir(parents=True, exist_ok=True)
        path = root / NARRATIVE_FILENAME
        path.write_text(narrative, encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001
        logger.exception("[narrative] persist failed")
        return None


def read_narrative(output_dir: str | Path) -> str:
    """Read the persisted narrative back, or '' if missing/unreadable."""
    path = Path(output_dir) / "contracts" / NARRATIVE_FILENAME
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return ""


# ────────────────────────────────────────────────────────────
# Planner-brief block
# ────────────────────────────────────────────────────────────

def render_narrative_block(narrative: str) -> str:
    """Wrap the narrative in a header/footer so the planner can spot
    it as extended-context (not authoritative contract).

    Empty narrative renders to '' so callers can unconditionally
    prepend without changing the byte-shape of the planner input on
    the disabled path.
    """
    body = (narrative or "").strip()
    if not body:
        return ""
    return (
        "# DOMAIN NARRATIVE (rich context for the planner)\n\n"
        "The following is extended context expanded from the user's "
        "original prompt. Treat it as GUIDANCE — actors, journeys, "
        "screens, and system rules described here should shape the "
        "plan you emit. It is NOT an authoritative contract (unlike "
        "an AUTHORITATIVE INPUTS block, if one is present above); "
        "you may prune or reorder to fit the plan schema.\n\n"
        f"{body}"
    )


def is_narrative_enabled() -> bool:
    """One-liner env-gate check so callers don't sprinkle os.getenv
    everywhere."""
    return os.getenv("FORGE_NARRATIVE_EXPANSION", "").lower() in (
        "1", "true", "yes", "on",
    )

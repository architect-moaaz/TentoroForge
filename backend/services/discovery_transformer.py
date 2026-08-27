"""Turn a discovery conversation into a StructuredBrief.

Discovery is the LLM's job to run — it's a conversation. Structuring
is a DIFFERENT job: given the transcript, extract the actors and user
journeys the user described, then emit strict JSON. Splitting into two
prompts (conversation vs extraction) keeps each optimized for its task
and lets us iterate the extractor without touching the conversation.

Contract
--------
:func:`transform_discovery` accepts a discovery session's transcript
(prose, list of turns, or an already-populated brief dict) and returns
a :class:`services.structured_brief.StructuredBrief`.

Failure modes are handled by returning an EMPTY brief rather than
raising — the caller falls through to legacy authoring instead of
crashing generation.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Awaitable, Callable, Iterable

from services.structured_brief import (
    Actor, ActorOnboarding, BriefParseError, Journey, JourneyStep,
    StructuredBrief, VALID_ONBOARDING_SOURCES,
)


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

QueryFn = Callable[[str, str], Awaitable[str]]
"""LLM boundary: ``(system_prompt, user_prompt) -> str``. Kept abstract so
tests inject deterministic stubs without touching the network."""


async def transform_discovery(
    session_input: Any,
    *,
    query_fn: QueryFn | None = None,
    max_retries: int = 1,
) -> StructuredBrief:
    """Extract a :class:`StructuredBrief` from a discovery session.

    ``session_input`` may be:
      * a string — the raw transcript
      * a list of turns — each ``{role, content}`` or plain str
      * a dict — a partial brief the transformer should structure

    Returns an empty ``StructuredBrief`` when the LLM output is
    unusable after ``max_retries``. Never raises — the planner's
    legacy path is the graceful fallback.
    """
    transcript = _normalize_transcript(session_input)
    if not transcript.strip():
        return StructuredBrief()

    fn = query_fn or _default_query
    system_prompt = _build_system_prompt()

    prior_errors: list[str] = []
    for attempt in range(max_retries + 1):
        user_prompt = _build_user_prompt(transcript, prior_errors)
        try:
            raw = await fn(system_prompt, user_prompt)
        except Exception as exc:  # noqa: BLE001
            logger.exception("discovery_transformer: LLM call crashed")
            prior_errors.append(f"LLM call crashed: {type(exc).__name__}: {exc}")
            continue

        try:
            payload = _extract_json(raw)
        except ValueError as exc:
            prior_errors.append(str(exc))
            continue

        try:
            brief = StructuredBrief.parse(payload)
        except BriefParseError as exc:
            prior_errors.append(f"schema mismatch: {exc}")
            continue

        if not brief.is_empty():
            return brief
        prior_errors.append("brief has no actors and no journeys")

    logger.warning("discovery_transformer: failed after %d attempt(s): %s",
                   max_retries + 1, prior_errors[-1] if prior_errors else "unknown")
    return StructuredBrief()


# --------------------------------------------------------------------------- #
# Prompt construction — the whole design lives here
# --------------------------------------------------------------------------- #

def _build_system_prompt() -> str:
    """The transformer prompt teaches: extract, don't invent.

    We name the exact JSON schema, give a rich example, and forbid the
    LLM from adding facts it can't cite in the transcript."""
    return f"""You are a discovery-transformer. Your job is to turn a
user's conversation with a product discovery agent into a strict
STRUCTURED BRIEF — one JSON object matching the schema below.

RULES:
1. EXTRACT ONLY. If the transcript doesn't establish an actor, journey
   step, or domain term, DO NOT invent one. Leave the field empty or
   the actor absent.
2. VOCABULARY FIDELITY. Use the user's exact nouns. If they said
   "Candidate", write "Candidate" — not "Applicant" or "User". If they
   said "Drive", keep "Drive" — not "campaign".
3. AMBIGUITY → open_questions. When the transcript is unclear on a
   real decision the plan needs (e.g., "sometimes recruiter, sometimes
   admin does X"), add an entry to `open_questions` rather than
   picking one silently.
4. ONBOARDING SOURCE must be exactly one of:
   {sorted(VALID_ONBOARDING_SOURCES)!r}
   - "self_signup":  actor signs up on the public /signup page
   - "invited_by":   another actor provisions them from inside the app
                     (must set `invited_by` to that actor's name)
   - "platform_org": actor is pre-provisioned via the Forge organization
5. JOURNEYS have STEPS. Each step is: {{actor, action, page, workflow?,
   outcome}}. The `page` is a URL route like "/apply" or "/pipeline/[id]"
   — invent one only if the transcript makes it obvious what page hosts
   the action. `workflow` names a workflow the step fires (e.g.
   "ShortlistCandidate") if the transcript describes a system action.
6. OUTPUT: exactly one JSON object. No prose, no markdown fences, no
   commentary. First character `{{`, last character `}}`.

OUTPUT SCHEMA:
{{
  "overview":       "one-sentence description of the app",
  "domain":         "domain slug like 'aviation.recruitment' or 'healthcare'",
  "actors": [
    {{
      "name": "Candidate",
      "role": "candidate",
      "onboarding": {{ "source": "self_signup", "gate": "public" }},
      "responsibilities": ["Apply for roles", "Upload CV"]
    }}
  ],
  "user_journeys": [
    {{
      "name": "Hire a cabin crew candidate",
      "primary_actor": "Candidate",
      "trigger": "New role opens on a Drive",
      "steps": [
        {{
          "actor": "Candidate",
          "action": "Apply for a role",
          "page": "/apply",
          "outcome": "Application(status=pending) created"
        }},
        {{
          "actor": "Recruiter",
          "action": "Review CV",
          "page": "/pipeline/[id]",
          "workflow": "ShortlistCandidate",
          "outcome": "Application(status=shortlisted)"
        }}
      ]
    }}
  ],
  "domain_terms":   ["Drive", "CV", "Shortlist"],
  "open_questions": ["Is there a screening stage between pending and shortlisted?"]
}}
"""


def _build_user_prompt(transcript: str, prior_errors: list[str]) -> str:
    """The user message wraps the transcript + (on retry) the last error."""
    parts: list[str] = []
    if prior_errors:
        parts.append(
            "Your previous attempt failed with:\n" + prior_errors[-1] +
            "\nCorrect it and emit valid JSON matching the schema.\n"
        )
    parts.append("Extract a structured brief from this discovery transcript:")
    parts.append("")
    parts.append(transcript)
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# LLM boundary
# --------------------------------------------------------------------------- #

async def _default_query(system_prompt: str, user_prompt: str) -> str:
    """Real LLM call. Kept behind an env-flag so tests never hit the wire."""
    from services.llm_client import AsyncAnthropic  # LangGraph migration (LG-1)
    client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = await client.messages.create(
        model=os.environ.get("FORGE_TRANSFORMER_MODEL", "claude-sonnet-4-6"),
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=0.0,
    )
    return "".join(
        block.text for block in msg.content if getattr(block, "type", "") == "text"
    )


# --------------------------------------------------------------------------- #
# Transcript normalization + JSON extraction
# --------------------------------------------------------------------------- #

def _normalize_transcript(source: Any) -> str:
    """Coerce whatever the caller had lying around into one prose blob."""
    if source is None:
        return ""
    if isinstance(source, str):
        return source
    if isinstance(source, dict):
        # A partial brief — reshape as prose so the LLM can restructure it.
        return json.dumps(source, indent=2, sort_keys=True)
    if isinstance(source, (list, tuple)):
        lines: list[str] = []
        for turn in source:
            if isinstance(turn, dict):
                role = turn.get("role") or "user"
                content = turn.get("content") or ""
                lines.append(f"{role}: {content}")
            else:
                lines.append(str(turn))
        return "\n".join(lines)
    return str(source)


def _extract_json(raw: str) -> dict:
    """Peel a JSON object out of the LLM's response.

    The prompt forbids fences and prose but LLMs still ignore that.
    Strip everything before the first ``{`` and after the last ``}``
    before parsing so those failures don't break the pipeline."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("LLM output was empty")
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM output has no JSON object")
    blob = raw[start : end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc

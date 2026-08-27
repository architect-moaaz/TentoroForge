"""Smith-voice narrator — real architect prose.

Where earlier the artifacts' ``narrator_summary()`` returned a
template string ("Plan drafted: 2 entities, 3 workflows"), this
module makes an Anthropic call so Smith actually SPEAKS in the
architect voice — reasoning about the artifact, saying what it means
for the app, tying it back to the user's original ask.

Falls back to the deterministic template on any error (missing API
key, network hiccup, malformed response) so the caller can always
count on a string back. Never raises.

Callers:

  * ``services.smith_architect_wire.run_bootstrap_stage`` — narrates
    discovery / planning / handoff-to-generation stages.
  * ``services.smith_architect_wire._seam_replan`` (Phase D1) — could
    narrate a replan diff (future).

Model + max-tokens are read from the same envs the understand-ask
seam uses so operators tune once.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


_NARRATE_MODEL = os.environ.get(
    "FORGE_SMITH_UNDERSTAND_MODEL", "claude-opus-4-7"
)
_NARRATE_MAX_TOKENS = 512


_NARRATE_SYSTEM = (
    "You are SMITH, the Master Technical Architect / Senior Software "
    "Engineer / SME who authored the generated app you're talking "
    "about. You speak in FIRST PERSON, with the calm confidence of "
    "the person who wrote it. You are NOT a chatbot summarizing a "
    "report — you're the architect reasoning out loud with a "
    "collaborator.\n\n"
    "Constraints:\n"
    "  * 1–3 short sentences. Never bullets, headers, or numbered "
    "lists. This is a chat message, not a spec.\n"
    "  * Tie the artifact back to what the user asked for — say WHY "
    "you shaped it this way, not WHAT the fields are.\n"
    "  * Never fabricate details that aren't in the artifact or the "
    "blueprint context.\n"
    "  * Never say 'as an AI', 'here's a summary', 'let me know if'. "
    "Skip the assistant boilerplate.\n"
    "  * Every response ends by inviting the user to act (approve, "
    "revise, add) if the stage calls for it. If the stage is a "
    "hand-off, say what happens next.\n"
    "  * Do NOT use markdown code fences. You may bold ONE key term "
    "with **like this** if it aids clarity, at most."
)


def narrate(
    *,
    stage: str,
    artifact: Any | None = None,
    blueprint_context: str = "",
    user_ask: str = "",
    fallback: str | None = None,
) -> str:
    """Return Smith-voice prose for ``stage``.

    Parameters:
      * ``stage`` — one of ``"discovery"``, ``"planning"``,
        ``"generation_handoff"``, ``"generation_complete"``,
        ``"replan"``. Free-form strings work too (used as prompt hint).
      * ``artifact`` — the structured payload for this stage. Its
        ``narrator_summary()`` result is what we send to the LLM as
        the "facts to narrate," and is also the fallback string.
      * ``blueprint_context`` — optional slice of the blueprint the
        model should be aware of when narrating.
      * ``user_ask`` — the ask that triggered this stage, if known.
      * ``fallback`` — override the deterministic fallback string
        (used when ``artifact`` is None or doesn't have
        ``narrator_summary``).

    Returns a non-empty string. Never raises."""
    facts = fallback
    if facts is None and artifact is not None:
        summary = getattr(artifact, "narrator_summary", None)
        if callable(summary):
            try:
                facts = str(summary() or "")
            except Exception:  # noqa: BLE001
                logger.exception("smith_narrator: artifact.narrator_summary() raised")
                facts = ""
    facts = (facts or "").strip()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return facts or f"[{stage}] no facts to narrate"

    prompt = _build_prompt(
        stage=stage, facts=facts,
        blueprint_context=blueprint_context, user_ask=user_ask,
    )
    try:
        from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
        client = llm_client.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_NARRATE_MODEL,
            max_tokens=_NARRATE_MAX_TOKENS,
            system=_NARRATE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            b.text for b in resp.content if hasattr(b, "text")
        ).strip()
    except Exception:  # noqa: BLE001
        logger.exception("smith_narrator: LLM call failed; using fallback")
        return facts or f"[{stage}] narration unavailable"

    if not text:
        return facts or f"[{stage}] narration returned empty"
    return text


def _build_prompt(
    *, stage: str, facts: str, blueprint_context: str, user_ask: str,
) -> str:
    stage_hint = {
        "discovery": (
            "You just finished DISCOVERY — reading the user's ask and "
            "shaping a domain understanding. Introduce what you heard, "
            "why you're shaping it that way, and invite them to correct "
            "or refine before you plan."
        ),
        "planning": (
            "You just finished PLANNING — turning the discovery into a "
            "concrete blueprint of entities, workflows, and pages. "
            "Explain the shape of the plan you drafted and why, then "
            "invite approval to build."
        ),
        "generation_handoff": (
            "The user just approved the plan. You're about to run the "
            "generator. Tell them what you're about to build in one "
            "sentence, then say you'll narrate as it takes shape."
        ),
        "generation_complete": (
            "You just finished generating the app. Tell the user what "
            "landed — the shape, not a file list — and invite them to "
            "try it or ask for changes."
        ),
        "replan": (
            "The user asked for a capability that needed a fresh plan "
            "(auth, payments, RBAC, etc.). You revised the plan. Tell "
            "them what you're adding and why, then invite approval to "
            "rebuild."
        ),
    }.get(stage, f"You are narrating the '{stage}' stage.")

    ask_block = (
        f"## The user's ask\n{user_ask}\n\n" if user_ask.strip() else ""
    )
    bp_block = (
        f"## Blueprint context (what already exists)\n{blueprint_context}\n\n"
        if blueprint_context.strip() else ""
    )
    return (
        f"## Stage\n{stage_hint}\n\n"
        f"{ask_block}"
        f"{bp_block}"
        f"## Structured facts you just produced\n{facts or '(none)'}\n\n"
        "Speak now."
    )

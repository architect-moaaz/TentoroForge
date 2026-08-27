"""Render a StructuredBrief as the AUTHORITATIVE INPUTS block the planner
sees in its user message.

The block is the *contract* between discovery and planning. Its shape is
deliberately stable: any change here needs a matching update to the
planner's STRUCTURED-INPUT MODE prompt, and to the plan validator's
authoritative rules. Keep the text plain, the sections labelled, and
the ordering fixed.

Design notes
------------
* Empty sections are DROPPED, not rendered with "(none)" placeholders.
  LLMs pattern-match on structure — an empty section reads as noise;
  no section reads as "the discovery didn't establish this."
* Section markers use the same triple-line separator style as the
  planner's REVISE MODE block, so the model already knows this is a
  "pre-instruction" region.
* Actor rows are rendered one per line with the same shape the plan's
  ``actors[]`` uses — the planner can literally copy them into its
  output.
"""
from __future__ import annotations

from typing import Any

from services.structured_brief import (
    Actor, Journey, JourneyStep, JourneyVariation, StructuredBrief,
)


SEPARATOR = "═" * 67


def render_authoritative_block(brief: StructuredBrief) -> str:
    """Turn a ``StructuredBrief`` into the text block the planner sees.

    Returns the empty string when the brief has nothing structural to
    contribute (no actors + no journeys) so the caller can safely
    concatenate the result without a nullness check."""
    if not isinstance(brief, StructuredBrief):
        # Defensive: caller passed a dict or JSON. Try to parse. On failure,
        # render nothing rather than crash the planner call.
        try:
            brief = StructuredBrief.parse(brief)
        except Exception:  # noqa: BLE001
            return ""

    if brief.is_empty():
        return ""

    parts: list[str] = [
        SEPARATOR,
        "AUTHORITATIVE INPUTS — preserve verbatim, build around them",
        SEPARATOR,
        "",
    ]

    if brief.overview:
        parts.append(f"## Overview")
        parts.append(brief.overview)
        parts.append("")

    if brief.actors:
        parts.append(f"## Actors  ({len(brief.actors)})")
        for a in brief.actors:
            parts.append(_render_actor_row(a))
        parts.append("")

    if brief.user_journeys:
        parts.append(f"## User Journeys  ({len(brief.user_journeys)})")
        for i, j in enumerate(brief.user_journeys, 1):
            parts.extend(_render_journey_block(j, index=i))
        parts.append("")

    if brief.domain_terms:
        parts.append("## Domain vocabulary  (use these exact terms)")
        parts.append(", ".join(brief.domain_terms))
        parts.append("")

    if brief.open_questions:
        parts.append(f"## Open questions  ({len(brief.open_questions)})")
        parts.append("Resolve each with senior-architect judgment; record the "
                     "resolution in `assumptions[]`.")
        for q in brief.open_questions:
            parts.append(f"  - {q}")
        parts.append("")

    parts.extend([
        SEPARATOR,
        "",
        "Your job: fill in everything the authoritative inputs don't cover — "
        "entities, additional pages (dashboards, settings, list pages), seed "
        "data, other workflows. In particular:",
        "",
        "  * Every page named in a journey step MUST appear in `pages[]` at "
        "its exact route.",
        "  * Every workflow named in a journey step MUST appear in "
        "`workflows[]` with the described outcome.",
        "  * `User.role.enum_values` MUST match the actor role list verbatim.",
        "  * Do NOT add actors or change onboarding sources.",
        "  * Resolve every open question and record the resolution in "
        "`assumptions[]`.",
        "",
        "Emit the plan in your normal JSON output schema.",
    ])

    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Section-level renderers
# --------------------------------------------------------------------------- #

def _render_actor_row(a: Actor) -> str:
    ob = a.onboarding
    tag = f"onboarding={ob.source or 'unspecified'}"
    if ob.source == "invited_by" and ob.invited_by:
        tag += f":{ob.invited_by}"
    if ob.gate:
        tag += f" ({ob.gate})"
    # Fixed-width name/role columns so the LLM can visually align them.
    return f"- {a.name:<14s} role={a.role:<14s} {tag}"


def _render_journey_block(j: Journey, *, index: int) -> list[str]:
    """One journey renders as: header + numbered steps + optional variations."""
    header_bits = [f"Journey #{index}", f"{j.name!r}"]
    if j.primary_actor:
        header_bits.append(f"(primary: {j.primary_actor})")
    lines = [""]
    lines.append("  " + "  ".join(header_bits))
    if j.trigger:
        lines.append(f"    trigger: {j.trigger}")
    for i, step in enumerate(j.steps, 1):
        lines.append(_render_journey_step(step, index=i))
    for v in j.variations:
        lines.append(f"    (variation at step {v.at_step}: {v.condition} → {v.outcome})")
    return lines


def _render_journey_step(step: JourneyStep, *, index: int) -> str:
    """Steps are the whole point — render them so the planner can walk
    them one at a time and check each field against its own pages/
    workflows lists."""
    parts = [f"    {index}. {step.actor:<12s} {step.action:<30s}"]
    if step.page:
        parts.append(f"page={step.page}")
    if step.workflow:
        parts.append(f"via {step.workflow}")
    if step.outcome:
        parts.append(f"→ {step.outcome}")
    return "  ".join(parts)

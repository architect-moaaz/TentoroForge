"""LLM intent parser for the Discovery Adjust-strategy conversation.

Mirrors :mod:`services.plan_adjust_intent` for the discovery stage.
The user chats in plain English ("make the domain hospitality",
"add pci compliance", "drop the candidate pipeline pattern"). This
module maps the message to one or more
:mod:`services.discovery_adjust` op calls, applies them
deterministically, and returns the new dossier + a structured diff.

The LLM's only surface is picking which whitelisted op to call — it
never authors JSON directly. That is the reliability guarantee for
multi-turn discovery conversations.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Optional

from services.discovery_adjust import (
    DossierAdjustError,
    DossierDiff,
    add_compliance,
    add_design_pattern,
    add_entity_suggestion,
    add_pitfall,
    compute_diff,
    remove_compliance,
    remove_design_pattern,
    remove_entity_suggestion,
    remove_pitfall,
    set_description,
    set_domain,
    set_visual_language,
    validate_dossier_shape,
)


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Op dispatch table                                                            #
# --------------------------------------------------------------------------- #

_OPS: dict[str, Callable[..., dict]] = {
    "set_domain":              set_domain,
    "set_description":         set_description,
    "add_compliance":          add_compliance,
    "remove_compliance":       remove_compliance,
    "add_entity_suggestion":   add_entity_suggestion,
    "remove_entity_suggestion": remove_entity_suggestion,
    "add_design_pattern":      add_design_pattern,
    "remove_design_pattern":   remove_design_pattern,
    "add_pitfall":             add_pitfall,
    "remove_pitfall":          remove_pitfall,
    "set_visual_language":     set_visual_language,
}


# --------------------------------------------------------------------------- #
# Types                                                                        #
# --------------------------------------------------------------------------- #

@dataclass
class AppliedOp:
    op: str
    args: dict[str, Any]


@dataclass
class DossierAdjustResult:
    new_dossier: dict = field(default_factory=dict)
    applied_ops: list[AppliedOp] = field(default_factory=list)
    diff: DossierDiff = field(default_factory=DossierDiff)
    narrative: str = ""
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "new_dossier": self.new_dossier,
            "applied_ops": [asdict(a) for a in self.applied_ops],
            "diff":        self.diff.to_dict(),
            "narrative":   self.narrative,
            "warnings":    self.warnings,
            "error":       self.error,
        }


# --------------------------------------------------------------------------- #
# LLM boundary                                                                 #
# --------------------------------------------------------------------------- #

QueryFn = Callable[[str, str], Awaitable[str]]


SYSTEM_PROMPT = """You are the discovery-adjust intent parser for Tentoro Forge.

The user is chatting with you to refine the *discovery dossier* their
project uses BEFORE the planner runs. Your only job is to translate
their message into a JSON array of operations from the whitelist below.
You do NOT write dossier JSON directly. You do NOT invent new op names.

Available ops (case-sensitive):

  set_domain(text)
      Replace the domain label (e.g. "Hospitality", "Recruitment").

  set_description(text)
      Replace the free-form dossier description prose.

  add_compliance(regime)
      Append a compliance regime. regime MUST be one of:
      none, hipaa, pci, gdpr, sox, fda, ferpa, ada-wcag

  remove_compliance(regime)

  add_entity_suggestion(name, likely_fields?)
      name: display name (letters, digits, spaces, hyphens ok — e.g.
            "Reservation" or "Hiring pipeline")
      likely_fields: optional list of field names, e.g.
                     ["guest_name", "arrival_at"]

  remove_entity_suggestion(name)

  add_design_pattern(name, description?, evidence?)
      name: pattern name — "Kanban board", "Split-pane detail", etc.
      description: one-line explanation
      evidence: optional list of short quotes from the user prompt

  remove_design_pattern(name)

  add_pitfall(text)
      Append a "watch out for X" note. text is a full sentence.

  remove_pitfall(text)

  set_visual_language(palette_character?, typography_tone?, density_preference?)
      Update one or more visual-language keys. Keys not supplied stay
      as-is.

Output format (STRICT JSON, no prose, no markdown):

  {
    "ops": [
      {"op": "set_domain", "args": {"text": "Hospitality"}},
      {"op": "add_compliance", "args": {"regime": "pci"}}
    ],
    "narrative": "Switched the domain to Hospitality and turned on PCI."
  }

Rules:
  * Emit ONLY ops that map to the user's stated intent.
  * Emit ops in the order they should apply.
  * If the user names a compliance regime that isn't in the whitelist,
    return {"ops": [], "narrative": "Only these compliance regimes are
    supported: none/hipaa/pci/gdpr/sox/fda/ferpa/ada-wcag."}
  * If ambiguous, return {"ops": [], "narrative": "Could you clarify —
    <what's ambiguous>?"}
  * NEVER include the word "APPROVED" or attempt to run the planner.

Current dossier skeleton is in the next message."""


async def _default_query(system_prompt: str, user_prompt: str) -> str:
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
        block.text for block in msg.content
        if getattr(block, "type", "") == "text"
    )


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

def _skeleton(dossier: dict) -> dict:
    """Compact view of the dossier for the LLM. Full dossier can be
    long (designPatterns descriptions + prose); the intent parser only
    needs names + structure."""
    return {
        "domain":         dossier.get("domain") or "",
        "domainAliases":  list(dossier.get("domainAliases") or [])[:5],
        "description":    (dossier.get("description") or "")[:400],
        "complianceNotes": list(dossier.get("complianceNotes") or []),
        "designPatterns": [
            {"name": p.get("name")}
            for p in (dossier.get("designPatterns") or [])
        ],
        "entitySuggestions": [
            {"name": e.get("name")}
            for e in (dossier.get("entitySuggestions") or [])
        ],
        "commonPitfalls": list(dossier.get("commonPitfalls") or [])[:8],
        "visualLanguage": dict(dossier.get("visualLanguage") or {}),
    }


async def adjust_dossier_via_llm(
    dossier: dict,
    user_message: str,
    *,
    query_fn: QueryFn | None = None,
    prior_turns: Optional[list[dict]] = None,
) -> DossierAdjustResult:
    """Run one Discovery-Adjust turn.

    Same contract as :func:`plan_adjust_intent.adjust_plan_via_llm`.
    Never raises — every failure path lands in ``error`` so the UI can
    display a specific message.
    """
    q = query_fn or _default_query
    user_message = (user_message or "").strip()
    if not user_message:
        return DossierAdjustResult(
            new_dossier=dossier,
            narrative="No message received.",
            error="empty_message",
        )

    skeleton_blob = json.dumps(_skeleton(dossier), indent=2, sort_keys=True)
    history_blob = ""
    if prior_turns:
        formatted: list[str] = []
        for t in prior_turns[-6:]:
            role = t.get("role") or "user"
            content = (t.get("content") or "").strip()
            if content:
                formatted.append(f"[{role}] {content}")
        if formatted:
            history_blob = (
                "\nPrior turns (most recent last):\n"
                + "\n".join(formatted) + "\n"
            )

    user_prompt = (
        f"Current dossier skeleton:\n{skeleton_blob}\n"
        f"{history_blob}"
        f"\nUser's message: {user_message}\n\n"
        f"Emit the JSON now."
    )

    try:
        raw = await q(SYSTEM_PROMPT, user_prompt)
    except Exception as exc:
        logger.warning("discovery_adjust: LLM call failed: %s", exc)
        return DossierAdjustResult(
            new_dossier=dossier,
            narrative="I couldn't reach the model right now. Try again in a moment.",
            error=f"llm_error: {exc.__class__.__name__}",
        )

    parsed = _parse_ops(raw)
    if parsed.get("error"):
        return DossierAdjustResult(
            new_dossier=dossier,
            narrative=parsed.get("narrative") or "I couldn't parse the model's reply.",
            error=parsed["error"],
        )

    return apply_ops(
        dossier, parsed.get("ops") or [],
        narrative=parsed.get("narrative") or "",
    )


def apply_ops(
    dossier: dict,
    ops: list[dict],
    *,
    narrative: str = "",
) -> DossierAdjustResult:
    """Apply a list of ``{op, args}`` to a dossier."""
    current = dossier
    applied: list[AppliedOp] = []
    warnings: list[str] = []

    for entry in ops:
        if not isinstance(entry, dict):
            warnings.append(f"Skipped malformed op entry: {entry!r}")
            continue
        op_name = entry.get("op")
        args = entry.get("args") or {}
        if op_name not in _OPS:
            warnings.append(f"Unknown op {op_name!r} — skipped.")
            continue
        if not isinstance(args, dict):
            warnings.append(
                f"Args for {op_name!r} must be a dict, got {type(args).__name__}"
            )
            continue
        try:
            current = _OPS[op_name](current, **args)
            applied.append(AppliedOp(op=op_name, args=args))
        except DossierAdjustError as exc:
            warnings.append(f"{op_name}: {exc}")
        except TypeError as exc:
            warnings.append(f"{op_name}: bad args ({exc})")

    warnings.extend(validate_dossier_shape(current))

    return DossierAdjustResult(
        new_dossier=current,
        applied_ops=applied,
        diff=compute_diff(dossier, current),
        narrative=narrative or _default_narrative(applied),
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Response parsing                                                             #
# --------------------------------------------------------------------------- #

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _parse_ops(raw: str) -> dict:
    """Extract ``{ops, narrative}`` from the model's reply. Same logic
    as plan_adjust_intent — tolerates markdown fences and leading prose."""
    if not raw or not raw.strip():
        return {"error": "empty_response"}
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        return {"error": "no_json_in_response", "narrative": text[:200]}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        return {"error": f"invalid_json: {exc.msg}"}
    if not isinstance(data, dict):
        return {"error": "response_not_object"}
    ops = data.get("ops")
    if ops is not None and not isinstance(ops, list):
        return {"error": "ops_not_list"}
    return {
        "ops": ops or [],
        "narrative": data.get("narrative") or "",
    }


def _default_narrative(applied: list[AppliedOp]) -> str:
    if not applied:
        return "No changes applied."
    verbs = {
        "set_domain":              "Set domain",
        "set_description":         "Updated description",
        "add_compliance":          "Added compliance",
        "remove_compliance":       "Removed compliance",
        "add_entity_suggestion":   "Added entity",
        "remove_entity_suggestion": "Removed entity",
        "add_design_pattern":      "Added pattern",
        "remove_design_pattern":   "Removed pattern",
        "add_pitfall":             "Noted pitfall",
        "remove_pitfall":          "Dropped pitfall",
        "set_visual_language":     "Updated visual language",
    }
    parts: list[str] = []
    for a in applied:
        verb = verbs.get(a.op, a.op)
        label = (
            a.args.get("name")
            or a.args.get("regime")
            or a.args.get("text")
            or ""
        )
        parts.append(f"{verb} {label}".strip())
    return "; ".join(parts) + "."

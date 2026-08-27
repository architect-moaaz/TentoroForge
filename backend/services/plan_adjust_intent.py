"""LLM intent parser for the Adjust-strategy conversation.

The user chats in plain English ("add a bookings entity", "remove
Notifications", "make Staff invite-only"). This module classifies the
message into a list of ``plan_adjust`` op calls, applies them
deterministically, and returns the new plan + a structured diff.

Contract
--------
:func:`adjust_plan_via_llm` accepts the current plan + user message,
returns :class:`AdjustResult` — never raises for LLM issues (falls
back to no-op with a narrative explaining why). Raises only when the
underlying pure ops reject invalid input.

The LLM's ONLY job is to pick which ops to call and with what args —
it never authors plan JSON directly. That is the reliability
guarantee: the pipeline can't drift because the surface area is a
short whitelist.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Optional

from services.plan_adjust import (
    PlanAdjustError,
    PlanDiff,
    add_actor,
    add_entity,
    add_page,
    add_workflow,
    compute_diff,
    remove_actor,
    remove_entity,
    remove_page,
    remove_workflow,
    toggle_feature,
    validate_plan_shape,
)


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Op dispatch table                                                            #
# --------------------------------------------------------------------------- #
# Central catalog: this is the WHOLE surface the LLM can drive. Extend
# here + in the SYSTEM_PROMPT + in tests, in that order.

_OPS: dict[str, Callable[..., dict]] = {
    "add_entity":      add_entity,
    "remove_entity":   remove_entity,
    "add_page":        add_page,
    "remove_page":     remove_page,
    "add_workflow":    add_workflow,
    "remove_workflow": remove_workflow,
    "add_actor":       add_actor,
    "remove_actor":    remove_actor,
    "toggle_feature":  toggle_feature,
}


# --------------------------------------------------------------------------- #
# Types                                                                        #
# --------------------------------------------------------------------------- #

@dataclass
class AppliedOp:
    """Record of a single mutation that landed. Serialised into the
    SSE stream + persisted in the adjust history so undo can rebuild
    the plan from the same intent."""

    op: str
    args: dict[str, Any]


@dataclass
class AdjustResult:
    """Outcome of one Adjust-strategy chat turn."""

    new_plan: dict = field(default_factory=dict)
    applied_ops: list[AppliedOp] = field(default_factory=list)
    diff: PlanDiff = field(default_factory=PlanDiff)
    narrative: str = ""
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "new_plan": self.new_plan,
            "applied_ops": [asdict(a) for a in self.applied_ops],
            "diff": self.diff.to_dict(),
            "narrative": self.narrative,
            "warnings": self.warnings,
            "error": self.error,
        }


# --------------------------------------------------------------------------- #
# LLM boundary                                                                 #
# --------------------------------------------------------------------------- #

QueryFn = Callable[[str, str], Awaitable[str]]
"""``(system_prompt, user_prompt) -> str`` — abstract so tests inject
deterministic stubs without touching the network."""


SYSTEM_PROMPT = """You are the plan-adjust intent parser for Tentoro Forge.

The user is chatting with you about tweaking their app plan BEFORE
generation. Your ONLY job is to translate their message into a JSON
array of operations from the whitelist below. You do NOT write plan
JSON directly. You do NOT invent new op names.

Available ops (case-sensitive, args are keyword arguments):

  add_entity(name, fields?)
      name: PascalCase identifier (e.g. "Booking")
      fields: optional list of {name, type}. Defaults to id/createdAt/updatedAt.
              Types: uuid, string, int, decimal, bool, date, timestamp, text, jsonb

  remove_entity(name)
      Cascades: also drops pages and relations tied to this entity.

  add_page(name, entity?, archetype?, route?, description?, features?)
      name: PascalCase, usually ending in "Page" (e.g. "BookingsPage")
      entity: optional entity name if the page is bound to one
      archetype: one of: dashboard, list, detail, form, kanban, calendar,
                 timeline, profile, settings, auth. Defaults to "list".
      route: optional explicit path (e.g. "/checkout"). Derived from name.

  remove_page(route)
      route: exact path (e.g. "/members")

  add_workflow(name, trigger, description?)
      name: PascalCase (e.g. "CancelBooking")
      trigger: HTTP route or event string (e.g. "POST /api/bookings/cancel")

  remove_workflow(name)

  add_actor(name, role, onboarding?)
      name: PascalCase (e.g. "Reviewer")
      role: kebab-or-lowercase (e.g. "reviewer")
      onboarding: optional {source: "self_signup" | "invited_by" | "admin_creates"}

  remove_actor(name)

  toggle_feature(feature, on)
      feature: one of: commerce, notifications, search, reporting, audit
      on: true|false

Output format (STRICT JSON, no prose, no markdown):

  {
    "ops": [
      {"op": "add_entity", "args": {"name": "Booking", "fields": [...]}},
      {"op": "add_page", "args": {"name": "BookingsPage", "entity": "Booking", "archetype": "list"}}
    ],
    "narrative": "Added a Booking entity and a list page to browse them."
  }

Rules:
  * Emit ONLY ops that map to the user's stated intent. Don't add
    extras "because they might want them."
  * When the user asks for a domain concept, derive the entity + a
    default list page. Skip the page if the user was clear it's not a
    UI thing (e.g. "add a background job").
  * When they say "remove X", figure out from the current plan whether
    X is an entity, page, workflow, or actor and emit the matching op.
  * If the message is ambiguous or you can't map it, return
    {"ops": [], "narrative": "I couldn't tell what to change — could you
    be more specific? (e.g. 'add a bookings entity')"}
  * NEVER include the word "APPROVED" or attempt to generate.

Current plan skeleton is in the next message."""


async def _default_query(system_prompt: str, user_prompt: str) -> str:
    """Real Claude call. Kept behind an env-flag so tests never touch
    the network."""
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

def _skeleton(plan: dict) -> dict:
    """Compact view of the plan we hand to the LLM. Full plan is often
    tens of kilobytes; the intent parser only needs names + structure."""
    return {
        "module_name": plan.get("module_name"),
        "description": (plan.get("description") or "")[:400],
        "data_models": [
            {"name": e.get("name"),
             "fields": [f.get("name") for f in (e.get("fields") or [])]}
            for e in (plan.get("data_models") or [])
        ],
        "pages": [
            {"route": p.get("route"),
             "name": p.get("name"),
             "entity": p.get("entity"),
             "archetype": p.get("archetype")}
            for p in (plan.get("pages") or [])
        ],
        "workflows": [
            {"name": w.get("name"),
             "trigger": (w.get("trigger") or "")[:120]}
            for w in (plan.get("workflows") or [])
        ],
        "actors": [
            {"name": a.get("name"), "role": a.get("role")}
            for a in (plan.get("actors") or [])
        ],
        "features": list(plan.get("features") or []),
    }


async def adjust_plan_via_llm(
    plan: dict,
    user_message: str,
    *,
    query_fn: QueryFn | None = None,
    prior_turns: Optional[list[dict]] = None,
) -> AdjustResult:
    """Run one Adjust-strategy turn.

    Args:
        plan: current plan dict (from ``plan.json``)
        user_message: what the user typed this turn
        query_fn: LLM boundary; tests pass a stub
        prior_turns: optional list of ``{"role": "user"|"assistant",
            "content": str}`` from earlier adjust turns. Passed to the
            LLM as prior context so multi-turn asks land coherently.
            The plan itself is the SoT — this is just for narrative
            continuity.

    Returns:
        :class:`AdjustResult` with ``new_plan``, ``diff``, ``narrative``,
        and any warnings. Never raises; failure paths land in ``error``.
    """
    q = query_fn or _default_query
    user_message = (user_message or "").strip()
    if not user_message:
        return AdjustResult(
            new_plan=plan,
            narrative="No message received.",
            error="empty_message",
        )

    skeleton_blob = json.dumps(_skeleton(plan), indent=2, sort_keys=True)
    history_blob = ""
    if prior_turns:
        formatted = []
        for t in prior_turns[-6:]:  # cap at last 6 turns
            role = t.get("role") or "user"
            content = (t.get("content") or "").strip()
            if content:
                formatted.append(f"[{role}] {content}")
        if formatted:
            history_blob = "\nPrior turns (most recent last):\n" + "\n".join(formatted) + "\n"

    user_prompt = (
        f"Current plan skeleton:\n{skeleton_blob}\n"
        f"{history_blob}"
        f"\nUser's message: {user_message}\n\n"
        f"Emit the JSON now."
    )

    try:
        raw = await q(SYSTEM_PROMPT, user_prompt)
    except Exception as exc:
        logger.warning("plan_adjust: LLM call failed: %s", exc)
        return AdjustResult(
            new_plan=plan,
            narrative="I couldn't reach the model right now. Try again in a moment.",
            error=f"llm_error: {exc.__class__.__name__}",
        )

    parsed = _parse_ops(raw)
    if parsed.get("error"):
        return AdjustResult(
            new_plan=plan,
            narrative=parsed.get("narrative") or "I couldn't parse the model's reply.",
            error=parsed["error"],
        )

    ops = parsed.get("ops") or []
    narrative = parsed.get("narrative") or ""
    return apply_ops(plan, ops, narrative=narrative)


def apply_ops(
    plan: dict,
    ops: list[dict],
    *,
    narrative: str = "",
) -> AdjustResult:
    """Apply a list of ``{op, args}`` operations to a plan.

    Extracted from :func:`adjust_plan_via_llm` so callers can bypass
    the LLM (e.g. undo replay, deterministic tests). Continues past
    a single-op error instead of failing the whole batch — that
    partial failure surfaces in ``warnings``.
    """
    current = plan
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
            warnings.append(f"Args for {op_name!r} must be a dict, got {type(args).__name__}")
            continue
        try:
            current = _OPS[op_name](current, **args)
            applied.append(AppliedOp(op=op_name, args=args))
        except PlanAdjustError as exc:
            warnings.append(f"{op_name}: {exc}")
        except TypeError as exc:
            warnings.append(f"{op_name}: bad args ({exc})")

    shape_warnings = validate_plan_shape(current)
    warnings.extend(shape_warnings)

    return AdjustResult(
        new_plan=current,
        applied_ops=applied,
        diff=compute_diff(plan, current),
        narrative=narrative or _default_narrative(applied),
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Response parsing                                                             #
# --------------------------------------------------------------------------- #

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _parse_ops(raw: str) -> dict:
    """Extract ``{ops, narrative}`` from the model's reply. Handles
    the model wrapping JSON in ``` fences or leading prose despite the
    prompt asking for pure JSON."""
    if not raw or not raw.strip():
        return {"error": "empty_response"}
    text = raw.strip()
    # Strip markdown fences if the model added them.
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
    """Human-readable summary when the LLM didn't supply one."""
    if not applied:
        return "No changes applied."
    parts = []
    for a in applied:
        name = a.args.get("name") or a.args.get("route") or a.args.get("feature") or ""
        verb = {
            "add_entity":      "Added entity",
            "remove_entity":   "Removed entity",
            "add_page":        "Added page",
            "remove_page":     "Removed page",
            "add_workflow":    "Added workflow",
            "remove_workflow": "Removed workflow",
            "add_actor":       "Added actor",
            "remove_actor":    "Removed actor",
            "toggle_feature":  "Toggled feature",
        }.get(a.op, a.op)
        parts.append(f"{verb} {name}")
    return "; ".join(parts) + "."

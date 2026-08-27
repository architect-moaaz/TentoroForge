"""Plan coverage critic — Slice REL-S2.

Independent verification that the plan covers what the brief says
(and what a reasonable domain reading of the brief implies).

**Why this exists.** Auto-repair can fix everything mechanical, but it
can't invent what the planner silently dropped. If the brief says
"notify managers when a report is due" and the plan emits `Report`
but no `Notification` entity or `notify_manager` workflow, no
mechanical repair pass can put them there — adding them would be
hallucination, not repair. The reliability lever is catching the
gap at plan-time and making the planner fix it via REVISE.

**Why LLM-based, not rule-based.**
- The gap set is open-ended: verbs like ``notify``/``approve``/
  ``schedule``/``publish``/``audit`` imply workflows; roles mentioned
  casually imply actors; domain conventions (approvals in
  doc-intel, notifications in workflow apps) live in the brief's
  register, not as tokens.
- A separate LLM call in a fresh context, seeing only ``brief +
  prompt + plan``, reads with different attention than the planner
  that wrote the plan. Cheaper and more honest than self-critique.

**Composition with existing critics.**
- Emits :class:`Violation` objects with a stable rule slug so they
  ride the SAME REVISE loop as :mod:`plan_completeness_validator`.
- The planner already handles one REVISE turn per gap-set; we just
  merge into that list. No new retry cycle.
- Gated by ``FORGE_COVERAGE_CRITIC`` env var — off by default until
  live-tested.

Contract summary
----------------
- ``critique_coverage(brief, prompt, plan)`` → list of :class:`CoverageGap`
- ``to_violations(gaps)`` → list of :class:`Violation` (bridge to REVISE)
- ``format_coverage_gaps(gaps)`` → prompt block if REVISE prefers a
  standalone block over the merged violations list.

Fail-open: missing SDK, no API key, LLM error, malformed response —
all return an empty gap list. Never raises; a broken critic must
never fail a generation.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# Public shape
# ══════════════════════════════════════════════════════════════════

# Rule slugs the coverage critic emits. Every gap becomes a
# Violation with rule = "coverage:" + kind so tests can grep for the
# critic's contribution independently of the other completeness rules.
COVERAGE_RULE_PREFIX = "coverage:"

_ALLOWED_KINDS = frozenset({
    "missing_entity",
    "missing_workflow",
    "missing_action",
    "missing_role",
    "missing_page",
    "missing_capability",
})


@dataclass(frozen=True)
class CoverageGap:
    """One gap the plan doesn't cover but the brief says or implies.

    ``kind`` is a stable slug so REVISE prompts can nudge the planner
    toward the right emitter (entity vs workflow vs role).

    ``what`` is a short noun phrase naming the thing missing.

    ``why`` is a quote or close paraphrase from the brief/prompt that
    justifies the finding. Keeping this in the record prevents the
    critic from hallucinating gaps with no source.

    ``suggested_fix`` is one imperative sentence a planner can act
    on ("add `Notification` entity with fields …").
    """
    kind: str
    what: str
    why: str
    suggested_fix: str = ""


# ══════════════════════════════════════════════════════════════════
# Env gate
# ══════════════════════════════════════════════════════════════════

def is_coverage_critic_enabled() -> bool:
    """True when the coverage critic should run.

    Routed through :mod:`services.flag_profile` so ``FORGE_QUALITY=full``
    turns this on alongside every other quality gate — one env var, not
    sixty. ``FORGE_COVERAGE_CRITIC=1`` still works as a per-gate escape
    hatch for debugging in isolation.

    Default off until live-validated (post-REL-S2-T4).
    """
    try:
        from services.flag_profile import is_on
        return is_on("FORGE_COVERAGE_CRITIC", default=False)
    except Exception:  # noqa: BLE001
        # Fall back to the direct env-var read if the meta-flag module
        # isn't importable (shouldn't happen in prod but keeps this
        # module standalone for tests).
        return os.getenv("FORGE_COVERAGE_CRITIC", "").strip().lower() in (
            "1", "true", "yes", "on",
        )


# ══════════════════════════════════════════════════════════════════
# Prompt construction
# ══════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = (
    "You are a reliability critic for an internal-app generation pipeline. "
    "Your ONLY job: read the brief + user prompt + plan JSON, and list "
    "things the brief says or a reasonable domain reading implies, that "
    "the plan does not cover.\n"
    "\n"
    "Rules:\n"
    "• Quote or paraphrase the brief/prompt line for every gap — no gap "
    "without a source.\n"
    "• Prefer FEWER, HIGHER-QUALITY gaps. Do not pad. Empty list is OK.\n"
    "• Skip gaps the plan addresses under a different name; check "
    "synonyms (e.g. `Notification` vs `Alert` vs `Message`).\n"
    "• Skip stylistic / cosmetic gaps — this critic is for structural "
    "completeness, not design quality.\n"
    "• Gap kinds (stable slugs, use exactly these):\n"
    "    - missing_entity     : brief names a noun, plan has no entity\n"
    "    - missing_workflow   : brief has a verb (notify/approve/publish/"
    "schedule/audit) or implies a background job, plan has no workflow\n"
    "    - missing_action     : brief names a user action, plan has no "
    "button/form for it\n"
    "    - missing_role       : brief names an actor, plan actors list is silent\n"
    "    - missing_page       : brief implies a screen, plan pages don't cover it\n"
    "    - missing_capability : cross-cutting requirement (audit trail, "
    "search, notifications) implied by domain, plan lacks it\n"
    "\n"
    "OUTPUT: pure JSON, no prose, no code fences:\n"
    "{\"gaps\": [{\"kind\": string, \"what\": string, \"why\": string, "
    "\"suggested_fix\": string}, ...]}"
)


def _build_user_message(brief: dict, prompt: str, plan: dict) -> str:
    """The prompt body: brief + user prompt + trimmed plan.

    Plan is trimmed to the shape-carrying keys the critic needs
    (entities, workflows, pages, actors) to keep token cost bounded.
    Full plan is ~24K tokens; trimmed ~2-4K.
    """
    trimmed_plan = _trim_plan_for_critic(plan)
    return (
        "USER PROMPT (verbatim):\n"
        f"{prompt.strip() if isinstance(prompt, str) else '(none)'}\n"
        "\n"
        "BRIEF (identity / palette / voice — abbreviated):\n"
        f"{json.dumps(_abbreviate_brief(brief), indent=2)}\n"
        "\n"
        "PLAN (structural — entities, workflows, pages, actors):\n"
        f"{json.dumps(trimmed_plan, indent=2)}\n"
        "\n"
        "List gaps now."
    )


def _abbreviate_brief(brief: dict) -> dict:
    """Drop visual-only fields (palette hexes, radius, shadow) that
    don't affect structural coverage. Keep identity / domain / voice /
    signature_moves — they hint at semantic expectations."""
    if not isinstance(brief, dict):
        return {}
    keep_top = {"identity", "signature_moves", "content_bank", "personas"}
    out: dict[str, Any] = {}
    for k in keep_top:
        if k in brief:
            out[k] = brief[k]
    return out


def _trim_plan_for_critic(plan: dict) -> dict:
    """Extract just the shape the critic needs to detect coverage gaps.

    Full plan.json embeds design tokens, schema hints, LLM-authored
    notes — the critic doesn't need any of it. Entities' `columns` are
    kept as name lists (not full definitions) so the critic can see
    what exists without spending tokens on data types.
    """
    if not isinstance(plan, dict):
        return {}
    out: dict[str, Any] = {
        "archetype": plan.get("archetype") or plan.get("app_archetype"),
        "description": plan.get("description") or plan.get("app_description"),
        "landing": plan.get("landing"),
    }

    # Entities: name + column-name list only
    ents_out: list[dict] = []
    ents = plan.get("entities")
    if isinstance(ents, dict):
        for name, e in ents.items():
            if isinstance(name, str) and isinstance(e, dict):
                cols = e.get("columns") or e.get("fields") or []
                col_names = [
                    c.get("name") if isinstance(c, dict) else str(c)
                    for c in cols if c
                ]
                ents_out.append({"name": name, "columns": col_names})
    elif isinstance(ents, list):
        for e in ents:
            if isinstance(e, dict) and e.get("name"):
                cols = e.get("columns") or e.get("fields") or []
                col_names = [
                    c.get("name") if isinstance(c, dict) else str(c)
                    for c in cols if c
                ]
                ents_out.append({"name": e["name"], "columns": col_names})
    if ents_out:
        out["entities"] = ents_out

    # Pages: route + kind + title only
    pages = plan.get("pages")
    if isinstance(pages, list):
        out["pages"] = [
            {
                "route": p.get("route"),
                "kind": p.get("kind") or p.get("type"),
                "title": p.get("title"),
            }
            for p in pages if isinstance(p, dict)
        ]

    # Workflows: name + trigger + step actionTypes only
    wfs = plan.get("workflows")
    if isinstance(wfs, list):
        out["workflows"] = [
            {
                "name": w.get("name"),
                "trigger": w.get("trigger"),
                "steps": [
                    s.get("actionType") if isinstance(s, dict) else str(s)
                    for s in (w.get("steps") or [])
                ],
            }
            for w in wfs if isinstance(w, dict)
        ]

    # Actors: name + role only
    actors = plan.get("actors")
    if isinstance(actors, list):
        out["actors"] = [
            {"name": a.get("name"), "role": a.get("role")}
            for a in actors if isinstance(a, dict)
        ]

    # Personas: name + jobs list only (jobs are the structural claim)
    personas = plan.get("personas")
    if isinstance(personas, list):
        out["personas"] = [
            {"name": p.get("name"), "jobs": p.get("jobs")}
            for p in personas if isinstance(p, dict)
        ]

    return out


# ══════════════════════════════════════════════════════════════════
# LLM call
# ══════════════════════════════════════════════════════════════════

async def _call_llm(brief: dict, prompt: str, plan: dict) -> list[dict] | None:
    """Return parsed gaps list from the LLM, or None on any failure.

    Uses the anthropic SDK directly (small, targeted). Returns None
    when SDK isn't installed OR key isn't set OR the response isn't
    valid JSON; callers treat None as "no gaps found" (fail-open).
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
    except Exception:  # noqa: BLE001
        return None
    try:
        client = llm_client.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=os.getenv("FORGE_COVERAGE_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=2048,
            temperature=0.0,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_message(brief, prompt, plan)}],
        )
        text = "".join(
            getattr(b, "text", "") for b in response.content
            if getattr(b, "type", "") == "text"
        ).strip()
        if not text:
            return None
        data = json.loads(text)
        gaps = data.get("gaps") if isinstance(data, dict) else None
        return gaps if isinstance(gaps, list) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[coverage-critic] LLM call failed: %s", exc)
        return None


def _validate_gap(raw: Any) -> CoverageGap | None:
    """Enforce the gap schema. Reject entries with disallowed kind or
    missing required fields; that stops LLM hallucinations from
    reaching the planner."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if kind not in _ALLOWED_KINDS:
        return None
    what = raw.get("what")
    why = raw.get("why")
    if not (isinstance(what, str) and what.strip()):
        return None
    if not (isinstance(why, str) and why.strip()):
        return None
    return CoverageGap(
        kind=kind,
        what=what.strip()[:200],
        why=why.strip()[:400],
        suggested_fix=str(raw.get("suggested_fix") or "").strip()[:300],
    )


# ══════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════

async def critique_coverage(brief: dict, prompt: str, plan: dict) -> list[CoverageGap]:
    """Return coverage gaps between brief+prompt and plan.

    Fail-open: any error path (no API key, malformed response,
    network) returns []. Enabling gate lives at the caller (see
    :func:`is_coverage_critic_enabled`).
    """
    if not isinstance(plan, dict):
        return []
    raw_gaps = await _call_llm(brief or {}, prompt or "", plan)
    if not raw_gaps:
        return []
    out: list[CoverageGap] = []
    for r in raw_gaps:
        gap = _validate_gap(r)
        if gap is not None:
            out.append(gap)
    # Cap at 10 to bound REVISE prompt size — if more surface, the plan
    # is broken enough that the first 10 tell the same story.
    return out[:10]


def to_violations(gaps: list[CoverageGap]) -> list["Violation"]:
    """Bridge to :mod:`plan_completeness_validator` so gaps ride the
    existing REVISE loop. Rule slug is prefixed with "coverage:" so
    downstream logs can tell coverage gaps apart from structural
    completeness violations."""
    try:
        from services.plan_completeness_validator import Violation
    except Exception:  # noqa: BLE001
        return []
    out: list[Violation] = []
    for g in gaps:
        rule = f"{COVERAGE_RULE_PREFIX}{g.kind}"
        msg_parts = [f"missing {g.kind.replace('missing_', '').replace('_', ' ')}: {g.what}"]
        if g.why:
            msg_parts.append(f'(brief says: "{g.why}")')
        if g.suggested_fix:
            msg_parts.append(f"fix: {g.suggested_fix}")
        out.append(Violation(rule=rule, msg=" ".join(msg_parts)))
    return out


def format_coverage_gaps(gaps: list[CoverageGap]) -> str:
    """Standalone REVISE block for coverage gaps, if a caller prefers
    it over the merged violations list. Mirrors
    :func:`plan_completeness_validator.format_revise_gaps` shape so
    the planner's REVISE MODE handles it uniformly."""
    if not gaps:
        return ""
    lines = ["COVERAGE GAPS TO FIX:"]
    for i, g in enumerate(gaps, 1):
        lines.append(
            f"{i}. [COVERAGE] [{g.kind}] {g.what}\n"
            f"   evidence: brief/prompt says \"{g.why}\"\n"
            + (f"   fix: {g.suggested_fix}\n" if g.suggested_fix else "")
        )
    return "\n".join(lines)


def gap_to_dict(gap: CoverageGap) -> dict[str, str]:
    """JSON-serializable form for persisting to disk (open_decisions,
    logs, reports). Frozen dataclass → asdict works cleanly."""
    return asdict(gap)


__all__ = [
    "CoverageGap",
    "COVERAGE_RULE_PREFIX",
    "critique_coverage",
    "format_coverage_gaps",
    "gap_to_dict",
    "is_coverage_critic_enabled",
    "to_violations",
]

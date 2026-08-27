"""Smith Auto-Act — decide whether to act, act-all, chip, or ask.

When a user says "change the Status field", Smith today runs
:func:`services.smith_find_resources.find_resources` and often punts with
"which page?" because token overlap is weak. This module replaces that
punt with a scored decision:

- **act** — one candidate stands out (current-route match, or literal
  label + only one page has it). Smith proceeds with that target.
- **act_all** — user said "everywhere" / "on all pages" and there are
  multiple candidates. Smith applies to all.
- **chip** — 2-4 near-equal candidates; the chat card shows a picker.
- **ask** — no candidates, or too many (5+); Smith falls back to prose.

Pure module: reads the app's registry via the existing tools
(:func:`grep_schemas_tool`, :func:`find_component_tool`,
:func:`list_pages_tool`, :func:`list_entities_tool`) but performs no LLM
calls of its own.

See :file:`docs/superpowers/specs/2026-08-07-smith-auto-act.md`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal, Sequence

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Public types
# --------------------------------------------------------------------------- #

CandidateKind = Literal["page", "component", "entity", "workflow"]
ResolutionKind = Literal["act", "act_all", "chip", "ask"]


@dataclass(frozen=True)
class Candidate:
    """A place in the app the user's query might refer to."""

    kind: CandidateKind
    route: str | None      # page's route if kind=page, else None
    path: str              # file path on disk (e.g. src/schemas/candidates.json)
    matched_by: tuple[str, ...] = ()   # ("label", "field_name", "entity_ref")
    excerpt: str = ""      # short preview (≤200 chars)


@dataclass(frozen=True)
class Resolution:
    """The action Smith should take."""

    kind: ResolutionKind
    targets: tuple[Candidate, ...] = ()
    reason: str = ""
    scores: tuple[tuple[Candidate, int], ...] = ()   # for debugging / UI


# --------------------------------------------------------------------------- #
# Universal-intent detection
# --------------------------------------------------------------------------- #

# Only unambiguous phrases. False positives here mean edits to pages the
# user didn't intend — bias hard toward "not universal".
_UNIVERSAL_RE = re.compile(
    r"""(?ix)
    (?:^|\s)
    (?:
        every[- ]?where
      | on\s+all\s+pages?
      | on\s+every\s+\w+
      | across\s+the\s+app
      | for\s+every\s+\w+
      | in\s+all\s+places
      | wherever\s+it\s+appears
      | all\s+instances\s+of
    )
    (?:$|[\s.,;:])
    """,
)


def universal_intent(query: str) -> bool:
    """Does the query explicitly ask for the change everywhere?

    Conservative — only matches unambiguous phrases. A generic "fix the
    status field" does NOT match; the user might mean only one page.
    """
    if not query:
        return False
    return bool(_UNIVERSAL_RE.search(query))


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

_ACT_SCORE_FLOOR = 60
_ACT_GAP_MIN = 20
_CHIP_MIN_CANDIDATES = 2
_CHIP_MAX_CANDIDATES = 4

# Signal weights. Kept as module constants so tests + callers can inspect.
_W_CURRENT_ROUTE = 50   # candidate.route == current_route
_W_RECENT_EDIT = 20     # candidate.route in recent_edits
_W_LITERAL_LABEL = 15   # candidate.matched_by includes 'label'
_W_ENTITY_RELEVANCE = 10  # candidate.matched_by includes 'entity_ref'


def score_candidate(
    c: Candidate,
    *,
    current_route: str | None,
    recent_edits: Sequence[str] = (),
) -> int:
    """Compute a candidate's score. Pure."""
    score = 0
    if current_route and c.route and c.route == current_route:
        score += _W_CURRENT_ROUTE
    if c.route and c.route in recent_edits:
        score += _W_RECENT_EDIT
    if "label" in c.matched_by:
        score += _W_LITERAL_LABEL
    if "entity_ref" in c.matched_by:
        score += _W_ENTITY_RELEVANCE
    return score


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #

def resolve(
    query: str,
    candidates: Sequence[Candidate],
    *,
    current_route: str | None = None,
    recent_edits: Sequence[str] = (),
) -> Resolution:
    """Score candidates + decide the action Smith should take.

    Pure — no I/O. Callers (in ``smith_agent`` and the like) are
    responsible for building the ``candidates`` list by calling the
    scanning tools (``grep_schemas``, ``find_component`` etc.) — that
    keeps this decision function trivially testable.

    Decision rules (in order):
        1. No candidates → ask.
        2. Universal-intent phrase in the query → act_all with all candidates
           (regardless of score). "make Status a badge everywhere" is
           unambiguous even when the label appears on 3 pages.
        3. Top candidate score ≥ 60 AND gap-to-second ≥ 20 → act.
        4. 2-4 candidates → chip.
        5. 5+ candidates (all lower-score) → ask.
    """
    if not candidates:
        return Resolution(
            kind="ask",
            reason="no matching pages/components/entities found for the query",
        )

    scored = tuple(
        (c, score_candidate(c, current_route=current_route, recent_edits=recent_edits))
        for c in candidates
    )
    # Sort by score desc; stable so tie order = input order.
    scored_sorted = tuple(sorted(scored, key=lambda pair: -pair[1]))

    # Rule 2: universal intent short-circuits scoring.
    if universal_intent(query):
        return Resolution(
            kind="act_all",
            targets=tuple(c for c, _ in scored_sorted),
            reason='query says "everywhere/on all pages"; applying to all matches',
            scores=scored_sorted,
        )

    top, top_score = scored_sorted[0]
    second_score = scored_sorted[1][1] if len(scored_sorted) > 1 else 0
    gap = top_score - second_score

    # Rule 3: act — high confidence.
    if top_score >= _ACT_SCORE_FLOOR and gap >= _ACT_GAP_MIN:
        return Resolution(
            kind="act",
            targets=(top,),
            reason=(
                f"top candidate scores {top_score} with a {gap}-point gap; "
                f"proceeding on {top.route or top.path}"
            ),
            scores=scored_sorted,
        )

    # Rule 4: chip — small, actionable set.
    if _CHIP_MIN_CANDIDATES <= len(scored_sorted) <= _CHIP_MAX_CANDIDATES:
        return Resolution(
            kind="chip",
            targets=tuple(c for c, _ in scored_sorted),
            reason=(
                f"top score {top_score} with only a {gap}-point gap over #2; "
                "presenting {n} options for the user to pick".format(
                    n=len(scored_sorted),
                )
            ),
            scores=scored_sorted,
        )

    # Rule 5: too many low-signal candidates → ask.
    return Resolution(
        kind="ask",
        reason=(
            f"{len(scored_sorted)} candidates with weak/similar scores "
            f"(top {top_score}, gap {gap}); need clarification"
        ),
        scores=scored_sorted,
    )


# --------------------------------------------------------------------------- #
# Candidate builder — the glue between existing scan tools and resolve()
# --------------------------------------------------------------------------- #

def build_candidates_from_scan(
    grep_matches: Sequence[dict] = (),
    component_usages: Sequence[dict] = (),
    entity_matches: Sequence[dict] = (),
    *,
    page_index: dict[str, str] | None = None,
) -> list[Candidate]:
    """Turn raw tool outputs into a de-duped list of Candidates.

    Inputs are the ``matches`` / ``usages`` arrays returned by
    ``grep_schemas_tool``, ``find_component_tool``, ``list_entities_tool``.
    ``page_index`` maps schema-file paths to their route (from
    ``list_pages_tool``), so grep hits on ``src/schemas/candidates.json``
    become route ``/candidates``.

    Output: unique Candidate per (path, route) pair, with ``matched_by``
    accumulated across signal sources.
    """
    page_index = page_index or {}
    by_key: dict[tuple[str, str | None], Candidate] = {}

    def _add(kind: CandidateKind, path: str, matched_by: str, excerpt: str = "") -> None:
        route = page_index.get(path)
        key = (path, route)
        existing = by_key.get(key)
        if existing:
            by_key[key] = Candidate(
                kind=existing.kind,
                route=existing.route,
                path=existing.path,
                matched_by=tuple(sorted(set(existing.matched_by) | {matched_by})),
                excerpt=existing.excerpt or excerpt,
            )
        else:
            by_key[key] = Candidate(
                kind=kind,
                route=route,
                path=path,
                matched_by=(matched_by,),
                excerpt=(excerpt or "")[:200],
            )

    for m in grep_matches:
        path = m.get("path") or ""
        if not path:
            continue
        previews = m.get("previews") or []
        excerpt = (previews[0] if previews else "")[:200]
        _add("page" if path in page_index else "workflow", path, "label", excerpt)

    for u in component_usages:
        path = u.get("path") or ""
        if not path:
            continue
        fields = u.get("fields") or []
        excerpt = f"used on fields: {', '.join(fields[:3])}"
        _add("page" if path in page_index else "component", path, "field_name", excerpt)

    for e in entity_matches:
        path = e.get("path") or ""
        if not path:
            continue
        _add("entity", path, "entity_ref", e.get("excerpt") or "")

    return list(by_key.values())


# --------------------------------------------------------------------------- #
# Trace harvest — pull resolve_target outputs back out of Smith's ReAct trace
# so the router can attach `also_applies_to` / `disambiguation` metadata to
# the persisted message without changing Smith's response envelope.
# --------------------------------------------------------------------------- #

def _target_to_dict(t: dict | Candidate) -> dict:
    if isinstance(t, dict):
        return {
            "route": t.get("route"),
            "label": t.get("label"),
            "excerpt": t.get("excerpt") or "",
        }
    return {"route": t.route, "excerpt": t.excerpt or ""}


def harvest_metadata(trace: list[dict] | None) -> dict:
    """Read resolve_target results from Smith's trace and shape them into
    UI-ready metadata for the persisted assistant message.

    Returns a dict with (possibly-empty) keys:
        also_applies_to — [{route, label?}] when Smith acted on one page
            and other candidates exist (from an `act` or `act_all` result).
        disambiguation — {query, candidates, reason} when the LATEST
            resolve_target returned kind="chip".

    Pure — no I/O. Trace entries are the tool-loop turns; each has
    ``tool``, ``args``, ``result`` (dict). We tolerate missing/mangled
    entries silently — this is a UI-nicety, never a correctness gate.
    """
    if not trace:
        return {}
    out: dict = {}
    resolve_calls: list[dict] = []
    for step in trace:
        if not isinstance(step, dict):
            continue
        if step.get("tool") != "resolve_target":
            continue
        result = step.get("result")
        if not isinstance(result, dict):
            continue
        args = step.get("args") or {}
        resolve_calls.append({"args": args, "result": result})
    if not resolve_calls:
        return {}

    # Take the LAST resolve_target result — that's the one Smith acted on.
    last = resolve_calls[-1]
    result = last["result"]
    args = last["args"]
    kind = result.get("kind")
    targets = result.get("targets") or []

    if kind == "chip" and targets:
        out["disambiguation"] = {
            "query": (args.get("query") or "").strip(),
            "candidates": [_target_to_dict(t) for t in targets[:_CHIP_MAX_CANDIDATES]],
            "reason": result.get("reason") or "",
        }
        return out

    if kind in ("act", "act_all") and len(targets) > 1:
        # For `act`, Smith touched targets[0] — the OTHERS are the
        # "also applies to" candidates. For `act_all`, Smith already
        # applied to everything, so nothing to offer.
        if kind == "act":
            others = targets[1:]
            if others:
                out["also_applies_to"] = [
                    {"route": t.get("route"), "label": t.get("label")}
                    for t in others[:4]
                    if t.get("route")
                ]
    return out


def harvest_brief_metadata(trace: list[dict] | None) -> dict:
    """PHASE-3 — scan Smith trace for design-brief tool calls and shape
    them as UI-ready metadata for ChatMessage.

    Returns:
        {"brief_edit": {...}} when Smith ran edit_brief this turn.
        {"brief_snapshot": {...}} when Smith ran get_brief only.
        {} on neither.

    edit_brief wins over get_brief when both fire in the same turn.
    """
    if not trace:
        return {}

    last_edit: dict | None = None
    last_get: dict | None = None
    for step in trace:
        if not isinstance(step, dict):
            continue
        tool = step.get("tool")
        result = step.get("result")
        if not isinstance(result, dict):
            continue
        if tool == "edit_brief" and result.get("applied"):
            last_edit = result
        elif tool == "get_brief" and result.get("brief") is not None:
            last_get = result

    if last_edit is not None:
        return {"brief_edit": {
            "before": last_edit.get("before") or {},
            "after": last_edit.get("after") or {},
        }}
    if last_get is not None:
        return {"brief_snapshot": last_get.get("brief") or {}}
    return {}


__all__ = [
    "Candidate",
    "CandidateKind",
    "Resolution",
    "ResolutionKind",
    "universal_intent",
    "score_candidate",
    "resolve",
    "build_candidates_from_scan",
    "harvest_metadata",
    "harvest_brief_metadata",
]

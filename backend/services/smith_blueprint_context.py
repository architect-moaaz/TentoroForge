"""Blueprint → Smith-system-prompt context rendering.

Spec: `docs/superpowers/specs/2026-07-17-smith-as-architect.md` §6.4.

Every Smith turn starts with the blueprint loaded into his system
prompt. This module is the renderer: it takes a Blueprint and
produces the compact prose Smith actually reads. It is intentionally
plain-text (no JSON dumps in-prompt) because Smith reasons better
against readable summaries than against raw records.

Two entry points:

  * :func:`pick_relevant_slice` — the S2b seam. Today it always
    returns the whole blueprint (the "small app" branch of §6.4).
    A later slice layers an LLM slicer on top for large apps, at
    which point this function grows to return a sub-blueprint.

  * :func:`blueprint_to_context` — the renderer proper. Respects a
    soft character budget by dropping the least-load-bearing sections
    first (older change_log entries).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.smith_blueprint import Blueprint


# --------------------------------------------------------------------------- #
# Budgeting
# --------------------------------------------------------------------------- #

# Default is generous. Only tight budgets force truncation; the
# common case for a hand-designed ATS-sized app fits comfortably.
_DEFAULT_MAX_CHARS = 12_000

# When rendering the change_log, we start by including the tail this
# many entries deep and back off if the budget is tight.
_DEFAULT_RECENT_MOVES = 12

_MIN_RECENT_MOVES = 3


@dataclass(frozen=True)
class ContextBudget:
    """Soft caps for the rendered context.

    `max_chars` is a target, not a hard cutoff — the renderer will
    truncate less-important sections to fit, but domain/entities/
    workflows/pages always render at least in summary form even when
    the budget is small enough to drop everything else."""
    max_chars: int = _DEFAULT_MAX_CHARS
    recent_moves: int = _DEFAULT_RECENT_MOVES


# --------------------------------------------------------------------------- #
# Slicer seam (S2b)
# --------------------------------------------------------------------------- #

def pick_relevant_slice(bp: Blueprint, *, ask: str | None) -> Blueprint:
    """Return the slice of the blueprint Smith should see for `ask`.

    Today: always the whole thing (`return bp`). A future slice will
    layer an LLM-driven picker for large apps; callers of this
    function are the seam."""
    _ = ask  # accepted for future signature stability
    return bp


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def blueprint_to_context(
    bp: Blueprint,
    *,
    budget: ContextBudget | None = None,
) -> str:
    """Render the blueprint as prose for Smith's system prompt.

    Always includes: project id, domain, every entity/workflow/page
    name. Change log tail is included as budget allows. Missing
    sections render as an explicit "no X yet" line rather than being
    silently omitted — Smith reads that as a signal about bootstrap
    state.

    The function is deterministic and side-effect-free; it never hits
    disk, model, or DB. That means it can be dropped into any
    context-assembly path without concurrency concerns."""
    budget = budget or ContextBudget()

    if _blueprint_is_empty(bp):
        return _render_bootstrap_stub(bp)

    # Render bounded sections first (they always survive), then fill
    # remaining budget with change_log.
    header = _render_header(bp)
    domain = _render_domain(bp)
    requirements = _render_requirements(bp)
    entities = _render_entities(bp)
    rules = _render_rules(bp)
    workflows = _render_workflows(bp)
    pages = _render_pages(bp)
    decisions = _render_design_decisions(bp)

    core_sections = "\n".join(
        s for s in (header, domain, requirements, entities, rules, workflows,
                    pages, decisions) if s
    )

    remaining = max(0, budget.max_chars - len(core_sections) - 200)
    # Reserve ~200 chars for section headers/newlines around the log.

    change_log_block = _render_change_log(bp, remaining, budget.recent_moves)

    parts = [core_sections]
    if change_log_block:
        parts.append(change_log_block)
    rendered = "\n\n".join(p for p in parts if p)

    # Hard-cap. If we still overshoot (e.g. very-large-single-entity
    # ATSes with 200 fields), trim the tail and mark the truncation.
    if len(rendered) > budget.max_chars:
        rendered = rendered[: budget.max_chars - 40].rstrip() + \
                   "\n\n… (older entries omitted; budget cap)"
    return rendered


# --------------------------------------------------------------------------- #
# Section renderers — each returns "" when there's nothing to say
# --------------------------------------------------------------------------- #

def _blueprint_is_empty(bp: Blueprint) -> bool:
    return (
        bp.domain is None
        and not bp.entities and not bp.workflows and not bp.pages
        and not getattr(bp, "requirements", None)
        and not getattr(bp, "business_rules", None)
        and not bp.design_decisions and not bp.change_log
    )


def _render_bootstrap_stub(bp: Blueprint) -> str:
    return (
        f"# App blueprint — project {bp.project_id}\n"
        f"(no app built yet; this is a bootstrap conversation. "
        f"Your first move is typically discovery.)"
    )


def _render_header(bp: Blueprint) -> str:
    return f"# App blueprint — project {bp.project_id}"


def _render_domain(bp: Blueprint) -> str:
    d = bp.domain
    if not isinstance(d, dict) or not d:
        return "## Domain\n(not yet defined — discovery hasn't run.)"
    parts = [f"## Domain: {d.get('name') or '(unnamed)'}"]
    actors = d.get("primary_actors") or []
    if actors:
        parts.append(f"- Primary actors: {', '.join(map(str, actors))}")
    verbs = d.get("core_verbs") or []
    if verbs:
        parts.append(f"- Core verbs: {', '.join(map(str, verbs))}")
    shape = d.get("distinctive_shape")
    if shape:
        parts.append(f"- Distinctive shape: {shape}")
    why = d.get("why")
    if why:
        parts.append(f"- Why this shape: {why}")
    return "\n".join(parts)


def _render_requirements(bp: Blueprint) -> str:
    """Every requirement with where it came from.

    The evidence is the point: a requirement that cites `document 1` came
    from the file the user uploaded, one that cites a screenshot was read off
    a picture, and one that cites the conversation was said. Smith is asked
    which is which, and this is the only place the answer lives.
    """
    reqs = [r for r in (getattr(bp, "requirements", None) or [])
            if isinstance(r, dict)]
    if not reqs:
        return "## Requirements\n(none recorded yet.)"
    lines = [f"## Requirements ({len(reqs)})"]
    for r in reqs:
        desc = " ".join(str(r.get("description") or "").split())
        cites = []
        for e in (r.get("evidence") or []):
            if not isinstance(e, dict):
                continue
            kind = str(e.get("type") or "").strip()
            src = str(e.get("source") or "").strip()
            # "document 1" already names its kind; "screenshot board.png"
            # needs it said.
            if src and src.lower().startswith(kind.lower()):
                cites.append(src)
            else:
                cites.append(f"{kind} {src}".strip() if src else kind)
        line = f"- {r.get('id') or '?'}: {desc}"
        if cites:
            line += f"  [from: {', '.join(c for c in cites if c)}]"
        lines.append(line)
    return "\n".join(lines)


def _render_entities(bp: Blueprint) -> str:
    if not bp.entities:
        return "## Entities\n(none yet.)"
    lines = ["## Entities"]
    for e in bp.entities:
        name = e.get("name") or "?"
        table = e.get("table") or ""
        purpose = e.get("purpose") or ""
        why = e.get("why_shaped_this_way") or ""
        summary = f"- **{name}** (table `{table}`): {purpose}"
        if why:
            summary += f"  · why: {why}"
        lines.append(summary)
        # ITS BOXES, WHICH IS WHAT "DOES IT ALREADY HAVE ONE" ASKS ABOUT.
        # Asked to validate the telephone number, Smith asked whether a
        # telephone field existed: the entity's name and table were all it
        # could see, so the only honest thing it could do was ask.
        spelled = []
        for f in (e.get("fields") or []):
            if not isinstance(f, dict) or not f.get("name"):
                continue
            one = f"{f['name']}: {f.get('type') or 'string'}"
            if f.get("required"):
                one += ", required"
            if f.get("enumValues"):
                one += " [" + "|".join(str(v) for v in f["enumValues"][:6]) + "]"
            spelled.append(one)
        if spelled:
            lines.append("    fields — " + "; ".join(spelled))
        elif e.get("key_fields"):
            lines.append("    fields — " + ", ".join(str(k) for k in e["key_fields"]))
    return "\n".join(lines)


def _render_rules(bp: Blueprint) -> str:
    """The rules already in force.

    Asked to add one, Smith could not tell whether it was already there, so
    every rule was either a question or a duplicate the seam refused after the
    fact. The seam still refuses duplicates; this is what lets the ANSWER say
    so instead.
    """
    rules = [r for r in (getattr(bp, "business_rules", None) or []) if isinstance(r, dict)]
    if not rules:
        return "## Rules\n(none yet.)"
    lines = [f"## Rules ({len(rules)})"]
    for r in rules:
        said = " ".join(str(r.get("statement") or "").split())
        line = f"- **{r.get('name') or '?'}**: {said}"
        if r.get("when"):
            line += f"  · when `{r['when']}`"
        lines.append(line)
    return "\n".join(lines)


def _render_workflows(bp: Blueprint) -> str:
    if not bp.workflows:
        return "## Workflows\n(none yet.)"
    lines = ["## Workflows"]
    for w in bp.workflows:
        name = w.get("name") or "?"
        purpose = w.get("purpose") or ""
        trigger = w.get("trigger") or ""
        why = w.get("why") or ""
        s = f"- **{name}**: {purpose}"
        if trigger:
            s += f"  · trigger: {trigger}"
        if why:
            s += f"  · why: {why}"
        lines.append(s)
    return "\n".join(lines)


def _render_pages(bp: Blueprint) -> str:
    if not bp.pages:
        return "## Pages\n(none yet.)"
    lines = ["## Pages"]
    for p in bp.pages:
        route = p.get("route") or "?"
        role = p.get("role") or ""
        lines.append(f"- `{route}` — {role}")
        for c in (p.get("notable_choices") or [])[:3]:
            if isinstance(c, dict):
                choice = c.get("choice") or ""
                why = c.get("why") or ""
                if choice:
                    lines.append(f"  · {choice}" + (f"  ({why})" if why else ""))
    return "\n".join(lines)


def _render_design_decisions(bp: Blueprint) -> str:
    if not bp.design_decisions:
        return ""  # non-load-bearing when empty
    lines = ["## Design decisions"]
    for d in bp.design_decisions:
        topic = d.get("topic") or "?"
        choice = d.get("choice") or ""
        why = d.get("why") or ""
        s = f"- **{topic}**: {choice}"
        if why:
            s += f"  · why: {why}"
        lines.append(s)
    return "\n".join(lines)


def _render_change_log(
    bp: Blueprint, char_budget: int, initial_recent: int,
) -> str:
    """Include the tail of the change log up to (or backed off from)
    the requested recent count, respecting the char budget."""
    total = len(bp.change_log or [])
    if total == 0 or char_budget <= 0:
        return ""

    recent = min(initial_recent, total)
    while recent >= _MIN_RECENT_MOVES:
        block = _render_change_log_block(bp, recent, total)
        if len(block) <= char_budget:
            return block
        recent -= 1

    # Budget too tight even for _MIN_RECENT_MOVES; drop to a marker.
    if total > 0:
        return f"## Recent moves\n(all {total} older entries omitted — context budget too tight.)"
    return ""


def _render_change_log_block(
    bp: Blueprint, recent: int, total: int,
) -> str:
    tail = list(bp.change_log)[-recent:]
    lines = [
        f"## Recent moves (last {recent} of {total};"
        f" {max(0, total - recent)} older entries omitted)"
    ]
    for e in tail:
        at = e.get("at") or ""
        src = e.get("source") or "smith"
        move = e.get("smith_move") or ""
        ask = e.get("user_ask") or ""
        why = e.get("why") or ""
        header_line = f"- [{at}] ({src}) {move}"
        lines.append(header_line)
        if ask:
            lines.append(f"    ask: {ask}")
        if why:
            lines.append(f"    why: {why}")
    return "\n".join(lines)

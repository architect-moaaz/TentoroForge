"""Design Context Pack — Sprint 1 of the Forge Great Again plan.

Assembles a designer-facing context block prepended to the page-schema
LLM's prompt inside ``_generate_schema_for_page``. The pack reframes the
authoring task from "fill a widget inventory" to "author this page as a
designer would" — with the brief, signature moves, a curated component
shortlist, a synthesized page purpose, and an explicit design mandate.

Design philosophy
-----------------
Today's pipeline treats the LLM as a schema-fitting mechanism: emit widgets
that satisfy the plan's widget inventory, respect the component contract
allowlist, and pass the guards. The result is technically valid but visually
inert — no hero moment, no brand echo, no signature moves, no authored
copy, no empty states. See the Propel-vs-Forge dashboard comparison in
docs/superpowers/specs/2026-08-09-forge-great-again.md for the source
observation.

The pack doesn't remove the technical contracts (props, tokens, binding
rules, catalog) — the base ``schema_prompt.build_schema_prompt`` continues
to inject those. The pack sits ABOVE them and primes the model to design
first, wire second.

Rollout
-------
Opt-in via ``FORGE_DESIGN_CONTEXT_PACK=1``. Scoped to dashboard pages in
Sprint 1 so we can watch quality per archetype before flipping everywhere.
Later slices lift list, detail, form. Sprint 4 replaces the synthesized
page purpose with a first-class ``page.purpose`` field emitted by the
planner; until then we derive it from the page shape.

Failures are silent: any exception during assembly returns an empty string
and the base prompt runs unchanged. The pack must never break generation.
"""
from __future__ import annotations

import os
import re
from typing import Any

_FLAG = "FORGE_DESIGN_CONTEXT_PACK"


def design_context_pack_enabled() -> bool:
    """Read the opt-in env flag. Default OFF; flip to 1 to activate.

    Mirrors the FORGE_POLISH_* rollout convention — off in tests + baseline
    generations, on in live pipelines once shadow-verified.
    """
    return os.getenv(_FLAG, "0").strip() == "1"


# Archetypes the pack currently supports. Sprint 1 = dashboard only, so
# the exemplar and mandate are dashboard-shaped. Extending to list /
# detail / form is a slice-per-archetype rollout.
_SUPPORTED_TYPES = frozenset({"dashboard"})


def build_design_context_pack(
    plan: dict, page: dict, output_dir: str,
) -> str:
    """Assemble the pack for one page. Returns ``""`` when disabled, when
    the page type isn't supported yet, or on any error during assembly."""
    if not design_context_pack_enabled():
        return ""
    if not isinstance(page, dict) or not isinstance(plan, dict):
        return ""
    page_type = (page.get("type") or page.get("page_type") or "").strip().lower()
    if page_type not in _SUPPORTED_TYPES:
        return ""
    try:
        parts: list[str] = [
            _design_mandate_block(),
            _page_purpose_block(plan, page),
        ]
        brief_block = _design_brief_block(output_dir)
        if brief_block:
            parts.append(brief_block)
        sig_block = _signature_moves_block(output_dir)
        if sig_block:
            parts.append(sig_block)
        # Sprint 9 — prior-page memory (behind FORGE_PAGE_DESIGN_MEMORY;
        # returns "" when off or when no prior pages exist yet).
        try:
            from services.page_design_memory import memory_block_for_prompt
            mem_block = memory_block_for_prompt(output_dir)
            if mem_block:
                parts.append(mem_block)
        except Exception:  # noqa: BLE001
            pass
        palette_block = _component_shortlist_block(page_type)
        if palette_block:
            parts.append(palette_block)
    except Exception:  # noqa: BLE001 — the pack is best-effort
        return ""
    return "\n\n".join(p for p in parts if p)


# ── Section builders ─────────────────────────────────────────────────────

def _design_mandate_block() -> str:
    """The philosophy prose — read first, sets the mindset. Deliberately
    written as an art-director brief, not a spec. The goal is to give the
    LLM PERMISSION to design, not more rules to fill out."""
    return """<design-mandate>
You are AUTHORING this page as a product designer would. You are not filling
widget slots. The plan's widget inventory is a HINT, not a constraint —
add, remove, or recompose widgets to serve the page's purpose.

Design principles that must hold on this page:

1. HERO MOMENT. One thing on the page reads first — the most important
   number, chart, or action. Give it size, color, and space. Everything
   else supports it. A dashboard where every widget has the same visual
   weight has no hero and reads as a data dump.

2. READING ORDER. Compose a scan-first hierarchy: KPI row at the TOP,
   primary content next (usually a hero chart), a secondary rail on the
   side, richer lists at the bottom. Never invert this by putting KPIs on
   the right and charts on the left — the eye reads top-down and left-to-
   right, and the layout must match.

3. BRAND COLOR AS INFORMATION. The primary color from the design brief
   MUST appear in at least 3 semantically meaningful places on this page:
   KPI icon tiles, chart accents, primary CTAs, active states, "View all"
   links, progress bars. A page where brand color lives only in the
   sidebar is a failure — the brand vanishes the moment content starts.

4. SEMANTIC COLOR FOR STATUS. Positive deltas in green, negative in red,
   in-progress in amber/orange, resolved in green, high-priority in red or
   amber. Never render "everything is grey". Status pills, delta arrows,
   and colored dot indicators are what let a user scan.

5. COPY IS A DESIGN MATERIAL. Author every user-facing string with intent:
   authored eyebrows ("PORTFOLIO OVERVIEW · AUG 2026"), rich sub-context
   lines ("Across 4 cities", "91.25% occupancy", "+2.1% vs last month"),
   actionable CTAs ("Send payment reminder →"). Never leak raw column
   names like "Maintenance_request" or naive plurals like "Propertys" —
   pluralize correctly (Property → Properties, Person → People) and
   humanize aggressively.

6. CARDS OR NOTHING. If one KPI is in a Card, they ALL are. If one chart
   has a border and shadow, they all do. Inconsistent card treatment reads
   as accidental, not intentional. Pick one and hold it.

7. EMPTY STATES MUST BE AUTHORED. Every list, chart, or widget that could
   be empty needs an intentional empty state — icon or illustration plus a
   plain-language message plus a primary CTA. Never leave a dashed
   rectangle as the empty-state design.

8. SIGNATURE MOVES MUST BE APPLIED. The design brief lists 2-3 signature
   moves that give this specific app its personality. They are not
   decoration — they are the visual DNA. Apply them on this page.

The full component library is available. Compose freely. Ask "what would
a designer put here to serve this page's purpose", not "which components
does the widget list say to use".
</design-mandate>"""


def _page_purpose_block(plan: dict, page: dict) -> str:
    """Render the page-purpose block.

    Sprint 4 promoted ``page.purpose`` + ``page.reading_priority`` to
    first-class planner fields — when the planner authored them (via
    ``_sanitize_page_purpose``), we PASS THROUGH the planner's prose
    verbatim. Only when the planner is silent do we synthesize a
    fallback from the page shape (Sprint 1 behavior). The planner has
    full domain context and writes a better purpose than any downstream
    heuristic can invent.
    """
    name = (page.get("name") or "").strip() or "This page"
    route = page.get("route") or ""
    entity = (page.get("entity") or "").strip()
    actor = _guess_actor(plan, page)
    widgets = page.get("widgets") or []
    actions = page.get("actions") or []

    # Planner-authored (Sprint 4) — pass through when present.
    authored_purpose = page.get("purpose")
    if not (isinstance(authored_purpose, str) and authored_purpose.strip()):
        authored_purpose = None
    authored_priorities_raw = page.get("reading_priority")
    if isinstance(authored_priorities_raw, list):
        authored_priorities: list[str] = [
            str(p).strip() for p in authored_priorities_raw
            if isinstance(p, str) and str(p).strip()
        ]
    else:
        authored_priorities = []

    # Fallback synthesis (Sprint 1) — only when the planner didn't author.
    goal = authored_purpose or _synthesize_goal(entity, widgets, actions)
    priorities = authored_priorities or _synthesize_reading_priorities(
        widgets, actions, entity,
    )
    source = "planner-authored" if authored_purpose else "synthesized"

    lines: list[str] = [f'<page-purpose source="{source}">']
    lines.append(f"Page: {name}" + (f" ({route})" if route else ""))
    if actor:
        lines.append(f"Primary reader: {actor}")
    lines.append("")
    lines.append("What the reader needs when they open this page:")
    lines.append(f"  {goal}")
    if priorities:
        lines.append("")
        lines.append("Reading priority (top → bottom):")
        for i, p in enumerate(priorities, 1):
            lines.append(f"  {i}. {p}")
    lines.append("")
    lines.append(
        "Design the page's composition, hierarchy, and copy to serve this "
        "purpose. Do not treat the widget inventory in the plan as a "
        "checklist — treat it as source material for a designed page."
    )
    lines.append("</page-purpose>")
    return "\n".join(lines)


def _design_brief_block(output_dir: str) -> str:
    """Load the on-disk design brief and render it as designer-facing prose.

    Reuses ``design_brief_to_prompt.brief_to_prompt`` — already used by
    ``page_agent``, ``component_agent``, ``agent``. Adding it to the
    schema-authoring turn closes the gap where the brief influences chrome
    tokens but not page-level composition.
    """
    try:
        from services.design_brief_to_prompt import (
            brief_to_prompt, load_brief_from_disk,
        )
    except Exception:  # noqa: BLE001
        return ""
    try:
        brief = load_brief_from_disk(output_dir)
    except Exception:  # noqa: BLE001
        return ""
    if brief is None:
        return ""
    try:
        text = brief_to_prompt(brief)
    except Exception:  # noqa: BLE001
        return ""
    if not text or not text.strip():
        return ""
    return f"<design-brief>\n{text.strip()}\n</design-brief>"


def _signature_moves_block(output_dir: str) -> str:
    """Render the signature-moves catalog, intersected with the brief's
    selected moves. If the brief lists nothing, all registered moves are
    considered available — the mandate above still requires 2 to be used.

    This is the surface Task #392 (signature-moves catalog) built but that
    nothing at authoring time consumed. Prior wiring only applied moves
    post-hoc via ``apply_signature_moves`` — the LLM never knew they
    existed. Here we tell it.
    """
    try:
        from services.signature_moves import describe_all
    except Exception:  # noqa: BLE001
        return ""
    try:
        all_moves = list(describe_all() or [])
    except Exception:  # noqa: BLE001
        return ""
    if not all_moves:
        return ""

    selected = _brief_signature_move_names(output_dir)
    if selected:
        picked = [m for m in all_moves if _move_kind(m) in selected]
        # If the brief selected moves but none are in the registry, fall
        # back to the full list — the LLM should still see options.
        if not picked:
            picked = all_moves
    else:
        picked = all_moves

    lines: list[str] = ["<signature-moves>"]
    lines.append(
        "This app's signature moves. Apply AT LEAST TWO of these on this "
        "page — they are the memorable design touches that give the app "
        "its personality. Not decoration; required."
    )
    for m in picked:
        kind = _move_kind(m)
        desc = str(m.get("description") or "").strip() if isinstance(m, dict) else ""
        if kind:
            lines.append(f"  · {kind}: {desc}" if desc else f"  · {kind}")
    lines.append("</signature-moves>")
    return "\n".join(lines)


def _brief_signature_move_names(output_dir: str) -> set[str]:
    """Return the set of signature-move kinds the brief committed to.

    Empty when the brief lacks a ``signature_moves`` section — caller
    interprets that as "all registered moves are available".
    """
    try:
        from services.design_brief_to_prompt import load_brief_from_disk
    except Exception:  # noqa: BLE001
        return set()
    try:
        brief = load_brief_from_disk(output_dir)
    except Exception:  # noqa: BLE001
        return set()
    if brief is None:
        return set()
    moves = getattr(brief, "signature_moves", None) or []
    out: set[str] = set()
    for m in moves:
        if isinstance(m, dict):
            k = m.get("kind") or m.get("name") or m.get("id")
            if isinstance(k, str) and k.strip():
                out.add(k.strip())
        elif isinstance(m, str) and m.strip():
            out.add(m.strip())
    return out


def _component_shortlist_block(page_type: str) -> str:
    """A curated per-archetype palette with composition hints (not just prop
    schemas). Complements — doesn't replace — the full component catalog
    that ``schema_prompt`` still injects.

    The point isn't to enumerate every component (the LLM sees that
    elsewhere). It's to tell the model which components a designer reaches
    for FIRST on this archetype, and how they compose. Anti-patterns are
    called out inline so a wrong choice reads as wrong."""
    if page_type == "dashboard":
        return _DASHBOARD_PALETTE
    return ""


_DASHBOARD_PALETTE = """<component-palette page-type="dashboard">
The components a designer reaches for FIRST on a manager/operations
dashboard. Compose freely — this is the vocabulary, not a checklist.

KPI ROW (top of the page — the scan-first summary):
  · Card > Stack containing:
      · Row: uppercase tracked label (muted) + IconTile (32-36px rounded
        square, brand color at 15% alpha, icon inside)
      · Big number (display scale, bold, primary foreground)
      · Sub-context line ("Across 4 cities", "91.25% occupancy")
      · Delta indicator: arrow (↗/↘) + colored text (green good / red bad)
        + comparison ("+2.1% vs last month")
    Each KPI carries FIVE pieces of information: label, icon, number,
    context, delta. Not just "TOTAL_UNITS: 0".
    ANTI-PATTERN: bare label + big number floating without a Card, no
    icon, no delta. That reads as page metadata, not a metric.

HERO CHART (primary content — earns the biggest slot):
  · Chart type=area — gradient-filled, brand color as the primary series.
    Include axis grid, formatted axis labels, inline legend top-right.
    Container: Card with title + optional date-range subtitle
    ("Feb — Aug 2026").
  · Chart type=line for multi-series time series (no fill).
  · Chart type=bar / pie / funnel for categorical breakdowns.
  ANTI-PATTERN: an empty dashed rectangle with a single "Payment"
  legend chip below it. If there's no data yet, author an empty state
  (see below).

SECONDARY RAIL (right of the hero — supporting context):
  · Card > Stack of Progress bars for goal-vs-actual metrics. Each
    Progress row: label + value on one line, then the bar. Show 3-4.
  · Below the progress bars: a small UPCOMING section — 2-3 dated
    items with right-aligned dates ("Nov 30", "Aug 15").

RICH LISTS (bottom row — recent activity, top items):
  · List with rich rowTemplate: two-line rows (title + subtitle), right-
    aligned metric or status pill, optional thumbnail image if the entity
    has a media field. "View all →" affordance in the section header.
  ANTI-PATTERN: a full data-table with a Search box and sortable column
  headers on a DASHBOARD. Dashboard lists are feeds/summaries, not
  tables. Full-fidelity tables belong on index pages.

STATUS EXPRESSIONS (use consistently):
  · Tag/Chip — status pill, semantic color. "In Progress" = amber,
    "Open" = blue, "Resolved" = green. Same mapping everywhere.
  · Colored dot before item title in list rows for at-a-glance status.

EYEBROW PATTERN (recommended editorial signature):
  · Above the page title: monospace, letter-spaced uppercase subtitle
    ("Portfolio overview · Aug 2026"). Same treatment for KPI labels and
    section eyebrows. Gives the page editorial character and consistent
    hierarchy for meta-info.

LAYOUT COMPOSITION (typical dashboard shape):
  · Top row: 4 KPI cards, evenly spaced (grid columns=4 gap=4).
  · Middle row: hero chart (2/3 or 3/4 width) + secondary rail (1/3 or 1/4).
  · Bottom row: 1-2 rich list cards, evenly spaced.
  · Never: charts left / KPIs stacked right (inverts reading order).
  · Never: a widget grid where every cell has identical visual weight.

EMPTY STATE (author every widget's zero-data view):
  · Icon or IllustratedEmpty component + one-line plain-language message
    + primary CTA that lets the user create data.
  Example: an empty payments chart shows "No payment data yet — record
  a payment to see the breakdown" + "Record payment" button.
  ANTI-PATTERN: dashed rectangle with no message. Reads as broken.
</component-palette>"""


# ── Synthesis helpers ────────────────────────────────────────────────────

def _guess_actor(plan: dict, page: dict) -> str:
    role = (page.get("role") or "").strip()
    if role:
        return _humanize(role)
    actors = plan.get("actors") or []
    if isinstance(actors, list) and actors:
        first = actors[0]
        if isinstance(first, dict):
            name = first.get("name") or first.get("role") or first.get("label")
            if isinstance(name, str) and name.strip():
                return _humanize(name)
        elif isinstance(first, str) and first.strip():
            return _humanize(first)
    return "user"


def _synthesize_goal(entity: str, widgets: list, actions: list) -> str:
    """One-sentence "what this reader needs" for a dashboard page."""
    if entity:
        return (
            f"Get a scan-first view of {_humanize(entity)} health, spot the "
            f"one thing that needs attention right now, and act on it in "
            f"≤2 clicks."
        )
    if widgets and isinstance(widgets, list):
        topics = _widget_topics(widgets)
        if topics:
            joined = ", ".join(topics[:-1]) + f" and {topics[-1]}" if len(topics) > 1 else topics[0]
            return (
                f"Get a scan-first view of {joined}, spot anything that "
                f"needs attention right now, and act on it in ≤2 clicks."
            )
    return (
        "Get a scan-first view of the app's operational health and act on "
        "anything that needs attention in ≤2 clicks."
    )


def _synthesize_reading_priorities(
    widgets: list, actions: list, entity: str,
) -> list[str]:
    """Ordered priorities for what the reader looks at first, second, third.
    Kept short — 3 items — because the LLM should compose to this shape."""
    priorities: list[str] = ["At-a-glance operational health (KPIs)"]
    if entity or (isinstance(widgets, list) and widgets):
        priorities.append("The one item that needs attention right now")
    priorities.append("Recent activity and trend over time")
    return priorities


def _widget_topics(widgets: list) -> list[str]:
    seen: list[str] = []
    for w in widgets:
        if not isinstance(w, dict):
            continue
        topic = (
            w.get("title") or w.get("label") or w.get("entity") or w.get("column")
        )
        if not (isinstance(topic, str) and topic.strip()):
            continue
        human = _humanize(topic.strip())
        if human and human not in seen:
            seen.append(human)
    return seen[:4]


# ── Small helpers ────────────────────────────────────────────────────────

def _move_kind(m: Any) -> str:
    if isinstance(m, dict):
        k = m.get("kind") or m.get("name") or m.get("id")
        return str(k).strip() if k else ""
    return ""


_CAMEL_SPLIT = re.compile(r"([a-z0-9])([A-Z])")


def _humanize(s: str) -> str:
    """snake_case / camelCase / kebab-case → Human Readable words."""
    if not isinstance(s, str):
        return ""
    s = s.strip()
    if not s:
        return ""
    s = _CAMEL_SPLIT.sub(r"\1_\2", s)
    s = s.replace("-", "_").replace(".", "_").replace(" ", "_")
    parts = [p for p in s.split("_") if p]
    return " ".join(p.capitalize() for p in parts)

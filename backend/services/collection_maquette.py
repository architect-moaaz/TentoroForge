"""Collection-page decisions — LLM authors the content + moments
decisions for one collection page (list / kanban / calendar / cards /
timeline).

Parallel to :mod:`services.dashboard_maquette` for the collection page
type. Composer wiring is deferred to a follow-up — this module owns:

- The :class:`CollectionMaquette` data shape (columns + layout + row
  treatment + filter presets + hero + empty-state + signature moves +
  footer).
- Validation-in-parse via :meth:`CollectionMaquette.from_dict` — invalid
  fields are dropped, never raise. Callers decide whether the partial
  result meets their richness contract.
- The LLM authoring turn (:func:`author_collection_maquette`) with a
  strict output contract + entity-aware prompt + Phase 2 moments-layer
  extensions (personality signals, variance seed, 21st.dev references).

Behavioural notes:

- Every ``column`` value MUST reference a real column on the entity —
  the LLM sees an entity-scoped column list in the user prompt and
  the parser drops columns that don't appear.
- Only ONE collection maquette exists per collection page. Multi-page
  apps that want decisions for every collection call this once per
  ``page.entity`` — the caller manages that fanout (there's no "author
  all collections in one turn" seam here because each page is
  independent and prompts stay smaller per-page).
- The maquette is not the schema. A separate composer reads the
  maquette + rewrites the collection page's schema JSON in place.
- Follows the same "one authority per artifact" pattern as
  :mod:`services.dashboard_maquette`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────── vocabulary ────────────────────────────────

# Layout picker — the composer branches on this to select the top-level
# component (Table / Kanban / Calendar / a Row of Cards / a
# TimelineList). "table" is the safe default when nothing else fits.
COLLECTION_LAYOUTS = (
    "table",     # default — dense, sortable, filterable
    "kanban",    # groups by a status/stage column
    "calendar",  # events keyed to a date/timestamp column
    "cards",     # photo-forward or people-forward card grid
    "timeline",  # chronological read view (feeds, audit trails)
)

# Row treatment — how much visual weight each row gets. Composer maps
# this to typography + spacing + photo affordances.
ROW_TREATMENTS = (
    "compact",        # single-line rows, dense; admin/fintech default
    "cozy",           # balanced default; two lines allowed
    "photo-forward",  # left avatar / photo; people/product lists
    "status-led",     # leading status pill; approval / task inboxes
    "narrative",      # multi-line with prose subtitle; content lists
)

# Empty-state illustration keys — the renderer maps each to a
# curated SVG (see services/deterministic_strings + IllustratedEmpty
# component in the library). The LLM picks by mood, not by asset name.
EMPTY_STATE_ILLUSTRATIONS = (
    "welcome-mat",       # neutral onboarding
    "clipboard-blank",   # task / form inboxes
    "empty-calendar",    # calendar view with no events
    "empty-inbox",       # notifications / approvals
    "planted-seed",      # early-adopter / first-run
    "sunlit-window",     # editorial / consumer
    "quiet-cafe",        # hospitality / wellness
    "workshop-bench",    # ops / admin
    "map-with-pin",      # location / real-world entities
    "storefront-open",   # commerce / retail
)


# ─────────────────────────── data shapes ───────────────────────────────


@dataclass
class ColumnSpec:
    """One column shown in the collection view.

    ``name`` is the column key from the entity registry (must exist).
    ``label`` is the human-readable header (LLM authors this).
    ``kind`` gives the renderer a hint — otherwise it's inferred from
    the underlying SQL type.
    """

    name: str
    label: str
    kind: Optional[str] = None  # "text" | "badge" | "date" | "money" | "photo" | "link"
    emphasis: bool = False       # primary column, gets extra weight

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"name": self.name, "label": self.label}
        if self.kind:
            d["kind"] = self.kind
        if self.emphasis:
            d["emphasis"] = True
        return d


@dataclass
class FilterPresetSpec:
    """A named filter chip the user can toggle above the collection.

    ``expr`` is a plain-English filter (e.g. ``"status=active"``,
    ``"createdAt > 7 days ago"``); the composer + runtime translate it
    to a real query. LLM authors filters that fit the domain — a
    booking system's presets are different from a helpdesk's.
    """

    label: str
    expr: str

    def to_dict(self) -> dict:
        return {"label": self.label, "expr": self.expr}


@dataclass
class EmptyStateSpec:
    """The moment the collection has no rows — often the first thing a
    new user sees, so it's a real design opportunity."""

    illustration: str  # one of EMPTY_STATE_ILLUSTRATIONS
    headline: str
    subhead: Optional[str] = None
    cta_label: Optional[str] = None
    cta_action: Optional[str] = None  # workflow id / route

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"illustration": self.illustration, "headline": self.headline}
        if self.subhead:
            d["subhead"] = self.subhead
        if self.cta_label:
            d["cta_label"] = self.cta_label
        if self.cta_action:
            d["cta_action"] = self.cta_action
        return d


@dataclass
class CollectionHeroSpec:
    """Small hero band above the collection — different from a full
    dashboard hero. Just a title + optional subtitle + optional badge
    (e.g. row count).
    """

    title: str
    subtitle: Optional[str] = None
    badge: Optional[str] = None  # e.g. "12 open", "3 needing review"

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"title": self.title}
        if self.subtitle:
            d["subtitle"] = self.subtitle
        if self.badge:
            d["badge"] = self.badge
        return d


@dataclass
class CollectionFooterSpec:
    """Optional footer band beneath the collection — total row, batch
    action strip, insight callout, "add another" affordance. LLM leaves
    this empty for most collections; it's a moment, not a chrome default.
    """

    kind: str  # "total-row" | "batch-actions" | "insight" | "add-affordance"
    content: Optional[str] = None  # human copy for insight/callout

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"kind": self.kind}
        if self.content:
            d["content"] = self.content
        return d


@dataclass
class CollectionMaquette:
    """The whole content + moments spec for one collection page.

    Composer reads this and rewrites the page's schema JSON. The
    ``entity`` and ``route`` fields anchor the maquette to its page —
    the composer uses ``route`` to pick the schema file to rewrite.
    """

    entity: str
    route: str
    layout: str = "table"
    columns: list[ColumnSpec] = field(default_factory=list)
    row_treatment: str = "cozy"
    filter_presets: list[FilterPresetSpec] = field(default_factory=list)
    hero: Optional[CollectionHeroSpec] = None
    empty_state: Optional[EmptyStateSpec] = None
    footer: Optional[CollectionFooterSpec] = None
    signature_moves: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entity": self.entity,
            "route": self.route,
            "layout": self.layout,
            "columns": [c.to_dict() for c in self.columns],
            "row_treatment": self.row_treatment,
            "filter_presets": [f.to_dict() for f in self.filter_presets],
            "hero": self.hero.to_dict() if self.hero else None,
            "empty_state": self.empty_state.to_dict() if self.empty_state else None,
            "footer": self.footer.to_dict() if self.footer else None,
            "signature_moves": list(self.signature_moves),
        }

    @classmethod
    def from_dict(cls, obj: dict, *, valid_columns: set[str] | None = None) -> "CollectionMaquette | None":
        """Parse an LLM response. Returns None when the required fields
        (``entity``, ``route``) are missing or invalid — the caller
        decides whether to fall back to the deterministic builder.

        ``valid_columns`` (optional) is the set of real column names for
        ``entity``. When passed, columns not in the set are dropped —
        the LLM occasionally hallucinates a column that doesn't exist.
        Callers who don't have the registry handy can omit it and rely
        on downstream binding-validator to catch the drift.
        """
        if not isinstance(obj, dict):
            return None
        entity = obj.get("entity")
        route = obj.get("route")
        if not (isinstance(entity, str) and entity and
                isinstance(route, str) and route.startswith("/")):
            return None

        m = cls(entity=entity, route=route)

        layout = obj.get("layout")
        if isinstance(layout, str) and layout in COLLECTION_LAYOUTS:
            m.layout = layout
        # else: keep default "table"

        # Columns — drop anything without a name; when valid_columns
        # is supplied, also drop columns the entity doesn't have.
        for col in obj.get("columns") or []:
            if not isinstance(col, dict):
                continue
            name = col.get("name")
            label = col.get("label") or (name if isinstance(name, str) else "")
            if not (isinstance(name, str) and name):
                continue
            if valid_columns is not None and name not in valid_columns:
                continue
            kind = col.get("kind") if isinstance(col.get("kind"), str) else None
            m.columns.append(ColumnSpec(
                name=name,
                label=str(label),
                kind=kind,
                emphasis=bool(col.get("emphasis")),
            ))

        row_treatment = obj.get("row_treatment")
        if isinstance(row_treatment, str) and row_treatment in ROW_TREATMENTS:
            m.row_treatment = row_treatment
        # else: keep default "cozy"

        # Filter presets — need both label + expr.
        for fp in obj.get("filter_presets") or []:
            if not isinstance(fp, dict):
                continue
            label = fp.get("label")
            expr = fp.get("expr")
            if isinstance(label, str) and label and isinstance(expr, str) and expr:
                m.filter_presets.append(FilterPresetSpec(label=label, expr=expr))

        hero = obj.get("hero")
        if isinstance(hero, dict):
            title = hero.get("title")
            if isinstance(title, str) and title:
                m.hero = CollectionHeroSpec(
                    title=title,
                    subtitle=hero.get("subtitle") if isinstance(hero.get("subtitle"), str) else None,
                    badge=hero.get("badge") if isinstance(hero.get("badge"), str) else None,
                )

        empty = obj.get("empty_state")
        if isinstance(empty, dict):
            illustration = empty.get("illustration") if isinstance(empty.get("illustration"), str) else "welcome-mat"
            # Unknown illustration → safe default, so composer always has
            # a valid asset key to render.
            if illustration not in EMPTY_STATE_ILLUSTRATIONS:
                illustration = "welcome-mat"
            headline = empty.get("headline")
            if isinstance(headline, str) and headline:
                m.empty_state = EmptyStateSpec(
                    illustration=illustration,
                    headline=headline,
                    subhead=empty.get("subhead") if isinstance(empty.get("subhead"), str) else None,
                    cta_label=empty.get("cta_label") if isinstance(empty.get("cta_label"), str) else None,
                    cta_action=empty.get("cta_action") if isinstance(empty.get("cta_action"), str) else None,
                )

        footer = obj.get("footer")
        if isinstance(footer, dict):
            kind = footer.get("kind")
            if isinstance(kind, str) and kind in ("total-row", "batch-actions", "insight", "add-affordance"):
                m.footer = CollectionFooterSpec(
                    kind=kind,
                    content=footer.get("content") if isinstance(footer.get("content"), str) else None,
                )

        for sm in obj.get("signature_moves") or []:
            if isinstance(sm, str) and sm.strip():
                m.signature_moves.append(sm.strip())

        return m


# ─────────────────────────── contract check ────────────────────────────


def meets_richness_contract(
    m: CollectionMaquette,
    *,
    min_columns: int = 3,
    require_empty_state: bool = True,
    require_hero: bool = False,
) -> list[str]:
    """Return a list of missing-requirement labels. Empty → contract met.

    Different from the dashboard contract — collections rarely need a
    hero, but SHOULD always have an empty-state (that's the moment new
    users see first). Composer callers decide whether to fall back to
    the deterministic builder when a requirement is missing.
    """
    missing: list[str] = []
    if len(m.columns) < min_columns:
        missing.append(f"columns(need ≥{min_columns}, got {len(m.columns)})")
    if require_empty_state and m.empty_state is None:
        missing.append("empty_state")
    if require_hero and m.hero is None:
        missing.append("hero")
    return missing


# ─────────────────────────── LLM prompts ───────────────────────────────


def _build_system_prompt() -> str:
    return f"""\
You are the collection-page content director. Given an entity from the
app's plan + optional design brief, decide the collection page's
content — WHICH columns to show, WHICH layout fits, WHAT filter chips
matter, HOW the empty state feels, WHERE the signature moves land.

The rendering is deterministic downstream. Your job is judgment:
which 4–6 columns a real user actually scans, which layout fits the
data shape, which filter presets they'd toggle first thing Monday,
what the empty state SAYS to a new user.

OUTPUT CONTRACT
Emit ONE JSON object exactly matching this shape (no markdown fences):

{{
  "entity": "<entity_name — must match the plan>",
  "route": "/<page-route — matches the plan page>",
  "layout": {" | ".join(f'"{l}"' for l in COLLECTION_LAYOUTS)},
  "columns": [
    {{
      "name": "<real column name on the entity>",
      "label": "Human-readable header",
      "kind": "text" | "badge" | "date" | "money" | "photo" | "link" | null,
      "emphasis": true  // set true on the ONE primary column
    }}, ...
  ],
  "row_treatment": {" | ".join(f'"{r}"' for r in ROW_TREATMENTS)},
    // compact = dense/admin; cozy = balanced default; photo-forward =
    // people/products; status-led = approvals/tasks; narrative =
    // content lists with prose subtitles.
  "filter_presets": [
    {{"label": "Chip label", "expr": "status=active"}},
    {{"label": "This week", "expr": "createdAt > 7 days ago"}}
  ],
  "hero": {{
    "title": "Optional band-title above the collection",
    "subtitle": "Optional secondary line",
    "badge": "Optional row-count teaser like '12 open'"
  }} | null,
  "empty_state": {{
    "illustration": "welcome-mat" | "clipboard-blank" | "empty-calendar"
      | "empty-inbox" | "planted-seed" | "sunlit-window" | "quiet-cafe"
      | "workshop-bench" | "map-with-pin" | "storefront-open",
    "headline": "What a new user sees when the list is empty",
    "subhead": "Optional secondary explanation",
    "cta_label": "Optional button label like 'Book your first class'",
    "cta_action": "Optional workflow-id or route the button targets"
  }} | null,
  "footer": {{
    "kind": "total-row" | "batch-actions" | "insight" | "add-affordance",
    "content": "Optional copy for insight / callout kinds"
  }} | null,
  "signature_moves": [
    // 1-3 signature-move ids from the catalog (see
    // archetypes/signature_moves.json). Examples for collections:
    //   "sparkline-preview" (Table with tiny inline sparkline column)
    //   "column-headers-with-counts" (Kanban lane headers show counts)
    //   "photo-forward-row" (photo/avatar prominent in row)
    //   "quick-peek-on-hover" (row hover reveals expanded card)
    //   "grouped-by-day" (Calendar with day headers)
    //   "sticky-first-column" (Table with pinned first column)
  ]
}}

STRICT RULES
1. Every column `name` MUST be a real column on the entity — see the
   entity column list in the user prompt. Do NOT invent columns.
2. Emit 4–6 columns. Fewer feels sparse; more feels crowded on
   normal screens.
3. Exactly ONE column has `emphasis: true` — the primary field a
   scanner's eye lands on first.
4. Choose `layout` to fit the data:
   - date/timestamp anchor + <100 rows → `calendar`
   - status/stage column driving the flow → `kanban`
   - photo/avatar column present + people/products focus → `cards`
   - chronological, read-only, feed-shaped → `timeline`
   - everything else → `table`
5. `filter_presets` are the 2–4 filters a domain owner would toggle
   first — not every possible filter, just the ones that matter Monday
   morning. Domain-shaped ("Overdue", "Awaiting review") beats
   generic ("Filter by status").
6. `empty_state.headline` is a design moment. First-run copy. Warm,
   specific, not "No records found." Example: "Your practice starts
   here. Book your first class." Not "There are no items to display."
7. `footer` is optional and usually null. Only fill it when there's
   a real moment (total for money-typed lists, batch actions for
   bulk-review inboxes, insight callout for KPI-adjacent lists).
8. `signature_moves` — 1-3 ids from the catalog that give this
   collection personality. Two collections in the same app should
   pick DIFFERENT ids. Look at the personality signals + variance
   hint in the user prompt to break ties.
9. Return JSON only. No prose. No markdown fences.
"""


def _domain_page_block(plan: dict, entity_name: str, entity_meta: dict,
                       kind: str) -> str:
    """The archetype vocabulary's answer to "what does this screen SHOW?".

    Shape was already domain-informed; content was not, so which columns
    reached a list and how a record grouped its fields were free choices
    on every page of every app. This hands the author the industry's own
    reading order, already filtered to columns this app really built.
    Silent no-op when the archetype has no recipe for the entity.
    """
    try:
        from services.page_vocabulary import (
            resolve_page_recipe, vocabulary_for_plan,
        )
    except Exception:  # noqa: BLE001
        return ""
    vocab = vocabulary_for_plan(plan)
    if vocab is None:
        return ""
    r = resolve_page_recipe(vocab, entity_name, entity_meta)
    if not r:
        return ""
    lines = [
        "",
        f"## WHAT THIS DOMAIN SHOWS FOR {entity_name.upper()} (authoritative)",
        f"Archetype: {getattr(vocab, 'id', '?')}. This is the reading order",
        "people in this business expect. Lead with it. You may relabel for",
        "tone and add a column the brief calls for; do not reorder it into",
        "an id-and-timestamp dump.",
    ]
    if kind == "collection" and r.get("list_columns"):
        lines.append("Columns, in order: " + ", ".join(r["list_columns"]))
        if r.get("filter_chips"):
            lines.append("Worth a filter chip: " + ", ".join(r["filter_chips"]))
    if kind == "record" and r.get("detail_sections"):
        lines.append("Field groups, in order:")
        for sec in r["detail_sections"]:
            lines.append(f"  - {sec['label']}: {', '.join(sec['fields'])}")
    return "\n".join(lines) + "\n" if len(lines) > 6 else ""


def _build_user_prompt(
    plan: dict,
    entity_name: str,
    entity_meta: dict,
    route: str,
    brief_text: str | None,
) -> str:
    columns = entity_meta.get("fields") or entity_meta.get("columns") or []
    column_lines: list[str] = []
    if isinstance(columns, list):
        for f in columns:
            if isinstance(f, dict):
                fn = f.get("name") or f.get("column")
                ft = f.get("type") or f.get("sqlType")
                nn = " NOT NULL" if f.get("required") else ""
                if fn:
                    column_lines.append(f"  - {fn}: {ft or 'unknown'}{nn}")
    elif isinstance(columns, dict):
        for fn, meta in columns.items():
            ft = None
            if isinstance(meta, dict):
                ft = meta.get("type") or meta.get("sqlType")
            column_lines.append(f"  - {fn}: {ft or 'unknown'}")

    domain = plan.get("domain") or "generic"
    module_name = plan.get("module_name") or "App"
    brief_line = f"\nUser's brief: {brief_text}\n" if brief_text else ""

    # Phase 2 propagation (same helpers as dashboard maquette).
    from services.dashboard_maquette import _extract_personality_signals, _read_21st_references
    signals = _extract_personality_signals(brief_text)
    personality_block = ""
    if signals:
        personality_block = (
            "\nPERSONALITY SIGNALS (steer layout + row_treatment + "
            "signature_moves toward these):\n"
            + "\n".join(f"  • {s}" for s in signals)
            + "\n"
        )

    from services.pipeline.variance import variance_hint_line
    _variance = variance_hint_line(plan)
    variance_block = f"\n{_variance}\n" if _variance else ""

    refs = _read_21st_references(plan)
    references_block = ""
    if refs:
        references_block = (
            "\nDESIGN REFERENCES (shape inspiration for cards / rows /"
            " filters — not verbatim copies):\n"
            + "\n".join(f"  • {r}" for r in refs)
            + "\n"
        )

    # MONTAGE COMPOSITION. The design-reference montage says what a screen
    # of this kind carries and how dense it is — the bar this page should
    # meet. Shape only: it never names entities/columns (the plan and
    # registry below own those) and carries no colour (the picked design
    # option owns that). Empty string when no montage was designated.
    from services.montage_composition import load_composition_block
    composition_block = load_composition_block(plan)

    return f"""\
App: {module_name}
Domain: {domain}
{brief_line}{personality_block}{variance_block}{references_block}{composition_block}
COLLECTION PAGE
  entity: {entity_name}
  route:  {route}

Entity columns:
{chr(10).join(column_lines) if column_lines else '  (no columns listed)'}

{_domain_page_block(plan, entity_name, entity_meta, "collection")}
Emit the collection maquette JSON now."""


# ─────────────────────────── LLM authoring ─────────────────────────────


async def author_collection_maquette(
    plan: dict,
    entity_name: str,
    route: str,
    *,
    brief_text: str | None = None,
    query_fn: Any | None = None,
    timeout_seconds: float = 45.0,
) -> CollectionMaquette | None:
    """Call the LLM to produce a collection maquette for ONE page.

    Multi-page apps that want maquettes for every collection call this
    once per page — there is intentionally no "author all collections
    in one turn" seam because per-page prompts stay smaller + focused
    on a single entity.

    Returns None on any failure (missing entity in plan, malformed LLM
    output, timeout). Never raises.

    Args:
        plan: The full plan dict (entities + description + domain).
        entity_name: The entity the page shows.
        route: The page's route (e.g. ``/sessions``).
        brief_text: Optional original user brief — steers moments.
        query_fn: Injectable ``async (system, user) -> str`` for tests.
        timeout_seconds: Hard cap on the LLM call.
    """
    if not isinstance(plan, dict):
        return None
    entities = plan.get("entities")
    if not isinstance(entities, dict):
        return None
    entity_meta = entities.get(entity_name)
    if not isinstance(entity_meta, dict):
        # Unknown entity — caller passed an entity not in the plan.
        # Return None rather than author a maquette that references
        # something the schema doesn't have.
        return None

    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(plan, entity_name, entity_meta, route, brief_text)

    if query_fn is not None:
        try:
            text = await query_fn(system_prompt, user_prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[collection-maquette] injected query_fn failed: %s", exc)
            return None
    else:
        api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            logger.warning("[collection-maquette] no ANTHROPIC_API_KEY; skipping")
            return None
        try:
            text = await asyncio.wait_for(
                _default_query(system_prompt, user_prompt),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("[collection-maquette] LLM timed out after %ss", timeout_seconds)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[collection-maquette] LLM call failed: %s", exc)
            return None

    parsed = _extract_json_object(text)
    if parsed is None:
        logger.warning("[collection-maquette] response did not contain a JSON object")
        return None

    # Build the valid_columns set from the entity so from_dict can drop
    # hallucinated column names.
    valid_columns = _valid_columns_from(entity_meta)
    return CollectionMaquette.from_dict(parsed, valid_columns=valid_columns)


def _valid_columns_from(entity_meta: dict) -> set[str]:
    """Return the set of real column names on an entity."""
    out: set[str] = set()
    fields = entity_meta.get("fields") or entity_meta.get("columns") or []
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict):
                name = f.get("name") or f.get("column")
                if isinstance(name, str) and name:
                    out.add(name)
    elif isinstance(fields, dict):
        out.update(k for k in fields.keys() if isinstance(k, str))
    return out


# ─────────────────────────── JSON extract ──────────────────────────────


def _extract_json_object(text: str | None) -> dict | None:
    """Best-effort JSON object extract — the same logic
    :mod:`services.dashboard_maquette` uses, kept independent to avoid
    coupling on that module's private surface."""
    if not text or not text.strip():
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        # Strip a markdown fence — first line is the fence, last line is closing.
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    try:
        obj = json.loads(stripped)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass
    # Balance-scan fallback — find the first `{` and match braces
    # respecting strings, in case the LLM wrapped JSON in prose.
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(stripped):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(stripped[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except Exception:  # noqa: BLE001
                    return None
    return None


async def _default_query(system: str, user: str) -> str:
    """Live LLM call — same shape as dashboard_maquette's default.

    Kept independent so tests can monkeypatch this module without
    accidentally patching the dashboard path.
    """
    from services.llm_client import AsyncAnthropic  # LangGraph migration (LG-1)
    client = AsyncAnthropic()
    resp = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts = []
    for block in resp.content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)

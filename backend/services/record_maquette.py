"""Record-page decisions — LLM authors the content + moments
decisions for one record page (create / edit / view detail).

Parallel to :mod:`services.dashboard_maquette` +
:mod:`services.collection_maquette`. Composer wiring lives in
:mod:`services.apply_record_maquette`.

This module owns:

- The :class:`RecordMaquette` data shape (mode + section_grouping +
  field_ordering + control_hints + hero + signature_moves + footer).
- Validation-in-parse via :meth:`RecordMaquette.from_dict` — invalid
  fields are dropped, never raise. Callers decide whether the partial
  result meets their richness contract.
- The LLM authoring turn (:func:`author_record_maquette`) with a
  strict output contract + entity-aware prompt + Phase 2 moments
  extensions (personality signals, variance seed, 21st.dev references).

Behavioural notes:

- Every field in ``section_grouping[].fields`` and ``field_ordering``
  MUST reference a real column on the entity — the LLM sees an
  entity-scoped column list in the user prompt and the parser drops
  unknown names.
- ``control_hints[field]`` values MUST be one of the renderer's
  known control types (see ``FIELD_CONTROL_HINTS``); unknown values
  are dropped so the composer never emits a broken control.
- Only ONE record maquette exists per record page. Multi-page apps
  fanout by calling this once per (entity, route, mode) triple.
- The maquette is not the schema. A separate composer reads the
  maquette and rewrites the record page's schema JSON in place.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────── vocabulary ────────────────────────────────

# The three record modes. Every generated app has, at minimum, an
# edit-record page for each writable entity; ``view`` is the read-only
# detail page (dashboard-style key-value display); ``create`` is the
# blank-slate first-write form.
RECORD_MODES = ("view", "edit", "create")

# Curated control-type hints. Composer maps each to a real component.
# The list intentionally excludes low-signal defaults (Input, Textarea)
# — the composer picks those on its own when no hint is present.
FIELD_CONTROL_HINTS = (
    "select",              # enum / relational FK dropdown
    "combobox",            # typeahead FK with search
    "radio-group",         # small enum (≤5), horizontal buttons
    "switch",              # bool
    "date-picker",         # date-only
    "date-range",          # date-range picker
    "time-picker",         # time-only
    "datetime-picker",     # timestamp
    "number-input",        # numeric with step
    "slider",              # range with visible track
    "rating",              # 1-5 star / heart / thumb
    "color-picker",        # hex or named palette
    "file-upload",         # image / doc / any
    "camera-capture",      # in-browser photo
    "signature",           # touch/mouse signature pad
    "rich-text",           # WYSIWYG
    "markdown",            # markdown source with preview
    "code-block",          # monospace code w/ syntax
    "textarea",            # long text
    "masked-input",        # phone/ssn/etc formatted
    "otp",                 # one-time code input
    "key-value",           # jsonb dict editor
    "tags",                # multi-select chips
    "money",               # currency w/ symbol + step
    "phone",               # E.164 phone with country
    "url",                 # URL w/ open-in-new-tab affordance
    "email",               # email w/ mailto affordance
)

# Section grouping shape hints — describe how a single section renders
# above the fields it contains. The composer wraps each section in a
# Card and uses the tone to pick heading level + separator style.
SECTION_TONES = (
    "primary",     # first section, bold heading
    "secondary",   # supporting section, calmer heading
    "advanced",    # collapsible "Advanced settings"
    "meta",        # timestamps, ids, audit — read-only in edit mode
    "danger",      # destructive actions, red accent
)

# Hero kinds a record page can adopt. Different from dashboard hero:
# record pages default to a compact page-header, not a photo-greeting.
RECORD_HERO_KINDS = (
    "page-header",     # default: title + subtitle + primary action
    "media-lead",      # left-aligned image/avatar + title (for entities with a photo/logo)
    "status-led",      # leading status pill above title (approval/task detail)
    "editorial",       # centred title + eyebrow, generous whitespace
    "breadcrumbs",     # explicit path with parent entity links
)


# ─────────────────────────── data shapes ───────────────────────────────


@dataclass
class SectionSpec:
    """A grouped block of fields.

    ``label`` is the section heading (human copy). ``fields`` is an
    ordered list of column names to render inside the section. ``tone``
    controls the visual weight (primary/secondary/advanced/meta/danger).
    ``collapsible`` defaults to True for advanced sections and False
    otherwise.
    """

    label: str
    fields: list[str] = field(default_factory=list)
    tone: str = "primary"
    collapsible: Optional[bool] = None
    subhead: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "label": self.label,
            "fields": list(self.fields),
            "tone": self.tone,
        }
        if self.collapsible is not None:
            d["collapsible"] = bool(self.collapsible)
        if self.subhead:
            d["subhead"] = self.subhead
        return d


@dataclass
class RecordHeroSpec:
    """Hero band above the record page.

    Compact by default. ``kind`` decides layout; the composer branches
    on it exactly like the dashboard composer branches on hero kinds.
    """

    kind: str = "page-header"
    title: str = ""
    subtitle: Optional[str] = None
    status_field: Optional[str] = None  # only for kind="status-led"
    media_field: Optional[str] = None   # only for kind="media-lead"
    eyebrow: Optional[str] = None       # only for kind="editorial"

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"kind": self.kind, "title": self.title}
        for k in ("subtitle", "status_field", "media_field", "eyebrow"):
            v = getattr(self, k)
            if v:
                d[k] = v
        return d


@dataclass
class RecordFooterSpec:
    """Optional footer beneath the record form.

    ``kind`` selects a template: ``timestamps`` for created/updated
    display, ``danger-zone`` for the destructive-actions card, ``audit``
    for a history/audit-trail link, ``related`` for a jump-to-related
    strip.
    """

    kind: str  # "timestamps" | "danger-zone" | "audit" | "related"
    content: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"kind": self.kind}
        if self.content:
            d["content"] = self.content
        return d


@dataclass
class RecordMaquette:
    """The whole content + moments spec for one record page.

    Composer reads this and rewrites the page's schema JSON. ``entity``
    + ``route`` + ``mode`` uniquely identify the target page — the
    composer uses them to pick the right schema file.
    """

    entity: str
    route: str
    mode: str = "edit"
    section_grouping: list[SectionSpec] = field(default_factory=list)
    field_ordering: list[str] = field(default_factory=list)
    control_hints: dict[str, str] = field(default_factory=dict)
    hero: Optional[RecordHeroSpec] = None
    footer: Optional[RecordFooterSpec] = None
    signature_moves: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entity": self.entity,
            "route": self.route,
            "mode": self.mode,
            "section_grouping": [s.to_dict() for s in self.section_grouping],
            "field_ordering": list(self.field_ordering),
            "control_hints": dict(self.control_hints),
            "hero": self.hero.to_dict() if self.hero else None,
            "footer": self.footer.to_dict() if self.footer else None,
            "signature_moves": list(self.signature_moves),
        }

    @classmethod
    def from_dict(cls, obj: dict, *, valid_columns: set[str] | None = None) -> "RecordMaquette | None":
        """Parse an LLM response. Returns None when required fields
        (``entity``, ``route``) are missing or invalid.

        ``valid_columns`` (optional) is the set of real column names for
        ``entity``. When passed, field references not in the set are
        dropped from ``section_grouping[].fields``, ``field_ordering``,
        ``control_hints``, and ``hero.status_field`` / ``hero.media_field``.
        """
        if not isinstance(obj, dict):
            return None
        entity = obj.get("entity")
        route = obj.get("route")
        if not (isinstance(entity, str) and entity and
                isinstance(route, str) and route.startswith("/")):
            return None

        m = cls(entity=entity, route=route)

        mode = obj.get("mode")
        if isinstance(mode, str) and mode in RECORD_MODES:
            m.mode = mode
        # else: keep default "edit"

        # ── section grouping ─────────────────────────────────────────
        for sec in obj.get("section_grouping") or []:
            if not isinstance(sec, dict):
                continue
            label = sec.get("label")
            if not (isinstance(label, str) and label.strip()):
                continue
            fields = sec.get("fields") or []
            clean_fields: list[str] = []
            for fn in fields:
                if not (isinstance(fn, str) and fn.strip()):
                    continue
                if valid_columns is not None and fn not in valid_columns:
                    continue
                clean_fields.append(fn)
            if not clean_fields:
                # An empty section is a bug — the composer would render
                # a heading with no content. Drop it.
                continue
            tone = sec.get("tone")
            if not (isinstance(tone, str) and tone in SECTION_TONES):
                tone = "primary"
            collapsible = sec.get("collapsible")
            if collapsible is not None:
                collapsible = bool(collapsible)
            subhead = sec.get("subhead") if isinstance(sec.get("subhead"), str) else None
            m.section_grouping.append(SectionSpec(
                label=label,
                fields=clean_fields,
                tone=tone,
                collapsible=collapsible,
                subhead=subhead,
            ))

        # ── field ordering ────────────────────────────────────────────
        # Explicit fallback ordering when the composer needs it (e.g.
        # section_grouping omitted entirely).
        for fn in obj.get("field_ordering") or []:
            if not (isinstance(fn, str) and fn.strip()):
                continue
            if valid_columns is not None and fn not in valid_columns:
                continue
            m.field_ordering.append(fn)

        # ── control hints ─────────────────────────────────────────────
        raw_hints = obj.get("control_hints") or {}
        if isinstance(raw_hints, dict):
            for fn, hint in raw_hints.items():
                if not (isinstance(fn, str) and fn.strip()):
                    continue
                if valid_columns is not None and fn not in valid_columns:
                    continue
                if not (isinstance(hint, str) and hint in FIELD_CONTROL_HINTS):
                    # Unknown control hint — drop rather than let the
                    # composer emit a broken component.
                    continue
                m.control_hints[fn] = hint

        # ── hero ──────────────────────────────────────────────────────
        hero = obj.get("hero")
        if isinstance(hero, dict):
            kind = hero.get("kind")
            if not (isinstance(kind, str) and kind in RECORD_HERO_KINDS):
                kind = "page-header"
            title = hero.get("title")
            if isinstance(title, str) and title.strip():
                status_field = hero.get("status_field") if isinstance(hero.get("status_field"), str) else None
                media_field = hero.get("media_field") if isinstance(hero.get("media_field"), str) else None
                # Drop unknown field refs on the hero — otherwise the
                # composer would try to render a status pill from a
                # non-existent column.
                if valid_columns is not None:
                    if status_field and status_field not in valid_columns:
                        status_field = None
                    if media_field and media_field not in valid_columns:
                        media_field = None
                m.hero = RecordHeroSpec(
                    kind=kind,
                    title=title.strip(),
                    subtitle=hero.get("subtitle") if isinstance(hero.get("subtitle"), str) else None,
                    status_field=status_field,
                    media_field=media_field,
                    eyebrow=hero.get("eyebrow") if isinstance(hero.get("eyebrow"), str) else None,
                )

        # ── footer ────────────────────────────────────────────────────
        footer = obj.get("footer")
        if isinstance(footer, dict):
            kind = footer.get("kind")
            if isinstance(kind, str) and kind in ("timestamps", "danger-zone", "audit", "related"):
                m.footer = RecordFooterSpec(
                    kind=kind,
                    content=footer.get("content") if isinstance(footer.get("content"), str) else None,
                )

        # ── signature moves ───────────────────────────────────────────
        for sm in obj.get("signature_moves") or []:
            if isinstance(sm, str) and sm.strip():
                m.signature_moves.append(sm.strip())

        return m


# ─────────────────────────── richness contract ─────────────────────────


def meets_richness_contract(
    m: RecordMaquette,
    *,
    require_section_grouping: bool = True,
    min_fields_grouped: int = 3,
    require_hero: bool = True,
) -> list[str]:
    """Return a list of missing-requirement labels. Empty → contract met.

    Record pages benefit MOST from section grouping — a flat list of
    every column is the exact "same-generator" tell the moments layer
    exists to fix. So section_grouping is required by default and the
    hero is required so the page opens with intent instead of a bare
    form.
    """
    missing: list[str] = []
    if require_section_grouping and not m.section_grouping:
        missing.append("section_grouping")
    else:
        total_grouped = sum(len(s.fields) for s in m.section_grouping)
        if total_grouped < min_fields_grouped:
            missing.append(f"section_grouping.fields(need ≥{min_fields_grouped}, got {total_grouped})")
    if require_hero and m.hero is None:
        missing.append("hero")
    return missing


# ─────────────────────────── LLM prompts ───────────────────────────────


def _build_system_prompt() -> str:
    return f"""\
You are the record-page content director. Given an entity from the
app's plan + the target route + mode + optional design brief, decide
the record page's content — HOW to group its fields into sections,
WHICH controls fit which fields, WHAT the hero says, WHERE the
signature moves land.

The rendering is deterministic downstream. Your job is judgment:
which fields belong together (contact info vs. billing vs. metadata),
which control types the domain actually needs (a Rating for a review
score, a Slider for a percentage, a CameraCapture for an inspection
photo), which fields are advanced-only, what the hero SAYS.

OUTPUT CONTRACT
Emit ONE JSON object exactly matching this shape (no markdown fences):

{{
  "entity": "<entity_name — must match the plan>",
  "route": "/<page-route — matches the plan page>",
  "mode": {" | ".join(f'"{m}"' for m in RECORD_MODES)},
  "section_grouping": [
    {{
      "label": "Contact",
      "fields": ["email", "phone", "address"],
      "tone": {" | ".join(f'"{t}"' for t in SECTION_TONES)},
      "collapsible": true,               // optional; default true for "advanced"
      "subhead": "Optional supporting line"
    }}, ...
  ],
  "field_ordering": ["field1", "field2", ...],
    // Optional fallback ordering. Only needed if section_grouping is
    // empty. Prefer section_grouping — a flat form of 15 fields reads
    // as "generic scaffolding".
  "control_hints": {{
    "email": "email",
    "role": "select",
    "avatar_url": "file-upload",
    "notes": "rich-text"
  }},
    // Only for fields where the DOMAIN implies a specific control the
    // renderer wouldn't infer from the column type alone. Examples:
    //   - a "rating" numeric field → "rating" not "number-input"
    //   - a "percentage" numeric field → "slider" not "number-input"
    //   - a "signature" jsonb → "signature" not "textarea"
    //   - a photo URL → "camera-capture" (when a phone context)
    //     or "file-upload"
    // Do NOT hint a control the renderer would choose by default
    // (e.g. FK columns already become dropdowns).
  "hero": {{
    "kind": {" | ".join(f'"{k}"' for k in RECORD_HERO_KINDS)},
    "title": "The moment-title above the form (e.g. 'Add a booking')",
    "subtitle": "Optional supporting line",
    "status_field": "status",     // only for kind='status-led'
    "media_field": "avatar_url",  // only for kind='media-lead'
    "eyebrow": "Section eyebrow"  // only for kind='editorial'
  }} | null,
  "footer": {{
    "kind": "timestamps" | "danger-zone" | "audit" | "related",
    "content": "Optional supporting line"
  }} | null,
  "signature_moves": [
    // 1-3 signature-move ids from the catalog.
    // Record-page examples:
    //   "sticky-save-bar" (Save button pinned to viewport)
    //   "field-focus-guide" (elegant field focus indicators)
    //   "inline-validation-tick" (green tick on valid completion)
    //   "field-help-drawer" (side drawer with help)
    //   "photo-lead-header" (large photo in hero)
    //   "audit-history-drawer" (drawer with change history)
  ]
}}

STRICT RULES
1. Every field name in `section_grouping[].fields`, `field_ordering`,
   `control_hints`, `hero.status_field`, `hero.media_field` MUST be a
   REAL column on the entity — see the column list in the user prompt.
   Do NOT invent columns.
2. Group EVERY writable field into a section. A flat 15-field form is
   the exact "generic scaffolding" tell we're avoiding.
3. First section should cover the 4-6 fields a user cares about most.
   Later sections cover the rest. Push audit/timestamps into a "meta"
   section (which the composer will render read-only or hide in edit
   mode).
4. Only hint a control when the DOMAIN implies it. A varchar "rating"
   column becomes "rating" (1-5 stars). A jsonb "signature" column
   becomes "signature". Don't hint fields where the renderer already
   picks correctly (regular text/date/FK/boolean).
5. Hero.kind:
   - `status-led` if the entity has a status/state column and this is a
     view/edit page (approval workflows, task detail).
   - `media-lead` if the entity has a photo/logo/avatar column and it
     matters (products, people).
   - `page-header` for edit forms of admin-adjacent entities.
   - `editorial` for consumer-facing FIRST-run creates (subscribe,
     book, register).
6. `footer.kind` is optional and usually null. `timestamps` for view
   pages, `danger-zone` for edit pages of destructible entities,
   `audit` for anything with an approval/change history.
7. `signature_moves` — 1-3 ids from the catalog. Two record pages in
   the same app should pick DIFFERENT ids. Use the variance hint in
   the user prompt to break ties.
8. Return JSON only. No prose. No markdown fences.
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
    mode: str,
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
                fk = f.get("references") or f.get("fk")
                fk_note = f" [FK→{fk}]" if fk else ""
                if fn:
                    column_lines.append(f"  - {fn}: {ft or 'unknown'}{nn}{fk_note}")
    elif isinstance(columns, dict):
        for fn, meta in columns.items():
            ft = None
            if isinstance(meta, dict):
                ft = meta.get("type") or meta.get("sqlType")
            column_lines.append(f"  - {fn}: {ft or 'unknown'}")

    domain = plan.get("domain") or "generic"
    module_name = plan.get("module_name") or "App"
    brief_line = f"\nUser's brief: {brief_text}\n" if brief_text else ""

    # Phase 2 propagation — reuse dashboard helpers.
    from services.dashboard_maquette import _extract_personality_signals, _read_21st_references
    signals = _extract_personality_signals(brief_text)
    personality_block = ""
    if signals:
        personality_block = (
            "\nPERSONALITY SIGNALS (steer hero kind + section rhythm + "
            "control hints toward these):\n"
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
            "\nDESIGN REFERENCES (shape inspiration for section layout + "
            "hero pattern — not verbatim copies):\n"
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
RECORD PAGE
  entity: {entity_name}
  route:  {route}
  mode:   {mode}

Entity columns:
{chr(10).join(column_lines) if column_lines else '  (no columns listed)'}

{_domain_page_block(plan, entity_name, entity_meta, "record")}
Emit the record maquette JSON now."""


# ─────────────────────────── LLM authoring ─────────────────────────────


async def author_record_maquette(
    plan: dict,
    entity_name: str,
    route: str,
    *,
    mode: str = "edit",
    brief_text: str | None = None,
    query_fn: Any | None = None,
    timeout_seconds: float = 45.0,
) -> RecordMaquette | None:
    """Call the LLM to produce a record maquette for ONE page.

    Multi-page apps that want maquettes for every record page call this
    once per (entity, route, mode) — there is intentionally no "author
    all records in one turn" seam because per-page prompts stay smaller
    and focused on a single entity.

    Returns None on any failure (missing entity in plan, malformed LLM
    output, timeout). Never raises.
    """
    if not isinstance(plan, dict):
        return None
    entities = plan.get("entities")
    if not isinstance(entities, dict):
        return None
    entity_meta = entities.get(entity_name)
    if not isinstance(entity_meta, dict):
        return None
    if mode not in RECORD_MODES:
        mode = "edit"

    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(plan, entity_name, entity_meta, route, mode, brief_text)

    if query_fn is not None:
        try:
            text = await query_fn(system_prompt, user_prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[record-maquette] injected query_fn failed: %s", exc)
            return None
    else:
        api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            logger.warning("[record-maquette] no ANTHROPIC_API_KEY; skipping")
            return None
        try:
            text = await asyncio.wait_for(
                _default_query(system_prompt, user_prompt),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("[record-maquette] LLM timed out after %ss", timeout_seconds)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[record-maquette] LLM call failed: %s", exc)
            return None

    parsed = _extract_json_object(text)
    if parsed is None:
        logger.warning("[record-maquette] response did not contain a JSON object")
        return None

    valid_columns = _valid_columns_from(entity_meta)
    return RecordMaquette.from_dict(parsed, valid_columns=valid_columns)


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
    """Best-effort JSON object extract — same as collection/dashboard."""
    if not text or not text.strip():
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    try:
        obj = json.loads(stripped)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass
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

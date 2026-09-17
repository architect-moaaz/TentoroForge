"""Translate an A2UI surface into a Forge page schema with live bindings.

The boundary this enforces
--------------------------
An A2UI payload is three messages. `updateComponents` is the composition — the
thing worth having. `updateDataModel` is invented sample data: 142 tasks, a
"Follow up with client" row. Importing that verbatim would produce a page that
looks finished and is entirely fiction — strictly worse than the empty-but-
honest pages Forge ships today, and invisible to every existing gate because
structurally it is perfect.

So the data model is **read and discarded**. It survives only as evidence of
what shape the composer expected at each binding site.

What makes this tractable is that A2UI never inlines data into a component.
Every data-bearing prop is a pointer:

    {"id": "tasksTable", "component": "Table",
     "columns": {"path": "/tasks/columns"}, "rows": {"path": "/tasks/rows"}}

so translation is a pointer rewrite — `{"path": "/tasks/rows"}` becomes
`"{{tasks}}"` plus a real `dataSource` — rather than an attempt to rescue
literals that were never there.

The KPI filter inference
------------------------
The live q941voiw dashboard shipped three MetricTiles labelled Total / In
Progress / Completed, all bound to the *same* unfiltered count, so all three
read 10. The intent was in the label and nowhere else.

The composer does know the difference — it invented 142 / 38 / 91 and a matching
status breakdown. This module recovers that intent deterministically: match the
tile's label against the entity's real enum values from the registry and emit
the `filter` the label implies. Labels that name no enum value stay unfiltered,
which is the honest reading of "Total Tasks".

Repeated children
-----------------
A2UI has no clone and no loop node: it says "draw component X once per element
of array Y". That collapses to two different Forge pages depending on what the
array holds — N independently-bound widgets, or one ``Repeat`` over a live list
— and picking wrong is silent in both directions. See ``expand_template``.

Heuristic honestly
------------------
Mapping a data-model path to an entity is inference, not fact. The path segment
is tried first, then the component's own label. Anything unresolved is reported
in `warnings` rather than guessed at — a wrong entity binding is far more
expensive than an unbound widget, because it renders convincingly.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

from services.section_layout import shape_sections

# A route addresses one existing record when it carries a dynamic id segment
# (`/records/[id]`, `/records/[id]/edit`). A Next.js catch-all (`[...slug]`) is
# NOT one — it is the dev editor route — so a leading dot after `[` is excluded.
_ROUTE_HAS_ID = re.compile(r"/\[[^.\]/][^\]/]*\]")

# A2UI container props that carry child references.
_CHILD_KEYS = ("children", "child")

# Props that are data bindings rather than presentation.
_DATA_PROPS = frozenset({"data", "rows", "items", "series", "columns", "value", "entries"})

# Props A2UI needs but Forge's renderer does not.
_DROP_PROPS = frozenset({"component", "id", "weight"})

# Props whose value purports to be MEASURED — a sparkline, a breakdown, a
# count. A literal here is invented data sitting directly on the component,
# which the updateDataModel stripping never touches because it never went
# through the data model.
#
# Found live: a composed dashboard cleared the substance floor carrying
# `trend: [8, 9, 10, 11, 12]` and `breakdown: [{"label": "Quorum Met",
# "value": "9"}]`. Nine what? Nothing. It renders as a real sparkline over a
# real tile and there is no gate downstream that can tell.
#
# `columns` is deliberately absent: a column list is CONFIG (which fields to
# show), not a measurement, and carrying the composer's choice through is the
# whole point of the `__literal__` path.
# Data props whose literal value is legitimate CONFIG rather than measurement:
# which columns to show, how to encode a series.
_CONFIG_DATA_PROPS = frozenset({"columns", "series"})

_MEASURED_PROPS = frozenset({
    "trend", "breakdown", "sparkline", "spark", "history", "points",
    "values", "dataset",
    # The same fiction in string form, which the list rule let through:
    # `delta: "+34 since midnight"` on a live tile. Thirty-four since
    # midnight according to whom? A pointer or a {{binding}} survives; a
    # hand-written claim does not.
    "delta", "change", "comparison", "deltaLabel",
})

# A FLOOR, AND NO LONGER A SILENT ONE.
#
# These rewrite `Text.text` to `Text.content`, `Alert.text` to `Alert.message`
# and four more. They described themselves as "a stopgap, not the fix. The fix
# is to make the catalog generator fall back to the schema node when the
# manifest has no key_props… Every entry here marks a component whose manifest
# entry is thin."
#
# That fix has happened. `_PRIMITIVE_PROPS` supplies the fallback, and every
# one of these seven now points at a canonical prop the catalog already
# carries — measured, not assumed. With `unevaluatedProperties` on every
# component, A2UI's own validator rejects `{"component": "Text", "text": …}`
# and retries, so in the ordinary case the wrong prop never arrives here.
# Verified against A2UI's validator rather than an approximation of it.
#
# KEPT ANYWAY, because "unnecessary in the happy path" and "safe to delete" are
# different claims. A rejection costs A2UI a retry out of three, shared with
# whatever else is wrong with that surface; if it cannot self-correct, a page
# that used to ship is lost. A prop name is not worth a page.
#
# What was actually wrong with them was the silence. `translate` reported no
# warning and nothing dropped, so the composer emitted `text` forever while
# this table quietly fixed it — a repair nobody could see is a repair nobody
# removes. Each rename now says so through `warnings`, which is the same
# channel an unknown prop already uses, so a rename that keeps happening is
# visible as a catalog defect rather than absorbed as a habit.
_PROP_ALIASES: dict[str, dict[str, str]] = {
    "Text": {"text": "content"},
    "Heading": {"text": "content"},
    "Badge": {"label": "content", "text": "content"},
    "Tag": {"content": "label", "text": "label"},
    "Alert": {"text": "message"},
}

# Enum synonyms and required-prop defaults. The catalog now carries both, so a
# freshly generated surface needs neither; these keep older payloads (and any
# catalog whose manifest entry is still thin) renderable rather than blank.
_ENUM_SYNONYMS: dict[str, dict[str, str]] = {
    "direction": {"column": "vertical", "row": "horizontal"},
}
# The same floor, for a required prop the composer left out.
#
# `MetricTile.format` decides how the number reads — a count, a currency, a
# percentage — and the node is `.strict()` about having one. Without it the tile
# rendered blank: schema-valid to A2UI at the time, rejected by Forge's node,
# and silently empty on the page.
#
# Redundant in the happy path now, for the same two reasons as the aliases: the
# catalog marks `format` required (`required=['component','format','label',
# 'value']`) and A2UI's own validator refuses a MetricTile without one —
# verified against that validator, not an approximation. Kept for the same
# reason too: a rejection costs a retry out of three, and a page is worth more
# than a default nobody had to guess at.
#
# WARNED, LIKE THE ALIASES. Injecting a value the composer did not choose is a
# decision, and one made silently is one nobody can review. "number" is a
# reasonable default and it is still a guess — a count and a currency read very
# differently, and this module has no idea which it is looking at.
_REQUIRED_DEFAULTS: dict[str, dict[str, Any]] = {
    "MetricTile": {"format": "number"},
}

# Props the composer emits that no Forge component accepts. Dropped rather than
# passed through, because `.strict()` nodes reject unknown keys outright.
# Field controls. A form is the one place where the composer's component
# CHOICE is not the last word: a column typed `timestamp` needs a DatePicker
# whatever was reached for, and `semantic_field_types._decide` already owns
# that mapping for every other builder in the pipeline.
_FIELD_TYPES = frozenset({
    "Input", "Textarea", "Select", "MultiSelect", "Combobox", "Checkbox",
    "RadioGroup", "Switch", "NumberInput", "MoneyInput", "DatePicker",
    "DateRangePicker", "TimePicker", "FileUpload", "Slider", "Rating",
    "KeyValueInput", "MaskedInput", "InputOTP", "RichTextEditor",
    "ColorPicker", "SegmentedControl", "Cascader",
})

_UNSUPPORTED: dict[str, frozenset[str]] = {
    "Text": frozenset({"variant"}),
    "Heading": frozenset({"variant"}),
}


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _humanize(name: str) -> str:
    """A column name as a chart-legend label: `dueDate` → "Due Date"."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", (name or "").replace("_", " "))
    return " ".join(w[:1].upper() + w[1:] for w in spaced.split()) or "Value"


#: A KPI LABEL NAMES ITS MEASURE. "Amount requested outstanding" is a SUM of
#: `amountRequested` over the cases that are outstanding; the converter bound
#: every tile to `count` of a guessed entity, so a dashboard whose contract
#: asked for issued value, denied value and pending value showed counts —
#: of Approvals. The label's words against the entities' numeric columns say
#: which measure, and which entity carries it.
_MEASURE_WORDS = frozenset({"amount", "value", "total", "sum", "revenue", "spend",
                            "cost", "balance", "price", "fee", "worth", "refunded"})
_COUNT_WORDS = frozenset({"count", "number", "cases", "requests", "items", "open"})
_NUMERIC_TYPES = frozenset({"decimal", "numeric", "integer", "int", "float", "money",
                            "currency", "double", "bigint", "real", "number", "smallint"})


def _words(text: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(text or "").replace("_", " "))
    return [w for w in re.split(r"[^a-z0-9]+", spaced.lower()) if w]


def _measure_for_label(label: str, entity: str | None, registry: dict) -> tuple[str | None, dict]:
    """(entity, metric): a sum/avg over the numeric column the label names,
    on the entity that carries it; otherwise a count on `entity`."""
    words = set(_words(label))
    if not (words & _MEASURE_WORDS) or (words & {"count", "number"}):
        return entity, {"fn": "count"}
    ents = registry.get("entities") or {}
    order = ([entity] if entity in ents else []) + [e for e in ents if e != entity]
    best: tuple[int, str, str] | None = None
    for ename in order:
        for col in (ents.get(ename) or {}).get("columns") or []:
            if str(col.get("type") or "").lower() not in _NUMERIC_TYPES:
                continue
            score = len(set(_words(col["name"])) & words)
            if score and (best is None or score > best[0]):
                best = (score, ename, col["name"])
    fn = "avg" if words & {"average", "avg", "mean"} else "sum"
    if best is None:
        # "Issued value" names no column by word; the entity's own amount
        # column is the measure a value of it means.
        for col in (ents.get(entity or "") or {}).get("columns") or []:
            if (str(col.get("type") or "").lower() in _NUMERIC_TYPES
                    and set(_words(col["name"])) & _MEASURE_WORDS):
                return entity, {"fn": fn, "field": col["name"]}
        return entity, {"fn": "count"}
    return best[1], {"fn": fn, "field": best[2]}


def _filter_owner(label: str, entity: str | None, registry: dict, first: str = "") -> tuple[str | None, dict | None]:
    """(entity, filter): the entity whose enum the label names — the current
    one first, then the page's, then any. "Awaiting posting" names a status
    of RefundCase, whatever pointer the composer hung the tile on."""
    ents = registry.get("entities") or {}
    order = [e for e in (entity, first) if e in ents]
    order += [e for e in ents if e not in order]
    for ename in order:
        filt = _enum_filter(label, ename, registry)
        if filt:
            return ename, filt
    return entity, None


def _entity_owning_columns(keys: list[str], entity: str | None, registry: dict) -> str | None:
    """The entity whose columns the table's own column keys name best.

    "Cases needing attention" was bound to the approvals list and drew
    refund-case columns — every cell a dash. The columns the composer chose
    are the strongest statement of what the rows are."""
    ents = registry.get("entities") or {}
    want = {_slugify(k) for k in keys if k}
    if not want:
        return None
    def score(ename: str) -> int:
        cols = {_slugify(c.get("name", "")) for c in (ents.get(ename) or {}).get("columns") or []}
        return len(want & cols)
    current = score(entity) if entity in ents else 0
    best = max(ents, key=score, default=None)
    if best and score(best) > current:
        return best
    return None


def _entity_index(registry: dict) -> dict[str, str]:
    """Every reasonable alias for an entity → its canonical name."""
    idx: dict[str, str] = {}
    for name, ent in (registry.get("entities") or {}).items():
        for alias in (name, ent.get("camel"), ent.get("slug"), ent.get("plural")):
            if alias:
                idx[_slugify(alias)] = name
        # bare plural of the camel name, e.g. task -> tasks
        camel = ent.get("camel") or name.lower()
        idx.setdefault(_slugify(camel + "s"), name)
    return idx


def _resolve_entity(hint: str, idx: dict[str, str]) -> str | None:
    """Longest alias contained in the hint wins — 'totalTasks' resolves to Task
    without 'task' also matching some unrelated 'multitasking' field."""
    h = _slugify(hint)
    if not h:
        return None
    if h in idx:
        return idx[h]
    best: tuple[int, str] | None = None
    for alias, ent in idx.items():
        if len(alias) >= 3 and alias in h:
            if best is None or len(alias) > best[0]:
                best = (len(alias), ent)
    return best[1] if best else None


def _slug_for(entity: str, registry: dict) -> str:
    ent = (registry.get("entities") or {}).get(entity) or {}
    return ent.get("slug") or ent.get("camel") or entity.lower()


def _source_name_for(entity: str, registry: dict) -> str:
    """The list source a page reads an entity's rows from, as an identifier:
    `properties`, `refundCases` — the slug with its dashes folded."""
    ent = (registry.get("entities") or {}).get(entity) or {}
    slug = str(ent.get("slug") or ent.get("plural") or "")
    if not slug or slug.lower() == entity.lower():
        # No table name to read the plural off: say it the plain English way.
        base = ent.get("camel") or (entity[:1].lower() + entity[1:])
        slug = base[:-1] + "ies" if base.endswith("y") and base[-2:-1] not in "aeiou" else base + "s"
    parts = [p for p in slug.replace("_", "-").split("-") if p]
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:]) if parts else entity.lower()


def _label_column(entity: str, registry: dict, preferred: str = "") -> str:
    """What to show for a row of `entity` in a dropdown."""
    cols = [str(c.get("name") or "") for c in
            ((registry.get("entities") or {}).get(entity) or {}).get("columns") or []]
    if preferred and preferred in cols:
        return preferred
    for candidate in ("name", "title", "label", "fullName", "displayName", "code", "email"):
        if candidate in cols:
            return candidate
    return preferred or "name"


def option_source(binder: Any, registry: dict, spoken: Any, *,
                  references: str = "") -> dict | None:
    """A2UI's way of saying where a dropdown's options come from → Forge's.

    THE COMPOSER THINKS ENTITY-FIRST AND THE CONTRACT READS SOURCE-FIRST. The
    composer writes `optionsFrom: {entity, labelField, valueField}` — the
    entity whose rows are the options, named by id or by name. `Select` and a
    Form field's `interaction.optionsFrom` read `{source, value, label}`,
    where `source` is a name in the page's `dataSources`. Same meaning, and
    every intake form on one real build was refused over the difference
    ("'source' is a required property; 'entity' … were unexpected") while
    the page's data model held nothing that listed the entity. Translation
    registers the list the source names, exactly as a bound pointer would.

    `references` is the column's own foreign key, for a field the composer
    named after one without saying where its options come from.
    """
    hint = ""
    label_pref = ""
    value = "id"
    if isinstance(spoken, dict):
        if spoken.get("source"):
            return None  # already the contract's shape
        hint = str(spoken.get("entity") or spoken.get("table") or "")
        label_pref = str(spoken.get("labelField") or spoken.get("label") or "")
        value = str(spoken.get("valueField") or spoken.get("value") or "id")
    entity = None
    for candidate in (hint, references):
        if not candidate:
            continue
        entity = (registry.get("entityNames") or {}).get(candidate) or candidate
        entity = entity if entity in (registry.get("entities") or {}) else _resolve_entity(entity, binder.idx)
        if entity:
            break
    if not entity:
        return None
    name = binder._add_source({"name": _source_name_for(entity, registry),
                               "entity": entity, "op": "list"})
    return {"source": name, "value": value or "id",
            "label": _label_column(entity, registry, label_pref)}


# Words that describe a boolean flag, not an enum member. Checked before enums
# because "Active Users" against role[admin|user] otherwise matches the literal
# substring "user" and emits {"role": "user"} — a filter that is plausible,
# wrong, and impossible to spot in a rendered page.
_BOOLEAN_WORDS = {
    "active": True, "inactive": False, "enabled": True, "disabled": False,
    "archived": True, "published": True, "draft": False,
}


# enum value (slugified) -> label words that mean it. Deliberately small: each
# entry is a synonym pair observed on a real surface, not a thesaurus. Guessing
# broadly here would bind a KPI to the wrong subset, which renders just as
# convincingly as the right one.
_ENUM_LABEL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "done": ("completed", "complete", "finished", "closed"),
    "inprogress": ("active", "ongoing", "wip"),
    "todo": ("pending", "open", "backlog", "new"),
    "cancelled": ("canceled", "voided"),
    "approved": ("accepted",),
    "rejected": ("declined", "denied"),
    "pendingapproval": ("outstanding", "awaitingapproval"),
}


def _enum_filter(label: str, entity: str, registry: dict) -> dict | None:
    """The filter a KPI label implies, read off the entity's real columns.

    "In Progress" against status[todo|in_progress|done] yields
    {"status": "in_progress"}. "Total Tasks" matches nothing and stays
    unfiltered, which is correct rather than a miss.
    """
    want = _slugify(label)
    if not want:
        return None
    cols = ((registry.get("entities") or {}).get(entity) or {}).get("columns") or []

    # A label that simply NAMES a boolean column is the strongest signal
    # available and needs no vocabulary: "Quorum Met" against `quorumMet` is
    # the same two words. Checked before everything else, because the generic
    # word list below has no entry for a domain's own flags and never will.
    for col in cols:
        if col.get("type") != "boolean":
            continue
        cslug = _slugify(col["name"])
        if cslug and (cslug == want or cslug in want or want in cslug):
            return {col["name"]: True}

    # Then the generic flag vocabulary — see _BOOLEAN_WORDS.
    for word, truth in _BOOLEAN_WORDS.items():
        if word not in want:
            continue
        for col in cols:
            if col.get("type") == "boolean" and word in _slugify(col["name"]):
                return {col["name"]: truth}

    for col in cols:
        for value in col.get("enum") or []:
            v = _slugify(value)
            if not v:
                continue
            if v in want:
                return {col["name"]: value}
            # "Awaiting posting" names the value "Approved awaiting posting"
            # by its distinctive tail; the whole value need not be spelled.
            if len(want) >= 6 and want in v:
                return {col["name"]: value}
            if any(syn in want for syn in _ENUM_LABEL_SYNONYMS.get(v, ())):
                return {col["name"]: value}
    return None


class _Binder:
    def _record(self, kind: str, where: Any, what: str, detail: str,
                *, material: bool = False) -> None:
        """Write a removal to the translation's ledger.

        Tolerates a binder built without one — the tests construct `_Binder`
        directly, and a missing ledger must not turn a recorded loss into a
        crash.
        """
        ledger = getattr(self, "losses", None)
        if ledger is not None:
            ledger.record(kind, where, what, detail, material=material)

    def __init__(self, registry: dict, data_model: dict | None = None):
        self.registry = registry
        # Read for SHAPE and for COPY only — never for values. Labels live
        # here because A2UI points at them like anything else, and a KPI's
        # label is the only evidence of which subset it counts.
        self.data_model = data_model or {}
        self.idx = _entity_index(registry)
        self.sources: list[dict] = []
        self.warnings: list[str] = []
        self.assumptions: list[str] = []
        # Every place the binder had to GUESS an entity, in a shape a
        # resolver can answer. Prose assumptions are for the reader;
        # these are for the next pass.
        self.questions: list[dict] = []
        # component id -> entity, supplied by a resolver. Consulted
        # BEFORE the dominant fallback, and only ever honoured when it
        # names a REGISTERED entity — the closed set is the whole point.
        self.entity_hints: dict[str, str] = {}
        # Props a bound component needs but the A2UI payload never carries.
        # Keyed by component id and applied by the tree builder — writing them
        # onto the component in place would mutate a dict mid-iteration.
        self.extra_props: dict[str, dict[str, Any]] = {}
        # Which entity each component ended up bound to, so a derived prop
        # (a breakdown row, a trend) can be resolved against the same one its
        # own tile counts. Recorded by `bind`, read by the resolvers.
        self.entity_of: dict[str, str] = {}
        # Things the composer asked for that carry real intent but that this
        # module could not turn into a query. NOT the same as fiction: these
        # are reported so the gap is visible, because a silent drop is how a
        # declared decision disappears without anyone noticing.
        self.unresolved: list[str] = []
        # The entity a form on this surface writes to. Resolved once, because a
        # form's fields all belong to one record and guessing per field would
        # let a single typo split them silently across two tables.
        self.form_entity: str | None = None
        self.dominant: str | None = None
        self._by_path: dict[str, str] = {}
        self._names: set[str] = set()

    def _at(self, path: str) -> Any:
        node: Any = self.data_model
        for seg in [s2 for s2 in str(path).split("/") if s2]:
            node = node.get(seg) if isinstance(node, dict) else None
        return node

    def label_of(self, comp: dict) -> str:
        """The component's human label, following a pointer if that is how it
        was written.

        A2UI points at labels the same way it points at data, so a live surface
        arrived with ``label: {"path": "/kpi1/label"}``. Reading that raw gave
        the literal string ``{'path': '/kpi1/label'}``, which names no enum
        value, so all four KPI tiles bound to the same unfiltered count and
        rendered the same number — the exact defect ``_enum_filter`` exists to
        prevent, walking back in through a different door.
        """
        for key in ("label", "title"):
            v = comp.get(key)
            if isinstance(v, str) and v:
                return v
            if isinstance(v, dict) and "path" in v:
                lit = self._at(str(v["path"]))
                if isinstance(lit, str) and lit:
                    return lit
        return ""

    def _add_source(self, spec: dict) -> str:
        """Register a fetch, reusing an identical one. Returns its name.

        `_by_path` is keyed on the POINTER, so two pointers resolving to the
        same entity and the same operation each minted their own source: one
        page declared `books`, `books2` and `books3` — three identical list
        queries against one table, with the tree reading all three.

        Sameness is the whole spec apart from its name. An aggregate with
        different metrics, or a list carrying a filter, is a different fetch
        and keeps its own; nothing is merged that would return different rows.
        """
        without_name = {k: v for k, v in spec.items() if k != "name"}
        for existing in self.sources:
            if {k: v for k, v in existing.items() if k != "name"} == without_name:
                return str(existing["name"])
        spec = {**spec, "name": self._unique(str(spec["name"]))}
        self.sources.append(spec)
        return str(spec["name"])

    def _unique(self, base: str) -> str:
        name, n = base, 2
        while name in self._names:
            name, n = f"{base}{n}", n + 1
        self._names.add(name)
        return name

    def bind(self, path: str, comp: dict, prop: str) -> str | None:
        """A `{path: ...}` pointer → a `{{binding}}`, registering the dataSource."""
        key = f"{path}|{prop}"
        if key in self._by_path:
            return self._by_path[key]

        label = self.label_of(comp)
        segments = [s for s in path.split("/") if s]
        hint = " ".join(segments[-2:]) if segments else ""

        entity = _resolve_entity(hint, self.idx) or _resolve_entity(label, self.idx)

        if not entity:
            # A resolver answered this one. Honoured only if it names a
            # registered entity: an invented name would become a dataSource
            # nothing serves, which is the failure the closed set exists to
            # prevent.
            hinted = self.entity_hints.get(str(comp.get("id")))
            if hinted and hinted in (self.registry.get("entities") or {}):
                entity = hinted

        if not entity and self.dominant:
            # A dashboard's KPI tiles are usually labelled by *subset* ("In
            # Progress", "Completed") with the entity implied by the page, so the
            # path and label name no entity at all. Falling back to the surface's
            # dominant entity recovers those. Recorded as an assumption, because
            # a silent wrong binding renders convincingly and is the single most
            # expensive failure this module can produce.
            entity = self.dominant
            self.questions.append({
                "component": str(comp.get("id") or ""),
                "prop": prop,
                "path": path,
                "label": label,
                "assumed": entity,
                "candidates": sorted((self.registry.get("entities") or {}).keys()),
            })
            self.assumptions.append(
                f'{comp.get("id")}.{prop}: "{path}" (label {label!r}) names no '
                f"entity; assumed {entity} — the dominant entity on this surface."
            )
        if not entity:
            # THE PAGE SAYS WHAT IT IS ABOUT. A2UI names its data after the
            # screen and this resolves by entity name, so `/team` on a page
            # whose entity is `TeamMember` matched nothing and the page ended
            # with no sources at all. Reading `primaryEntity` off the Page
            # Contract is not the guess this refuses to make — it is the
            # declaration the pointer failed to reach.
            declared = getattr(self, "page_entity", "")
            if declared and declared in (self.registry.get("entities") or {}):
                entity = declared
                self.assumptions.append(
                    f'{comp.get("id")}.{prop}: "{path}" names no entity; used '
                    f"{entity} — what this page's contract says it is about."
                )
        if not entity:
            self.warnings.append(
                f'{comp.get("id")}.{prop}: could not resolve "{path}" to an entity '
                f"(label {label!r}). Left unbound rather than guessed."
            )
            return None

        kind = comp.get("component")

        if kind == "Table" and prop == "rows":
            raw_cols = comp.get("columns")
            if isinstance(raw_cols, dict) and raw_cols.get("path"):
                raw_cols = self._at(str(raw_cols["path"]))
            keys = [str(c.get("key") or c.get("field") or "")
                    for c in (raw_cols if isinstance(raw_cols, list) else []) if isinstance(c, dict)]
            owner = _entity_owning_columns(keys, entity, self.registry)
            if owner and owner != entity:
                self.assumptions.append(
                    f'{comp.get("id")}.rows: "{path}" resolved to {entity}, but the '
                    f"table's columns are {owner}'s — bound to {owner}.")
                entity = owner

        if kind == "MetricTile" or prop == "value":
            owner, filt = _filter_owner(label, entity, self.registry,
                                        str(getattr(self, "page_entity", "") or ""))
            measured, metric = _measure_for_label(label, owner, self.registry)
            if measured and measured != owner:
                owner = measured
                filt = _enum_filter(label, owner, self.registry)
            if owner and owner != entity:
                self.assumptions.append(
                    f'{comp.get("id")}.{prop}: label {label!r} names {owner}\'s '
                    f"{'measure' if metric.get('field') else 'status'}, not {entity}'s — bound to {owner}.")
                entity = owner

        self.entity_of[str(comp.get("id"))] = entity
        slug = _slug_for(entity, self.registry)

        if kind == "MetricTile" or prop == "value":
            base = _slugify(label) or f"{slug}Count"
            name = self._unique(base)
            # The filter belongs INSIDE the metric. `AggregateSource` has no
            # source-level `filter` field, so putting it there is silently
            # dropped and every KPI reports the unfiltered total — which is how
            # "In Progress" first rendered 10 against 3 real rows.
            if filt:
                metric["filter"] = filt
            src: dict[str, Any] = {
                "name": name, "entity": entity, "op": "aggregate",
                "metrics": {"value": metric},
            }
            self.sources.append(src)
            binding = f"{{{{{name}.value}}}}"
        elif kind == "Chart" and prop in ("data", "series"):
            if prop == "series":
                # Series descriptors are presentation, not rows — the runtime
                # derives them from the grouped result. Written down because
                # this was the one `bind()` exit with no record of any kind:
                # the prop vanished and `expand_template`'s comment claiming
                # "bind() already recorded why" was false for exactly this
                # path. Not material — the runtime supplies the descriptors.
                self._record("dropped_prop", comp.get("id"), prop,
                             "series descriptors are derived from the grouped "
                             "result at runtime, not bound")
                return None
            # The component's own id and title say what it is ABOUT —
            # `categoryChart` means category — which is the only signal to the
            # dimension A2UI never declares.
            hint = f"{comp.get('id') or ''} {comp.get('title') or ''} {label or ''}"
            group = self._group_column(entity, hint=hint)
            if group is None:
                # No readable axis exists on this entity. Emitting one anyway
                # means a uuid-labelled chart, which the dashboard floor
                # rejects — taking the whole page down with it. Leave the
                # chart unbound and say why.
                # A STRING, LIKE EVERY OTHER ENTRY. `unresolved` is
                # declared `list[str]` and this one site appended a dict, so
                # any consumer joining the list raised instead of reporting.
                why = (f"{entity} has no groupable dimension (no enum, and "
                       f"every other column is a key, free text or an "
                       f"ungroupable type) — a chart here could only be "
                       f"grouped by a uuid")
                self.unresolved.append(
                    f"{comp.get('id') or '?'}.{prop}: {why}")
                self._record("dropped_prop", comp.get("id"), prop, why,
                             material=True)
                return None
            name = self._unique(f"{slug}By{group[:1].upper()}{group[1:]}")
            # `SeriesSource` reads `agg`, not `metrics` — the aggregate shape
            # does not carry over. fn defaults to count, but being explicit
            # keeps the two ops visibly distinct.
            src = {"name": name, "entity": entity, "op": "series",
                   "groupBy": group, "agg": {"fn": "count"}}
            self.sources.append(src)
            binding = f"{{{{{name}}}}}"
            # A2UI charts carry only the data pointer; Recharts needs to be
            # told which key is the axis and which is the value, and an empty
            # `series` plots nothing at all. resolveSeries always returns
            # {label, value} rows, so these are constants, not guesses.
            extra = self.extra_props.setdefault(str(comp.get("id")), {})
            extra["xKey"] = "label"
            # A2UI's `series` is another DATA pointer, not a Recharts series
            # descriptor, so it resolves to nothing and the prop vanishes —
            # leaving the chart with rows but no encoding, which renders blank.
            # Only a literal descriptor list is worth keeping.
            declared = comp.get("series")
            already_shaped = isinstance(declared, list) and all(
                isinstance(d, dict) and d.get("dataKey") for d in declared
            )
            if not already_shaped:
                extra["series"] = [{
                    "name": str(comp.get("title") or _humanize(group)),
                    "dataKey": "value",
                }]
        elif prop == "columns":
            # Column definitions are literal config; carry the composer's own
            # choice through rather than binding it.
            return "__literal__"
        else:
            name = self._add_source({"name": slug, "entity": entity,
                                     "op": "list", "limit": LIST_PAGE_SIZE})
            binding = f"{{{{{name}}}}}"

        self._by_path[key] = binding
        return binding

    def is_record_page(self) -> bool:
        """Whether this page is about one record.

        `_family_of` rather than `page_family` directly: page_family knows
        nothing about `record_workspace` and answers None, and the authority's
        map is the one covering every declared kind.
        """
        # A ROUTE WITH A RECORD ID ADDRESSES ONE EXISTING INSTANCE, whatever
        # A2UI named the page. `/records/[id]/edit` and `/records/[id]` classify
        # as `form`/unclassified, not `record` — but both show and act on the
        # single record the `[id]` segment names, so their `/entity/*` pointers
        # ARE record-scoped and must bind through a `get`-by-id source. Without
        # this an edit page dropped every such pointer: a KeyValueList lost the
        # `value` its contract requires, and the Save form had no record for its
        # Update workflow to name. Route-driven, the same rule `_family_of`
        # already applies (the route outranks the declared pattern); the `[...]`
        # catch-all is excluded — it is the dev editor route, not a record.
        if _ROUTE_HAS_ID.search(str(getattr(self, "route", "") or "")):
            return True
        try:
            from services.a2ui_authority import _family_of
            return _family_of(getattr(self, "page_kind", ""),
                              getattr(self, "route", "")) == "record"
        except Exception:  # noqa: BLE001 — a lookup must not fail a binding
            return False

    def record_source(self, entity: str) -> str:
        """The page's single `get` source for `entity`, created once.

        One source, however many fields read from it — a detail page that
        minted a source per field would fetch the same record six times and
        bind each field to a different name.

        `get` is the runtime's own word: data-engine-bridge resolves the URL id
        and calls findById for any source that is not a list, so this needs no
        URL template and no key.
        """
        existing = getattr(self, "_record_src", None)
        if existing:
            return str(existing)
        name = self._add_source({"name": _slug_for(entity, self.registry),
                                 "entity": entity, "op": "get"})
        self._record_src = name
        return name

    def measure_from_label(self, comp: dict, prop: str) -> str | None:
        """A measured value that arrived as a bare LITERAL → a real aggregate.

        A MetricTile whose value is a pointer already gets this treatment via
        `resolve`. A Gauge arriving with `value: 87` was caught one step
        earlier by the rule that discards invented rows, and shipped with no
        value at all — it renders empty. The number is fiction; the intent is
        not, and the label names a real subset. Same judgement already made
        for `breakdown`: re-bind rather than discard.
        """
        cid = str(comp.get("id") or "")
        ents = self.registry.get("entities") or {}
        entity = self.entity_of.get(cid)

        if not entity:
            hinted = self.entity_hints.get(cid)
            if hinted and hinted in ents:
                entity = hinted

        if not entity and self.dominant:
            # Same guess the pointer path makes, and it must ASK for the same
            # reason: a quorum gauge on a legislative dashboard is about the
            # session, not about whatever entity the surface mentions most.
            # This path was invisible to the resolver until it recorded a
            # question, so the gauge kept the dominant-entity guess even with
            # the resolver switched on.
            entity = self.dominant
            self.questions.append({
                "component": cid,
                "prop": prop,
                "path": "",
                "label": self.label_of(comp),
                "assumed": entity,
                "candidates": sorted(ents.keys()),
            })

        if not entity or entity not in ents:
            return None
        label = self.label_of(comp)
        filt = _enum_filter(label, entity, self.registry)

        # A PERCENTAGE is not a count. `unit:"%"` or a 0-100 range says the
        # widget draws a proportion; binding count(entity) there renders "40%"
        # for forty rows. A ratio is derivable when the label names a real
        # subset — filtered over total — and when it names none, nothing in the
        # registry says what the percentage is OF. Unbound and explained beats
        # a confident wrong number: an empty gauge is visibly broken, a wrong
        # one is not, which makes it the worse failure.
        pct = (str(comp.get("unit") or "").strip() == "%"
               or (comp.get("min") in (0, 0.0) and comp.get("max") in (100, 100.0)))
        if pct and not filt:
            self.unresolved.append(
                f'{comp.get("id")}.{prop}: draws a percentage (unit/range 0-100) '
                f"but its label {label!r} names no subset of {entity}, so nothing "
                f"says what the proportion is OF. Left unbound rather than "
                f"binding a raw count, which would render 40 rows as \"40%\".")
            return None

        owner, filt = _filter_owner(label, entity, self.registry,
                                    str(getattr(self, "page_entity", "") or ""))
        measured, metric = _measure_for_label(label, owner, self.registry)
        if measured and measured != owner:
            owner = measured
            filt = _enum_filter(label, owner, self.registry)
        entity = owner or entity
        slug = _slug_for(entity, self.registry)
        name = self._unique(_slugify(label) or f"{slug}Measure")
        if pct:
            metric = {"fn": "ratio"}
        if filt:
            metric["filter"] = filt
        self.sources.append({"name": name, "entity": entity, "op": "aggregate",
                             "metrics": {"value": metric}})
        return f"{{{{{name}.value}}}}"

    def resolve_field(self, comp: dict) -> tuple[str, dict] | None:
        """A proposed form field → a real column, with the control its SQL type
        deserves. ``None`` means the field names nothing and must not ship.

        Two corrections happen here and both matter:

        * The NAME. A field bound to a column that does not exist fails at
          SUBMIT, not at render — so it looks perfect until someone uses it.
          Matched on column name first, then on label, so "Full Name" finds
          ``fullName``. Anything unmatched is reported, never invented.
        * The CONTROL. The composer picks from a catalog; the column has a SQL
          type. When they disagree the type wins — a `timestamp` gets a
          DatePicker even if an Input was proposed. That is the rule
          ``semantic_field_types._decide`` already applies for every other
          builder, reused here rather than re-derived.
        """
        entity = self.form_entity
        if not entity:
            self.unresolved.append(
                f'{comp.get("id")}: form field with no resolvable entity — the '
                f"route names none and the surface has no dominant one.")
            return None

        cols = ((self.registry.get("entities") or {}).get(entity) or {}).get("columns") or []
        want_name = _slugify(str(comp.get("name") or ""))
        want_label = _slugify(str(comp.get("label") or ""))

        col = None
        for want in (want_name, want_label):
            if not want:
                continue
            for c in cols:
                if _slugify(c.get("name", "")) == want:
                    col = c
                    break
            if col:
                break

        if col is None:
            if getattr(self, "page_kind", "") == "dashboard":
                # A dashboard has no form. Its Selects and date pickers are
                # FILTER CHROME — a range picker names no column because it is
                # not a column. Running them through the form-field resolver
                # both dropped the control and reported a defect that isn't
                # one. Kept unbound; the form rule below is untouched, because
                # there a field naming no column really does fail at submit.
                return str(comp.get("component")), {
                    "name": str(comp.get("name") or ""),
                    "label": str(comp.get("label")
                                 or _humanize(str(comp.get("name") or ""))),
                }
            self.unresolved.append(
                f'{comp.get("id")}: field '
                f'{comp.get("name") or comp.get("label") or "?"!r} names no '
                f"column of {entity}. Dropped — a field bound to a column that "
                f"does not exist fails at submit, not at render, so it looks "
                f"correct until someone uses it.")
            return None

        props: dict[str, Any] = {
            "name": col["name"],
            "label": str(comp.get("label") or _humanize(col["name"])),
        }
        try:
            from services.semantic_field_types import _decide
            node_type, extra = _decide(col["name"], str(col.get("type") or ""),
                                       list(col.get("enum") or []) or None)
        except Exception as exc:  # noqa: BLE001 — never fail a composition on this
            logger.warning("[a2ui] control decision failed for %s: %s",
                           col.get("name"), exc)
            node_type, extra = None, None

        if node_type:
            props.update(extra or {})
        kind = node_type or str(comp.get("component"))
        # A SELECT OVER A FOREIGN KEY SAYS WHERE ITS ROWS COME FROM. Rebuilding
        # the props from the column dropped the composer's `optionsFrom`, and a
        # column that references another entity said nothing either; the
        # dropdown shipped with no options and no source. Both are the same
        # list, registered here so the page fetches it.
        if kind in ("Select", "Combobox", "MultiSelect") and not props.get("options"):
            translated = option_source(self, self.registry, comp.get("optionsFrom"),
                                       references=str(col.get("references") or ""))
            if translated:
                props["optionsFrom"] = translated

        # WHAT THE COMPOSER WROTE ON THIS FIELD, CARRIED RATHER THAN MOURNED.
        #
        # The props above are built FROM THE COLUMN, not from the component —
        # deliberately, because the column is the authority on what the field
        # collects and which control collects it. But everything ELSE the
        # composer decided about the control was discarded with it:
        # `placeholder`, `helpText`, `required`, `min`, `max`, `rows`,
        # `defaultValue`, on every field of every form, silently.
        #
        # RECORDING THAT WOULD HAVE BEEN THE WRONG FIX. It is a real loss and
        # the composer cannot do anything about it — composing again produces
        # the same field and the same rebuild — so refusing would loop and
        # reporting would be noise on every form this platform builds. The
        # column decides what the field IS; the composer decides how it reads.
        # Both can be true at once.
        #
        # Only props the control actually accepts, so this cannot put an
        # unknown key on a strict node; anything else is left to
        # `_unknown_props`, which is the check that owns that question.
        try:
            from services.a2ui_catalog import load_contracts, props_for
            accepted = set(props_for(str(kind), load_contracts()) or {})
        except Exception:  # noqa: BLE001 — never fail a composition on a lookup
            accepted = set()
        for prop, value in (comp or {}).items():
            if prop in props or prop not in accepted or value in (None, ""):
                continue
            if prop in ("name", "label", "options", "optionsFrom"):
                continue
            props[prop] = value

        # THE COMPOSER'S COMPONENT CHOICE, OVERRULED BY THE COLUMN'S TYPE. An
        # `Input` becomes a `DatePicker` because the column is a date, which
        # is right and was silent.
        spoken = str(comp.get("component") or "")
        if node_type and spoken and spoken != kind:
            self._record("coerced", comp.get("id"), "component",
                         f"written as {spoken}, rendered as {kind} because "
                         f"{col['name']!r} is a {col.get('type') or 'column'}")
        return kind, props

    def resolve_breakdown(self, comp: dict, rows: list) -> list[dict] | None:
        """A KPI's breakdown rows → one filtered aggregate each.

        The composer writes these with invented values —
        ``[{"label": "Quorum Met", "value": "9"}]`` — but the LABEL is real
        intent: it names a subset of the tile's own entity. Dropping the row
        because its number was made up throws the intent away with the
        fiction; the number is recoverable, so recover it.

        Each row becomes its own ``aggregate`` source filtered the way its
        label implies, exactly as the tile's own value does. A row whose label
        names no subset is reported rather than bound to the unfiltered total,
        which would render as a plausible duplicate of the headline number.
        """
        entity = self.entity_of.get(str(comp.get("id")))
        if not entity:
            self.unresolved.append(
                f'{comp.get("id")}.breakdown: the tile itself is unbound, so '
                f"there is no entity to break down.")
            return None

        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "").strip()
            if not label:
                continue
            filt = _enum_filter(label, entity, self.registry)
            if not filt:
                self.unresolved.append(
                    f'{comp.get("id")}.breakdown: "{label}" names no value of '
                    f"any {entity} column, so the subset it counts is unknown. "
                    f"Left out rather than bound to the unfiltered total, "
                    f"which would render as a convincing duplicate.")
                continue
            name = self._unique(_slugify(label) or f"{entity.lower()}Subset")
            self.sources.append({
                "name": name, "entity": entity, "op": "aggregate",
                "metrics": {"value": {"fn": "count", "filter": filt}},
            })
            out.append({"label": label, "value": f"{{{{{name}.value}}}}"})
        return out or None

    # Words that name a dimension people actually read a chart by. Matched
    # against the column name, and against the component's own id/label so a
    # component called `categoryChart` finds `category` even when the entity
    # offers another groupable column.
    _DIMENSION_WORDS = (
        "category", "type", "status", "state", "kind", "tier", "priority",
        "level", "group", "region", "department", "role", "method", "channel",
        "source", "unit", "severity", "stage", "class", "grade", "mode",
    )
    # Mirrors dashboard_anatomy's floor exactly. Authoring something the gate
    # is guaranteed to reject is how a 95-node page became a 13-node stub.
    _UNREADABLE_TYPES = frozenset({"uuid", "json", "jsonb", "text"})
    _FREE_TEXT_WORDS = ("name", "title", "label", "description", "notes",
                        "summary", "comment", "address", "email", "phone",
                        "slug", "code")

    def _groupable(self, col: dict) -> bool:
        """Whether this column can carry a chart axis a human can read."""
        if col.get("enum"):
            return True          # an enum is the ideal axis, full stop
        if col.get("fk"):
            return False         # one bar per uuid, labelled by uuid
        name = str(col.get("name") or "").lower()
        if name == "id" or name.endswith("id"):
            return False
        if str(col.get("type") or "").lower() in self._UNREADABLE_TYPES:
            return False
        # Free text groups one row per row — a list drawn as a chart.
        return not any(w in name for w in self._FREE_TEXT_WORDS)

    def _group_column(self, entity: str, hint: str = "") -> Optional[str]:
        """The dimension to group a chart by, or None when none is readable.

        A2UI names the measure and never the dimension, so this is an
        inference. It used to end `return "id"`, which is never a real axis:
        the chart draws one bar per row with uuid labels, the dashboard floor
        rejects the page, and the app falls back to a stub. Returning None
        instead lets the caller emit NO chart — an absent widget is honest,
        an unreadable one is not.
        """
        ents = (self.registry.get("entities") or {})
        cols = (ents.get(entity) or {}).get("columns") or []
        usable = [c for c in cols if isinstance(c, dict) and c.get("name")
                  and self._groupable(c)]
        if not usable:
            return None

        # 1. What the component itself is about — `categoryChart` means category.
        h = str(hint or "").lower()
        if h:
            for word in self._DIMENSION_WORDS:
                if word not in h:
                    continue
                for c in usable:
                    if word in str(c["name"]).lower():
                        return str(c["name"])

        # 2. An enum: the axis the floor accepts unconditionally.
        for c in usable:
            if c.get("enum"):
                return str(c["name"])

        # 3. A column whose name reads like a dimension.
        for word in self._DIMENSION_WORDS:
            for c in usable:
                if word in str(c["name"]).lower():
                    return str(c["name"])

        return None



def _enum_members(kind: str, prop: str) -> set[str]:
    """The values `kind.prop` accepts, or an empty set when it is not an enum.

    Read from the generated component contracts, so this knows what the
    renderer knows rather than restating it — a second list here would drift
    from the Zod components the way the A2UI catalog did.
    """
    try:
        from services.a2ui_catalog import load_contracts, props_for
    except Exception:  # noqa: BLE001 — never fail a translation over a lookup
        return set()
    try:
        spec = props_for(kind, load_contracts()).get(prop) or {}
    except Exception:  # noqa: BLE001
        return set()
    members = spec.get("enum")
    return {str(m) for m in members} if isinstance(members, list) else set()


def _contract_prop(kind: str, prop: str) -> dict:
    """`kind.prop`'s contract entry as `{"type": ..., "optional": ...}`, or {}.

    Read from the SAME catalogue `page_planner.validate_props` judges the
    finished page by — the tracked `contracts/component-catalog.json` — so
    what is coerced here and what is checked there cannot disagree. The
    registry's generated Zod contracts are the fallback: they are richer, but
    they are a build artefact a checkout may not have, and a coercion that
    silently did nothing on such a checkout is what this first shipped as.
    """
    try:
        from services.blueprint.page_planner import load_catalog
        entry = load_catalog().get(kind) or {}
        schema = entry.get("props") or {}
        spec = (schema.get("properties") or {}).get(prop)
        if isinstance(spec, dict):
            return {"type": spec.get("type"),
                    "optional": prop not in (schema.get("required") or [])}
    except Exception:  # noqa: BLE001 — never fail a translation over a lookup
        pass
    try:
        from services.a2ui_catalog import load_contracts, props_for
        return dict(props_for(kind, load_contracts()).get(prop) or {})
    except Exception:  # noqa: BLE001
        return {}


def _required_props(kind: str) -> list[str]:
    """Every prop `kind` cannot be rendered without, per the contracts.

    Empty when the catalog cannot be read — which is the honest answer and
    also a hole: `_is_required` has the same failure and answers ``False``,
    so a thin or unreachable catalog silently blesses everything. Reported
    once here rather than pretended about at seven call sites.
    """
    try:
        from services.a2ui_catalog import load_contracts, props_for
        entry = props_for(str(kind), load_contracts())
    except Exception:  # noqa: BLE001 — a lookup must never fail a translation
        return []
    return [name for name, spec in (entry or {}).items()
            if isinstance(spec, dict) and not spec.get("optional")]


def _is_required(kind: str, prop: str) -> bool:
    """The contract knows the prop and does not mark it optional."""
    spec = _contract_prop(kind, prop)
    return bool(spec) and not spec.get("optional")


def _coerce_copy(kind: str, prop: str, value: Any) -> Any:
    """A literal read out of the sample model, in the type the contract asks
    for.

    A2UI types a caption as DynamicString, which admits a binding; the
    composer bound `Table.caption` to a count and the sample model answered
    `6`. The contract wants a string, so the page was refused for a value that
    was right in everything but its type. The same value, typed as declared:
    a number becomes its text, a numeric string becomes its number, "true"
    becomes true. Nothing is invented; only the spelling changes.
    """
    if isinstance(value, bool):
        scalar_kind = "boolean"
    elif isinstance(value, (int, float)):
        scalar_kind = "number"
    elif isinstance(value, str):
        scalar_kind = "string"
    else:
        return value
    declared = str(_contract_prop(kind, prop).get("type") or "")
    if declared == "string" and scalar_kind != "string":
        return "true" if value is True else "false" if value is False else str(value)
    if declared in ("number", "integer") and scalar_kind == "string":
        try:
            num = float(value)
            return int(num) if declared == "integer" or num.is_integer() else num
        except ValueError:
            return value
    if declared == "boolean" and scalar_kind == "string":
        low = value.strip().lower()
        if low in ("true", "false"):
            return low == "true"
    return value


def _note_coercion(losses: "Losses | None", where: str, prop: str,
                   before: Any, after: Any) -> None:
    """Say that a literal changed type on its way through.

    Every branch of `_coerce_copy` rewrote silently — `True` became `"true"`,
    a caption reading `6` became `"6"` — and a value in the Blueprint the
    composer never wrote had no explanation anywhere. Never material: the
    value is the one that was meant, in the type the component declares.
    """
    if losses is None or before == after or type(before) is type(after):
        return
    losses.record("coerced", where, prop,
                  f"{before!r} stored as {after!r}, the type {prop!r} declares")


def _has_pointer(value: Any) -> bool:
    """Whether a literal carries `{"path": ...}` anywhere inside it."""
    if isinstance(value, dict):
        return "path" in value or any(_has_pointer(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_pointer(v) for v in value)
    return False


#: HOW MANY ROWS A MINTED LIST SOURCE FETCHES. One number, because there
#: were two: `bind()` minted every generic list at 10 and
#: `_adopt_table_bindings` minted the same kind of thing at 50, so the same
#: table showed ten rows or fifty depending on which path happened to name its
#: source. Neither cap was written down anywhere the other could see.
#:
#: The composer never says how many rows it wants, so this is not a loss of
#: its intent — it is a default, and a default that disagreed with itself.
LIST_PAGE_SIZE = 50


#: Fields that sit beside `props` in NodeV2 rather than inside it. A2UI emits
#: them among the props and the binder lifts them out afterwards, so they are
#: not unknown — they are early.
#:
#: EVERY ONE OF THESE MUST ACTUALLY BE LIFTED. `bind` sat here for the excuse
#: and nowhere else: excluded from the unknown-prop report because it was
#: "early", and then never moved, so it reached a `.strict()` node as an
#: unknown key and failed the whole page parse with no warning naming it.
_NODE_SIBLINGS = frozenset({"style", "bind", "visibleIf", "id"})


class Losses:
    """Everything this translation takes away from what the composer wrote.

    ONE CHANNEL, BECAUSE SIX WERE NONE. This module maintained `warnings`,
    `assumptions`, `unresolved`, `dangling`, `dropped_data_model_keys` and
    `dominant_entity`, built them at real cost, and every caller dropped all
    but one on the floor. So a page refused for a binding with no source was
    refused with a message about the binding, while the warning naming the
    component and prop that had been removed three hundred lines earlier went
    nowhere — and the losses with no channel at all (a whole unreferenced
    subtree, the page replaced by an empty Stack, an `optionsFrom` popped and
    never put back) left no trace anywhere.

    MATERIAL MEANS THE READER WOULD SEE A DIFFERENCE. A renamed prop and a
    coerced number are recorded and are not material: the page still shows
    what the composer meant. A dropped subtree, a control that lost its
    action, a select that lost its options — those change what is on screen,
    and `compose_page_via_a2ui` refuses the page rather than shipping the
    remains, because a composer asked again can fix what a silent removal
    cannot.
    """

    __slots__ = ("entries",)

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, kind: str, where: str, what: str, detail: str,
               *, material: bool = False) -> None:
        self.entries.append({
            "kind": kind, "where": str(where or "page"), "what": str(what or ""),
            "detail": detail, "material": bool(material),
        })

    def material(self) -> list[dict]:
        return [e for e in self.entries if e["material"]]

    def summary(self) -> str:
        """The material losses, as one line a composer can act on."""
        out = []
        for e in self.material():
            where = f"{e['where']}." if e["where"] not in ("", "page") else ""
            out.append(f"{where}{e['what']}: {e['detail']}" if e["what"]
                       else f"{where or 'page'}: {e['detail']}")
        return "; ".join(out)

    def __len__(self) -> int:  # noqa: D105
        return len(self.entries)


def _unknown_props(kind: str, props: dict) -> list[str]:
    """Props `kind` does not accept, per the generated component contracts.

    Reported, not dropped. The catalog is generated from the Zod components
    and should be authoritative, but "should be" is the wrong footing on which
    to delete a value a composer meant: if the catalog's entry for a component
    is thin, dropping would silently strip props the renderer does accept.
    Naming them puts the diagnosis in front of whoever reads the run, and the
    prop still reaches the schema exactly as it did before.

    An empty entry means the catalog knows nothing about this component, which
    is a different problem — every prop would be "unknown" and the message
    would say nothing.
    """
    try:
        from services.a2ui_catalog import load_contracts, props_for

        known = set(props_for(kind, load_contracts()) or {})
    except Exception as exc:  # noqa: BLE001 — never fail a translation over a lookup
        # A CATALOGUE THAT CANNOT BE READ BLESSES EVERYTHING. Returning an
        # empty list here reads as "nothing unknown", so a build whose
        # registry dist is missing or stale checked no prop on any component
        # and every unknown key rode through to a strict node unreported.
        # Raised as one loss, once, rather than pretended about per component.
        _catalogue_unreadable(str(exc))
        return []
    if not known:
        _catalogue_silent(str(kind))
        return []
    return sorted(k for k in props if k not in known and k not in _NODE_SIBLINGS)


#: The translation in flight, so `_unknown_props` — a module-level helper
#: every caller shares — can report a catalogue it could not read without
#: growing a parameter each of its six call sites would have to thread.
_ACTIVE_LOSSES: list["Losses"] = []


def _catalogue_unreadable(why: str) -> None:
    for ledger in _ACTIVE_LOSSES:
        if any(e["kind"] == "catalogue_unreadable" for e in ledger.entries):
            return
        ledger.record(
            "catalogue_unreadable", "page", "",
            f"the component contracts could not be read ({why[:120]}), so no "
            f"prop on any component was checked and an unknown one will be "
            f"refused by a strict node with nothing naming it",
            material=True)


def _catalogue_silent(kind: str) -> None:
    for ledger in _ACTIVE_LOSSES:
        if any(e["kind"] == "catalogue_silent" and e["what"] == kind
               for e in ledger.entries):
            return
        ledger.record(
            "catalogue_silent", "page", kind,
            f"the contracts carry no props for {kind}, so nothing it was "
            f"given could be checked")


def _dangling_workflows(node: Any, known: set[str], path: str = "props"):
    """Every `workflow` under `node` naming something outside `known`.

    Walks rather than reads one key, because a workflow reference is nested as
    often as it is top-level: `Table.rowActions[]`, `emptyAction`, and whatever
    action-bearing shape a component adds next. Clears each in place — a
    binding that resolves to nothing renders as a working control and fails on
    click, which is worse than the control not being there.
    """
    found: list[tuple[str, str]] = []
    if isinstance(node, list):
        for i, item in enumerate(node):
            found += _dangling_workflows(item, known, f"{path}[{i}]")
        return found
    if not isinstance(node, dict):
        return found
    for key, value in list(node.items()):
        if key == "workflow" and isinstance(value, str) and value:
            if value not in known:
                found.append((f"{path}.{key}", value))
                node.pop(key, None)
        elif isinstance(value, (dict, list)):
            found += _dangling_workflows(value, known, f"{path}.{key}")
    return found


def _adopt_table_bindings(schema: dict, binder: Any, registry: dict) -> None:
    """Declare a source for every dangling binding that names a real table.

    The composer writes `{{blocs}}`; the application has a `Bloc` entity whose
    table is `blocs`. That is not an invention to refuse, it is a fetch to
    declare — and declaring it is what the pointer path already does.

    Mutates `schema["dataSources"]` in place. Silent when nothing matches, so
    a genuinely invented name reaches `dangling_bindings` exactly as before.
    """
    dangling = dangling_bindings(schema)
    if not dangling:
        return

    # table -> entity, and slug -> entity. Both are names the binder itself
    # mints sources under, so both are names a composer can reasonably use.
    by_name: dict[str, str] = {}
    for ent_name, ent in (registry.get("entities") or {}).items():
        for alias in (ent.get("table"), ent.get("slug"), ent.get("camel"),
                      ent_name.lower()):
            if isinstance(alias, str) and alias:
                by_name.setdefault(alias, ent_name)

    for name in dangling:
        # Only the head of a dotted path: `{{votes.total}}` asks for `votes`.
        head = str(name).split(".")[0].strip()
        entity = by_name.get(head)
        if not entity:
            continue
        # Named exactly as the composer wrote it, or the binding still dangles
        # — `_add_source` would otherwise dedupe it onto an existing source
        # under a different name and leave the tree pointing at nothing.
        if any(s.get("name") == head for s in binder.sources):
            continue
        binder.sources.append({"name": head, "entity": entity,
                               "op": "list", "limit": LIST_PAGE_SIZE})
    schema["dataSources"] = binder.sources


#: The binding root a page's own values answer to — `{{state.display}}`.
#: One word rather than each value at the top level, so a state name can never
#: collide with a dataSource name and a reader can always tell which is which.
CLIENT_STATE_ROOT = "state"


def dangling_bindings(schema: dict) -> list[str]:
    """`{{name}}` in the tree with no dataSource named `name`.

    A composed /plants carried four stat tiles bound to
    {{plantstracked.value}}, {{overdue.value}}, {{duetoday.value}} and
    {{neverwatered.value}} against a single declared source, `plants`. A2UI
    invented a source per metric and nothing checked, so the page rendered
    four em-dashes — or the raw placeholder, which is worse, because it looks
    like a template that failed rather than a number that is missing.

    The binder rewrites the pointers it recognises and reports what it could
    not resolve; a name it never saw is neither. This is the check that says
    the two halves agree — every binding backed by a source that will actually
    be fetched.
    """
    import re

    declared = {s.get("name") for s in (schema.get("dataSources") or [])}
    # A SCREEN'S OWN VALUES ARE A SOURCE TOO. `clientState` declares values
    # that live on the page and nowhere else, read as `{{state.display}}`; the
    # binder has no fetch to rewrite for them and rightly leaves them alone,
    # so without this they read as invented and the page is refused. That is
    # what "binds {{display}}, which no data source provides" was: a
    # calculator's display, correct, and rejected for having no table behind
    # it.
    if schema.get("clientState"):
        declared.add(CLIENT_STATE_ROOT)
    found: set[str] = set()

    def _repeat_var(node: dict) -> str:
        """The loop variable a `Repeat` introduces, if it iterates a real source.

        THIS MODULE MINTS THE NODE AND DID NOT RECOGNISE IT. `_repeat_from`
        emits `{"type": "Repeat", "props": {"source": <name>, "as": "item"}}`
        and its children bind `{{item.titleAr}}` — so a page composed here was
        refused by the floor over `binding 'item' has no declared data source`,
        after A2UI had spent 140 seconds on it.

        `_row_scope` below looks for a `repeat` KEY, or for `rows`/`items`/
        `data` holding `{{…}}` syntax. A Repeat has neither: the prop is
        `source` and its value is a bare source name. Two spellings of "this is
        a row scope", with the checker attached to neither of the ones the
        translator actually produces.

        The variable is read from `as` rather than assumed to be `item`, and
        only a source the page really declares opens the scope — a Repeat over
        an invented collection is still a dangling binding and must still be
        reported.
        """
        if node.get("type") != "Repeat":
            return ""
        props = node.get("props")
        props = props if isinstance(props, dict) else {}
        source = str(props.get("source") or "").strip().split(".")[0]
        if not source or source not in declared:
            return ""
        return str(props.get("as") or "item").strip()

    def _row_scope(node: dict) -> bool:
        """Whether this node renders once per item of a declared collection.

        A ROW IS NOT THE PAGE. Inside one, `{{id}}` means this row's id and the
        renderer resolves it against the row — there is no page-level source
        called `id`, and there should not be. Read as a page binding it looked
        dangling, and /tickets was refused over `rowHref: "/tickets/{{id}}"`
        on a Table whose `rows` was bound to a declared source.

        Decided structurally, from what the node binds rather than from what
        it is called: a collection prop carrying a binding to a source the page
        declares. `repeat` is the planner's own form of the same thing.
        """
        if node.get("repeat"):
            return True
        props = node.get("props")
        props = props if isinstance(props, dict) else {}
        for prop in ("rows", "items", "data"):
            value = props.get(prop)
            if not isinstance(value, str):
                continue
            names = [m.split(".")[0].strip()
                     for m in re.findall(r"\{\{([^}]+)\}\}", value)]
            if any(n in declared for n in names):
                return True
        return False

    def walk(node: Any, in_row: bool = False,
             bound: frozenset[str] = frozenset()) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n, in_row, bound)
            return
        if not isinstance(node, dict):
            return
        # The collection binding itself is page-level — it is what opens the
        # row scope — so the node is judged before the scope is entered.
        row = in_row or _row_scope(node)
        var = _repeat_var(node)
        # NAMED, NOT BLANKET. `row` suppresses every unknown name inside it,
        # which is right when the row's fields are unknowable. A Repeat says
        # exactly what its variable is called, so only that one is bound and
        # anything else inside it is still reported.
        inner = bound | {var} if var else bound
        for value in node.values():
            if isinstance(value, str):
                # `{{plants}}` and `{{record.title}}` both name `plants`/`record`.
                names = [m.split(".")[0].strip()
                         for m in re.findall(r"\{\{([^}]+)\}\}", value)]
                # Within a row, only a name the page actually declares is a
                # page binding; anything else is a field of the row.
                found.update(n for n in names
                             if n not in bound and (not row or n in declared))
            else:
                walk(value, row, inner)

    walk(schema.get("root"))
    return sorted(n for n in found if n and n not in declared)


def _enum_options_for_field(registry: dict, field_name: str,
                            prefer_entity: str | None) -> list[dict] | None:
    """Declared ``options`` for a Form field that names a schema enum column.

    A workflow field like ``mediaType`` is written to a column the form's route
    entity does not own — ``ConditionEvidence`` reached through the workflow's
    insert step, on a ``/rentals/[id]/return`` form whose entity is ``Rental`` —
    so the composer ships it as a bare ``select`` with neither ``options`` nor a
    source, and the Form-field contract refuses a select with neither. The enum
    is still knowable from the schema: resolve the column by the field's name —
    the form entity first, then a UNIQUE match across entities so an ambiguous
    name (a ``status`` on Rental AND Dispute, different vocabularies) is left
    alone rather than guessed. Reads the enum key tolerantly, since the registry
    has carried it as ``enum``/``enum_values``/``enumValues`` at different times.
    """
    ents = (registry or {}).get("entities") or {}
    want = _slugify(field_name)
    if not want:
        return None

    def col_enum(entity: str | None) -> list[str] | None:
        for c in (ents.get(entity or "") or {}).get("columns") or []:
            if _slugify(str(c.get("name") or "")) != want:
                continue
            vals = c.get("enum") or c.get("enum_values") or c.get("enumValues")
            return [str(v) for v in vals] if isinstance(vals, list) and vals else None
        return None

    vals = col_enum(prefer_entity)
    if not vals:
        hits = [v for ent in ents if (v := col_enum(ent))]
        vals = hits[0] if len(hits) == 1 else None
    return [{"value": v, "label": v} for v in vals] if vals else None


def _translate_option_sources(root: Any, binder: Any, registry: dict) -> None:
    """Every place the tree says where options come from, in the contract's words.

    Three shapes, one meaning. A declarative Form field carries `optionsFrom`
    at the top level or under `interaction`; a Select-like node carries it in
    `props`; and a list of `items` may name each choice by label alone. The
    Form field schema reads `interaction.optionsFrom` and allows an empty
    `options` beside it — the shape a runtime-sourced dropdown ships in; the
    Select contract still wants a declared option; and an item needs a
    `value` — which, unsaid, is its label. Mutates in place; runs
    before `dataSources` is sealed so the lists it registers ship with the
    page.
    """
    def walk(node: Any) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n)
            return
        if not isinstance(node, dict):
            return
        props = node.get("props")
        if isinstance(props, dict):
            kind = str(node.get("type") or "")
            if kind in ("Select", "Combobox", "MultiSelect", "RadioGroup"):
                # The source is translated, and an empty `options` beside it
                # goes: declared options number at least one, and a dropdown
                # whose rows come from a list at render time declares none.
                translated = option_source(binder, registry, props.get("optionsFrom"))
                if translated:
                    props["optionsFrom"] = translated
                if props.get("optionsFrom") and props.get("options") == []:
                    props.pop("options")
            if kind == "Form":
                form_entity = getattr(binder, "form_entity", None)
                for field in props.get("fields") or []:
                    if not isinstance(field, dict):
                        continue
                    spoken = field.pop("optionsFrom", None)
                    interaction = field.get("interaction") if isinstance(field.get("interaction"), dict) else None
                    if spoken is None and interaction:
                        spoken = interaction.get("optionsFrom")
                    if spoken is not None:
                        translated = option_source(binder, registry, spoken)
                        final = translated or (spoken if isinstance(spoken, dict) and spoken.get("source") else None)
                        if final:
                            field.setdefault("interaction", {})["optionsFrom"] = final
                            field.setdefault("options", [])
                            continue
                        # POPPED AND NEVER PUT BACK. `spoken` came off the
                        # field at the top of this branch; when the source
                        # could not be resolved the `continue` below skipped
                        # the schema-enum recovery too, so the field shipped
                        # with neither options nor a source — and the Form
                        # contract refuses exactly that. The composer had
                        # named a source and the translation lost it.
                        #
                        # Fall through to the enum recovery rather than
                        # continuing, and say what was lost if that fails too.
                        binder._record(
                            "dropped_prop", str(c.get("id") or ""),
                            "optionsFrom",
                            f"named a source this page cannot resolve "
                            f"({spoken!r}); recovering options from the schema")
                    # No source named. A select over a schema enum still needs
                    # its options declared — the composer omits them for a column
                    # the route entity does not own (a workflow field written to
                    # a secondary entity), and the contract refuses a select with
                    # neither options nor a source. Recover them from the schema.
                    fkind = str(field.get("kind") or field.get("component") or "").lower()
                    if (fkind in ("select", "multiselect", "radiogroup", "combobox")
                            and not field.get("options")):
                        opts = _enum_options_for_field(
                            registry, str(field.get("name") or ""), form_entity)
                        if opts:
                            field["options"] = opts
            items = props.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "value" not in item and item.get("label") is not None:
                        item["value"] = str(item["label"])
            # A PLACEHOLDER IS NOT AN OPTION. "Select a category" with value ""
            # is how a composer says what an empty select shows; the contract
            # says it with `placeholder` and refuses an option with no value.
            _placeholder_out_of_options(
                props, getattr(binder, "losses", None), str(node.get("id") or ""))
            if kind == "Form":
                for field in props.get("fields") or []:
                    if isinstance(field, dict):
                        _placeholder_out_of_options(
                            field, getattr(binder, "losses", None),
                            str(node.get("id") or ""))
        for child in node.get("children") or []:
            walk(child)
    walk(root)


def _placeholder_out_of_options(holder: dict, losses: "Losses | None" = None,
                                where: str = "") -> None:
    options = holder.get("options")
    if not isinstance(options, list):
        return
    kept = []
    for opt in options:
        if isinstance(opt, dict) and str(opt.get("value") or "") == "":
            if opt.get("label") and not holder.get("placeholder"):
                holder["placeholder"] = str(opt["label"])
            elif opt.get("label") and losses is not None:
                # THE LABEL GOES NOWHERE. The option is removed because it has
                # no value, and its text is kept only when there is no
                # placeholder already — otherwise the composer's wording was
                # deleted outright with nothing saying so.
                losses.record(
                    "dropped_option", where, str(opt["label"]),
                    f"an option with no value, and {holder['placeholder']!r} "
                    f"is already the placeholder")
            continue
        kept.append(opt)
    if len(kept) != len(options):
        holder["options"] = kept


def translate(payload: dict, registry: dict, route: str = "/",
              page_id: str = "home", kind: str = "",
              entity_hints: dict | None = None) -> dict:
    """A2UI surface → Forge page schema. Returns {schema, warnings, dropped}."""
    comps: dict[str, dict] = {}
    data_model: dict = {}
    # BEFORE THE FIRST MESSAGE IS READ. The ingest loop below is itself a
    # place things are lost — a duplicate id, a component with none — so the
    # ledger has to exist before it, not beside the binder that comes after.
    losses = Losses()
    _ACTIVE_LOSSES.append(losses)
    try:
        return _translate(payload, registry, route, page_id, kind,
                          entity_hints, comps, data_model, losses)
    finally:
        _ACTIVE_LOSSES.remove(losses)


def _translate(payload: dict, registry: dict, route: str, page_id: str,
               kind: str, entity_hints: dict | None, comps: dict[str, dict],
               data_model: dict, losses: "Losses") -> dict:
    """The translation itself. Split from :func:`translate` only so the
    ledger can be registered and removed around it — nothing else moved."""
    for msg in payload.get("messages", []) or []:
        for c in (msg.get("updateComponents") or {}).get("components", []) or []:
            cid = c.get("id")
            if cid is None:
                # UNADDRESSABLE. It lands under the key `None`, which nothing
                # can reference, so it is written and never placed. Caught
                # here rather than by the orphan pass, which would report it
                # as "pointed at from nowhere" and hide the real reason.
                losses.record(
                    "dropped_component", "", str(c.get("component") or "?"),
                    "written with no id, so nothing can reference it",
                    material=True)
                continue
            if cid in comps:
                # THE SECOND ONE WINS, SILENTLY. Two components declaring the
                # same id — or one redeclared across `updateComponents`
                # messages — overwrote each other here, so a whole component
                # left the payload without a word.
                losses.record(
                    "dropped_component", str(cid),
                    str(comps[cid].get("component") or "?"),
                    f"a second component declares the same id, and it "
                    f"replaced this one",
                    material=True)
            comps[cid] = c
        if "updateDataModel" in msg:
            replacement = msg["updateDataModel"].get("value") or {}
            if data_model and replacement is not data_model:
                # LAST ONE WINS. A composer sending the model in parts had
                # every part but the last discarded, so pointers into the
                # earlier ones resolved to nothing and their props were
                # dropped — reported, much later, as bindings with no source.
                losses.record(
                    "dropped_data_model", "page", "updateDataModel",
                    f"a later message replaced the data model; "
                    f"{', '.join(sorted(data_model)[:6]) or 'its keys'} are "
                    f"no longer readable")
            data_model = replacement

    binder = _Binder(registry, data_model)
    # THE SAME LEDGER, REACHABLE FROM INSIDE THE BINDER. The sites that drop a
    # prop deep inside `bind()` write to the one the ingest loop already used.
    binder.losses = losses
    binder.page_kind = str(kind or "").strip().lower()
    # The route drives `is_record_page()`: a `[id]` segment means one existing
    # record is in scope, whatever the declared pattern.
    binder.route = str(route or "")
    # The entity this page's own contract says it is about — the last thing
    # tried before a pointer is left unbound.
    binder.page_entity = str(
        (registry.get("pageEntity") or {}).get(str(page_id)) or "")
    binder.entity_hints = dict(entity_hints or {})

    # Which entity does this surface mostly talk about? Counted over every path
    # segment and label that names one, so the tie-break is evidence rather than
    # document order.
    tally: dict[str, int] = {}
    for c in comps.values():
        hints = [binder.label_of(c)]
        for v in c.values():
            if isinstance(v, dict) and "path" in v:
                hints += [s2 for s2 in str(v["path"]).split("/") if s2]
        for h in hints:
            ent = _resolve_entity(h, binder.idx)
            if ent:
                tally[ent] = tally.get(ent, 0) + 1
    if tally:
        binder.dominant = max(tally, key=lambda k: tally[k])

    # A form writes to ONE record, so its entity is resolved once from the
    # route ("/bills/new" -> Bill) rather than per field. Guessing per field
    # would let a single typo split a form silently across two tables, which
    # renders perfectly and fails at submit.
    binder.form_entity = (
        _resolve_entity(" ".join(s2 for s2 in route.split("/") if s2), binder.idx)
        or binder.dominant
    )

    # A record page needs a record entity for `record_source` to mint the
    # `get`-by-id source its `/entity/*` pointers and workflow bind through. The
    # tally sets `dominant` when the surface's paths name the entity, but a
    # composer that used a generic `/record` key names none — so an edit page
    # over an existing record could still find nothing. The route names it
    # (`/records/[id]/edit` -> Record) and the contract names it (`page_entity`);
    # fall back to those rather than leave a record page with no record.
    if binder.is_record_page() and not binder.dominant:
        binder.dominant = binder.form_entity or (binder.page_entity or None)

    def resolve(v: Any, comp: dict, prop: str) -> Any:
        if isinstance(v, dict) and "path" in v:
            out = binder.bind(str(v["path"]), comp, prop)
            if out == "__literal__":
                # Substitute the shape the composer designed against, read out
                # of the sample data model.
                node: Any = data_model
                for seg in [s for s in str(v["path"]).split("/") if s]:
                    node = (node or {}).get(seg) if isinstance(node, dict) else None
                return node
            return out
        return v

    def at_path(path: str) -> Any:
        node: Any = data_model
        for seg in [s2 for s2 in str(path).split("/") if s2]:
            node = node.get(seg) if isinstance(node, dict) else None
        return node

    def repeat_over(container: dict, template: dict, base: str) -> dict | None:
        """Homogeneous records → one Repeat over a real list source.

        The alternative — cloning the template once per row of the sample model
        — would ship four hard-coded cards reading "Follow up with client",
        which is exactly the fiction this module exists to strip.
        """
        probe = {"id": container.get("id"), "component": "Repeat",
                 "label": container.get("title") or ""}
        binding = binder.bind(base, probe, "rows") or ""
        source = binding.strip("{}")
        if not source:
            return None  # bind() already recorded why
        clone_id = f'{template.get("id")}-item'
        clone = dict(template)
        clone["id"] = clone_id
        for k, v in template.items():
            if isinstance(v, dict) and "path" in v:
                # Inside a Repeat the row is in scope as `item`, so a pointer
                # relative to the row becomes a relative binding, not a source.
                clone[k] = f'{{{{item.{str(v["path"]).lstrip("/")}}}}}'
        comps[clone_id] = clone
        inner = build(clone_id, scope="item")
        if not inner:
            return None
        return {"type": "Repeat", "props": {"source": source, "as": "item"},
                "children": [inner]}

    def expand_template(container: dict, spec: dict) -> list[dict]:
        """A2UI's repeated child → concrete Forge nodes.

        A2UI says "render component X once per element of array Y":

            {"id": "kpiRow", "component": "Row",
             "children": {"componentId": "kpiTile", "path": "/kpis"}}

        Forge has no template node, and the two shapes this collapses to are
        genuinely different pages:

        * The array is a list of RECORDS (``/tasks/rows``) → a ``Repeat`` bound
          to one list source. Row count is a runtime fact.
        * The array is a list of SPECS (``/kpis`` — each element carries its own
          label) → N distinct nodes, each with its own bound source, because
          "In Progress" and "Completed" are different queries, not two rows of
          one. Row count is an authoring decision, so it is honest to read it
          off the sample model.

        Telling them apart on whether the path names an entity is inference,
        and it is the only inference here: getting it wrong turns four KPIs into
        one empty Repeat, or four rows of invented data into the page.
        """
        tid = str(spec.get("componentId") or "")
        base = str(spec.get("path") or "")
        template = comps.get(tid)
        if not template or not base:
            binder.warnings.append(
                f'{container.get("id")}: template child names component '
                f"{tid!r} at {base!r}, which does not resolve — rendered nothing.")
            return []

        if _resolve_entity(" ".join(s2 for s2 in base.split("/") if s2), binder.idx):
            node = repeat_over(container, template, base)
            return [node] if node else []

        items = at_path(base)
        if not isinstance(items, list) or not items:
            binder.warnings.append(
                f'{container.get("id")}: template over "{base}" names no entity '
                f"and the sample model holds no array there, so how many "
                f"instances to draw is unknowable — rendered nothing.")
            return []

        out: list[dict] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                # AN INSTANCE THAT NEVER DREW. The spec said four tiles and
                # three were rendered, with no message: a reader counting the
                # summary row sees one fewer number than the composer put
                # there.
                losses.record(
                    "dropped_component", str(tid), f"instance {i}",
                    f"the repeat's data holds a {type(item).__name__} at "
                    f"position {i}, not an object, so that instance was not "
                    f"drawn",
                    material=True)
                continue
            clone = dict(template)
            clone["id"] = f"{tid}-{i}"
            for k, v in template.items():
                if not (isinstance(v, dict) and "path" in v):
                    continue
                rel = str(v["path"]).lstrip("/")
                if k in _DATA_PROPS:
                    # Left as a pointer so the binder resolves it to a real
                    # source. Absolute, so each instance gets its own cache
                    # entry instead of all four collapsing onto one count.
                    clone[k] = {"path": f"{base}/{i}/{rel}"}
                else:
                    # Labels are copy the composer authored, not invented data
                    # — the one part of updateDataModel worth keeping, and the
                    # only thing that tells the binder these are four different
                    # queries.
                    # A KEY THE SAMPLE ITEM DOES NOT CARRY becomes None
                    # here and is dropped further down, so an expanded
                    # MetricTile can lose its `label` — required, and gone
                    # from every instance at once, silently.
                    clone[k] = item.get(rel)
                    if clone[k] is None:
                        losses.record(
                            "dropped_prop", f"{tid}-{i}", k,
                            f"the repeat's item {i} has no {rel!r}, so this "
                            f"instance was left without it",
                            material=True)
            comps[clone["id"]] = clone
            node = build(clone["id"])
            if node:
                out.append(node)
        return out

    def build(cid: str, scope: str = "") -> dict | None:
        """``scope`` is the name the current row is bound under, inside a
        Repeat — "" when this node is not in one.

        Threaded rather than inferred because only the caller knows: the same
        component id is built as a standalone widget in one place and as a
        Repeat's template in another, and a pointer means a different thing in
        each.
        """
        c = comps.get(cid)
        if not c:
            # A PARENT POINTING AT NOTHING. The child is filtered out of
            # `kids` by the caller and the page ships one component short,
            # with no record anywhere — the mirror of an orphan, and the more
            # common of the two: an id that a later edit renamed, or a
            # component the composer meant to emit and did not.
            losses.record(
                "missing_component", str(cid), "",
                "a parent lists it as a child and no component carries that "
                "id, so that part of the page was never built",
                material=True)
            return None
        kind = c.get("component")

        # Form fields are the one place the composer's component choice is not
        # final: the column's SQL type outranks it, and a field naming no
        # column must not ship at all. See `_Binder.resolve_field`.
        if kind in _FIELD_TYPES:
            resolved = binder.resolve_field(c)
            if resolved is None:
                return None
            new_kind, field_props = resolved
            node: dict[str, Any] = {"type": new_kind, "props": field_props}
            # Same lift as the general builder below. c051f6f patched only
            # that one, and a form field composed through this path still
            # arrived with `style` inside props — the identical rejection, in
            # a branch the synthetic tree I verified against never reached.
            style = field_props.pop("style", None)
            if style is not None:
                node["style"] = style
            if c.get("id"):
                node["id"] = c["id"]
            return node
        aliases = _PROP_ALIASES.get(kind, {})
        unsupported = _UNSUPPORTED.get(kind, frozenset())
        props: dict[str, Any] = {}

        def pointer_binding(raw2: str, where: str) -> str | None:
            """A pointer nested inside a prop → a `{{binding}}`, or None with
            the reason recorded. Same rule as the dict-of-pointers branch:
            the record this page shows, the row in scope, or nothing."""
            segs2 = [x for x in raw2.strip("/").split("/") if x]
            if (binder.is_record_page() and len(segs2) >= 2
                    and binder.dominant
                    and isinstance(at_path("/" + segs2[0]), dict)):
                src2 = binder.record_source(binder.dominant)
                return f"{{{{{src2}.{segs2[-1]}}}}}"
            if scope and segs2 and not raw2.startswith("/"):
                return f"{{{{{scope}.{segs2[-1]}}}}}"
            binder.warnings.append(
                f'{c.get("id")}.{where}: "{raw2}" resolves to no source on '
                f"this page — dropped rather than sent as a pointer the "
                f"renderer cannot read.")
            return None
        # WRITTEN DOWN BEFORE THEY DISAPPEAR. These two filters removed
        # props ahead of every other branch, so nothing downstream could
        # report them: `weight` is a real layout intent (how much space this
        # child takes) thrown away, and `_UNSUPPORTED` drops `Text.variant`
        # and `Heading.variant` — the composer's typographic choice — with the
        # component never learning it was asked for.
        #
        # Not material: the page still shows what the composer meant, in a
        # default weight and a default size. Recorded so "why does this look
        # evenly spaced when I asked for 2:1" has an answer.
        for k in c:
            if k in _CHILD_KEYS or k == "component" or k == "id":
                continue
            if k in _DROP_PROPS:
                binder._record("dropped_prop", c.get("id"), k,
                               f"{kind} carries no {k!r} through translation")
            elif k in unsupported:
                binder._record("dropped_prop", c.get("id"), k,
                               f"the {kind} component has no {k!r}")

        items = [(k, v) for k, v in c.items()
                 if k not in _DROP_PROPS and k not in _CHILD_KEYS
                 and k not in unsupported]
        # Data props are resolved FIRST because they are what establish which
        # entity this component is about, and the derived props below have to
        # be resolved against that same entity.
        items = ([kv for kv in items if kv[0] in _DATA_PROPS]
                 + [kv for kv in items if kv[0] not in _DATA_PROPS])

        for k, val in items:
            if k == "breakdown" and isinstance(val, list):
                # Recoverable: the values are invented but each label names a
                # real subset. Bind them rather than discard the intent.
                rows = binder.resolve_breakdown(c, val)
                if rows:
                    props[k] = rows
                continue

            _is_bound = isinstance(val, dict) or (
                isinstance(val, str) and "{{" in val)
            if k in _MEASURED_PROPS and not _is_bound:
                if k == "trend":
                    # Genuinely blocked, not merely refused: a time series IS
                    # derivable here (op:"series" over a date column with a
                    # bucket), but MetricTile's sparkline reads raw numbers and
                    # a series source resolves to {label, value} rows, so
                    # binding it would plot NaN. Recorded as a gap in the
                    # component, not treated as fiction the composer invented.
                    binder.unresolved.append(
                        f'{c.get("id")}.trend: a real series is derivable, but '
                        f"MetricTile's sparkline reads raw numbers while "
                        f"op:\"series\" yields {{label, value}} rows. Needs the "
                        f"component to accept both before this can bind.")
                else:
                    binder.unresolved.append(
                        f'{c.get("id")}.{k}: reads as a measured comparison and '
                        f"nothing in the registry says over what period, so it "
                        f"cannot be derived. Left out — a number nobody counted "
                        f"renders exactly like one that was.")
                continue
            if k in _DATA_PROPS:
                if isinstance(val, list) and k not in _CONFIG_DATA_PROPS \
                        and _has_pointer(val):
                    # A LIST OF COPY WITH BOUND VALUES IS NOT FICTION. A
                    # record page's metadata block — KeyValueList items of
                    # `{label: "Created", value: {path: "/note/createdAt"}}` —
                    # is labels the composer wrote and values the record
                    # supplies. The literal check below saw a list, called it
                    # invented rows and dropped it, and the contract then
                    # refused the component for the `items` it requires.
                    # Each pointer inside is bound the way a pointer prop is;
                    # the labels ride along as the copy they are.
                    resolved = [
                        {k2: (pointer_binding(str(v["path"]), f"{k}[{i}].{k2}")
                              if isinstance(v, dict) and "path" in v else v)
                         for k2, v in el.items()}
                        if isinstance(el, dict) else el
                        for i, el in enumerate(val)
                    ]
                    resolved = [
                        {k2: v for k2, v in el.items() if v is not None}
                        if isinstance(el, dict) else el
                        for el in resolved
                    ]
                    props[k] = resolved
                    continue
                if not isinstance(val, dict) and k not in _CONFIG_DATA_PROPS:
                    # A scalar `value` on a measuring component is recoverable:
                    # the number is invented but the label names a real subset,
                    # so count that subset instead of dropping the widget's
                    # only value and shipping an empty gauge.
                    if k == "value" and isinstance(val, (int, float)) \
                            and not isinstance(val, bool):
                        bound = binder.measure_from_label(c, k)
                        if bound:
                            props[k] = bound
                            continue
                    # Not a pointer at all — a literal rows/data array is the
                    # same fiction wearing a different prop name, and `resolve`
                    # would hand it straight through.
                    if _is_required(kind, k):
                        # A component without the prop its contract requires
                        # is not a component. Shipping it failed the page on
                        # a `required` check far from here; the composer
                        # wrote content nothing fetches, so the honest
                        # outcome is no component — said so, not silently.
                        binder.warnings.append(
                            f'{c.get("id")}.{k}: {kind} requires {k!r} and the '
                            f"composer wrote a literal nothing on this page "
                            f"reads — the component is left out rather than "
                            f"shipped invalid or with invented rows.")
                        return None
                    binder.warnings.append(
                        f'{c.get("id")}.{k}: dropped a literal on a data prop '
                        f"— rows the page did not read from anywhere.")
                    continue
                resolved = resolve(val, c, k)
            elif (isinstance(val, dict) and "path" not in val and val
                  and any(isinstance(v, dict) and "path" in v
                          for v in val.values())):
                # A DICT OF POINTERS — `Button.args`, the inputs a dispatched
                # workflow acts on. The branch below reads a prop that IS a
                # pointer; this is a prop whose VALUES are, so it matched
                # neither and the raw {"path": ...} dicts rode into the schema.
                # `interpolateDeep` resolves `{{...}}` strings and nothing
                # else, so the click posted {"ticketId": {"path": "/ticket/id"}}
                # and the workflow received an object where an id belongs —
                # the same null-column failure the args channel was opened to
                # fix.
                #
                # A BINDING, NEVER A LITERAL. The copy branch may read a value
                # out of the sample model, which is right for a heading and
                # wrong here: baking "TCK-1042" into args sends every click the
                # same id. The pointer names where the value lives, and that is
                # what has to survive to dispatch time.
                resolved = {}
                for k2, v in val.items():
                    if not (isinstance(v, dict) and "path" in v):
                        resolved[k2] = v
                        continue
                    raw2 = str(v["path"])
                    segs2 = [x for x in raw2.strip("/").split("/") if x]
                    if (binder.is_record_page() and len(segs2) >= 2
                            and binder.dominant
                            and isinstance(at_path("/" + segs2[0]), dict)):
                        # The record this page shows — the same rule the copy
                        # branch uses, so args and the fields around it name
                        # one source rather than two.
                        src2 = binder.record_source(binder.dominant)
                        resolved[k2] = f"{{{{{src2}.{segs2[-1]}}}}}"
                    elif scope and segs2 and not raw2.startswith("/"):
                        # Inside a repeat the row is bound under its `as` name,
                        # so a row-relative pointer follows the row — which is
                        # what a per-row action needs.
                        resolved[k2] = f"{{{{{scope}.{segs2[-1]}}}}}"
                    else:
                        # No source and no row: any binding here would name
                        # something nothing fetches. Dropped with a reason,
                        # because a missing input fails at the workflow where
                        # it can be read, and an unresolvable pointer fails
                        # silently as an object.
                        binder.warnings.append(
                            f'{c.get("id")}.{k}.{k2}: "{raw2}" resolves to no '
                            f"source on this page — dropped rather than sent "
                            f"as a pointer the renderer cannot read.")
                        # ONE INPUT SHORT IS THE WHOLE POINT OF `args`. The
                        # control still dispatches and the workflow receives
                        # nothing for this parameter, which fails at the
                        # workflow rather than at render — so a button that
                        # looks right writes a row with a null column.
                        binder._record(
                            "dropped_prop", c.get("id"), f"{k}.{k2}",
                            f"{raw2!r} resolves to no source, so the workflow "
                            f"receives nothing for {k2!r}",
                            material=True)
                if not resolved:
                    # EVERY KEY FAILED, so the prop itself vanishes here — the
                    # one event in this branch that was reported nowhere,
                    # because the per-key warnings above say a key went and
                    # nothing says the dispatch now carries no inputs at all.
                    binder._record(
                        "dropped_prop", c.get("id"), k,
                        f"every value in {k!r} resolved to no source, so the "
                        f"dispatch carries no inputs",
                        material=True)
                    continue
            elif isinstance(val, dict) and "path" in val:
                # A pointer on a non-data prop is COPY — a header title, a card
                # heading. Reading it off the sample model is the one honest use
                # of that model, and the alternative is worse than it looks: the
                # raw {"path": ...} dict passes straight through into `props`,
                # where a `.strict()` string field rejects it and the whole page
                # fails to parse.
                raw = str(val["path"])
                # A RECORD'S FIELDS ARE NOT COPY. This branch reads a pointer
                # off the sample data model, which is right for a card heading
                # and ruinous for the record the page exists to show: every
                # `/ticket/subject` became the sample string, so /tickets/[id]
                # shipped one hardcoded fictional ticket and rendered it
                # whichever ticket you opened. Nothing reported it, because a
                # page full of plausible text looks exactly like a page that
                # works.
                #
                # Bound when the page is about one record AND the pointer
                # names a field of an object in the sample — `/ticket/subject`
                # yes, `/ticketDetails` (a list) no, `/heading` no. The
                # resulting string passes the literal check below untouched,
                # so the repair chain stays for the cases it was written for.
                segs = [seg for seg in raw.strip("/").split("/") if seg]
                if (binder.is_record_page() and len(segs) >= 2
                        and binder.dominant
                        and isinstance(at_path("/" + segs[0]), dict)):
                    src = binder.record_source(binder.dominant)
                    resolved = f"{{{{{src}.{segs[-1]}}}}}"
                    binder.assumptions.append(
                        f'{c.get("id")}.{k}: "{raw}" names a field of the '
                        f"record this page shows — bound to {resolved!r} "
                        f"rather than read out of the sample.")
                else:
                    spoken_copy = at_path(raw)
                    resolved = _coerce_copy(kind, k, spoken_copy)
                    _note_coercion(getattr(binder, "losses", None),
                                   str(c.get("id") or ""), k,
                                   spoken_copy, resolved)
                if not isinstance(resolved, (str, int, float, bool)):
                    field = raw.strip("/").split("/")[-1]
                    members = _enum_members(kind, k)
                    if scope and field and not raw.startswith("/"):
                        # THE ROW IS IN SCOPE, SO SAY SO. A relative pointer
                        # means "this row's field", and inside a Repeat the
                        # renderer can read exactly that: `Repeat` binds each
                        # element into the render data under its `as` name, so
                        # `{{item.statusVariant}}` resolves per row.
                        #
                        # `expand_records` has always emitted this for the
                        # props it rewrites on the way into a Repeat; the
                        # generic path could not, because it did not know
                        # whether it was inside one. So the same pointer became
                        # a bare field name — right for `Kanban.cardTitle`,
                        # which names a field, and wrong for `Badge.variant`,
                        # which takes one of five values and got the literal
                        # "statusVariant".
                        #
                        # Safe on an enum prop: the A2UI catalog admits a
                        # binding beside the members, and `validate_props`
                        # defers a binding string because the renderer supplies
                        # the value later.
                        resolved = f"{{{{{scope}.{field}}}}}"
                        binder.assumptions.append(
                            f'{c.get("id")}.{k}: "{raw}" is row-relative and '
                            f"this node is inside a repeat — bound to "
                            f"{resolved!r}, so it follows the row.")
                    elif members and field not in members:
                        # AN ENUM PROP TAKES A MEMBER, NOT A FIELD NAME. The
                        # rule below is right for `Kanban.cardTitle`, which
                        # names the field to read — but `Badge.variant` takes
                        # one of five fixed values, and A2UI's
                        # `{"path": "statusVariant"}` became the literal
                        # "statusVariant", which is not one of them. The page
                        # failed validation and did not ship.
                        #
                        # Dropped, so the prop falls back to its default and
                        # the badge renders in a neutral style. A row-relative
                        # binding is a real intent this contract cannot express
                        # — losing the colour is the small half of that, and
                        # losing the page was the large one.
                        resolved = None
                        binder.warnings.append(
                            f'{c.get("id")}.{k}: "{raw}" is row-relative and '
                            f"{k!r} takes one of {sorted(members)} — dropped, "
                            f"so the default applies rather than failing the "
                            f"page.")
                    elif not raw.startswith("/") and raw.strip("/"):
                        # A relative pointer is scoped to the row, so on a prop
                        # like Kanban's `cardTitle` it names a FIELD, and the
                        # field name is the literal Forge wants. Dropping it
                        # (as this did) left the cards with no title.
                        resolved = field
                        binder.assumptions.append(
                            f'{c.get("id")}.{k}: "{raw}" is row-relative; read '
                            f"as the field name {resolved!r}.")
                    else:
                        binder.warnings.append(
                            f'{c.get("id")}.{k}: "{raw}" holds no literal in '
                            f"the sample model — prop dropped rather than "
                            f"emitted as a pointer the renderer cannot read.")
                        resolved = None
            else:
                resolved = val
            if isinstance(resolved, str):
                spoken = resolved
                resolved = _ENUM_SYNONYMS.get(k, {}).get(resolved, resolved)
                if resolved != spoken:
                    # `direction: "column"` becomes `"vertical"`. The right
                    # rewrite, and it left no trace, so a value in the
                    # Blueprint that the composer never wrote had no
                    # explanation anywhere.
                    binder._record("coerced", c.get("id"), k,
                                   f"{spoken!r} read as {resolved!r}")
            if resolved is not None:
                canonical = aliases.get(k, k)
                if canonical in props and canonical != k:
                    # BOTH SPELLINGS ON ONE COMPONENT. A Badge carrying
                    # `label` AND `content` renamed the first onto the second
                    # and one of them won silently — the composer's copy,
                    # gone, with the page looking fine.
                    binder._record(
                        "overwritten", c.get("id"), canonical,
                        f"written both as {k!r} and as {canonical!r}; "
                        f"{props[canonical]!r} replaced by {resolved!r}",
                        material=True)
                if canonical != k:
                    # Said out loud. The catalog already offers the right name,
                    # so a rename reaching here means the composer was told and
                    # wrote something else anyway — worth seeing, not worth
                    # losing the page over.
                    binder.warnings.append(
                        f'{c.get("id")}.{k}: {kind} has no {k!r} prop; '
                        f"renamed to {canonical!r}. The catalog offers "
                        f"{canonical!r} — the composer should be writing it."
                    )
                props[canonical] = resolved
        # EVERY workflow reference, not the one on the component itself. A
        # `workflow` also lives inside `Table.rowActions[]`, `emptyAction`, and
        # any other action object a component accepts — and a composed /plants
        # shipped rowActions[0].workflow = "markPlantWatered", an id no
        # workflow has, which reached the browser and answered "Workflow not
        # found" on click. Six sibling bindings on the same page were correct
        # FLOW ids; this one was invented, and the check that exists to catch
        # exactly that only looked at the top level.
        if kind in ("Form", "Button") and props.get("workflow"):
            # By id, because `/api/workflows/{id}/execute` is what the renderer
            # POSTs to. This compared against workflow *names*, so the only
            # value that reaches a live route was the one it rejected.
            #
            # Buttons were never checked at all — the composer had no workflow
            # vocabulary to get wrong, so nothing exercised it. It has one now.
            known = {str(w.get("id")) if isinstance(w, dict) else str(w)
                     for w in (binder.registry.get("workflows") or [])}
            if known and str(props["workflow"]) not in known:
                # A submit pointed at a workflow that does not exist fails on
                # click. Dropping it leaves the form for the existing post-gen
                # seams (orphan_wiring_pass, the form_target guard), which are
                # already the authority on submit targets — better than this
                # module inventing a second opinion.
                binder.unresolved.append(
                    f'{c.get("id")}: {kind} targets workflow '
                    f'"{props["workflow"]}", which this app does not define. '
                    f"Cleared for the submit-authority pass to resolve.")
                props.pop("workflow", None)

        for req, default in _REQUIRED_DEFAULTS.get(kind, {}).items():
            if req not in props:
                props[req] = default
                binder.warnings.append(
                    f'{c.get("id")}.{req}: {kind} requires a {req!r} and none '
                    f"was given; defaulted to {default!r}. The catalog marks "
                    f"it required — the composer should be choosing it."
                )
        # WHAT THE BINDER DECIDES, OVER WHAT THE COMPOSER WROTE. `Chart.series`
        # and `xKey` are set from the resolved grouping, so a composer-authored
        # series was replaced wholesale and the substitution left no trace —
        # a chart plotting a different column than the one it was told to.
        mine = binder.extra_props.get(str(c.get("id")), {})
        for prop, value in mine.items():
            if prop in props and props[prop] != value:
                binder._record(
                    "overwritten", c.get("id"), prop,
                    f"the binder resolved {prop!r} from the data and replaced "
                    f"what the composer wrote")
        props.update(mine)

        # AFTER THE ALIASES AND THE BINDER'S OWN PROPS, so `Badge.label` is
        # already `content` and nothing this module attaches is reported as
        # the composer's invention.
        #
        # A prop no component accepts does not fail here — it rides into
        # `props` and meets a `.strict()` field downstream, where the whole
        # page fails to parse and the message names a schema path rather than
        # the component that carried it. This says which component and which
        # prop, at the point where that is still cheap to know.
        for bad in _unknown_props(kind, props):
            binder.warnings.append(
                f'{c.get("id")}.{bad}: {kind} does not accept a {bad!r} prop. '
                f"Passed through unchanged — it may be rejected downstream.")
            binder._record(
                "unknown_prop", c.get("id"), bad,
                f"{kind} does not accept it; passed through and it will be "
                f"rejected by a strict node")

        # A REQUIRED PROP THAT DID NOT SURVIVE, WHEREVER IT WAS LOST.
        #
        # Seven places above can drop a prop — a measured literal, an enum
        # whose pointer was row-relative, a pointer with no literal in the
        # sample model, a binding the binder could not resolve — and exactly
        # ONE of them consulted `_is_required` before dropping. The other six
        # removed required props and said nothing stronger than a warning, so
        # the component reached a validator missing something it cannot render
        # without, and the page was refused for a schema path.
        #
        # Asked once, at the end, about what actually survived: that is the
        # only place the answer is complete, and it needs no site to remember
        # to ask. Material — a component missing a required prop is a
        # component that cannot draw what the composer meant.
        for required in _required_props(kind):
            if required in props or required in _NODE_SIBLINGS:
                continue
            if required not in (c or {}):
                continue
            # THE SPECIFIC REASON WINS. A site that already said why this prop
            # went — "no groupable dimension", "the sample model has no
            # literal" — is more use to a composer than "it did not survive",
            # and reporting both puts the same loss in the summary twice.
            if any(e["where"] == str(c.get("id") or "page")
                   and e["what"] == required
                   for e in (getattr(binder, "losses", None) or Losses()).entries):
                continue
            binder._record(
                "dropped_required_prop", c.get("id"), required,
                f"{kind} requires it and the composer supplied it, but it "
                f"did not survive translation",
                material=True)

        # AFTER EVERY PROP IS ON. This walk ran above the `extra_props` merge,
        # so it inspected a dict that did not yet hold the props the binder
        # attaches — `Table.rowActions` among them, which is where three
        # invented ids shipped on one run while the check passed its own tests.
        # Correct helper, wrong position: it was looking for something that
        # arrived a few lines later.
        known_ids = {str(w.get("id")) if isinstance(w, dict) else str(w)
                     for w in (binder.registry.get("workflows") or [])}
        if known_ids:
            for where, bad in _dangling_workflows(props, known_ids):
                binder.unresolved.append(
                    f'{c.get("id")}: {where} targets workflow "{bad}", which '
                    f"this app does not define. Cleared for the "
                    f"submit-authority pass to resolve.")

        if kind == "Dialog" and c.get("id"):
            # A DIALOG IS NAMED BY ITS OWN `id` PROP. `opensDialog` on a
            # Button points at it, and `functional_completeness` resolves the
            # target against Dialog `props.id` — node ids are composition-time
            # and stripped before commit. A2UI names the dialog with the node
            # id and nothing else, so dropping that with the other node ids
            # left every dialog anonymous and every button opening nothing.
            props.setdefault("id", str(c["id"]))
        node: dict[str, Any] = {"type": kind, "props": props}
        # `style` is a sibling of `type` in NodeV2, alongside `id` and `bind` —
        # not a prop. A2UI emits it inside props, its own catalog accepts that,
        # and ours rejected the same tree:
        #
        #   InvalidPatternTemplate: root.children[0].props.(root):
        #   {'style': {'maxWidth': ...}} is not valid under any of the schemas
        #
        # Lifted here rather than widening NodeV2 to accept both placements:
        # two spellings of one thing in the Blueprint is the drift this whole
        # binder exists to close.
        style = props.pop("style", None)
        if style is not None:
            node["style"] = style
        # LIFTED, BECAUSE IT WAS ONLY EVER EXCUSED. `bind` is in
        # `_NODE_SIBLINGS`, which exists to say "this is not an unknown prop,
        # it is an early one" — and nothing moved it, so it stayed in `props`,
        # was never reported as unknown, and met a `.strict()` node as an
        # unrecognised key. The whole page parse failed with no warning naming
        # the cause.
        bound = props.pop("bind", None)
        if bound is not None:
            node["bind"] = bound
        # `visibleIf` is a sibling of `type` too, and the composer writes it
        # as the pointer path it binds fields from — `/note/id`, or `!/note/id`
        # for "no record". The renderer evaluates it with FEEL-lite in data
        # scope, so the pointer becomes the binding's path and the negation a
        # null test: `notes.id != null` / `notes.id = null`. A pointer that
        # resolves to no source is dropped, with the reason; the node then
        # always shows, which is the failure that is visible.
        cond = props.pop("visibleIf", None)
        if isinstance(cond, str) and cond.strip():
            raw_cond = cond.strip()
            negated = raw_cond.startswith("!")
            pointer = raw_cond.lstrip("!").strip()
            bound = pointer_binding(pointer, "visibleIf") if pointer else None
            if bound:
                path = bound.strip("{}").strip()
                node["visibleIf"] = f"{path} = null" if negated else f"{path} != null"
            else:
                # A CONDITION THAT BECAME NO CONDITION. The node then shows
                # ALWAYS — including the empty state the composer gated, so a
                # page can render "nothing here yet" over a populated table.
                # Material: the reader sees something the composer said to
                # hide.
                binder._record(
                    "dropped_prop", c.get("id"), "visibleIf",
                    f"{raw_cond!r} resolves to no source on this page, so "
                    f"this node is now always visible",
                    material=True)
        if c.get("id"):
            node["id"] = c["id"]

        kids: list[dict] = []
        raw = c.get("children")
        if isinstance(raw, list):
            kids = [n for n in (build(str(r), scope) for r in raw) if n]
        elif isinstance(raw, dict) and raw.get("componentId"):
            kids = expand_template(c, raw)
        elif isinstance(c.get("child"), str):
            n = build(c["child"], scope)
            if n:
                kids = [n]
        if kids:
            node["children"] = kids
        return node

    root = build("root")
    if root is None:
        # THE WHOLE COMPOSITION, GONE, SILENTLY. A payload whose top-level
        # component is not called "root" — or one whose root failed to build —
        # was replaced by an empty Stack here, and the page then went to the
        # floor, which refused it for having no table, no KPIs, no anything.
        # The reason it reported was a symptom; the cause was that nothing
        # had been translated at all, and no channel said so.
        losses.record("dropped_page", "page", "root",
                      "no component is reachable as `root`, so nothing the "
                      "composer wrote was translated"
                      + (f" (it emitted: {', '.join(sorted(str(c) for c in comps)[:8])})"
                         if comps else " (it emitted no components)"),
                      material=True)
        root = {"type": "Stack", "props": {}, "children": []}
    # Layout rules live in one module now, applied again post-generate over
    # whatever composed the page. Called here too so an A2UI schema is
    # already well-shaped when the floor judges it.
    root = shape_sections(root)

    # A DIALOG IS OPENED BY ID, NOT PLACED. The composer writes it as a second
    # top-level component — a surface root of its own, referenced by a
    # button's `opensDialog` and by nothing's `children` — and this built
    # only what `root` reaches, so the dialog vanished and the contract then
    # refused the page for opening a dialog it "does not contain". Measured
    # on two builds running: the detail page was composed correctly twice
    # and lost twice. The runtime mounts a Dialog wherever it sits in the
    # tree and shows it on `openDialog(id)`, so an unreached one is attached
    # under the root, after sectioning, which is layout and none of its.
    def _ids(n: Any) -> set[str]:
        out: set[str] = set()
        if isinstance(n, dict):
            if n.get("id"):
                out.add(str(n["id"]))
            for child in n.get("children") or []:
                out |= _ids(child)
        return out

    placed = _ids(root)
    for cid, c in list(comps.items()):
        if c.get("component") == "Dialog" and str(cid) not in placed:
            dialog = build(str(cid))
            if dialog:
                root.setdefault("children", []).append(dialog)
                placed |= _ids(dialog)

    # WHAT THE COMPOSER WROTE AND NOTHING PLACED. Only Dialogs were rescued
    # above; every other unreached component — a Table, a Chart, a whole Card
    # subtree — was dropped here with no record on any channel. A page that
    # lost its table is then refused for having no list surface, which is
    # true and is not the cause.
    #
    # Recorded rather than rescued: a component nothing references has no
    # position, and appending it somewhere would be this module inventing
    # layout. The composer is asked again instead, and told exactly what it
    # left unreferenced.
    # REFERENCED IS NOT THE SAME AS PLACED. A template is named once, by
    # `children: {componentId: "tile", path: "/kpis"}`, and expanded into
    # instances that carry none of its id — so `placed` never contains it and
    # a check keyed on placement calls every repeat template an orphan. The
    # question is whether the composer pointed at it from anywhere, in any of
    # the ways A2UI can point: a child id, a `componentId`, a nested spec.
    def _referenced(value: Any, out: set[str]) -> None:
        if isinstance(value, str):
            if value in comps:
                out.add(value)
        elif isinstance(value, dict):
            target = value.get("componentId")
            if isinstance(target, str):
                out.add(target)
            for v in value.values():
                _referenced(v, out)
        elif isinstance(value, list):
            for v in value:
                _referenced(v, out)

    referenced: set[str] = set()
    for cid, c in comps.items():
        for key, value in c.items():
            if key == "id":
                continue
            _referenced(value, referenced)

    for cid, c in list(comps.items()):
        if (str(cid) in placed or str(cid) in referenced
                or c.get("component") == "Dialog" or str(cid) == "root"):
            continue
        losses.record(
            "orphaned_component", str(cid), str(c.get("component") or "?"),
            "written by the composer and pointed at from nowhere — no parent "
            "lists it as a child and no template names it, so it has no place "
            "on the page",
            material=True)

    # ONE SEARCH PER LIST. A data-bound Table renders its own search toolbar,
    # and a composer that also places a FilterBar above it hands the page two
    # search boxes for one list — the duplication that reads as a broken,
    # low-density layout (measured on the Master Data page: a FilterBar search
    # over a Records table that already searched). When both are present the
    # FilterBar keeps its filter chips (they drive the query) and drops its
    # search; the Table's search stays. A Table whose own search is off leaves
    # the FilterBar's alone, so a page with no other search still has one.
    def _walk_nodes(n: Any):
        if isinstance(n, dict):
            yield n
            for ch in n.get("children") or []:
                yield from _walk_nodes(ch)

    _table_searches = any(
        (t.get("props") or {}).get("searchable") is not False
        and any((t.get("props") or {}).get(p) for p in ("data", "rows"))
        for t in _walk_nodes(root) if t.get("type") == "Table")
    if _table_searches:
        for n in _walk_nodes(root):
            if n.get("type") == "FilterBar":
                if (n.get("props") or {}).get("showSearch") is not False:
                    losses.record(
                        "overwritten", str(n.get("id") or "FilterBar"),
                        "showSearch",
                        "the table on this page searches its own rows, so the "
                        "second search box was switched off")
                n.setdefault("props", {})["showSearch"] = False

    _translate_option_sources(root, binder, registry)
    schema: dict[str, Any] = {
        "schemaVersion": "2",
        "id": page_id,
        "route": route,
        "layout": "main",
        "root": root,
    }
    # Always present, even when empty. A key that appears only sometimes makes
    # every consumer write `doc.get("dataSources") or []` and makes "this page
    # binds nothing" indistinguishable from "this page predates the field".
    schema["dataSources"] = binder.sources

    # A LITERAL BINDING THAT NAMES A REAL TABLE IS A REQUEST FOR THAT TABLE.
    #
    # A2UI can express a data reference two ways: as a pointer into the data
    # model, which this binder walks and mints a source for, or as a literal
    # `{{name}}` written straight into a prop, which it passes through
    # untouched. Only the first declared a source, so a composition that named
    # the right table the second way was refused for binding data the page
    # "will never fetch".
    #
    # Measured on the legislative platform: 14 of 50 routes went unbuilt, and
    # EVERY name in the rejections — audit_logs, blocs, document_signatures,
    # recordings, attendance_records, votes — is a real table in that
    # application's own schema. The composer was right and the binder had no
    # opinion. `/` was among the fourteen, so the app opened on a 404.
    #
    # So a dangling name that matches an entity's table or slug gets the same
    # source the pointer path would have minted. A name matching nothing is
    # still dangling and still refused: this completes the binder, it does not
    # loosen the check.
    _adopt_table_bindings(schema, binder, registry)

    return {
        "schema": schema,
        "dominant_entity": binder.dominant,
        "assumptions": binder.assumptions,
        "unresolved": binder.unresolved,
        # Bindings with no source behind them: the composition names data the
        # page will never fetch.
        "dangling": dangling_bindings(schema),
        # What a resolver could still answer — every place the binder had to
        # guess an entity, in a shape the next pass can act on. Empty when
        # every binding resolved on its own.
        "questions": binder.questions,
        "warnings": binder.warnings,
        # EVERYTHING THIS TRANSLATION TOOK AWAY, in one structured channel the
        # caller actually reads. The five above are kept because tests and
        # logs use them; this is the one that changes what happens, because a
        # material loss refuses the page instead of shipping the remains.
        "losses": list(losses.entries),
        "material_losses": losses.material(),
        "dropped_data_model_keys": sorted(data_model),
    }

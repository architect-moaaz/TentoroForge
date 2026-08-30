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

# Last-resort prop reconciliation.
#
# The catalog is only as truthful as `library_manifest.key_props`, and that list
# is empty for some components — Text among them. Given no properties to work
# from the composer invents plausible ones ("text", "variant"), which then fail
# Forge's strict schema node ({content, as}). That is the very drift A2UI's
# closed catalog is supposed to prevent, reappearing one layer up.
#
# These aliases are a stopgap, not the fix. The fix is to make the catalog
# generator fall back to the schema node when the manifest has no key_props, so
# the contract is complete at authoring time instead of patched at translation
# time. Every entry here marks a component whose manifest entry is thin.
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
            if any(syn in want for syn in _ENUM_LABEL_SYNONYMS.get(v, ())):
                return {col["name"]: value}
    return None


class _Binder:
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
            self.warnings.append(
                f'{comp.get("id")}.{prop}: could not resolve "{path}" to an entity '
                f"(label {label!r}). Left unbound rather than guessed."
            )
            return None

        self.entity_of[str(comp.get("id"))] = entity
        slug = _slug_for(entity, self.registry)
        kind = comp.get("component")

        if kind == "MetricTile" or prop == "value":
            filt = _enum_filter(label, entity, self.registry)
            base = _slugify(label) or f"{slug}Count"
            name = self._unique(base)
            # The filter belongs INSIDE the metric. `AggregateSource` has no
            # source-level `filter` field, so putting it there is silently
            # dropped and every KPI reports the unfiltered total — which is how
            # "In Progress" first rendered 10 against 3 real rows.
            metric: dict[str, Any] = {"fn": "count"}
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
                # derives them from the grouped result.
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
                self.unresolved.append({
                    "component": str(comp.get("id") or ""), "prop": prop,
                    "path": path, "label": label,
                    "reason": (f"{entity} has no groupable dimension (no enum, "
                               f"and every other column is a key, free text or "
                               f"an ungroupable type) — a chart here could only "
                               f"be grouped by a uuid"),
                })
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
            name = self._unique(slug)
            self.sources.append({"name": name, "entity": entity, "op": "list", "limit": 10})
            binding = f"{{{{{name}}}}}"

        self._by_path[key] = binding
        return binding

    def is_record_page(self) -> bool:
        """Whether this page is about one record.

        `_family_of` rather than `page_family` directly: page_family knows
        nothing about `record_workspace` and answers None, and the authority's
        map is the one covering every declared kind.
        """
        try:
            from services.a2ui_authority import _family_of
            return _family_of(getattr(self, "page_kind", "")) == "record"
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
        name = self._unique(_slug_for(entity, self.registry))
        self.sources.append({"name": name, "entity": entity, "op": "get"})
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

        slug = _slug_for(entity, self.registry)
        name = self._unique(_slugify(label) or f"{slug}Measure")
        metric: dict[str, Any] = {"fn": "ratio" if pct else "count"}
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
            return node_type, props
        # `_decide` returns None for foreign keys and for anything it has no
        # opinion about — the composer's own choice stands there.
        return str(comp.get("component")), props

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


#: Fields that sit beside `props` in NodeV2 rather than inside it. A2UI emits
#: them among the props and the binder lifts them out afterwards, so they are
#: not unknown — they are early.
_NODE_SIBLINGS = frozenset({"style", "bind", "visibleIf", "id"})


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
    except Exception:  # noqa: BLE001 — never fail a translation over a lookup
        return []
    if not known:
        return []
    return sorted(k for k in props if k not in known and k not in _NODE_SIBLINGS)


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
    found: set[str] = set()

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

    def walk(node: Any, in_row: bool = False) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n, in_row)
            return
        if not isinstance(node, dict):
            return
        # The collection binding itself is page-level — it is what opens the
        # row scope — so the node is judged before the scope is entered.
        row = in_row or _row_scope(node)
        for value in node.values():
            if isinstance(value, str):
                # `{{plants}}` and `{{record.title}}` both name `plants`/`record`.
                names = [m.split(".")[0].strip()
                         for m in re.findall(r"\{\{([^}]+)\}\}", value)]
                # Within a row, only a name the page actually declares is a
                # page binding; anything else is a field of the row.
                found.update(n for n in names if not row or n in declared)
            else:
                walk(value, row)

    walk(schema.get("root"))
    return sorted(n for n in found if n and n not in declared)


def translate(payload: dict, registry: dict, route: str = "/",
              page_id: str = "home", kind: str = "",
              entity_hints: dict | None = None) -> dict:
    """A2UI surface → Forge page schema. Returns {schema, warnings, dropped}."""
    comps: dict[str, dict] = {}
    data_model: dict = {}
    for msg in payload.get("messages", []) or []:
        for c in (msg.get("updateComponents") or {}).get("components", []) or []:
            comps[c.get("id")] = c
        if "updateDataModel" in msg:
            data_model = msg["updateDataModel"].get("value") or {}

    binder = _Binder(registry, data_model)
    binder.page_kind = str(kind or "").strip().lower()
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
                    clone[k] = item.get(rel)
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
                if not resolved:
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
                    resolved = at_path(raw)
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
                resolved = _ENUM_SYNONYMS.get(k, {}).get(resolved, resolved)
            if resolved is not None:
                props[aliases.get(k, k)] = resolved
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
            props.setdefault(req, default)
        props.update(binder.extra_props.get(str(c.get("id")), {}))

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

    root = build("root") or {"type": "Stack", "props": {}, "children": []}
    # Layout rules live in one module now, applied again post-generate over
    # whatever composed the page. Called here too so an A2UI schema is
    # already well-shaped when the floor judges it.
    root = shape_sections(root)

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
        "dropped_data_model_keys": sorted(data_model),
    }

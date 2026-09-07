"""Page planner — a pattern template plus a Page Contract, made a page schema.

§33 gives us a Page Contract: intent. The engine renders a node tree. Between
them sat the platform's most expensive habit — asking a model to compose every
page. That cost scaled with page count, produced structurally different results
for pages of the same kind, and forced the component library to loosen its own
prop schemas to absorb the misses. The library still carries the receipts::

    // ``columns`` is often null in generated schemas …
    // The LLM consistently emits ``rows``/``data`` on list tables; without
    // this they were stripped by the strict schema → empty "No rows found"

So the split is: A2UI authors *structure*, once per pattern the app uses (§34),
and this module instantiates that structure per page with no model call at all.
That makes it a service node like ``apis`` — §116's rule that whatever is
derivable belongs to deterministic code.

What falls out of it:

* **Consistency is structural.** Every ``entity_list`` page in an app is the
  same template, so two list pages cannot drift apart.
* **The app-specific component disappears.** ``role-form`` was never a
  component — it is ``Form`` carrying ENTITY-002's fields, and a planner can
  work that out. Same for ``pipeline-board`` (``Kanban`` grouped by stage) and
  ``cv-panel`` (``Card`` over a ``DescriptionList``). Nobody authors them, so
  they cannot drift from the entity they describe.
* **Failure is loud.** An unresolved ``$placeholder`` raises rather than
  reaching the renderer as a literal string.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from services.metric_dialect import normalize_sources

#: Emitted by ``npm run emit:catalog --workspace=packages/library``.
CATALOG_PATH = Path(__file__).resolve().parents[2] / "contracts" / "component-catalog.json"

#: Field names that read as a record's title, best first.
TITLE_HINTS = ("name", "title", "label", "subject", "summary")

#: Blueprint field type -> Form field ``kind`` (see Form.schema.ts).
FORM_KINDS: dict[str, str] = {
    "text": "text", "string": "text", "str": "text",
    "email": "email",
    "url": "text",
    "int": "number", "integer": "number", "number": "number",
    "decimal": "number", "numeric": "number", "float": "number",
    "money": "number", "currency": "number",
    "bool": "checkbox", "boolean": "checkbox",
    "date": "date", "datetime": "date", "timestamp": "date",
    "enum": "select",
    "json": "object", "jsonb": "object", "object": "object",
}

#: Fields no user edits and no list shows by default.
INTERNAL_FIELDS = frozenset({"id", "createdAt", "updatedAt", "deletedAt"})

#: The dataSource name a template binds the primary collection / record to.
ROWS = "rows"
RECORD = "record"

#: The namespace `page_widgets` binds every KPI tile into: `{{metrics.<key>}}`.
METRICS = "metrics"

#: Binding roots that are NOT data sources and must never be reported as
#: dangling. The renderer supplies each of these from somewhere other than a
#: page fetch — the signed-in actor, the route, the form being edited, the
#: current repeat item. A `$`-prefixed placeholder never reaches here at all:
#: `_bindings_used` only matches roots starting `[A-Za-z_]`.
SCOPE_ROOTS = frozenset({
    "user", "actor", "session", "route", "params", "param", "query",
    "search", "form", "state", "theme", "now", "today",
    "item", "row", "index", "i",
})


class PlanError(RuntimeError):
    """A template could not be instantiated for a page. Never swallowed."""


def load_catalog(path: str | Path = CATALOG_PATH) -> dict[str, dict]:
    """The component catalog, keyed by component name."""
    data = json.loads(Path(path).read_text("utf-8"))
    return {c["name"]: c for c in data["components"]}


def _humanise(name: str) -> str:
    """``createdAt`` -> ``Created At``. Column and field labels."""
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", (name or "").strip())
    spaced = re.sub(r"[_\-]+", " ", spaced)
    return " ".join(w[:1].upper() + w[1:] for w in spaced.split())


def _plural(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return ""
    if n.endswith("y") and not n.endswith(("ay", "ey", "iy", "oy", "uy")):
        return n[:-1] + "ies"
    if n.endswith(("s", "x", "z", "ch", "sh")):
        return n + "es"
    return n + "s"


def _live(items: Any) -> list[dict]:
    return [i for i in (items or []) if i.get("status") != "DEPRECATED"]


def _entities(doc: dict) -> dict[str, dict]:
    return {e.get("id"): e for e in _live((doc.get("data") or {}).get("entities"))}


def _visible_fields(entity: dict) -> list[dict]:
    return [f for f in (entity.get("fields") or [])
            if f.get("name") not in INTERNAL_FIELDS]


# ---------------------------------------------------------------------------
# Field-role derivation — what "the title" or "the columns" mean for an entity
# ---------------------------------------------------------------------------

def title_field(entity: dict) -> str | None:
    """The field that names a record.

    Hint-matched first so ``Candidate.fullName`` wins over whatever happens to
    be declared first; otherwise the first non-internal text field.
    """
    fields = _visible_fields(entity)
    for hint in TITLE_HINTS:
        for f in fields:
            if (f.get("name") or "").lower() == hint:
                return f.get("name")
    for hint in TITLE_HINTS:
        for f in fields:
            if hint in (f.get("name") or "").lower():
                return f.get("name")
    for f in fields:
        if str(f.get("type") or "").lower() in ("text", "string", "str"):
            return f.get("name")
    return fields[0].get("name") if fields else None


def subtitle_field(entity: dict) -> str | None:
    """A second identifying field, skipping the one already used as title."""
    title = title_field(entity)
    for f in _visible_fields(entity):
        name = f.get("name")
        if name != title and str(f.get("type") or "").lower() in (
            "text", "string", "str", "enum", "email"
        ):
            return name
    return None


def summary_fields(entity: dict, limit: int = 6) -> list[dict]:
    """``[{term, description}]`` — the canonical DescriptionList pair.

    Emitted in the shape the component actually wants, not the one it has
    learned to repair. `DescriptionList.schema.ts` accepts `{label, value}` too
    — "the more common shape LLM-authored schemas tend to emit" — and the
    component normalises it at render. That is a loosened schema plus a repair
    pass, added because generated output kept arriving wrong; producing the
    canonical shape is what makes both unnecessary rather than load-bearing.

    It also matters for correctness, not just tidiness: the strict node shape
    in `page.ts` only knows `{term, description}`, so the repaired shape
    rendered fine and failed validation, which is how six pages came to be
    silently non-conforming.
    """
    title = title_field(entity)
    out: list[dict] = []
    for f in _visible_fields(entity):
        name = f.get("name")
        if name == title:
            continue
        out.append({"term": _humanise(name),
                    "description": f"{{{{{RECORD}.{name}}}}}"})
        if len(out) >= limit:
            break
    return out


def columns_for(entity: dict, limit: int = 7) -> list[dict]:
    """ColumnDef list for Table / TableSortable.

    Emitted as real column definitions rather than left null — the library's
    ``ColumnDef`` preprocessor exists precisely because generated schemas kept
    arriving without them and rendered uppercased keys as headers.
    """
    title = title_field(entity)
    fields = _visible_fields(entity)
    ordered = ([f for f in fields if f.get("name") == title]
               + [f for f in fields if f.get("name") != title])
    cols: list[dict] = []
    for f in ordered[:limit]:
        numeric = str(f.get("type") or "").lower() in (
            "int", "integer", "number", "decimal", "numeric", "float",
            "money", "currency",
        )
        col: dict[str, Any] = {
            "key": f.get("name"),
            "label": _humanise(f.get("name")),
            "sortable": True,
        }
        if numeric:
            col["align"] = "right"
        cols.append(col)
    return cols


#: Fields a person never fills in on a create form. A record's own lifecycle
#: state and the timestamps the system stamps are outcomes of using the app,
#: not questions to answer before it exists.
DERIVED_ON_CREATE = ("createdat", "updatedat", "savedat", "readat",
                     "completedat", "deletedat", "archivedat")


def _asked_of_a_person(field: dict, *, creating: bool) -> bool:
    """Whether a create form should ask for this field.

    A generated reading list offered `Is Read`, `Takeaway`, `Read At` and
    `Saved At` on its *new article* page — while the page's own description
    said an article "starts unread with no takeaway". The template emitted
    every entity field indiscriminately, so a form for something that does not
    exist yet asked about what happens to it later.
    """
    if not creating:
        return True
    name = str(field.get("name") or "").lower()
    if name.endswith("at") and name in DERIVED_ON_CREATE:
        return False
    # A boolean lifecycle flag defaults false on a new record; asking inverts
    # the meaning of the form.
    return not (str(field.get("type") or "").lower() == "boolean"
                and name.startswith("is"))


def enum_values(field: dict) -> list[str]:
    """The values this field is allowed to hold, as the contract spells them.

    The contract's name is ``enumValues`` and its field object is
    ``additionalProperties: false``, so ``values`` and ``enum`` — which two
    readers here were looking for — cannot appear on a valid Blueprint at all.
    Both branches were dead: a status field seeded as "Status 1" rather than
    as one of its own states, and every select in every generated form
    degraded to a free-text box because it found no options.

    The other two spellings are still accepted. This is also called with
    field-shaped dicts that did not come from the Blueprint, and one name for
    one thing is worth more than being strict about the two nobody writes.
    """
    for key in ("enumValues", "values", "enum"):
        got = field.get(key)
        if isinstance(got, (list, tuple)) and got:
            return [str(v) for v in got]
    return []


def form_fields_for(entity: dict, *, creating: bool = False) -> list[dict]:
    """Form ``fields`` — this is what an app-specific ``*-form`` component was."""
    out: list[dict] = []
    for f in _visible_fields(entity):
        if not _asked_of_a_person(f, creating=creating):
            continue
        kind = FORM_KINDS.get(str(f.get("type") or "").lower(), "text")
        field: dict[str, Any] = {
            "kind": kind,
            "name": f.get("name"),
            "label": _humanise(f.get("name")),
        }
        # A boolean control always has a value, so `required` says nothing —
        # and the Form contract's checkbox/switch branches do not accept it.
        if f.get("required") and kind not in ("checkbox", "switch"):
            field["required"] = True
        if kind == "select":
            field["options"] = [
                {"value": str(v), "label": _humanise(str(v))}
                for v in enum_values(f)
            ]
            # A select with no options cannot be filled; degrade to text rather
            # than emit a dead control.
            if not field["options"]:
                field["kind"] = "text"
                field.pop("options")
        out.append(field)
    return out


# ---------------------------------------------------------------------------
# Repeat sources — the lists a template may iterate
# ---------------------------------------------------------------------------

#: Verbs that change something. Everything else a page lists as an "action" is
#: an affordance the component already provides — filtering, sorting, opening a
#: row — and does not deserve a button of its own.
MUTATING_VERBS = ("create", "add", "new", "edit", "update", "delete", "remove",
                  "archive", "close", "approve", "reject", "submit", "assign",
                  "invite", "cancel", "schedule", "move", "attach", "export")


def is_mutating_action(action: str) -> bool:
    return (str(action).split("_", 1)[0] or "").lower() in MUTATING_VERBS


def _action_label(action: str) -> str:
    return _humanise(str(action).replace("_", " "))


def related_collections(doc: dict, entity_id: str) -> list[dict]:
    """Entities that point *at* this one — a record's child collections.

    This is the reason relationships had to become writable. Without them a
    record workspace has no way to know that applications belong to a role, and
    the tabs it should show are guesswork.
    """
    entities = _entities(doc)
    out: list[dict] = []
    for rel in _live((doc.get("data") or {}).get("relationships")):
        if rel.get("to") != entity_id:
            continue
        child = entities.get(rel.get("from"))
        if not child:
            continue
        name = child.get("name") or ""
        out.append({
            "id": child.get("id"),
            "label": _plural(_humanise(name)),
            "entity": child.get("id"),
            "value": f"{{{{{_lower_first(name)}}}}}",
            # A tab per related collection almost always contains a table of
            # that collection, and its columns come from the *child* entity,
            # not the page's own. Without this the template has no way to say
            # so and falls back to hard-coding.
            "columns": columns_for(child),
        })
    return out


def _lower_first(name: str) -> str:
    return (name[:1].lower() + name[1:]) if name else name


def page_widgets(doc: dict, page_id: str) -> list[dict]:
    """Widgets bound to this page, already carrying an executable data source."""
    out: list[dict] = []
    for w in _live(doc.get("widgets")):
        if w.get("page") != page_id:
            continue
        out.append({
            "id": w.get("id"),
            "label": w.get("label") or "",
            "value": f"{{{{metrics.{_metric_key(w)}}}}}",
            "kind": w.get("kind") or "metric",
        })
    return out


def _metric_key(widget: dict) -> str:
    src = widget.get("dataSource") or {}
    parts = [str(src.get("op") or "value"), str(src.get("aggregation") or "")]
    label = re.sub(r"[^a-zA-Z0-9]+", "_", (widget.get("label") or "")).strip("_")
    return "_".join(p for p in parts + [label.lower()] if p)


def _is_equality_value(v: Any) -> bool:
    """True when `v` is a scalar the runtime can compare with `eq`."""
    if isinstance(v, bool) or isinstance(v, (int, float)):
        return True
    return isinstance(v, str) and bool(v) and v[0] not in "<>!=~"


def widget_metrics(doc: dict, page_id: str) -> dict[str, dict]:
    """The `metrics` map for the aggregate source `{{metrics.<key>}}` binds to.

    `page_widgets` has always emitted `{{metrics.<key>}}`, and the source that
    was supposed to satisfy it was emitted as a bare
    ``{"name": "metrics", "entity": …, "op": "aggregate"}`` with NO `metrics`
    map at all. `resolveAggregate` iterates `source.metrics` — an empty map
    yields an empty object, so every one of those tiles resolved to `undefined`
    and rendered blank. The binding named a declared source, so no validator
    caught it.

    Each metric is derived from the widget's OWN Blueprint dataSource, never
    from its prose label: `aggregation` when the widget declares one, else a
    row count, which is the only thing that is true of any entity. An
    equality-shaped `filter` is carried through so "Low Stock Items" counts the
    rows it says it counts rather than all of them.
    """
    out: dict[str, dict] = {}
    for w in _live(doc.get("widgets")):
        if w.get("page") != page_id:
            continue
        src = w.get("dataSource") if isinstance(w.get("dataSource"), dict) else {}
        agg = str(src.get("aggregation") or "").strip().lower()
        field = src.get("field") or src.get("aggregateField")
        metric: dict[str, Any] = {"fn": "count"}
        # sum/avg/min/max over a column the widget actually names. Without a
        # field the runtime returns 0 by its own rule, so a count is the honest
        # answer instead.
        if agg in {"sum", "avg", "min", "max"} and isinstance(field, str) and field:
            metric = {"fn": agg, "field": field}
        # Only a plain equality filter. The runtime compiles `filter` to
        # `eq(col, value)`, so carrying a comparison the Blueprint wrote as
        # prose — `{"quantity": "<5"}` — would compare the column to the
        # literal string "<5", match no rows, and report a confident 0.
        flt = src.get("filter")
        if isinstance(flt, dict) and flt and all(
                _is_equality_value(v) for v in flt.values()):
            metric["filter"] = dict(flt)
        out[_metric_key(w)] = metric
    return out


def repeat_items(doc: dict, page: dict, entity: dict | None, over: str) -> list[dict]:
    """The list a ``repeat`` iterates. Every branch returns ``$item`` dicts."""
    if over in ("actions", "primaryActions"):
        actions = page.get("actions") or []
        if over == "primaryActions":
            actions = [a for a in actions if is_mutating_action(a)]
        return [{"id": a, "label": _action_label(a), "value": a} for a in actions]
    if over == "widgets":
        return page_widgets(doc, page.get("id"))
    if over == "relatedCollections":
        return related_collections(doc, entity.get("id")) if entity else []
    if over == "columns":
        return ([{"id": c["key"], "label": c["label"], "value": c["key"]}
                 for c in columns_for(entity)] if entity else [])
    if over == "formFields":
        return ([{"id": f["name"], "label": f["label"], "value": f["name"]}
                 for f in form_fields_for(entity)] if entity else [])
    if over == "views":
        return [{"id": v.get("key"), "label": v.get("label"),
                 "value": v.get("key")}
                for v in (page.get("views") or [])]
    if over == "states":
        # `states` is an array of state names — see PageContract.states, which
        # is z.array(z.enum([...])). This read it as a mapping and crashed the
        # whole frontend projection with `'list' object has no attribute
        # 'items'` the first time a pattern template repeated over it, taking
        # five nodes down with it. Nothing caught it because no template had
        # repeated over states before.
        return [{"id": name, "label": _humanise(name), "value": name}
                for name in (page.get("states") or []) if name]
    raise PlanError(f"unknown repeat source {over!r}")


# ---------------------------------------------------------------------------
# Placeholder resolution
# ---------------------------------------------------------------------------

def build_context(doc: dict, page: dict, entity: dict | None) -> dict[str, Any]:
    """The closed placeholder vocabulary, bound for one page."""
    ctx: dict[str, Any] = {
        "$page.name": page.get("name") or "",
        "$page.purpose": page.get("purpose") or "",
    }
    if entity:
        name = entity.get("name") or ""
        ctx.update({
            "$entity.name": _humanise(name),
            "$entity.plural": _plural(_humanise(name)),
            "$titleField": f"{{{{{RECORD}.{title_field(entity)}}}}}",
            "$subtitleField": (f"{{{{{RECORD}.{subtitle_field(entity)}}}}}"
                               if subtitle_field(entity) else ""),
            "$summaryFields": summary_fields(entity),
            # A create route asks a person for a new record; a detail route
            # edits one that exists and may legitimately show its lifecycle.
            "$formFields": form_fields_for(
                entity, creating=str(page.get("route") or "").endswith("/new")),
            "$columns": columns_for(entity),
            # The saved views this page declares, in the shape
            # `FilterBar.savedViews` and `SavedViewsPicker.views` take. Without
            # this the contract could describe a view and nothing would render
            # it, which is how five filtered variants became five routes.
            "$savedViews": [
                {"id": v.get("key"), "label": v.get("label"),
                 "filters": v.get("filter") or {}}
                for v in (page.get("views") or [])
            ],
        })
    return ctx


#: A placeholder mistakenly wrapped in the engine's binding braces.
_WRAPPED_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\$[A-Za-z][A-Za-z0-9_.]*)\s*\}\}")

#: Matches a placeholder wherever it appears in a string.
_PLACEHOLDER_RE = re.compile(r"\$[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?")


def resolve(value: Any, ctx: dict[str, Any]) -> Any:
    """Substitute placeholders inside a prop value, at any depth.

    A placeholder standing alone becomes whatever it resolves to, list or
    string alike. One embedded in a sentence is interpolated:
    ``"$entity.name details"`` -> ``"Job Role details"``. Requiring the bare
    form was an arbitrary restriction, and A2UI ran into it immediately —
    nine record-workspace pages failed on a heading that read naturally.

    List-valued placeholders (``$columns``, ``$summaryFields``) can only stand
    alone; splicing a list into a sentence has no meaning, so it is an error
    rather than a stringified array.

    ``{{…}}`` bindings are the engine's own runtime interpolation and are left
    exactly as authored — only ``$`` placeholders belong to the planner.
    """
    if isinstance(value, str):
        if "$" not in value:
            return value
        # A placeholder wrapped in binding braces — `{{$columns}}`. Two
        # interpolation syntaxes sit side by side here and conflating them is
        # the obvious mistake; it is also unambiguous, because an engine
        # binding names a data key and never starts with `$`. Normalise rather
        # than reject.
        wrapped = _WRAPPED_PLACEHOLDER_RE.fullmatch(value.strip())
        if wrapped:
            value = wrapped.group(1)
        if value in ctx:
            return ctx[value]

        found = _PLACEHOLDER_RE.findall(value)
        if not found:
            return value
        unknown = [f for f in found if f not in ctx]
        if unknown:
            raise PlanError(
                f"unresolved placeholder {unknown[0]!r} — not in the closed "
                f"vocabulary"
            )
        out = value
        for name in sorted(set(found), key=len, reverse=True):
            replacement = ctx[name]
            if not isinstance(replacement, (str, int, float)):
                raise PlanError(
                    f"{name!r} is a list and cannot be interpolated into "
                    f"{value!r}; use it as the whole value"
                )
            out = out.replace(name, str(replacement))
        return out
    if isinstance(value, dict):
        return {k: resolve(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, ctx) for v in value]
    return value


def instantiate(node: dict, ctx: dict[str, Any], doc: dict, page: dict,
                entity: dict | None,
                catalog: dict[str, dict] | None = None) -> list[dict]:
    """One template node -> zero or more page-schema nodes.

    Returns a list because ``repeat`` fans a subtree out over a derived list;
    an ordinary node returns exactly one.
    """
    rep = node.get("repeat")
    if rep:
        items = repeat_items(doc, page, entity, rep)
        out: list[dict] = []
        for item in items:
            scoped = dict(ctx)
            scoped.update({
                "$item.id": item.get("id"),
                "$item.label": item.get("label"),
                "$item.value": item.get("value"),
            })
            if item.get("columns") is not None:
                scoped["$item.columns"] = item["columns"]
            bare = {k: v for k, v in node.items() if k != "repeat"}
            out.extend(instantiate(bare, scoped, doc, page, entity, catalog))
        return out

    built: dict[str, Any] = {"type": node["type"]}
    if node.get("id"):
        built["id"] = node["id"]
    props = resolve(node.get("props") or {}, ctx)
    # A binding carries one concept; each prop takes the shape it declares.
    entry = (catalog or {}).get(node["type"]) or {}
    declared = ((entry.get("props") or {}).get("properties") or {})
    props = {k: narrow_to_prop(v, declared.get(k) or {}) for k, v in props.items()}
    if props:
        built["props"] = props
    children: list[dict] = []
    for child in node.get("children") or []:
        children.extend(instantiate(child, ctx, doc, page, entity, catalog))
    if children:
        built["children"] = children
    if node.get("visibleIf"):
        built["visibleIf"] = node["visibleIf"]
    return [built]


# ---------------------------------------------------------------------------
# Validation — against the real registry, before anything renders
# ---------------------------------------------------------------------------

#: Node types the engine dispatches directly instead of resolving through the
#: component registry — RESERVED_V2 in packages/schema/src/page.ts. They are
#: legal nodes with no catalog entry.
STRUCTURAL_NODES = frozenset({
    "Stack", "Row", "Grid", "Container", "Spacer",
    "Box", "Text", "Image",
    "Repeat", "Conditional", "DataBoundary", "Slot",
})


def validate_template(template: dict, catalog: dict[str, dict]) -> list[str]:
    """Structural errors in a template. Empty list means it can be planned.

    Checked against the emitted catalog, so this is the actual registry rather
    than a model's recollection of it. A2UI output that fails here is rejected
    and re-asked — the schemas are never loosened to accept it.
    """
    errors: list[str] = []

    def walk(node: dict, path: str) -> None:
        kind = node.get("type")
        entry = catalog.get(kind)

        # Two questions, and one variable used to answer both. Is this a legal
        # node? — which decides whether its subtree is worth walking. And do I
        # have a contract for it? — which decides whether the child rules below
        # apply. `entry is None` answered the first with the second, so a
        # `Repeat` was called unregistered and its subtree went unchecked;
        # NodeV2 declares Repeat at page.ts:332 and the renderer dispatches it.
        if entry is None and kind not in STRUCTURAL_NODES:
            # An unknown type makes its children meaningless — nothing below it
            # can be judged against a contract that does not exist.
            errors.append(f"{path}: '{kind}' is not a registered component")
            return

        children = node.get("children") or []
        contract = entry.get("childContract") if entry else None
        if entry and children and not entry["acceptsChildren"]:
            errors.append(f"{path}: '{kind}' takes no children, got {len(children)}")
        if contract and not node.get("repeat"):
            if contract["kind"] == "roles":
                roles = contract["roles"]
                if len(children) != len(roles):
                    errors.append(
                        f"{path}: '{kind}' needs exactly {len(roles)} children "
                        f"({', '.join(roles)}), got {len(children)}"
                    )
            elif contract["kind"] == "repeat":
                paired = contract.get("pairedWith")
                declared = (node.get("props") or {}).get(paired)
                if paired and isinstance(declared, list) and len(declared) != len(children):
                    errors.append(
                        f"{path}: '{kind}' has {len(children)} children but "
                        f"{len(declared)} entries in props.{paired}"
                    )
        for i, child in enumerate(children):
            walk(child, f"{path}.children[{i}]")

    root = template.get("root")
    if not isinstance(root, dict):
        return ["root: missing"]
    walk(root, "root")
    return errors


def narrow_to_prop(value: Any, spec: dict) -> Any:
    """Trim a resolved binding to the keys the receiving prop declares.

    One concept, two contracts: a page's saved views feed `FilterBar.savedViews`
    as {id, label, filters} — where `filters` is required — and
    `SavedViewsPicker.views` as {id, label, isDefault}, where `filters` is
    rejected outright. A single `$savedViews` binding cannot satisfy both, and
    emitting the union failed the stricter one: every collection page in a
    generated app died on "Additional properties are not allowed ('filters'
    was unexpected)" and was dropped before it reached disk.

    The planner knows which prop it is filling and the catalog declares that
    prop's shape, so the binding carries everything and each prop takes what it
    accepts. Naming two placeholders instead would make A2UI pick correctly
    between them, which is a thing to get wrong rather than a thing to derive.
    """
    items = (spec or {}).get("items") or {}
    allowed = set((items.get("properties") or {}))
    if not allowed or items.get("additionalProperties") is not False:
        return value
    if not isinstance(value, list):
        return value
    return [
        {k: v for k, v in item.items() if k in allowed}
        if isinstance(item, dict) else item
        for item in value
    ]


def validate_props(schema: dict, catalog: dict[str, dict]) -> list[str]:
    """Prop errors in an instantiated page, against each component's own schema."""
    from jsonschema import Draft7Validator

    errors: list[str] = []

    def walk(node: dict, path: str) -> None:
        entry = catalog.get(node.get("type"))
        if entry:
            props = node.get("props") or {}
            # Binding strings ("{{rows}}") stand in for values the renderer
            # supplies later, so they cannot be type-checked here. They must
            # still count as *present*, though — dropping a bound `value` and
            # then enforcing `required` reports every data-driven MetricTile as
            # missing the very prop it was given.
            bound = {k for k, v in props.items()
                     if isinstance(v, str) and "{{" in v}
            # `className` IS A RENDERER PASSTHROUGH, NOT A COMPONENT PROP.
            # `packages/library/src/registry.ts` lifts it out of the props and
            # forwards it to the element deliberately:
            #
            #     if (typeof inputProps.className === "string") {
            #       passthrough.className = inputProps.className;
            #     }
            #     delete inputProps.className;
            #
            # The catalog declares `additionalProperties: false` with, for
            # Container, a single `maxWidth` — so the contract forbade what the
            # renderer explicitly supports, and every Figma-derived page was
            # refused for carrying the Tailwind that IS its fidelity. Excluded
            # for the same reason bindings are: the value is real, and this is
            # not the thing that can judge it.
            # `style` joins it for the same reason and by the same route —
            # `registry.ts` lifts both out of the props and forwards them to
            # the element, so neither is a component prop this can judge.
            _PASSTHROUGH = {"className", "style"}
            checkable = {k: v for k, v in props.items()
                         if k not in bound and k not in _PASSTHROUGH}
            schema = entry["props"]
            if bound and isinstance(schema.get("required"), list):
                schema = dict(schema)
                schema["required"] = [r for r in schema["required"] if r not in bound]
            for err in Draft7Validator(schema).iter_errors(checkable):
                # Two kinds of value are supplied later and cannot be type
                # checked now.
                #
                # A binding can sit anywhere, not only at the top of a prop:
                # `ValidationChecklist.items[0].valid` is legitimately
                # "{{form.values.title}}", a boolean the renderer resolves at
                # run time.
                #
                # A placeholder is the same story one stage earlier. Validating
                # an *un-instantiated* tree sees `$summaryFields` as the string
                # it currently is rather than the array it becomes, so the gate
                # rejected a page for using the placeholder vocabulary exactly
                # as intended — and the retry, correctly told what was wrong,
                # could only fix it by abandoning the placeholders.
                if isinstance(err.instance, str) and (
                    "{{" in err.instance or err.instance.startswith("$")
                ):
                    continue
                loc = ".".join(str(p) for p in err.absolute_path) or "(root)"
                errors.append(f"{path}.props.{loc}: {err.message}")
        for i, child in enumerate(node.get("children") or []):
            walk(child, f"{path}.children[{i}]")

    if schema.get("root"):
        walk(schema["root"], "root")
    return errors


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def _bindings_used(node: dict, found: set[str] | None = None) -> set[str]:
    """Root binding names referenced anywhere in an instantiated tree.

    Data sources are emitted from what the page actually binds, so a page never
    carries a fetch it does not use, and never binds something nothing fetches.
    """
    found = set() if found is None else found
    for value in (node.get("props") or {}).values():
        for text in ([value] if isinstance(value, str) else
                     [v for v in value if isinstance(v, str)] if isinstance(value, list) else
                     [v for v in value.values() if isinstance(v, str)] if isinstance(value, dict) else
                     []):
            for m in re.finditer(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)", text):
                found.add(m.group(1))
    for child in node.get("children") or []:
        _bindings_used(child, found)
    return found


def workflow_for_page(doc: dict, page: dict, entity: dict | None) -> str | None:
    """The workflow a form on this page dispatches on submit.

    Read from `PageContract.dispatches`, not inferred. Inferring it from step
    order binds the wrong flow: `Bike Drop-off Intake` opens by searching for
    the owner and registering a Customer, so its first mutating step names
    Customer while the page that starts it is `/jobs/new`. A rule over "first
    mutating step" sent the drop-off wizard to `Flag a Job as Awaiting Parts`.

    The workflow states its own entry point in the trigger's prose — "started
    from the New Drop-off wizard (/jobs/new)" — which is exactly the shape that
    string-matching would turn into a rule. So the contract carries it instead
    and the agent that already knows declares it.

    Bound to the form, not to the button that navigates here: a twelve-step
    intake dispatched from a list page gives the user nowhere to enter
    anything.
    """
    declared = page.get("dispatches")
    if not declared:
        return None
    known = {wf.get("id") for wf in _live(doc.get("workflows"))}
    return declared if declared in known else None


def bind_workflows(node: dict, workflow: str | None) -> dict:
    """Give every declarative Form on the page the workflow it submits to."""
    if not workflow or not isinstance(node, dict):
        return node
    props = node.get("props") or {}
    if (node.get("type") == "Form" and props.get("fields")
            and not props.get("workflow")):
        node["props"] = {**props, "workflow": workflow}
    for child in node.get("children") or []:
        bind_workflows(child, workflow)
    return node


#: What each authored state node is for. A2UI writes all four as siblings in
#: a Stack, so they render at once and permanently: a spinner beside an empty
#: state beside an error alert, on a page that fetched successfully.
STATE_NODES = {
    "LoadingState": "loading", "Skeleton": "loading",
    "EmptyState": "empty", "IllustratedEmpty": "empty", "Alert": "error",
}


def gate_states(node: dict, source: str | None) -> dict:
    """Gate the authored state nodes on the data source, and drop the unreachable.

    `ctx.data` distinguishes three cases, not four: a resolved source is present
    (empty or not), and a failed one is absent entirely — schema-page.tsx logs
    the failure and never sets the key, so one bad source cannot blank a page.

    Loading is not among them. Sources resolve server-side before the page
    renders, so nothing is ever in flight when a Conditional evaluates. A
    LoadingState on a server-rendered page is a node for a state that cannot
    occur, which is why "Loading customers" sat permanently under a table that
    had already loaded. Dropped rather than gated: no expression selects it.
    """
    if not source or not isinstance(node, dict):
        return node
    kept: list[dict] = []
    for child in node.get("children") or []:
        state = STATE_NODES.get(child.get("type")) if isinstance(child, dict) else None
        if state == "loading":
            continue
        if state:
            kept.append({
                "type": "Conditional",
                "props": {"when": (f"{source} == null" if state == "error"
                                   else f"{source} != null and count({source}) == 0")},
                "children": [child],
            })
            continue
        kept.append(gate_states(child, source))
    if node.get("children") is not None:
        node["children"] = kept
    return node


def repeat_aliases(node: Any, found: set[str] | None = None) -> set[str]:
    """Every per-row alias a Repeat introduces into its subtree.

    A composed tree may bind `{{order.total}}` inside a `Repeat` whose `as` is
    `order`. That root names no dataSource and never will — it is a scope, and
    reporting it as a dangling binding would fail a page that is correct.
    """
    found = set() if found is None else found
    if isinstance(node, dict):
        if _norm_type(node.get("type")) == "repeat" or node.get("repeat"):
            props = node.get("props") if isinstance(node.get("props"), dict) else {}
            for key in ("as", "alias", "itemName", "var"):
                v = node.get(key) or props.get(key)
                if isinstance(v, str) and v.strip():
                    found.add(v.strip().lstrip("$"))
        for v in node.values():
            repeat_aliases(v, found)
    elif isinstance(node, list):
        for v in node:
            repeat_aliases(v, found)
    return found


def _norm_type(t: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(t or "").lower())


def known_scopes(root: dict) -> set[str]:
    """Binding roots this page supplies without a fetch."""
    return set(SCOPE_ROOTS) | repeat_aliases(root)


def data_sources(doc: dict, page: dict, entity: dict | None, root: dict,
                 declared: frozenset[str] | set[str] = frozenset()) -> list[dict]:
    """The fetches this page needs, keyed to the bindings its tree actually uses.

    `declared` names the sources the caller already has (a composer-authored
    layout carries its own). Those roots are satisfied, so they are skipped and
    only the GAPS come back — see `plan_page` for why a carried set is not the
    same as a complete one.

    Emitted empty on every generated page, for three compounding reasons.

    It keyed on the planner's own placeholder names — `rows`, `record` — while
    an authored tree binds the entity: A2UI writes `{{customers}}`, so `rows in
    used` was false and nothing was emitted. It carried a `source` URL, which
    is not a field of the DataSource contract at all (`{name, entity, op}` is —
    see a reference app's documents.json). And that URL was `/api/{slug}`, the
    path this morning's derivation fix moved to `/api/data/{slug}`.

    The consequence was the whole visible product: tables bound to
    `{{customers}}` that never fetched, dashboards of em-dashes, empty states
    beside a spinner that never resolves, and no SSR — schema-page.tsx falls
    back to live client rendering when a page declares no sources, so nothing
    is fetched on the server either.

    The binding name *is* the source name. That is what the renderer looks up,
    so it is derived from the tree rather than assumed.
    """
    used = _bindings_used(root) - set(declared) - known_scopes(root)
    if not used:
        return []

    entities = _entities(doc)
    by_name = {_lower_first(e.get("name") or ""): e for e in entities.values()}
    detail = "[id]" in str(page.get("route") or "")
    out: list[dict] = []

    unresolved: list[str] = []
    for name in sorted(used):
        # A binding that names an entity resolves to it; anything else falls
        # back to the page's own entity, which is what `rows`/`record` mean.
        target = by_name.get(_lower_first(name)) or by_name.get(
            _lower_first(name.rstrip("s"))) or (
            entity if name in {ROWS, RECORD, METRICS} else None)
        if not target:
            # NOT `continue`. Skipping in silence is what put the literal text
            # "{{overdue.value}}" on a shipped page: the tree kept the binding
            # and the page lost the fetch, and neither half knew about the
            # other. Four aggregate counts and two further lists went this way
            # on one page — all six resolved correctly by the composer's
            # binder, all six discarded here for not being entity names.
            unresolved.append(name)
            continue
        if name == METRICS:
            # WITH its metric map. An aggregate source whose `metrics` is empty
            # resolves to `{}`, so every `{{metrics.<key>}}` on the page came
            # back undefined and the KPI tile rendered blank — a dangling
            # binding wearing a declared source's name.
            out.append({"name": name, "entity": target.get("name"),
                        "op": "aggregate",
                        "metrics": widget_metrics(doc, page.get("id"))})
            continue
        singular = name == RECORD or (detail and target is entity
                                      and name != ROWS)
        source = {
            "name": name,
            "entity": target.get("name"),
            "op": "get" if singular else "list",
        }
        # A saved view declared a filter, the picker rendered it, and nothing
        # narrowed the fetch: /articles offered Unread, Read and All saved and
        # every one showed the same rows. The default view's filter belongs on
        # the source so the page opens showing what it says it is showing.
        # Switching views is the renderer's job — this is the load.
        if not singular and target is entity:
            default = next(
                (v for v in (page.get("views") or []) if v.get("isDefault")),
                None)
            if default and default.get("filter"):
                source["filter"] = dict(default["filter"])
        out.append(source)

    if unresolved:
        raise PlanError(
            f"{page.get('id')}: " + ", ".join(
                f"binding {{{{{n}}}}} names no data this page can fetch"
                for n in unresolved)
        )
    return out


_AGG_OPS = ("aggregate", "stats")
#: Split `totalInventoryValue` / `total_inventory_value` / `Total Inventory
#: Value` into the same word list.
_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


def _words(text: Any) -> set[str]:
    """Comparable word set for a label, a source name or a metric key.

    Trailing plurals are folded so a tile labelled "Items" meets a metric
    called `itemCount`. Crude on purpose: this only ever decides which of a
    page's own declared metrics a tile meant, and an ambiguous answer is
    discarded rather than guessed.
    """
    out = set()
    for w in _WORD_RE.findall(str(text or "")):
        w = w.lower()
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def bind_widget_metrics(doc: dict, page: dict, root: dict,
                        sources: list[dict]) -> int:
    """Point `{{metrics.<key>}}` at a metric the page actually declares.

    `page_widgets` binds every KPI tile into a `metrics` namespace that only
    `data_sources` ever declared. A composer-authored layout carries its own
    dataSources, `plan_page` prefers those, and the `metrics` source was then
    never emitted: `/items` shipped three Stat tiles bound to
    `{{metrics.list_total_inventory_value}}` beside sources named `items`,
    `totalInventoryValue` and `lowStockCount`. The root named nothing, so the
    tiles rendered blank.

    Declaring a `metrics` source would resolve the binding, but to a row count
    the composer never asked for — a tile reading "Total Inventory Value" over
    a count is worse than a blank one. So a tile is first rebound onto the
    metric the composer DID design for it, matched on the words of the metric
    key (the source name only breaks ties). A match must be unique and strictly
    better than the runner-up; anything less is left alone for the gap-fill in
    `plan_page` to declare honestly. Returns how many tiles were rebound.
    """
    widgets = {_metric_key(w): w for w in _live(doc.get("widgets"))
               if w.get("page") == page.get("id")}
    if not widgets:
        return 0
    candidates: list[tuple[str, str, set[str], set[str]]] = []
    for s in sources:
        if not isinstance(s, dict) or s.get("op") not in _AGG_OPS:
            continue
        name = s.get("name")
        metrics = s.get("metrics")
        if not isinstance(name, str) or not isinstance(metrics, dict):
            continue
        for key in metrics:
            candidates.append((name, key, _words(key), _words(name)))
    if not candidates:
        return 0

    resolved: dict[str, str] = {}
    for mkey, widget in widgets.items():
        label = _words(widget.get("label"))
        if not label:
            continue
        scored = sorted(
            ((len(kw & label), len(sw & label), sname, key)
             for sname, key, kw, sw in candidates),
            reverse=True,
        )
        best = scored[0]
        if best[0] < 1:
            continue
        if len(scored) > 1 and scored[1][:2] == best[:2]:
            continue  # two declared metrics fit equally well — do not guess
        resolved[mkey] = "{{%s.%s}}" % (best[2], best[3])

    if not resolved:
        return 0

    rebound = 0

    def walk(node: Any) -> None:
        nonlocal rebound
        if isinstance(node, dict):
            props = node.get("props")
            if isinstance(props, dict):
                for prop, val in list(props.items()):
                    if not isinstance(val, str):
                        continue
                    for mkey, binding in resolved.items():
                        if val.strip() == "{{%s.%s}}" % (METRICS, mkey):
                            props[prop] = binding
                            rebound += 1
                            break
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(root)
    return rebound


#: Placeholders and repeat sources that only mean anything with a primary
#: entity behind them.
ENTITY_DEPENDENT = frozenset({
    "$entity.name", "$entity.plural", "$titleField", "$subtitleField",
    "$summaryFields", "$formFields", "$columns",
})


def derived_requires(template: dict) -> dict[str, bool]:
    """What a template genuinely needs, read off what it actually uses.

    Only scalar substitution is a real requirement. ``$entity.name`` in a
    heading has no sensible value without an entity, so a page without one
    cannot use that template. A ``repeat`` is different: it fans out over a
    list, and an empty list yields no nodes — which is exactly right for a
    metrics strip on a board that has no widgets. Treating a repeat as a
    requirement is what made a perfectly good kanban page fail rather than
    render without its garnish.

    Declaring `requires` separately from the body lets the two disagree, and
    they did on the first live run: a template declared no primary entity and
    then referenced `$entity.name`. Reading it off the body makes that
    impossible.
    """
    needs = {"primaryEntity": False, "widgets": False, "relatedCollections": False}

    def walk(node: dict) -> None:
        def scan(value: Any) -> None:
            if isinstance(value, str):
                if value in ENTITY_DEPENDENT:
                    needs["primaryEntity"] = True
            elif isinstance(value, dict):
                for v in value.values():
                    scan(v)
            elif isinstance(value, list):
                for v in value:
                    scan(v)

        scan(node.get("props") or {})
        for child in node.get("children") or []:
            walk(child)

    root = template.get("root")
    if isinstance(root, dict):
        walk(root)
    return needs


def _requires_non_empty(schema: dict, prop: str) -> bool:
    """Does this component refuse an empty list for ``prop``?"""
    spec = (schema.get("properties") or {}).get(prop) or {}
    return spec.get("type") == "array" and (spec.get("minItems") or 0) >= 1


def prune_unsatisfiable(node: dict, catalog: dict[str, dict]) -> dict | None:
    """Drop nodes whose data simply is not there.

    The same rule as an empty ``repeat``, one level down. A ``FilterBar``
    requires at least one chip; a page whose entity yields no filterable fields
    cannot give it one. That is an absent input, not a broken template — so the
    filter bar is omitted and the page renders without it, exactly as a metrics
    strip is omitted from a board with no widgets.

    Deliberately narrow: only an empty list on a prop the component declares
    non-empty. Every other prop violation is still a hard failure, because it
    means the template asked for something the component cannot do.
    """
    entry = catalog.get(node.get("type"))
    if entry:
        schema = entry.get("props") or {}
        for prop, value in (node.get("props") or {}).items():
            if value == [] and _requires_non_empty(schema, prop):
                return None

    children = node.get("children")
    if children:
        kept = [c for c in (prune_unsatisfiable(c, catalog) for c in children)
                if c is not None]
        node = dict(node)
        if kept:
            node["children"] = kept
        else:
            node.pop("children", None)
    return node


def assign_node_ids(node: dict, path: str = "n") -> dict:
    """Give every node a stable id derived from its position.

    Not decoration. ``LibraryNode`` — the open fallback that lets *any*
    registered component be used — requires an id, so a node without one falls
    through to the closed structural unions and is reported as an invalid
    discriminator. Every library component in a generated page was failing
    strict validation for want of an id, and the page rendered "as-is" with the
    component silently missing.

    Derived from the path rather than generated, so the same Blueprint produces
    the same ids and re-projection stays byte-identical.
    """
    out = dict(node)
    out.setdefault("id", path)
    kids = out.get("children") or []
    if kids:
        out["children"] = [assign_node_ids(c, f"{path}-{i}")
                           for i, c in enumerate(kids)]
    return out


def plan_page(doc: dict, page: dict, template: dict,
              catalog: dict[str, dict]) -> dict:
    """One Page Contract + its pattern template -> an engine page schema."""
    entity = _entities(doc).get((page.get("data") or {}).get("primaryEntity"))
    # Declared requirements are a floor; what the body uses is the truth.
    requires = dict(template.get("requires") or {})
    for key, needed in derived_requires(template).items():
        requires[key] = requires.get(key, False) or needed
    if requires.get("primaryEntity") and not entity:
        raise PlanError(
            f"{page.get('id')} uses pattern '{template.get('pattern')}' which "
            f"requires a primary entity, but the page contract declares none"
        )

    ctx = build_context(doc, page, entity)
    roots = instantiate(template["root"], ctx, doc, page, entity, catalog)
    if len(roots) != 1:
        raise PlanError(
            f"{page.get('id')}: template root produced {len(roots)} nodes; "
            f"a repeat on the root would leave the page without a single root"
        )
    root = bind_workflows(prune_unsatisfiable(roots[0], catalog),
                          workflow_for_page(doc, page, entity))
    # The composer's binder already resolved this tree's fetches, in the pass
    # that rewrote its pointers. Prefer them; derive only for a layout that
    # carries none. See `data_sources` for what re-deriving costs.
    # ONE CANONICAL FORM FOR `entity`. The engine resolves a source by entity
    # NAME (data-engine-bridge calls engine.query(entity, …)), and both forms
    # legitimately arrive here: the composer's binder writes "Plant" because
    # its registry is keyed by name, while an authoring agent writes
    # "ENTITY-001" because that is how a page references an entity everywhere
    # else in the Blueprint.
    #
    # Carrying them through unnormalised shipped a /plants whose every source
    # named ENTITY-001. The engine resolved no such entity, returned [], and
    # the page rendered its empty state over a database with rows in it — the
    # conditionals were right, the data was wrong. Only reachable once carried
    # sources became the default, which is the change that was meant to stop
    # exactly this kind of divergence.
    by_id = {e.get("id"): e.get("name") for e in _entities(doc).values()
             if e.get("id") and e.get("name")}
    carried = []
    for x in (template.get("dataSources") or []):
        if not isinstance(x, dict) or not x.get("name"):
            continue
        x = dict(x)
        x["entity"] = by_id.get(x.get("entity"), x.get("entity"))
        carried.append(x)
    sources = carried or (data_sources(doc, page, entity, root) if root else [])
    if root is not None:
        # ONE METRIC DIALECT. The composer writes
        # `{"expression": "sum(quantity * price)"}`; every resolver — the data
        # engine's computeSimple, the editor's preview-resolve — reads
        # `{"fn", "field"}` and nothing parses the other. Translate here, once,
        # so no dialect reaches a resolver that would silently answer 0.
        normalize_sources(sources)
        # A CARRIED SET IS NOT A COMPLETE ONE. It is what the composer thought
        # of; the tree is what this planner actually emitted, and the planner
        # binds every KPI tile into a `metrics` namespace of its own. Rebind
        # those onto the metrics the composer declared where one clearly fits,
        # then derive whatever is STILL unbacked. `data_sources` raises on a
        # root that names no fetchable data, which is what makes this loud —
        # `/items` shipped three blank Stat tiles because that check only ever
        # ran on the derived path, and carried sources are now the default.
        bind_widget_metrics(doc, page, root, sources)
        sources = sources + data_sources(
            doc, page, entity, root,
            declared={s.get("name") for s in sources if isinstance(s, dict)})
    primary = next((s["name"] for s in sources if s.get("op") == "list"), None)
    root = gate_states(root, primary) if root else root
    if root is not None:
        root = assign_node_ids(root)
    if root is None:
        raise PlanError(
            f"{page.get('id')}: the pattern's root node needs data this page "
            f"does not have, so there is nothing to render"
        )

    schema: dict[str, Any] = {
        "schemaVersion": "2",
        "id": page.get("id"),
        "route": page.get("route"),
        "meta": {
            "name": page.get("name"),
            "pattern": template.get("pattern"),
            "module": page.get("module"),
        },
        "dataSources": sources,
        "root": root,
    }
    errors = validate_props(schema, catalog)
    if errors:
        raise PlanError(f"{page.get('id')}: " + "; ".join(errors[:4]))

    return schema


def plan_pages(doc: dict, catalog: dict[str, dict] | None = None) -> dict[str, Any]:
    """Plan every page that has a pattern and a template. Reports what it skipped."""
    catalog = catalog or load_catalog()
    # One composed tree per page, and no second source. There used to be a
    # per-pattern template to fall back on, authored by its own agent; a page
    # nobody composed was stubbed from the template for its pattern. That made
    # "this page was designed" and "this page got the generic shape for its
    # kind" indistinguishable in the output — §76's silent divergence, arrived
    # at by fallback. A page nothing composed is now reported as such.
    authored = {l.get("page"): l for l in _live(doc.get("pageLayouts"))}

    planned: dict[str, dict] = {}
    skipped: list[dict] = []
    failed: list[dict] = []
    for page in _live(doc.get("pages")):
        pattern = page.get("pattern")
        template = authored.get(page.get("id"))
        if not template:
            skipped.append({"page": page.get("id"), "pattern": pattern,
                            "reason": "nothing composed a tree for this page"})
            continue
        try:
            planned[page.get("id")] = plan_page(doc, page, template, catalog)
        except PlanError as exc:
            failed.append({"page": page.get("id"), "pattern": pattern,
                           "reason": str(exc)})
    return {"planned": planned, "skipped": skipped, "failed": failed,
            "templates": sorted(authored)}


# ---------------------------------------------------------------------------
# The catalog, as A2UI sees it
# ---------------------------------------------------------------------------

def _prop_line(name: str, spec: dict, *, required: bool = False) -> str:
    """One prop, with the constraints that actually get violated.

    A bare name-and-type listing is what produced the first run's failures: a
    FilterBar authored without its required ``chips``, a MetricTile without
    ``value``, and a SplitView given ``masterWidth: 38`` because nothing said
    the units were pixels with a floor of 160. Required-ness and bounds are the
    part worth spending prompt tokens on.
    """
    if spec.get("enum"):
        kind = "|".join(str(v) for v in spec["enum"][:6])
    else:
        kind = spec.get("type") or "any"
        if kind == "array":
            items = spec.get("items") or {}
            inner = items.get("type")
            if inner == "object":
                # `array<object>` tells the author nothing, and they fill it in
                # from imagination — a Kanban's `cardFields` arrived as
                # `{label, value}` when the component wanted `{field}`. The
                # item shape is the part that gets guessed wrong.
                shape = items.get("properties") or {}
                req = set(items.get("required") or [])
                def _item_field(k: str) -> str:
                    spec = shape.get(k) or {}
                    mark = "*" if k in req else ""
                    # Enums inside an item shape are the values an author has
                    # no way to guess: `rowActions[].variant` came back as
                    # "ghost", which is not one the component accepts.
                    if spec.get("enum"):
                        return f"{k}{mark}:" + "|".join(
                            str(v) for v in spec["enum"][:4])
                    # A nested array of objects needs its own shape stated.
                    # `FilterBar.chips[].options` is a list of {value, label},
                    # and rendering it as a bare name let an author write a
                    # list of plain strings — correct-looking, and rejected.
                    if spec.get("type") == "array":
                        inner = spec.get("items") or {}
                        if inner.get("type") == "object":
                            keys = list(inner.get("properties") or {})[:4]
                            inner_req = set(inner.get("required") or [])
                            if keys:
                                fields = ", ".join(
                                    f"{n}{'*' if n in inner_req else ''}"
                                    for n in keys)
                                return f"{k}{mark}: [{{{fields}}}]"
                        return f"{k}{mark}: [{inner.get('type') or 'any'}]"
                    return f"{k}{mark}"

                fields = ", ".join(_item_field(k) for k in list(shape)[:6])
                kind = f"array<{{{fields}}}>" if fields else "array<object>"
            else:
                kind = f"array<{inner}>" if inner else "array"
    bounds = []
    for key, label in (("minimum", ">="), ("maximum", "<="),
                       ("minLength", "len>="), ("maxLength", "len<=")):
        if spec.get(key) is not None:
            bounds.append(f"{label}{spec[key]}")
    if spec.get("default") is not None:
        bounds.append(f"default={json.dumps(spec['default'])[:24]}")
    suffix = f" ({', '.join(bounds)})" if bounds else ""
    return f"{name}{'*' if required else ''}: {kind}{suffix}"


def catalog_digest(catalog: dict[str, dict], *, categories: tuple[str, ...] = ()) -> str:
    """A compact rendering of the catalog for a prompt.

    Full JSON Schemas for 165 components would dominate the context window, so
    the model gets names, composition rules and prop signatures. Validation
    still runs against the complete schemas — the model sees a summary, the
    gate does not.
    """
    lines: list[str] = ["`*` marks a required prop; omitting one fails the template."]
    by_cat: dict[str, list[dict]] = {}
    for entry in catalog.values():
        if categories and entry["category"] not in categories:
            continue
        by_cat.setdefault(entry["category"], []).append(entry)

    for cat in sorted(by_cat):
        lines.append(f"\n## {cat}")
        for entry in sorted(by_cat[cat], key=lambda e: e["name"]):
            schema = entry.get("props") or {}
            props = schema.get("properties") or {}
            required = set(schema.get("required") or [])
            # Required props first — those are the ones whose absence fails.
            ordered = (sorted(k for k in props if k in required)
                       + [k for k in props if k not in required])
            sig = ", ".join(_prop_line(k, props[k], required=k in required)
                            for k in ordered[:12])
            head = entry["name"]
            if entry["acceptsChildren"]:
                head += " (children)"
            contract = entry.get("childContract")
            if contract:
                if contract["kind"] == "roles":
                    head += f" [children are exactly: {', '.join(contract['roles'])}]"
                else:
                    paired = contract.get("pairedWith")
                    head += (f" [one child per {contract['role']}"
                             + (f", matching props.{paired}]" if paired else "]"))
            lines.append(f"- {head}")
            if sig:
                lines.append(f"    props: {sig}")
            doc = (entry.get("doc") or "").strip().split("\n")[0]
            if doc and not doc.startswith("Renderer primitive"):
                lines.append(f"    {doc[:150]}")
    return "\n".join(lines)


def pattern_page_facts(doc: dict) -> str:
    """Which pages each pattern must serve, and what each one actually has.

    A template is authored once and every page of that pattern inherits it, so
    it has to fit the *weakest* page in the group — not the one the model
    pictured. The first run wrote one `configuration` template around
    `$entity.name`, which fit Sign In and made the entry redirect (a non-visual
    route with no entity at all) unrenderable. Stating the group up front is
    cheaper than discovering it at projection time.
    """
    entities = _entities(doc)
    groups: dict[str, list[dict]] = {}
    for page in _live(doc.get("pages")):
        if page.get("pattern"):
            groups.setdefault(page["pattern"], []).append(page)

    lines: list[str] = []
    for pattern in sorted(groups):
        pages = groups[pattern]
        lines.append(f"- {pattern} — {len(pages)} page(s):")
        for page in pages:
            eid = (page.get("data") or {}).get("primaryEntity")
            entity = entities.get(eid)
            has = (f"entity {entity.get('name')}" if entity
                   else "NO PRIMARY ENTITY")
            widgets = len(page_widgets(doc, page.get("id")))
            lines.append(
                f"    {page.get('name')} ({page.get('route')}) — {has}, "
                f"{widgets} widget(s), {len(page.get('actions') or [])} action(s)"
            )
    return "\n".join(lines)


def patterns_in_use(doc: dict) -> list[str]:
    """The distinct §39 patterns this app's pages actually use.

    Per-app authoring means the model call count follows this list, not the
    page count and not the full §39 vocabulary.
    """
    return sorted({p.get("pattern") for p in _live(doc.get("pages")) if p.get("pattern")})


# ---------------------------------------------------------------------------
# One page's slice — what a per-page author is shown
# ---------------------------------------------------------------------------

def page_brief(doc: dict, page_id: str) -> dict:
    """Everything about one page and nothing about the other seventeen.

    A per-page author handed the whole Blueprint pays ~50k tokens a call for
    context it cannot act on, and eighteen of those is most of the cost of the
    whole run. It needs this page's contract, the entity behind it, the fields
    of anything it links to, its widgets, and — the part the pattern author
    never had — the requirements this page exists to satisfy.
    """
    pages = {p.get("id"): p for p in _live(doc.get("pages"))}
    page = pages.get(page_id)
    if not page:
        return {}

    entities = _entities(doc)
    entity = entities.get((page.get("data") or {}).get("primaryEntity"))
    wanted = set(page.get("requirements") or [])
    reqs = [r for r in _live(doc.get("requirements")) if r.get("id") in wanted]
    roles = {r.get("id"): r for r in _live(doc.get("roles"))}

    brief: dict[str, Any] = {
        "page": page,
        "requirements": reqs,
        "users": [roles[r] for r in (page.get("users") or []) if r in roles],
        "widgets": [w for w in _live(doc.get("widgets"))
                    if w.get("page") == page_id],
        "designSystem": doc.get("designSystem") or {},
    }
    if entity:
        brief["entity"] = entity
        # Derived field roles, so the author sees the real columns and form
        # fields rather than reconstructing them from the entity by eye.
        brief["derived"] = {
            "titleField": title_field(entity),
            "columns": columns_for(entity),
            "formFields": form_fields_for(
                entity, creating=str(page.get("route") or "").endswith("/new")),
            "summaryFields": summary_fields(entity),
        }
        brief["relatedCollections"] = [
            {**rel, "columns": rel.get("columns")}
            for rel in related_collections(doc, entity.get("id"))
        ]
    return brief


# ---------------------------------------------------------------------------
# §32 — the page set as slots, not as a free list
# ---------------------------------------------------------------------------

#: One slot per job an entity's UI has to do. A filter over a list is not on
#: this list, which is the whole point: the page-design prompt was already told
#: at length that a filter belongs in `views`, with the `/jobs` example spelled
#: out, and a run still returned `/jobs/mine`, `/jobs/unassigned`,
#: `/jobs/overdue`, `/jobs/awaiting-decision`, `/jobs/ready-for-collection` and
#: `/jobs/awaiting-extra-work`. A free list of pages admits a filtered page as a
#: perfectly good answer, so the instruction was arguing with the question.
#:
#: Asking slot by slot removes the room rather than policing it. There is no
#: sixth jobs slot to put "overdue" in, so it goes where it fits: `views`.
ENTITY_SLOTS = (
    ("list", "entity_list", "Every {name}, in one place."),
    ("detail", "record_workspace", "One {name}, with everything about it."),
    ("create", "form", "Add a {name}."),
)


def _screen_frames(doc: dict, *, specification: bool) -> list[dict]:
    """Screen-like frames from the sources held one way or the other.

    Only frames that look like screens: `looksLikeScreen` is recorded rather
    than enforced at extraction (§49), and a component or a colour swatch is
    not a page even in a file that IS the specification.
    """
    out: list[dict] = []
    for source in doc.get("designSources") or []:
        is_spec = str(source.get("treatAs") or "evidence") == "specification"
        if is_spec is not specification:
            continue
        for frame in source.get("frames") or []:
            if frame.get("looksLikeScreen", True) and frame.get("nodeId"):
                out.append({"source": source.get("id"), **frame})
    return out


def specification_frames(doc: dict) -> list[dict]:
    """Frames from every design the user connected as the specification.

    Empty when none is — the normal case, which keeps `page_slots` answering
    entity by entity exactly as before.
    """
    return _screen_frames(doc, specification=True)


def reference_frames(doc: dict) -> list[dict]:
    """Frames from every design connected as a reference rather than the spec.

    THESE ARE SLOTS TOO, AND THAT IS THE WHOLE POINT OF THIS FUNCTION.

    A reference does not decide the page SET — the data model does, and one
    dashboard legitimately implying thirteen pages is the outcome §48 asks for.
    But it does decide those pages it drew. A frame somebody drew is a screen
    somebody drew, whichever way the file is held, and the common case is a
    design that covers only the interesting part of an application: the part
    that must come out as drawn, with the rest generated around it.

    That guarantee did not exist. Frames were absent from the slot list under a
    reference, and `figmaFrame` was attached afterwards only if `page_contracts`
    happened to notice the correspondence while it was authoring thirty other
    pages. Nothing required it to notice and nothing reported when it did not,
    so the failure was a drawn screen quietly composed from components —
    buildable, and not the thing that was drawn.

    Naming the frames as slots is the same move `frame_slots` already argues
    for: an enumeration somebody connected on purpose is not a heuristic.
    """
    return _screen_frames(doc, specification=False)


def frame_slots(frames: list[dict], *, sole: bool = True) -> list[dict]:
    """One slot per designed screen: the design IS the answer space.

    THE QUESTION NARROWS; THE ANSWER IS NOT FILTERED. `page_slots` says of its
    own entity slots that pruning was considered and rejected because "the
    obvious signals do not discriminate", and that matching names against the
    description would be "string-matching a heuristic into a rule". This is
    neither. A frame list is an enumeration, and four connected frames are four
    screens somebody drew on purpose.

    So a design held as the specification does not prune a page set derived
    from entities — it replaces the question. `page_contracts` is asked which
    route each frame is, rather than which of thirty entity features to keep.
    """
    why = ("Give this frame a route and a pattern. It is a screen the user "
           "drew, so it is not declinable.")
    if not sole:
        why += (" The entity features below are built around it, not instead "
                "of it.")

    slots: list[dict] = []
    for frame in frames:
        node_id = frame["nodeId"]
        name = str(frame.get("name") or "").strip() or node_id
        slots.append({
            "feature": node_id,
            "figmaFrame": node_id,
            "source": frame.get("source"),
            "name": name,
            "pages": [{"slot": "screen",
                       "prompt": "The screen drawn as \u201c%s\u201d." % name}],
            "prompt": why,
        })
    return slots


def page_slots(doc: dict) -> list[dict]:
    """The features this application's page set may fill, one per entity.

    Two rules, both encoded in the shape of the question rather than argued in
    prose the agent has already been observed to ignore.

    **A feature is filled or declined whole.** The unit is the entity, not the
    page: a list with no way to create a record is not a cheaper feature, it is
    a broken one. A per-page question invites exactly that — each page looks
    reasonable alone while the set does not add up to a job a user can finish.
    Fewer complete features beat more incomplete ones.

    **What the user asked for is not a candidate for pruning.** Deliberately
    *not* computed here. The obvious signals do not discriminate: every one of
    21 entities in a live run carried requirements, and 37 of 39 requirements
    cited `application.description`, so both mark everything required and mean
    nothing. Matching entity names against the description would discriminate,
    but only by string-matching a heuristic into a rule.

    So the judgement stays with the model and the evidence travels to it: the
    slots carry their requirements, and :func:`page_slot_prompt` puts the
    user's own words beside them. "The user named this" is a reading of their
    sentence, which is the one thing a model is better at than a rule.
    """
    # A DESIGN HELD AS THE SPECIFICATION REPLACES THIS QUESTION.
    # Entity slots ask which of the data model's features should exist;
    # connected frames already answer which screens exist. Asking both
    # gives the cross-product — which is how one dashboard became a
    # thirteen-page application. Correct for evidence, wrong for a
    # specification.
    designed = specification_frames(doc)
    if designed:
        return frame_slots(designed)

    slots: list[dict] = [
        {"feature": "home", "entity": None, "requirements": [],
         "pages": [{"slot": "home", "pattern": "dashboard",
                    "prompt": "Where a user lands."}],
         "prompt": "Omit if the app opens on a list."},
    ]
    entities = (doc.get("data") or {}).get("entities") or []
    names = {e.get("id"): e.get("name") or e.get("id") for e in entities}
    for entity in entities:
        eid = entity.get("id")
        name = entity.get("name") or eid
        # A field that references another entity is how "reachable only
        # through" becomes a fact instead of a guess. PartUsage.jobId and
        # RepairLine.jobId are the difference between a record a user goes to
        # and one they only ever write while looking at something else.
        parents = sorted({
            f.get("references") for f in (entity.get("fields") or [])
            if f.get("references") and f.get("required")
        })
        slots.append({
            "feature": eid,
            "entity": eid,
            "name": name,
            "reachedThrough": [names.get(p, p) for p in parents],
            "requirements": list(entity.get("requirements") or []),
            "pages": [
                {"slot": f"{eid}.{slot}", "pattern": pattern,
                 "prompt": why.format(name=name)}
                for slot, pattern, why in ENTITY_SLOTS
            ],
        })

    # THE DRAWN SCREENS LEAD, AND THEY ARE NOT ENTITY FEATURES.
    # A reference does not replace this question — every entity slot above
    # survives — but the screens it drew are already answered, so they are
    # stated rather than left to be noticed. First in the list because they
    # are the fixed points the rest is arranged around.
    return frame_slots(reference_frames(doc), sole=False) + slots


_DRAWN_PREAMBLE = (
    "SOME OF THESE SCREENS WERE DRAWN. A design is connected as a reference, "
    "and the slots at the top of the list are its frames, each carrying the "
    "`figmaFrame` it must be built from. They are not declinable and they are "
    "not candidates: every one of them is a page, and every one keeps the "
    "`figmaFrame` its slot carries \u2014 that is how a screen gets built from "
    "the drawing rather than composed from components.\n\n"
    "A design usually covers only the interesting part of an application. The "
    "entity features that follow are the rest, built AROUND those screens. "
    "Where an entity feature would BE one of them, answer it with that "
    "screen\u2019s page instead of authoring a second page at the same route: "
    "the drawn one is the one that exists.\n\n"
)


def page_slot_prompt(doc: dict) -> str:
    """The slot question, with the user's own words attached (§115)."""
    described = (doc.get("application") or {}).get("description") or ""

    # THE SPECIFICATION ASKS A DIFFERENT QUESTION, so it gets a different
    # prompt. Everything below argues about which entity features are worth
    # having — declining lookups, folding line items into their parent, reading
    # the phasing in the brief. None of it applies when the answer space is a
    # list of screens somebody drew: there is nothing to decline, and the only
    # judgement left is what each frame IS.
    designed = specification_frames(doc)
    if designed:
        return (
            "This application's screens are the frames of a connected design, "
            "and they are the whole page set. One page per frame: no more, and "
            "none declined.\n\n"
            "For each frame decide only what it IS — its route and its pattern. "
            "Set `figmaFrame` to the frame's `nodeId`, which the slot already "
            "carries: it is how the screen gets built from the drawing rather "
            "than composed from components.\n\n"
            "Do NOT add pages the design does not show. A list behind a "
            "dashboard's numbers, a form that creates what it displays, a "
            "sign-in — all reasonable, all absent from these frames, and all "
            "out of scope here. If the set genuinely cannot work without one, "
            "say so in `issues` rather than adding it.\n\n"
            "The entities exist and are still yours to bind: a screen reads "
            "and writes them. What you may not do is invent a screen for one.\n\n"
            "The user's own words, for the routes and the wording:\n\n"
            f"  \u201c{described}\u201d"
        )

    return (
        _DRAWN_PREAMBLE if reference_frames(doc) else ""
    ) + (
        "Fill in this application's page set feature by feature. A feature is "
        "one entity's pages: fill it completely or decline it completely.\n\n"
        "Filling it completely matters more than filling many. A list with no "
        "way to add a record, or a record with nowhere to open it, is not a "
        "smaller feature — it is one a user cannot finish a job with. Prefer "
        "few features a user can complete over many they cannot.\n\n"
        "Decline a feature when the entity is a join table, a lookup, or "
        "something only ever edited inside another record — a line item is "
        "edited on its invoice, not on a page of its own.\n\n"
        "`reachedThrough` names the entities a feature hangs off, taken from "
        "its required references. A feature that is reached through another is "
        "usually written while looking at that one, not visited: default to "
        "declining it and giving the parent the means to edit it.\n\n"
        "Except: anything the user asked for is not declinable, however "
        "lookup-shaped it shows up here. These are their words:\n\n"
        f"  \u201c{described}\u201d\n\n"
        "If they named it for NOW, it gets its feature, and it gets it "
        "complete.\n\n"
        # NAMED AND DEFERRED ARE NOT THE SAME THING. This said "if they named "
        # it, it gets its feature" — so a brief that names ten modules and then
        # says which six to begin with got all ten. The Palestinian Legislative
        # Council brief ended "Begin with sessions, committees, attendance,
        # voting, minutes, and document management. Add legislative workflows,
        # mobile access, analytics, and the public portal in later phases", and
        # the run planned 44 pages across all ten. The sentence was in the
        # description and quoted above; the rule discarded it, because naming
        # phase two is how you get phase two built.
        "Read the phasing in their words, because most briefs have one. "
        "\u201cBegin with\u2026\u201d, \u201clater\u201d, \u201cphase "
        "two\u201d, \u201ceventually\u201d and \u201conce that works\u201d "
        "all name something AND put it out of scope, and the second half is "
        "as much a decision as the first. Fill what they said to start with. "
        "Decline what they deferred, and give the deferral as the reason \u2014 "
        "it is theirs, not yours.\n\n"
        "Building the later phases now is not generosity. It is pages nobody "
        "asked for yet, each one a route to compose, maintain and read past on "
        "the way to the ones they wanted, and it buries the first release in "
        "work they explicitly postponed. When the brief names no phases, this "
        "does not apply and everything they named is in scope.\n\n"
        "There is no slot for a filtered list, because a filter is not a page. "
        "Every \u2018only mine\u2019, \u2018overdue\u2019, \u2018unassigned\u2019 or "
        "\u2018awaiting X\u2019 belongs in that list page\u2019s `views` as "
        "{key, label, filter}."
    )

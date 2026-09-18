"""Whether the application the Blueprint describes would actually work.

Every other edge asks whether the Blueprint is *coherent* — a page addressed to
a role that exists, an endpoint guarded by a real permission. None asks whether
the thing it describes DOES anything, and that is the class of defect that
survived every check and reached people using the app:

  * five buttons on one page carrying a label and no action at all — they
    render, they are clickable, and nothing happens
  * `workflow: "markPlantWateredToday"` where no such workflow exists, which
    answers "Workflow not found" on click
  * `{{overdue.value}}` with no `overdue` source, which renders the template
    text to whoever opens the page
  * a declared page with no composed tree, so its route 404s

Each was found by using the application. None needed the application running to
find: they are all two-sided consistency questions over the Blueprint, decidable
before a single file is written.

THE FINDINGS ARE MEANT TO BE REJECTIONS. §73 says verification exists to close
the loop, and the orchestrator already re-asks a node when its output is
refused — that mechanism recovers composition failures on nearly every run. A
button with no action is not a page to repair afterwards; it is a page that was
not composed correctly, and the composer is the thing that should hear about it.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

#: Components that exist to be acted upon. A `Text` that does nothing is
#: content; a `Button` that does nothing is a defect.
_ACTIONABLE = ("Button", "Form")

#: Page findings whose remedy is NOT the page composer's to make: the cause is
#: upstream (a missing text column, a form field whose column the data model
#: lacks) or the condition degrades gracefully at runtime (a search that matches
#: nothing returns nothing, it does not break the page). Re-composing cannot fix
#: them, so REFUSING a composition over them only burns the bounded repair rounds
#: and ships the page degraded anyway — the "smith cannot fail" trap. They are
#: still RETURNED (surfaced for the report and for a run that can route them to
#: the owning agent), just not treated as a composition blocker.
ADVISORY_PAGE_RULES = frozenset({
    "search-without-columns",   # entity has no text column — the composer can't add one
    "form-field-unknown",       # a form field whose column the data model lacks upstream
})

#: `{{plants}}` and `{{plants.count}}` both name `plants`.
_BINDING = re.compile(r"\{\{([^}]+)\}\}")

# A route addresses one existing record when it carries a dynamic id segment —
# a detail page (`/records/[id]`) OR an edit page (`/records/[id]/edit`), which
# does not END with `]`. A Next.js catch-all (`[...slug]`) is not a record id.
_ROUTE_HAS_ID = re.compile(r"/\[[^.\]/][^\]/]*\]")


def _dangling(schema: dict) -> list[str]:
    """`dangling_bindings`, or nothing if it cannot be reached.

    A verification edge must not fail the run over an import, and a check that
    cannot run is better silent than wrong.
    """
    try:
        from services.a2ui_to_forge import dangling_bindings
        return dangling_bindings(schema)
    except Exception:  # noqa: BLE001
        return []


def _planner_placeholders() -> set[str]:
    """Names the planner substitutes, which are not bindings yet.

    A pattern template says `{{rows}}` and `$item.label`; `plan_page` resolves
    both when it instantiates the template for a page. Read as bindings they
    look like references to data nothing provides — which flagged the coherent
    fixture as broken and would have failed every pattern-derived page.

    Taken from the planner's own constants rather than restated, because a
    vocabulary listed twice drifts.
    """
    try:
        from services.blueprint.page_planner import RECORD, ROWS
        return {ROWS, RECORD, "metrics"}
    except Exception:  # noqa: BLE001
        return {"rows", "record", "metrics"}


def _live(items: Any) -> list[dict]:
    """Artifacts still in play — the same reading `projection` and
    `completeness` take.

    DEPRECATED was missing here, and it is not a nicety: a retired page kept
    being graded. Its controls were checked, its contract was held to a screen
    that no longer resolves, and the observer opened repair rounds against a
    screen the owner had asked to be rid of. A retired artifact is not part of
    the application the Blueprint describes, so it is not part of the question
    "would this application work".
    """
    return [i for i in (items or [])
            if isinstance(i, dict) and i.get("status") not in ("SUPERSEDED", "DEPRECATED")]


def _action_props() -> set[str]:
    """Every way a component may declare that it does something.

    Read from the composer's own contract, so this cannot drift from what the
    composer is told to produce. Hand-listing them is how `opensDialog` came to
    be refused on a page whose create form was a modal: the list held four of
    the six the catalog offers.
    """
    try:
        from services.a2ui_catalog import _COMPOSE_ONE_OF
    except Exception:  # noqa: BLE001 — a lookup must not fail verification
        return {"workflow", "navigate", "submit", "onClick"}
    out: set[str] = set()
    for choices in _COMPOSE_ONE_OF.values():
        out.update(choices)
    return out


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
        return
    if not isinstance(node, dict):
        return
    if node.get("type"):
        yield node
    yield from _walk(node.get("children") or [])


def _workflow_refs(props: Any) -> Iterator[str]:
    """Every `workflow` value at any depth.

    Nested as often as top-level — `Table.rowActions[]`, `emptyAction` — and a
    check that reads one key walks past the rest.
    """
    if isinstance(props, list):
        for item in props:
            yield from _workflow_refs(item)
        return
    if not isinstance(props, dict):
        return
    for key, value in props.items():
        if key == "workflow" and isinstance(value, str) and value:
            yield value
        elif isinstance(value, (dict, list)):
            yield from _workflow_refs(value)


# ---------------------------------------------------------------------------
# A DESTRUCTIVE CONTROL DELETES. `delete` is the one mutating verb the
# entity-level workflow check cannot satisfy by proxy: an Update workflow can
# stand in for neither Create nor Delete, so a page that declares `delete` on an
# entity whose only workflows create and update it has NO workflow to delete
# with — and the composer, given nothing correct to wire the Delete button to,
# reaches for the nearest write workflow (Update). The button then updates the
# record instead of removing it and looks broken. Decided on the DB operation
# (`db_delete`) rather than a label, and on the terse verb the page contract and
# the control label already use — the same vocabulary `detail_action_guard` and
# `verification._acts_on_existing_record` speak.
# ---------------------------------------------------------------------------

#: Action/label verbs that REMOVE a record. Their intent can only be served by a
#: workflow whose action is `db_delete`; no other write op deletes.
_DESTRUCTIVE_VERBS = frozenset({"delete", "remove", "archive", "destroy", "discard"})


def _verb_of(text: Any) -> str:
    """The leading word of an action string or a control label, lowercased —
    `"Delete Record"` → `"delete"`, `"delete"` → `"delete"`. The page contract
    names actions by intent (`delete`, `filter_by_status`) and controls by label
    (`Delete Record`); both reduce to their first word for the verb."""
    for part in re.split(r"[^a-z0-9]+", str(text or "").lower()):
        if part:
            return part
    return ""


def is_destructive_action(action: Any) -> bool:
    """Whether a page-contract action removes a record (delete / remove /
    archive …). Accepts the bare string the contract uses or a dict form."""
    label = action if isinstance(action, str) else (
        (action or {}).get("name") or (action or {}).get("label") or (action or {}).get("id")
        if isinstance(action, dict) else action)
    return _verb_of(label) in _DESTRUCTIVE_VERBS


def _workflow_db_ops(wf: dict) -> set[str]:
    """The `db_*` action types a workflow performs, read from its steps —
    `{"db_insert"}`, `{"db_update"}`, `{"db_delete"}`, or a union."""
    ops: set[str] = set()
    for step in (wf or {}).get("steps") or []:
        if not isinstance(step, dict):
            continue
        at = (step.get("config") or {}).get("actionType")
        if isinstance(at, str) and at.startswith("db_"):
            ops.add(at)
    return ops


def _workflow_targets_entity(doc: dict, wf: dict, entity: str) -> bool:
    """Whether a workflow's DB steps act on `entity` — matched on the step's
    own `entity` id or, failing that, the entity's table name. `entity` may be
    given as an id or a name."""
    by_name = _entity_id_by_name(doc)
    ent_id = entity if entity in set(by_name.values()) else by_name.get(entity, entity)
    tables = {
        str(e.get("table") or "").lower()
        for e in _live((doc.get("data") or {}).get("entities"))
        if e.get("id") == ent_id and e.get("table")
    }
    for step in (wf or {}).get("steps") or []:
        if not isinstance(step, dict):
            continue
        cfg = step.get("config") or {}
        if not str(cfg.get("actionType") or "").startswith("db_"):
            continue
        if str(step.get("entity") or "") == ent_id:
            return True
        if str(cfg.get("table") or "").lower() in tables:
            return True
    return False


def entities_with_delete_workflow(doc: dict) -> set[str]:
    """Entity ids some workflow DELETES — a step whose action is `db_delete`
    on that entity's id or table. The set a destructive page action can be
    correctly wired against."""
    out: set[str] = set()
    id_by_name = _entity_id_by_name(doc)
    ids = set(id_by_name.values())
    for e in _live((doc.get("data") or {}).get("entities")):
        eid = str(e.get("id") or "")
        if eid and any(
            "db_delete" in _workflow_db_ops(w) and _workflow_targets_entity(doc, w, eid)
            for w in _live(doc.get("workflows"))
        ):
            out.add(eid)
    return out


def _delete_workflow_for(doc: dict, page: dict) -> str | None:
    """The name of a workflow that deletes THIS page's primary entity, or None.
    Used to name the correct target when a Delete control is mis-bound."""
    entity = str((page.get("data") or {}).get("primaryEntity") or "")
    if not entity:
        return None
    for w in _live(doc.get("workflows")):
        if "db_delete" in _workflow_db_ops(w) and _workflow_targets_entity(doc, w, entity):
            return str(w.get("name") or w.get("id") or "") or None
    return None


def _workflow_by_id(doc: dict, wid: str) -> dict | None:
    return next((w for w in _live(doc.get("workflows")) if str(w.get("id")) == str(wid)), None)


#: Control/action verbs that name a CRUD operation, and the DB op each requires.
#: UNAMBIGUOUS verbs only — `save`/`submit`/`apply`/`modify` name no single op
#: (a Save can insert or update), so they are left out rather than guessed. This
#: is the closed CRUD vocabulary, not a growing exception list: a control that
#: says one of these must run a workflow that does the matching thing.
def _acts_on_another_thing(label: str, entity_name: str) -> bool:
    """Whether an action's object is something OTHER than this page's record.

    Read from the action's own name. `add_test_to_package` joins two things
    and creates neither, `add_lab_staff` adds staff rather than a Lab, while
    `add_package` on a TestPackage page is that page's own create — the
    contract's short name for the entity, which is why the object only has to
    be part of the entity's name, not equal to it.

    Ambiguous names (`create_user_account` on a User page) fall on the side of
    NOT demanding, on purpose: a demand that should not have been made costs
    the page every attempt it has and then the page itself, while a demand
    that is not made is still caught by the terminal `verification` node.
    """
    words = [w for w in re.split(r"[^a-z0-9]+", str(label or "").lower()) if w]
    if len(words) < 2:
        return False                       # a bare `add` is a create
    if {"to", "from", "into", "onto"} & set(words[1:]):
        return True                        # joins two things; creates neither
    entity = re.sub(r"[^a-z0-9]", "", str(entity_name or "").lower())
    obj = "".join(words[1:])
    for candidate in (obj, obj.rstrip("s"), obj + "s"):
        if candidate and candidate in entity:
            return False
    return True


_VERB_DB_OP: dict[str, str] = {
    "create": "db_insert", "add": "db_insert", "new": "db_insert", "register": "db_insert",
    "edit": "db_update", "update": "db_update",
    "delete": "db_delete", "remove": "db_delete", "archive": "db_delete", "destroy": "db_delete",
}


def _workflow_for_op(doc: dict, page: dict, op: str) -> str | None:
    """The name of a workflow that performs `op` on THIS page's primary entity,
    or None — the correct target to name when a control is mis-bound."""
    entity = str((page.get("data") or {}).get("primaryEntity") or "")
    if not entity:
        return None
    for w in _live(doc.get("workflows")):
        if op in _workflow_db_ops(w) and _workflow_targets_entity(doc, w, entity):
            return str(w.get("name") or w.get("id") or "") or None
    return None


def _columns_of_workflow_tables(doc: dict, wf: dict) -> set[str]:
    """Column names of every entity a workflow's db steps write. Empty when the
    workflow has no db step whose table resolves — the signal that we cannot
    judge which fields a form dispatching it should collect."""
    cols: set[str] = set()
    for step in (wf or {}).get("steps") or []:
        cfg = step.get("config") or {}
        if not str(cfg.get("actionType") or "").startswith("db_"):
            continue
        ent = _entity_for_table(doc, cfg.get("table"))
        if ent is not None:
            cols |= {str(f.get("name")) for f in ent.get("fields") or [] if f.get("name")}
    return cols


def form_field_findings(doc: dict, page: dict, layout: dict) -> list[str]:
    """A Form collects fields the entity it writes still has. A field is
    accepted when it is a declared input of the Form's workflow, a column of the
    table that workflow writes, or a session-filled column. A field that is none
    of these is one the entity no longer has — renamed or removed — so the form
    collects a value that goes nowhere; the write drops it or fails. The
    form-side mirror of `unsatisfied_inputs` (which catches the reverse: a
    workflow input no form collects)."""
    session_filled = _session_filled_fields(doc)
    out: list[str] = []
    for form in _walk(layout.get("root")):
        if form.get("type") != "Form":
            continue
        wid = (form.get("props") or {}).get("workflow")
        wf = _workflow_by_id(doc, str(wid)) if wid else None
        if wf is None:
            continue                      # a form with no workflow: nothing to judge against
        columns = _columns_of_workflow_tables(doc, wf)
        if not columns:
            continue                      # cannot judge without the target's columns
        inputs = {str(i.get("name")) for i in wf.get("inputs") or [] if i.get("name")}
        accepted = inputs | columns | session_filled
        for name in sorted(_form_fields_of(form)):
            # accept a FK spelled either `owner` or `ownerId`.
            variants = {name, f"{name}Id", f"{name}_id",
                        re.sub(r"(Id|_id)$", "", name)}
            if variants & accepted:
                continue
            out.append(f"Form collects {name!r}, which is neither an input of "
                       f"{wf.get('name') or wid} nor a column of the entity it writes "
                       f"(columns: {', '.join(sorted(columns))}) — a field renamed or removed "
                       f"leaves the form collecting a value that goes nowhere. Drop the field, "
                       f"or point it at a column the entity has.")
    return out


def _bindings(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, list):
        for item in node:
            found |= _bindings(item)
        return found
    if not isinstance(node, dict):
        return found
    for value in node.values():
        if isinstance(value, str):
            found.update(m.split(".")[0].strip() for m in _BINDING.findall(value))
        else:
            found |= _bindings(value)
    return found


#: Verbs that OPEN a record rather than change it — satisfied by a navigation
#: to the record's own page, or a row click.
_VIEW_VERBS = frozenset({"view", "open", "show", "details", "detail"})

_COLLECTION_PATTERNS = frozenset({"entity_list", "list", "table", "collection", "master_detail", "index"})
_FORM_PATTERNS = frozenset({"form", "create", "edit", "new", "wizard", "configuration", "settings"})
_RECORD_PATTERNS = frozenset({"record_workspace", "record", "detail", "show"})


def page_family(page: dict) -> str | None:
    """`collection`, `form`, `record`, or None — from the page's pattern, with
    an id-bearing route read as a record page. The families the deterministic
    template composes, and the ones an `edit` can be hosted on."""
    pattern = str(page.get("pattern") or "").strip().lower()
    route = str(page.get("route") or "")
    if pattern in _COLLECTION_PATTERNS:
        return "collection"
    if pattern in _FORM_PATTERNS or re.search(r"/(new|create|add(-[a-z]+)?|edit)(/|$)", route):
        return "form"                         # `/records/new`, `/add-data`, `/x/[id]/edit`
    if pattern in _RECORD_PATTERNS or (re.search(r"\[[^\]]+\]", route) and pattern not in _FORM_PATTERNS):
        return "record"
    return None


def _somewhere_to_go(doc: dict, page: dict, entity: str, by_name: dict,
                     families: tuple[str, ...]) -> bool:
    """A `create` or `edit` on a list is a navigation to the page that collects
    the fields — a form page (or, for edit, the record's own page) for this
    entity. A button or row action cannot run Create/Update itself (nothing
    around it collects the fields), so with no such page the verb has nowhere
    to go and demanding a control would be unsatisfiable."""
    wanted = {entity, by_name.get(entity, "")} - {""}
    if page_family(page) in families:
        return True
    return any(page_family(p) in families
               and str((p.get("data") or {}).get("primaryEntity") or "") in wanted
               for p in _live(doc.get("pages")))


def _intents(props: Any, actions: set[str]) -> Iterator[dict]:
    """Every dict inside a node's props that carries an action — the node's own
    props, and the nested ones (`Table.rowActions[]`, `emptyAction`,
    `headerActions[]`) — so a row action counts as the control it is."""
    if isinstance(props, list):
        for item in props:
            yield from _intents(item, actions)
        return
    if not isinstance(props, dict):
        return
    if set(props) & actions:
        yield props
    for v in props.values():
        if isinstance(v, (dict, list)):
            yield from _intents(v, actions)


def _route_shape(route: str) -> str:
    """`/master-data/[id]`, `/master-data/{{id}}`, `/master-data/{id}` and
    `/master-data/{{row.id}}` all name the same page."""
    return re.sub(r"(\[[^\]/]+\]|\{\{[^}]*\}\}|\{[^}/]*\})", "*",
                  str(route or "").split("?")[0].rstrip("/")) or "/"


def declared_action_findings(doc: dict, page: dict, layout: dict) -> list[str]:
    """A page declares what a person can DO there (`actions: [view, edit,
    delete]`); the composed tree must give each of those a control. The
    inverse of `control-without-action`: there every control must do
    something, here everything declared must have a control. Without it a
    re-compose that DROPPED the Delete row action was accepted — the page
    passed every per-control check because it had no controls to check —
    and the user's "Delete does nothing" became "Delete is gone".

    Checked only where a control could be satisfied: a CRUD verb whose
    workflow exists on the page's entity, a view verb whose record page
    exists. What is not there to bind is the workflow author's (Page↔Workflow),
    not the composer's."""
    entity = str((page.get("data") or {}).get("primaryEntity") or "")
    if not entity or not layout:
        return []
    route = str(page.get("route") or page.get("id") or "")
    by_name = _entity_id_by_name(doc)
    ent_name = next((str(e.get("name")) for e in _live((doc.get("data") or {}).get("entities"))
                     if str(e.get("id")) == entity), entity)
    actions = _action_props()
    intents = [i for n in _walk(layout.get("root")) for i in _intents(n.get("props") or {}, actions)]
    tables = [n for n in _walk(layout.get("root")) if n.get("type") == "Table"]

    def label_of(i: dict) -> str:
        return str(i.get("label") or i.get("submitLabel") or i.get("aria-label") or "")

    def runs_op(op: str) -> bool:
        for i in intents:
            for ref in _workflow_refs(i):
                wf = _workflow_by_id(doc, ref)
                if wf is not None and op in _workflow_db_ops(wf) \
                        and _workflow_targets_entity(doc, wf, entity):
                    return True
            if _VERB_DB_OP.get(_verb_of(label_of(i))) == op and (set(i) & actions):
                return True                   # "Add Record" → the form page; "Edit" → the form
        return False

    detail_routes = {str(p.get("route")) for p in _live(doc.get("pages"))
                     if "[" in str(p.get("route") or "")
                     and str((p.get("data") or {}).get("primaryEntity") or "") in {entity, by_name.get(entity, "")}}

    def opens_record() -> bool:
        shapes = {_route_shape(r) for r in detail_routes}
        for t in tables:
            if (t.get("props") or {}).get("onRowClick") or (t.get("props") or {}).get("rowHref"):
                return True
        for i in intents:
            nav = i.get("navigate") or i.get("href") or i.get("to")
            if isinstance(nav, str) and _route_shape(nav) in shapes:
                return True
            if _verb_of(label_of(i)) in _VIEW_VERBS and (set(i) & actions):
                return True
        return False

    def names_a_record() -> bool:
        # An update or a delete acts on a record the page can name: the route's
        # own `[id]`, or a row of a Table / an item of a Repeat over the entity.
        # /add-data declares `update` too (the contract imagines one form that
        # creates or edits), but a Form runs ONE workflow and nothing on that
        # route names a record — a control there would be refused for its
        # inputs, so demanding it would only burn the composer's attempts.
        # That contract is the planner's to reshape, not the composer's.
        if _record_in_scope(doc, page, entity) or _reaches(doc, page, entity):
            return True
        wanted = {entity, by_name.get(entity, "")} - {""}
        for n in _walk(layout.get("root")):
            if _row_scoped(n, layout, doc) in wanted:
                return True
            props = n.get("props") or {}
            if n.get("type") == "Table":
                data = next((str(props[k]) for k in ("data", "rows", "items") if props.get(k)), "")
                if _entity_of_source(doc, layout, data.strip("{} ").split(".")[0]) in wanted:
                    return True
        return False

    _does = {"db_insert": "creates", "db_update": "updates", "db_delete": "deletes"}
    out: list[str] = []
    seen: set[str] = set()
    for action in page.get("actions") or []:
        label = action if isinstance(action, str) else str(
            (action or {}).get("name") or (action or {}).get("label") or "")
        if not label or label.upper().startswith("FLOW-"):
            continue
        verb = _verb_of(label)
        op = _VERB_DB_OP.get(verb)
        if op and _acts_on_another_thing(label, ent_name):
            # `add_test_to_package` ADDS A TEST, NOT A PACKAGE. The verb is
            # the first word and the object is not read at all, so an
            # association action on a record page was demanding a control
            # that CREATES the record the page is already showing.
            # LabConnect's /packages/[id] was refused eight times for not
            # offering "Create TestPackage" on the package's own detail page,
            # and never composed. `add_package` still reads as a create.
            continue
        if op:
            if op in seen or runs_op(op):
                continue
            wf_name = _workflow_for_op(doc, page, op)
            if not wf_name:
                continue                      # nothing to bind yet — Page↔Workflow's
            if op != "db_insert" and not names_a_record():
                continue                      # no record here to act on — the contract's
            if op == "db_update" and not _somewhere_to_go(doc, page, entity, by_name, ("form", "record")):
                continue                      # an Edit needs a form or record page to go to
            if op == "db_insert" and not _somewhere_to_go(doc, page, entity, by_name, ("form",)):
                continue                      # a Create needs a form page to go to
            seen.add(op)
            wf_id = next((str(w.get("id")) for w in _live(doc.get("workflows"))
                          if str(w.get("name") or w.get("id")) == wf_name), wf_name)
            how = (f"a `rowActions` entry on the Table, or a Button on the {ent_name}'s own page, "
                   f"labelled '{verb.capitalize()} …' bound to {wf_name} ({wf_id})"
                   if op != "db_insert" else
                   f"a Button labelled '{verb.capitalize()} …' that runs {wf_name} ({wf_id}) "
                   f"or navigates to the page whose Form does")
            out.append(f"{route} declares `{label}` on {ent_name}, but nothing composed "
                       f"{_does[op]} a {ent_name} — a control the contract promises is "
                       f"missing, and a page that quietly drops it is not fixed. Add {how}.")
        elif verb in _VIEW_VERBS and "[" not in route and detail_routes:
            if "view" in seen or opens_record():
                continue
            seen.add("view")
            out.append(f"{route} declares `{label}` on {ent_name}, but nothing composed opens "
                       f"a {ent_name} — add a `rowActions` entry (or a Link) that navigates to "
                       f"{sorted(detail_routes)[0]}, or an `onRowClick` on the Table.")
    return out


def page_findings(doc: dict) -> list[dict]:
    """What a page's controls would do — the composer's refusals."""
    """`[{rule, page, detail}]` — everything that would not work.

    Returned as plain dicts rather than `Finding`s so the composer's rejection
    path and the verification edge can share one implementation; the caller
    wraps them in whichever shape it needs.
    """
    out: list[dict] = []
    actions = _action_props()
    workflows = {str(w["id"]) for w in _live(doc.get("workflows")) if w.get("id")}
    layouts = {l.get("page"): l for l in _live(doc.get("pageLayouts"))}

    for page in _live(doc.get("pages")):
        pid = str(page.get("id") or "")
        route = page.get("route") or pid
        layout = layouts.get(pid)

        # A page nothing composed has no schema, so its route 404s. The run
        # reports the composition failure; without this the Blueprint still
        # claims the page exists and every consumer believes it.
        if not layout:
            out.append({"rule": "page-not-composed", "page": pid,
                        "detail": f"{route} has no composed tree, so the route "
                                  f"cannot render"})
            continue

        declared = {str(s.get("name")) for s in (layout.get("dataSources") or [])
                    if isinstance(s, dict) and s.get("name")}
        # A DIALOG IS NAMED BY ITS OWN `id` PROP — that is the registry's
        # contract for it, and what `opensDialog` points at. Node ids are
        # composition-time and stripped before commit, so a page whose only
        # dialog was declared correctly read as opening nothing.
        node_ids = {str(n.get("id")) for n in _walk(layout.get("root")) if n.get("id")} | {
            str((n.get("props") or {}).get("id"))
            for n in _walk(layout.get("root"))
            if n.get("type") == "Dialog" and (n.get("props") or {}).get("id")}

        for node in _walk(layout.get("root")):
            kind = str(node.get("type"))
            props = node.get("props") or {}

            # A control with no action renders, is clickable, and does nothing —
            # indistinguishable from a broken application, and with no error to
            # diagnose from. Worse than the control not being there.
            # A repeated control takes its action from the item it repeats
            # over, so the template itself carries none. `$item.label` is the
            # planner's own placeholder, substituted per item at plan time.
            templated = str(props.get("label") or "").startswith("$") or \
                bool(node.get("repeat"))
            if kind in _ACTIONABLE and not (set(props) & actions) and not templated:
                label = props.get("label") or props.get("submitLabel") or kind
                out.append({"rule": "control-without-action", "page": pid,
                            "detail": f"{route}: {kind} {label!r} declares no "
                                      f"action — it would do nothing"})

            target = props.get("opensDialog")
            if isinstance(target, str) and target and target not in node_ids:
                out.append({"rule": "dialog-not-defined", "page": pid,
                            "detail": f"{route}: {kind} {props.get('label') or kind!r} opens dialog "
                                      f"{target!r}, which this page does not contain — a control that "
                                      f"opens nothing does nothing; add the Dialog with that id, or bind "
                                      f"the control to a workflow or route"})
            for ref in _workflow_refs(props):
                if ref not in workflows:
                    out.append({"rule": "workflow-not-defined", "page": pid,
                                "detail": f"{route}: targets workflow {ref!r}, "
                                          f"which this application does not "
                                          f"define"})
                    continue
                # A CONTROL MUST RUN A WORKFLOW THAT DOES WHAT IT SAYS. A
                # "Delete" wired to an Update workflow changes the record instead
                # of removing it; an "Edit" wired to the Create workflow adds a
                # second record; nothing a person can see happens, which reads as
                # a broken button. `workflow-not-defined` never catches it — the
                # wrong workflow exists, so the ref resolves. Decided on the DB op
                # the verb names (`db_insert`/`db_update`/`db_delete`), and flagged
                # only when a correctly-typed workflow EXISTS to name: when none
                # does, the missing workflow is the workflow author's to add
                # (Page↔Workflow), and demanding a rebind here would ask the
                # composer for a target that is not there yet.
                _op_of = {"db_insert": "creates", "db_update": "updates", "db_delete": "deletes"}
                expected = _VERB_DB_OP.get(_verb_of(
                    props.get("label") or props.get("submitLabel") or props.get("aria-label")))
                if expected:
                    target = _workflow_by_id(doc, ref)
                    if target is not None and expected not in _workflow_db_ops(target):
                        correct = _workflow_for_op(doc, page, expected)
                        if correct:
                            did = next((_op_of[o] for o in _workflow_db_ops(target) if o in _op_of),
                                       "does not")
                            out.append({"rule": "workflow-verb-mismatch", "page": pid,
                                        "detail": f"{route}: {kind} "
                                                  f"{props.get('label') or props.get('submitLabel') or kind!r} "
                                                  f"{_op_of[expected]}, but runs {target.get('name') or ref} "
                                                  f"({ref}), which {did} — the control does something other than "
                                                  f"what it says, so it looks broken. Bind it to {correct!r}, the "
                                                  f"workflow that {_op_of[expected]} this record."})
                for missing in unsatisfied_inputs(doc, page, layout, node, ref):
                    out.append({"rule": "workflow-inputs-unsatisfied", "page": pid,
                                "detail": f"{route}: {missing}"})

        # A binding with no source behind it renders its own template text.
        #
        # ASKED OF THE BINDER, NOT RE-DERIVED HERE. `dangling_bindings` answers
        # the same question and knows one thing this walker did not: inside a
        # Table or a Repeat, `{{id}}` means this row's id and the renderer
        # resolves it against the row. Reading it as a page-level source
        # refused /tickets twice over `rowHref: "/tickets/{{id}}"` — after the
        # floor had already been taught otherwise, because the rule lived in
        # two places and only one of them learned.
        for finding in search_findings(doc, page, layout):
            out.append({"rule": finding[0], "page": pid, "detail": f"{route}: {finding[1]}"})
        for detail in dependent_option_findings(doc, page, layout):
            out.append({"rule": "dependent-options-unsatisfied", "page": pid, "detail": f"{route}: {detail}"})
        for detail in form_field_findings(doc, page, layout):
            out.append({"rule": "form-field-unknown", "page": pid, "detail": f"{route}: {detail}"})
        for detail in declared_action_findings(doc, page, layout):
            out.append({"rule": "declared-action-without-control", "page": pid, "detail": detail})
        unresolved = set(_dangling(
            {"dataSources": layout.get("dataSources") or [],
             # THE SCREEN'S OWN VALUES ARE A SOURCE. `dangling_bindings` reads
             # `clientState` to decide whether `{{state.x}}` resolves, and a
             # caller that hands it only the fetches makes every screen value
             # look like a binding with nothing behind it — so a correctly
             # composed calculator was refused for reading its own display.
             "clientState": layout.get("clientState") or [],
             "root": layout.get("root")})) - _planner_placeholders()
        for name in sorted(unresolved):
            out.append({"rule": "binding-without-source", "page": pid,
                        "detail": f"{route}: binds {{{{{name}}}}}, which no "
                                  f"data source provides"})

    # WHAT THE CONTROL PUTS ON THE WIRE. The checks above reason about scope —
    # "the row names the record"; this one about the POST body — "the row
    # action sends {id}". Both must hold. After the page loop, since it reads
    # the projected tree (the record carried onto the control).
    from services.blueprint.dispatch_contract import dispatch_findings, field_kind_findings
    out.extend(dispatch_findings(doc))
    out.extend(field_kind_findings(doc))
    return out


# ---------------------------------------------------------------------------
# A WORKFLOW DOES NOT WRITE THE PLATFORM'S CREDENTIALS.
#
# `users` is a platform table (§97): auth owns it, the signup route writes
# `password` and `name`, NextAuth reads them back, and the projector folds a
# Blueprint `passwordHash` INTO the platform's `password` rather than adding a
# column beside it. A workflow step, authored against the Blueprint's field
# names, then writes `passwordHash` — a column the shipped table does not have.
#
# LabConnect (d1bl1nes) shipped exactly that: FLOW-001 wrote
# `passwordHash: "{{password}}"` and FLOW-004 `passwordHash: "$uuid"`, and the
# only thing that noticed was the engine dry run at `assemble`, forty minutes
# into a build, where no repair round can reach it.
#
# Folding the name here would be worse than the failure: `{{password}}` is the
# raw password, the platform's column holds a bcrypt hash, and a silent rename
# would store a plaintext credential that cannot log in. So the credential is
# refused outright — account creation belongs to the platform's signup — and a
# field the projector merely renames is told its real column.
# ---------------------------------------------------------------------------

#: Columns of a platform table that hold a credential, by the name the platform
#: uses and by the names a Blueprint reaches for.
_CREDENTIAL_COLUMNS = {"password", "passwordhash", "hashedpassword",
                       "passwordsalt", "salt"}


def platform_write_findings(doc: dict) -> list[dict]:
    from services.blueprint.projection import (
        _PLATFORM_SYNONYMS, PLATFORM_TABLE_SOURCES,
    )

    out: list[dict] = []
    for wf in _live(doc.get("workflows")):
        for st in wf.get("steps") or []:
            if not isinstance(st, dict):
                continue
            cfg = st.get("config") or {}
            if cfg.get("actionType") not in ("db_insert", "db_update"):
                continue
            table = str(cfg.get("table") or "").lower()
            if table not in PLATFORM_TABLE_SOURCES:
                continue
            values = cfg.get("values") if isinstance(cfg.get("values"), dict) else {}
            synonyms = _PLATFORM_SYNONYMS.get(table, {})
            where = f"{wf.get('name') or wf.get('id')}, step {st.get('key')!r}"
            for column in sorted(str(k) for k in values):
                folded = column.lower().replace("_", "")
                if folded in _CREDENTIAL_COLUMNS:
                    out.append({"rule": "platform-credential-write", "page": str(wf.get("id")),
                                "detail": f"{where}: sets {column!r} on the platform's {table!r} "
                                          f"table. The platform owns the credential — its signup "
                                          f"route hashes the password and NextAuth reads it back — "
                                          f"so a workflow that writes it either names a column the "
                                          f"shipped table does not have, or stores a password the "
                                          f"login cannot verify. Drop it from `values` and let the "
                                          f"account be created through sign-up; write only what the "
                                          f"Blueprint adds to {table!r}."})
                elif folded in synonyms:
                    out.append({"rule": "platform-column-renamed", "page": str(wf.get("id")),
                                "detail": f"{where}: sets {column!r} on the platform's {table!r} "
                                          f"table, which the platform already stores as "
                                          f"{synonyms[folded]!r} — the shipped table has that column "
                                          f"and not this one. Write {synonyms[folded]!r}."})
    return out


def authoring_findings(doc: dict) -> list[dict]:
    """What the engine would refuse in a workflow or rule as written — the
    author's refusals. Kept apart from :func:`page_findings` because a page
    composer cannot fix a workflow: on 2026-09-05 one workflow's `concat(...)`
    refused seven pages that had nothing to do with it."""
    out: list[dict] = []
    out.extend(rule_findings(doc))
    out.extend(expression_findings(doc))
    out.extend(template_findings(doc))
    out.extend(insert_findings(doc))
    out.extend(column_findings(doc))
    out.extend(platform_write_findings(doc))
    # A step reads what no input declares and no earlier step produces — the
    # wire side of the contract (see dispatch_contract). Imported here: that
    # module reads this one's helpers.
    from services.blueprint.dispatch_contract import workflow_ref_findings
    out.extend(workflow_ref_findings(doc))
    return out


def functional_findings(doc: dict) -> list[dict]:
    """Everything, for verification."""
    return page_findings(doc) + authoring_findings(doc)


# ---------------------------------------------------------------------------
# A CONTROL SUPPLIES WHAT ITS WORKFLOW NEEDS, FROM WHAT ITS PAGE HAS IN SCOPE.
#
# A workflow declares `inputs` (contract). A record input is satisfied on a
# detail page of that entity — the page shows the record, and projection
# carries its id on the control — or by an explicit argument. A field input
# is satisfied by a form around the control that collects that field, or by
# an argument. Anything else is a button that fails when pressed, and is
# refused here, with what is missing and where it could come from, so the
# author can put the control where its inputs are.
# ---------------------------------------------------------------------------

def _entity_id_by_name(doc: dict) -> dict:
    return {str(e.get("name") or ""): str(e.get("id") or "")
            for e in _live((doc.get("data") or {}).get("entities"))}


def _route_record_entities(doc: dict, route: str) -> set[str]:
    """The entities a route names through its OWN `[id]` segments.

    `/tools/[id]/request` carries a ToolListing id even though the request it
    submits is a Rental: the id-bearing prefix `/tools/[id]` is the ToolListing
    detail page, and that page declares what the `[id]` is. So the record the
    route holds is not the page's `primaryEntity` (the Rental being created) but
    the entity of the detail page that owns the prefix. Resolving it from that
    sibling page's own `primaryEntity` keeps the answer evidence-based rather
    than parsed from the URL stem. Returns entity ids."""
    by_route = {str(p.get("route") or ""): p for p in _live(doc.get("pages"))}
    out: set[str] = set()
    prefix = ""
    for seg in route.split("/"):
        if not seg:
            continue
        prefix = f"{prefix}/{seg}"
        if not _ROUTE_HAS_ID.search(f"/{seg}"):
            continue
        owner = by_route.get(prefix)
        pe = str((owner.get("data") or {}).get("primaryEntity") or "") if owner else ""
        if pe:
            out.add(pe)
    return out


def _record_in_scope(doc: dict, page: dict, entity: str) -> bool:
    route = str(page.get("route") or "")
    primary = str((page.get("data") or {}).get("primaryEntity") or "")
    by_name = _entity_id_by_name(doc)
    wanted = {entity, by_name.get(entity, "")} - {""}
    if not _ROUTE_HAS_ID.search(route):
        return False
    # A detail route ends with the id (`/records/[id]`); an edit route carries
    # it mid-path (`/records/[id]/edit`). Both hold the record — matching only
    # `endswith("]")` dropped edit pages, whose Save form then read as having no
    # record for its Update workflow to name.
    if primary in wanted:
        return True
    # An action sub-page (`/tools/[id]/request`) is ABOUT the record it creates
    # (Rental) but still holds the record its `[id]` names (ToolListing), which
    # is exactly the record its workflow consumes. The page's `primaryEntity`
    # never sees it — so consult the entity the route itself names.
    return bool(wanted & _route_record_entities(doc, route))


def _form_fields_of(form: dict) -> set[str]:
    """Every field a Form collects: its declarative `fields` (the shape a
    generated form takes — the fields live in props, not in child nodes)
    and any input nodes inside it."""
    names: set[str] = set()
    for f in (form.get("props") or {}).get("fields") or []:
        if isinstance(f, dict) and f.get("name"):
            names.add(str(f["name"]))
        for sub in (f.get("fields") or []) if isinstance(f, dict) else []:
            if isinstance(sub, dict) and sub.get("name"):
                names.add(str(sub["name"]))
    for inner in _walk(form):
        props = inner.get("props") or {}
        name = props.get("name")
        if inner.get("type") in ("Input", "Select", "Textarea", "Checkbox", "DatePicker", "Field", "Combobox", "MultiSelect") and name:
            names.add(str(name))
        elif inner.get("type") == "FileUpload":
            # A file input is not typed by hand: a FileUpload provides the URL
            # column (its `name`, default "file") and, via the companion
            # fields, the file name and mime type. So a Form holding a
            # FileUpload named `fileUrl` satisfies `fileUrl`/`fileName`, which a
            # text field for a URL never should.
            for key in ("name", "filenameField", "mimeTypeField"):
                v = props.get(key)
                if v:
                    names.add(str(v))
    return names


def _form_chooses(doc: dict, layout: dict, control: dict, name: str,
                  wanted: set[str]) -> bool:
    """A Form that lets the person pick the record supplies it.

    An intake form's property is not a record the screen already holds — it
    is chosen on the form, from the list of properties. That is a select
    field named for the input whose options come from a source listing that
    entity: `interaction.optionsFrom.source` on a declarative field, or
    `optionsFrom.source` on a Select node inside the Form. The rule accepted
    only records the page holds, rows and repeats and `args`, so every
    intake form on one real build — new refund case, guest request, new
    support case, new property, new user — was refused for "nothing there
    names one" while the form plainly asked for it.
    """
    form = _form_around(layout.get("root"), control)
    if form is None:
        return False
    names = {name, f"{name}Id", f"{name}_id"}
    for f in (form.get("props") or {}).get("fields") or []:
        if not isinstance(f, dict) or str(f.get("name") or "") not in names:
            continue
        of = (f.get("interaction") or {}).get("optionsFrom") if isinstance(f.get("interaction"), dict) else None
        of = of if isinstance(of, dict) else f.get("optionsFrom")
        if isinstance(of, dict) and _entity_of_source(doc, layout, str(of.get("source") or "")) in wanted:
            return True
    for inner in _walk(form):
        props = inner.get("props") or {}
        if inner.get("type") in ("Select", "Combobox") and str(props.get("name") or "") in names:
            of = props.get("optionsFrom")
            if isinstance(of, dict) and _entity_of_source(doc, layout, str(of.get("source") or "")) in wanted:
                return True
    return False


def _form_around(root: Any, target: dict) -> dict | None:
    """The nearest Form holding `target`, or `target` when it is the Form."""
    if target.get("type") == "Form":
        return target

    def walk(node: Any, form: dict | None):
        if not isinstance(node, dict):
            return None
        here = node if node.get("type") == "Form" else form
        for child in node.get("children") or []:
            if child is target:
                return here
            found = walk(child, here)
            if found is not None:
                return found
        return None
    return walk(root, None)


def _form_fields_around(root: Any, target: dict) -> set[str] | None:
    """The field names collected by the nearest Form holding `target` — or by
    `target` itself when it is the Form — or None when no Form does."""
    if target.get("type") == "Form":
        return _form_fields_of(target)

    def walk(node: Any, fields: set | None):
        if not isinstance(node, dict):
            return None
        here = _form_fields_of(node) if node.get("type") == "Form" else fields
        if node is target:
            return here
        for child in node.get("children") or []:
            found = walk(child, here)
            if found is not None or (isinstance(child, dict) and child is target):
                return found if found is not None else here
        return None
    return walk(root, None)


def _reaches(doc: dict, page: dict, entity: str) -> str | None:
    """A detail page reaches the records its record links to: a write-off's
    page reaches the case it belongs to through `caseId`. Returns the
    foreign-key field on the page's entity, or None."""
    primary = str((page.get("data") or {}).get("primaryEntity") or "")
    by_name = _entity_id_by_name(doc)
    wanted = {entity, by_name.get(entity, "")} - {""}
    if not str(page.get("route") or "").endswith("]") or not primary:
        return None
    for rel in _live((doc.get("data") or {}).get("relationships")):
        if str(rel.get("from")) == primary and str(rel.get("to")) in wanted and rel.get("fromField"):
            return str(rel["fromField"])
    return None


def _entity_of_source(doc: dict, layout: dict, name: str) -> str | None:
    for src in layout.get("dataSources") or []:
        if isinstance(src, dict) and src.get("name") == name:
            ent = _entity_by_ref(doc, str(src.get("entity") or ""))
            return str((ent or {}).get("id") or src.get("entity") or "") or None
    return None


def _row_scoped(control: dict, layout: dict, doc: dict) -> str | None:
    """A Table's row actions carry the row, and a control inside a repeated
    item carries that item: the entity of the source the Table or Repeat
    reads is in scope. Returns that entity's id or None."""
    if control.get("type") == "Table":
        props = control.get("props") or {}
        # The row source can arrive under any of the Table's data-prop names.
        # `Table.schema.ts` accepts `data`, `rows` AND `items`, the a2ui composer
        # emits `rows` on a list table, and the converter carries whichever it
        # was given. Reading only `data` here made the validator blind to a
        # perfectly-composed table — a rowAction over `rows: "{{tasks}}"` was
        # refused for "nothing names a task" when the row plainly does. Read the
        # same prop names the schema and converter treat as the row source.
        data = next((str(props[p]) for p in ("data", "rows", "items")
                     if props.get(p)), "")
        return _entity_of_source(doc, layout, data.strip("{} ").split(".")[0])
    # Inside a Repeat (or any node repeating over a source), the item is the
    # record — an Approve button drawn once per pending case.
    def holder(node, target):
        if not isinstance(node, dict):
            return None
        for child in node.get("children") or []:
            if child is target or holder(child, target) is not None:
                rep = node.get("repeat") or ((node.get("props") or {}).get("source") if node.get("type") == "Repeat" else None)
                if isinstance(rep, dict):
                    rep = rep.get("source") or rep.get("items")
                if isinstance(rep, str) and rep:
                    return rep.strip("{} ").split(".")[0]
                inner = holder(child, target)
                if inner:
                    return inner
                return "" if child is target else None
        return None
    source = holder(layout.get("root"), control)
    return _entity_of_source(doc, layout, source) if source else None


def _ancestry(root: Any, target: dict) -> str:
    """`Stack > Card > Row` — where the control sits, for the refusal."""
    def walk(node, path):
        if not isinstance(node, dict):
            return None
        for child in node.get("children") or []:
            if child is target:
                return path + [str(node.get("type"))]
            found = walk(child, path + [str(node.get("type"))])
            if found:
                return found
        return None
    chain = walk(root, [])
    return " > ".join(chain[-4:]) if chain else "the page root"


def _session_filled_fields(doc: dict) -> set[str]:
    """Field names the RUNTIME supplies from the session, so a Form must NOT be
    asked to collect them.

    ``security.ownershipRules`` already declares them, and the projection
    (``ownership_rules``) + the generated runtime read the same manifest: a
    ``scope`` rule (``ownerId``, ``organisationId``, …) is filled from the
    session and becomes a row filter; an ``attribution`` rule
    (``createdByUserAccountId``, ``signerUserAccountId``, …) stamps who acted,
    also from the session. A create form that ran ``Create Vessel Profile`` was
    refused for not collecting ``organisationId`` — the caller's own tenant,
    which no user types. Consulting the contract's own manifest, rather than a
    hardcoded field-name allowlist, keeps the check in step with what the
    runtime actually provides."""
    sec = doc.get("security") or {}
    return {
        str(r.get("column"))
        for r in (sec.get("ownershipRules") or [])
        if isinstance(r, dict) and r.get("kind") in ("scope", "attribution") and r.get("column")
    }


def _session_filled_records(doc: dict, page: dict) -> set[str]:
    """Record-input names the RUNTIME supplies from the session, so a Form on
    this page must NOT be asked to name them.

    The record analog of :func:`_session_filled_fields`. A KYC intake form
    (`/kyc-verifications/new`) runs a workflow needing a ``member`` record — but
    that member is the signed-in person filling it in about themselves, never a
    record the screen displays or the user picks. The page's own primary entity
    (``KycVerification``) carries a ``scope``/``user`` ownership rule on
    ``memberId``: the runtime stamps that column from the session, exactly as it
    fills a ``scope`` field. A ``memberId`` column therefore supplies a
    ``member`` record. Scoping this to ownership rules on THIS page's primary
    entity keeps it tight — a KYC officer approving *someone else's* verification
    (primary ``KycVerification``, no ``member`` record input) is untouched, and a
    page whose primary has no such rule still must name the record."""
    primary = str((page.get("data") or {}).get("primaryEntity") or "")
    id_to_name = {str(e.get("id")): str(e.get("name") or "")
                  for e in _live((doc.get("data") or {}).get("entities"))}
    primary_names = {primary, id_to_name.get(primary, "")} - {""}
    out: set[str] = set()
    for r in (doc.get("security") or {}).get("ownershipRules") or []:
        if not isinstance(r, dict) or r.get("kind") not in ("scope", "attribution"):
            continue
        if str(r.get("entity") or "") not in primary_names:
            continue
        col = str(r.get("column") or "")
        out.add(col)
        for suf in ("Id", "_id", "ID"):
            if col.endswith(suf) and len(col) > len(suf):
                out.add(col[: -len(suf)])
    return out


_TEMPLATE_NAME = re.compile(r"\{\{\s*([A-Za-z_][\w]*)\s*\}\}")


def _inputs_a_step_writes(wf: dict) -> set[str]:
    """Input names a db_insert/db_update step templates into its `values` —
    exactly the set the engine's dry run resolves against the payload."""
    names: set[str] = set()
    for st in wf.get("steps") or []:
        cfg = (st or {}).get("config") or {}
        if cfg.get("actionType") not in ("db_insert", "db_update"):
            continue
        values = cfg.get("values") if isinstance(cfg.get("values"), dict) else {}
        for ref in values.values():
            if isinstance(ref, str):
                names.update(_TEMPLATE_NAME.findall(ref))
    return names


def unsatisfied_inputs(doc: dict, page: dict, layout: dict, control: dict,
                       workflow_id: str) -> list[str]:
    """What the control cannot supply for the workflow it runs."""
    wf = next((w for w in _live(doc.get("workflows")) if w.get("id") == workflow_id), None)
    if not wf:
        return []
    props = control.get("props") or {}
    args = props.get("args") if isinstance(props.get("args"), dict) else {}
    label = props.get("label") or props.get("submitLabel") or control.get("type")
    session_filled = _session_filled_fields(doc)
    session_records = _session_filled_records(doc, page)
    out: list[str] = []
    fields = None
    written = _inputs_a_step_writes(wf)
    for inp in wf.get("inputs") or []:
        # OPTIONAL IS NOT THE SAME AS UNUSED. This skipped every optional
        # input, while the engine's dry run (templates/runtime/workflows/
        # dry-run.ts) refuses any `{{name}}` a step writes that the payload
        # leaves empty — optional or not. So a form passed composition and
        # failed `assemble` for the same field: Neighbourhood Kit's "Add
        # Listing" never collected latitude/longitude, and "Submit Decision"
        # never collected agreedStartDate/agreedEndDate (UAT, 2026-09-18),
        # found only after the pages were paid for. An optional input a step
        # writes must be collectable; one nothing writes may still be left out.
        if not inp.get("required", True) and str(inp.get("name") or "") not in written:
            continue
        name = str(inp.get("name") or "")
        if name in args:
            continue
        if name in session_filled:
            # The runtime fills this from the session (an ownership `scope` /
            # `attribution` column); asking a Form to collect the caller's own
            # organisation or identity is wrong, so it is not "unsatisfied".
            continue
        if inp.get("kind") == "record":
            entity = str(inp.get("entity") or "")
            if _record_in_scope(doc, page, entity) or _reaches(doc, page, entity):
                continue
            if name in session_records:
                # The signed-in person is this record (a member submitting their
                # own KYC); the runtime stamps it from the session, so a Form
                # must not be asked to name it.
                continue
            by_name = _entity_id_by_name(doc)
            row_entity = _row_scoped(control, layout, doc)
            if row_entity and row_entity in {entity, by_name.get(entity, "")}:
                continue
            if _form_chooses(doc, layout, control, name, {entity, by_name.get(entity, "")} - {""}):
                continue
            ent_name = next((e.get("name") for e in _live((doc.get("data") or {}).get("entities"))
                             if e.get("id") == entity), entity)
            out.append(f"{control.get('type')} {label!r} (inside {_ancestry(layout.get('root'), control)}) "
                       f"runs {wf.get('name') or workflow_id} ({workflow_id}), which needs a {ent_name} "
                       f"record ({name!r}); nothing there names one — put it on the {ent_name} detail "
                       f"page, or make it a `rowActions` entry of a Table whose `data` lists {ent_name}, "
                       f"or a control inside a `Repeat` over a {ent_name} source, or pass {name!r} in `args`")
        elif inp.get("kind") == "field":
            if control.get("type") == "Table":
                out.append(f"Table {label!r} runs {wf.get('name') or workflow_id} ({workflow_id}), "
                           f"which needs the field {name!r}; a table collects no fields — a Button "
                           f"that navigates to the page whose Form collects them is the control here")
                continue
            if fields is None:
                fields = _form_fields_around(layout.get("root"), control)
            if fields is not None and name in fields:
                continue
            out.append(f"{control.get('type')} {label!r} runs {wf.get('name') or workflow_id} "
                       f"({workflow_id}), which needs the field {name!r}; "
                       + ("no Form around the control collects it — add a field named "
                          f"{name!r} to that Form" if fields is not None else
                          f"the control is in no Form — put it in a Form whose fields include {name!r}")
                       + (f", or, when the control itself is the answer (an Approve button is the "
                          f"decision), pass it as a constant: `args: {{\"{name}\": ...}}`"))
    return out


# ---------------------------------------------------------------------------
# A SEARCH BOX SEARCHES THE PAGE'S LIST, AND THE LIST HAS SOMETHING TO SEARCH.
#
# `Input type="search"` writes `q`; the page passes `q` to its list source;
# the searchable-columns manifest says which columns match. Either half
# missing is a search box that finds nothing and looks broken — a page with
# no list, or an entity with no text column — and is refused with which.
# ---------------------------------------------------------------------------

def _list_sources(layout: dict) -> list[dict]:
    return [s for s in (layout.get("dataSources") or [])
            if isinstance(s, dict) and (s.get("op") in (None, "list"))]


def _entity_by_ref(doc: dict, ref: str) -> dict | None:
    for e in _live((doc.get("data") or {}).get("entities")):
        if ref in (e.get("id"), e.get("name")):
            return e
    return None


def search_findings(doc: dict, page: dict, layout: dict) -> list[tuple[str, str]]:
    boxes = [n for n in _walk(layout.get("root"))
             if n.get("type") == "Input" and (n.get("props") or {}).get("type") == "search"]
    if not boxes:
        return []
    lists = _list_sources(layout)
    if not lists:
        return [("search-without-source",
                 "has a search box and no list source — nothing on this page can be "
                 "searched; give the page a list source, or drop the box")]
    from services.blueprint.projection import searchable_columns
    columns = searchable_columns(doc)
    out = []
    for src in lists:
        ent = _entity_by_ref(doc, str(src.get("entity") or ""))
        name = (ent or {}).get("name") or str(src.get("entity") or "")
        if name and not columns.get(name) and not columns.get(name.lower()):
            fields = [f.get("name") for f in (ent or {}).get("fields") or []][:6]
            out.append(("search-without-columns",
                        f"searches {name}, which has no text column to search "
                        f"(its fields: {', '.join(map(str, fields))}) — a text field "
                        f"on {name} is what a search needs"))
    return out


# ---------------------------------------------------------------------------
# A DEPENDENT SELECT DEPENDS ON A SIBLING IT HAS, MATCHED ON A COLUMN THAT IS.
# ---------------------------------------------------------------------------

def _source_entity(doc: dict, layout: dict, source: str) -> dict | None:
    for s in layout.get("dataSources") or []:
        if isinstance(s, dict) and s.get("name") == source:
            return _entity_by_ref(doc, str(s.get("entity") or ""))
    return None


def dependent_option_findings(doc: dict, page: dict, layout: dict) -> list[str]:
    out = []
    for node in _walk(layout.get("root")):
        props = node.get("props") or {}
        of = props.get("optionsFrom") if isinstance(props.get("optionsFrom"), dict) else None
        dep = (of or {}).get("dependsOn") if of else None
        if not isinstance(dep, dict):
            continue
        label = props.get("label") or props.get("name") or node.get("type")
        siblings = _form_fields_around(layout.get("root"), node)
        field, column = str(dep.get("field") or ""), str(dep.get("column") or "")
        if siblings is None:
            out.append(f"{node.get('type')} {label!r} depends on {field!r} but sits in no Form")
        elif field not in siblings:
            out.append(f"{node.get('type')} {label!r} depends on {field!r}, which is not a field "
                       f"of its Form (fields: {', '.join(sorted(siblings)) or 'none'})")
        ent = _source_entity(doc, layout, str(of.get("source") or ""))
        if ent is not None and column not in {str(f.get("name")) for f in ent.get("fields") or []}:
            out.append(f"{node.get('type')} {label!r} is matched on {column!r}, which "
                       f"{ent.get('name')} does not have")
    return out


# ---------------------------------------------------------------------------
# A RULE'S EFFECTS LAND ON FIELDS THE ENTITY HAS. A condition-action rule
# that hides `amountDue` on an entity with no such field would fire on
# nothing and read as a rule that does not work.
# ---------------------------------------------------------------------------

def rule_findings(doc: dict) -> list[dict]:
    out: list[dict] = []
    entities = {str(e.get("id")): e for e in _live((doc.get("data") or {}).get("entities"))}
    for rule in _live(doc.get("businessRules")):
        if rule.get("kind") != "condition_action":
            continue
        rid = str(rule.get("id") or "")
        ent = entities.get(str(rule.get("entity") or ""))
        if ent is None:
            out.append({"rule": "rule-without-entity", "page": rid,
                        "detail": f"{rule.get('name') or rid} has effects but names no entity "
                                  f"this application defines"})
            continue
        fields = {str(f.get("name")) for f in ent.get("fields") or []}
        for action in list(rule.get("then") or []) + list(rule.get("otherwise") or []):
            field = str((action or {}).get("field") or "")
            if field and field not in fields:
                out.append({"rule": "rule-field-unknown", "page": rid,
                            "detail": f"{rule.get('name') or rid} acts on {field!r}, which "
                                      f"{ent.get('name')} does not have (fields: "
                                      f"{', '.join(sorted(fields))})"})
    return out


# ---------------------------------------------------------------------------
# AN EXPRESSION IS READ BY THE ENGINE'S PARSER BEFORE A PERSON PRESSES THE
# BUTTON. A condition written in JavaScript (`==`, `&&`) is refused at run
# time by the FEEL dialect; refused here, the author is told.
# ---------------------------------------------------------------------------

def _expressions(doc: dict) -> list[tuple[str, str, str]]:
    """(id, where, expression) for every condition the engine will parse."""
    # KEYED BY POSITION, NOT BY ID. A proposal has no id until it is applied,
    # so every rule the author sent shared the key "None/when" and one rule's
    # parse error was reported against all thirty of them.
    out = []
    for n, wf in enumerate(_live(doc.get("workflows"))):
        for m, step in enumerate(wf.get("steps") or []):
            if not isinstance(step, dict):
                continue
            cfg = step.get("config") or {}
            expr = cfg.get("expression") or cfg.get("condition")
            if isinstance(expr, str) and expr.strip():
                out.append((f"workflow#{n}/{step.get('key') or step.get('id') or m}",
                            f"{wf.get('name') or wf.get('id')}, step {step.get('key') or step.get('id')!r}", expr))
    for n, rule in enumerate(_live(doc.get("businessRules"))):
        if rule.get("kind") == "condition_action" and isinstance(rule.get("when"), str) and rule["when"].strip():
            out.append((f"rule#{n}/when", f"rule {rule.get('name') or rule.get('id')}", rule["when"]))
    return out


def expression_findings(doc: dict) -> list[dict]:
    items = _expressions(doc)
    if not items:
        return []
    from services.blueprint.feel_check import check_expressions
    errors = check_expressions([(i, e) for i, _w, e in items])
    out = []
    for i, where, expr in items:
        if i in errors:
            out.append({"rule": "expression-invalid", "page": i.split("/")[0],
                        "detail": f"{where}: the engine cannot parse {expr!r} — {errors[i]}. "
                                  f"Conditions are FEEL: `=` not `==`, `and`/`or`/`not`, field names "
                                  f"without braces (`caseType`, never `input.caseType`), membership as "
                                  f"`stage in [\"A\",\"B\"]` with square brackets, never parentheses"})
    return out


# ---------------------------------------------------------------------------
# A TEMPLATE NAMES SOMETHING THE ENGINE HOLDS. The engine seeds the trigger's
# input as flat variables (`{{title}}`), stores each step's output under the
# step's key (`{{insert_case.id}}`), and `set_variable` steps under their
# `variableName`; `$now`, `$today` and `$user.id` are whole-value sentinels.
# A workflow wrote `{{now}}`, `{{currentUser.id}}`, `{{vars.approvalState}}`
# and `{{steps.insert_case.output.id}}` — none of which exists — and its
# insert wrote blanks where it wrote anything.
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{\{\s*([\w.\[\]|:]+)\s*\}\}")
_WRONG_ROOTS = {
    "now": "the sentinel `$now` as the whole value",
    "today": "the sentinel `$today` as the whole value",
    "currentUser": "the sentinel `$user.id` as the whole value",
    "user": "the sentinel `$user.id` as the whole value",
    "input": "the field name alone — `{{title}}`, not `{{input.title}}`",
    "vars": "the variable name alone — `{{approvalState}}`",
    "steps": "the step key and field — `{{insert_case.id}}`",
    "sequence": "nothing — the engine has no sequences; number records in the data model",
}


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def template_findings(doc: dict) -> list[dict]:
    out: list[dict] = []
    for wf in _live(doc.get("workflows")):
        steps = [st for st in wf.get("steps") or [] if isinstance(st, dict)]
        inputs = {str(i.get("name")) for i in wf.get("inputs") or [] if i.get("name")}
        keys = {str(st.get("key") or st.get("id")) for st in steps}
        variables = {str((st.get("config") or {}).get("variableName")) for st in steps
                     if (st.get("config") or {}).get("variableName")}
        known = inputs | keys | variables
        seen: set[str] = set()
        for st in steps:
            for text in _strings(st.get("config") or {}):
                for ref in _TEMPLATE_RE.findall(text):
                    root = ref.split(".")[0].split("[")[0].split("|")[0]
                    if root in known or (root, str(st.get("key"))) in seen:
                        continue
                    seen.add((root, str(st.get("key"))))
                    if root in _WRONG_ROOTS:
                        fix = _WRONG_ROOTS[root]
                        out.append({"rule": "template-unknown", "page": str(wf.get("id")),
                                    "detail": f"{wf.get('name') or wf.get('id')}, step {st.get('key')!r}: "
                                              f"{{{{{ref}}}}} names nothing the engine holds — write {fix}"})
                    else:
                        out.append({"rule": "template-unknown", "page": str(wf.get("id")),
                                    "detail": f"{wf.get('name') or wf.get('id')}, step {st.get('key')!r}: "
                                              f"{{{{{ref}}}}} names nothing the engine holds — an input field "
                                              f"({', '.join(sorted(inputs)) or 'none'}), a step key "
                                              f"({', '.join(sorted(keys)) or 'none'}), or a variable a "
                                              f"set_variable step set ({', '.join(sorted(variables)) or 'none'})"})
    return out


# ---------------------------------------------------------------------------
# AN INSERT SUPPLIES WHAT THE TABLE REQUIRES. A required column the data model
# declares and the insert omits fails at the database, after the row's other
# values are gone. Create Case wrote the case number in a db_update after the
# insert; the column is NOT NULL, so the insert never happened.
# ---------------------------------------------------------------------------

def _entity_for_table(doc: dict, table: str | None) -> dict | None:
    if not table:
        return None
    t = str(table).strip().lower()
    for e in (doc.get("data") or {}).get("entities") or []:
        if str(e.get("table") or "").lower() == t or str(e.get("name") or "").lower() == t:
            return e
    return None


def insert_findings(doc: dict) -> list[dict]:
    out: list[dict] = []
    for wf in _live(doc.get("workflows")):
        for st in wf.get("steps") or []:
            if not isinstance(st, dict):
                continue
            cfg = st.get("config") or {}
            if cfg.get("actionType") != "db_insert":
                continue
            entity = _entity_for_table(doc, cfg.get("table"))
            if entity is None:
                continue
            values = cfg.get("values") if isinstance(cfg.get("values"), dict) else {}
            given = {str(k) for k in values}
            missing = [f["name"] for f in entity.get("fields") or []
                       if f.get("required") and not f.get("primaryKey") and f.get("name") not in given
                       and not (f.get("references") and f["name"] in ("createdById", "updatedById"))]
            if missing:
                out.append({"rule": "insert-missing-required", "page": str(wf.get("id")),
                            "detail": f"{wf.get('name') or wf.get('id')}, step {st.get('key')!r}: inserts into "
                                      f"{entity.get('name')} without {', '.join(repr(m) for m in missing)}, which "
                                      f"the data model requires — supply each in `values`: an input by name, "
                                      f"`$now` for a time, `$user.id` for the actor, `$uuid` for a reference "
                                      f"nothing else supplies, a literal for a starting state"})
    return out


# ---------------------------------------------------------------------------
# A WRITE NAMES COLUMNS THE ENTITY HAS. The mirror of insert-missing-required:
# when a field is renamed or removed, a db step that still writes or filters it
# names a column that is gone, and the action fails at the database — the exact
# dependency a field change must not silently break. Judged only against an
# entity with a declared field list, ignoring the system columns the engine
# fills (`id`, `$now` timestamps), so it flags a genuinely absent column, not a
# managed one.
# ---------------------------------------------------------------------------

_SYSTEM_COLUMNS = {"id", "createdat", "updatedat", "deletedat",
                   "created_at", "updated_at", "deleted_at",
                   "createdbyid", "updatedbyid"}


def column_findings(doc: dict) -> list[dict]:
    out: list[dict] = []
    for wf in _live(doc.get("workflows")):
        for st in wf.get("steps") or []:
            if not isinstance(st, dict):
                continue
            cfg = st.get("config") or {}
            if cfg.get("actionType") not in ("db_insert", "db_update", "db_delete"):
                continue
            entity = _entity_for_table(doc, cfg.get("table"))
            if entity is None:
                continue
            fields = {str(f.get("name")) for f in entity.get("fields") or [] if f.get("name")}
            if not fields:                       # cannot judge without a field list
                continue
            columns: set[str] = set()
            for key in ("values", "where"):
                block = cfg.get(key)
                if isinstance(block, dict):
                    columns |= {str(k) for k in block}
            unknown = sorted(
                c for c in columns
                if c not in fields and c.lower().replace("_", "") not in _SYSTEM_COLUMNS
            )
            if unknown:
                out.append({"rule": "workflow-column-unknown", "page": str(wf.get("id")),
                            "detail": f"{wf.get('name') or wf.get('id')}, step {st.get('key')!r}: writes or "
                                      f"filters {', '.join(repr(c) for c in unknown)}, which {entity.get('name')} "
                                      f"does not have (fields: {', '.join(sorted(fields))}) — a field that was "
                                      f"renamed or removed leaves the step naming a column that is gone, and the "
                                      f"action fails at the database. Point it at a column the entity has, or "
                                      f"restore the field."})
    return out


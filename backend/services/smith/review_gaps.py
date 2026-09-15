"""Page↔Workflow gaps a verify can settle itself.

A page declares what a person can do there (`actions: [view, edit, delete]`);
a workflow is what a control runs. When a page declares a CRUD verb and no
workflow on its primary entity performs that operation, every control for it
is wired wrong or not at all: the composer reaches for the nearest write
workflow (a Delete that runs Update), the completeness check refuses the page,
and the review loop spends every round re-composing a page that cannot be
composed correctly — /master-data was refused fourteen times for a Delete that
had no delete workflow to run.

The gap is the workflow author's, and the workflow node is not in a build-phase
plan, so the review loop settles it here, deterministically: a CRUD workflow
on the entity is mechanical (one `db_*` step on the entity's table, the record
and the writable fields as inputs), the same shape the workflow agent authors
and the same catalog check it is held to. Declared into the Blueprint — the
source of truth — before the page is re-composed, so the composer has the
correct target to bind and the verb-mismatch check can name it.

Nothing non-CRUD is guessed: a page whose `approve` has no workflow is reported,
not invented.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from services.blueprint.functional_completeness import (
    _VERB_DB_OP, _verb_of, _workflow_for_op, _live, _workflow_db_ops,
    _workflow_targets_entity, authoring_findings,
)
from services.blueprint.projection import to_snake

logger = logging.getLogger(__name__)

#: Columns the platform manages; never an input a person supplies.
_MANAGED = frozenset({"id", "createdat", "updatedat", "deletedat",
                      "created_at", "updated_at", "deleted_at"})

_OP_WORD = {"db_insert": "Create", "db_update": "Update", "db_delete": "Delete"}
_OP_PAST = {"db_insert": "created", "db_update": "updated", "db_delete": "deleted"}


@dataclass
class Gap:
    """One page action with no workflow that performs it."""
    entity_id: str
    entity_name: str
    op: str                                   # db_insert | db_update | db_delete
    pages: list[str] = field(default_factory=list)      # page ids declaring it
    routes: list[str] = field(default_factory=list)
    verbs: list[str] = field(default_factory=list)      # the words the pages used

    @property
    def workflow_name(self) -> str:
        return f"{_OP_WORD[self.op]} {self.entity_name}"


def crud_gaps(doc: Mapping[str, Any]) -> list[Gap]:
    """Every (entity, op) some live page declares and no workflow performs —
    keyed on the DB operation the verb names, one gap per entity/op however
    many pages declare it. Empty when every declared CRUD verb has its
    workflow."""
    ent_name = {str(e.get("id")): str(e.get("name") or e.get("id"))
                for e in _live((doc.get("data") or {}).get("entities"))}
    gaps: dict[tuple[str, str], Gap] = {}
    for page in _live(doc.get("pages")):
        entity = str((page.get("data") or {}).get("primaryEntity") or "")
        if not entity:
            continue
        for action in page.get("actions") or []:
            label = action if isinstance(action, str) else str(
                (action or {}).get("name") or (action or {}).get("label") or "")
            if label.upper().startswith("FLOW-"):
                continue                      # bound by id; checked elsewhere
            op = _VERB_DB_OP.get(_verb_of(label))
            if not op or _workflow_for_op(dict(doc), dict(page), op):
                continue
            g = gaps.setdefault((entity, op), Gap(
                entity_id=entity, entity_name=ent_name.get(entity, entity), op=op))
            pid = str(page.get("id") or "")
            if pid and pid not in g.pages:
                g.pages.append(pid)
                g.routes.append(str(page.get("route") or pid))
            if label not in g.verbs:
                g.verbs.append(label)
    return list(gaps.values())


def _entity(doc: Mapping[str, Any], entity_id: str) -> dict:
    return next((e for e in _live((doc.get("data") or {}).get("entities"))
                 if str(e.get("id")) == entity_id), {})


def _table_for(doc: Mapping[str, Any], entity_id: str) -> str:
    """The table the entity's other workflows already write, else the entity's
    declared table, else the projection's own derivation from the name."""
    for w in _live(doc.get("workflows")):
        if not _workflow_targets_entity(dict(doc), w, entity_id):
            continue
        for st in w.get("steps") or []:
            cfg = (st or {}).get("config") or {}
            if str(cfg.get("actionType") or "").startswith("db_") and cfg.get("table"):
                return str(cfg["table"])
    ent = _entity(doc, entity_id)
    return str(ent.get("table") or to_snake(ent.get("name") or "entity"))


def _writable_fields(ent: Mapping[str, Any]) -> list[dict]:
    out = []
    for f in ent.get("fields") or []:
        name = str((f or {}).get("name") or "")
        if not name or name.lower() in _MANAGED:
            continue
        if (f or {}).get("references") or (f or {}).get("foreignKey"):
            continue
        out.append({"name": name, "type": str(f.get("type") or "string")})
    return out


def crud_workflow(doc: Mapping[str, Any], gap: Gap) -> dict:
    """The Blueprint workflow that closes `gap`: trigger → one db step on the
    entity → end. Inputs are what a control must supply — the record for an
    update/delete, the writable fields for a create/update — so the composer's
    input check holds it to the same bar as an authored one."""
    ent = _entity(doc, gap.entity_id)
    table = _table_for(doc, gap.entity_id)
    name = gap.workflow_name
    inputs: list[dict] = []
    if gap.op in ("db_update", "db_delete"):
        inputs.append({"name": "record", "kind": "record", "entity": gap.entity_id,
                       "required": True,
                       "description": f"The existing {gap.entity_name} being "
                                      f"{_OP_PAST[gap.op]}."})
    fields = _writable_fields(ent)
    if gap.op in ("db_insert", "db_update"):
        for f in fields:
            inputs.append({"name": f["name"], "kind": "field", "type": f["type"],
                           "required": True,
                           "description": f"{f['name']} of the {gap.entity_name}."})
    if gap.op == "db_delete":
        config = {"actionType": "db_delete", "table": table,
                  "where": {"id": "{{record.id}}"}}
    elif gap.op == "db_update":
        config = {"actionType": "db_update", "table": table,
                  "values": {**{f["name"]: "{{%s}}" % f["name"] for f in fields},
                             "updatedAt": "$now"},
                  "where": {"id": "{{record.id}}"}}
    else:
        config = {"actionType": "db_insert", "table": table,
                  "values": {f["name"]: "{{%s}}" % f["name"] for f in fields}}
    step_key = f"do_{gap.op.split('_', 1)[1]}"
    where = ", ".join(gap.routes) or "a page"
    return {
        "name": name,
        "purpose": f"{_OP_WORD[gap.op]} a {gap.entity_name} from {where} — declared "
                   f"by the verify because the page's "
                   f"{'/'.join(gap.verbs) or _OP_WORD[gap.op].lower()} had no "
                   f"workflow that {_OP_PAST[gap.op].rstrip('d')}s one.",
        "status": "PROPOSED",
        "trigger": {"kind": "manual",
                    "detail": f"User chooses {'/'.join(gap.verbs) or _OP_WORD[gap.op].lower()} "
                              f"on a {gap.entity_name} from {where}."},
        "inputs": inputs,
        "launchedFrom": list(gap.pages),
        "steps": [
            {"key": "start", "name": f"Start: {name}", "type": "trigger",
             "config": {"type": "manual"}, "next": [step_key]},
            {"key": step_key, "name": name, "type": "action",
             "entity": gap.entity_id, "config": config, "next": ["done"]},
            {"key": "done", "name": f"End: {gap.entity_name} {_OP_PAST[gap.op]}",
             "type": "end", "next": []},
        ],
    }


def workflow_problems(doc: Mapping[str, Any], body: Mapping[str, Any]) -> list[str]:
    """What the workflow contract would refuse — the catalog's node check and
    the authoring findings, exactly as `check_workflow_steps` holds an agent."""
    from services.catalog import workflow_nodes
    problems = [f"{body.get('name')}/{e}" for e in workflow_nodes().workflow_errors(dict(body))]
    problems.extend(f["detail"] for f in authoring_findings({
        "workflows": [dict(body)], "businessRules": [],
        "data": doc.get("data") or {}}))
    return problems


def settle_crud_gaps(svc: Any, *, emit: Callable[[str, dict], None] | None = None,
                     only_pages: set[str] | None = None) -> dict[str, str]:
    """Declare the workflow for every CRUD gap the Blueprint has (or only those
    touching `only_pages`), save, and return ``{page_id: note}`` — one note per
    page telling its composer what now exists to bind. A gap whose workflow the
    contract would refuse is reported and left; nothing is declared that could
    not be run."""
    notes: dict[str, str] = {}
    said: list[str] = []
    for gap in crud_gaps(svc.doc):
        if only_pages is not None and not (set(gap.pages) & only_pages):
            continue
        verbs = "/".join(gap.verbs) or _OP_WORD[gap.op].lower()
        does = _OP_PAST[gap.op].rstrip("d") + "s"          # creates/updates/deletes
        body = crud_workflow(svc.doc, gap)
        problems = workflow_problems(svc.doc, body)
        if problems:
            logger.warning("[review] cannot declare %s: %s", body["name"],
                           "; ".join(problems[:4]))
            if emit is not None:
                emit("message", {"text":
                    f"{', '.join(gap.routes)} declares {verbs} on {gap.entity_name}, "
                    f"but no workflow {does} one and I couldn't declare it myself: "
                    f"{problems[0]}"})
            continue
        from services.blueprint.ids import natural_key_for
        key = natural_key_for("workflows", body) or body["name"].lower()
        wf = svc.upsert("workflows", body, natural_key=key)
        said.append(f"{wf['name']} ({wf['id']}) — {', '.join(gap.routes)} had a "
                    f"{verbs} with no workflow that {does} a {gap.entity_name}")
        for pid in gap.pages:
            notes[pid] = notes.get(pid, "") + (
                f"\n- The page's {verbs} on {gap.entity_name} now has a workflow to "
                f"run: {wf['name']} ({wf['id']}). Bind that control to it (a Table's "
                f"`rowActions` entry with `workflow: \"{wf['id']}\"`, or a Button on "
                f"the record's own page) and to nothing else.")
    if said:
        svc.save()
        if emit is not None:
            emit("message", {"text": "Declared " + "; ".join(said) + "."})
    return {pid: "Before re-composing, I fixed the Blueprint:" + n
            for pid, n in notes.items()}


__all__ = ["Gap", "crud_gaps", "crud_workflow", "workflow_problems", "settle_crud_gaps"]

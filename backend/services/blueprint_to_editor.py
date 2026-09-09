"""Blueprint artifacts in the shapes the legacy editor endpoints promise.

`/rules` and `/pages` were backed by `project_rules` and `page_definitions`,
tables the Blueprint engine never writes. `/pages` appeared to work only
because `_sync_pages_from_app_model` — reachable from `routers/generate.py`
alone — had happened to run for that project on the legacy path. A
Blueprint-only project has no rows in either table, so both editors opened
empty on an application whose rules and pages were fully specified.

Extending that sync was the obvious move and the wrong one: it copies the
Blueprint into a second store that goes stale the moment the Blueprint
changes, which is the divergence §76 exists to prevent and the same
two-representations defect that has cost this codebase a page tree, a
workflow reference and a set of bindings already.

So the Blueprint answers directly, and the DB rows stay only for what a user
authored by hand through the POST endpoints.

IDS ARE DERIVED, NOT INVENTED. The response models promise a UUID and the
Blueprint carries `RULE-001`. A random id per request would give the editor a
different identity for the same rule on every poll, so it is a uuid5 of the
project and the artifact id — stable across processes, and reversible only in
the sense that the same input always gives the same answer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Namespace for editor-facing ids derived from Blueprint artifacts. Fixed, so
#: the id an editor saw last week is the id it sees today.
_NS = uuid.UUID("6f4a1e2c-3d7b-4c8a-9e1f-2b5d8c7a4e30")


def _id_for(project_id: Any, artifact_id: str) -> uuid.UUID:
    return uuid.uuid5(_NS, f"{project_id}:{artifact_id}")


def _live(items: Any) -> list[dict]:
    return [i for i in (items or [])
            if isinstance(i, dict) and i.get("status") != "SUPERSEDED"]


def _stamp(output_dir: str | Path) -> datetime:
    """When this Blueprint was last written.

    The response models require created_at/updated_at and a Blueprint artifact
    has neither. The file's mtime is the honest answer to "how current is
    this", and it moves when the Blueprint moves — which is what a caller
    polling for changes actually wants to know.
    """
    p = Path(output_dir) / ".forge" / "blueprint" / "current.json"
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.now(tz=timezone.utc)


def rules_from_blueprint(doc: dict, project_id: Any,
                         output_dir: str | Path) -> list[dict]:
    """`businessRules` as RuleResponse-shaped dicts."""
    at = _stamp(output_dir)
    out: list[dict] = []
    for r in _live(doc.get("businessRules")):
        rid = str(r.get("id") or "")
        if not rid:
            continue
        applies = r.get("appliesTo") or []
        out.append({
            "id": _id_for(project_id, rid),
            "project_id": project_id,
            "name": str(r.get("name") or rid),
            # The Blueprint does not classify rules the way the legacy table
            # did. Saying "business" is a smaller claim than picking one of
            # the old enum's members on the strength of an expression string.
            "rule_type": "business",
            "model_name": str(applies[0]) if applies else None,
            "field_name": None,
            # Everything the Blueprint says, so the editor can show the rule
            # rather than just its name — and so nothing is lost in a shape
            # that predates it.
            "config": {
                "blueprintId": rid,
                "statement": r.get("statement"),
                "expression": r.get("expression"),
                "appliesTo": applies,
                "requirements": r.get("requirements") or [],
                "confidence": r.get("confidence"),
            },
            "is_active": r.get("status") != "REJECTED",
            "created_at": at,
            "updated_at": at,
        })
    return out


def pages_from_blueprint(doc: dict, project_id: Any,
                         output_dir: str | Path) -> list[dict]:
    """`pages` as PageResponse-shaped dicts.

    `html` and `css` stay empty: the Blueprint composes a page as a node tree
    in `pageLayouts`, not as markup, and rendering one to HTML here would
    invent a second renderer beside the real one. The route and the name are
    what this endpoint's callers use.
    """
    at = _stamp(output_dir)
    layouts = {l.get("page") for l in _live(doc.get("pageLayouts"))}
    out: list[dict] = []
    for p in _live(doc.get("pages")):
        pid = str(p.get("id") or "")
        if not pid:
            continue
        out.append({
            "id": _id_for(project_id, pid),
            "project_id": project_id,
            "name": str(p.get("name") or pid),
            "route": str(p.get("route") or "/"),
            "html": "",
            "css": "",
            "data_bindings": {
                "blueprintId": pid,
                "pattern": p.get("pattern"),
                "module": p.get("module"),
                "access": p.get("access"),
                "entry": p.get("entry"),
                "presentation": p.get("presentation"),
                "primaryEntity": (p.get("data") or {}).get("primaryEntity"),
                "navigatesTo": p.get("navigatesTo") or [],
                # Whether anything composed a tree for this page. A page with
                # no layout renders nothing, and an editor listing it beside
                # composed pages with no way to tell them apart is how a 404
                # gets mistaken for an empty state.
                "composed": pid in layouts,
            },
            "created_at": at,
            "updated_at": at,
        })
    return out


def derived_ids(doc: dict, project_id: Any,
                section: str) -> dict[uuid.UUID, str]:
    """`{editor uuid: Blueprint artifact id}` for one section.

    Membership, not pattern-matching. A uuid5 is indistinguishable from any
    other uuid by inspection, so the only honest way to ask "did this id come
    from the Blueprint" is to derive them all again and look. That also means
    the answer changes when the Blueprint does — an artifact that has been
    superseded stops claiming its id, which is correct.
    """
    items = _live(doc.get(section))
    return {_id_for(project_id, str(i["id"])): str(i["id"])
            for i in items if i.get("id")}


def app_model_from_blueprint(doc: dict, project_id: Any, output_dir: str | Path) -> dict:
    """Derive the app-model (ERD/editor shape) directly from the Blueprint.

    §76 pattern: the blueprint pipeline projects the app under ``output_dir/app``
    and never writes ``app-model.json``, so ``/app-model`` 404'd forever and the
    Data Model / Workflows / Rules editor tabs sat on "index hasn't been built".
    The Blueprint already carries the full data model, so answer from it rather
    than a store the engine never writes. Shape mirrors what the ERD canvas and
    ``useProjectDataModel`` read: ``database.tables[].columns[]`` (name, type,
    nullable, primaryKey, references) + ``database.enums`` + entity relations.
    """
    data = (doc or {}).get("data", {}) or {}
    entities = [e for e in (data.get("entities") or [])
                if isinstance(e, dict) and e.get("status") != "SUPERSEDED"]
    relationships = [r for r in (data.get("relationships") or []) if isinstance(r, dict)]
    by_id = {e.get("id"): e for e in entities}

    def _table(e: dict) -> str:
        return e.get("table") or (str(e.get("name", "")).lower() + "s")

    tables: list[dict] = []
    enums: list[dict] = []
    for e in entities:
        columns: list[dict] = []
        for f in (e.get("fields") or []):
            if not isinstance(f, dict) or not f.get("name"):
                continue
            col: dict = {
                "name": f["name"],
                "type": f.get("type", "text"),
                # Blueprint marks `required`; the ERD wants `nullable`.
                "nullable": not bool(f.get("required")),
                "primaryKey": bool(f.get("primaryKey")),
            }
            if f.get("unique"):
                col["unique"] = True
            # A relationship whose `from` is this entity+field is a foreign key.
            for r in relationships:
                if r.get("from") == e.get("id") and r.get("fromField") == f["name"]:
                    target = by_id.get(r.get("to"))
                    if target:
                        col["references"] = {"table": _table(target), "column": r.get("toField") or "id"}
                    break
            columns.append(col)
            if f.get("type") == "enum" and f.get("enumValues"):
                enums.append({"name": f"{e.get('name')}.{f['name']}", "values": list(f["enumValues"])})
        relations = []
        for r in relationships:
            if r.get("from") == e.get("id"):
                target = by_id.get(r.get("to"))
                relations.append({
                    "type": str(r.get("kind") or "many_to_one").replace("_", "-"),
                    "target": _table(target) if target else r.get("to"),
                    "foreignKey": r.get("fromField"),
                })
        tables.append({
            "name": _table(e),
            "displayName": e.get("name"),
            "columns": columns,
            "relations": relations,
        })

    # workflows / businessRules / pages live at the Blueprint doc top level.
    return {
        "database": {"tables": tables, "enums": enums},
        "entities": entities,
        "workflows": _live((doc or {}).get("workflows")),
        "businessRules": _live((doc or {}).get("businessRules")),
        "pages": _live((doc or {}).get("pages")),
        "derivedFrom": "blueprint",
        "generatedAt": _stamp(output_dir).isoformat(),
    }

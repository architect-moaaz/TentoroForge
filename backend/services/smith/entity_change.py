"""The data model is a Blueprint section, and Smith can add an entity to it
or retire one.

"Add a Ward entity with a name and a capacity", "we don't need the
Department entity": the build declares entities in `data_model` (names,
tables, relationships) and authors each one's fields in `entity_fields`;
the data layer is projected from them. Nothing in the verb set added or
removed an entity, and the tools of those names wrote a resource registry a
Blueprint-built app does not have.

Add: the ask becomes a requirement; `data_model` is briefed to declare ONE
new entity and its relationships (existing entities are never returned);
`entity_fields` authors its fields; the data layer, entity access and seed
are re-projected. The table reaches the database as a migration on the
next install; screens for it are a separate ask.

Remove: the entity is retired, never deleted, and everything that stood on
it goes with it — its pages (retired, taken off the menu), the workflows
that act on it (retired, their controls off every screen), the
relationships that touch it; a field on another entity that still points
at it is reported, not rewritten.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from services.llm_client import tell
from services.smith.section_change import (
    SectionChangeError, find_named, names, pinned, record_requirement, rerun,
)

logger = logging.getLogger(__name__)


def _entities(doc: dict) -> list[dict]:
    return [e for e in ((doc.get("data") or {}).get("entities") or []) if isinstance(e, dict)]


def _live(doc: dict) -> list[dict]:
    return [e for e in _entities(doc) if e.get("status") != "DEPRECATED"]


def _project_data(svc: Any, app_root: str | None) -> list[str]:
    if not app_root:
        return []
    from services.blueprint.projection import project_data_layer, project_entity_access, project_seed
    files = list(project_data_layer(svc.doc, app_root).get("files") or [])
    for fn in (project_entity_access, project_seed):
        try:
            files += list((fn(svc.doc, app_root) or {}).get("files") or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[entity] %s failed: %s", fn.__name__, exc)
    return sorted(set(files))


def add_entity(svc: Any, request: str, *, app_root: str | None = None, executor: Any = None,
               reasoning: Any = None) -> dict:
    request = (request or "").strip()
    if not request:
        raise SectionChangeError("no entity was described, so there is nothing to add.")
    req = record_requirement(svc, request, owner="data")
    existing = {str(e.get("name") or "").strip().lower() for e in _live(svc.doc)}
    existing_ids = {str(e.get("id")) for e in _entities(svc.doc)}
    brief = (
        "THIS IS A CHANGE to an application that is already built, not a first authoring.\n"
        f"The user asked for ONE new entity: \"{request}\". It satisfies {req.get('id')}.\n"
        f"These entities exist already and are NOT to be returned or renamed: {names(_live(svc.doc))}. "
        "Return exactly ONE entity proposal, for the new one, with `fields: []` as the standing task "
        "says, plus any `relationships` between it and the existing entities."
    )
    def keep(props):
        ents = [p for p in props if p.section == "data.entities"
                and str((p.body or {}).get("name") or "").strip().lower() not in existing
                and str((p.body or {}).get("id") or "") not in existing_ids][:1]
        if not ents:
            return []
        for p in ents:
            p.body = {k: v for k, v in (p.body or {}).items() if k not in ("id", "fields", "labelField")}
            p.body["fields"] = []
        new_name = str(ents[0].body.get("name") or "").strip().lower()
        rels = [p for p in props if p.section == "data.relationships"
                and new_name in (str((p.body or {}).get("from") or "").lower(), str((p.body or {}).get("to") or "").lower())]
        return ents + rels
    props, _ = rerun(svc, "data_model", brief=brief, request=request, interpretation=f"declare an entity: {request}",
                     keep=keep, executor=executor, reasoning=reasoning, app_root=app_root,
                     empty="every entity you returned already exists — return exactly one NEW entity",
                     say=f"Declaring an entity for: {request}.")
    name = str((props[0].body or {}).get("name") or "")
    ent = next((e for e in _live(svc.doc) if str(e.get("name") or "").strip().lower() == name.strip().lower()), None)
    if ent is None:
        raise SectionChangeError("the entity was declared but cannot be found by its name.")
    eid = str(ent["id"])
    steps_brief = (f"This entity was just declared for the user's ask: \"{request}\". Author its fields to "
                   "honour the ask; keep its name and table exactly as declared.")
    def keep_fields(props):
        mine = [p for p in props if p.section == "data.entities"
                and str((p.body or {}).get("name") or "").strip().lower() == name.strip().lower()][:1]
        for p in mine:
            p.body = {k: v for k, v in (p.body or {}).items() if k != "id"}
        others = [p for p in props if p.section in ("data.relationships", "data.constraints")]
        return pinned(svc, mine, "data.entities", eid) + others
    rerun(svc, "entity_fields", brief=steps_brief, request=request, interpretation=f"author the fields of {name}",
          subject=eid, keep=keep_fields, executor=executor, reasoning=reasoning, app_root=app_root,
          empty=f"return the entity {name} with its fields", say=f"Authoring the fields of {name}.")
    ent = next(e for e in _entities(svc.doc) if e["id"] == eid)
    if req.get("id") and req["id"] not in (ent.get("requirements") or []):
        ent["requirements"] = list(ent.get("requirements") or []) + [req["id"]]
        svc.save()
    return {"applied": True, "entity": eid, "name": name, "table": ent.get("table"),
            "fields": [str(f.get("name")) for f in (ent.get("fields") or []) if isinstance(f, dict)],
            "requirement": req.get("id"), "edited_paths": _project_data(svc, app_root)}


def dependents(doc: dict, eid: str) -> dict:
    from services.blueprint.functional_completeness import _workflow_targets_entity
    pages = [p for p in (doc.get("pages") or []) if isinstance(p, dict) and p.get("status") != "DEPRECATED"
             and str((p.get("data") or {}).get("primaryEntity") or "") == eid]
    workflows = [w for w in (doc.get("workflows") or []) if isinstance(w, dict) and w.get("status") != "DEPRECATED"
                 and _workflow_targets_entity(doc, w, eid)]
    rels = [r for r in ((doc.get("data") or {}).get("relationships") or []) if isinstance(r, dict)
            and eid in (str(r.get("from")), str(r.get("to")))]
    pointing = [f"{e.get('name')}.{f.get('name')}" for e in _live(doc) if str(e.get("id")) != eid
                for f in (e.get("fields") or []) if isinstance(f, dict) and str(f.get("references") or "") == eid]
    return {"pages": pages, "workflows": workflows, "relationships": rels, "pointing": pointing}


def _retire_pages(svc: Any, pages: list[dict]) -> list[str]:
    ids = {str(p.get("id")) for p in pages}
    routes = []
    for p in pages:
        p["status"] = "DEPRECATED"
        routes.append(str(p.get("route")))
    for layout in svc.doc.get("pageLayouts") or []:
        if isinstance(layout, dict) and str(layout.get("page")) in ids and layout.get("status") != "SUPERSEDED":
            layout["status"] = "DEPRECATED"
    nav = svc.doc.get("navigation") or {}
    def prune(tree):
        out = []
        for n in tree or []:
            if not isinstance(n, dict):
                continue
            if str(n.get("page") or "") in ids:
                continue
            if n.get("children"):
                n["children"] = prune(n["children"])
                if not n["children"] and not n.get("page"):
                    continue
            out.append(n)
        return out
    if nav.get("tree"):
        nav["tree"] = prune(nav["tree"])
    initial = (nav.get("initialRoute") or {}).get("default") if isinstance(nav.get("initialRoute"), dict) else None
    if initial in routes:
        nav["initialRoute"] = {}
    return routes


def remove_entity(svc: Any, ref: str, *, app_root: str | None = None, reasoning: Any = None) -> dict:
    from services.smith.workflow_change import remove_workflow
    ent = find_named(_entities(svc.doc), ref)
    if ent is None:
        raise SectionChangeError(f"I cannot tell which entity {ref!r} means. The entities are: {names(_entities(svc.doc))}.")
    eid = str(ent["id"])
    deps = dependents(svc.doc, eid)
    routes = _retire_pages(svc, deps["pages"])
    retired_wfs = []
    for w in deps["workflows"]:
        remove_workflow(svc, str(w["id"]), app_root=None, reasoning=None)
        retired_wfs.append(str(w.get("name")))
    data = svc.doc.get("data") or {}
    if deps["relationships"]:
        data["relationships"] = [r for r in (data.get("relationships") or []) if r not in deps["relationships"]]
    ent["status"] = "DEPRECATED"
    svc.save()
    tell(reasoning, f"Retired {ent.get('name')}" + (f" with {len(routes)} page(s) and {len(retired_wfs)} workflow(s)" if routes or retired_wfs else "") + ".", "step")
    files = _project_data(svc, app_root)
    if app_root:
        from services.blueprint.orchestrator import _project_integration
        from services.blueprint.projection import apply_frontend_projection, project_nav_flow, project_shell
        _project_integration(svc, app_root)
        files += [str(f) for f in (apply_frontend_projection(svc, app_root) or {}).get("files", [])]
        files += list(project_shell(svc.doc, app_root).get("files") or []) + list(project_nav_flow(svc.doc, app_root).get("files") or [])
    return {"applied": True, "entity": eid, "name": str(ent.get("name")), "pages": routes, "workflows": retired_wfs,
            "relationships": len(deps["relationships"]), "pointing": deps["pointing"], "edited_paths": sorted(set(files))}


def summary_of(verb: str, out: dict) -> str:
    if verb == "add_entity":
        return (f"Added the entity {out['name']} ({out['entity']}, table {out['table']}) with "
                f"{', '.join(out['fields']) or 'no fields'}; recorded as {out['requirement']}. The table lands as a "
                "migration on the next install. Say \"add a screen for " + str(out['name']) + "\" and I will compose it.")
    s = f"Retired the entity {out['name']} ({out['entity']})."
    if out.get("pages"):
        s += f" Its screens are retired and off the menu: {', '.join(out['pages'])}."
    if out.get("workflows"):
        s += f" Its workflows are retired: {', '.join(out['workflows'])}."
    if out.get("relationships"):
        s += f" {out['relationships']} relationship(s) dropped."
    if out.get("pointing"):
        s += f" Still pointing at it, for you to decide: {', '.join(out['pointing'])}."
    s += " The table is dropped on the next install."
    return s


def run(output_dir: str, verb: str, *, entity: str = "", reasoning: Any = None) -> dict:
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [], "reason": "this project has no Blueprint yet, so there is no data model to change."}
    app_root = str(Path(output_dir) / "app")
    try:
        if verb == "add_entity":
            out = add_entity(svc, entity, app_root=app_root, reasoning=reasoning)
        elif verb == "remove_entity":
            out = remove_entity(svc, entity, app_root=app_root, reasoning=reasoning)
        else:
            return {"applied": False, "edited_paths": [], "reason": f"unknown entity verb {verb!r}"}
    except SectionChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[smith] %s failed", verb)
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out.get("edited_paths") or [], "diff_summary": summary_of(verb, out),
            "reason": "", **{k: v for k, v in out.items() if k != "edited_paths"}}


__all__ = ["add_entity", "remove_entity", "dependents", "run", "summary_of"]

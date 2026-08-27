"""API surface derivation — endpoints are computed, not authored.

An application's endpoints are already implied by the rest of the Blueprint:

* **Mutations** come from workflows. A step that writes an entity needs a way
  to be driven; a manually-triggered workflow needs a way to be launched.
* **Reads** come from the data engine. Every entity a page displays needs a
  list and a fetch-one; that is a property of the data model, not a design
  decision.
* **Analytics** come from widgets. A metric tile bound to
  ``aggregate(Candidate)`` implies exactly one aggregate endpoint over
  candidates — the widget already declared the shape of the answer.

Asking a model to invent that surface was a category error, and an expensive
one: the ``apis`` agent produced ~40 endpoints for $0.40 and failed contract
validation, when every endpoint was recoverable from artifacts that already
existed. §116 is explicit that deterministic services own what is derivable;
this is the same reasoning that makes ``verification`` a service node.

What this buys beyond cost: the §75 ``Page↔API`` and ``Workflow↔API`` edges
become true by construction. An endpoint cannot reference a missing entity
because it was generated *from* the entity, and a page action cannot lack a
backing endpoint because the action is what generated it.

What it does not do is decide *policy* — which endpoints require which
permission is a security decision, and this reads the permissions the security
agent authored rather than inventing them.
"""
from __future__ import annotations

import re
from typing import Any

#: Page actions that imply a mutation, and the method each needs. Mirrors
#: ACTION_METHOD in verification — the edge checks what this produces.
ACTION_METHOD: dict[str, str] = {
    "create": "POST", "edit": "PUT", "update": "PUT", "delete": "DELETE",
}

#: Workflow step types that write to an entity.
MUTATING_STEPS = ("action", "approval", "human_task")


def _slug(name: str) -> str:
    """`JobRole` -> `job-roles`. Deterministic, so re-derivation is stable."""
    s = re.sub(r"(?<!^)(?=[A-Z])", "-", (name or "").strip()).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "resource"
    if s.endswith("y") and not s.endswith(("ay", "ey", "iy", "oy", "uy")):
        return s[:-1] + "ies"
    if s.endswith(("s", "x", "z", "ch", "sh")):
        return s + "es"
    return s + "s"


def _live(items: Any) -> list[dict]:
    return [i for i in (items or []) if i.get("status") != "DEPRECATED"]


def _permission_for(doc: dict, entity_id: str, action: str) -> str | None:
    """The permission guarding this action, if security declared one.

    Never invents one — an endpoint with no matching permission is left
    unguarded so the §75 API↔Permission edge reports it, rather than being
    silently papered over with a permission nobody authorised.
    """
    entities = {e.get("id"): e for e in doc.get("data", {}).get("entities") or []}
    name = (entities.get(entity_id) or {}).get("name", "")
    for perm in _live(doc.get("permissions")):
        if perm.get("action") != action:
            continue
        subject = perm.get("subject") or ""
        if subject == entity_id or subject.lower() == name.lower():
            return perm.get("id")
    return None


def _workflow_permission(doc: dict, workflow: dict) -> str | None:
    """The `execute` permission guarding this workflow, if security declared one.

    A workflow-launch endpoint has no entity, so the entity-keyed lookup never
    matched and every one of them came out unguarded — sixteen on the first
    real run. Security had authored `execute` permissions all along; nothing
    looked for them. Still read, never invented.
    """
    wid = workflow.get("id")
    name = (workflow.get("name") or "").lower()

    # Security modelled `execute` against the *entity* a workflow acts on
    # (`role.close` guards ENTITY-002), not against the workflow — so match the
    # entity the workflow writes as well as the workflow itself.
    entities = {step.get("entity") for step in workflow.get("steps") or []
                if step.get("type") in MUTATING_STEPS and step.get("entity")}

    for perm in _live(doc.get("permissions")):
        if perm.get("action") != "execute":
            continue
        subject = perm.get("subject") or ""
        if subject == wid or subject.lower() == name or subject in entities:
            return perm.get("id")
    return None


def derive_apis(doc: dict) -> list[dict]:
    """Every endpoint the Blueprint implies, as ``(method, path)``-keyed dicts.

    Pure: reads the document, returns proposals, writes nothing. Endpoints are
    emitted in a stable order so two runs over the same Blueprint produce the
    same list.
    """
    entities = {e.get("id"): e for e in _live(doc.get("data", {}).get("entities"))}
    out: dict[tuple[str, str], dict] = {}

    def add(method: str, path: str, *, entity: str | None, purpose: str,
            requirements: list[str] | None = None,
            permission: str | None = None) -> None:
        key = (method, path)
        action = {"POST": "create", "PUT": "update",
                  "DELETE": "delete", "GET": "read"}[method]
        existing = out.get(key)
        if existing:
            # Same endpoint implied twice — merge provenance rather than
            # emitting a duplicate.
            for req in requirements or []:
                if req not in existing["requirements"]:
                    existing["requirements"].append(req)
            return
        api: dict[str, Any] = {
            "method": method, "path": path, "purpose": purpose,
            "requirements": list(requirements or []),
        }
        if entity:
            api["entity"] = entity
        perm = permission or (_permission_for(doc, entity, action) if entity else None)
        if perm:
            api["permission"] = perm
        out[key] = api

    # --- reads: the data engine ------------------------------------------
    for eid, ent in entities.items():
        slug = _slug(ent.get("name") or "")
        reqs = list(ent.get("requirements") or [])
        add("GET", f"/api/{slug}", entity=eid,
            purpose=f"List {ent.get('name')} records.", requirements=reqs)
        add("GET", f"/api/{slug}/{{id}}", entity=eid,
            purpose=f"Fetch one {ent.get('name')} by id.", requirements=reqs)

    # --- mutations: from workflows ---------------------------------------
    for wf in _live(doc.get("workflows")):
        wid, wname = wf.get("id"), wf.get("name") or "workflow"
        reqs = list(wf.get("requirements") or [])
        if (wf.get("trigger") or {}).get("kind") == "manual":
            add("POST", f"/api/workflows/{_slug(wname)[:-1] or 'run'}/run",
                entity=None,
                purpose=f"Launch the {wname} workflow ({wid}).", requirements=reqs,
                permission=_workflow_permission(doc, wf))
        for step in wf.get("steps") or []:
            eid = step.get("entity")
            if step.get("type") not in MUTATING_STEPS or eid not in entities:
                continue
            slug = _slug(entities[eid].get("name") or "")
            add("POST", f"/api/{slug}", entity=eid,
                purpose=f"Create {entities[eid].get('name')} "
                        f"(written by {wname}).", requirements=reqs)
            add("PUT", f"/api/{slug}/{{id}}", entity=eid,
                purpose=f"Update {entities[eid].get('name')} "
                        f"(written by {wname}).", requirements=reqs)

    # --- mutations: from page actions ------------------------------------
    for page in _live(doc.get("pages")):
        eid = (page.get("data") or {}).get("primaryEntity")
        if eid not in entities:
            continue
        slug = _slug(entities[eid].get("name") or "")
        for action in page.get("actions") or []:
            method = ACTION_METHOD.get(str(action).lower())
            if not method:
                continue
            path = f"/api/{slug}" if method == "POST" else f"/api/{slug}/{{id}}"
            add(method, path, entity=eid,
                purpose=f"{str(action).title()} {entities[eid].get('name')} "
                        f"(used by {page.get('name')}).",
                requirements=list(page.get("requirements") or []))

    # --- analytics: from widgets -----------------------------------------
    for widget in _live(doc.get("widgets")):
        src = widget.get("dataSource") or {}
        eid = src.get("entity")
        if src.get("op") not in ("aggregate", "series") or eid not in entities:
            continue
        slug = _slug(entities[eid].get("name") or "")
        add("GET", f"/api/{slug}/metrics", entity=eid,
            purpose=f"Aggregate {entities[eid].get('name')} for dashboard widgets.",
            requirements=list(widget.get("requirements") or []))

    return [out[k] for k in sorted(out)]


def apply_derived_apis(svc: Any) -> dict[str, int]:
    """Derive and upsert. Keyed on METHOD + path, so re-running is a no-op."""
    from services.blueprint.ids import api_key

    derived = derive_apis(svc.doc)
    for api in derived:
        svc.upsert("apis", dict(api),
                   natural_key=api_key(api["method"], api["path"]))
    svc.save()
    return {
        "derived": len(derived),
        "guarded": sum(1 for a in derived if a.get("permission")),
    }

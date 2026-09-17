"""The business processes are a Blueprint section, and Smith can change them.

"Email the admin after a registration" had nowhere to go: the chat's verbs
covered pages, layouts, fields and the design system, and the `add_workflow`
tool wrote `workflows/*.json` and a resource registry that a Blueprint-built
app does not have. A workflow is authored by the build in two calls — the
`workflows` node declares its identity and contract, `workflow_steps`
authors its step graph against the node catalogue — and the pages are
composed against the declaration. A change after the build takes the same
path, Blueprint-first:

* **add** — the ask becomes a requirement; the `workflows` node is briefed
  to declare ONE new workflow for it (existing ones are never re-declared —
  a re-declaration carries no steps and would wipe them); `workflow_steps`
  authors the steps; the runtime definitions are re-projected; and when a
  person starts it, the screen it starts from is composed again so a control
  for it appears — the composer binds what `launchedFrom` declares.
* **edit** — the ask becomes a decision on the workflow; `workflow_steps` is
  re-run for it with a brief saying what changed and what stays (name,
  trigger, inputs — the pages were composed against those); the definitions
  are re-projected. No page changes.
* **remove** — the workflow is retired (DEPRECATED, never deleted: the
  history keeps it), every control bound to it comes off every screen, the
  verbs those controls served are retracted from the pages, and the
  definitions are re-projected without it.

The whole-DAG answer to "a workflow changed" is to re-compose every page,
because pages depend on workflows. That is right for a build and wrong for
one workflow: only the screen a new workflow starts from needs composing.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
_CLICK_CONTROLS = ("Button", "IconButton", "Link", "ConfirmDialog")


class WorkflowChangeError(Exception):
    """The change could not be made, with the reason a user can act on."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60] or "workflow"


def _live_workflows(doc: dict) -> list[dict]:
    return [w for w in (doc.get("workflows") or [])
            if isinstance(w, dict) and w.get("status") != "DEPRECATED"]


def find_workflow(doc: dict, ref: str) -> dict | None:
    """The workflow a person means by `ref`: its id, its exact name, or the
    name inside what they said ("remove the delete nurse workflow")."""
    want = (ref or "").strip().lower()
    if not want:
        return None
    rows = _live_workflows(doc)
    for w in rows:
        if str(w.get("id") or "").lower() == want or str(w.get("name") or "").strip().lower() == want:
            return w
    hits = [w for w in rows if str(w.get("name") or "").strip().lower()
            and (str(w.get("name")).strip().lower() in want or want in str(w.get("name")).strip().lower())]
    if len(hits) == 1:
        return hits[0]
    return None


def _names(doc: dict) -> str:
    return ", ".join(f"{w.get('name')} ({w.get('id')})" for w in _live_workflows(doc)) or "(none)"


def _executor(svc: Any, executor: Any, reasoning: Any) -> Any:
    if executor is not None:
        return executor
    from services.blueprint.executors import RunUsage, make_executor, tiered_router
    return make_executor(svc, tiered_router(reasoning=reasoning),
                         usage=RunUsage.for_app(svc, phase="change"), reasoning=reasoning)


def record_requirement(svc: Any, request: str) -> dict:
    """The ask as a requirement the workflow satisfies — what the workflow
    agents author from, and what the observer grades the result against."""
    from services.smith.smith import bootstrap as _bind_ids
    _bind_ids(svc)
    body = {
        "description": request,
        "evidence": [{"message": request, "type": "conversation"}],
        "confidence": 1.0,
        "status": "APPROVED",
        "owner": "workflows",
    }
    written = svc.upsert("requirements", body, natural_key=f"REQ:{_slug(request)}")
    svc.save()
    return written


def _page_for_route(doc: dict, route: str) -> dict | None:
    from services.smith.compose import _page_for_route as _pf
    return _pf(doc, route)


def _entity_of(wf: dict) -> str:
    for i in wf.get("inputs") or []:
        if isinstance(i, dict) and i.get("kind") == "record" and i.get("entity"):
            return str(i["entity"])
    for st in wf.get("steps") or []:
        if isinstance(st, dict) and st.get("entity"):
            return str(st["entity"])
    return ""


def pick_page(doc: dict, wf: dict) -> dict | None:
    """The screen a manual workflow starts from when nobody named one: the
    list page of its entity, else its record page, else the one page that
    already declares it in `launchedFrom`."""
    from services.blueprint.functional_completeness import page_family
    pages = [p for p in (doc.get("pages") or []) if isinstance(p, dict) and p.get("status") != "DEPRECATED"]
    by_id = {str(p.get("id")): p for p in pages}
    declared = [by_id[x] for x in (wf.get("launchedFrom") or []) if x in by_id]
    if declared:
        return declared[0]
    ent = _entity_of(wf)
    mine = [p for p in pages if str((p.get("data") or {}).get("primaryEntity") or "") == ent] if ent else []
    for fam in ("collection", "record"):
        for p in mine:
            if page_family(p) == fam:
                return p
    return mine[0] if mine else None


def _declare_brief(request: str, req: dict, doc: dict, page: dict | None) -> str:
    where = (f"It is started by a person on the screen {page.get('route')} ({page.get('id')}): "
             f"trigger `manual`, `launchedFrom: [\"{page.get('id')}\"]`."
             if page else
             "THE TRIGGER COMES FROM THE WORDS. \"When X happens\", \"after X\", \"once a record is "
             "saved\" is an event: trigger `db_change` on that entity (say which table and which "
             "change in `detail`) or `api_event`, with `launchedFrom` empty and NO inputs a person "
             "would type — the record the change produced is what it acts on. \"Every Monday\", "
             "\"nightly\" is `schedule`. `manual` ONLY when a person starts it — \"let the user…\", "
             "\"add an action/button to…\" — and then pick the ONE screen it starts from among the "
             "pages below and put that page's id in `launchedFrom`. A manual workflow whose inputs "
             "are the same fields a form on that screen already collects is a duplicate of that "
             "form's workflow, and the composer will place no control for it.")
    return (
        "THIS IS A CHANGE to an application that is already built, not a first authoring.\n"
        f"The user asked for ONE new workflow: \"{request}\". It satisfies {req.get('id')} — cite it "
        "in the workflow's `requirements`.\n"
        f"{where}\n"
        f"These workflows exist already and are NOT to be returned, renamed or re-declared: {_names(doc)}. "
        "Return exactly ONE proposal, for the new workflow, under a new name that says what it does. "
        "Declare its `inputs` as the standing task says; do not write `steps`."
    )


def _field_inputs(wf: dict) -> frozenset:
    return frozenset(str(i.get("name") or "").lower() for i in (wf.get("inputs") or [])
                     if isinstance(i, dict) and i.get("kind") == "field" and i.get("name"))


def duplicate_of(doc: dict, body: dict) -> dict | None:
    """The existing workflow a declared manual workflow duplicates: same field
    inputs, started from a screen they share. Asked "when a nurse is
    registered, notify the admin", the agent declared a second manual workflow
    taking the registration form's five fields, and the composer put a second
    form on the registration page. Those inputs ARE Register Nurse's
    submission; the ask is a change to that workflow, not a sibling of it."""
    if str((body.get("trigger") or {}).get("kind") or "manual") != "manual":
        return None
    mine = _field_inputs(body)
    if not mine:
        return None
    pages = set(str(x) for x in (body.get("launchedFrom") or []))
    for w in _live_workflows(doc):
        if str((w.get("trigger") or {}).get("kind") or "") != "manual":
            continue
        theirs = _field_inputs(w)
        shared = pages & set(str(x) for x in (w.get("launchedFrom") or []))
        if theirs and theirs == mine and (shared or not pages):
            return w
    return None


def _steps_brief(wf: dict, why: str) -> str:
    return (
        "THIS IS A CHANGE to an application that is already built.\n"
        f"{why}\n"
        f"Keep the workflow's identity exactly as declared — name \"{wf.get('name')}\", trigger, "
        "`launchedFrom` and `inputs` — the pages are composed against them. Author the steps to "
        "honour the ask, from the node catalogue, with real values."
    )


def _proposals(result: Any, section: str = "workflows") -> list:
    return [p for p in (getattr(result, "proposals", None) or []) if getattr(p, "section", "") == section]


def _pinned(svc: Any, proposals: list, workflow_id: str) -> list:
    """The proposals re-keyed to what the registry bound `workflow_id` to.
    A steps proposal is FOR one workflow; keyed by whatever name the agent
    wrote, it lands on a second id beside the first and the edit reads as
    "applied" while the workflow keeps its old steps."""
    from services.blueprint.agent_contract import ArtifactProposal
    from services.blueprint.ids import IdAllocator
    try:
        key = IdAllocator.load(output_dir=svc.output_dir).key_for(workflow_id)
    except Exception:  # noqa: BLE001
        key = None
    if not key:
        return list(proposals)
    return [ArtifactProposal(p.section, key, p.body) if p.section == "workflows" else p for p in proposals]


def _apply(svc: Any, request: str, proposals: list, *, interpretation: str, agent: str,
           app_root: str | None) -> tuple[Any, str]:
    """`apply_change` without the whole-DAG regeneration; returns (result,
    refusal) where refusal is "" on success."""
    from services.blueprint.agent_contract import InvalidPatternTemplate, InvalidWorkflowStep
    from services.blueprint.service import BlueprintInvalid
    from services.smith.change import apply_change
    from services.smith.smith import bootstrap as _bind_ids
    _bind_ids(svc)                       # the registry in step with the document before any allocation
    try:
        out = apply_change(svc, request, proposals=list(proposals), interpretation=interpretation,
                           agent=agent, app_root=app_root, regenerate=False)
    except (BlueprintInvalid, InvalidPatternTemplate, InvalidWorkflowStep) as exc:
        # The contract's refusal — an unknown node, a value the engine would
        # never hold — is the feedback the next attempt is told.
        return None, f"{type(exc).__name__}: {exc}".replace("\n", " ")[:500]
    if not getattr(out, "applied", False):
        return None, str(getattr(out, "reason", "") or "refused")
    return out, ""


def _project_runtime(svc: Any, app_root: str | None) -> list[str]:
    if not app_root:
        return []
    from services.blueprint.orchestrator import _project_integration
    _project_integration(svc, app_root)
    return ["src/lib/workflows/definitions"]


# --- add ---------------------------------------------------------------------

def add_workflow(svc: Any, request: str, *, route: str = "", app_root: str | None = None,
                 executor: Any = None, reasoning: Any = None) -> dict:
    from services.blueprint.agent_contract import ArtifactProposal
    from services.blueprint.orchestrator import DAG, TaskSpec

    request = (request or "").strip()
    if not request:
        raise WorkflowChangeError("nothing was described, so there is no workflow to add.")
    page = None
    if route:
        page = _page_for_route(svc.doc, route)
        if page is None:
            known = ", ".join(str(p.get("route")) for p in svc.doc.get("pages") or []) or "(none)"
            raise WorkflowChangeError(f"there is no screen at {route!r}. The screens are: {known}.")
    run = _executor(svc, executor, reasoning)
    agent = DAG["workflows"].agent
    req = record_requirement(svc, request)
    existing_names = {str(w.get("name") or "").strip().lower() for w in _live_workflows(svc.doc)}
    existing_ids = {str(w.get("id")) for w in svc.doc.get("workflows") or []}
    brief = _declare_brief(request, req, svc.doc, page)

    # 1. declare
    feedback, new_id, new_name = "", "", ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        spec = TaskSpec(task_id=f"smith-add-workflow-{attempt}", node="workflows", agent=agent,
                        attempt=attempt, feedback=feedback, brief=brief)
        tell(reasoning, f"Declaring a workflow for: {request}.", "step")
        result = run(spec)
        fresh = [p for p in _proposals(result)
                 if str((p.body or {}).get("name") or "").strip().lower() not in existing_names
                 and str((p.body or {}).get("id") or "") not in existing_ids]
        if not fresh:
            feedback = ("Every workflow you returned already exists. Return exactly one NEW workflow, "
                        f"under a new name, for: \"{request}\".")
            if attempt == MAX_ATTEMPTS:
                raise WorkflowChangeError("the workflow agent declared nothing new twice; nothing has been changed.")
            continue
        body = dict(fresh[0].body or {})
        body.pop("steps", None)
        body.pop("id", None)
        dup = duplicate_of(svc.doc, body)
        if dup is not None:
            # THE ASK IS A CHANGE TO WHAT EXISTS. A second workflow taking the
            # same submission would be a second form on the same screen.
            tell(reasoning, f"\"{request}\" is what {dup.get('name')} already does when it runs — "
                            f"changing {dup.get('name')} instead of adding a second workflow.", "step")
            reqs = list(dup.get("requirements") or [])
            if req.get("id") and req["id"] not in reqs:
                dup["requirements"] = reqs + [req["id"]]
                svc.save()
            edited = edit_workflow(svc, str(dup["id"]), request, app_root=app_root,
                                   executor=run, reasoning=reasoning)
            edited.update({"requirement": req.get("id"), "extended": str(dup.get("name")),
                           "workflow": str(dup["id"]), "name": str(dup.get("name")),
                           "steps": len(edited.get("steps_after") or []), "trigger": "manual",
                           "composed": None, "offered": False})
            return edited
        if page is not None and str((body.get("trigger") or {}).get("kind") or "manual") == "manual":
            launched = [str(x) for x in (body.get("launchedFrom") or [])]
            if page.get("id") not in launched:
                launched.append(str(page.get("id")))
            body["launchedFrom"] = launched
        reqs = list(body.get("requirements") or [])
        if req.get("id") and req["id"] not in reqs:
            body["requirements"] = reqs + [req["id"]]
        out, refusal = _apply(svc, request, [ArtifactProposal("workflows", fresh[0].natural_key, body)],
                              interpretation=f"declare a workflow: {request}", agent=agent, app_root=app_root)
        if refusal:
            feedback = refusal
            if attempt == MAX_ATTEMPTS:
                raise WorkflowChangeError(f"the declared workflow was refused {MAX_ATTEMPTS} times and nothing "
                                          f"has been changed. The last reason was: {refusal}")
            tell(reasoning, f"That declaration was refused — {refusal[:160]} Asking again.", "step")
            continue
        new_name = str(body.get("name") or "")
        new = next((w for w in svc.doc.get("workflows") or []
                    if str(w.get("name") or "").strip().lower() == new_name.strip().lower()), None)
        if new is None:
            raise WorkflowChangeError("the declaration was committed but the workflow cannot be found by its name.")
        new_id = str(new["id"])
        break

    # 2. steps
    wf = next(w for w in svc.doc["workflows"] if w["id"] == new_id)
    steps_brief = _steps_brief(wf, f"This workflow was just declared for the user's ask: \"{request}\".")
    feedback = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        spec = TaskSpec(task_id=f"smith-workflow-steps-{new_id}-{attempt}", node="workflow_steps",
                        agent=DAG["workflow_steps"].agent, attempt=attempt, subject=new_id,
                        feedback=feedback, brief=steps_brief)
        tell(reasoning, f"Authoring the steps of {new_name}.", "step")
        result = run(spec)
        props = _proposals(result)
        if not props:
            raise WorkflowChangeError(f"the workflow agent wrote no steps for {new_name}; the workflow is declared "
                                      "but does nothing yet.")
        out, refusal = _apply(svc, request, _pinned(svc, props[:1], new_id),
                              interpretation=f"author the steps of {new_name}",
                              agent=DAG["workflow_steps"].agent, app_root=app_root)
        if not refusal:
            break
        feedback = refusal
        if attempt == MAX_ATTEMPTS:
            raise WorkflowChangeError(f"the steps of {new_name} were refused {MAX_ATTEMPTS} times; the workflow "
                                      f"is declared ({new_id}) but has no steps. The last reason was: {refusal}")
        tell(reasoning, f"Those steps were refused — {refusal[:160]} Asking again.", "step")

    wf = next(w for w in svc.doc["workflows"] if w["id"] == new_id)
    files = _project_runtime(svc, app_root)

    # 3. the screen it starts from
    composed, offered = None, False
    if str((wf.get("trigger") or {}).get("kind") or "") == "manual":
        start = page or pick_page(svc.doc, wf)
        if start is not None:
            if start.get("id") not in (wf.get("launchedFrom") or []):
                wf["launchedFrom"] = list(wf.get("launchedFrom") or []) + [str(start["id"])]
                svc.save()
            from services.smith.compose import compose_route
            tell(reasoning, f"Composing {start.get('route')} so it offers {new_name}.", "step")
            compose_route(svc, str(start.get("route")), app_root=app_root,
                          request=f"add a control that runs the {new_name} workflow ({new_id})",
                          executor=run, reasoning=reasoning)
            composed = str(start.get("route"))
            files.append(f"src/schemas{start.get('route')}.json")
            # SAY WHAT LANDED, NOT WHAT WAS ASKED. The composer binds a control
            # only where one makes sense; a screen whose form already submits
            # a workflow with the same inputs gets none, and "composed so it
            # offers it" would be a claim nothing on the screen backs.
            offered = _offers(svc.doc, str(start.get("id")), new_id)
    return {"applied": True, "workflow": new_id, "name": new_name, "requirement": req.get("id"),
            "steps": len(wf.get("steps") or []), "trigger": str((wf.get("trigger") or {}).get("kind") or ""),
            "composed": composed, "offered": offered, "edited_paths": files}


def _offers(doc: dict, page_id: str, wf_id: str) -> bool:
    """Whether the page's live layout has a control bound to `wf_id`."""
    layout = next((l for l in doc.get("pageLayouts") or []
                   if isinstance(l, dict) and str(l.get("page")) == page_id
                   and l.get("status") not in ("SUPERSEDED", "DEPRECATED")), None)
    if not layout:
        return False
    def walk(n: Any) -> bool:
        if isinstance(n, list):
            return any(walk(c) for c in n)
        if not isinstance(n, dict):
            return False
        props = n.get("props") or {}
        if props.get("workflow") == wf_id:
            return True
        for val in props.values():
            for c in (val if isinstance(val, list) else [val]):
                if isinstance(c, dict) and c.get("workflow") == wf_id:
                    return True
        return walk(n.get("children") or [])
    return walk(layout.get("root"))


# --- edit --------------------------------------------------------------------

def edit_workflow(svc: Any, ref: str, change: str, *, app_root: str | None = None,
                  executor: Any = None, reasoning: Any = None) -> dict:
    from services.blueprint.orchestrator import DAG, TaskSpec
    from services.smith.decisions import NotADecision, record

    change = (change or "").strip()
    wf = find_workflow(svc.doc, ref)
    if wf is None:
        raise WorkflowChangeError(f"I cannot tell which workflow {ref!r} means. The workflows are: {_names(svc.doc)}.")
    if not change:
        raise WorkflowChangeError(f"what should be different about {wf.get('name')}?")
    try:
        decision = record(svc, artifact_id=str(wf["id"]), decision=change,
                          reason="Asked in conversation after the build; the steps were re-authored against it.")
    except NotADecision as exc:
        raise WorkflowChangeError(str(exc)) from exc
    before = [str(s.get("name") or s.get("key")) for s in wf.get("steps") or []]
    run = _executor(svc, executor, reasoning)
    brief = _steps_brief(wf, f"The user asked to change what it does: \"{change}\". Keep every step the "
                             "change does not touch; change, add or drop steps only where the ask needs it.")
    feedback = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        spec = TaskSpec(task_id=f"smith-edit-workflow-{wf['id']}-{attempt}", node="workflow_steps",
                        agent=DAG["workflow_steps"].agent, attempt=attempt, subject=str(wf["id"]),
                        feedback=feedback, brief=brief)
        tell(reasoning, f"Re-authoring the steps of {wf.get('name')}: {change}.", "step")
        result = run(spec)
        props = _proposals(result)
        if not props:
            raise WorkflowChangeError(f"the workflow agent returned nothing for {wf.get('name')}; nothing has been changed.")
        out, refusal = _apply(svc, change, _pinned(svc, props[:1], str(wf["id"])),
                              interpretation=f"change {wf.get('name')}: {change}",
                              agent=DAG["workflow_steps"].agent, app_root=app_root)
        if not refusal:
            break
        feedback = refusal
        if attempt == MAX_ATTEMPTS:
            raise WorkflowChangeError(f"the changed steps were refused {MAX_ATTEMPTS} times and nothing has been "
                                      f"changed. The last reason was: {refusal}")
        tell(reasoning, f"Those steps were refused — {refusal[:160]} Asking again.", "step")
    now = next(w for w in svc.doc["workflows"] if w["id"] == wf["id"])
    after = [str(s.get("name") or s.get("key")) for s in now.get("steps") or []]
    files = _project_runtime(svc, app_root)
    return {"applied": True, "workflow": str(wf["id"]), "name": str(wf.get("name")),
            "decision": decision.id, "steps_before": before, "steps_after": after, "edited_paths": files}


# --- remove ------------------------------------------------------------------

def _strip_controls(node: Any, wf_id: str) -> list[dict]:
    """Every control bound to `wf_id` comes off the tree — a Button, a row
    action, an empty-state action, and a Form that submits to it: a form
    submitting to a retired workflow is a dead end dressed as a screen."""
    removed: list[dict] = []
    if isinstance(node, list):
        keep = []
        for n in node:
            props = (n.get("props") or {}) if isinstance(n, dict) else {}
            if isinstance(n, dict) and n.get("type") in (*_CLICK_CONTROLS, "Form") and props.get("workflow") == wf_id:
                removed.append({**props, "_type": n.get("type")})
            else:
                removed.extend(_strip_controls(n, wf_id))
                keep.append(n)
        node[:] = keep
        return removed
    if not isinstance(node, dict):
        return removed
    props = node.get("props")
    if isinstance(props, dict):
        for key, val in list(props.items()):
            if isinstance(val, list) and val and all(isinstance(v, dict) for v in val):
                gone = [v for v in val if v.get("workflow") == wf_id]
                if gone:
                    removed.extend(gone)
                    kept = [v for v in val if v.get("workflow") != wf_id]
                    if kept:
                        props[key] = kept
                    else:
                        del props[key]
            elif isinstance(val, dict) and val.get("workflow") == wf_id:
                removed.append(val)
                del props[key]
    removed.extend(_strip_controls(node.get("children") or [], wf_id))
    return removed


def _forms_bound(root: Any, wf_id: str) -> int:
    n = 0
    def walk(x: Any) -> None:
        nonlocal n
        if isinstance(x, dict):
            if x.get("type") == "Form" and (x.get("props") or {}).get("workflow") == wf_id:
                n += 1
            for c in x.get("children") or []:
                walk(c)
        elif isinstance(x, list):
            for c in x:
                walk(c)
    walk(root)
    return n


def remove_workflow(svc: Any, ref: str, *, app_root: str | None = None, reasoning: Any = None) -> dict:
    from services.smith.move_dispatcher import _retract

    wf = find_workflow(svc.doc, ref)
    if wf is None:
        raise WorkflowChangeError(f"I cannot tell which workflow {ref!r} means. The workflows are: {_names(svc.doc)}.")
    wf_id = str(wf["id"])
    pages = {str(p.get("id")): p for p in (svc.doc.get("pages") or []) if isinstance(p, dict)}
    touched: list[str] = []
    notes: list[str] = []
    forms = 0
    for layout in svc.doc.get("pageLayouts") or []:
        if not isinstance(layout, dict) or layout.get("status") in ("SUPERSEDED", "DEPRECATED"):
            continue
        removed = _strip_controls(layout.get("root"), wf_id)
        forms += sum(1 for r in removed if r.get("_type") == "Form")
        if not removed:
            continue
        page = pages.get(str(layout.get("page"))) or {}
        notes.extend(_retract(svc.doc, page, layout, removed))
        svc.upsert("pageLayouts", layout, natural_key=str(layout["page"]))
        touched.append(str(page.get("route") or layout.get("page")))
    wf["status"] = "DEPRECATED"
    wf["launchedFrom"] = []
    svc.save()
    tell(reasoning, f"Retired {wf.get('name')}" + (f"; took its controls off {', '.join(touched)}" if touched else "") + ".", "step")
    files = _project_runtime(svc, app_root)
    if touched and app_root:
        from services.blueprint.projection import apply_frontend_projection
        result = apply_frontend_projection(svc, app_root)
        files.extend(str(f) for f in (result or {}).get("files", []))
    return {"applied": True, "workflow": wf_id, "name": str(wf.get("name")), "pages": touched,
            "notes": notes, "forms_left": forms, "edited_paths": files}


# --- the envelope --------------------------------------------------------------

def summary_of(verb: str, out: dict) -> str:
    if verb == "add_workflow" and out.get("extended"):
        return (f"That is what {out['extended']} ({out['workflow']}) already does when it runs, so I changed "
                f"it instead of adding a second workflow — recorded as {out['requirement']} and "
                f"{out['decision']}. Its steps now: {' → '.join(out['steps_after']) or '(none)'}.")
    if verb == "add_workflow":
        s = (f"Added the workflow {out['name']} ({out['workflow']}): {out['steps']} step(s), "
             f"trigger {out['trigger'] or 'manual'}, recorded as {out['requirement']}.")
        if out.get("composed") and out.get("offered"):
            s += f" Composed {out['composed']} again so it offers it."
        elif out.get("composed"):
            s += (f" Composed {out['composed']} again, but the composer placed no control for it there — "
                  "the screen already runs a workflow with the same inputs. Tell me which screen should "
                  "start it, or ask for it to run automatically when the record changes.")
        elif out.get("trigger") == "manual":
            s += " No screen was found to start it from — tell me which one and I will compose it there."
        else:
            s += " It runs on its own; no screen needs a control for it."
        return s
    if verb == "edit_workflow":
        return (f"Changed {out['name']} ({out['workflow']}), recorded as {out['decision']}. Steps now: "
                f"{' → '.join(out['steps_after']) or '(none)'}"
                + (f" (were: {' → '.join(out['steps_before'])})." if out['steps_before'] != out['steps_after'] else "."))
    s = f"Retired {out['name']} ({out['workflow']})."
    if out.get("pages"):
        s += f" Took its controls off {', '.join(out['pages'])}"
        if out.get("notes"):
            s += " (" + "; ".join(out["notes"]) + ")"
        s += "."
    if out.get("forms_left"):
        s += (f" {out['forms_left']} form(s) submitted to it and came off too — if that screen should still "
              "collect something, tell me what it should run.")
    return s


def run(output_dir: str, verb: str, *, workflow: str = "", change: str = "", route: str = "",
        reasoning: Any = None) -> dict:
    """`{applied, edited_paths, diff_summary, reason}` — the shape `compose.run`
    returns, so the session and the tools share one implementation."""
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": "this project has no Blueprint yet, so there are no workflows to change."}
    app_root = str(Path(output_dir) / "app")
    try:
        if verb == "add_workflow":
            out = add_workflow(svc, workflow, route=route, app_root=app_root, reasoning=reasoning)
        elif verb == "edit_workflow":
            out = edit_workflow(svc, workflow, change, app_root=app_root, reasoning=reasoning)
        elif verb == "remove_workflow":
            out = remove_workflow(svc, workflow, app_root=app_root, reasoning=reasoning)
        else:
            return {"applied": False, "edited_paths": [], "reason": f"unknown workflow verb {verb!r}"}
    except WorkflowChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[smith] %s failed", verb)
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out.get("edited_paths") or [],
            "diff_summary": summary_of(verb, out), "reason": "", **{k: v for k, v in out.items() if k != "edited_paths"}}


__all__ = ["add_workflow", "edit_workflow", "remove_workflow", "find_workflow", "pick_page",
           "record_requirement", "run", "summary_of", "WorkflowChangeError"]

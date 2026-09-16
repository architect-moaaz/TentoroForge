"""The definition — requirements, product, APIs, integrations — is a set of
Blueprint sections, and Smith can change them after the build.

Before the build these are what discovery writes; after it, nothing in the
verb set touched them, so "the app should also let a nurse mark herself
unavailable" or "call the app Nurse Roster" had no path.

* A REQUIREMENT changed flows to what cites it: the pages citing it are
  composed again against the new wording, the workflows and rules citing
  it are re-authored against it. A new requirement is recorded and
  reported as not yet implemented, with the way to make it so. A removed
  requirement is retired and taken off the artifacts that cited it.
* PRODUCT and the application's name and description are revised by a
  small structured call and re-projected into the shell.
* An API is declared by the `apis` agent for the entity it serves and
  guarded by a permission; the data engine serves data routes, anything
  else is declared and said to need a handler. An INTEGRATION is declared
  by the `integrations` agent with the NAMES of its secrets — never a
  value — which the install writes to `.env.example`.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.llm_client import tell
from services.smith.section_change import SectionChangeError, find_named, names, record_requirement, rerun

logger = logging.getLogger(__name__)


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("status") not in ("DEPRECATED", "SUPERSEDED")]


# --- requirements ----------------------------------------------------------------

def _find_requirement(doc: dict, ref: str) -> dict | None:
    want = (ref or "").strip().lower()
    rows = _live(doc.get("requirements"))
    for r in rows:
        if str(r.get("id") or "").lower() == want:
            return r
    hits = [r for r in rows if want and (want in str(r.get("description") or "").lower()
                                         or str(r.get("description") or "").lower()[:40] in want)]
    return hits[0] if len(hits) == 1 else None


def _citing(doc: dict, req_id: str) -> dict[str, list[dict]]:
    out = {"pages": [], "workflows": [], "rules": []}
    for p in _live(doc.get("pages")):
        if req_id in (p.get("requirements") or []):
            out["pages"].append(p)
    for w in _live(doc.get("workflows")):
        if req_id in (w.get("requirements") or []):
            out["workflows"].append(w)
    for r in _live(doc.get("businessRules")):
        if req_id in (r.get("requirements") or []):
            out["rules"].append(r)
    return out


def add_requirement(svc: Any, text: str, *, reasoning: Any = None) -> dict:
    text = (text or "").strip()
    if not text:
        raise SectionChangeError("no requirement was stated.")
    req = record_requirement(svc, text, owner="")
    if not req.get("owner"):
        req.pop("owner", None)
        svc.save()
    tell(reasoning, f"Recorded {req.get('id')}.", "step")
    return {"applied": True, "requirement": str(req.get("id")), "text": text, "edited_paths": []}


def edit_requirement(svc: Any, ref: str, change: str, *, app_root: str | None = None, executor: Any = None,
                     reasoning: Any = None) -> dict:
    from services.smith.decisions import NotADecision, record
    change = (change or "").strip()
    req = _find_requirement(svc.doc, ref)
    if req is None:
        known = "; ".join(f"{r.get('id')}: {str(r.get('description'))[:60]}" for r in _live(svc.doc.get("requirements")))
        raise SectionChangeError(f"I cannot tell which requirement {ref!r} means. They are: {known or '(none)'}.")
    if not change:
        raise SectionChangeError(f"what should {req.get('id')} say instead?")
    before = str(req.get("description") or "")
    req["description"] = change
    req.setdefault("evidence", []).append({"message": change, "type": "conversation"})
    req["status"] = "APPROVED"
    svc.validate()
    svc.save()
    try:
        decision = record(svc, artifact_id=str(req["id"]), decision=change,
                          reason="Asked in conversation after the build; the requirement was restated.")
    except NotADecision as exc:
        raise SectionChangeError(str(exc)) from exc
    cites = _citing(svc.doc, str(req["id"]))
    done, failed = [], []
    if cites["pages"]:
        from services.smith.compose import ComposeError, compose_route
    for p in cites["pages"]:
        try:
            tell(reasoning, f"Composing {p.get('route')} against the restated {req['id']}.", "step")
            compose_route(svc, str(p.get("route")), app_root=app_root, executor=executor, reasoning=reasoning,
                          request=f"{req['id']} now says: {change}")
            done.append(str(p.get("route")))
        except Exception as exc:  # noqa: BLE001 — one refused page is reported, not fatal to the rest
            failed.append(f"{p.get('route')}: {str(exc)[:160]}")
    if cites["workflows"]:
        from services.smith.workflow_change import WorkflowChangeError, edit_workflow
        for w in cites["workflows"]:
            try:
                edit_workflow(svc, str(w["id"]), f"{req['id']} now says: {change}", app_root=app_root,
                              executor=executor, reasoning=reasoning)
                done.append(str(w.get("name")))
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{w.get('name')}: {str(exc)[:160]}")
    if cites["rules"]:
        from services.smith.rule_change import edit_rule
        for r in cites["rules"]:
            try:
                edit_rule(svc, str(r["id"]), f"{req['id']} now says: {change}", app_root=app_root,
                          executor=executor, reasoning=reasoning)
                done.append(str(r.get("name")))
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{r.get('name')}: {str(exc)[:160]}")
    return {"applied": True, "requirement": str(req["id"]), "before": before, "after": change,
            "decision": decision.id, "reauthored": done, "failed": failed,
            "edited_paths": ["src/schemas"] if cites["pages"] else []}


def remove_requirement(svc: Any, ref: str, *, reasoning: Any = None) -> dict:
    req = _find_requirement(svc.doc, ref)
    if req is None:
        raise SectionChangeError(f"I cannot tell which requirement {ref!r} means.")
    rid = str(req["id"])
    req["status"] = "DEPRECATED"
    touched = []
    for section in ("pages", "workflows", "businessRules", "data.entities"):
        rows = (svc.doc.get("data") or {}).get("entities") if section == "data.entities" else svc.doc.get(section)
        for a in rows or []:
            if isinstance(a, dict) and rid in (a.get("requirements") or []):
                a["requirements"] = [x for x in a["requirements"] if x != rid]
                touched.append(str(a.get("id")))
    svc.validate()
    svc.save()
    tell(reasoning, f"Retired {rid}.", "step")
    return {"applied": True, "requirement": rid, "text": str(req.get("description") or ""), "uncited": touched, "edited_paths": []}


# --- product ---------------------------------------------------------------------

PRODUCT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "objectives": {"type": "array", "items": {"type": "string"}},
        # The API refuses `additionalProperties: {type}` on an object, so the
        # glossary travels as pairs and is folded back into the map.
        "terminology": {"type": "array", "items": {"type": "object", "properties": {
            "term": {"type": "string"}, "meaning": {"type": "string"}}, "required": ["term", "meaning"],
            "additionalProperties": False}},
        "personas": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "description": {"type": "string"},
            "goals": {"type": "array", "items": {"type": "string"}}}, "required": ["name"], "additionalProperties": False}},
        "locale": {"type": "string"},
        "changed": {"type": "array", "items": {"type": "string", "enum": ["name", "description", "objectives", "terminology", "personas", "locale"]},
                    "description": "the fields the request changed; only these are applied"},
        "note": {"type": "string"},
    },
    "required": ["name", "description", "objectives", "changed"],
    "additionalProperties": False,
}


def _client() -> Any:
    from services.blueprint.executors import AGENT_MODEL, AnthropicModel
    return AnthropicModel(model=AGENT_MODEL, effort="medium")


def edit_product(svc: Any, change: str, *, app_root: str | None = None, client: Any = None,
                 reasoning: Any = None) -> dict:
    from services.blueprint.service import BlueprintInvalid
    change = (change or "").strip()
    if not change:
        raise SectionChangeError("nothing was described, so there is nothing to change about the product.")
    app = svc.doc.get("application") or {}
    prod = svc.doc.get("product") or {}
    current = {"name": app.get("name"), "description": app.get("description"),
               "objectives": prod.get("objectives") or [],
               "terminology": [{"term": k, "meaning": v} for k, v in (prod.get("terminology") or {}).items()],
               "personas": prod.get("personas") or [], "locale": prod.get("locale") or "en"}
    system = ("You revise the product definition of an application that is already built: its name, its "
              "description, its objectives, its domain terminology, its personas and its locale.\n"
              "Rules: change ONLY what the request asks; return every field as it should be after the "
              "change, unchanged fields exactly as given, and list in `changed` the fields the request "
              "changed — nothing else is applied, so a field you rewrote without listing it is dropped. "
              "The name is never empty. `locale` is a BCP-47 tag. Say in `note` anything that could not be done.")
    user = f"The request: \"{change}\".\n\nThe product as it stands:\n{json.dumps(current, indent=1)}\n\nReturn it as it should be."
    call = client or _client()
    tell(reasoning, f"Revising the product definition: {change}.", "step")
    raw = call(system=system, user=user, schema=PRODUCT_SCHEMA)
    try:
        data = json.loads(str(getattr(raw, "text", raw)))
    except ValueError as exc:
        raise SectionChangeError(f"the revision was not JSON: {exc}") from exc
    if not str(data.get("name") or "").strip():
        raise SectionChangeError("the revised product has no name.")
    before = svc.snapshot()
    # ONLY THE FIELDS THE REVISION SAYS IT CHANGED. Asked to rename the app,
    # the model also rewrote a persona's name into one of its goals; told to
    # change only what was asked, it did not, and nothing held it to that.
    declared = {str(x) for x in (data.get("changed") or [])}
    changed = []
    if "name" in declared and str(data["name"]).strip() != app.get("name"):
        app["name"] = str(data["name"]).strip(); changed.append("name")
    if "description" in declared and str(data.get("description") or "") != (app.get("description") or ""):
        app["description"] = str(data.get("description") or ""); changed.append("description")
    if isinstance(data.get("terminology"), list):
        data["terminology"] = {str(t.get("term")): str(t.get("meaning") or "") for t in data["terminology"]
                               if isinstance(t, dict) and t.get("term")}
    for key in ("objectives", "terminology", "personas"):
        if key in declared and key in data and data[key] != prod.get(key):
            prod[key] = data[key]; changed.append(key)
    if "locale" in declared and data.get("locale") and data["locale"] != prod.get("locale"):
        prod["locale"] = str(data["locale"]); changed.append("locale")
    svc.doc["application"] = app
    svc.doc["product"] = prod
    if not changed:
        raise SectionChangeError("the product came back exactly as it is" + (f" — {data.get('note')}" if data.get("note") else "") + ".")
    try:
        svc.validate()
    except BlueprintInvalid as exc:
        raise SectionChangeError(f"the revised product does not fit the Blueprint: {exc}") from exc
    svc.commit(user_request=change, smith_interpretation=f"revise the product: {', '.join(changed)}",
               before=before, affected=[])
    files: list[str] = []
    if app_root and ("name" in changed):
        from services.blueprint.projection import project_nav_flow, project_shell
        files += list(project_shell(svc.doc, app_root).get("files") or [])
        files += list(project_nav_flow(svc.doc, app_root).get("files") or [])
    return {"applied": True, "changed": changed, "name": app.get("name"), "note": str(data.get("note") or "").strip(),
            "edited_paths": files}


# --- apis --------------------------------------------------------------------------

def add_api(svc: Any, request: str, *, app_root: str | None = None, executor: Any = None, reasoning: Any = None) -> dict:
    request = (request or "").strip()
    if not request:
        raise SectionChangeError("no endpoint was described.")
    req = record_requirement(svc, request, owner="apis")
    existing = {(str(a.get("method") or "").upper(), str(a.get("path") or "")) for a in _live(svc.doc.get("apis"))}
    perms = ", ".join(f"{p.get('id')} {p.get('action')} {p.get('name')}" for p in _live(svc.doc.get("permissions"))) or "(none)"
    brief = ("THIS IS A CHANGE to an application that is already built.\n"
             f"The user asked for ONE new endpoint: \"{request}\". It satisfies {req.get('id')}.\n"
             f"Endpoints that exist and are NOT to be returned: {', '.join(m + ' ' + p for m, p in sorted(existing)) or '(none)'}. "
             f"Permissions that exist: {perms}. Return exactly ONE `apis` proposal: method, path, purpose, the "
             "entity it serves when it serves one, and the permission that guards it (required unless GET).")
    def keep(props):
        mine = [p for p in props if p.section == "apis"
                and (str((p.body or {}).get("method") or "").upper(), str((p.body or {}).get("path") or "")) not in existing]
        return mine[:1] if len(mine) == 1 else []
    props, _ = rerun(svc, "apis", brief=brief, request=request, interpretation=f"declare an endpoint: {request}",
                     keep=keep, executor=executor, reasoning=reasoning, app_root=app_root,
                     empty="return exactly ONE new endpoint and nothing else", say=f"Declaring an endpoint for: {request}.")
    body = props[0].body or {}
    api = next((a for a in _live(svc.doc.get("apis")) if str(a.get("method") or "").upper() == str(body.get("method") or "").upper()
                and str(a.get("path") or "") == str(body.get("path") or "")), None)
    served = str(body.get("path") or "").startswith("/api/data/") and bool(body.get("entity"))
    files: list[str] = []
    if app_root:
        from services.blueprint.projection import project_middleware, project_public_resources
        files += list(project_public_resources(svc.doc, app_root).get("files") or [])
        try:
            files += list((project_middleware(svc.doc, app_root) or {}).get("files") or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[api] middleware projection failed: %s", exc)
    return {"applied": True, "api": str((api or {}).get("id") or ""), "method": body.get("method"), "path": body.get("path"),
            "permission": body.get("permission"), "served": served, "requirement": req.get("id"), "edited_paths": files}


def remove_api(svc: Any, ref: str, *, app_root: str | None = None, reasoning: Any = None) -> dict:
    want = (ref or "").strip().lower()
    rows = _live(svc.doc.get("apis"))
    api = next((a for a in rows if str(a.get("id") or "").lower() == want
                or f"{a.get('method')} {a.get('path')}".lower() == want or str(a.get("path") or "").lower() == want), None)
    if api is None:
        hits = [a for a in rows if want and want in f"{a.get('method')} {a.get('path')} {a.get('purpose')}".lower()]
        api = hits[0] if len(hits) == 1 else None
    if api is None:
        raise SectionChangeError(f"I cannot tell which endpoint {ref!r} means. They are: "
                                 + ("; ".join(f"{a.get('id')} {a.get('method')} {a.get('path')}" for a in rows) or "(none)") + ".")
    api["status"] = "DEPRECATED"
    svc.save()
    files: list[str] = []
    if app_root:
        from services.blueprint.projection import project_public_resources
        files += list(project_public_resources(svc.doc, app_root).get("files") or [])
    tell(reasoning, f"Retired {api.get('method')} {api.get('path')}.", "step")
    return {"applied": True, "api": str(api.get("id")), "method": api.get("method"), "path": api.get("path"), "edited_paths": files}


# --- integrations --------------------------------------------------------------------

def add_integration(svc: Any, request: str, *, executor: Any = None, reasoning: Any = None) -> dict:
    request = (request or "").strip()
    if not request:
        raise SectionChangeError("no integration was described.")
    req = record_requirement(svc, request, owner="integrations")
    existing = {str(i.get("name") or "").strip().lower() for i in _live(svc.doc.get("integrations"))}
    brief = ("THIS IS A CHANGE to an application that is already built.\n"
             f"The user asked for ONE new integration: \"{request}\". It satisfies {req.get('id')}.\n"
             f"Integrations that exist and are NOT to be returned: {names(_live(svc.doc.get('integrations')))}. "
             "Return exactly ONE `integrations` proposal: name, kind, provider, and `secretRefs` — the NAMES of the "
             "environment variables it needs (SENDGRID_API_KEY), never a value.")
    def keep(props):
        mine = [p for p in props if p.section == "integrations"
                and str((p.body or {}).get("name") or "").strip().lower() not in existing]
        return mine[:1] if len(mine) == 1 else []
    props, _ = rerun(svc, "integrations", brief=brief, request=request, interpretation=f"declare an integration: {request}",
                     keep=keep, executor=executor, reasoning=reasoning, app_root=None,
                     empty="return exactly ONE new integration and nothing else", say=f"Declaring an integration for: {request}.")
    body = props[0].body or {}
    row = next((i for i in _live(svc.doc.get("integrations")) if str(i.get("name") or "").strip().lower() == str(body.get("name") or "").strip().lower()), {})
    return {"applied": True, "integration": str(row.get("id") or ""), "name": body.get("name"), "kind": body.get("kind"),
            "provider": body.get("provider"), "secrets": list(body.get("secretRefs") or []), "requirement": req.get("id"),
            "edited_paths": []}


def remove_integration(svc: Any, ref: str, *, reasoning: Any = None) -> dict:
    rows = [i for i in (svc.doc.get("integrations") or []) if isinstance(i, dict)]
    row = find_named(rows, ref)
    if row is None:
        raise SectionChangeError(f"I cannot tell which integration {ref!r} means. They are: {names(rows)}.")
    row["status"] = "DEPRECATED"
    svc.save()
    tell(reasoning, f"Retired the integration {row.get('name')}.", "step")
    return {"applied": True, "integration": str(row.get("id")), "name": str(row.get("name")), "edited_paths": []}


# --- summaries and the envelope ---------------------------------------------------

def summary_of(verb: str, out: dict) -> str:
    if verb == "add_requirement":
        return (f"Recorded {out['requirement']}: \"{out['text']}\". Nothing implements it yet — say what screen or "
                "process should, or run Verify & Fix and I will hold the app to it.")
    if verb == "edit_requirement":
        s = f"Restated {out['requirement']}, recorded as {out['decision']}: \"{out['after']}\" (was: \"{out['before']}\")."
        if out.get("reauthored"):
            s += f" Re-authored against it: {', '.join(out['reauthored'])}."
        if out.get("failed"):
            s += " Refused: " + "; ".join(out["failed"]) + "."
        if not out.get("reauthored") and not out.get("failed"):
            s += " Nothing cites it yet."
        return s
    if verb == "remove_requirement":
        return f"Retired {out['requirement']}" + (f" and took it off {len(out['uncited'])} artifact(s)" if out.get("uncited") else "") + "."
    if verb == "edit_product":
        return (f"Revised the product ({', '.join(out['changed'])}); the application is now \"{out['name']}\"."
                + (f" {out['note']}" if out.get("note") else ""))
    if verb == "add_api":
        s = f"Declared {out['method']} {out['path']} ({out['api']}), guarded by {out.get('permission') or 'no permission'}, recorded as {out['requirement']}."
        s += (" The data engine serves it." if out.get("served") else
              " It is declared and guarded; a handler for it still has to be written — say what it should return.")
        return s
    if verb == "remove_api":
        return f"Retired {out['method']} {out['path']} ({out['api']})."
    if verb == "add_integration":
        # WRITTEN DOWN, NOT WIRED UP. This declares the integration and the
        # names of the secrets it would need; it changes no code, and the
        # application does not talk to the service until somebody builds that.
        # The reply used to stop at "Declared", which reads as "connected" to
        # anyone who asked for email to be sent.
        return (f"Recorded **{out['name']}** in the definition ({out['integration']}, "
                f"{out['kind']} via {out['provider'] or 'unspecified provider'}), "
                f"as {out['requirement']}."
                + (f"\n\nIt names these secrets, which have to be set in the environment: "
                   f"{', '.join('`%s`' % x for x in out['secrets'])}. Names only — no value ever "
                   "goes in the Blueprint." if out.get("secrets") else "")
                + "\n\nThis is a declaration, not a connection: nothing is sent or received "
                  "until a developer wires it up against those secrets.")
    return f"Retired the integration {out['name']} ({out['integration']})."


def run(output_dir: str, verb: str, *, text: str = "", change: str = "", reasoning: Any = None) -> dict:
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [], "reason": "this project has no Blueprint yet."}
    app_root = str(Path(output_dir) / "app")
    try:
        if verb == "add_requirement":
            out = add_requirement(svc, text, reasoning=reasoning)
        elif verb == "edit_requirement":
            out = edit_requirement(svc, text, change, app_root=app_root, reasoning=reasoning)
        elif verb == "remove_requirement":
            out = remove_requirement(svc, text, reasoning=reasoning)
        elif verb == "edit_product":
            out = edit_product(svc, change or text, app_root=app_root, reasoning=reasoning)
        elif verb == "add_api":
            out = add_api(svc, text, app_root=app_root, reasoning=reasoning)
        elif verb == "remove_api":
            out = remove_api(svc, text, app_root=app_root, reasoning=reasoning)
        elif verb == "add_integration":
            out = add_integration(svc, text, reasoning=reasoning)
        elif verb == "remove_integration":
            out = remove_integration(svc, text, reasoning=reasoning)
        else:
            return {"applied": False, "edited_paths": [], "reason": f"unknown verb {verb!r}"}
    except SectionChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[smith] %s failed", verb)
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out.get("edited_paths") or [], "diff_summary": summary_of(verb, out),
            "reason": "", **{k: v for k, v in out.items() if k != "edited_paths"}}


__all__ = ["add_requirement", "edit_requirement", "remove_requirement", "edit_product", "add_api", "remove_api",
           "add_integration", "remove_integration", "run", "summary_of", "PRODUCT_SCHEMA"]

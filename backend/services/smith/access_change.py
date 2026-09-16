"""Roles, permissions and who reaches which screen are Blueprint sections,
and Smith can change them.

"Add a Ward Manager role", "only admins can delete a nurse", "make Master
Data admin-only", "let anyone open the registration page without signing
in": the first two are `roles` / `permissions` / `security` — authored by
the `security` agent — and the last two are the pages' own `users` and
`access`. Nothing in the verb set touched any of them; the role tools wrote
`plan.json`, which a Blueprint-built app does not have.

One verb, `edit_access`, two steps. The `security` agent is re-run against
a brief: the ask, the model as it stands, keep everything the ask does not
touch, retire (status DEPRECATED) what it removes — a role not returned
would simply stay. Then a small structured call revises which roles reach
which screen, held to the roles and pages that exist. Both are committed
through the Blueprint; the middleware, the public resources, the entity
access map, the launch roles and the seed accounts are re-projected.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.llm_client import tell
from services.smith.section_change import SectionChangeError, record_requirement, rerun

logger = logging.getLogger(__name__)

NODE = "security"

PAGE_ACCESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page": {"type": "string", "description": "the page id"},
                    "access": {"type": "string", "enum": ["public", "authenticated"]},
                    "roles": {"type": "array", "items": {"type": "string"},
                              "description": "role NAMES that may open it; empty = every signed-in role"},
                },
                "required": ["page", "access", "roles"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string"},
    },
    "required": ["pages"],
    "additionalProperties": False,
}


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("status") != "DEPRECATED"]


def _client() -> Any:
    from services.blueprint.executors import AGENT_MODEL, AnthropicModel
    return AnthropicModel(model=AGENT_MODEL, effort="medium")


def _model_lines(doc: dict) -> str:
    roles = _live(doc.get("roles"))
    perms = {str(p.get("id")): p for p in _live(doc.get("permissions"))}
    lines = []
    for r in roles:
        ps = ", ".join(f"{perms[p].get('action')} {perms[p].get('name')}" for p in (r.get("permissions") or []) if p in perms)
        lines.append(f"- {r.get('name')} ({r.get('id')}): {ps or 'no permissions'}")
    sec = doc.get("security") or {}
    lines.append(f"- authentication: {sec.get('authentication')}, rbac: {sec.get('rbac')}")
    return "\n".join(lines)


def _pages_lines(doc: dict) -> list[dict]:
    roles = {str(r.get("id")): str(r.get("name")) for r in _live(doc.get("roles"))}
    return [{"id": str(p.get("id")), "route": str(p.get("route") or ""), "name": str(p.get("name") or ""),
             "access": str(p.get("access") or "authenticated"),
             "roles": [roles.get(str(u), str(u)) for u in (p.get("users") or [])]}
            for p in _live(doc.get("pages"))]


def _check_page_access(svc: Any, entries: list[dict]) -> tuple[list[tuple[dict, str, list[str]]], list[str]]:
    """The revision held to the roles and pages that exist: (resolved
    entries, problems). Nothing is written here — a revision with one bad
    entry is refused whole and asked again, not half-applied."""
    roles_by_name = {str(r.get("name") or "").strip().lower(): str(r.get("id")) for r in _live(svc.doc.get("roles"))}
    pages = {str(p.get("id")): p for p in _live(svc.doc.get("pages"))}
    resolved, problems = [], []
    for e in entries:
        page = pages.get(str(e.get("page") or ""))
        if page is None:
            problems.append(f"{e.get('page')!r} is not a page of this application")
            continue
        ids = []
        for name in e.get("roles") or []:
            rid = roles_by_name.get(str(name).strip().lower())
            if rid is None:
                problems.append(f"{name!r} is not a role of this application (roles: {', '.join(roles_by_name) or 'none'})")
            else:
                ids.append(rid)
        access = str(e.get("access") or "authenticated")
        if access not in ("public", "authenticated"):
            problems.append(f"access {access!r} is not public or authenticated")
        resolved.append((page, access, ids))
    return resolved, problems


def _apply_page_access(svc: Any, resolved: list[tuple[dict, str, list[str]]]) -> list[str]:
    """The pages' `users`/`access` as the revision says; the routes that changed."""
    from services.blueprint.ids import page_key
    changed = []
    for page, access, ids in resolved:
        if access == page.get("access", "authenticated") and sorted(ids) == sorted(str(u) for u in (page.get("users") or [])):
            continue
        body = {k: v for k, v in page.items() if k != "id"}
        body["access"] = access
        body["users"] = ids
        svc.upsert("pages", body, natural_key=page_key(str(page.get("route") or "")))
        changed.append(str(page.get("route")))
    if changed:
        svc.save()
    return changed


def _project(svc: Any, app_root: str | None) -> list[str]:
    if not app_root:
        return []
    from services.blueprint.projection import (
        project_entity_access, project_launch_roles, project_middleware, project_public_resources, project_seed,
    )
    files: list[str] = []
    for fn in (project_middleware, project_public_resources, project_entity_access, project_launch_roles):
        try:
            files += list((fn(svc.doc, app_root) or {}).get("files") or [])
        except Exception as exc:  # noqa: BLE001 — a projector that cannot run here is said, not hidden
            logger.warning("[access] %s failed: %s", fn.__name__, exc)
    try:
        project_seed(svc.doc, app_root)
        files.append("src/db/seed.json")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[access] project_seed failed: %s", exc)
    return sorted(set(files))


def change_access(svc: Any, change: str, *, app_root: str | None = None, executor: Any = None,
                  client: Any = None, reasoning: Any = None) -> dict:
    change = (change or "").strip()
    if not change:
        raise SectionChangeError("nothing was described, so there is nothing to change about access.")
    roles_before = [str(r.get("name")) for r in _live(svc.doc.get("roles"))]
    req = record_requirement(svc, change, owner="security")

    # 1. roles, permissions, security — the agent that owns them
    brief = (
        "THIS IS A CHANGE to an application that is already built, not a first authoring.\n"
        f"The user asked: \"{change}\". It satisfies {req.get('id')} — cite it in what you add or change.\n"
        f"The access model as it stands:\n{_model_lines(svc.doc)}\n"
        "Return the roles, permissions and security as they should be AFTER the change. Keep every "
        "role and permission the ask does not touch exactly as it is, under its existing name (the "
        "name is its identity). A role or permission the ask removes is returned with `status: "
        "\"DEPRECATED\"` — one you do not return simply stays. Where the ask restricts an action to "
        "a role, give that role the permission and take it from the others. If the ask only concerns "
        "which screens a role may open, return the model unchanged: that is decided in the next step."
    )
    def keep(props):
        return [p for p in props if p.section in ("roles", "permissions", "security")]
    rerun(svc, NODE, brief=brief, request=change, interpretation=f"change access: {change}", keep=keep,
          executor=executor, reasoning=reasoning, app_root=app_root,
          say=f"Re-deciding roles and permissions: {change}.")

    # 2. which roles reach which screen — held to the roles that now exist
    call = client or _client()
    system = (
        "You revise which roles may open which screens of an application that is already built, "
        "and whether a screen needs a sign-in at all.\n"
        "Rules: change ONLY what the request asks; every other page keeps its access and roles. "
        "`access` is \"public\" (no sign-in) or \"authenticated\". `roles` names the roles that may "
        "open the page, from the roles given; an empty list means every signed-in role. Return "
        "every page, changed or not. Say in `note` anything that could not be done."
    )
    user = (f"The request: \"{change}\".\n\nThe roles: {', '.join(str(r.get('name')) for r in _live(svc.doc.get('roles'))) or '(none)'}\n\n"
            f"The pages as they stand:\n{json.dumps(_pages_lines(svc.doc), indent=1)}\n\nReturn the pages as they should be.")
    feedback = ""
    changed: list[str] = []
    note = ""
    for attempt in range(1, 3):
        tell(reasoning, f"Deciding which roles reach which screen: {change}.", "step")
        raw = call(system=system, user=user + (f"\n\nYour previous answer was refused:\n{feedback}" if feedback else ""),
                   schema=PAGE_ACCESS_SCHEMA)
        try:
            data = json.loads(str(getattr(raw, "text", raw)))
        except ValueError as exc:
            feedback = f"not JSON: {exc}"
            continue
        resolved, problems = _check_page_access(svc, data.get("pages") or [])
        note = str(data.get("note") or "").strip()
        if not problems:
            changed = _apply_page_access(svc, resolved)
            break
        feedback = "; ".join(problems)
        if attempt == 2:
            raise SectionChangeError(f"the screen access came back wrong twice: {feedback}")
    roles_after = [str(r.get("name")) for r in _live(svc.doc.get("roles"))]
    files = _project(svc, app_root)
    if changed and app_root:
        from services.blueprint.projection import apply_frontend_projection
        files += [str(f) for f in (apply_frontend_projection(svc, app_root) or {}).get("files", [])]
    return {"applied": True, "requirement": req.get("id"), "roles_before": roles_before, "roles_after": roles_after,
            "pages_changed": changed, "pages": _pages_lines(svc.doc), "model": _model_lines(svc.doc),
            "note": note, "edited_paths": sorted(set(files))}


def summary_of(out: dict, change: str) -> str:
    s = f"Changed access for \"{change}\", recorded as {out['requirement']}. Roles now: {', '.join(out['roles_after']) or 'none'}"
    if out["roles_after"] != out["roles_before"]:
        s += f" (were: {', '.join(out['roles_before']) or 'none'})"
    s += "."
    if out.get("pages_changed"):
        who = {p["route"]: p for p in out["pages"]}
        parts = []
        for route in out["pages_changed"]:
            p = who.get(route) or {}
            parts.append(f"{route} → {p.get('access')}" + (f" for {', '.join(p.get('roles') or [])}" if p.get("roles") else ""))
        s += " Screens: " + "; ".join(parts) + "."
    if out.get("note"):
        s += f" {out['note']}"
    return s


def run(output_dir: str, change: str, *, reasoning: Any = None) -> dict:
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [], "reason": "this project has no Blueprint yet, so there is no access model to change."}
    app_root = str(Path(output_dir) / "app")
    try:
        out = change_access(svc, change, app_root=app_root, reasoning=reasoning)
    except SectionChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[smith] access change failed")
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out["edited_paths"], "diff_summary": summary_of(out, change), "reason": ""}


__all__ = ["change_access", "run", "summary_of", "PAGE_ACCESS_SCHEMA"]

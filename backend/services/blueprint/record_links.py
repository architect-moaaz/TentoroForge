"""Where a record lives: the address that opens one record of an entity.

A screen's panel opens a record by its link parameter (`/ops/support?ticket=
<id>`, `sections[].param`); an application built before screens opens it on a
record page (`/orders/[id]`). Either is an address something can link to — a
notification above all: "your order is out for delivery" opened nothing,
because nothing knew where an order lives (Mozato, forge-v3, 2026-10-06).
"""
from __future__ import annotations

import re
from typing import Any

_ID_SEGMENT = re.compile(r"\[[^\]/]+\]")


def _live(rows: Any) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict) and r.get("status") != "DEPRECATED"]


def _opens(page: dict, roles: set[str] | None) -> bool:
    """Whether a person of one of `roles` (role ids) may open `page`; `None`
    is someone unknown, who may open only what everyone signed in may."""
    users = {str(u) for u in page.get("users") or []}
    if roles is None or not users:
        return str(page.get("access") or "") != "role_restricted" or bool(roles and users & roles)
    return bool(users & roles)


def record_address(doc: dict, entity_id: str, roles: set[str] | None = None, *,
                   anyone: bool = True) -> str | None:
    """`/screen?param={id}` or `/records/{id}` for `entity_id`, with `{id}`
    where the record's id goes — or None when no screen opens one. With
    `anyone=False`, only a screen a person of `roles` may open."""
    pages = [p for p in _live(doc.get("pages")) if anyone or _opens(p, roles)]
    for page in pages:
        for sec in page.get("sections") or []:
            if isinstance(sec, dict) and sec.get("placement") == "panel" and sec.get("param") \
                    and str(sec.get("entity") or "") == entity_id and page.get("route"):
                return f"{str(page['route']).split('?')[0]}?{sec['param']}={{id}}"
    for page in pages:
        route = str(page.get("route") or "")
        if str((page.get("data") or {}).get("primaryEntity") or "") == entity_id \
                and len(_ID_SEGMENT.findall(route)) == 1 and route.rstrip("/").endswith("]"):
            return _ID_SEGMENT.sub("{id}", route)
    return None


def entity_id_of(doc: dict, ref: Any) -> str:
    """An entity's id from its id, name or table."""
    ref = str(ref or "").strip()
    for e in (doc.get("data") or {}).get("entities") or []:
        if isinstance(e, dict) and ref and ref in (str(e.get("id")), str(e.get("name")), str(e.get("table"))):
            return str(e.get("id"))
    return ""


def _role_ids(doc: dict, refs: Any) -> set[str]:
    out = set()
    for ref in refs if isinstance(refs, (list, tuple, set)) else [refs]:
        for r in _live(doc.get("roles")):
            if str(ref or "").strip().lower() in (str(r.get("id")).lower(), str(r.get("name") or "").lower()):
                out.add(str(r.get("id")))
    return out


def recipient_roles(doc: dict, config: dict, workflow: dict | None = None) -> set[str] | None:
    """The roles of who a notification reaches, as role ids — `None` when the
    definition does not say. A role it is sent to; the person running the
    workflow, whose roles are its screens' people; a person's own record,
    who is whoever signs up (`signup_role`)."""
    if config.get("recipientRole"):
        return _role_ids(doc, config["recipientRole"]) or None
    recipient = str(config.get("recipient") or "")
    if "$user" in recipient and workflow is not None:
        pages = {str(p.get("id")): p for p in _live(doc.get("pages"))}
        runners: set[str] = set()
        for pid in workflow.get("launchedFrom") or []:
            users = {str(u) for u in (pages.get(str(pid)) or {}).get("users") or []}
            if not users:
                return None                  # started where anyone may: anyone runs it
            runners |= users
        return runners or None
    if recipient:
        from services.blueprint.account_model import signup_role
        role = signup_role(doc)
        return _role_ids(doc, role) if role else None
    return None


def notification_link(doc: dict, step: dict, config: dict, workflow: dict | None = None) -> str | None:
    """The link a `send_notification` step stores: the address of the record
    it is about (`entityId`, of the step's entity or the config's `entity`),
    on a screen the person it reaches may open. A customer told their account
    was activated was sent to the administrators' customer list — a 403 —
    because the only screen that opened a customer was the admin's
    (ToroCommerce, forge-v3, 2026-10-07): no link is better than that one."""
    if str(config.get("actionType") or "") != "send_notification" or config.get("link"):
        return None
    record = config.get("entityId")
    entity = entity_id_of(doc, config.get("entity") or step.get("entity"))
    if not record or not entity:
        return None
    address = record_address(doc, entity, recipient_roles(doc, config, workflow), anyone=False)
    return address.replace("{id}", str(record)) if address else None

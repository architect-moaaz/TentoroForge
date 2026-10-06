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


def record_address(doc: dict, entity_id: str) -> str | None:
    """`/screen?param={id}` or `/records/{id}` for `entity_id`, with `{id}`
    where the record's id goes — or None when no screen opens one."""
    pages = _live(doc.get("pages"))
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


def notification_link(doc: dict, step: dict, config: dict) -> str | None:
    """The link a `send_notification` step stores: the address of the record
    it is about (`entityId`, of the step's entity or the config's `entity`)."""
    if str(config.get("actionType") or "") != "send_notification" or config.get("link"):
        return None
    record = config.get("entityId")
    entity = entity_id_of(doc, config.get("entity") or step.get("entity"))
    if not record or not entity:
        return None
    address = record_address(doc, entity)
    return address.replace("{id}", str(record)) if address else None

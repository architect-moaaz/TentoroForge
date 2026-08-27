"""Entity shape classification — which entities deserve standalone screens.

A PURE JOIN entity (e.g. ``SessionSpeaker``: two FKs, at most one nullable
attribute scalar, lifecycle timestamps) is an implementation detail of a
many-to-many relationship. It must never surface as its own top-level
screen or sidebar item — its UX belongs inline on a parent detail page
(assign a speaker FROM the session page). This module is the single
authority the menu derivation, the create-route scaffolder, and the
delivery gate all consult, so "is this a join table?" can't drift
between passes.

Live origin: qeqorfii (Event Management Platform) shipped a top-level
``/session-speaker`` page + sidebar item for its SessionSpeaker join
table — a database detail leaking into the app's IA.
"""
from __future__ import annotations

import re
from typing import Any

from services.entity_names import entity_key

# Column names that never count against the "pure join" shape.
_LIFECYCLE = {
    "id", "createdat", "updatedat", "deletedat", "created_at", "updated_at",
    "deleted_at", "createdon", "updatedon",
}

# Scalar names commonly used as the single attribute ON a join row
# (speaker's role in a session, item position in a list…). One of these —
# even NOT NULL — doesn't make the join a first-class entity.
_JOIN_ATTRS = {
    "role", "order", "position", "rank", "sort", "sortorder", "sort_order",
    "notes", "note", "label", "status", "isprimary", "is_primary", "primary",
    "quantity", "weight",
}


def _fields_of(entity_def: Any) -> list[dict]:
    """Accept both plan shapes: ``{"fields": [...]}`` and a bare list."""
    if isinstance(entity_def, dict):
        f = entity_def.get("fields") or entity_def.get("columns")
        return [x for x in f if isinstance(x, dict)] if isinstance(f, list) else []
    if isinstance(entity_def, list):
        return [x for x in entity_def if isinstance(x, dict)]
    return []


def is_join_entity(entity_def: Any) -> bool:
    """True when the entity is a pure M:N join.

    Shape test: at least two FK columns, and every remaining column is a
    primary key, a lifecycle timestamp, or at most ONE join-attribute
    scalar (``role`` / ``order`` / … — or any single nullable scalar).
    A second real scalar means the entity carries domain data of its own
    (e.g. an Enrollment with grade + completedAt) and deserves screens.
    """
    fields = _fields_of(entity_def)
    if not fields:
        return False
    fks = [f for f in fields if isinstance(f.get("fk"), dict)]
    if len(fks) < 2:
        return False
    extras: list[dict] = []
    for f in fields:
        if isinstance(f.get("fk"), dict) or f.get("primaryKey"):
            continue
        name = str(f.get("name") or "").lower()
        if name in _LIFECYCLE:
            continue
        extras.append(f)
    if not extras:
        return True
    if len(extras) == 1:
        f = extras[0]
        name = str(f.get("name") or "").lower()
        return name in _JOIN_ATTRS or not f.get("not_null")
    return False


def join_entities(plan: dict | None) -> set[str]:
    """Names of every pure-join entity declared in the plan."""
    if not isinstance(plan, dict):
        return set()
    ents = plan.get("entities")
    out: set[str] = set()
    if isinstance(ents, dict):
        for name, edef in ents.items():
            if is_join_entity(edef):
                out.add(str(name))
    elif isinstance(ents, list):
        for e in ents:
            if isinstance(e, dict) and is_join_entity(e) and e.get("name"):
                out.add(str(e["name"]))
    return out


def _slug_variants(name: str, table: str | None = None) -> set[str]:
    """Every route-slug spelling a join entity might surface under:
    ``SessionSpeaker`` → session-speaker, session-speakers, sessionspeaker(s),
    session_speaker(s) — plus its table name verbatim + hyphenated."""
    out: set[str] = set()
    kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    flat = kebab.replace("-", "")
    snake = kebab.replace("-", "_")
    for base in (kebab, flat, snake):
        out.add(base)
        out.add(base + "s")
        if base.endswith("y"):
            out.add(base[:-1] + "ies")
    if table:
        t = str(table).lower()
        out.add(t)
        out.add(t.replace("_", "-"))
    return out


def join_route_slugs(plan: dict | None) -> set[str]:
    """Top-route slugs (no leading slash) that belong to join entities."""
    if not isinstance(plan, dict):
        return set()
    ents = plan.get("entities")
    out: set[str] = set()
    items: list[tuple[str, Any]] = []
    if isinstance(ents, dict):
        items = list(ents.items())
    elif isinstance(ents, list):
        items = [(str(e.get("name") or ""), e) for e in ents if isinstance(e, dict)]
    for name, edef in items:
        if name and is_join_entity(edef):
            table = edef.get("table") if isinstance(edef, dict) else None
            out |= _slug_variants(name, table)
    return out


def entity_slug_keys(plan: dict | None) -> set[str]:
    """Singular comparison keys (via the naming authority) for every plan
    entity — used to test whether a route stem is entity-backed at all."""
    if not isinstance(plan, dict):
        return set()
    ents = plan.get("entities")
    names: list[str] = []
    if isinstance(ents, dict):
        for name, edef in ents.items():
            names.append(str(name))
            if isinstance(edef, dict) and edef.get("table"):
                names.append(str(edef["table"]))
    elif isinstance(ents, list):
        for e in ents:
            if isinstance(e, dict):
                if e.get("name"):
                    names.append(str(e["name"]))
                if e.get("table"):
                    names.append(str(e["table"]))
    out: set[str] = set()
    for n in names:
        try:
            out.add(entity_key(n))
        except Exception:  # noqa: BLE001 — unusable name is just skipped
            continue
    return out


__all__ = [
    "is_join_entity", "join_entities", "join_route_slugs", "entity_slug_keys",
]

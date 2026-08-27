"""Deterministic ResourceTimeline adoption.

The schema agent knows ResourceTimeline exists (it's in the context-engine contracts)
but defaults to a Table for reservation/booking pages anyway. Steering it via the
prompt is unreliable, so this detects the *shape* of a resource-scheduling domain
from the entity schema and guarantees a ResourceTimeline on the matching page —
independent of what the LLM chose.

Shape of a schedulable domain: an ITEM entity with a date RANGE (two date fields)
plus a foreign key to a RESOURCE entity (room / unit / staff / vehicle / …).

TODO(spec-d-w2): the ``entity.schedulable_by`` planner-precedence branch is
already wired below, but the planner agent doesn't yet emit that field.
Once the planner emission ships, the regex/word-list fallback path (and its
``_RESOURCE_WORDS`` / ``_PERSON_WORDS`` / ``_SCHED_ROUTE_WORDS`` tables)
can be deleted and this module shrunk to a plan-reader.
"""
from __future__ import annotations

import re

_DATE_TYPES = ("date", "timestamp", "datetime", "timestamptz")
# Entity names that read as a bookable *resource* (the timeline's rows).
_RESOURCE_WORDS = (
    "room", "unit", "vehicle", "car", "table", "court", "bay", "desk", "space",
    "asset", "equipment", "provider", "staff", "employee", "doctor", "technician",
    "resource", "property", "apartment", "seat", "station", "machine", "chair",
)
# Entity names that read as the *person/customer* on the booking (the bar title).
_PERSON_WORDS = ("guest", "customer", "client", "patient", "member", "user", "tenant", "rider", "passenger")


def _as_fields(entity: dict) -> dict:
    """Normalize an entity's fields (dict OR list-of-dicts) to {name: meta}."""
    f = entity.get("fields") if isinstance(entity, dict) else None
    if isinstance(f, dict):
        return f
    out: dict = {}
    if isinstance(f, list):
        for item in f:
            if isinstance(item, dict) and item.get("name"):
                out[item["name"]] = item
            elif isinstance(item, str):
                out[item] = {}
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _fk_target(field_name: str, entities: dict) -> str | None:
    """`roomId` → the entity named Room/Rooms, if one exists."""
    m = re.match(r"^(.*?)(?:_?id|Id)$", field_name)
    if not m or not m.group(1):
        return None
    base = _norm(m.group(1))
    for name in entities:
        n = _norm(name)
        if n == base or n == base + "s" or n.rstrip("s") == base:
            return name
    return None


def _pick(fields: dict, *patterns: str) -> str | None:
    for name in fields:
        low = name.lower()
        if any(p in low for p in patterns):
            return name
    return None


def detect_scheduler(entities: dict) -> dict | None:
    """Return the ResourceTimeline field mapping for a schedulable domain, or None.

    Precedence (Spec D W2 — planner-authored `schedulable_by` wins):
      0. When any entity carries ``schedulable_by == "resource"``, treat it as
         the RESOURCE entity and pair it with the best-fit ITEM entity (an
         entity with a date range and an FK to the flagged resource).
         When ``schedulable_by == "person"`` the entity is the ITEM-side
         "person" attribute — we still fall through to the regex path but
         bias the item-loop to entities flagged as such when nothing else
         resolves. An explicit ``False``/``"none"`` opts a schedulable-shaped
         entity out (returns None outright — the domain isn't schedulable).

      1. Otherwise, the legacy regex/word-list classifier runs unchanged.
    """
    entities = entities or {}

    # Spec D W2 — planner-authored precedence.
    explicit_resource: str | None = None
    explicit_person_entities: set[str] = set()
    explicit_none = False
    for _name, _ent in entities.items():
        if not isinstance(_ent, dict):
            continue
        sb = _ent.get("schedulable_by")
        if sb is False or (isinstance(sb, str) and sb.strip().lower() in ("none", "false", "no")):
            explicit_none = True
        elif isinstance(sb, str):
            v = sb.strip().lower()
            if v == "resource" and explicit_resource is None:
                explicit_resource = _name
            elif v == "person":
                explicit_person_entities.add(_name)

    if explicit_none and not explicit_resource:
        # Planner said this domain isn't schedulable — respect it verbatim.
        return None

    if explicit_resource:
        res_ent = entities.get(explicit_resource) or {}
        res_fields = _as_fields(res_ent)
        # Find the best ITEM: a peer entity with ≥2 date fields + an FK
        # naming the explicit resource entity.
        for item_name, item in entities.items():
            if item_name == explicit_resource or not isinstance(item, dict):
                continue
            fields = _as_fields(item)
            date_fields = [n for n, meta in fields.items()
                           if str((meta or {}).get("type", "")).lower() in _DATE_TYPES
                           or any(k in n.lower() for k in ("date", "start", "end", "checkin", "checkout"))]
            fks = [n for n in fields if re.search(r"(_id|Id)$", n) and n.lower() not in ("id",)]
            if len(date_fields) < 2 or not fks:
                continue
            resource_fk = None
            for fk in fks:
                if _fk_target(fk, entities) == explicit_resource:
                    resource_fk = fk
                    break
            if not resource_fk:
                continue
            person_fk = next((fk for fk in fks
                              if (t := _fk_target(fk, entities))
                              and (t in explicit_person_entities
                                   or any(w in _norm(t) for w in _PERSON_WORDS))), None)
            return {
                "itemEntity": item_name,
                "resourceEntity": explicit_resource,
                "startField": date_fields[0],
                "endField": date_fields[1],
                "itemResourceField": resource_fk,
                "titleField": (_pick(fields, "name", "title", "label")
                               or (person_fk[:-2] + "Name" if person_fk else None)
                               or person_fk),
                "statusField": _pick(fields, "status", "state"),
                "resourceLabelField": _pick(res_fields, "number", "name", "label", "title", "code"),
                "resourceGroupField": _pick(res_fields, "type", "category", "group", "floor", "class"),
                "reason": "planner:resource",
            }
        # Planner marked a resource but no viable item entity — fall through
        # so the legacy path still gets a chance (it may pick a different pair).

    for item_name, item in entities.items():
        fields = _as_fields(item)
        date_fields = [n for n, meta in fields.items()
                       if str((meta or {}).get("type", "")).lower() in _DATE_TYPES
                       or any(k in n.lower() for k in ("date", "start", "end", "checkin", "checkout"))]
        fks = [n for n in fields if re.search(r"(_id|Id)$", n) and n.lower() not in ("id",)]
        if len(date_fields) < 2 or not fks:
            continue

        # Resource FK: target entity name reads like a bookable resource.
        resource_fk = resource_ent = None
        for fk in fks:
            tgt = _fk_target(fk, entities)
            if tgt and any(w in _norm(tgt) for w in _RESOURCE_WORDS):
                resource_fk, resource_ent = fk, tgt
                break
        if not resource_fk:
            continue

        res_fields = _as_fields(entities.get(resource_ent, {}))
        # A person FK on the item → a good bar title ("guest").
        person_fk = next((fk for fk in fks
                          if (t := _fk_target(fk, entities)) and any(w in _norm(t) for w in _PERSON_WORDS)), None)
        return {
            "itemEntity": item_name,
            "resourceEntity": resource_ent,
            "startField": date_fields[0],
            "endField": date_fields[1],
            "itemResourceField": resource_fk,
            "titleField": (_pick(fields, "name", "title", "label")
                           or (person_fk[:-2] + "Name" if person_fk else None)
                           or person_fk),
            "statusField": _pick(fields, "status", "state"),
            "resourceLabelField": _pick(res_fields, "number", "name", "label", "title", "code"),
            "resourceGroupField": _pick(res_fields, "type", "category", "group", "floor", "class"),
        }
    return None


def build_resource_timeline(mapping: dict, source_hint: str | None = None) -> dict:
    """Construct a ResourceTimeline schema node from a detected mapping."""
    res_src = _plural(mapping["resourceEntity"])
    item_src = _plural(mapping["itemEntity"])
    props = {
        "resources": f"{{{{{res_src}}}}}",
        "items": f"{{{{{item_src}}}}}",
        "itemResourceField": mapping["itemResourceField"],
        "startField": mapping["startField"],
        "endField": mapping["endField"],
    }
    for key in ("titleField", "statusField", "resourceLabelField", "resourceGroupField"):
        if mapping.get(key):
            props[key] = mapping[key]
    props["itemHref"] = f"/{item_src}/{{id}}"
    return {"type": "ResourceTimeline", "props": props}


def _plural(name: str) -> str:
    """Data-source key the renderer expects. Delegates to the canonical
    naming authority (:mod:`services.entity_names`) so this stage
    agrees byte-for-byte with the list/kanban/calendar/form builders."""
    from services.entity_names import derive_names
    return derive_names(name).sourceName


_SCHED_ROUTE_WORDS = ("calendar", "timeline", "schedule", "reservation", "booking",
                      "availability", "roster", "shift", "occupancy")


def is_scheduler_route(route: str, mapping: dict | None = None) -> bool:
    """A LIST/index page that should show the timeline: its route reads
    scheduler-ish, or it's the item entity's own list page (e.g. /reservations).
    Form/detail sub-routes (/new, /edit, /[id]) are excluded — a create form or a
    single record must not get a rooms×days grid."""
    parts = [s for s in str(route or "").strip("/").split("/") if s]
    if parts and (parts[-1] in ("new", "edit") or parts[-1].startswith("[")
                  or parts[-1].startswith(":") or "{{" in parts[-1]):
        return False
    low = _norm(route or "")
    if any(w in low for w in _SCHED_ROUTE_WORDS):
        return True
    return bool(mapping and _norm(mapping["itemEntity"]) in low)


def _has_resource_timeline(node) -> bool:
    if isinstance(node, dict):
        if node.get("type") == "ResourceTimeline":
            return True
        for k in ("children", "root"):
            if k in node and _has_resource_timeline(node[k]):
                return True
    elif isinstance(node, list):
        return any(_has_resource_timeline(n) for n in node)
    return False


def ensure_scheduler_view(schema: dict, node: dict) -> tuple[dict, bool]:
    """Guarantee a ResourceTimeline on the page: no-op if one exists, else insert
    the built node as the primary content (after a leading Heading/Hero). Any
    existing Table stays below as a secondary list."""
    if not isinstance(schema, dict) or _has_resource_timeline(schema):
        return schema, False
    root = schema.get("root")
    if not isinstance(root, dict):
        return schema, False
    kids = root.get("children")
    if not isinstance(kids, list):
        kids = []
        root["children"] = kids
    idx = 1 if (kids and isinstance(kids[0], dict)
                and kids[0].get("type") in ("Heading", "Hero")) else 0
    kids.insert(idx, node)
    return schema, True

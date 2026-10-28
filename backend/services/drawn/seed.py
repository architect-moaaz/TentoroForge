"""The drawing's example content as the app's first records.

A drawn page opens on what the drawing shows — "Al Noor Specialist Hospital,
Employer · Professional, 3 of 3" — only if those records exist. The binder
returns them as records of the entities (`seed`); they are loaded the one way
this codebase loads rows, as a declared import the app's own seeder applies
once (`smith.data_import.apply`), coerced to each field's type, and a value a
field cannot hold is left out and counted, never guessed.

THE ROWS POINT AT EACH OTHER. The drawing's tenant is on the Professional
plan, so its row names that plan — "plan-professional", the sample's own id,
or "Professional", its name. Each row is given a uuid of its own here, made
from what makes it unique (the plan's name, the tenant's code), and every
reference is led to the uuid of the row it names; one that names no row is
left empty when the field may be, and the row is left out when it may not.
A row two pages both draw (the plans) gets the same uuid and is loaded once,
and a parent's rows load before its children's (the seeder applies the files
in name order). Without this every child row failed its foreign key and the
drawn pages opened on "0 tenants" (d6drawn, 2026-10-28).
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

#: The namespace every drawn row's uuid is made in: the same row, the same id.
NAMESPACE = uuid.UUID("5d0c9a52-6f7e-4c1e-9b4a-d7a1f0e3c2b8")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
#: Fields that name a row the way a person would, when no field is declared unique.
LABELS = ("name", "code", "email", "fullName", "title", "label", "key", "slug")


def _entity(doc: dict, name: str) -> dict | None:
    key = str(name or "").strip().lower()
    for e in (doc.get("data") or {}).get("entities") or []:
        if isinstance(e, dict) and e.get("status") != "DEPRECATED" and key in (
                str(e.get("name") or "").lower(), str(e.get("table") or "").lower(), str(e.get("id") or "").lower()):
            return e
    return None


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def parents(doc: dict, entity_id: str) -> dict[str, str]:
    """``{field: parent entity id}`` — the entity's references, read the way
    the sample data reads them (`projection._link_target`): the declared
    relationship, else the entity the field is named for (`tenantId` → Tenant,
    which TrustSignal's relationship left undeclared)."""
    from services.blueprint.projection import _link_target

    entity = next((e for e in (doc.get("data") or {}).get("entities") or []
                   if isinstance(e, dict) and str(e.get("id")) == entity_id), None)
    out = {}
    for field in (entity or {}).get("fields") or []:
        if isinstance(field, dict) and field.get("name"):
            target = _link_target(doc, entity, field)
            if target:
                out[str(field["name"])] = target
    return out


def depth(doc: dict, entity_id: str, _seen: frozenset = frozenset()) -> int:
    """How many references deep an entity sits: its rows load after its parents'."""
    if entity_id in _seen:
        return 0
    ups = [p for p in parents(doc, entity_id).values() if p != entity_id]
    return 1 + max((depth(doc, p, _seen | {entity_id}) for p in ups), default=-1)


def _unique(entity: dict) -> list[str]:
    fields = [f for f in entity.get("fields") or [] if isinstance(f, dict) and f.get("name")]
    declared = [str(f["name"]) for f in fields if f.get("unique") and f["name"] != "id"]
    names = {str(f["name"]) for f in fields}
    return declared + [n for n in LABELS if n in names and n not in declared]


def _aliases(row: dict, entity: dict) -> set[str]:
    """What a reference to this row may say: its sample id or any name it has."""
    out = {_norm(row.get("id"))} | {_norm(row.get(k)) for k in _unique(entity)}
    return {a for a in out if a}


def _identity(row: dict, entity: dict) -> str:
    """What makes the row the row: its first unique value, else its sample id,
    else everything it holds."""
    for key in _unique(entity):
        if row.get(key) not in (None, ""):
            return f"{key}={_norm(row[key])}"
    if row.get("id") not in (None, ""):
        return f"id={_norm(row['id'])}"
    return json.dumps(row, sort_keys=True, default=str)


def resolve(value: Any, parent: dict, known: dict[str, str]) -> str | None:
    """The uuid of the parent row a reference names, or None.

    ``known`` is ``{alias: uuid}`` for the parent's drawn rows. "plan-premium"
    names the plan "Premium" too: the parent's own name is a prefix samples
    put on their ids."""
    text = str(value or "").strip()
    if not text:
        return None
    if UUID_RE.match(text) and text in known.values():
        return text
    key = _norm(text)
    if key in known:
        return known[key]
    for prefix in {_norm(parent.get("name")), _norm(parent.get("table")), _norm(str(parent.get("table") or "")[:-1])}:
        if prefix and key.startswith(prefix) and key[len(prefix):] in known:
            return known[key[len(prefix):]]
    return None


def _drawn_rows(app_root: str | None, doc: dict) -> dict[str, dict[str, str]]:
    """``{entity id: {alias: uuid}}`` for the rows earlier drawn pages loaded."""
    from services.smith.data_import import payload_path

    out: dict[str, dict[str, str]] = {}
    if not app_root:
        return out
    for item in (doc.get("data") or {}).get("imports") or []:
        if not str(item.get("id") or "").startswith("drawn-"):
            continue
        try:
            payload = json.loads(payload_path(app_root, str(item["id"])).read_text("utf-8"))
        except (OSError, ValueError):
            continue
        known = out.setdefault(str(item.get("entity") or ""), {})
        for rid, aliases in (payload.get("aliases") or {}).items():
            known[_norm(rid)] = rid
            for a in aliases:
                known.setdefault(str(a), rid)
    return out


def record(svc: Any, seed: dict, *, page_id: str, app_root: str | None) -> list[str]:
    """Load each entity's drawn rows, parents first. Returns one line per entity loaded."""
    from services.smith.data_import import Rejected, apply, coerce, table_of

    doc = svc.doc
    known = _drawn_rows(app_root, doc)
    batches = [(e, rows) for name, rows in (seed or {}).items()
               if (e := _entity(doc, name)) is not None and isinstance(rows, list) and rows]
    batches.sort(key=lambda b: depth(doc, str(b[0].get("id"))))

    # Every row's uuid first, so a reference to a row later in the seed resolves.
    for entity, rows in batches:
        mine = known.setdefault(str(entity.get("id")), {})
        for row in rows:
            if isinstance(row, dict):
                rid = str(uuid.uuid5(NAMESPACE, f"{entity.get('id')}:{_identity(row, entity)}"))
                mine[_norm(rid)] = rid
                for a in _aliases(row, entity):
                    mine.setdefault(a, rid)

    said: list[str] = []
    for entity, rows in batches:
        eid = str(entity.get("id"))
        fields = {str(f.get("name")): f for f in entity.get("fields") or [] if isinstance(f, dict) and f.get("name")}
        refs = parents(doc, eid)
        loaded = {r for item in (doc.get("data") or {}).get("imports") or []
                  if str(item.get("entity")) == eid and str(item.get("id", "")).startswith("drawn-")
                  for r in _loaded_ids(app_root, str(item["id"]))}
        accepted, rejects, used, aliases, seen = [], [], set(), {}, set()
        for i, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            rid = str(uuid.uuid5(NAMESPACE, f"{eid}:{_identity(row, entity)}"))
            if rid in loaded or rid in seen:
                continue                      # another page, or this one, already drew it
            out: dict[str, Any] = {"id": rid}
            dropped = None
            for key, value in row.items():
                field = fields.get(str(key))
                if field is None or str(key) == "id":
                    continue
                if str(key) in refs:
                    parent = _entity(doc, refs[str(key)]) or {}
                    target = resolve(value, parent, known.get(refs[str(key)], {}))
                    if target is None and value not in (None, ""):
                        if field.get("required"):
                            dropped = f"{key} names {value!r}, which is no {parent.get('name') or 'record'} drawn"
                            break
                        rejects.append({"row": i, "why": f"{key}: {value!r} names no drawn row"})
                    if target is not None:
                        out[str(key)] = target
                        used.add(str(key))
                    continue
                value = coerce(value, field)
                if isinstance(value, Rejected):
                    rejects.append({"row": i, "why": str(value)})
                    continue
                out[str(key)] = value
                used.add(str(key))
            if dropped:
                rejects.append({"row": i, "why": dropped})
                # Its children, loaded after it, must not point at it either.
                mine = known.get(eid, {})
                for a in [a for a, v in mine.items() if v == rid]:
                    del mine[a]
                continue
            if len(out) > 1:
                accepted.append(out)
                seen.add(rid)
                aliases[rid] = sorted(_aliases(row, entity))
        if not accepted:
            continue
        digest = hashlib.sha1(json.dumps([page_id, eid, accepted], sort_keys=True,
                                         default=str).encode()).hexdigest()[:12]
        # The seeder applies the files in name order: the depth leads the name.
        report = {"import_id": f"drawn-{depth(doc, eid):02d}-{digest}", "source": "the design's example content",
                  "entity": eid, "entity_name": str(entity.get("name") or ""),
                  "table": table_of(entity), "columns": [{"column": k, "field": k} for k in sorted(used)],
                  "ignored": [], "unmapped": [], "db_owned": [], "required_missing": [],
                  "rows": accepted, "rejects": rejects}
        if any(str(i.get("id")) == report["import_id"] for i in (doc.get("data") or {}).get("imports") or []):
            continue
        try:
            apply(svc, report, app_root=app_root)
            _keep_aliases(app_root, report["import_id"], aliases)
        except Exception as exc:  # noqa: BLE001 — sample rows are a help, never the reason a page fails
            said.append(f"{entity.get('name')}: not loaded ({type(exc).__name__}: {str(exc)[:120]})")
            continue
        said.append(f"{entity.get('name')}: {len(accepted)} drawn row(s)" + (f", {len(rejects)} left out"
                                                                              if rejects else ""))
    return said


def _loaded_ids(app_root: str | None, import_id: str) -> set[str]:
    from services.smith.data_import import payload_path

    if not app_root:
        return set()
    try:
        payload = json.loads(payload_path(app_root, import_id).read_text("utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(r.get("id")) for r in payload.get("rows") or [] if isinstance(r, dict) and r.get("id")}


def _keep_aliases(app_root: str | None, import_id: str, aliases: dict[str, list[str]]) -> None:
    """What each row was called in the drawing, beside its rows, so a later
    page's reference to it resolves. The seeder reads only `rows`."""
    from services.smith.data_import import payload_path

    if not app_root:
        return
    path = Path(payload_path(app_root, import_id))
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return
    payload["aliases"] = aliases
    path.write_text(json.dumps(payload, indent=2) + "\n", "utf-8")

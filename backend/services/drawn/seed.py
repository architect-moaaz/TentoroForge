"""The drawing's example content as the app's first records.

A drawn page opens on what the drawing shows — "Al Noor Specialist Hospital,
Employer · Professional, 3 of 3" — only if those records exist. The binder
returns them as records of the entities (`seed`); they are loaded the one way
this codebase loads rows, as a declared import the app's own seeder applies
once (`smith.data_import.apply`), coerced to each field's type, and a value a
field cannot hold is left out and counted, never guessed.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _entity(doc: dict, name: str) -> dict | None:
    key = str(name or "").strip().lower()
    for e in (doc.get("data") or {}).get("entities") or []:
        if isinstance(e, dict) and e.get("status") != "DEPRECATED" and key in (
                str(e.get("name") or "").lower(), str(e.get("table") or "").lower(), str(e.get("id") or "").lower()):
            return e
    return None


def record(svc: Any, seed: dict, *, page_id: str, app_root: str | None) -> list[str]:
    """Load each entity's drawn rows. Returns one line per entity loaded."""
    from services.smith.data_import import Rejected, apply, coerce, table_of

    said: list[str] = []
    for name, rows in (seed or {}).items():
        entity = _entity(svc.doc, name)
        if entity is None or not isinstance(rows, list) or not rows:
            continue
        fields = {str(f.get("name")): f for f in entity.get("fields") or [] if isinstance(f, dict) and f.get("name")}
        accepted, rejects, used = [], [], set()
        for i, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            out = {}
            for key, value in row.items():
                field = fields.get(str(key))
                if field is None or str(key) == "id":
                    continue
                value = coerce(value, field)
                if isinstance(value, Rejected):
                    rejects.append({"row": i, "why": str(value)})
                    continue
                out[str(key)] = value
                used.add(str(key))
            if out:
                accepted.append(out)
        if not accepted:
            continue
        digest = hashlib.sha1(json.dumps([page_id, entity.get("id"), accepted], sort_keys=True,
                                         default=str).encode()).hexdigest()[:12]
        report = {"import_id": f"drawn-{digest}", "source": "the design's example content",
                  "entity": str(entity.get("id") or ""), "entity_name": str(entity.get("name") or ""),
                  "table": table_of(entity), "columns": [{"column": k, "field": k} for k in sorted(used)],
                  "ignored": [], "unmapped": [], "db_owned": [], "required_missing": [],
                  "rows": accepted, "rejects": rejects}
        if any(str(i.get("id")) == report["import_id"] for i in (svc.doc.get("data") or {}).get("imports") or []):
            continue
        try:
            apply(svc, report, app_root=app_root)
        except Exception as exc:  # noqa: BLE001 — sample rows are a help, never the reason a page fails
            said.append(f"{entity.get('name')}: not loaded ({type(exc).__name__}: {str(exc)[:120]})")
            continue
        said.append(f"{entity.get('name')}: {len(accepted)} drawn row(s)" + (f", {len(rejects)} value(s) left out"
                                                                              if rejects else ""))
    return said

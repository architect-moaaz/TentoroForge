"""The renames an application's database has to make, in order.

`drizzle-kit push` cannot tell a renamed column from a dropped one and a new
one; it asks, and in a build nobody answers — it crashed, exited 0, and left
the old name under code reading the new one (database tests, 2026-10-01).
What made the rename knows it is one, so it writes it here; the app's
`prepare-schema` applies each where the old name is still there and the new
one is not, so every database — the preview's, the published one however
many deploys behind — gets each rename exactly once, with its data.

`src/db/migrations.json` is the application's, not a projection: it is
appended to, never rewritten from the Blueprint, and nothing deletes it.
"""
from __future__ import annotations

import json
from pathlib import Path

LEDGER = "src/db/migrations.json"


def _load(app_root: str | Path) -> dict:
    try:
        data = json.loads((Path(app_root) / LEDGER).read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(app_root: str | Path, data: dict) -> str:
    path = Path(app_root) / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", "utf-8")
    return LEDGER


def column_renamed(app_root: str | Path, table: str, old: str, new: str) -> str:
    """Record `table.old` -> `table.new`; returns the ledger's path."""
    data = _load(app_root)
    rows = data.setdefault("columns", [])
    entry = {"table": table, "from": old, "to": new}
    if old != new and entry not in rows:
        rows.append(entry)
    return _save(app_root, data)


def table_renamed(app_root: str | Path, old: str, new: str) -> str:
    """Record table `old` -> `new`; later column renames name the new table."""
    data = _load(app_root)
    rows = data.setdefault("tables", [])
    entry = {"from": old, "to": new}
    if old != new and entry not in rows:
        rows.append(entry)
    for c in data.get("columns") or []:
        if c.get("table") == old:
            c["table"] = new
    return _save(app_root, data)


def renames(app_root: str | Path) -> dict:
    return _load(app_root)


__all__ = ["LEDGER", "column_renamed", "table_renamed", "renames"]

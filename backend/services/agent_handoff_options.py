"""Who could handle a handoff in this app: its roles, and the people who hold them.

The human-handoff box in the builder is filled in from this: roles come from the Blueprint, people from the
app's own users table. Reading the people is best-effort (the app's database may not be running on this
machine); the answer says so and the builder falls back to typing a role.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from services.agent_runtime_install import resolve_roots


def _blueprint_roles(project_root: Path) -> list[str]:
    try:
        doc = json.loads((project_root / ".forge" / "blueprint" / "current.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    names = [str(r.get("name")) for r in (doc.get("roles") or [])
             if isinstance(r, dict) and r.get("name") and r.get("status") != "DEPRECATED"]
    seen: set[str] = set()
    return [n for n in names if not (n.lower() in seen or seen.add(n.lower()))]


def _database_url(app_root: Path) -> str | None:
    for name in (".env.local", ".env"):
        try:
            text = (app_root / name).read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r"^DATABASE_URL=(\S+)", text, re.M)
        if m:
            return m.group(1)
    return None


def _people(app_root: Path) -> tuple[list[dict[str, Any]], str | None]:
    url = _database_url(app_root)
    if not url:
        return [], "This app has no database address, so its people could not be listed."
    try:
        import psycopg2
        import psycopg2.extras

        con = psycopg2.connect(url, connect_timeout=3)
        try:
            cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM users LIMIT 300")
            rows = cur.fetchall()
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001 — the builder works without the list
        return [], f"The app's people could not be listed ({type(exc).__name__}); is its database running? You can still pick roles."
    out = []
    for r in rows:
        if r.get("is_active") is False or not r.get("id"):
            continue
        out.append({"id": str(r["id"]),
                    "name": str(r.get("display_name") or r.get("name") or r.get("full_name") or r.get("email") or r["id"]),
                    "role": str(r["role"]) if r.get("role") else None})
    out.sort(key=lambda p: p["name"].lower())
    return out, None


def handoff_options(output_dir: str | Path) -> dict[str, Any]:
    project_root, app_root = resolve_roots(output_dir)
    roles = _blueprint_roles(project_root)
    people, note = _people(app_root) if (app_root / "package.json").is_file() else ([], "The app is not built yet, so its people could not be listed.")
    # a role someone already holds counts even when the Blueprint does not list it
    for p in people:
        if p["role"] and p["role"].lower() not in {r.lower() for r in roles}:
            roles.append(p["role"])
    return {"roles": roles, "people": people, "peopleNote": note}

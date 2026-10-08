"""What a process wrote is read back where a person would look for it.

"Add a child" saved every child, and the process trials passed it: the insert
ran and the row was there. "My Children" showed none — its read failed on the
record type's name and came back empty — and two testers added the same child
six times before giving up (forge-v3, 2026-09-27). A save is only half of what
a person does; the other half is looking for what they saved.

So after a process passes its trial, each record it created or changed is
looked for, as the same person, on the pages that show that record type: its
own detail page, and the list when the list is short enough to hold every row.
A record it deleted must be gone from its detail page. The page is fetched as
the server renders it; only when the name is not in that HTML is it opened in
a browser, for a page that draws its data after it loads. What is not where it
should be goes to Smith with the process's own account, like any failed run.

Only records a person can recognise are looked for — by the record type's
label (`labelField`), a name or a title. A row with no such value, and a type
no page shows to this person, has nothing to look for.
"""
from __future__ import annotations

import html
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

#: A list longer than this may not show a new row on its first page, so it is
#: not held to showing it; the record's own page still is.
LIST_HOLDS = 20

_SCRIPT = re.compile(r"<(script|style|noscript|template)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_FORM = re.compile(r"/(new|create|add|edit|update)$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_PLATFORM = ("forge_", "workflow_", "_forge", "users", "accounts", "sessions")


def written(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, list[dict]]]:
    """`{table: {"added": [row], "removed": [row]}}` between two snapshots of
    `trials._snapshot` (rows as JSON text; a large table is only a count)."""
    out: dict[str, dict[str, list[dict]]] = {}
    for table in sorted(set(before) | set(after)):
        b, a = before.get(table), after.get(table)
        if not isinstance(b, (set, frozenset)) or not isinstance(a, (set, frozenset)):
            continue
        added, removed = a - b, b - a
        if not added and not removed:
            continue

        def rows(texts: set) -> list[dict]:
            got = []
            for t in sorted(texts):
                try:
                    got.append(json.loads(t))
                except ValueError:
                    continue
            return got
        out[table] = {"added": rows(added), "removed": rows(removed)}
    return out


def _entity(doc: dict, table: str) -> dict | None:
    from services.blueprint.projection import to_snake
    for e in (doc.get("data") or {}).get("entities") or []:
        if isinstance(e, dict) and e.get("status") != "DEPRECATED" \
                and (e.get("table") or to_snake(e.get("name") or "")) == table:
            return e
    return None


def label_of(entity: dict, row: dict) -> str:
    """The value a person knows this record by, or ""."""
    from services.blueprint.projection import to_snake
    fields = [f for f in entity.get("fields") or [] if isinstance(f, dict)]
    names = [str(entity.get("labelField") or "")] + [
        str(f.get("name")) for f in fields
        if re.search(r"(^|_)(name|title)$|[a-z](Name|Title)$", str(f.get("name") or ""))]
    for name in names:
        if not name:
            continue
        value = row.get(to_snake(name), row.get(name))
        text = str(value).strip() if value is not None else ""
        if len(text) >= 2 and not _UUID.match(text):
            return text
    return ""


def _opens(doc: dict, page: dict, role: str) -> bool:
    """Whether `role` (a name; "" for the administrator) is someone the page is for."""
    from services.blueprint.account_model import admin_role
    users = [str(u) for u in page.get("users") or []]
    if not users:
        return True
    ids = {str(r.get("name") or "").lower(): str(r.get("id")) for r in doc.get("roles") or [] if isinstance(r, dict)}
    who = (role or admin_role(doc) or "").lower()
    return ids.get(who, who) in users or who in [u.lower() for u in users]


def pages_for(doc: dict, entity: dict, role: str) -> tuple[list[str], list[str]]:
    """`(list routes, detail routes)` that show `entity` to `role`."""
    lists, details = [], []
    for p in doc.get("pages") or []:
        if not isinstance(p, dict) or p.get("status") == "DEPRECATED" or not p.get("route"):
            continue
        if str((p.get("data") or {}).get("primaryEntity") or "") != str(entity.get("id")):
            continue
        if p.get("pattern") == "auth" or not _opens(doc, p, role):
            continue
        route = str(p["route"])
        params = re.findall(r"\[[^\]]+\]", route)
        if _FORM.search(route.rstrip("/")):
            continue                     # a form to fill in, not somewhere a record is shown
        if not params:
            lists.append(route)
        elif len(params) == 1:
            details.append(route)
    return lists, details


def visible(page_html: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", _SCRIPT.sub(" ", page_html))).split())


def _seen(bench: Any, doc: dict, route: str, as_: str, jar: list[dict], label: str) -> tuple[bool, str]:
    """Whether `label` is on the page, and what the page showed."""
    from services.smith.trials import _http
    app = bench.app()
    status, where, body = _http(app, "GET", route, None, jar)
    if status >= 400 or where:
        return False, f"HTTP {status}" + (f", sent on to {where}" if where else "")
    text = visible(body)
    if label.lower() in text.lower():
        return True, ""
    # A page that draws its data after it loads: ask a browser.
    try:
        from pathlib import Path

        from services.blueprint.page_review import run_shots
        from services.smith.trials import _role
        name, is_admin = _role(doc, as_)
        entry: dict[str, Any] = {"id": "read-back", "route": route, "as": name or "signed out"}
        if not is_admin:
            entry["cookies"] = jar
        shot = run_shots(app, [entry], Path(bench.output_dir) / ".forge" / "trials" / "read-back",
                         probe=False, states=False)[0]
        drawn = " ".join(str(shot.get("text") or "").split())
        if label.lower() in drawn.lower():
            return True, ""
        text = drawn or text
    except Exception as exc:  # noqa: BLE001 — the server's HTML stands as the answer
        logger.info("[round-trips] browser read of %s failed: %s", route, exc)
    return False, f"HTTP {status}; the page shows: {text[:400] or '(nothing)'}"


def _count(bench: Any, table: str) -> int:
    from services.blueprint.page_review import _query
    rows = _query(bench.app(), 'select count(*) from "' + table.replace('"', '""') + '"')
    try:
        return int(rows[0][0])
    except (IndexError, TypeError, ValueError):
        return LIST_HOLDS + 1


def read_back(bench: Any, doc: dict, as_: str) -> list[str]:
    """What the last `try_workflow` on `bench` wrote and the person who ran it
    cannot then see: one line each."""
    from services.smith.trials import _role, _session
    problems: list[str] = []
    try:
        role, _is_admin = _role(doc, as_)
    except ValueError:
        return []
    snapshots = getattr(bench, "last_written", None)
    if not snapshots:
        return []
    who, jar = _session(bench.app(), doc, as_, getattr(bench, "guest", None))
    bench.server_said()
    for table, rows in written(*snapshots).items():
        if table.startswith(_PLATFORM):
            continue
        entity = _entity(doc, table)
        if entity is None:
            continue
        lists, details = pages_for(doc, entity, role)
        if not lists and not details:
            continue
        kind = str(entity.get("name") or table)
        added_ids = {str(r.get("id")) for r in rows["added"]}
        for row in rows["added"]:
            label = label_of(entity, row)
            rid = str(row.get("id") or "")
            if not label:
                continue
            for route in details:
                if not rid:
                    break
                path = re.sub(r"\[[^\]]+\]", rid, route)
                ok, shown = _seen(bench, doc, path, as_, jar, label)
                if not ok:
                    problems.append(f"{kind} \"{label}\" was written, but its page {path} as {who} does not show it ({shown}).")
            if lists and _count(bench, table) <= LIST_HOLDS:
                for route in lists:
                    ok, shown = _seen(bench, doc, route, as_, jar, label)
                    if not ok:
                        problems.append(f"{kind} \"{label}\" was written, but {route} as {who} does not list it ({shown}).")
        for row in rows["removed"]:
            rid = str(row.get("id") or "")
            label = label_of(entity, row)
            if not rid or rid in added_ids or not label:
                continue                 # a changed row, read back above
            for route in details:
                path = re.sub(r"\[[^\]]+\]", rid, route)
                ok, _shown = _seen(bench, doc, path, as_, jar, label)
                if ok:
                    problems.append(f"{kind} \"{label}\" was deleted, but {path} as {who} still shows it.")
    said_after = bench.server_said()
    swallowed = [l for l in said_after if "[forge:swallowed]" in l]
    if swallowed:
        problems.append("Reading it back, the server said: " + " | ".join(swallowed[:3]))
    return problems


__all__ = ["LIST_HOLDS", "label_of", "pages_for", "read_back", "visible", "written"]

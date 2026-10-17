"""Where things live: the application's ids mapped to the files that hold
them, read off the tree.

The Blueprint says what the Receipts screen does and who may open it; it
does not say that the fault behind "receipts are blank" lives in
`app/src/app/(dashboard)/payments/receipts/load.ts`. Smith discovered that
each time by listing directories — five steps before the first read
(qpqhdugb, 2026-10-16). The index is deterministic and cheap: a glob over
the app, matched to the definition's routes, process names and record
types. It goes on every turn's page, so the first read is the right file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

APP = "app"
#: Screens listed before the index is trimmed to those the ask names.
MAX_SCREENS = 40


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _route_of(view: Path, app_src: Path) -> str:
    rel = view.parent.relative_to(app_src / "app")
    parts = [p for p in rel.parts if not (p.startswith("(") and p.endswith(")"))]
    if parts == ["_root"] or not parts:
        return "/"
    return "/" + "/".join(parts)


def screens(output_dir: str | Path) -> dict[str, str]:
    """route -> directory (relative to the project root) for every screen
    the app has a view for."""
    app_src = Path(output_dir) / APP / "src"
    out: dict[str, str] = {}
    if not (app_src / "app").is_dir():
        return out
    for view in sorted((app_src / "app").rglob("view.tsx")):
        route = _route_of(view, app_src)
        out.setdefault(route, str(view.parent.relative_to(Path(output_dir))))
    return out


def processes(output_dir: str | Path) -> dict[str, str]:
    """normalised name/stem -> file for every process definition."""
    folder = Path(output_dir) / APP / "src" / "lib" / "workflows" / "definitions"
    out: dict[str, str] = {}
    if folder.is_dir():
        for f in sorted(folder.glob("*.json")):
            out[_norm(f.stem)] = str(f.relative_to(Path(output_dir)))
    return out


def tables(output_dir: str | Path) -> dict[str, str]:
    """normalised stem -> db schema file."""
    folder = Path(output_dir) / APP / "src" / "db" / "schema"
    out: dict[str, str] = {}
    if folder.is_dir():
        for f in sorted(folder.glob("*.ts")):
            if f.stem.startswith("_forge") or f.stem == "index":
                continue
            out[_norm(f.stem)] = str(f.relative_to(Path(output_dir)))
    return out


def _doc(output_dir: str | Path, doc: dict | None) -> dict:
    if doc:
        return doc
    try:
        return json.loads((Path(output_dir) / ".forge" / "blueprint" / "current.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _match(wanted: list[str], table: dict[str, str]) -> str:
    for w in wanted:
        n = _norm(w)
        if n and n in table:
            return table[n]
    for w in wanted:
        n = _norm(w)
        if not n:
            continue
        for k, v in table.items():
            if k and (k in n or n in k) and min(len(k), len(n)) >= 4:
                return v
    return ""


def _singular(word: str) -> str:
    w = word
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith("ses") or w.endswith("xes"):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def index(output_dir: str | Path, doc: dict | None = None, *, ask: str = "") -> str:
    """The block for the page; "" when there is no app on disk."""
    root = Path(output_dir)
    if not (root / APP / "src").is_dir():
        return ""
    d = _doc(output_dir, doc)
    by_route = screens(output_dir)
    flows = processes(output_dir)
    schema = tables(output_dir)
    words = {w for w in re.findall(r"[a-z0-9]+", (ask or "").lower()) if len(w) >= 3}
    lines: list[str] = []

    pages = [p for p in d.get("pages") or [] if isinstance(p, dict) and p.get("status") != "DEPRECATED"]
    rows = []
    for p in pages:
        route = str(p.get("route") or "")
        folder = by_route.get(route)
        if not folder:
            continue
        files = ["view.tsx"] + (["load.ts"] if (root / folder / "load.ts").is_file() else [])
        named = any(w in _norm(route) or w in _norm(p.get("name")) for w in words)
        rows.append((not named, f"- screen {route} ({p.get('id')}, {p.get('name')}): {folder}/{{{', '.join(files)}}}"))
    rows.sort(key=lambda r: r[0])
    shown = [r[1] for r in rows[:MAX_SCREENS]]
    lines += shown
    if len(rows) > MAX_SCREENS:
        lines.append(f"- … and {len(rows) - MAX_SCREENS} more screens under app/src/app/ (same shape: <route>/view.tsx, load.ts)")

    for w in d.get("workflows") or []:
        if not isinstance(w, dict) or w.get("status") == "DEPRECATED":
            continue
        f = _match([str(w.get("id") or ""), str(w.get("name") or "")], flows)
        if f:
            lines.append(f"- process {w.get('name')} ({w.get('id')}): {f}")

    for e in (d.get("data") or {}).get("entities") or []:
        if not isinstance(e, dict) or e.get("status") == "DEPRECATED":
            continue
        name, table = str(e.get("name") or ""), str(e.get("table") or "")
        f = _match([name, _singular(table), table], schema)
        schemas_dir = root / APP / "src" / "schemas" / table
        extra = f"; its screens' schemas: app/src/schemas/{table}/" if table and schemas_dir.is_dir() else ""
        if f or extra:
            lines.append(f"- record type {name} ({e.get('id')}, table {table or '?'}): {f or 'no schema file found'}{extra}")

    if not lines:
        return ""
    head = ("WHERE THINGS LIVE (paths from the project root; read the file named here first — "
            "do not list directories to find it):")
    tail = ["- the frame around every screen: app/src/app/_root/view.tsx; sign-in pages: app/src/app/login, "
            "register, signup; the API the screens call: app/src/app/api/",
            "- the definition itself: .forge/blueprint/current.json — `read_section` for pages, workflows, "
            "data.entities, designSystem, navigation, flows, requirements, decisions"]
    return "\n".join([head, *lines, *tail])


__all__ = ["index", "screens", "processes", "tables"]

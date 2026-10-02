"""What just landed, in one line a person can read.

The run panel used to show a subject as a coloured cell and an id
("ENTITY-003 written"); what it was — a Doctor with nine fields, a page at
/admin/doctors — was in the Blueprint and nowhere a watcher could see it.
Each fan-out subject now lands with a summary read off the document it was
just written into, so the build is watched as the application taking shape
rather than as ids ticking over.
"""
from __future__ import annotations

from typing import Any

_LIVE = lambda rows: [r for r in (rows or []) if isinstance(r, dict) and r.get("status") != "DEPRECATED"]  # noqa: E731


def _by_id(rows: Any, ident: str) -> dict | None:
    return next((r for r in _LIVE(rows) if str(r.get("id")) == ident), None)


def _names(items: Any, key: str = "name", limit: int = 4) -> str:
    names = [str(i.get(key) or i.get("label") or "") for i in (items or []) if isinstance(i, dict)]
    names = [n for n in names if n]
    if not names:
        return ""
    shown = ", ".join(names[:limit])
    return shown + (f" +{len(names) - limit}" if len(names) > limit else "")


def summarize_subject(doc: dict, node: str, subject: str) -> str:
    """One line for the subject `node` just wrote, or "" when there is
    nothing readable to say. Never raises: a summary is a courtesy."""
    try:
        return _summarize(doc or {}, str(node or ""), str(subject or ""))
    except Exception:  # noqa: BLE001 — never the reason a subject fails
        return ""


def _summarize(doc: dict, node: str, subject: str) -> str:
    data = doc.get("data") or {}
    if node == "entity_fields":
        ent = _by_id(data.get("entities"), subject)
        if ent:
            fields = _LIVE(ent.get("fields"))
            return f"{ent.get('name')} — {len(fields)} field{'s' if len(fields) != 1 else ''}" \
                   + (f": {_names(fields)}" if fields else "")
    if node in ("page_details", "page_code", "page_layouts"):
        # A page_details subject is a feature part (`ENTITY-003~2`) or a page.
        pid = subject.split("~")[0]
        page = _by_id(doc.get("pages"), pid)
        if page is None:
            pages = [p for p in _LIVE(doc.get("pages")) if str(p.get("feature") or "") == pid
                     or str((p.get("data") or {}).get("primaryEntity") or "") == pid]
            if pages:
                return f"{len(pages)} page{'s' if len(pages) != 1 else ''}: " \
                       + ", ".join(str(p.get("route") or p.get("name") or "") for p in pages[:4])
            return ""
        if node == "page_code":
            row = next((r for r in _LIVE(doc.get("pageCode")) if str(r.get("page")) == pid), None)
            size = len(str(row.get("view") or "")) + len(str(row.get("load") or "")) if row else 0
            return f"{page.get('name')} · {page.get('route')}" + (f" — {size // 1000}k chars of React" if size else "")
        return f"{page.get('name')} · {page.get('route')}" + (f" — {page.get('pattern')}" if page.get("pattern") else "")
    if node == "workflow_steps":
        wf = _by_id(doc.get("workflows"), subject)
        if wf:
            steps = _LIVE(wf.get("steps"))
            return f"{wf.get('name')} — {len(steps)} step{'s' if len(steps) != 1 else ''}" \
                   + (f": {_names(steps)}" if steps else "")
    if node == "analytics":
        page = _by_id(doc.get("pages"), subject)
        widgets = [w for w in _LIVE(doc.get("widgets")) if str(w.get("page")) == subject]
        if page and widgets:
            return f"{page.get('name')} — {len(widgets)} widget{'s' if len(widgets) != 1 else ''}: {_names(widgets, 'label')}"
    if node == "data_model":
        ents = _LIVE(data.get("entities"))
        if ents:
            return f"{len(ents)} entities: {_names(ents, limit=6)}"
    if node == "page_contracts":
        pages = _LIVE(doc.get("pages"))
        if pages:
            return f"{len(pages)} pages: {_names(pages, limit=5)}"
    if node == "workflows":
        wfs = _LIVE(doc.get("workflows"))
        if wfs:
            return f"{len(wfs)} workflows: {_names(wfs, limit=5)}"
    if node == "design_system":
        ds = doc.get("designSystem") or {}
        colors = ds.get("colors") or {}
        shell = ds.get("shell") or {}
        bits = [b for b in (f"primary {colors.get('primary')}" if colors.get("primary") else "",
                            f"accent {colors.get('accent')}" if colors.get("accent") else "",
                            str(shell.get("chrome") or ""), str(shell.get("tone") or "")) if b]
        return " · ".join(bits)
    return ""

"""Which screen each entry of a drawn menu opens (2026-10-31).

An application drawn from a design draws its own menu, one per portal, and
binds each entry to a page by the prototype's link, else by the page of the
same name. On DITANS 42 of 67 entries led nowhere — "Talent pools", "Saved
searches" and the rest had no link and no page of that name — and each was
bound by hand, in the drawing's row (`drawnViews[shell].sample.nav[].href`),
by someone who could edit JSON. This is the same act as a tool: see what each
entry opens, then say which screen it should, and the menu is projected again.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _shells(doc: dict) -> list[dict]:
    from services.drawn.project import _shells as shells
    return shells(doc)


def _pick(doc: dict, ref: str) -> dict | None:
    """A shell by its portal, its name or its key — any word of it."""
    ref = (ref or "").strip().lower()
    shells = _shells(doc)
    if not ref:
        return shells[0] if len(shells) == 1 else None
    for field in ("name", "portal", "key"):
        hit = [s for s in shells if str(s.get(field) or "").strip().lower() == ref]
        if len(hit) == 1:
            return hit[0]
    hit = [s for s in shells if ref in " ".join(str(s.get(f) or "") for f in ("name", "portal", "key")).lower()]
    return hit[0] if len(hit) == 1 else None


def table(doc: dict, shell: dict) -> list[str]:
    """Each entry and the screen it opens, `→ nowhere` when it opens none."""
    from services.drawn.project import nav_routes

    names = {str(p.get("route")): str(p.get("name") or "") for p in doc.get("pages") or [] if isinstance(p, dict)}
    out = []
    for e in nav_routes(doc, shell):
        href = str(e.get("href") or "#")
        where = f"{names.get(href, '')} ({href})".strip() if href != "#" else "nowhere ✗"
        section = f"[{e['section']}] " if e.get("section") else ""
        out.append(f"  {section}\"{e.get('label')}\" → {where}")
    return out


def bind_menu(output_dir: str, shell_ref: str, entries: list[dict]) -> dict:
    """Bind entries of a drawn menu to screens: `[{label, route}]`. With no
    entries, only says what each entry opens. One version; the menu is
    projected again from the drawing's row."""
    from services.blueprint.service import BlueprintService
    from services.drawn.project import project_drawn

    def finding(text: str) -> dict:
        return {"applied": False, "said": text, "finding": text, "touched": [], "version": 0}

    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return finding("This project has no Blueprint, so there is no menu to bind.")
    shells = _shells(svc.doc)
    if not shells:
        return finding("This application draws no menu of its own — its menu is `navigation` "
                       "(`write_section` on `navigation`).")
    shell = _pick(svc.doc, shell_ref)
    if shell is None:
        return finding("Say which drawn menu with `shell` — one of: "
                       + "; ".join(f"\"{s.get('portal') or s.get('name')}\" ({s.get('name')})" for s in shells) + ".")
    who = str(shell.get("portal") or shell.get("name"))
    entries = [e for e in entries or [] if isinstance(e, dict) and str(e.get("label") or "").strip()]
    if not entries:
        lines = table(svc.doc, shell)
        nowhere = sum("nowhere" in l for l in lines)
        said = f"The menu of {who} ({len(lines)} entries, {nowhere} leading nowhere):\n" + "\n".join(lines)
        # A LOOK, NOT A CHANGE: an observation for the next step, never a line of the reply.
        return {"applied": False, "touched": [], "version": 0, "finding": said, "said": said}
    live = {str(p.get("route")): p for p in svc.doc.get("pages") or []
            if isinstance(p, dict) and p.get("status") != "DEPRECATED" and p.get("route")}
    before = svc.snapshot()
    rows = [r for r in (shell.get("sample") or {}).get("nav") or [] if isinstance(r, dict)]
    done, refused = [], []
    for e in entries:
        label, route = str(e["label"]).strip(), str(e.get("route") or "").strip()
        row = next((r for r in rows if str(r.get("label") or "").strip().lower() == label.lower()), None)
        if row is None:
            refused.append(f"\"{label}\" is not an entry of this menu")
        elif route and route not in live:
            refused.append(f"\"{label}\": `{route}` is not a screen of this application")
        else:
            if route:
                row["href"] = route
            else:
                row.pop("href", None)
            done.append(f"\"{label}\" → {route or 'as the drawing links it'}")
    if not done:
        svc.doc = before
        return finding("Nothing was bound: " + "; ".join(refused) + ".")
    for view in svc.doc.get("drawnViews") or []:
        if isinstance(view, dict) and view.get("key") == shell.get("key"):
            view["sample"] = {**(view.get("sample") or {}), "nav": rows}
    svc.validate()
    record = svc.commit(user_request=f"bind the {who} menu: " + "; ".join(done),
                        smith_interpretation="bind drawn menu entries to screens", before=before, affected=[])
    try:
        project_drawn(svc.doc, output_dir, Path(output_dir) / "app")
    except Exception as exc:  # noqa: BLE001 — the binding is kept; the next projection writes it
        logger.warning("[drawn_menu] the menu was bound but not projected: %s", exc)
    lines = table(svc.doc, next(s for s in _shells(svc.doc) if s.get("key") == shell.get("key")))
    left = [l for l in lines if "nowhere" in l]
    said = (f"Bound {len(done)} entr{'y' if len(done) == 1 else 'ies'} of the {who} menu (version {record['version']}): "
            + "; ".join(done) + "." + (f" Still leading nowhere ({len(left)}):\n" + "\n".join(left) if left else ""))
    return {"applied": True, "said": said, "finding": "; ".join(refused), "version": int(record["version"]),
            "touched": ["app/src/components/DrawnShell.tsx"]}


__all__ = ["bind_menu", "table"]

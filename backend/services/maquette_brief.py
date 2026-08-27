"""Render a persisted maquette as a design brief for the page author.

The maquettes are authored early (bootstrap band) and land on disk long
before any page is written — but nothing downstream read them until
post-generation, where a composer used them to *overwrite* whatever the
page author had produced. That ordering wasted the design twice: the
author worked without it, then had its work discarded by it.

This module turns the maquette into an INPUT. Given a route, it finds
the matching maquette and renders it as prose the page author can build
from: what this screen is, which columns in which order, the filter
chips, the empty state, the copy. The author still chooses the component
tree and the styling — the brief decides *what the screen is about*,
never *how it is assembled*.

Pure and fail-soft: unreadable or missing maquettes return "" so the
author works exactly as it did before.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONTRACTS = ("src", "contracts")
_DASHBOARD_TYPES = {"dashboard", "overview", "home"}


def _load(root: Path, name: str) -> Any:
    try:
        p = Path(root).joinpath(*_CONTRACTS, name)
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[maquette-brief] %s unreadable: %s", name, exc)
        return None


def _norm_route(r: str) -> str:
    r = str(r or "").strip()
    if not r.startswith("/"):
        r = "/" + r
    return r.rstrip("/") or "/"


def _match(entries: Any, route: str) -> dict | None:
    """Find the maquette authored for this exact route."""
    if not isinstance(entries, list):
        return None
    want = _norm_route(route)
    for e in entries:
        if isinstance(e, dict) and _norm_route(e.get("route", "")) == want:
            return e
    return None


# ── renderers ────────────────────────────────────────────────────────


def _columns_block(cols: Any) -> list[str]:
    out: list[str] = []
    for c in (cols or []):
        if not isinstance(c, dict) or not c.get("name"):
            continue
        bits = [f"  - {c['name']}"]
        if c.get("label"):
            bits.append(f'shown as "{c["label"]}"')
        if c.get("kind"):
            bits.append(f"as {c['kind']}")
        if c.get("emphasis"):
            bits.append("(the identifying column — lead with it)")
        out.append(" ".join(bits))
    return out


def _empty_block(es: Any) -> list[str]:
    if not isinstance(es, dict) or not es.get("headline"):
        return []
    out = [f'  headline: "{es["headline"]}"']
    if es.get("subhead"):
        out.append(f'  subhead:  "{es["subhead"]}"')
    if es.get("cta_label"):
        out.append(f'  action:   "{es["cta_label"]}"'
                   + (f" → {es['cta_action']}" if es.get("cta_action") else ""))
    if es.get("illustration"):
        out.append(f'  illustration: {es["illustration"]}')
    return out


def _collection_brief(m: dict) -> list[str]:
    L: list[str] = []
    if m.get("layout"):
        L.append(f"Shape: {m['layout']}")
    cols = _columns_block(m.get("columns"))
    if cols:
        L.append("Columns, in this order:")
        L += cols
    presets = [p for p in (m.get("filter_presets") or []) if isinstance(p, dict)]
    if presets:
        L.append("Filter chips: " + ", ".join(
            f"{p.get('label')} ({p.get('expr')})" for p in presets if p.get("label")))
    hero = m.get("hero")
    if isinstance(hero, dict) and hero.get("title"):
        L.append(f'Header: "{hero["title"]}"'
                 + (f' — "{hero["subtitle"]}"' if hero.get("subtitle") else ""))
    es = _empty_block(m.get("empty_state"))
    if es:
        L.append("When there are no rows:")
        L += es
    ft = m.get("footer")
    if isinstance(ft, dict) and ft.get("kind"):
        L.append(f"Below the list: {ft['kind']}"
                 + (f' — "{ft["content"]}"' if ft.get("content") else ""))
    if m.get("row_treatment"):
        L.append(f"Row treatment: {m['row_treatment']}")
    return L


def _record_brief(m: dict) -> list[str]:
    L: list[str] = []
    if m.get("mode"):
        L.append(f"Mode: {m['mode']}")
    hero = m.get("hero")
    if isinstance(hero, dict) and (hero.get("title") or hero.get("kind")):
        L.append(f"Header: {hero.get('kind', 'page-header')}"
                 + (f' — "{hero["title"]}"' if hero.get("title") else ""))
    secs = [s for s in (m.get("section_grouping") or []) if isinstance(s, dict)]
    if secs:
        L.append("Field groups, in this order:")
        for s in secs:
            fields = ", ".join(str(f) for f in (s.get("fields") or []))
            if s.get("label") and fields:
                L.append(f"  - {s['label']}: {fields}")
    hints = m.get("control_hints")
    if isinstance(hints, dict) and hints:
        L.append("Control overrides: " + ", ".join(
            f"{k} → {v}" for k, v in list(hints.items())[:8]))
    ft = m.get("footer")
    if isinstance(ft, dict) and ft.get("kind"):
        L.append(f"Below the fields: {ft['kind']}")
    return L


def _dashboard_brief(m: dict) -> list[str]:
    L: list[str] = []
    kpis = [k for k in (m.get("kpis") or []) if isinstance(k, dict)]
    if kpis:
        L.append("Metrics, in priority order:")
        for k in kpis:
            filt = f" where {k['filter']}" if k.get("filter") else ""
            fld = f" of {k['field']}" if k.get("field") else ""
            L.append(f"  - {k.get('label')}: {k.get('op', 'count')}{fld}"
                     f" on {k.get('entity')}{filt}")
    pc = m.get("primary_chart")
    if isinstance(pc, dict) and pc.get("title"):
        L.append(f"Primary chart: {pc.get('kind', 'bar')} — \"{pc['title']}\""
                 + (f" ({pc.get('entity')} grouped by {pc.get('group_by')})"
                    if pc.get("entity") else ""))
    if m.get("subtitle"):
        L.append(f'Subtitle: "{m["subtitle"]}"')
    es = _empty_block(m.get("empty_state"))
    if es:
        L.append("Before any data exists:")
        L += es
    return L


# ── entry point ──────────────────────────────────────────────────────


def build_maquette_brief(output_dir: Any, route: str,
                         page_type: str | None = None) -> str:
    """Return the design brief for ``route``, or "" when there is none.

    ``page_type`` only steers which file is consulted first; the route
    match is what decides. A page with no maquette gets no block, which
    is why this is safe to call unconditionally.
    """
    if not output_dir or not route:
        return ""
    root = Path(output_dir)
    ptype = str(page_type or "").strip().lower()
    body: list[str] = []
    kind = ""

    if _norm_route(route) == "/" or ptype in _DASHBOARD_TYPES:
        m = _load(root, "dashboard-maquette.json")
        if isinstance(m, dict) and m:
            body, kind = _dashboard_brief(m), "dashboard"

    if not body:
        m = _match(_load(root, "collection-maquettes.json"), route)
        if m:
            body, kind = _collection_brief(m), "collection"

    if not body:
        m = _match(_load(root, "record-maquettes.json"), route)
        if m:
            body, kind = _record_brief(m), "record"

    if not body:
        return ""

    moves = m.get("signature_moves") if isinstance(m, dict) else None
    if moves:
        body.append("Signature moves to honour: " + ", ".join(str(x) for x in moves))

    logger.info("[maquette-brief] %s → %s brief (%d lines)", route, kind, len(body))
    return (
        "## THE DESIGN FOR THIS PAGE (authoritative)\n"
        "A designer already decided what this screen is for and what it\n"
        "must show. Build THAT. You choose the component tree, the\n"
        "grouping and the styling; you do not choose the content, the\n"
        "column set, the ordering or the copy — those are decided.\n"
        "If something here can't be built, build the rest; never\n"
        "substitute a generic placeholder for a line you were given.\n\n"
        + "\n".join(body)
        + "\n"
    )


__all__ = ["build_maquette_brief"]

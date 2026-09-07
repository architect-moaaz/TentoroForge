"""Deterministically apply nav-flow.transitions back onto the page schemas.

The inverse of ``nav_transitions.build_transitions``. When the flow is edited in
the Pages/Nav editor (a connection added/retargeted), the running app must
follow it — the app navigates via each Button/Link's ``navigate`` prop, so those
props are the runtime projection of the flow. This rewrites them from the
transitions:

  transition {from, trigger: "button:Save", to} → set the Button labelled "Save"
  on the `from` page's schema to navigate to the `to` page's route.

Deterministic (no LLM) and idempotent, so the editor's "Apply" is instant and
lossless instead of an agent round-trip. Only trigger kinds that name a concrete
node ("button:<label>") are applied; generic "link" edges are left untouched.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)


def apply_editor_nav(output_dir: str, nav_data: dict) -> dict[str, Any]:
    """Bridge the visual editor's screens/edges → nav-flow.transitions → schemas.

    The Pages/Nav editor persists `screens[]` (each with data.route) and `edges[]`
    (source/target screen ids + label). Translate those into nav-flow.transitions
    (keyed by page id) and rewrite the navigate props deterministically, so a flow
    edited in the editor governs the running app without an LLM round-trip.
    """
    root = Path(output_dir)
    nav_path = root / "src" / "contracts" / "nav-flow.json"
    if not nav_path.exists():
        return {"transitions": 0, "applied": 0}
    try:
        nav = json.loads(nav_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"transitions": 0, "applied": 0}

    id_by_route = {p["route"]: p["id"] for p in (nav.get("pages") or [])
                   if isinstance(p, dict) and p.get("route") and p.get("id")}
    route_by_screen = {
        s.get("id"): (s.get("data") or {}).get("route")
        for s in (nav_data.get("screens") or []) if isinstance(s, dict)
    }

    transitions: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for e in nav_data.get("edges") or []:
        if not isinstance(e, dict):
            continue
        from_id = id_by_route.get(route_by_screen.get(e.get("source")))
        to_id = id_by_route.get(route_by_screen.get(e.get("target")))
        if not from_id or not to_id:
            continue
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        label = e.get("label") or data.get("label") or "navigate"
        nav_type = data.get("navType") or "link"
        trigger = f"button:{label}" if label not in ("navigate", "link") else "link"
        key = (from_id, trigger, to_id)
        if key in seen:
            continue
        seen.add(key)
        transitions.append({
            "id": f"t-{len(transitions) + 1}",
            "from": from_id, "trigger": trigger, "to": to_id, "navType": nav_type,
        })

    nav["transitions"] = transitions
    nav_path.write_text(json.dumps(nav, indent=2), encoding="utf-8")
    return {"transitions": len(transitions), "applied": apply_transitions(output_dir).get("applied", 0)}


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _node_label(props: dict, node: dict) -> str:
    return str(props.get("label") or props.get("content") or props.get("text")
               or node.get("label") or "").strip()


def apply_transitions(output_dir: str) -> dict[str, Any]:
    """Rewrite Button navigate props from nav-flow.transitions. Returns a report."""
    root = Path(output_dir)
    nav_path = root / "src" / "contracts" / "nav-flow.json"
    if not nav_path.exists():
        return {"applied": 0}
    try:
        nav = json.loads(nav_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"applied": 0}

    pages = nav.get("pages") or []
    route_by_id = {p["id"]: p["route"] for p in pages
                   if isinstance(p, dict) and p.get("id") and p.get("route")}
    schemafile_by_id = {p["id"]: p["schemaFile"] for p in pages
                        if isinstance(p, dict) and p.get("id") and p.get("schemaFile")}

    # Group transitions by source page so each schema is read/written once.
    by_source: dict[str, list[dict]] = {}
    for t in nav.get("transitions") or []:
        if isinstance(t, dict) and t.get("from"):
            by_source.setdefault(t["from"], []).append(t)

    applied = 0
    for from_id, trans in by_source.items():
        sf = schemafile_by_id.get(from_id)
        if not sf:
            continue
        sp = root / sf
        if not sp.exists():
            continue
        try:
            schema = json.loads(sp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        # Index button-triggered transitions by their target label.
        want: dict[str, str] = {}   # label → target route
        for t in trans:
            trig = str(t.get("trigger") or "")
            if not trig.startswith("button:"):
                continue
            target_route = route_by_id.get(t.get("to"))
            if target_route:
                want[trig[len("button:"):].strip()] = target_route

        if not want:
            continue

        changed = False
        for node in _walk(schema):
            if not isinstance(node, dict) or node.get("type") not in ("Button", "IconButton"):
                continue
            props = node.get("props")
            if not isinstance(props, dict):
                continue
            label = _node_label(props, node)
            target = want.get(label)
            if target and props.get("navigate") != target:
                props["navigate"] = target
                changed = True
                applied += 1

        if changed:
            sp.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    if applied:
        logger.info("nav_apply: rewrote %d navigate prop(s) from transitions in %s", applied, output_dir)
    return {"applied": applied}

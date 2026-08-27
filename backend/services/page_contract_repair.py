"""Deterministic backfills for required props the page-contract gate flags.

The page-contract gate CHECKS; this pass REPAIRS the small closed set of
required-prop omissions the LLM page author keeps making, so a missing
string never ships as a renderer-rejected node:

  * ``Hero``       — ``headline`` (from the page's own title/id) and
                     ``layout`` (default ``centered``; invalid enum
                     values are also normalized).
  * ``EmptyState`` — ``message`` (from title/description, else a stock
                     line).
  * ``Select``     — ``options`` (plan-declared enum values for the
                     select's field name when any entity declares them,
                     else an empty list so the contract holds and the
                     control renders instead of being dropped).

Everything here is additive and idempotent: props that exist are never
overwritten, and a second run is a no-op. Structural rewrites stay the
job of the composers — this is a last-line backstop, wired immediately
BEFORE the page-contract gate in post_generate_fixes so the gate reports
what actually ships.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from services.plan_field_lookup import get_enum_values, load_plan


def _registered_component_names() -> set[str]:
    """Library components + renderer built-ins + known aliases — anything
    NOT in this set renders as an unknown-component placeholder."""
    names: set[str] = set()
    try:
        from services.library_manifest import load_component_catalog
        names |= set(load_component_catalog().keys())
    except Exception:  # noqa: BLE001
        return set()  # no catalog → don't judge, drop nothing
    try:
        from services.page_contract_validator import RENDERER_BUILTINS
        names |= set(RENDERER_BUILTINS)
    except Exception:  # noqa: BLE001
        names |= {"Box", "Text", "Image", "Icon", "Stack", "Row", "Grid",
                  "Container", "Spacer", "Repeat", "Conditional",
                  "DataBoundary", "Slot", "PageOutlet", "Custom"}
    try:
        from services.alias_unknown_components import _ALIASES
        names |= set(_ALIASES.keys())  # alias pass will rename these
    except Exception:  # noqa: BLE001
        pass
    return names


def _search_workflow_name(output_dir) -> str | None:
    """First on-disk workflow whose name reads search-ish — the target a
    prop-less GlobalSearch should dispatch to."""
    from pathlib import Path as _P
    wf_dir = _P(output_dir) / "workflows"
    if not wf_dir.is_dir():
        return None
    for p in sorted(wf_dir.glob("*.json")):
        try:
            w = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        name = str(w.get("name") or "")
        if "search" in name.lower():
            return name
    return None

logger = logging.getLogger(__name__)

_HERO_LAYOUTS = {"centered", "split", "stacked"}


def _humanize(name: str) -> str:
    s = re.sub(r"[_\-]+", " ", str(name))
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    s = re.sub(r"\bpage\b", "", s, flags=re.IGNORECASE).strip()
    return " ".join(w[:1].upper() + w[1:] for w in s.split()) or "Welcome"


def _plan_entity_names(plan: dict | None) -> list[str]:
    names: list[str] = []
    for m in (plan or {}).get("data_models") or []:
        if isinstance(m, dict) and m.get("name"):
            names.append(str(m["name"]))
    ents = (plan or {}).get("entities")
    if isinstance(ents, dict):
        names.extend(str(k) for k in ents.keys())
    return names


def _enum_options_for(plan: dict | None, field_name: str) -> list[dict] | None:
    """First plan entity that declares enum values for ``field_name`` wins."""
    if not field_name:
        return None
    for ent in _plan_entity_names(plan):
        values = get_enum_values(plan, ent, field_name)
        if values:
            return [{"value": v, "label": _humanize(v)} for v in values]
    return None


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from _walk(child)
    elif isinstance(node, list):
        for child in node:
            yield from _walk(child)


def _drop_unknown_nodes(node: Any, known: set[str],
                        repaired: list[str]) -> None:
    """Remove children whose type is unregistered with no alias — the
    renderer would show an unknown-component placeholder for them, so a
    clean gap is strictly better (the LLM keeps inventing `Pagination`;
    Table paginates itself)."""
    if isinstance(node, dict):
        kids = node.get("children")
        if isinstance(kids, list):
            keep = []
            for c in kids:
                t = c.get("type") if isinstance(c, dict) else None
                if isinstance(t, str) and t and known and t not in known:
                    repaired.append(f"dropped:{t}")
                    continue
                keep.append(c)
            if len(keep) != len(kids):
                node["children"] = keep
            for c in keep:
                _drop_unknown_nodes(c, known, repaired)
    elif isinstance(node, list):
        for c in node:
            _drop_unknown_nodes(c, known, repaired)


def _repair_doc(doc: dict, page_title: str, plan: dict | None,
                known: set[str] | None = None,
                search_wf: str | None = None) -> list[str]:
    repaired: list[str] = []
    if known:
        _drop_unknown_nodes(doc.get("root") or {}, known, repaired)
    for node in _walk(doc.get("root") or {}):
        t = node.get("type")
        props = node.get("props")
        if not isinstance(props, dict):
            props = {}
            node["props"] = props

        if t == "Hero":
            if not str(props.get("headline") or "").strip():
                props["headline"] = page_title
                repaired.append("Hero.headline")
            if str(props.get("layout") or "").strip().lower() not in _HERO_LAYOUTS:
                props["layout"] = "centered"
                repaired.append("Hero.layout")

        elif t == "EmptyState":
            if not str(props.get("message") or "").strip():
                props["message"] = (
                    str(props.get("title") or "").strip()
                    or str(props.get("description") or "").strip()
                    or "Nothing here yet."
                )
                repaired.append("EmptyState.message")

        elif t == "GlobalSearch":
            if not str(props.get("workflow") or "").strip():
                if search_wf:
                    props["workflow"] = search_wf
                    repaired.append("GlobalSearch.workflow")
                # No search workflow on disk → the control can't do
                # anything; a plain node with a dead required prop still
                # fails the contract, so remove it via the unknown-drop
                # path is NOT right (it IS registered) — leave for the
                # gate to flag honestly.

        elif t == "Select":
            if not isinstance(props.get("options"), list):
                opts = _enum_options_for(plan, str(props.get("name") or ""))
                props["options"] = opts if opts else []
                repaired.append("Select.options")
    return repaired


def repair_required_props(output_dir: str | Path) -> dict:
    """Backfill the known required-prop omissions across all page schemas.

    Returns ``{"repaired": [{"page": ..., "props": [...]}, ...]}``.
    Never raises; unreadable schemas are skipped.
    """
    root = Path(output_dir)
    plan = load_plan(root)
    known = _registered_component_names()
    search_wf = _search_workflow_name(root)
    schemas_dir = root / "src" / "schemas"
    report: list[dict] = []
    if not schemas_dir.is_dir():
        return {"repaired": report}
    for path in sorted(schemas_dir.rglob("*.json")):
        if path.name == "shell.json":
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        title = _humanize(str(doc.get("title") or doc.get("id") or path.stem))
        fixed = _repair_doc(doc, title, plan, known=known,
                            search_wf=search_wf)
        if fixed:
            path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            report.append({"page": str(path.relative_to(schemas_dir)),
                           "props": fixed})
            logger.info("[page-contract-repair] %s: backfilled %s",
                        path.name, ", ".join(fixed))
    return {"repaired": report}


__all__ = ["repair_required_props"]

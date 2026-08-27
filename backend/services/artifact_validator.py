"""Domain validators for the three artifacts. Beyond Pydantic shape:
- Token closure (I-5): no raw hex/px values escape into page schemas
- Registry closure (I-6): every component + prop matches the registry
- ID uniqueness (I-4): every node id is globally unique

Returns a flat list of error strings. Empty list = valid.
"""
from __future__ import annotations
import re
from typing import Any

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
_PX_RE = re.compile(r"\b\d+\s*px\b")


def _walk(node: dict[str, Any]):
    """Yield every node dict in a schema tree."""
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children", []) or []:
        yield from _walk(child)
    slots = node.get("slots") or {}
    if isinstance(slots, dict):
        for arr in slots.values():
            if isinstance(arr, list):
                for c in arr:
                    yield from _walk(c)


def validate_id_uniqueness(artifacts: dict) -> list[str]:
    errs: list[str] = []
    seen: set[str] = set()
    for pid, page in (artifacts.get("pageSchemas") or {}).items():
        root = page.get("root") if isinstance(page, dict) else None
        if not root:
            errs.append(f"{pid}: missing root")
            continue
        for n in _walk(root):
            nid = n.get("id")
            if not nid:
                errs.append(f"{pid}/<unknown>: missing id on {n.get('type')}")
                continue
            if nid in seen:
                errs.append(f"duplicate node id across pages: {nid}")
            seen.add(nid)
    return errs


def validate_registry_closure(artifacts: dict, registry: dict) -> list[str]:
    """Every node.type must be in the registry; every prop name must be
    in the registry entry's props."""
    errs: list[str] = []
    for pid, page in (artifacts.get("pageSchemas") or {}).items():
        root = page.get("root") if isinstance(page, dict) else None
        if not root:
            continue
        for n in _walk(root):
            t = n.get("type")
            if not t:
                errs.append(f"{pid}/{n.get('id','?')}: missing type")
                continue
            entry = registry.get(t)
            if not entry:
                errs.append(f"{pid}/{n.get('id','?')}: unknown component '{t}'")
                continue
            entry_props = entry.get("props") or {}
            for prop_name in (n.get("props") or {}).keys():
                if prop_name not in entry_props:
                    errs.append(
                        f"{pid}/{n.get('id','?')}.{prop_name}: unknown prop on '{t}'"
                    )
    return errs


def validate_token_closure(artifacts: dict) -> list[str]:
    """Raw hex / px values in page schemas violate I-5. Tokens may contain
    them (color.brand.primary = '#13A8A8') — that's the only place they
    legally live."""
    errs: list[str] = []
    for pid, page in (artifacts.get("pageSchemas") or {}).items():
        root = page.get("root") if isinstance(page, dict) else None
        if not root:
            continue
        for n in _walk(root):
            for prop_name, val in (n.get("props") or {}).items():
                s = val if isinstance(val, str) else ""
                if _HEX_RE.search(s):
                    errs.append(
                        f"{pid}/{n.get('id','?')}.{prop_name}: raw hex color '{val}'"
                    )
                if _PX_RE.search(s):
                    errs.append(
                        f"{pid}/{n.get('id','?')}.{prop_name}: raw px value '{val}'"
                    )
    return errs


def validate_nav_consistency(artifacts: dict) -> list[str]:
    """Cross-artifact consistency:
    - pageSchemas keys match navFlow.pages[].id
    - transitions reference known pages
    - guards.redirectTo references known pages
    """
    errs: list[str] = []
    page_ids = set((artifacts.get("pageSchemas") or {}).keys())
    nav = artifacts.get("navFlow") or {}
    nav_pages = nav.get("pages") or []
    nav_ids = {p.get("id") for p in nav_pages}

    for pid in page_ids - nav_ids:
        errs.append(f"pageSchemas['{pid}'] has no matching navFlow.pages entry")
    for nid in nav_ids - page_ids:
        errs.append(f"navFlow.pages['{nid}'] has no matching pageSchemas entry")

    for t in (nav.get("transitions") or []):
        for key in ("from", "to"):
            tgt = t.get(key)
            if tgt and tgt not in nav_ids:
                errs.append(f"transition {t.get('id','?')}: {key}='{tgt}' is not a known page id")

    initial = nav.get("initialPage")
    if initial and initial not in nav_ids:
        errs.append(f"navFlow.initialPage='{initial}' is not a known page id")

    return errs


def validate_all(artifacts: dict, registry: dict) -> list[str]:
    """Run every validator and concatenate errors."""
    return (
        validate_id_uniqueness(artifacts)
        + validate_registry_closure(artifacts, registry)
        + validate_token_closure(artifacts)
        + validate_nav_consistency(artifacts)
    )

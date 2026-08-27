"""Component catalog — the library's ``starter.json`` as Smith's lookup.

The library ships a ``starter.json`` at
``packages/registry/dist/starter.json`` (repo root) listing every
component available to generated apps + its prop schema. Smith reads
this catalog so he never invents phantom components (Kanbam, DataGrid,
"MyCustomThing") when authoring or replanning.

Cached on first read; call :func:`invalidate_cache` after the library
is rebuilt in-process. Hot-reload / long-running backends can also set
``FORGE_COMPONENT_CATALOG_CACHE=0`` to disable the cache entirely.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_DEFAULT_STARTER_PATH_ENV = "FORGE_COMPONENT_CATALOG_PATH"
_REPO_RELATIVE = Path("packages") / "registry" / "dist" / "starter.json"

_cache: dict[str, dict[str, Any]] | None = None


def _repo_root_guess() -> Path:
    """Walk up from this file until we find the repo root (has
    ``packages/registry``). Backend runs from ``backend/`` so this is
    two levels up in the typical layout, but the walk-up is robust to
    monorepo restructuring."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages" / "registry").is_dir():
            return parent
    # Fallback: cwd's parent (assumes running from backend/)
    return Path.cwd().parent


def _starter_path() -> Path:
    """Where ``starter.json`` lives on disk. Overridable via env."""
    override = os.environ.get(_DEFAULT_STARTER_PATH_ENV)
    if override:
        return Path(override)
    return _repo_root_guess() / _REPO_RELATIVE


def _cache_enabled() -> bool:
    return os.environ.get("FORGE_COMPONENT_CATALOG_CACHE", "1").strip() != "0"


def invalidate_cache() -> None:
    """Drop the in-process catalog cache. Call after rebuilding the
    library in the same process."""
    global _cache
    _cache = None


def list_components() -> dict[str, dict[str, Any]]:
    """Return ``{name: {props: {prop_name: {…}}, …}}`` for every
    component in the library. Empty dict when the starter file is
    missing (dev environment where the library hasn't built yet) —
    callers must degrade gracefully rather than fail."""
    global _cache
    if _cache is not None and _cache_enabled():
        return _cache

    path = _starter_path()
    if not path.is_file():
        logger.warning(
            "component_catalog: starter.json not found at %s — Smith "
            "will not know which components exist; rebuild the library "
            "or set FORGE_COMPONENT_CATALOG_PATH.", path,
        )
        catalog: dict[str, dict[str, Any]] = {}
    else:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            logger.exception("component_catalog: failed to load %s", path)
            raw = {}
        if not isinstance(raw, dict):
            catalog = {}
        else:
            catalog = {
                str(name): (entry if isinstance(entry, dict) else {})
                for name, entry in raw.items()
            }

    if _cache_enabled():
        _cache = catalog
    return catalog


def component_names() -> list[str]:
    """Sorted list of every available component name."""
    return sorted(list_components().keys())


def props_for(name: str) -> list[str]:
    """Prop names for one component, or ``[]`` if the component isn't
    in the catalog (Smith should treat that as 'component doesn't
    exist')."""
    entry = list_components().get(name) or {}
    props = entry.get("props")
    if isinstance(props, dict):
        return sorted(props.keys())
    return []


def has_component(name: str) -> bool:
    return name in list_components()


def format_component_context(
    *, budget_chars: int = 2000,
) -> str:
    """Render a compact catalog for injection into Smith's prompts.

    Format: one line per component, ``Name(prop1, prop2, …)``. If the
    full listing exceeds ``budget_chars``, names-only fallback is
    emitted instead (still authoritative — Smith just loses per-prop
    detail)."""
    catalog = list_components()
    if not catalog:
        return "## Available components\n(catalog unavailable; assume nothing)"

    lines = []
    for name in sorted(catalog.keys()):
        entry = catalog.get(name) or {}
        props = entry.get("props") if isinstance(entry, dict) else None
        prop_names = (
            sorted(props.keys())
            if isinstance(props, dict) else []
        )
        if prop_names:
            preview = ", ".join(prop_names[:6])
            more = f", +{len(prop_names) - 6}" if len(prop_names) > 6 else ""
            lines.append(f"  {name}({preview}{more})")
        else:
            lines.append(f"  {name}")

    body = "\n".join(lines)
    header = (
        f"## Available components ({len(catalog)} total)\n"
        "Only components in this list exist in the runtime. Never "
        "invent a name that isn't here.\n"
    )
    if len(header) + len(body) <= budget_chars:
        return header + body

    # Over-budget fallback: names-only.
    names_body = "  " + ", ".join(sorted(catalog.keys()))
    return header + names_body

"""IRF-M4-T6 — resolve a substrate signature name → a renderer kind.

The substrate's `backend/archetypes/signature_moves.json` catalog names
signature moves by their **behavioral primitive** (e.g. ``lane-swap-animation``,
``pulsing-scan-orb``, ``pin-cluster-badge``). Rendering those signatures on a
page schema is the job of the ``services.signature_moves`` package (the
predicate + renderer registry). Historically the two vocabularies drifted —
the catalog talks about kanban lane-swaps; the renderer registry has
``ledger_row`` and ``card_elevation``.

This module bridges the two:

- ``resolve(name)`` → the renderer kind (string) that materializes the
  substrate signature, or ``None`` when no renderer exists yet.
- ``known_substrate_signatures()`` → the full list of substrate signature
  names the catalog knows about (all triggers × all signatures + all
  recipe-specific signatures) — useful for gap-log reports.

The mapping is intentionally small and additive: adding a library component
+ a renderer + one line here is the recipe to wire a new signature. Every
signature the resolver DOESN'T recognize gets reported as a gap by the
enforcer, so telemetry drives the fill order.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_ARCHETYPES_DIR = Path(__file__).resolve().parent.parent / "archetypes"


# Substrate signature name → renderer kind name (must exist in
# `services.signature_moves` registry, or in the extension registry a future
# PR adds). Keep entries alphabetical within groups so diffs are readable.
#
# Empty by design at ship time — the existing renderer registry names
# (ledger_row, keyline_breadcrumb, velocity_sparkline, status_stripe,
# card_elevation, warm_serif_h1) don't correspond to substrate signature
# names. This map fills as new renderers land.
_SUBSTRATE_TO_RENDERER: dict[str, str] = {
    # Filled as library + renderer pairs land. Example (once implemented):
    # "sparkline-preview": "velocity_sparkline",
}


def resolve(signature_name: str) -> str | None:
    """Return the renderer kind for a substrate signature, or None.

    A caller that gets ``None`` should treat the signature as unfulfillable
    for now and log it via ``substrate_gap_log``.
    """
    if not isinstance(signature_name, str):
        return None
    return _SUBSTRATE_TO_RENDERER.get(signature_name.strip())


@lru_cache(maxsize=1)
def known_substrate_signatures() -> tuple[str, ...]:
    """Return every signature name declared in signature_moves.json.

    Deterministic — same catalog → same tuple. Used by the gap-log
    aggregator + tests. Recipes' ``recipe_signatures`` are included too
    (they contribute requirements via `compute_requirements`).
    """
    path = _ARCHETYPES_DIR / "signature_moves.json"
    if not path.exists():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    names: set[str] = set()
    for trigger in data.get("triggers") or []:
        for s in (trigger.get("signatures") or []):
            if isinstance(s, str):
                names.add(s)
    # Also harvest recipe-specific signatures from recipes.json.
    rpath = _ARCHETYPES_DIR / "recipes.json"
    if rpath.exists():
        try:
            rdata = json.loads(rpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rdata = {}
        for _rname, entry in (rdata.get("recipes") or {}).items():
            for s in (entry.get("recipe_signatures") or []):
                if isinstance(s, str):
                    names.add(s)
    return tuple(sorted(names))


def resolvable_signatures() -> tuple[str, ...]:
    """Substrate signatures currently mapped to a renderer."""
    return tuple(sorted(_SUBSTRATE_TO_RENDERER.keys()))


def unresolvable_signatures() -> tuple[str, ...]:
    """Signatures the catalog knows about but the resolver can't yet
    materialize — the gap list. Additive as renderers land."""
    known = set(known_substrate_signatures())
    resolvable = set(_SUBSTRATE_TO_RENDERER.keys())
    return tuple(sorted(known - resolvable))


def _clear_caches() -> None:
    """Test hook."""
    known_substrate_signatures.cache_clear()


__all__ = [
    "resolve",
    "known_substrate_signatures",
    "resolvable_signatures",
    "unresolvable_signatures",
]

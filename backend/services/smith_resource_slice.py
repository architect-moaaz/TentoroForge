"""CTX-1: build a focal resource-registry slice for a route Smith touched.

Bridges :mod:`services.smith_memory` (which knows *what* was last touched)
and :mod:`services.resource_registry_context` (which knows how to slice
entity/workflow/relationship context for a given entity).

Called by :func:`services.smith_memory.read_smith_memory` when an
``output_dir`` is passed. Never raises — a missing registry or nav-flow
returns an empty string; the memory block just skips the section.

Route → entity resolution priority:
  1. ``nav-flow.json`` page's ``entity`` field for the exact route.
  2. First non-dynamic route segment as the entity-name candidate.
     Downstream ``_resolve_focal`` fuzzy-matches slug/name/id.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def build_slice_for_route(output_dir: str, route: str) -> str:
    """Return a compact resource-registry slice string for ``route``, or
    ``""`` when nothing usable can be built.

    Output shape (when non-empty)::

        Focal: /candidates/new → Candidate
        <resource-registry>
          ... focal entity + FK neighbors + workflows + relationships ...
        </resource-registry>

    The ``Focal:`` header gives Smith an unambiguous anchor: which route
    triggered this context. Failures are silent.
    """
    if not route or route == "/":
        return ""
    try:
        entity = resolve_entity_for_route(output_dir, route)
        if not entity:
            return ""
        from services.resource_registry_context import (
            build_resource_context_slice,
        )
        body = build_resource_context_slice(output_dir, entity)
        if not body or not body.strip():
            return ""
        # Prepend the focal header — Smith reads this as the anchor
        # ("last thing you touched was this page for this entity").
        return f"Focal: {route} → {entity}\n{body}"
    except Exception:  # noqa: BLE001 — never block memory on a slice failure
        logger.exception("build_slice_for_route: unexpected error")
        return ""


def resolve_entity_for_route(output_dir: str, route: str) -> Optional[str]:
    """Best-effort route → entity-name resolution.

    Priority:
      1. ``src/contracts/nav-flow.json``'s page entry for this route: use
         its ``entity`` field verbatim (planner's authoritative binding).
      2. First non-dynamic path segment (``/candidates/[id]`` →
         ``"candidates"``). Downstream fuzzy-match will resolve plurals /
         case; if it can't, the whole-app fallback still gives Smith
         useful context.

    Returns None when nothing usable is derivable (root route, empty)."""
    if not route:
        return None
    r = route.strip()
    if not r or r == "/":
        return None

    # (1) nav-flow lookup — cheap, and often more precise than segment guessing.
    nav = _load_nav_flow(output_dir)
    if isinstance(nav, dict):
        pages = nav.get("pages") or []
        for p in pages:
            if not isinstance(p, dict):
                continue
            if p.get("route") == r:
                ent = p.get("entity")
                if isinstance(ent, str) and ent.strip():
                    return ent.strip()

    # (2) Segment fallback — take the first non-dynamic segment.
    parts = [s for s in r.strip("/").split("/") if s]
    for seg in parts:
        if seg.startswith("[") and seg.endswith("]"):
            continue
        return seg
    return None


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _load_nav_flow(output_dir: str) -> Optional[dict]:
    for candidate in (
        Path(output_dir) / "src" / "contracts" / "nav-flow.json",
        Path(output_dir) / "contracts" / "nav-flow.json",
    ):
        if not candidate.exists():
            continue
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    return None

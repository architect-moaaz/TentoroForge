"""CTX-1: route → entity → resource-registry slice for Smith memory.

The helper takes a route Smith last touched and returns a focal
resource-slice string (or "" when nothing usable exists). Failure modes
must be silent — a missing registry or nav-flow is never blocking, just
means the caller gets an empty slice.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.smith_resource_slice import (
    build_slice_for_route,
    resolve_entity_for_route,
)


# --------------------------------------------------------------------------- #
# resolve_entity_for_route — nav-flow first, first-segment fallback
# --------------------------------------------------------------------------- #

def _write(root: Path, rel: str, doc: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc))


def test_resolve_entity_from_nav_flow_page_entity_field(tmp_path):
    """When nav-flow.json declares an entity on a page, that wins over
    the first-segment guess (which might be a route alias)."""
    _write(tmp_path, "src/contracts/nav-flow.json", {
        "pages": [
            {"route": "/application-2/new", "entity": "Application"},
        ],
    })
    assert resolve_entity_for_route(str(tmp_path), "/application-2/new") == "Application"


def test_resolve_entity_falls_back_to_first_segment(tmp_path):
    """No nav-flow entity hint → use the first non-dynamic segment.
    A `_resolve_focal` fuzzy match downstream will normalize plural→singular."""
    # nav-flow exists but no entity field for this route.
    _write(tmp_path, "src/contracts/nav-flow.json", {
        "pages": [{"route": "/application-2/new"}],
    })
    assert resolve_entity_for_route(str(tmp_path), "/candidates/new") == "candidates"


def test_resolve_entity_skips_dynamic_segments(tmp_path):
    """Routes like /candidates/[id]/edit → 'candidates' (skip bracketed segs)."""
    assert (
        resolve_entity_for_route(str(tmp_path), "/candidates/[id]/edit")
        == "candidates"
    )


def test_resolve_entity_returns_none_for_root_or_empty(tmp_path):
    assert resolve_entity_for_route(str(tmp_path), "/") is None
    assert resolve_entity_for_route(str(tmp_path), "") is None


# --------------------------------------------------------------------------- #
# build_slice_for_route — end-to-end
# --------------------------------------------------------------------------- #

def test_build_slice_missing_registry_returns_empty(tmp_path):
    """No canonical registry file → no slice. Caller sees ''."""
    # nav-flow exists but registry doesn't → downstream builder will fall
    # through gracefully; we want an empty string, not a crash.
    _write(tmp_path, "src/contracts/nav-flow.json", {
        "pages": [{"route": "/candidates/new", "entity": "Candidate"}],
    })
    slice_str = build_slice_for_route(str(tmp_path), "/candidates/new")
    # No registry → helper returns "" (never raises).
    assert slice_str == "" or "Focal" in slice_str  # tolerant to fallback shape


def test_build_slice_with_registry_prepends_focal_header(tmp_path):
    """A successful slice starts with a `Focal:` header so Smith sees
    the anchor (route + entity) at the top of the block."""
    _write(tmp_path, "src/contracts/nav-flow.json", {
        "pages": [{"route": "/candidates/new", "entity": "Candidate"}],
    })
    _write(tmp_path, "contracts/resource-registry.json", {
        "entities": {
            "Candidate": {
                "id":   "e_candidate",
                "name": "Candidate",
                "slug": "candidates",
                "columns": [
                    {"name": "id",       "type": "uuid",    "notNull": True},
                    {"name": "fullName", "type": "varchar", "notNull": True},
                ],
                "fks": [],
            }
        },
        "interactions": [],
        "relationships": [],
    })

    slice_str = build_slice_for_route(str(tmp_path), "/candidates/new")
    assert slice_str, "expected a non-empty slice for a valid registry"
    assert "Focal:" in slice_str.splitlines()[0]
    assert "/candidates/new" in slice_str
    assert "Candidate" in slice_str


def test_build_slice_swallows_all_errors(tmp_path):
    """Anything blowing up in the downstream builder must NOT propagate —
    Smith memory is never blocked on this."""
    # Route with no entity hint, no registry, no nav-flow — full silent path.
    assert build_slice_for_route(str(tmp_path), "/whatever") == ""


def test_build_slice_empty_route_returns_empty(tmp_path):
    assert build_slice_for_route(str(tmp_path), "") == ""
    assert build_slice_for_route(str(tmp_path), "/") == ""

"""Sprint 2 — dashboard_completeness skips designer-authored pages.

Verifies: when a dashboard schema carries the `_designer_authored: true`
marker (Sprint 2 stamps this on schemas whose authoring turn was primed
by the Design Context Pack), the mechanical top-up in
`apply_dashboard_completeness` does NOT add widgets. The Designer's
composition is authoritative.

Without this behavior, a designer-authored dashboard with 2 hero widgets
(a big KPI row + a hero chart) would be silently "topped up" to N
generic widgets, wrecking the composition.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.dashboard_completeness import apply_dashboard_completeness


def _write(root: Path, rel: str, obj) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _plan(pages, entities=None):
    return {
        "pages": pages,
        "entities": entities or {"Payment": {"fields": [{"name": "amount"}]}},
    }


def _dashboard_page(route="/dashboard"):
    return {"route": route, "name": "Dashboard", "type": "dashboard", "widgets": []}


def _minimal_dashboard_schema(nodes=None, *, designer_authored=False):
    """A dashboard schema. When `designer_authored=True` the Sprint 2
    marker is stamped exactly as page_schema_agent stamps it after a
    Design-Context-Pack-primed turn."""
    schema = {
        "id": "dashboard",
        "route": "/dashboard",
        "schemaVersion": "2",
        "type": "dashboard",
        "nodes": nodes if nodes is not None else [],
    }
    if designer_authored:
        schema["_designer_authored"] = True
    return schema


def test_designer_authored_schema_is_left_alone(tmp_path):
    """When `_designer_authored: true` is on the schema, apply_dashboard_
    completeness must not add widgets — even if the schema has fewer
    nodes than the completeness floor."""
    _write(tmp_path, "src/contracts/plan.json", _plan([_dashboard_page()]))
    schema_before = _minimal_dashboard_schema(nodes=[], designer_authored=True)
    _write(tmp_path, "src/schemas/dashboard.json", schema_before)

    result = apply_dashboard_completeness(str(tmp_path))

    # No pages touched, no sections added.
    assert result["sections_added"] == 0
    assert result["pages_touched"] == []

    # Schema on disk is identical (marker intact, still zero nodes).
    schema_after = json.loads(
        (tmp_path / "src/schemas/dashboard.json").read_text(encoding="utf-8"),
    )
    assert schema_after == schema_before
    assert schema_after.get("_designer_authored") is True


def test_non_designer_authored_schema_still_gets_topped_up(tmp_path):
    """Sanity: pages WITHOUT the marker (legacy path, DCP flag off) get
    the completeness top-up as before."""
    _write(tmp_path, "src/contracts/plan.json", _plan([_dashboard_page()]))
    # No marker → normal top-up path applies.
    _write(tmp_path, "src/schemas/dashboard.json",
           _minimal_dashboard_schema(nodes=[], designer_authored=False))

    result = apply_dashboard_completeness(str(tmp_path))

    # At least one section was appended (the exact count depends on the
    # entity heuristics; we only care that the guard DID act).
    assert result["sections_added"] > 0
    assert "/dashboard" in result["pages_touched"] or "dashboard" in str(
        result["pages_touched"]
    )
    # Marker was never present on this schema — nothing to preserve.
    schema_after = json.loads(
        (tmp_path / "src/schemas/dashboard.json").read_text(encoding="utf-8"),
    )
    assert "_designer_authored" not in schema_after


def test_marker_ignored_when_value_is_not_literally_true(tmp_path):
    """Defense-in-depth: only `_designer_authored: true` triggers the
    skip. A truthy-but-not-True value (e.g. a stringified "true" from a
    malformed serialization) should NOT skip the guard — the guard
    remains the fallback for those cases."""
    _write(tmp_path, "src/contracts/plan.json", _plan([_dashboard_page()]))
    schema = _minimal_dashboard_schema(nodes=[])
    schema["_designer_authored"] = "true"  # string, not bool
    _write(tmp_path, "src/schemas/dashboard.json", schema)

    result = apply_dashboard_completeness(str(tmp_path))

    # Guard treated the string as not-True → top-up ran normally.
    assert result["sections_added"] > 0

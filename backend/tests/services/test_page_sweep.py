"""Tests for services.journey_verifier.sweep — manifest building +
results reading (the deterministic halves; the Playwright spec itself is
validated live)."""
from __future__ import annotations

import json
from pathlib import Path

from services.journey_verifier.sweep import (
    build_sweep_manifest,
    emit_sweep,
    read_sweep_results,
)


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _mk_app(tmp_path: Path, routes: list[str], tables: list[str]) -> Path:
    root = tmp_path / "app"
    reg = ",\n".join(f'  "{r}": () => import("./x.json")' for r in routes)
    _write(root, "src/schemas/registry.ts",
           "export const schemas = {\n" + reg + "\n};\n")
    lines = [
        f'export const {t} = pgTable("{t}", {{ id: uuid("id").primaryKey() }});'
        for t in tables
    ]
    _write(root, "src/db/schema/entities.ts", "\n".join(lines))
    return root


def test_manifest_concrete_and_param_routes(tmp_path: Path):
    root = _mk_app(tmp_path,
                   ["/", "/documents", "/documents/[id]", "/login", "/api/x"],
                   ["documents"])
    m = build_sweep_manifest(root)
    routes = {r["route"]: r for r in m["routes"]}
    assert "/" in routes
    assert "/documents" in routes
    assert routes["/documents/[id]"]["table"] == "documents"
    # auth + api never swept
    assert "/login" not in routes
    assert "/api/x" not in routes


def test_param_route_with_unresolvable_table_skipped(tmp_path: Path):
    root = _mk_app(tmp_path, ["/ghosts/[id]"], ["documents"])
    assert build_sweep_manifest(root)["routes"] == []


def test_emit_writes_manifest_and_spec(tmp_path: Path):
    root = _mk_app(tmp_path, ["/documents"], ["documents"])
    out = emit_sweep(root)
    assert out is not None
    assert (root / "journeys" / "sweep.json").is_file()
    spec = (root / "journeys" / "sweep.spec.ts").read_text()
    assert 'data-empty="true"' in spec
    assert "sweep-results.json" in spec


def test_emit_no_routes_returns_none(tmp_path: Path):
    root = _mk_app(tmp_path, [], [])
    assert emit_sweep(root) is None
    assert not (root / "journeys" / "sweep.spec.ts").exists()


def test_read_results_summary(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "journeys/sweep-results.json", json.dumps({"results": [
        {"route": "/", "status": "ok", "emptyMarkers": 0},
        {"route": "/documents", "status": "ok", "emptyMarkers": 2},
        {"route": "/broken", "status": "nav_failed", "emptyMarkers": 0},
    ]}))
    out = read_sweep_results(root)
    assert out["summary"] == {"routes": 3, "with_empty_markers": 1,
                              "nav_failed": 1}


def test_read_results_absent_returns_none(tmp_path: Path):
    assert read_sweep_results(tmp_path) is None

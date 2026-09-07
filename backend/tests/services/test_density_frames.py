"""Tests for services.density_frames (G5) + route_dedup.dedupe_search_endpoints."""
from __future__ import annotations

import json
from pathlib import Path

from services.density_frames import apply_density_frames, classify_density
from services.route_dedup import dedupe_search_endpoints


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ── classification ───────────────────────────────────────────────────

def test_lone_form_is_sparse():
    page = {"root": {"type": "Stack", "children": [
        {"type": "Heading", "props": {"text": "New Document"}},
        {"type": "Form", "props": {"entity": "Document", "fields": []}}]}}
    assert classify_density(page) == "sparse"


def test_table_page_is_regular():
    page = {"root": {"type": "Stack", "children": [
        {"type": "Table", "props": {"rows": "{{docs}}", "columns": []}}]}}
    assert classify_density(page) == "regular"


def test_dashboard_is_dense():
    page = {"root": {"type": "Stack", "children": [
        {"type": "Table", "props": {}}, {"type": "Chart", "props": {}},
        {"type": "MetricTile", "props": {}}]}}
    assert classify_density(page) == "dense"


def test_form_next_to_table_not_sparse():
    """A wide widget anywhere disqualifies the narrow frame."""
    page = {"root": {"type": "Stack", "children": [
        {"type": "Form", "props": {}}, {"type": "Table", "props": {}}]}}
    assert classify_density(page) != "sparse"


def test_redirect_alias_is_regular():
    page = {"root": {"type": "Stack", "children": [
        {"type": "Redirect", "props": {"to": "/x"}}]}}
    assert classify_density(page) == "regular"


# ── application ──────────────────────────────────────────────────────

def _sparse_doc() -> dict:
    return {"route": "/documents/new", "root": {"type": "Stack", "children": [
        {"type": "Form", "props": {"entity": "Document", "fields": []}}]}}


def test_sparse_page_gets_centered_frame(tmp_path: Path):
    _write(tmp_path, "src/schemas/documents/new.json", json.dumps(_sparse_doc()))
    rep = apply_density_frames(tmp_path)
    assert rep["counts"]["sparse"] == 1
    assert rep["framed"] == ["documents/new.json"]
    doc = json.loads((tmp_path / "src/schemas/documents/new.json").read_text(encoding="utf-8"))
    assert doc["density"] == "sparse"
    assert "max-w-2xl" in doc["root"]["props"]["className"]
    assert "mx-auto" in doc["root"]["props"]["className"]


def test_regular_page_untouched(tmp_path: Path):
    doc = {"route": "/documents", "root": {"type": "Stack", "children": [
        {"type": "Table", "props": {"rows": "{{d}}", "columns": []}}]}}
    _write(tmp_path, "src/schemas/documents.json", json.dumps(doc))
    rep = apply_density_frames(tmp_path)
    assert rep["framed"] == []
    out = json.loads((tmp_path / "src/schemas/documents.json").read_text(encoding="utf-8"))
    assert out["density"] == "regular"
    assert "className" not in out["root"].get("props", {})


def test_rerun_idempotent(tmp_path: Path):
    _write(tmp_path, "src/schemas/new.json", json.dumps(_sparse_doc()))
    apply_density_frames(tmp_path)
    rep2 = apply_density_frames(tmp_path)
    assert rep2["framed"] == []
    doc = json.loads((tmp_path / "src/schemas/new.json").read_text(encoding="utf-8"))
    assert doc["root"]["props"]["className"].count("max-w-2xl") == 1


def test_authored_width_constraint_respected(tmp_path: Path):
    doc = _sparse_doc()
    doc["root"]["props"] = {"className": "max-w-4xl"}
    _write(tmp_path, "src/schemas/new.json", json.dumps(doc))
    rep = apply_density_frames(tmp_path)
    assert rep["framed"] == []
    out = json.loads((tmp_path / "src/schemas/new.json").read_text(encoding="utf-8"))
    assert out["root"]["props"]["className"] == "max-w-4xl"


def test_missing_dir_no_crash(tmp_path: Path):
    assert apply_density_frames(tmp_path / "nope")["framed"] == []


# ── search-endpoint dedup ────────────────────────────────────────────

def test_nested_search_route_removed_canonical_kept(tmp_path: Path):
    _write(tmp_path, "src/app/api/search/route.ts", "// canonical")
    _write(tmp_path, "src/app/api/documents/search/route.ts", "// duplicate")
    rep = dedupe_search_endpoints(tmp_path)
    assert rep["removed"] == ["src/app/api/documents/search/route.ts"]
    assert (tmp_path / "src/app/api/search/route.ts").is_file()
    assert not (tmp_path / "src/app/api/documents/search").exists()
    # empty parent pruned too
    assert not (tmp_path / "src/app/api/documents").exists()


def test_parent_with_siblings_survives(tmp_path: Path):
    _write(tmp_path, "src/app/api/search/route.ts", "// canonical")
    _write(tmp_path, "src/app/api/documents/pdf/route.ts", "// keep")
    _write(tmp_path, "src/app/api/documents/search/route.ts", "// duplicate")
    dedupe_search_endpoints(tmp_path)
    assert (tmp_path / "src/app/api/documents/pdf/route.ts").is_file()


def test_no_api_dir_no_crash(tmp_path: Path):
    assert dedupe_search_endpoints(tmp_path)["removed"] == []

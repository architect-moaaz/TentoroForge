"""Tests for the Phase 5 output-directory project-scoped editor endpoints.

Uses FastAPI TestClient with a temporary output directory so no real filesystem
state is needed and no database is required.
"""

import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture: patch OUTPUT_ROOT to a temp dir before app import resolves routes
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path):
    """TestClient with OUTPUT_ROOT redirected to a per-test temp directory."""
    import services.project_paths as pp
    # Patch OUTPUT_ROOT before importing main so routes see the patched value.
    original = pp.OUTPUT_ROOT
    pp.OUTPUT_ROOT = tmp_path
    try:
        from main import app
        yield TestClient(app), tmp_path
    finally:
        pp.OUTPUT_ROOT = original


# ---------------------------------------------------------------------------
# List projects
# ---------------------------------------------------------------------------

def test_list_projects_empty(client):
    tc, tmp = client
    r = tc.get("/api/projects")
    assert r.status_code == 200
    assert r.json() == []


def test_list_projects_with_dir(client):
    tc, tmp = client
    (tmp / "demo").mkdir()
    (tmp / ".hidden").mkdir()
    r = tc.get("/api/projects")
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert ids == ["demo"]
    assert ".hidden" not in ids


def test_list_projects_multiple(client):
    tc, tmp = client
    (tmp / "alpha").mkdir()
    (tmp / "beta").mkdir()
    (tmp / "gamma").mkdir()
    r = tc.get("/api/projects")
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert ids == ["alpha", "beta", "gamma"]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def test_list_pages_no_schemas_dir(client):
    tc, tmp = client
    (tmp / "demo").mkdir()
    r = tc.get("/api/projects/demo/schemas")
    assert r.status_code == 200
    assert r.json() == {"paths": []}


def test_list_pages_with_schemas(client):
    tc, tmp = client
    schemas = tmp / "demo" / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "home.json").write_text("{}", encoding="utf-8")
    products_dir = schemas / "products"
    products_dir.mkdir(parents=True, exist_ok=True)
    (products_dir / "list.json").write_text("{}", encoding="utf-8")
    r = tc.get("/api/projects/demo/schemas")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "home" in paths
    assert "products/list" in paths


# ---------------------------------------------------------------------------
# Load schema
# ---------------------------------------------------------------------------

def test_load_existing_schema(client):
    tc, tmp = client
    project = tmp / "demo"
    (project / "src" / "schemas").mkdir(parents=True)
    schema_data = {
        "schemaVersion": "1",
        "id": "p",
        "route": "/",
        "root": {"id": "r", "type": "Box", "children": []},
    }
    (project / "src" / "schemas" / "page1.json").write_text(json.dumps(schema_data), encoding="utf-8")
    r = tc.get("/api/projects/demo/load?path=page1")
    assert r.status_code == 200
    assert r.json()["schema"]["id"] == "p"


def test_load_missing_schema(client):
    tc, tmp = client
    (tmp / "demo" / "src" / "schemas").mkdir(parents=True)
    r = tc.get("/api/projects/demo/load?path=nonexistent")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Save schema
# ---------------------------------------------------------------------------

def test_save_then_load(client):
    tc, tmp = client
    (tmp / "demo" / "src" / "schemas").mkdir(parents=True)
    schema = {
        "schemaVersion": "1",
        "id": "p",
        "route": "/",
        "root": {"id": "r", "type": "Box", "children": []},
    }
    r = tc.post("/api/projects/demo/save", json={"path": "newpage", "schema": schema})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert (tmp / "demo" / "src" / "schemas" / "newpage.json").exists()


def test_save_creates_dir(client):
    tc, tmp = client
    (tmp / "demo").mkdir()
    schema = {"schemaVersion": "1", "id": "x", "route": "/x",
              "root": {"id": "r", "type": "Box", "children": []}}
    r = tc.post("/api/projects/demo/save", json={"path": "sub/page", "schema": schema})
    assert r.status_code == 200
    assert (tmp / "demo" / "src" / "schemas" / "sub" / "page.json").exists()


def test_save_round_trip_content(client):
    tc, tmp = client
    (tmp / "demo" / "src" / "schemas").mkdir(parents=True)
    schema = {"schemaVersion": "1", "id": "rt", "route": "/rt",
              "root": {"id": "r", "type": "Box", "children": []}}
    tc.post("/api/projects/demo/save", json={"path": "rt", "schema": schema})
    r = tc.get("/api/projects/demo/load?path=rt")
    assert r.status_code == 200
    assert r.json()["schema"]["id"] == "rt"


# ---------------------------------------------------------------------------
# Path traversal
# ---------------------------------------------------------------------------

def test_path_traversal_dotdot(client):
    tc, tmp = client
    r = tc.get("/api/projects/../etc/schemas")
    # FastAPI will URL-decode and the path parameter may or may not reach the handler.
    # Either 400 (our validation) or 404 (route mismatch) is acceptable.
    assert r.status_code in (400, 404, 422)


def test_path_traversal_encoded(client):
    tc, tmp = client
    # %2F is a forward slash encoded
    r = tc.get("/api/projects/..%2Fetc/load?path=passwd")
    assert r.status_code in (400, 404, 422)


def test_path_traversal_double_dot_in_id(client):
    tc, tmp = client
    # Direct call to project_root with ".."
    from services.project_paths import project_root
    with pytest.raises(ValueError):
        project_root("..")


def test_path_traversal_slash_in_id(client):
    tc, tmp = client
    from services.project_paths import project_root
    with pytest.raises(ValueError):
        project_root("a/b")


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

def test_theme_default(client):
    tc, tmp = client
    (tmp / "demo").mkdir()
    r = tc.get("/api/projects/demo/theme")
    assert r.status_code == 200
    assert r.json()["source"] == "default"
    assert r.json()["tokens"] == {}


def test_theme_save_and_load(client):
    tc, tmp = client
    (tmp / "demo").mkdir()
    tokens = {"colors": {"primary.500": "#3b82f6"}}
    r = tc.post("/api/projects/demo/theme", json={"tokens": tokens})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    r2 = tc.get("/api/projects/demo/theme")
    assert r2.json()["source"] == "custom"
    assert r2.json()["tokens"] == tokens


# ---------------------------------------------------------------------------
# Editor mirror (Phase D2) — records editor saves in Smith's blueprint
# ---------------------------------------------------------------------------

def test_editor_mirror_records_edit_in_blueprint(client):
    from services.smith_blueprint import Blueprint

    tc, tmp = client
    (tmp / "demo").mkdir()

    r = tc.post("/api/projects/demo/editor/mirror", json={
        "artifact_path": "src/schemas/candidates/new.json",
        "summary": "changed CV field: Select → FileUpload",
        "why": "user requested via editor",
    })
    assert r.status_code == 200
    assert r.json() == {"mirrored": True}

    bp = Blueprint.load(project_id="demo", output_dir=str(tmp / "demo"))
    assert len(bp.change_log) == 1
    entry = bp.change_log[0]
    assert entry["source"] == "editor"
    assert "candidates/new.json" in entry["smith_move"]
    assert "FileUpload" in entry["diff_summary"]


def test_editor_mirror_never_5xx_on_blueprint_error(client, monkeypatch):
    """Even if the mirror write blows up, the endpoint returns 200 with
    mirrored=false — the editor's save has already succeeded."""
    tc, tmp = client
    (tmp / "demo").mkdir()

    class _Boom:
        def __init__(self, **kwargs): pass
        def record_edit(self, **kwargs): raise RuntimeError("boom")

    monkeypatch.setattr("services.smith_concurrency.EditorMirror", _Boom)

    r = tc.post("/api/projects/demo/editor/mirror", json={
        "artifact_path": "x", "summary": "y", "why": "z",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["mirrored"] is False
    assert "boom" in body["error"]

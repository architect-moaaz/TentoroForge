"""Tests for synthesizing nav-flow.json from on-disk page schemas."""
import json

from services.nav_flow_from_schemas import (
    build_nav_flow_from_schemas,
    ensure_nav_flow,
)


def _write_schema(root, rel, data):
    p = root / "src" / "schemas" / f"{rel}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def test_returns_none_without_schemas(tmp_path):
    assert build_nav_flow_from_schemas(tmp_path) is None


def test_builds_page_entries_from_schema_files(tmp_path):
    _write_schema(tmp_path, "dashboard", {"route": "/dashboard", "page_type": "dashboard"})
    _write_schema(tmp_path, "leases/[id]", {"route": "/leases/[id]", "page_type": "detail"})

    nav = build_nav_flow_from_schemas(tmp_path)
    assert nav is not None
    ids = {p["id"] for p in nav["pages"]}
    assert ids == {"dashboard", "leases/[id]"}
    detail = next(p for p in nav["pages"] if p["id"] == "leases/[id]")
    # schemaFile is the authoritative path the Canvas reads.
    assert detail["schemaFile"] == "src/schemas/leases/[id].json"


def test_skips_non_page_files(tmp_path):
    _write_schema(tmp_path, "home", {"route": "/", "page_type": "dashboard"})
    _write_schema(tmp_path, "registry", {"junk": True})
    _write_schema(tmp_path, "shell", {"junk": True})

    nav = build_nav_flow_from_schemas(tmp_path)
    ids = {p["id"] for p in nav["pages"]}
    assert ids == {"home"}


def test_auth_pages_are_non_shell_and_ordered_last(tmp_path):
    _write_schema(tmp_path, "login", {"route": "/login", "page_type": "auth"})
    _write_schema(tmp_path, "dashboard", {"route": "/dashboard", "page_type": "dashboard"})

    nav = build_nav_flow_from_schemas(tmp_path)
    login = next(p for p in nav["pages"] if p["id"] == "login")
    assert login["shell"] is False
    assert nav["pages"][-1]["id"] == "login"  # auth last
    assert "/login" in nav["auth_routes"]
    assert nav["post_logout_redirect"] == "/login"


def test_initial_page_prefers_landing(tmp_path):
    _write_schema(tmp_path, "analytics", {"route": "/analytics", "page_type": "list"})
    _write_schema(tmp_path, "dashboard", {"route": "/dashboard", "page_type": "dashboard"})

    nav = build_nav_flow_from_schemas(tmp_path)
    assert nav["initialPage"] == "dashboard"


def test_ensure_nav_flow_writes_when_missing(tmp_path):
    _write_schema(tmp_path, "dashboard", {"route": "/dashboard", "page_type": "dashboard"})
    target = tmp_path / "src" / "contracts" / "nav-flow.json"
    assert not target.exists()

    result = ensure_nav_flow(tmp_path)
    assert result == target
    assert target.exists()
    assert len(json.loads(target.read_text(encoding="utf-8"))["pages"]) == 1


def test_ensure_nav_flow_idempotent(tmp_path):
    _write_schema(tmp_path, "dashboard", {"route": "/dashboard"})
    target = tmp_path / "src" / "contracts" / "nav-flow.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    sentinel = {"version": "hand-written", "pages": []}
    target.write_text(json.dumps(sentinel), encoding="utf-8")

    ensure_nav_flow(tmp_path)  # must NOT overwrite an existing file
    assert json.loads(target.read_text(encoding="utf-8")) == sentinel


def test_ensure_nav_flow_none_without_schemas(tmp_path):
    assert ensure_nav_flow(tmp_path) is None

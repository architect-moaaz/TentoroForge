import pytest
from pathlib import Path
from services.phase_gates import check_pages_coverage


def test_passes_when_every_route_has_a_schema(tmp_path):
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "home.json").write_text("{}")
    (schemas / "login.json").write_text("{}")
    plan = {"pages": [
        {"route": "/", "name": "Home"},
        {"route": "/login", "name": "Login"},
    ]}
    result = check_pages_coverage(str(tmp_path), plan)
    assert result["passed"] is True
    assert result["missing"] == []


def test_fails_when_schema_missing(tmp_path):
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "home.json").write_text("{}")
    plan = {"pages": [
        {"route": "/", "name": "Home"},
        {"route": "/login", "name": "Login"},
        {"route": "/users", "name": "Users"},
    ]}
    result = check_pages_coverage(str(tmp_path), plan)
    assert result["passed"] is False
    assert "/login" in result["missing"]
    assert "/users" in result["missing"]
    assert len(result["missing"]) == 2


def test_dynamic_routes_resolved_via_detail_convention(tmp_path):
    """/users/[id] should look for src/schemas/users/detail.json."""
    schemas = tmp_path / "src" / "schemas" / "users"
    schemas.mkdir(parents=True)
    (schemas / "detail.json").write_text("{}")
    plan = {"pages": [{"route": "/users/[id]", "name": "User detail"}]}
    result = check_pages_coverage(str(tmp_path), plan)
    assert result["passed"] is True


def test_nested_routes_use_folder_layout(tmp_path):
    """/requests/new should look for src/schemas/requests/new.json (folder, not kebab)."""
    schemas = tmp_path / "src" / "schemas" / "requests"
    schemas.mkdir(parents=True)
    (schemas / "new.json").write_text("{}")
    plan = {"pages": [{"route": "/requests/new", "name": "New Request"}]}
    result = check_pages_coverage(str(tmp_path), plan)
    assert result["passed"] is True


def test_empty_plan_passes(tmp_path):
    """No declared pages -> trivially passes."""
    result = check_pages_coverage(str(tmp_path), {"pages": []})
    assert result["passed"] is True
    assert result["missing"] == []


def test_missing_pages_key_passes(tmp_path):
    result = check_pages_coverage(str(tmp_path), {})
    assert result["passed"] is True


def test_skips_malformed_entries(tmp_path):
    """Non-dict entries / entries without route -> skip, don't crash."""
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "home.json").write_text("{}")
    plan = {"pages": [
        {"route": "/"},
        "garbage",
        None,
        {"no_route": True},
    ]}
    result = check_pages_coverage(str(tmp_path), plan)
    assert result["passed"] is True


def test_none_plan_returns_passing(tmp_path):
    result = check_pages_coverage(str(tmp_path), None)
    assert result["passed"] is True


def test_coverage_passes_for_figma_emitted_pages(tmp_path):
    """When the deterministic Figma mapper has written every plan page's
    schema to disk, check_pages_coverage should pass — even though no LLM
    schema agent touched those routes."""
    from services.phase_gates import check_pages_coverage
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "login.json").write_text("{}")
    (schemas / "dashboard.json").write_text("{}")
    plan = {"pages": [
        {"route": "/login",     "figma_node_id": "1:2",  "file": "src/schemas/login.json"},
        {"route": "/dashboard", "figma_node_id": "1:74", "file": "src/schemas/dashboard.json"},
    ]}
    result = check_pages_coverage(str(tmp_path), plan)
    assert result["passed"] is True
    assert result["missing"] == []


def test_coverage_fails_when_figma_node_id_missing_schema(tmp_path):
    """A page with figma_node_id but no schema file on disk fails coverage."""
    from services.phase_gates import check_pages_coverage
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "login.json").write_text("{}")
    # dashboard has figma_node_id but no actual schema on disk
    plan = {"pages": [
        {"route": "/login",     "figma_node_id": "1:2",  "file": "src/schemas/login.json"},
        {"route": "/dashboard", "figma_node_id": "1:74", "file": "src/schemas/dashboard.json"},
    ]}
    result = check_pages_coverage(str(tmp_path), plan)
    assert result["passed"] is False
    assert result["missing"] == ["/dashboard"]

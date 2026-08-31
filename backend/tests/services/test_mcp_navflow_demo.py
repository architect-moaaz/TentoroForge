"""Programmatic assembly of the commitbiz-demo multi-page project.

Demonstrates Pillar 2 nav-flow interactivity:
- Two MCP-imported pages (Login + Intent Intelligence) live in one project
- nav-flow.json lists both pages so PreviewShell sidebar is populated
- Sign-in button navigate prop routes login → intent-intelligence

This test is marked as integration (requires fixture files) and is skipped
when /tmp/v1_design_context.tsx or /tmp/intel_design_context.tsx are absent.
"""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

FIXTURE_LOGIN = pathlib.Path("/tmp/v1_design_context.tsx")
FIXTURE_INTEL = pathlib.Path("/tmp/intel_design_context.tsx")

pytestmark = pytest.mark.skipif(
    not FIXTURE_LOGIN.exists() or not FIXTURE_INTEL.exists(),
    reason="MCP design-context fixtures not present in /tmp",
)


@pytest.fixture()
def demo_project(tmp_path):
    """Return a fresh temp directory pre-populated with commitbiz-demo structure."""
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "public" / "figma").mkdir(parents=True)
    return tmp_path


def test_upsert_nav_flow_idempotent(demo_project):
    """_upsert_nav_flow adds pages and is idempotent on repeated calls."""
    from services.figma_mcp_pipeline import _upsert_nav_flow

    out = str(demo_project)

    _upsert_nav_flow(out, "/login", "Login", "src/schemas/login.json")
    _upsert_nav_flow(out, "/intent-intelligence", "Intent Intelligence", "src/schemas/intent-intelligence.json")

    nav_path = demo_project / "src" / "contracts" / "nav-flow.json"
    assert nav_path.exists()

    nav = json.loads(nav_path.read_text())
    assert nav["version"] == "1.0"
    page_ids = {p["id"] for p in nav["pages"]}
    assert "login" in page_ids
    assert "intent-intelligence" in page_ids
    assert nav["initialPage"] == "login"

    # Idempotency: re-registering login does not duplicate it
    _upsert_nav_flow(out, "/login", "Login", "src/schemas/login.json")
    nav2 = json.loads(nav_path.read_text())
    assert len(nav2["pages"]) == 2, "second call should not add a duplicate"


def test_build_schema_from_jsx_sets_id_and_emits_navflow(demo_project):
    """build_schema_from_jsx with route= patches schema id/title and writes nav-flow."""
    from services.figma_mcp_pipeline import build_schema_from_jsx

    jsx = FIXTURE_LOGIN.read_text()
    out = str(demo_project)

    schema, _ = asyncio.run(
        build_schema_from_jsx(
            jsx,
            out,
            project_id="commitbiz-demo",
            route="/login",
            title="Login",
            schema_filename="login.json",
        )
    )

    assert schema["id"] == "login"
    assert schema["title"] == "Login"

    nav_path = demo_project / "src" / "contracts" / "nav-flow.json"
    assert nav_path.exists()
    nav = json.loads(nav_path.read_text())
    assert any(p["id"] == "login" for p in nav["pages"])


def test_commitbiz_demo_two_page_project(demo_project):
    """Full assembly: two pages → nav-flow lists both, schemas are valid PageV2."""
    from services.figma_mcp_pipeline import build_schema_from_jsx

    out = str(demo_project)

    # Page 1: Login
    login_schema, _ = asyncio.run(
        build_schema_from_jsx(
            FIXTURE_LOGIN.read_text(),
            out,
            project_id="commitbiz-demo",
            route="/login",
            title="Login",
            schema_filename="login.json",
        )
    )
    login_path = demo_project / "src" / "schemas" / "login.json"
    login_path.write_text(json.dumps(login_schema, indent=2))

    # Page 2: Intent Intelligence
    intel_schema, _ = asyncio.run(
        build_schema_from_jsx(
            FIXTURE_INTEL.read_text(),
            out,
            project_id="commitbiz-demo",
            route="/intent-intelligence",
            title="Intent Intelligence",
            schema_filename="intent-intelligence.json",
        )
    )
    intel_path = demo_project / "src" / "schemas" / "intent-intelligence.json"
    intel_path.write_text(json.dumps(intel_schema, indent=2))

    # Verify nav-flow.json
    nav_path = demo_project / "src" / "contracts" / "nav-flow.json"
    nav = json.loads(nav_path.read_text())

    assert nav["version"] == "1.0"
    assert len(nav["pages"]) == 2

    page_map = {p["id"]: p for p in nav["pages"]}
    assert "login" in page_map
    assert "intent-intelligence" in page_map

    assert page_map["login"]["route"] == "/login"
    assert page_map["login"]["schemaFile"] == "src/schemas/login.json"
    assert page_map["intent-intelligence"]["route"] == "/intent-intelligence"
    assert page_map["intent-intelligence"]["schemaFile"] == "src/schemas/intent-intelligence.json"

    # Schemas must be PageV2
    assert login_schema["schemaVersion"] == "2.0"
    assert intel_schema["schemaVersion"] == "2.0"
    assert login_schema["id"] == "login"
    assert intel_schema["id"] == "intent-intelligence"

    # Schemas must have children
    assert isinstance(login_schema.get("children"), list)
    assert len(login_schema["children"]) > 0
    assert isinstance(intel_schema.get("children"), list)
    assert len(intel_schema["children"]) > 0

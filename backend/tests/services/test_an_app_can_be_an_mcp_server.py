"""An application as an MCP server: its tools written from its definition, its
switch kept with the project and handed to the app, Smith able to read and
turn it, and the platform files delivered to apps built before it existed.
The protocol and the route themselves are tested where they ship
(`templates/runtime/__tests__/an-assistant-acts-as-the-person.test.mts`)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import app_settings
from services.blueprint import app_mcp

DOC = {
    "application": {"name": "Shop", "description": "A clothes shop"},
    "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Customer"}],
    "data": {"entities": [
        {"id": "ENT-001", "name": "Product", "table": "products", "description": "What is for sale",
         "fields": [{"name": "name", "type": "string"},
                    {"name": "category", "type": "string", "enumValues": ["Tops", "Bottoms"]},
                    {"name": "price", "type": "decimal"}]},
        {"id": "ENT-002", "name": "Order", "table": "orders", "fields": [{"name": "total", "type": "decimal"}]},
        {"id": "ENT-003", "name": "Old", "table": "olds", "status": "DEPRECATED", "fields": []},
    ], "relationships": []},
    "pages": [
        {"id": "PAGE-001", "route": "/products", "access": "public", "users": ["ROLE-001", "ROLE-002"],
         "data": {"primaryEntity": "ENT-001"}, "launches": ["FLOW-001"]},
        {"id": "PAGE-002", "route": "/admin/orders", "access": "authenticated", "users": ["ROLE-001"],
         "data": {"primaryEntity": "ENT-002"}, "launches": ["FLOW-002"]},
    ],
    "workflows": [
        {"id": "FLOW-001", "name": "Add Product", "purpose": "Put a product on sale", "trigger": {"kind": "manual"},
         "inputs": [{"name": "name", "type": "string"},
                    {"name": "category", "type": "string"},
                    {"name": "price", "type": "decimal", "required": False}],
         "steps": [{"key": "s", "entity": "ENT-001"}]},
        {"id": "FLOW-002", "name": "Refund Order", "trigger": {"kind": "manual"},
         "inputs": [{"name": "order", "kind": "record", "entity": "ENT-002", "description": "the order"}]},
        {"id": "FLOW-003", "name": "Nightly Report", "trigger": {"kind": "schedule"}, "inputs": []},
    ],
}


def test_the_tools_are_the_definitions_processes_and_records():
    data = app_mcp.catalog(DOC)
    tools = {w["tool"]: w for w in data["workflows"]}
    assert set(tools) == {"add_product", "refund_order"}            # a schedule is no one's to start
    add = tools["add_product"]
    assert add["id"] == "FLOW-001" and add["description"] == "Add Product: Put a product on sale"
    props = add["inputSchema"]["properties"]
    assert props["category"] == {"type": "string", "enum": ["Tops", "Bottoms"]}   # typed from the column it writes
    assert props["price"]["type"] == "number"
    assert add["inputSchema"]["required"] == ["name", "category"]
    refund = tools["refund_order"]["inputSchema"]["properties"]["order"]
    assert refund == {"type": "string", "description": "id of the Order record — the order"}
    records = {r["slug"]: r for r in data["records"]}
    assert set(records) == {"products", "orders"}
    assert records["products"]["find"] == "find_products" and records["products"]["get"] == "get_products"
    assert "category" in [f["name"] for f in records["products"]["fields"]]


def test_the_catalogue_is_written_beside_the_gates(tmp_path):
    out = app_mcp.project_app_mcp(DOC, tmp_path)
    assert out["files"] == ["src/lib/mcp/catalog.json"] and out["tools"] == 6
    data = json.loads((tmp_path / "src/lib/mcp/catalog.json").read_text())
    assert data["app"] == "Shop" and [w["tool"] for w in data["workflows"]] == ["add_product", "refund_order"]


def test_the_switch_is_kept_with_the_project_and_written_for_the_preview(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "package.json").write_text("{}")
    (app / ".env.local").write_text("DATABASE_URL=postgres://x\nFORGE_APP_MCP=off\n")
    assert app_settings.env_for(tmp_path) == {"FORGE_APP_MCP": "off"}      # off unless turned on
    app_settings.set_mcp(tmp_path, True, by="owner@shop.test")
    assert app_settings.mcp_enabled(tmp_path)
    assert json.loads((tmp_path / ".forge/app-settings.json").read_text())["mcpServer"]["changedBy"] == "owner@shop.test"
    assert (app / ".env.local").read_text() == "DATABASE_URL=postgres://x\nFORGE_APP_MCP=on\n"
    app_settings.set_mcp(tmp_path, False)
    assert (app / ".env.local").read_text().count("FORGE_APP_MCP") == 1
    assert "FORGE_APP_MCP=off" in (app / ".env.local").read_text()


def test_the_middleware_lets_a_token_through_to_the_route():
    from services.blueprint.projection import _ALWAYS_OPEN
    assert "api/mcp" in _ALWAYS_OPEN


def test_smith_reads_and_turns_the_switch(tmp_path):
    from services.smith import act, tools

    (tmp_path / "app").mkdir()
    app_mcp.project_app_mcp(DOC, tmp_path / "app")
    assert tools.is_act("app_mcp")
    said = act.run("app_mcp", {}, said=[], output_dir=str(tmp_path)).said
    assert said.startswith("Off — assistants may not connect")
    assert "- `add_product` runs Add Product — anyone signed in" in said
    assert "- `find_orders` / `get_orders` read Order — Admin" in said
    said = act.run("app_mcp", {"action": "on"}, said=[], output_dir=str(tmp_path)).said
    assert said.startswith("On — assistants may connect") and "/connect-ai" in said
    assert app_settings.mcp_enabled(tmp_path)
    nobody = act.run("app_mcp", {"action": "off"}, said=[], output_dir=str(tmp_path), unattended=True).said
    assert "owner's choice" in nobody and app_settings.mcp_enabled(tmp_path)


def test_an_app_built_before_gets_the_server_files_and_its_catalogue(tmp_path):
    from services.smith.sync_app import MCP_FILES, refresh_engine

    app = tmp_path / "app"
    (app / "src").mkdir(parents=True)
    (app / "package.json").write_text("{}")
    changed = refresh_engine(app, DOC, complete=False)
    for rel in MCP_FILES:
        assert (app / rel).is_file() and rel in changed
    assert "src/lib/mcp/catalog.json" in changed
    assert json.loads((app / "src/lib/mcp/catalog.json").read_text())["workflows"]
    again = refresh_engine(app, DOC, complete=False)
    assert not [c for c in again if "mcp" in c or "connect-ai" in c]             # current: untouched


def test_an_app_nobody_signs_in_to_gets_no_server(tmp_path):
    from services.smith.sync_app import refresh_engine

    app = tmp_path / "app"
    (app / "src").mkdir(parents=True)
    (app / "package.json").write_text("{}")
    refresh_engine(app, {**DOC, "security": {"authentication": "none"}}, complete=False)
    assert not (app / "src/app/api/mcp/route.ts").exists()


def test_the_account_menu_offers_the_connect_page_only_when_on():
    menu = (Path(__file__).resolve().parents[2] / "templates/app-foundation/src/app/(dashboard)/AccountMenu.tsx").read_text()
    assert "/api/mcp/tokens" in menu and "Connect an AI assistant" in menu and "{assistants && (" in menu


@pytest.mark.asyncio
async def test_the_owner_turns_it_on_and_off(auth_client, org_id, tmp_path, monkeypatch):
    r = await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Assisted App"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    from sqlalchemy import update

    from database import async_session
    from models.project import Project
    import uuid
    async with async_session() as db:
        await db.execute(update(Project).where(Project.id == uuid.UUID(pid)).values(output_dir=str(tmp_path)))
        await db.commit()
    (tmp_path / "app").mkdir()
    app_mcp.project_app_mcp(DOC, tmp_path / "app")

    r = await auth_client.get(f"/api/projects/{pid}/app-mcp")
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert [w["tool"] for w in r.json()["tools"]["workflows"]] == ["add_product", "refund_order"]
    r = await auth_client.put(f"/api/projects/{pid}/app-mcp", json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert app_settings.mcp_enabled(tmp_path)
    r = await auth_client.put(f"/api/projects/{pid}/app-mcp", json={"enabled": False})
    assert r.json()["enabled"] is False and not app_settings.mcp_enabled(tmp_path)

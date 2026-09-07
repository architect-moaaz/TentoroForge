"""Tests for the deterministic contract generator.

Focus: the `data_models` vs stale `entities` staleness bug and the new
app-model.json emission from `generate_contracts`.
"""
import json

from services.contract_generator import generate_contracts, _normalize_models


def _plan_list() -> dict:
    """Representative plan: 2 entities (Order FK->User), 1 approval workflow,
    a couple of pages with routes. Uses the CANONICAL `data_models` list and
    deliberately omits the legacy `entities` key."""
    return {
        "name": "Order Manager",
        "data_models": [
            {"name": "User", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "email", "type": "varchar"},
            ]},
            {"name": "Order", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "userId", "type": "uuid"},
                {"name": "total", "type": "numeric"},
                {"name": "status", "type": "varchar"},
            ]},
        ],
        "relations": [
            {"from": "Order", "to": "User", "type": "many-to-one", "foreignKey": "userId"},
        ],
        "workflows": [
            {"name": "OrderApproval", "trigger": "on order create",
             "description": "Manager must approve each Order before fulfillment"},
        ],
        "pages": [
            {"name": "OrderList", "route": "/orders", "entity": "Order", "description": "Orders"},
            {"name": "OrderDetail", "route": "/orders/:id", "entity": "Order", "description": "Order detail"},
        ],
    }


def test_event_bindings_from_data_models(tmp_path):
    """The workflow->entity inference must read `data_models` (canonical) not the
    stale `entities` key. With an approval workflow naming Order, the emitted
    event-bindings must contain the `order_created` start-binding. Before the
    fix (which read `plan.get("entities", [])`, empty here) that binding is
    absent, so this reproduces the staleness bug."""
    plan = _plan_list()
    res = generate_contracts(str(tmp_path), plan)
    assert not res["errors"], res["errors"]

    path = tmp_path / "src" / "contracts" / "event-bindings.json"
    assert path.exists()
    cfg = json.loads(path.read_text(encoding="utf-8"))
    bindings = cfg["bindings"]
    assert bindings, "event bindings must be non-empty"

    created = [b for b in bindings if b.get("source") == "data:order:create"]
    assert created, f"expected an order_created start-binding, got {bindings}"
    assert "OrderApproval" in created[0]["workflows"]


def test_seed_plan_from_data_models(tmp_path):
    """Seed plan must derive tables from `data_models`, not stale `entities`."""
    plan = _plan_list()
    res = generate_contracts(str(tmp_path), plan)
    assert not res["errors"], res["errors"]

    path = tmp_path / "contracts" / "seed-plan.json"
    assert path.exists()
    seed = json.loads(path.read_text(encoding="utf-8"))
    tables = seed["tables"]
    assert tables, "seed tables must be non-empty"
    names = {t["name"] for t in tables}
    assert {"User", "Order"} <= names


def test_legacy_dict_data_models(tmp_path):
    """`data_models` supplied as a legacy DICT keyed by name still yields output."""
    plan = _plan_list()
    plan["data_models"] = {
        "User": {"fields": [{"name": "id", "type": "uuid"}]},
        "Order": {"fields": [
            {"name": "id", "type": "uuid"},
            {"name": "userId", "type": "uuid"},
        ]},
    }
    res = generate_contracts(str(tmp_path), plan)
    assert not res["errors"], res["errors"]

    seed = json.loads((tmp_path / "contracts" / "seed-plan.json").read_text(encoding="utf-8"))
    assert {t["name"] for t in seed["tables"]} >= {"User", "Order"}

    app_model = json.loads((tmp_path / "src" / "contracts" / "app-model.json").read_text(encoding="utf-8"))
    assert set(app_model["entities"].keys()) >= {"User", "Order"}


def test_generate_contracts_emits_app_model(tmp_path):
    """`generate_contracts` must emit src/contracts/app-model.json with the
    entities + pages keys downstream consumers read."""
    plan = _plan_list()
    res = generate_contracts(str(tmp_path), plan)
    assert "src/contracts/app-model.json" in res["generated"], res
    assert not res["errors"], res["errors"]

    path = tmp_path / "src" / "contracts" / "app-model.json"
    assert path.exists()
    model = json.loads(path.read_text(encoding="utf-8"))
    assert "entities" in model and "pages" in model
    assert set(model["entities"].keys()) >= {"User", "Order"}
    routes = {p["route"] for p in model["pages"]}
    assert "/orders" in routes


def test_normalize_models_list_and_dict():
    lst = _normalize_models([{"name": "Order"}, {"name": "User"}])
    assert [m["name"] for m in lst] == ["Order", "User"]

    d = _normalize_models({"Order": {"fields": []}, "User": {}})
    assert {m["name"] for m in d} == {"Order", "User"}

    assert _normalize_models(None) == []


def test_api_client_uses_registry_table_for_hinted_entity(tmp_path):
    """api-client CRUD paths point at /api/data/{registry table}. For a hinted
    uncountable entity the hint wins — /api/data/equipment, never /equipments."""
    plan = {"name": "Fleet", "data_models": [
        {"name": "Equipment", "table": "equipment", "fields": [
            {"name": "id", "type": "uuid"},
            {"name": "name", "type": "varchar"},
        ]},
    ]}
    res = generate_contracts(str(tmp_path), plan)
    assert not res["errors"], res["errors"]
    api = (tmp_path / "src" / "contracts" / "api-client.ts").read_text(encoding="utf-8")
    assert "/api/data/equipment" in api
    assert "/api/data/equipments" not in api


def test_navigation_flow_route_uses_registry_slug(tmp_path):
    """nav-flow list/create/detail route segments use the registry slug (kebab
    PLURAL), fixing the old divergent inline kebab-SINGULAR. api sub-paths use
    the registry table (camelCase plural)."""
    plan = {"name": "X", "data_models": [
        {"name": "RecruitmentDrive", "fields": [{"name": "id", "type": "uuid"}]},
    ]}
    res = generate_contracts(str(tmp_path), plan)
    assert not res["errors"], res["errors"]
    nav = json.loads((tmp_path / "src" / "contracts" / "navigation-flow.json").read_text(encoding="utf-8"))
    crud = nav["flows"]["entity_crud"]["RecruitmentDrive"]
    # kebab PLURAL now (was singular "/recruitment-drive")
    assert crud["list"]["route"] == "/recruitment-drives"
    assert crud["create"]["route"] == "/recruitment-drives/new"
    assert crud["detail"]["route"] == "/recruitment-drives/{id}"
    # api sub-paths still use the camelCase-plural registry table
    assert "/api/data/recruitmentDrives" in crud["list"]["actions"]["delete"]["api"]
    # sidebar href matches the route
    hrefs = {i["href"] for i in nav["navigation"]["sidebar_items"]}
    assert "/recruitment-drives" in hrefs


def test_navigation_flow_hinted_entity_route(tmp_path):
    """A hinted uncountable entity's nav route is the hint slug, never pluralized."""
    plan = {"name": "Fleet", "data_models": [
        {"name": "Equipment", "table": "equipment", "fields": [{"name": "id", "type": "uuid"}]},
    ]}
    res = generate_contracts(str(tmp_path), plan)
    assert not res["errors"], res["errors"]
    nav = json.loads((tmp_path / "src" / "contracts" / "navigation-flow.json").read_text(encoding="utf-8"))
    crud = nav["flows"]["entity_crud"]["Equipment"]
    assert crud["list"]["route"] == "/equipment"
    assert crud["create"]["route"] == "/equipment/new"
    assert "/api/data/equipment/" in crud["detail"]["actions"]["delete"]["api"]
    assert "equipments" not in json.dumps(nav)


def test_deterministic_contracts_pass_the_gate(tmp_path):
    """The payoff: deterministic generate_contracts must satisfy
    phase_gates.check_contract_completeness so the pipeline SKIPS the LLM
    contract agent. Requires design-system.tsx + api-client fns + app-model
    pages per entity — all emitted deterministically now."""
    from services.phase_gates import check_contract_completeness

    plan = {
        "name": "Order Manager",
        "data_models": [
            {"name": "Order", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "userId", "type": "uuid"},
                {"name": "status", "type": "varchar"},
            ]},
            {"name": "User", "fields": [{"name": "id", "type": "uuid"}, {"name": "email", "type": "varchar"}]},
        ],
        "relations": [{"from": "Order", "to": "User", "foreignKey": "userId"}],
        "workflows": [{"name": "OrderApproval", "trigger": {"type": "manual"}}],
        "pages": [
            {"route": "/orders", "name": "OrdersListPage", "entity": "Order", "archetype": "list"},
            {"route": "/orders/:id", "name": "OrderDetailPage", "entity": "Order", "archetype": "detail"},
            {"route": "/orders/new", "name": "OrderCreatePage", "entity": "Order", "archetype": "form"},
            {"route": "/users", "name": "UsersListPage", "entity": "User", "archetype": "list"},
            {"route": "/users/:id", "name": "UserDetailPage", "entity": "User", "archetype": "detail"},
            {"route": "/users/new", "name": "UserCreatePage", "entity": "User", "archetype": "form"},
        ],
    }
    res = generate_contracts(str(tmp_path), plan)
    assert not res["errors"], res["errors"]
    assert "src/contracts/design-system.tsx" in res["generated"]

    gate = check_contract_completeness(str(tmp_path), plan)
    assert gate["passed"], gate.get("missing") or gate.get("issues")

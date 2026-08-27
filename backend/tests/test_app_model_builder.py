"""Deterministic app-model.json builder: expands the plan into a dependency graph
+ page/route manifest that downstream code and agents read. No LLM."""
import json

from services.app_model_builder import build_app_model, write_app_model

PLAN = {
    "name": "Order Manager",
    "data_models": [
        {"name": "Order", "fields": [
            {"name": "id", "type": "uuid"},
            {"name": "userId", "type": "uuid"},
            {"name": "total", "type": "numeric"},
        ]},
        {"name": "User", "fields": [{"name": "id", "type": "uuid"}]},
        {"name": "Invoice", "fields": [
            {"name": "id", "type": "uuid"},
            {"name": "orderId", "type": "uuid"},
        ]},
    ],
    "relations": [
        {"from": "Order", "to": "User", "type": "many-to-one", "foreignKey": "userId"},
        {"from": "Invoice", "to": "Order", "type": "many-to-one", "foreignKey": "orderId"},
    ],
}


def test_entity_paths_and_table():
    m = build_app_model(PLAN)
    assert m["name"] == "Order Manager"
    order = m["entities"]["Order"]
    assert order["table"] == "orders"
    assert order["schema"] == "src/db/schema/orders.ts"
    assert order["type"] == "src/types/orders.ts"
    assert order["api"] == [
        "src/app/api/orders/route.ts",
        "src/app/api/orders/[id]/route.ts",
    ]
    assert order["components"] == [
        "src/components/orders/OrderTable.tsx",
        "src/components/orders/OrderForm.tsx",
    ]
    assert order["pages"] == [
        "src/app/orders/page.tsx",
        "src/app/orders/[id]/page.tsx",
    ]


def test_multiword_entity_segments():
    plan = {"name": "X", "data_models": [{"name": "ExpenseReport", "fields": []}]}
    m = build_app_model(plan)
    er = m["entities"]["ExpenseReport"]
    # table constant + api fetch segment = camelCase plural (matches api-client)
    assert er["table"] == "expenseReports"
    assert er["api"][0] == "src/app/api/expenseReports/route.ts"
    # filesystem segments (schema/type/page/component files) = kebab plural,
    # matching the files schema_builder actually writes + the real page routes
    assert er["schema"] == "src/db/schema/expense-reports.ts"
    assert er["type"] == "src/types/expense-reports.ts"
    assert er["pages"] == [
        "src/app/expense-reports/page.tsx",
        "src/app/expense-reports/[id]/page.tsx",
    ]
    assert er["components"][0] == "src/components/expense-reports/ExpenseReportTable.tsx"


def test_depends_on_and_used_by_bidirectional():
    m = build_app_model(PLAN)
    assert m["entities"]["Order"]["depends_on"] == ["User"]
    assert m["entities"]["Order"]["used_by"] == ["Invoice"]
    assert m["entities"]["User"]["used_by"] == ["Order"]
    assert m["entities"]["User"]["depends_on"] == []
    assert m["entities"]["Invoice"]["depends_on"] == ["Order"]
    assert m["entities"]["Invoice"]["used_by"] == []


def test_pages_manifest_fallback_when_no_plan_pages():
    # PLAN has no `pages` key → derive CRUD routes per entity (kebab slug)
    m = build_app_model(PLAN)
    routes = {p["route"] for p in m["pages"]}
    assert {"/", "/login", "/signup", "/error"} <= routes
    assert {"/orders", "/orders/new", "/orders/[id]"} <= routes
    assert {"/invoices", "/invoices/new", "/invoices/[id]"} <= routes
    assert all("route" in p for p in m["pages"])
    by_route = {p["route"]: p for p in m["pages"]}
    assert by_route["/orders"]["component"] == "OrderListPage"
    assert by_route["/orders/[id]"]["component"] == "OrderDetailPage"
    assert by_route["/"]["component"] == "DashboardPage"
    assert by_route["/error"]["component"] == "ErrorPage"


def test_pages_faithful_to_planner_pages():
    # When the planner emits its own pages (real routes, incl. non-CRUD
    # archetypes), the manifest preserves them verbatim (":id" -> "[id]").
    plan = {
        "name": "Y",
        "data_models": [{"name": "Order", "fields": []}],
        "pages": [
            {"route": "/orders", "name": "OrdersListPage", "entity": "Order", "archetype": "list"},
            {"route": "/orders/:id", "name": "OrderDetailPage", "entity": "Order", "archetype": "detail"},
            {"route": "/board", "name": "OrderBoardPage", "entity": "Order", "archetype": "kanban"},
            {"route": "/analytics", "name": "AnalyticsPage", "entity": None, "archetype": "report"},
        ],
    }
    m = build_app_model(plan)
    by_route = {p["route"]: p for p in m["pages"]}
    # non-CRUD pages the planner chose are preserved (entity-derivation would drop these)
    assert "/board" in by_route and by_route["/board"]["component"] == "OrderBoardPage"
    assert "/analytics" in by_route
    # express-style :id normalised to Next bracket form
    assert "/orders/[id]" in by_route
    assert by_route["/orders"]["entity"] == "Order"
    # fixed auth/dashboard pages still guaranteed
    assert {"/", "/login", "/signup", "/error"} <= set(by_route)


def test_multiword_fallback_route_is_kebab_phase_gate_compatible():
    # phase_gates checks "/{kebab-singular}" or "/{kebab-singular}s" — the kebab
    # fallback route "/expense-reports" satisfies the "+s" form.
    plan = {"name": "X", "data_models": [{"name": "ExpenseReport", "fields": []}]}
    routes = {p["route"] for p in build_app_model(plan)["pages"]}
    assert "/expense-reports" in routes


def test_routes_five_per_entity():
    m = build_app_model(PLAN)
    order_routes = [r for r in m["routes"] if r["path"].startswith("/api/orders")]
    assert len(order_routes) == 5
    sig = {(r["method"], r["path"]) for r in order_routes}
    assert sig == {
        ("GET", "/api/orders"),
        ("POST", "/api/orders"),
        ("GET", "/api/orders/[id]"),
        ("PATCH", "/api/orders/[id]"),
        ("DELETE", "/api/orders/[id]"),
    }
    # 3 entities x 5 routes
    assert len(m["routes"]) == 15


def test_missing_relations_no_crash():
    plan = {"name": "X", "data_models": [{"name": "Order", "fields": []}]}
    m = build_app_model(plan)
    assert m["entities"]["Order"]["depends_on"] == []
    assert m["entities"]["Order"]["used_by"] == []


def test_data_models_as_dict_legacy():
    plan = {
        "name": "Legacy",
        "data_models": {
            "Order": {"fields": [{"name": "userId", "type": "uuid"}]},
            "User": {"fields": []},
        },
        "relations": [{"from": "Order", "to": "User"}],
    }
    m = build_app_model(plan)
    assert set(m["entities"].keys()) == {"Order", "User"}
    assert m["entities"]["Order"]["table"] == "orders"
    assert m["entities"]["Order"]["depends_on"] == ["User"]
    assert m["entities"]["User"]["used_by"] == ["Order"]


def test_relations_tolerant_source_target_keys():
    plan = {
        "name": "X",
        "data_models": [{"name": "A", "fields": []}, {"name": "B", "fields": []}],
        "relations": [{"source": "A", "target": "B"}],
    }
    m = build_app_model(plan)
    assert m["entities"]["A"]["depends_on"] == ["B"]
    assert m["entities"]["B"]["used_by"] == ["A"]


def test_hinted_entity_uses_registry_table():
    # Uncountable/hinted entity: the planner `table` hint wins everywhere.
    # app-model must NOT re-pluralize "equipment" -> "equipments".
    plan = {"name": "Fleet", "data_models": [
        {"name": "Equipment", "table": "equipment", "fields": [{"name": "id", "type": "uuid"}]},
    ]}
    m = build_app_model(plan)
    eq = m["entities"]["Equipment"]
    assert eq["table"] == "equipment"                       # hint honored, NOT "equipments"
    assert eq["api"] == [
        "src/app/api/equipment/route.ts",
        "src/app/api/equipment/[id]/route.ts",
    ]
    assert eq["schema"] == "src/db/schema/equipment.ts"     # slug == hint, not "equipments"
    assert eq["type"] == "src/types/equipment.ts"
    assert eq["pages"] == [
        "src/app/equipment/page.tsx",
        "src/app/equipment/[id]/page.tsx",
    ]
    api_paths = {r["path"] for r in m["routes"]}
    assert "/api/equipment" in api_paths
    assert "/api/equipments" not in api_paths


def test_no_hint_entity_unchanged_regression():
    # Regression guard: a no-hint multi-word entity keeps its byte-identical
    # camelCase-plural table + kebab-plural slug (no behavior change).
    plan = {"name": "X", "data_models": [{"name": "RecruitmentDrive", "fields": []}]}
    m = build_app_model(plan)
    rd = m["entities"]["RecruitmentDrive"]
    assert rd["table"] == "recruitmentDrives"
    assert rd["schema"] == "src/db/schema/recruitment-drives.ts"
    assert rd["type"] == "src/types/recruitment-drives.ts"
    assert rd["api"][0] == "src/app/api/recruitmentDrives/route.ts"
    assert rd["pages"][0] == "src/app/recruitment-drives/page.tsx"


def test_write_app_model(tmp_path):
    path = write_app_model(str(tmp_path), PLAN)
    p = tmp_path / "src" / "contracts" / "app-model.json"
    assert path == str(p)
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["name"] == "Order Manager"
    assert "Order" in data["entities"]
    assert any(r["route"] == "/orders" for r in data["pages"])

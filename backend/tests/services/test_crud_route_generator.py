from services.crud_route_generator import ensure_api_routes, parse_schema_file, slug_for


def test_parse_schema_and_slug():
    info = parse_schema_file('export const workOrders = pgTable("work_orders", { id: serial("id").primaryKey() });')
    assert info == {"export": "workOrders", "table": "work_orders", "id_numeric": True}
    assert slug_for("work_orders") == "work-orders"
    uuid = parse_schema_file('export const customers = pgTable("customers", { id: uuid("id").primaryKey() });')
    assert uuid["id_numeric"] is False


def test_ensure_api_routes_fills_every_entity(tmp_path):
    schema = tmp_path / "src" / "db" / "schema"
    schema.mkdir(parents=True)
    (schema / "customer.ts").write_text('export const customers = pgTable("customers", { id: serial("id").primaryKey() });', encoding="utf-8")
    (schema / "work_order.ts").write_text('export const workOrders = pgTable("work_orders", { id: uuid("id").primaryKey() });', encoding="utf-8")
    (schema / "index.ts").write_text('export * from "./customer";', encoding="utf-8")

    written = ensure_api_routes(tmp_path)
    api = tmp_path / "src" / "app" / "api"

    for slug in ("customers", "work-orders"):
        assert (api / slug / "route.ts").exists()
        assert (api / slug / "[id]" / "route.ts").exists()
        assert (api / slug / "stats" / "route.ts").exists()
    assert len(written) == 6  # 2 entities x 3 routes

    listing = (api / "customers" / "route.ts").read_text(encoding="utf-8")
    assert 'import { customers } from "@/db/schema"' in listing
    assert "db.select().from(customers)" in listing
    assert "db.insert(customers)" in listing

    # id coercion: serial -> Number(...), uuid -> raw string
    assert "Number(params.id)" in (api / "customers" / "[id]" / "route.ts").read_text(encoding="utf-8")
    assert "Number(params.id)" not in (api / "work-orders" / "[id]" / "route.ts").read_text(encoding="utf-8")


def test_non_destructive_keeps_existing_routes(tmp_path):
    schema = tmp_path / "src" / "db" / "schema"
    schema.mkdir(parents=True)
    (schema / "customer.ts").write_text('export const customers = pgTable("customers", { id: serial("id") });', encoding="utf-8")
    existing = tmp_path / "src" / "app" / "api" / "customers"
    existing.mkdir(parents=True)
    (existing / "route.ts").write_text("// custom LLM route — keep me", encoding="utf-8")

    ensure_api_routes(tmp_path)
    assert (existing / "route.ts").read_text(encoding="utf-8") == "// custom LLM route — keep me"
    assert (existing / "[id]" / "route.ts").exists()  # missing ones still filled

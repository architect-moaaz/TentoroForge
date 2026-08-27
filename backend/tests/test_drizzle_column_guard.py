"""A column emitted as `sql`varchar(50) default 'X'`.notNull()` throws at import
(sql fragments have no builder methods) and crashes migrate + seed. The guard
rewrites it to a real Drizzle column builder."""
from services.drizzle_column_guard import guard_drizzle_columns, _convert


def _schema(body_line: str) -> str:
    return (
        'import { pgTable, uuid, integer, timestamp } from "drizzle-orm/pg-core";\n'
        'import { sql } from "drizzle-orm";\n\n'
        'export const classBookings = pgTable("class_bookings", {\n'
        '  id: uuid("id").primaryKey().defaultRandom(),\n'
        f'  {body_line}\n'
        '  createdAt: timestamp("created_at").defaultNow().notNull(),\n'
        '});\n'
    )


def _write(tmp_path, text):
    d = tmp_path / "src" / "db" / "schema"
    d.mkdir(parents=True)
    (d / "class-bookings.ts").write_text(text)
    return d / "class-bookings.ts"


def test_rewrites_varchar_default_notnull(tmp_path):
    fp = _write(tmp_path, "status: sql`varchar(50) default 'Confirmed'`.notNull(),")
    res = guard_drizzle_columns(tmp_path)
    assert res["fixed"] == 1
    out = fp.read_text()
    assert 'status: varchar("status", { length: 50 }).default("Confirmed").notNull()' in out
    assert "sql`varchar" not in out
    # helper added to the pg-core import
    assert "varchar" in out.split('drizzle-orm/pg-core')[0]


def test_camelcase_prop_gets_snake_column(tmp_path):
    fp = _write(tmp_path, "membershipTier: sql`varchar(20) default 'Bronze'`.notNull(),")
    guard_drizzle_columns(tmp_path)
    assert 'membershipTier: varchar("membership_tier", { length: 20 })' in fp.read_text()


def test_not_null_inside_body(tmp_path):
    fp = _write(tmp_path, "status: sql`varchar(30) not null default 'A'`,")
    guard_drizzle_columns(tmp_path)
    out = fp.read_text()
    assert '.default("A").notNull()' in out
    assert out.count(".notNull()") >= 1  # not doubled


def test_numeric_and_boolean(tmp_path):
    d = tmp_path / "src" / "db" / "schema"
    d.mkdir(parents=True)
    (d / "x.ts").write_text(_schema(
        "price: sql`numeric(10,2) default 0`.notNull(),\n"
        "  active: sql`boolean default true`.notNull(),"
    ))
    guard_drizzle_columns(tmp_path)
    out = (d / "x.ts").read_text()
    assert 'price: numeric("price", { precision: 10, scale: 2 }).default(0).notNull()' in out
    assert 'active: boolean("active").default(true).notNull()' in out
    imports = out.split('drizzle-orm/pg-core')[0]
    assert "numeric" in imports and "boolean" in imports


def test_leaves_valid_columns_and_checks_untouched(tmp_path):
    valid = (
        'import { pgTable, uuid, varchar, timestamp, check } from "drizzle-orm/pg-core";\n'
        'import { sql } from "drizzle-orm";\n\n'
        'export const t = pgTable("t", {\n'
        '  id: uuid("id").primaryKey(),\n'
        '  status: varchar("status", { length: 50 }).notNull(),\n'
        '}, (table) => ({\n'
        '  ck: check("c", sql`status <> \'\'`),\n'   # sql in a check() is NOT a column
        '}));\n'
    )
    d = tmp_path / "src" / "db" / "schema"
    d.mkdir(parents=True)
    (d / "t.ts").write_text(valid)
    res = guard_drizzle_columns(tmp_path)
    assert res["fixed"] == 0
    assert (d / "t.ts").read_text() == valid   # untouched


def test_idempotent(tmp_path):
    _write(tmp_path, "status: sql`varchar(50) default 'Confirmed'`.notNull(),")
    guard_drizzle_columns(tmp_path)
    second = guard_drizzle_columns(tmp_path)
    assert second["fixed"] == 0


def test_unknown_type_left_alone(tmp_path):
    fp = _write(tmp_path, "geom: sql`geography(Point,4326)`.notNull(),")
    res = guard_drizzle_columns(tmp_path)
    assert res["fixed"] == 0
    assert "sql`geography" in fp.read_text()


def test_missing_dir_safe(tmp_path):
    assert guard_drizzle_columns(tmp_path) == {"fixed": 0, "changes": []}

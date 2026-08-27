from services.seed_backstop import (
    parse_pg_tables, find_auth_table, _admin_value, render_admin_seed, ensure_seed_file,
)

SCHEMA = '''
import { pgTable, uuid, varchar, timestamp, boolean } from "drizzle-orm/pg-core";

export const users = pgTable("users", {
  id: uuid("id").primaryKey(),
  username: varchar("username").notNull(),
  email: varchar("email").notNull(),
  full_name: varchar("full_name").notNull(),
  role: varchar("role").notNull(),
  password_hash: varchar("password_hash").notNull(),
  last_login: timestamp("last_login"),
  status: varchar("status").notNull(),
  created_at: timestamp("created_at").notNull().defaultNow(),
  updated_at: timestamp("updated_at").notNull(),
});

export const trucks = pgTable("trucks", {
  id: uuid("id").primaryKey(),
  plate_number: varchar("plate_number").notNull(),
  is_active: boolean("is_active").notNull(),
});
'''


def test_parse_tables_and_columns():
    t = parse_pg_tables(SCHEMA)
    assert set(t) == {"users", "trucks"}
    cols = {c["col"]: c for c in t["users"]}
    assert cols["id"]["primary_key"] and cols["id"]["type"] == "uuid"
    assert cols["username"]["not_null"] and not cols["username"]["has_default"]
    assert cols["created_at"]["has_default"]      # defaultNow()
    assert not cols["last_login"]["not_null"]     # nullable


def test_find_auth_table():
    assert find_auth_table(parse_pg_tables(SCHEMA)) == "users"


def test_admin_value_mapping():
    pw = {"col": "password_hash", "type": "varchar", "not_null": True, "has_default": False, "primary_key": False}
    assert _admin_value(pw).startswith('"$2')          # bcrypt hash
    un = {"col": "username", "type": "varchar", "not_null": True, "has_default": False, "primary_key": False}
    assert _admin_value(un) == '"admin"'
    ts = {"col": "updated_at", "type": "timestamp", "not_null": True, "has_default": False, "primary_key": False}
    assert _admin_value(ts) == "new Date()"
    defaulted = {"col": "created_at", "type": "timestamp", "not_null": True, "has_default": True, "primary_key": False}
    assert _admin_value(defaulted) is None             # omit defaulted
    nullable = {"col": "last_login", "type": "timestamp", "not_null": False, "has_default": False, "primary_key": False}
    assert _admin_value(nullable) is None              # omit nullable


def test_render_seed_has_admin_insert():
    t = parse_pg_tables(SCHEMA)
    ts = render_admin_seed("users", t["users"])
    assert 'import { db } from "./index"' in ts
    assert 'import { users } from "./schema"' in ts
    # PK is the fixed admin uuid (deterministic across reseeds), not random.
    assert "a0000000-0000-4000-8000-0000000000ad" in ts
    assert 'username: "admin"' in ts
    assert "password_hash:" in ts and "$2" in ts
    assert ".onConflictDoNothing()" in ts
    # defaulted / nullable columns omitted
    assert "created_at:" not in ts
    assert "last_login:" not in ts


def test_ensure_seed_writes_when_missing(tmp_path):
    db = tmp_path / "src" / "db"
    db.mkdir(parents=True)
    (db / "schema.ts").write_text(SCHEMA)
    written = ensure_seed_file(tmp_path)
    assert written is not None
    content = (db / "seed.ts").read_text()
    assert 'username: "admin"' in content


def test_ensure_seed_does_not_overwrite_real_seed(tmp_path):
    db = tmp_path / "src" / "db"
    db.mkdir(parents=True)
    (db / "schema.ts").write_text(SCHEMA)
    real = "// a real, substantial LLM-generated seed file\n" + ("x" * 300)
    (db / "seed.ts").write_text(real)
    assert ensure_seed_file(tmp_path) is None
    assert (db / "seed.ts").read_text() == real


def test_ensure_seed_noop_without_schema(tmp_path):
    assert ensure_seed_file(tmp_path) is None

"""Seed backstop must find the auth table in the PER-ENTITY schema dir
(src/db/schema/*.ts), not just src/db/schema.ts — the auth `users` table is
emitted into src/db/schema/user.ts by the auth agent, so reading only schema.ts
misses it and no login user is ever seeded (app is unusable, auth-gated)."""
from pathlib import Path

from services.seed_backstop import ensure_seed_file, _find_auth_source

_USER_TS = '''import { pgTable, text, serial } from "drizzle-orm/pg-core";
export const users = pgTable("users", {
  id: serial("id").primaryKey(),
  email: text("email").notNull().unique(),
  password: text("password").notNull(),
  name: text("name"),
});
'''

_SCHEMA_TS = '''import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";
export const project = pgTable("project", { id: uuid("id").primaryKey(), name: varchar("name") });
'''


def _app(tmp_path: Path) -> Path:
    db = tmp_path / "src" / "db"
    (db / "schema").mkdir(parents=True)
    (db / "schema" / "user.ts").write_text(_USER_TS, encoding="utf-8")
    (db / "schema" / "projects.ts").write_text(_SCHEMA_TS.replace("project", "projects2"), encoding="utf-8")
    (db / "schema" / "index.ts").write_text('export * from "./user";\nexport * from "./projects";\n', encoding="utf-8")
    (db / "schema.ts").write_text(_SCHEMA_TS, encoding="utf-8")  # domain-only, NO users
    return tmp_path


def test_finds_auth_table_in_per_entity_dir(tmp_path):
    var, cols, import_module = _find_auth_source(_app(tmp_path))
    assert var == "users"
    assert import_module == "./schema/user"           # NOT "./schema" (which lacks users)
    assert any(c["col"] == "password" for c in cols)


def test_ensure_seed_file_emits_correct_import(tmp_path):
    p = ensure_seed_file(_app(tmp_path))
    assert p is not None
    seed = (tmp_path / "src" / "db" / "seed.ts").read_text(encoding="utf-8")
    assert 'import { users } from "./schema/user";' in seed
    assert "admin@example.com" in seed
    assert ".insert(users)" in seed


def test_still_works_with_single_file_schema_only(tmp_path):
    # legacy single-file layout where users IS in schema.ts
    db = tmp_path / "src" / "db"; db.mkdir(parents=True)
    db.joinpath("schema.ts").write_text(_USER_TS, encoding="utf-8")
    var, cols, import_module = _find_auth_source(tmp_path)
    assert var == "users" and import_module == "./schema"

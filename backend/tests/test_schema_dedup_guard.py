"""Tests for the gen-time duplicate-pgTable guard."""
from __future__ import annotations

import os

from services.schema_dedup_guard import dedup_schema_tables


def _schema_dir(tmp_path):
    d = tmp_path / "src" / "db" / "schema"
    d.mkdir(parents=True)
    return d


def _write(d, name, text):
    (d / name).write_text(text, encoding="utf-8")


def test_dedup_prefers_auth_users(tmp_path):
    d = _schema_dir(tmp_path)
    _write(d, "user.ts", (
        '// required by auth.ts\n'
        'import { pgTable, text, uuid } from "drizzle-orm/pg-core";\n'
        'export const users = pgTable("users", {\n'
        '  id: uuid("id").primaryKey(),\n'
        '  password: text("password").notNull(),\n'
        '});\n'
    ))
    _write(d, "users.ts", (
        'import { pgTable, text, uuid } from "drizzle-orm/pg-core";\n'
        'export const users = pgTable("users", {\n'
        '  id: uuid("id").primaryKey(),\n'
        '  email: text("email").notNull(),\n'
        '});\n'
    ))
    _write(d, "index.ts", (
        'export * from "./user";\n'
        'export * from "./users";\n'
    ))

    res = dedup_schema_tables(str(tmp_path))

    assert "users" in res["duplicates"]
    assert res["kept"]["users"] == str(d / "user.ts")
    assert str(d / "users.ts") in res["removed"]
    assert not (d / "users.ts").exists()
    assert (d / "user.ts").exists()

    barrel = (d / "index.ts").read_text(encoding="utf-8")
    assert './users"' not in barrel
    assert './user"' in barrel


def test_dedup_prefers_more_columns_when_no_marker(tmp_path):
    d = _schema_dir(tmp_path)
    _write(d, "things_small.ts", (
        'import { pgTable, text, uuid } from "drizzle-orm/pg-core";\n'
        'export const things = pgTable("things", {\n'
        '  id: uuid("id").primaryKey(),\n'
        '  name: text("name"),\n'
        '});\n'
    ))
    _write(d, "things_big.ts", (
        'import { pgTable, text, uuid, integer } from "drizzle-orm/pg-core";\n'
        'export const things = pgTable("things", {\n'
        '  id: uuid("id").primaryKey(),\n'
        '  name: text("name"),\n'
        '  color: text("color"),\n'
        '  size: integer("size"),\n'
        '  note: text("note"),\n'
        '});\n'
    ))

    res = dedup_schema_tables(str(tmp_path))

    assert res["kept"]["things"] == str(d / "things_big.ts")
    assert str(d / "things_small.ts") in res["removed"]
    assert not (d / "things_small.ts").exists()
    assert (d / "things_big.ts").exists()


def test_no_duplicates_noop(tmp_path):
    d = _schema_dir(tmp_path)
    _write(d, "a.ts", (
        'import { pgTable, text } from "drizzle-orm/pg-core";\n'
        'export const alpha = pgTable("alpha", { name: text("name") });\n'
    ))
    _write(d, "b.ts", (
        'import { pgTable, text } from "drizzle-orm/pg-core";\n'
        'export const beta = pgTable("beta", { name: text("name") });\n'
    ))

    res = dedup_schema_tables(str(tmp_path))

    assert res["duplicates"] == {}
    assert res["removed"] == []
    assert (d / "a.ts").exists()
    assert (d / "b.ts").exists()


def test_unresolved_when_file_has_other_unique_table(tmp_path):
    d = _schema_dir(tmp_path)
    # canonical keeper for `users`
    _write(d, "user.ts", (
        '// required by auth.ts\n'
        'import { pgTable, text, uuid } from "drizzle-orm/pg-core";\n'
        'export const users = pgTable("users", {\n'
        '  id: uuid("id").primaryKey(),\n'
        '  password: text("password").notNull(),\n'
        '});\n'
    ))
    # duplicates `users` BUT also defines a unique `profiles` table → must NOT delete
    _write(d, "misc.ts", (
        'import { pgTable, text, uuid } from "drizzle-orm/pg-core";\n'
        'export const users = pgTable("users", {\n'
        '  id: uuid("id").primaryKey(),\n'
        '  email: text("email"),\n'
        '});\n'
        'export const profiles = pgTable("profiles", {\n'
        '  id: uuid("id").primaryKey(),\n'
        '  bio: text("bio"),\n'
        '});\n'
    ))

    res = dedup_schema_tables(str(tmp_path))

    assert "users" in res["duplicates"]
    assert str(d / "misc.ts") in res["unresolved"]
    assert str(d / "misc.ts") not in res["removed"]
    assert (d / "misc.ts").exists()

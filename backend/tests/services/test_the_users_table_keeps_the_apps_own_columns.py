"""The users table is the auth foundation's columns and the app's own, merged.

A build writes an app's User columns (a role, profile fields) into
`src/db/schema/user.ts` beside the foundation's. Two things went wrong once the
foundation grew the columns sign-up writes to prove an address:
  * the engine refresh copied the template over that file, taking the app's
    `role` away (and a publish's `drizzle-kit push --force` would then drop it);
  * the build's merged table kept its own old list of base columns, so sign-up
    wrote `email_verification` into a table without it, and every account failed.
Both now read the foundation's file, and keep the app's columns.
"""
from __future__ import annotations

from pathlib import Path

from services import schema_builder as SB

FOUNDATION = Path(SB.__file__).resolve().parents[1] / "templates" / "app-foundation" / "src" / "db" / "schema" / "user.ts"

MERGED_OLD = '''// Users table — auth foundation base columns MERGED with the app's domain
import { pgTable, uuid, text, boolean, timestamp } from "drizzle-orm/pg-core";
import { departments } from "./departments";

export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  email: text("email").notNull().unique(),
  password: text("password").notNull(),
  name: text("name"),
  isActive: boolean("is_active").default(true),
  createdAt: timestamp("created_at").defaultNow(),
  role: text("role").default("member").notNull(),
  departmentId: uuid("department_id").references(() => departments.id),
});
'''


def _props(text: str) -> list[str]:
    return [n for n, _, _ in SB.user_columns(text)]


def test_the_foundation_is_where_the_base_columns_come_from():
    foundation = _props(FOUNDATION.read_text())
    assert "emailVerification" in foundation and "emailCodeHash" in foundation and "activeOrgId" in foundation
    assert [l.split(":")[0].strip() for l in SB._AUTH_USERS_BASE_LINES] == foundation
    assert "integer" in SB._AUTH_USERS_BASE_BUILDERS, "the attempts counter's builder is imported too"


def test_a_merged_table_gets_the_new_columns_and_keeps_its_own():
    out = SB.merge_user_schema(MERGED_OLD)
    props = _props(out)
    assert props[:len(_props(FOUNDATION.read_text()))] == _props(FOUNDATION.read_text())
    assert props[-2:] == ["role", "departmentId"], "the app's columns stay, after the foundation's"
    assert out.count('pgTable("users"') == 1
    assert 'import { departments } from "./departments";' in out, "a referenced table's import stays"
    pg = next(l for l in out.splitlines() if "drizzle-orm/pg-core" in l)
    for b in ("pgTable", "uuid", "text", "boolean", "timestamp", "integer"):
        assert b in pg
    assert SB.merge_user_schema(out) == out, "merging again changes nothing"


def test_an_app_with_only_the_foundations_columns_gets_the_foundation():
    old_plain = MERGED_OLD.replace('  role: text("role").default("member").notNull(),\n', "").replace(
        '  departmentId: uuid("department_id").references(() => departments.id),\n', "")
    assert SB.merge_user_schema(old_plain) == FOUNDATION.read_text()
    assert SB.merge_user_schema(None) == FOUNDATION.read_text()


def test_the_engine_refresh_merges_the_users_table(tmp_path):
    from services.smith import sync_app
    app = tmp_path / "app"
    (app / "src" / "db" / "schema").mkdir(parents=True)
    (app / "package.json").write_text("{}")
    (app / "src" / "db" / "schema" / "user.ts").write_text(MERGED_OLD)
    changed = sync_app.refresh_engine(app, None, complete=False)
    text = (app / "src" / "db" / "schema" / "user.ts").read_text()
    assert sync_app.USER_SCHEMA in changed
    assert "role:" in text and "departmentId:" in text and "emailVerification:" in text
    assert sync_app.USER_SCHEMA not in sync_app.refresh_engine(app, None, complete=False), "a current table is left alone"


def test_the_build_merges_a_role_over_every_foundation_column(tmp_path):
    out = tmp_path / "schema"
    out.mkdir()
    generated: list[str] = []
    model = {"name": "User", "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                                        {"name": "email", "type": "string"}, {"name": "role", "type": "string"}]}
    reg = {"User": {"table": "users", "columns": []}}
    SB._emit_merged_users(out, [model], reg, {}, {}, generated)
    text = (out / "user.ts").read_text()
    props = _props(text)
    assert "role" in props and "emailVerification" in props and "emailCodeAttempts" in props, props
    assert props.count("email") == 1
    assert generated == ["src/db/schema/user.ts"]


MULTI_LINE = '''import { pgTable, uuid, text } from "drizzle-orm/pg-core";
import { departments } from "./departments";

export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  email: text("email").notNull().unique(),
  role: text("role").notNull().default("member"), // who they are
  departmentId: uuid("department_id")
    .references(() => departments.id, { onDelete: "set null" }),
  managerId: uuid("manager_id").references(
    () => departments.id,
    { onDelete: "cascade" },
  ),
  note: text("note"),
});
'''


def test_a_column_written_over_several_lines_is_kept_whole():
    """#37 review, 2026-11-13: a column was read as its first line, so the merged
    table kept `departmentId: uuid("department_id")` without its reference, and
    `managerId: uuid("manager_id").references(` did not parse at all."""
    cols = {n: src for n, _, src in SB.user_columns(MULTI_LINE)}
    assert list(cols) == ["id", "email", "role", "departmentId", "managerId", "note"]
    assert cols["departmentId"].endswith('{ onDelete: "set null" }),')
    assert cols["managerId"].count("\n") == 3 and cols["managerId"].endswith("),")
    merged = SB.merge_user_schema(MULTI_LINE)
    assert '.references(() => departments.id, { onDelete: "set null" }),' in merged
    assert '    { onDelete: "cascade" },\n  ),\n  note: text("note"),\n});' in merged
    assert 'import { departments } from "./departments";' in merged
    assert merged.count('pgTable("users"') == 1
    # Merged again, nothing moves.
    assert SB.merge_user_schema(merged) == merged

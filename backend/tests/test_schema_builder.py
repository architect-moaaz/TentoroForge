"""Tests for the deterministic Drizzle schema + types builder.

The builder replaces the mechanical part of the LLM schema agent: it emits
ONLY per-entity `src/db/schema/<slug>.ts` + `src/types/<slug>.ts` (plus their
barrels). Config files (package.json, drizzle.config.ts, src/db/index.ts, ...)
come from the project templates and must NOT be emitted here.
"""

from pathlib import Path

from services.schema_builder import build_schema_files

# NOTE: the sample entity is `Account` (not `User`) on purpose — `users` is an
# auth-reserved table owned by the template, so a plan `User` entity is skipped
# by the builder (see test_reserved_users_table_skipped).


def _basic_plan():
    return {
        "data_models": [
            {
                "name": "Account",
                "fields": [
                    {"name": "id", "type": "serial", "primaryKey": True},
                    {"name": "email", "type": "varchar", "nullable": False, "unique": True},
                    {"name": "name", "type": "varchar"},
                    {"name": "createdAt", "type": "timestamp"},
                ],
            },
            {
                "name": "Order",
                "fields": [
                    {"name": "id", "type": "serial", "primaryKey": True},
                    {"name": "title", "type": "varchar", "nullable": False},
                    {"name": "accountId", "type": "integer", "nullable": False},
                    {"name": "quantity", "type": "integer"},
                    {"name": "shipped", "type": "boolean"},
                    {"name": "status", "type": "varchar", "enum_values": ["open", "closed"]},
                ],
            },
        ],
        "relations": [
            {"from": "Order", "to": "Account", "type": "many-to-one", "foreignKey": "accountId"},
        ],
    }


# (a) varchar / integer / boolean / timestamp map to the right column builders
def test_column_builders(tmp_path):
    build_schema_files(_basic_plan(), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "orders.ts").read_text()
    assert 'pgTable("orders"' in src
    assert 'varchar("title"' in src
    assert 'integer("account_id"' in src
    assert 'integer("quantity"' in src
    assert 'boolean("shipped"' in src
    # imports come from drizzle-orm/pg-core
    assert 'from "drizzle-orm/pg-core"' in src
    assert "varchar" in src.split("\n")[0] or "varchar" in src[: src.index("export")]


# (b) PK id -> .primaryKey(); non-nullable -> .notNull()
def test_primary_key_and_not_null(tmp_path):
    build_schema_files(_basic_plan(), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "orders.ts").read_text()
    assert 'serial("id").primaryKey()' in src
    # title is nullable:false -> notNull
    assert 'varchar("title", { length: 255 }).notNull()' in src
    # accountId is nullable:false -> notNull
    assert ".notNull()" in src
    accounts = (tmp_path / "src" / "db" / "schema" / "accounts.ts").read_text()
    assert ".unique()" in accounts  # email unique


# (c) FK field present in relations -> .references(...) + a relations() block
def test_foreign_key_references_and_relations(tmp_path):
    build_schema_files(_basic_plan(), str(tmp_path))
    orders = (tmp_path / "src" / "db" / "schema" / "orders.ts").read_text()
    assert ".references(() => accounts.id)" in orders
    assert 'import { accounts } from "./accounts"' in orders
    assert "relations(orders" in orders
    assert "one(accounts" in orders
    # the referenced side gets a many() back-reference
    accounts = (tmp_path / "src" / "db" / "schema" / "accounts.ts").read_text()
    assert "relations(accounts" in accounts
    assert "many(orders)" in accounts


# (d) index.ts barrel exports every entity
def test_schema_barrel(tmp_path):
    build_schema_files(_basic_plan(), str(tmp_path))
    barrel = (tmp_path / "src" / "db" / "schema" / "index.ts").read_text()
    assert './accounts"' in barrel
    assert './orders"' in barrel


# (e) src/types/<slug>.ts has $inferSelect / $inferInsert
def test_types_infer(tmp_path):
    build_schema_files(_basic_plan(), str(tmp_path))
    t = (tmp_path / "src" / "types" / "orders.ts").read_text()
    assert 'import { orders } from "@/db/schema/orders"' in t
    assert "export type Order = typeof orders.$inferSelect;" in t
    assert "export type NewOrder = typeof orders.$inferInsert;" in t
    types_barrel = (tmp_path / "src" / "types" / "index.ts").read_text()
    assert './orders"' in types_barrel


# (f) legacy dict-keyed data_models is normalized to a list
def test_legacy_dict_data_models(tmp_path):
    plan = {
        "data_models": {
            "Account": {
                "fields": [
                    {"name": "id", "type": "serial", "primaryKey": True},
                    {"name": "email", "type": "varchar", "nullable": False},
                ]
            },
            "Order": {
                "fields": [
                    {"name": "id", "type": "serial", "primaryKey": True},
                    {"name": "accountId", "type": "integer", "nullable": False},
                ]
            },
        },
        "relations": [
            {"from": "Order", "to": "Account", "type": "many-to-one", "foreignKey": "accountId"},
        ],
    }
    out = build_schema_files(plan, str(tmp_path))
    assert out["errors"] == []
    assert (tmp_path / "src" / "db" / "schema" / "accounts.ts").exists()
    orders = (tmp_path / "src" / "db" / "schema" / "orders.ts").read_text()
    assert ".references(() => accounts.id)" in orders


# (g) return value lists generated paths and files exist under tmp_path
def test_return_and_files_written(tmp_path):
    out = build_schema_files(_basic_plan(), str(tmp_path))
    assert isinstance(out, dict)
    assert "generated" in out and "errors" in out
    assert out["errors"] == []
    assert "src/db/schema/orders.ts" in out["generated"]
    assert "src/db/schema/index.ts" in out["generated"]
    assert "src/types/orders.ts" in out["generated"]
    assert "src/types/index.ts" in out["generated"]
    for rel in out["generated"]:
        assert (tmp_path / rel).exists(), f"missing {rel}"
    # MUST NOT emit config files (those come from templates)
    assert not (tmp_path / "package.json").exists()
    assert not (tmp_path / "drizzle.config.ts").exists()
    assert not (tmp_path / "src" / "db" / "index.ts").exists()


# ── Task 1b: required domain fields emit .notNull() ──
# The planner marks required fields with `nullable: false` (observed in real
# plans, e.g. output/7uwywvau/plan.json) and the prompt example. Some callers /
# legacy plans may use `notNull: true` or `required: true` instead. All three
# must produce `.notNull()`; optional fields (no flag) must NOT; a PK is
# unaffected (already `.primaryKey()`); a declared lifecycle `*At` column with no
# required flag must NOT be forced notNull.
def _required_plan():
    return {
        "data_models": [
            {
                "name": "Drive",
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    # three flavours of "required"
                    {"name": "title", "type": "varchar", "nullable": False},
                    {"name": "code", "type": "varchar", "notNull": True},
                    {"name": "owner", "type": "varchar", "required": True},
                    # optional — no flag at all
                    {"name": "notes", "type": "text"},
                    # a declared lifecycle column, no required flag
                    {"name": "closedAt", "type": "timestamp"},
                ],
            },
        ],
    }


# required-by-nullable:false, notNull:true, and required:true all -> .notNull()
def test_required_fields_emit_not_null(tmp_path):
    build_schema_files(_required_plan(), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "drives.ts").read_text()
    assert 'varchar("title", { length: 255 }).notNull()' in src
    assert 'varchar("code", { length: 255 }).notNull()' in src
    assert 'varchar("owner", { length: 255 }).notNull()' in src


# an optional field (no required flag) must NOT be notNull
def test_optional_field_not_not_null(tmp_path):
    build_schema_files(_required_plan(), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "drives.ts").read_text()
    # find the `notes:` line and assert it lacks .notNull()
    notes_line = next(l for l in src.splitlines() if l.strip().startswith("notes:"))
    assert ".notNull()" not in notes_line


# a PK stays .primaryKey() and does not get a spurious .notNull() from this pass
def test_primary_key_unaffected_by_required(tmp_path):
    build_schema_files(_required_plan(), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "drives.ts").read_text()
    id_line = next(l for l in src.splitlines() if l.strip().startswith("id:"))
    assert ".primaryKey()" in id_line
    assert ".notNull()" not in id_line


# a declared lifecycle *At column with no required flag is NOT forced notNull
def test_lifecycle_at_not_forced_not_null(tmp_path):
    build_schema_files(_required_plan(), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "drives.ts").read_text()
    closed_line = next(l for l in src.splitlines() if l.strip().startswith("closedAt:"))
    assert ".notNull()" not in closed_line


# legacy dict-keyed data_models still honor the required flag -> .notNull()
def test_legacy_dict_required_honored(tmp_path):
    plan = {
        "data_models": {
            "Drive": {
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "title", "type": "varchar", "nullable": False},
                    {"name": "notes", "type": "text"},
                ]
            },
        },
    }
    build_schema_files(plan, str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "drives.ts").read_text()
    assert 'varchar("title", { length: 255 }).notNull()' in src
    notes_line = next(l for l in src.splitlines() if l.strip().startswith("notes:"))
    assert ".notNull()" not in notes_line


# (Task 2.1) An explicit planner `table` hint (an uncountable noun) flows through
# schema_builder VIA THE REGISTRY: the emitted pgTable const/name is the hint
# verbatim ("equipment", NOT the re-pluralized "equipments"), the schema file is
# named for the hint's slug, and a child entity's FK references the hinted table.
# Before this change schema_builder re-derived names with `_to_table` and ignored
# the hint → "equipments"; the registry now owns the name family.
def test_table_hint_flows_through_registry(tmp_path):
    plan = {
        "data_models": [
            {
                "name": "Equipment",
                "table": "equipment",  # explicit planner hint (uncountable)
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "name", "type": "varchar", "nullable": False},
                ],
            },
            {
                "name": "MaintenanceLog",
                "fields": [
                    {"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "equipmentId", "type": "uuid", "nullable": False},
                    {"name": "note", "type": "text"},
                ],
            },
        ],
        "relations": [
            {"from": "MaintenanceLog", "to": "Equipment",
             "type": "many-to-one", "foreignKey": "equipmentId"},
        ],
    }
    out = build_schema_files(plan, str(tmp_path))
    assert out["errors"] == []
    # the hint wins verbatim for the table const + pgTable name (NOT "equipments")
    eq = (tmp_path / "src" / "db" / "schema" / "equipment.ts").read_text()
    assert 'export const equipment = pgTable("equipment"' in eq
    assert "equipments" not in eq
    # the child entity's FK targets the hinted table name
    log = (tmp_path / "src" / "db" / "schema" / "maintenance-logs.ts").read_text()
    assert ".references(() => equipment.id)" in log
    assert 'import { equipment } from "./equipment"' in log
    # barrels + types reference the hinted slug, not "equipments"
    barrel = (tmp_path / "src" / "db" / "schema" / "index.ts").read_text()
    assert './equipment"' in barrel and "equipments" not in barrel
    assert (tmp_path / "src" / "types" / "equipment.ts").exists()


# (h) A plan `User` entity maps to the auth-reserved `users` table, which the
# template owns (with password/next-auth columns). The builder MUST skip it —
# otherwise it emits a second pgTable("users") that clobbers the auth-correct
# one, dropping `password` and breaking the admin seed at runtime.
def test_reserved_users_table_skipped(tmp_path):
    plan = {
        "data_models": [
            {"name": "User", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "email", "type": "varchar"},
                {"name": "role", "type": "varchar"},
            ]},
            {"name": "Ticket", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "title", "type": "varchar"},
                {"name": "assigneeId", "type": "uuid"},
            ]},
        ],
        "relations": [
            {"from": "Ticket", "to": "User", "type": "many-to-one", "foreignKey": "assigneeId"},
        ],
    }
    out = build_schema_files(plan, str(tmp_path))
    assert out["errors"] == []
    schema_dir = tmp_path / "src" / "db" / "schema"
    # the builder must NOT write a users table file (template owns it)
    assert not (schema_dir / "users.ts").exists()
    assert not (tmp_path / "src" / "types" / "users.ts").exists()
    # the non-reserved entity is still emitted
    assert (schema_dir / "tickets.ts").exists()
    # and the barrel must not export a builder-owned users module...
    barrel = (schema_dir / "index.ts").read_text()
    assert "./users" not in barrel
    # ...nor should Ticket try to import the (non-existent) builder users file
    tickets = (schema_dir / "tickets.ts").read_text()
    assert 'from "./users"' not in tickets


# ── Real FK .references() for EVERY FK column (explicit relation OR inferred) ──
# Root problem (app 6fvy3ll3): the plan named a relationship (appointment→staff)
# but NOT which column is the FK, so schema_builder emitted vetId/administeredById
# as plain uuid columns with NO .references() — the constraint never existed in
# Postgres. Now the builder pairs FK-shaped columns to relationships (name match,
# then 1-and-only-1 elimination — the SAME algorithm as
# registry_schema_reconcile.pair_fk_columns_to_relationships) and emits a real
# .references() + the target import for every FK column.
def _inferred_fk_plan():
    return {
        "data_models": [
            {"name": "Appointment", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "petId", "type": "uuid"},
                {"name": "vetId", "type": "uuid"},
            ]},
            {"name": "Pet", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
            ]},
            # explicit `table` hint so the uncountable noun stays "staff"
            {"name": "Staff", "table": "staff", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
            ]},
        ],
        # NO foreignKey on either relation — the builder must infer the column.
        "relations": [
            {"from": "Appointment", "to": "Pet", "type": "many-to-one"},
            {"from": "Appointment", "to": "Staff", "type": "many-to-one"},
        ],
    }


# petId pairs by name → pets.id; vetId pairs by elimination → staff.id; both get
# a .references() AND the target import, even though the plan named no foreignKey.
def test_inferred_fk_references_emitted(tmp_path):
    out = build_schema_files(_inferred_fk_plan(), str(tmp_path))
    assert out["errors"] == []
    src = (tmp_path / "src" / "db" / "schema" / "appointments.ts").read_text()
    assert 'petId: uuid("pet_id").references(() => pets.id)' in src
    assert 'vetId: uuid("vet_id").references(() => staff.id)' in src
    assert 'import { pets } from "./pets";' in src
    assert 'import { staff } from "./staff";' in src


# An explicit `foreignKey` on the relation still works and takes priority (the
# authoritative source is never overridden by the inference fallback).
def test_explicit_foreign_key_still_wins(tmp_path):
    plan = _inferred_fk_plan()
    # name petId's relation explicitly; leave vetId to inference
    plan["relations"] = [
        {"from": "Appointment", "to": "Pet", "type": "many-to-one", "foreignKey": "petId"},
        {"from": "Appointment", "to": "Staff", "type": "many-to-one"},
    ]
    out = build_schema_files(plan, str(tmp_path))
    assert out["errors"] == []
    src = (tmp_path / "src" / "db" / "schema" / "appointments.ts").read_text()
    assert 'petId: uuid("pet_id").references(() => pets.id)' in src
    assert 'vetId: uuid("vet_id").references(() => staff.id)' in src


# A uuid *Id column with NO relationship to pair to stays a plain uuid — the
# builder never invents a target (no .references(), no spurious import).
def test_standalone_uuid_id_column_stays_plain(tmp_path):
    plan = {
        "data_models": [
            {"name": "Widget", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                # externalRefId has no relationship — genuinely standalone
                {"name": "externalRefId", "type": "uuid"},
                {"name": "name", "type": "varchar"},
            ]},
        ],
    }
    out = build_schema_files(plan, str(tmp_path))
    assert out["errors"] == []
    src = (tmp_path / "src" / "db" / "schema" / "widgets.ts").read_text()
    ext_line = next(l for l in src.splitlines() if l.strip().startswith("externalRefId:"))
    assert ".references(" not in ext_line
    # no invented target import (no sibling schema-module import at all)
    assert 'from "./' not in src


# ── RBAC (Theme C / C-3): merge the planner's domain columns (role) into the
# auth users table instead of blanket-skipping the User entity, and emit real
# .references(() => users.id) for actor FK columns targeting User. ──
def _rbac_schema_plan():
    return {
        "access_control": {"roles": ["Recruiter", "Assessor"]},
        "data_models": [
            {"name": "Assessment", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "score", "type": "integer"},
                {"name": "assignedAssessorId", "type": "uuid"},
            ]},
            {"name": "User", "table": "users", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "name", "type": "varchar"},
                {"name": "email", "type": "varchar", "nullable": False},
                {"name": "role", "type": "varchar", "enum_values": ["Recruiter", "Assessor"]},
            ]},
        ],
        "relations": [
            {"from": "Assessment", "to": "User", "type": "many-to-one",
             "foreignKey": "assignedAssessorId"},
        ],
    }


def test_users_schema_carries_role_column(tmp_path):
    out = build_schema_files(_rbac_schema_plan(), str(tmp_path))
    assert out["errors"] == []
    user_ts = (tmp_path / "src" / "db" / "schema" / "user.ts").read_text()
    # a SINGLE users table (merged, not a second pgTable), auth base preserved,
    # domain role column added.
    assert user_ts.count('pgTable("users"') == 1
    assert 'password: text("password").notNull()' in user_ts
    assert 'email: text("email").notNull().unique()' in user_ts
    assert 'role: varchar("role"' in user_ts
    # never a plural users.ts (that would be a second table clobbering auth)
    assert not (tmp_path / "src" / "db" / "schema" / "users.ts").exists()


def test_assessor_fk_references_users(tmp_path):
    out = build_schema_files(_rbac_schema_plan(), str(tmp_path))
    assert out["errors"] == []
    src = (tmp_path / "src" / "db" / "schema" / "assessments.ts").read_text()
    assert 'assignedAssessorId: uuid("assigned_assessor_id").references(() => users.id)' in src
    assert 'import { users } from "./user";' in src


# A FK whose target is the reserved `users` table imports the template const
# (`users` from ./user) and references users.id — the builder skips writing a
# users.ts but the child FK must still constrain to the auth-owned table.
def test_reserved_users_fk_target_imports_correctly(tmp_path):
    plan = {
        "data_models": [
            {"name": "User", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "email", "type": "varchar"},
            ]},
            {"name": "Ticket", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "assigneeId", "type": "uuid"},
                {"name": "title", "type": "varchar"},
            ]},
        ],
        "relations": [
            {"from": "Ticket", "to": "User", "type": "many-to-one", "foreignKey": "assigneeId"},
        ],
    }
    out = build_schema_files(plan, str(tmp_path))
    assert out["errors"] == []
    tickets = (tmp_path / "src" / "db" / "schema" / "tickets.ts").read_text()
    assert 'assigneeId: uuid("assignee_id").references(() => users.id)' in tickets
    # imports the template's const from ./user (const is `users`, file is user.ts)
    assert 'import { users } from "./user";' in tickets
    # the builder still does NOT write its own users.ts (auth owns it)
    assert not (tmp_path / "src" / "db" / "schema" / "users.ts").exists()

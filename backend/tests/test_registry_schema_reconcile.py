"""Tests for registry_schema_reconcile — correcting the canonical resource
registry (``contracts/resource-registry.json``) against the REAL emitted
Drizzle schema, so its per-column ``notNull``/``enum``/``type`` stop drifting
from the schema the app actually ships (the resource-registry vs registry.json
divergence described in the pipeline-reliability atlas, finding A2 / P1 #5)."""

from __future__ import annotations

import json
import os

from services.registry_schema_reconcile import reconcile_registry_to_schema


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _write_registry(output_dir: str, registry: dict) -> str:
    contracts = os.path.join(output_dir, "contracts")
    os.makedirs(contracts, exist_ok=True)
    path = os.path.join(contracts, "resource-registry.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(registry, indent=2, sort_keys=True))
    return path


def _write_schema(output_dir: str, filename: str, content: str) -> str:
    schema_dir = os.path.join(output_dir, "src", "db", "schema")
    os.makedirs(schema_dir, exist_ok=True)
    path = os.path.join(schema_dir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


# A real Drizzle schema in the EXACT shape extract_entities_from_schema parses:
# per-column `name: builder("col"...)` with a chained `.notNull()`, and enum
# values carried on `.$type<"A" | "B">()` (the only enum form the extractor
# recognises).  status is NOT NULL + enum; title is NOT NULL; note is nullable;
# priority is a schema-only column absent from the stale registry.
_DRIVES_SCHEMA = '''\
import { pgTable, uuid, varchar, text } from "drizzle-orm/pg-core";

export const drives = pgTable("drives", {
  id: uuid("id").primaryKey().defaultRandom(),
  title: varchar("title", { length: 255 }).notNull(),
  status: varchar("status", { length: 50 })
    .$type<"Active" | "Closed">()
    .notNull()
    .default("Active"),
  priority: varchar("priority", { length: 50 }).$type<"Low" | "High">().notNull(),
  note: text("note"),
});
'''


def _stale_registry() -> dict:
    """Canonical registry as built from the RAW plan: status wrongly nullable
    with no enum, title wrongly nullable, and no `priority` column at all."""
    return {
        "version": 1,
        "entities": {
            "Drive": {
                "id": "drive",
                "name": "Drive",
                "table": "drives",
                "slug": "drives",
                "camel": "drive",
                "schemaFile": "src/db/schema/drives.ts",
                "columns": [
                    {"name": "id", "type": "uuid", "notNull": False, "fk": None, "enum": None},
                    {"name": "title", "type": "varchar", "notNull": False, "fk": None, "enum": None},
                    {"name": "status", "type": "varchar", "notNull": False, "fk": None, "enum": None},
                    {"name": "note", "type": "text", "notNull": False, "fk": None, "enum": None},
                ],
                "fks": [],
            }
        },
        "relationships": [],
        "interactions": [],
        "roles": [],
    }


def _load(output_dir: str) -> dict:
    with open(
        os.path.join(output_dir, "contracts", "resource-registry.json"), encoding="utf-8"
    ) as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_notnull_and_enum_corrected_from_schema(tmp_path):
    out = str(tmp_path)
    _write_registry(out, _stale_registry())
    _write_schema(out, "drives.ts", _DRIVES_SCHEMA)

    counts = reconcile_registry_to_schema(out)

    reg = _load(out)
    cols = {c["name"]: c for c in reg["entities"]["Drive"]["columns"]}

    # status: schema is NOT NULL + carries the enum → both corrected.
    assert cols["status"]["notNull"] is True
    assert cols["status"]["enum"] == ["Active", "Closed"]
    # title: schema is NOT NULL → corrected from the stale False.
    assert cols["title"]["notNull"] is True
    # note: schema is nullable → stays nullable.
    assert cols["note"]["notNull"] is False

    assert counts["entities_reconciled"] == 1
    assert counts["columns_updated"] >= 2


def test_schema_only_column_is_added(tmp_path):
    out = str(tmp_path)
    _write_registry(out, _stale_registry())
    _write_schema(out, "drives.ts", _DRIVES_SCHEMA)

    reconcile_registry_to_schema(out)

    reg = _load(out)
    cols = {c["name"]: c for c in reg["entities"]["Drive"]["columns"]}
    # `priority` existed only in the schema — reconcile adds it.
    assert "priority" in cols
    assert cols["priority"]["notNull"] is True
    assert cols["priority"]["enum"] == ["Low", "High"]


def test_canonical_only_metadata_preserved(tmp_path):
    out = str(tmp_path)
    _write_registry(out, _stale_registry())
    _write_schema(out, "drives.ts", _DRIVES_SCHEMA)

    reconcile_registry_to_schema(out)

    reg = _load(out)
    ent = reg["entities"]["Drive"]
    # naming/family metadata is registry-owned and must survive.
    assert ent["id"] == "drive"
    assert ent["name"] == "Drive"
    assert ent["table"] == "drives"
    assert ent["slug"] == "drives"
    assert ent["camel"] == "drive"
    assert ent["schemaFile"] == "src/db/schema/drives.ts"
    assert "fks" in ent


def test_idempotent_second_run_byte_identical(tmp_path):
    out = str(tmp_path)
    _write_registry(out, _stale_registry())
    _write_schema(out, "drives.ts", _DRIVES_SCHEMA)

    reconcile_registry_to_schema(out)
    path = os.path.join(out, "contracts", "resource-registry.json")
    with open(path, "rb") as fh:
        first = fh.read()

    reconcile_registry_to_schema(out)
    with open(path, "rb") as fh:
        second = fh.read()

    assert first == second


def test_missing_registry_is_noop(tmp_path):
    out = str(tmp_path)
    # No contracts/resource-registry.json, no schema either.
    counts = reconcile_registry_to_schema(out)
    assert counts == {"entities_reconciled": 0, "columns_updated": 0}


def test_unparseable_registry_is_noop(tmp_path):
    out = str(tmp_path)
    contracts = os.path.join(out, "contracts")
    os.makedirs(contracts, exist_ok=True)
    with open(os.path.join(contracts, "resource-registry.json"), "w", encoding="utf-8") as fh:
        fh.write("{ not valid json ")

    counts = reconcile_registry_to_schema(out)
    assert counts == {"entities_reconciled": 0, "columns_updated": 0}


# ---------------------------------------------------------------------------
# FK-target capture from schema .references()  (vetId → staff, name ≠ target)
# ---------------------------------------------------------------------------

_STAFF_SCHEMA = '''\
import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";

export const staff = pgTable("staff", {
  id: uuid("id").primaryKey().defaultRandom(),
  fullName: varchar("full_name", { length: 255 }).notNull(),
});
'''

# appointments.vetId references staff.id — the FK COLUMN NAME (vetId) shares no
# letters with the TARGET entity (Staff), which is exactly what breaks name-guessing.
_APPTS_SCHEMA = '''\
import { pgTable, uuid, text } from "drizzle-orm/pg-core";
import { staff } from "./staff";

export const appointments = pgTable("appointments", {
  id: uuid("id").primaryKey().defaultRandom(),
  vetId: uuid("vet_id")
    .references(() => staff.id)
    .notNull(),
  reason: text("reason"),
});
'''


def _fk_registry() -> dict:
    return {
        "version": 1,
        "entities": {
            "Appointment": {
                "id": "appointment", "name": "Appointment", "table": "appointments",
                "slug": "appointments", "camel": "appointment",
                "schemaFile": "src/db/schema/appointments.ts",
                "columns": [
                    {"name": "id", "type": "uuid", "notNull": False, "fk": None, "enum": None},
                    {"name": "vetId", "type": "uuid", "notNull": False, "fk": None, "enum": None},
                    {"name": "reason", "type": "text", "notNull": False, "fk": None, "enum": None},
                ],
                "fks": [],
            },
            "Staff": {
                "id": "staff", "name": "Staff", "table": "staff", "slug": "staff",
                "camel": "staff", "schemaFile": "src/db/schema/staff.ts",
                "columns": [
                    {"name": "id", "type": "uuid", "notNull": False, "fk": None, "enum": None},
                    {"name": "fullName", "type": "varchar", "notNull": False, "fk": None, "enum": None},
                ],
                "fks": [],
            },
        },
        "relationships": [
            {"from": "appointment", "to": "staff", "type": "many-to-one", "fkColumn": None},
        ],
        "interactions": [],
        "roles": [],
    }


def test_fk_target_captured_from_references(tmp_path):
    out = str(tmp_path)
    _write_registry(out, _fk_registry())
    _write_schema(out, "staff.ts", _STAFF_SCHEMA)
    _write_schema(out, "appointments.ts", _APPTS_SCHEMA)

    reconcile_registry_to_schema(out)

    reg = _load(out)
    appt = reg["entities"]["Appointment"]
    # entity fks list gains the vetId → staff link
    assert {"column": "vetId", "targetEntityId": "staff"} in appt["fks"]
    # the vetId column's fk is set to the target entity id
    vet = next(c for c in appt["columns"] if c["name"] == "vetId")
    assert vet["fk"] == "staff"
    # the appointment→staff relationship gains its fkColumn
    rel = next(r for r in reg["relationships"] if r["from"] == "appointment" and r["to"] == "staff")
    assert rel["fkColumn"] == "vetId"


def test_extract_fk_references_both_forms(tmp_path):
    from services.registry_schema_reconcile import extract_fk_references

    out = str(tmp_path)
    _write_schema(out, "staff.ts", _STAFF_SCHEMA)
    _write_schema(out, "appointments.ts", _APPTS_SCHEMA)
    # composite foreignKey() form
    _write_schema(out, "customers.ts",
                  'import { pgTable, uuid } from "drizzle-orm/pg-core";\n'
                  'export const customers = pgTable("customers", {\n'
                  '  id: uuid("id").primaryKey().defaultRandom(),\n});\n')
    _write_schema(out, "orders.ts",
                  'import { pgTable, uuid, foreignKey } from "drizzle-orm/pg-core";\n'
                  'import { customers } from "./customers";\n'
                  'export const orders = pgTable("orders", {\n'
                  '  id: uuid("id").primaryKey().defaultRandom(),\n'
                  '  buyerId: uuid("buyer_id"),\n'
                  '}, (table) => [\n'
                  '  foreignKey({ columns: [table.buyerId], foreignColumns: [customers.id] }),\n'
                  ']);\n')

    refs = extract_fk_references(out)
    assert refs["appointments"]["vetId"] == "staff"
    assert refs["orders"]["buyerId"] == "customers"


def test_fk_capture_idempotent(tmp_path):
    out = str(tmp_path)
    _write_registry(out, _fk_registry())
    _write_schema(out, "staff.ts", _STAFF_SCHEMA)
    _write_schema(out, "appointments.ts", _APPTS_SCHEMA)

    reconcile_registry_to_schema(out)
    path = os.path.join(out, "contracts", "resource-registry.json")
    with open(path, "rb") as fh:
        first = fh.read()
    reconcile_registry_to_schema(out)
    with open(path, "rb") as fh:
        second = fh.read()
    assert first == second


# ---------------------------------------------------------------------------
# pair_fk_columns_to_relationships — relationship-based FK truth (name + elim)
# ---------------------------------------------------------------------------

def _ent(eid, name, slug, cols):
    """cols: list of (name, type[, fk]) tuples."""
    columns = []
    for c in cols:
        col = {"name": c[0], "type": c[1], "notNull": False,
               "fk": (c[2] if len(c) > 2 else None), "enum": None}
        columns.append(col)
    return {"id": eid, "name": name, "slug": slug, "camel": eid, "table": slug,
            "columns": columns, "fks": []}


def _rel(frm, to):
    return {"from": frm, "to": to, "type": "many-to-one", "fkColumn": None}


def test_pair_exact_matches_plus_elimination():
    from services.registry_schema_reconcile import pair_fk_columns_to_relationships

    appt = _ent("appointment", "Appointment", "appointments",
                [("id", "uuid"), ("petId", "uuid"), ("ownerId", "uuid"),
                 ("vetId", "uuid"), ("notes", "text")])
    registry = {
        "entities": {
            "Appointment": appt,
            "Pet": _ent("pet", "Pet", "pets", [("id", "uuid")]),
            "Owner": _ent("owner", "Owner", "owners", [("id", "uuid")]),
            "Staff": _ent("staff", "Staff", "staff", [("id", "uuid")]),
        },
        "relationships": [_rel("appointment", "pet"), _rel("appointment", "owner"),
                          _rel("appointment", "staff")],
    }
    # petId/ownerId by name; vetId → staff by elimination (last col, last target).
    assert pair_fk_columns_to_relationships(appt, registry) == {
        "petId": "pet", "ownerId": "owner", "vetId": "staff"}


def test_pair_two_unmatched_left_unresolved():
    from services.registry_schema_reconcile import pair_fk_columns_to_relationships

    # neither aId nor bId name-matches; two targets remain → ambiguous, no guess.
    ent = _ent("thing", "Thing", "things",
               [("id", "uuid"), ("aId", "uuid"), ("bId", "uuid")])
    registry = {
        "entities": {
            "Thing": ent,
            "Pet": _ent("pet", "Pet", "pets", [("id", "uuid")]),
            "Staff": _ent("staff", "Staff", "staff", [("id", "uuid")]),
        },
        "relationships": [_rel("thing", "pet"), _rel("thing", "staff")],
    }
    assert pair_fk_columns_to_relationships(ent, registry) == {}


def test_pair_name_match_wins_over_elimination():
    from services.registry_schema_reconcile import pair_fk_columns_to_relationships

    # petId must land on pet (name), NOT be consumed by elimination for staff.
    ent = _ent("appointment", "Appointment", "appointments",
               [("id", "uuid"), ("petId", "uuid"), ("vetId", "uuid")])
    registry = {
        "entities": {
            "Appointment": ent,
            "Pet": _ent("pet", "Pet", "pets", [("id", "uuid")]),
            "Staff": _ent("staff", "Staff", "staff", [("id", "uuid")]),
        },
        "relationships": [_rel("appointment", "staff"), _rel("appointment", "pet")],
    }
    assert pair_fk_columns_to_relationships(ent, registry) == {
        "petId": "pet", "vetId": "staff"}


def test_pair_skips_already_resolved_columns_and_targets():
    from services.registry_schema_reconcile import pair_fk_columns_to_relationships

    # petId already has fk=pet (from schema .references()); only vetId→staff left.
    ent = _ent("appointment", "Appointment", "appointments",
               [("id", "uuid"), ("petId", "uuid", "pet"), ("vetId", "uuid")])
    registry = {
        "entities": {
            "Appointment": ent,
            "Pet": _ent("pet", "Pet", "pets", [("id", "uuid")]),
            "Staff": _ent("staff", "Staff", "staff", [("id", "uuid")]),
        },
        "relationships": [_rel("appointment", "pet"), _rel("appointment", "staff")],
    }
    # pet target claimed by the resolved petId → vetId elimination lands on staff.
    assert pair_fk_columns_to_relationships(ent, registry) == {"vetId": "staff"}


def test_pair_non_uuid_and_bare_id_ignored():
    from services.registry_schema_reconcile import pair_fk_columns_to_relationships

    ent = _ent("appointment", "Appointment", "appointments",
               [("id", "uuid"), ("vetId", "varchar")])  # vetId not uuid
    registry = {
        "entities": {"Appointment": ent,
                     "Staff": _ent("staff", "Staff", "staff", [("id", "uuid")])},
        "relationships": [_rel("appointment", "staff")],
    }
    assert pair_fk_columns_to_relationships(ent, registry) == {}


def test_pair_never_raises_on_garbage():
    from services.registry_schema_reconcile import pair_fk_columns_to_relationships

    assert pair_fk_columns_to_relationships({}, {}) == {}
    assert pair_fk_columns_to_relationships(None, None) == {}
    assert pair_fk_columns_to_relationships({"id": "x"}, {"entities": None}) == {}

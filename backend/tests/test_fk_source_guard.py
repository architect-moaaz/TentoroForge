"""Tests for fk_source_guard — pointing every FK dropdown at the entity the
schema ACTUALLY `.references()` (the vet-app 6fvy3ll3 bug: vetId/administeredById
both reference Staff, yet the dropdowns were sourced from pets/vets or left as
free-text Inputs feeding a uuid column)."""

from __future__ import annotations

import json
import os

from services.fk_source_guard import reconcile_fk_sources


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _write_registry(output_dir: str, registry: dict) -> None:
    contracts = os.path.join(output_dir, "contracts")
    os.makedirs(contracts, exist_ok=True)
    with open(os.path.join(contracts, "resource-registry.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(registry, indent=2, sort_keys=True))


def _write_schema(output_dir: str, filename: str, content: str) -> None:
    schema_dir = os.path.join(output_dir, "src", "db", "schema")
    os.makedirs(schema_dir, exist_ok=True)
    with open(os.path.join(schema_dir, filename), "w", encoding="utf-8") as fh:
        fh.write(content)


def _write_form(output_dir: str, relpath: str, schema: dict) -> str:
    path = os.path.join(output_dir, "src", "schemas", relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(schema, indent=2))
    return path


def _entity(eid, name, table, slug, cols):
    return {
        "id": eid, "name": name, "table": table, "slug": slug, "camel": table,
        "columns": [{"name": c, "type": "uuid", "notNull": False, "fk": None, "enum": None}
                    for c in cols],
        "fks": [],
    }


def _registry() -> dict:
    return {
        "version": 1,
        "entities": {
            "Staff": _entity("staff", "Staff", "staff", "staff", ["id", "fullName"]),
            "Pet": _entity("pet", "Pet", "pets", "pets", ["id", "name"]),
            "Appointment": _entity("appointment", "Appointment", "appointments",
                                   "appointments", ["id", "vetId", "petId", "notes"]),
            "Vaccination": _entity("vaccination", "Vaccination", "vaccinations",
                                   "vaccinations", ["id", "administeredById", "petId"]),
        },
        "relationships": [],
        "interactions": [],
        "roles": [],
    }


# vetId + administeredById BOTH reference staff (name ≠ target); petId → pets.
_STAFF = ('import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";\n'
          'export const staff = pgTable("staff", {\n'
          '  id: uuid("id").primaryKey().defaultRandom(),\n'
          '  fullName: varchar("full_name", { length: 255 }).notNull(),\n});\n')

_PETS = ('import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";\n'
         'export const pets = pgTable("pets", {\n'
         '  id: uuid("id").primaryKey().defaultRandom(),\n'
         '  name: varchar("name", { length: 255 }),\n});\n')

_APPTS = ('import { pgTable, uuid, text } from "drizzle-orm/pg-core";\n'
          'import { staff } from "./staff";\n'
          'import { pets } from "./pets";\n'
          'export const appointments = pgTable("appointments", {\n'
          '  id: uuid("id").primaryKey().defaultRandom(),\n'
          '  vetId: uuid("vet_id").references(() => staff.id),\n'
          '  petId: uuid("pet_id").references(() => pets.id),\n'
          '  notes: text("notes"),\n});\n')

_VACC = ('import { pgTable, uuid } from "drizzle-orm/pg-core";\n'
         'import { staff } from "./staff";\n'
         'import { pets } from "./pets";\n'
         'export const vaccinations = pgTable("vaccinations", {\n'
         '  id: uuid("id").primaryKey().defaultRandom(),\n'
         '  administeredById: uuid("administered_by_id").references(() => staff.id),\n'
         '  petId: uuid("pet_id").references(() => pets.id),\n});\n')


def _setup(tmp_path):
    out = str(tmp_path)
    _write_registry(out, _registry())
    _write_schema(out, "staff.ts", _STAFF)
    _write_schema(out, "pets.ts", _PETS)
    _write_schema(out, "appointments.ts", _APPTS)
    _write_schema(out, "vaccinations.ts", _VACC)
    return out


def _field(ntype, name, **props):
    return {"type": ntype, "props": {"name": name, **props}}


def _form(workflow, *fields):
    return {
        "route": "/x",
        "dataSources": [],
        "root": {
            "type": "Form",
            "props": {"workflow": workflow},
            "children": [{"type": "Stack", "children": list(fields)}],
        },
    }


def _load(path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _find(schema, name):
    stack = [schema.get("root") or schema]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if (cur.get("props") or {}).get("name") == name:
                return cur
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_wrong_select_source_repointed_to_real_target(tmp_path):
    out = _setup(tmp_path)
    fp = _write_form(out, "appointments/new.json", _form(
        "CreateAppointment",
        _field("Select", "vetId", optionsFrom={"source": "pets", "value": "id", "label": "name"}),
    ))

    res = reconcile_fk_sources(out)
    assert res["fixed"] >= 1

    node = _find(_load(fp), "vetId")
    assert node["props"]["optionsFrom"]["source"] == "staff"
    # a matching dataSource was upserted so the source resolves
    ds = {d["name"]: d for d in _load(fp)["dataSources"]}
    assert ds["staff"]["entity"] == "Staff"


def test_uuid_fk_input_promoted_to_select(tmp_path):
    out = _setup(tmp_path)
    fp = _write_form(out, "vaccinations/new.json", _form(
        "CreateVaccination",
        _field("Input", "administeredById"),
    ))

    res = reconcile_fk_sources(out)
    assert res["promoted"] >= 1

    node = _find(_load(fp), "administeredById")
    assert node["type"] == "Select"
    assert node["props"]["optionsFrom"]["source"] == "staff"


def test_correct_source_left_unchanged(tmp_path):
    out = _setup(tmp_path)
    fp = _write_form(out, "appointments/new.json", _form(
        "CreateAppointment",
        _field("Select", "vetId", optionsFrom={"source": "staff", "value": "id", "label": "fullName"}),
    ))
    before = _load(fp)

    res = reconcile_fk_sources(out)

    assert res["fixed"] == 0 and res["promoted"] == 0
    assert _load(fp) == before  # byte-for-byte idempotent


def test_non_fk_field_untouched(tmp_path):
    out = _setup(tmp_path)
    fp = _write_form(out, "appointments/new.json", _form(
        "CreateAppointment",
        _field("Input", "notes"),
    ))
    before = _load(fp)

    reconcile_fk_sources(out)

    assert _load(fp) == before


def test_petid_points_at_pets_not_staff(tmp_path):
    """A correctly-named FK still lands on the schema's real target (regression)."""
    out = _setup(tmp_path)
    fp = _write_form(out, "appointments/new.json", _form(
        "CreateAppointment",
        _field("Select", "petId", optionsFrom={"source": "owners", "value": "id", "label": "name"}),
    ))

    reconcile_fk_sources(out)

    node = _find(_load(fp), "petId")
    assert node["props"]["optionsFrom"]["source"] == "pets"


def test_missing_schema_is_noop(tmp_path):
    out = str(tmp_path)
    _write_registry(out, _registry())
    # no schema files at all → nothing to reconcile
    res = reconcile_fk_sources(out)
    assert res == {"fixed": 0, "promoted": 0, "files": 0}


# ---------------------------------------------------------------------------
# FALLBACK: no `.references()` in the schema, but registry relationships exist.
# The FK column → target must resolve from the relationship pairing instead.
# ---------------------------------------------------------------------------

# Same tables as above but with the `.references(...)` stripped — the plan named
# the relationship yet never said which column is the FK, so schema_builder
# emitted plain uuid columns.
_APPTS_NOREF = ('import { pgTable, uuid, text } from "drizzle-orm/pg-core";\n'
                'export const appointments = pgTable("appointments", {\n'
                '  id: uuid("id").primaryKey().defaultRandom(),\n'
                '  vetId: uuid("vet_id"),\n'
                '  petId: uuid("pet_id"),\n'
                '  notes: text("notes"),\n});\n')

_VACC_NOREF = ('import { pgTable, uuid } from "drizzle-orm/pg-core";\n'
               'export const vaccinations = pgTable("vaccinations", {\n'
               '  id: uuid("id").primaryKey().defaultRandom(),\n'
               '  administeredById: uuid("administered_by_id"),\n'
               '  petId: uuid("pet_id"),\n});\n')


def _registry_with_relationships() -> dict:
    reg = _registry()
    reg["relationships"] = [
        {"from": "appointment", "to": "pet", "type": "many-to-one", "fkColumn": None},
        {"from": "appointment", "to": "staff", "type": "many-to-one", "fkColumn": None},
        {"from": "vaccination", "to": "pet", "type": "many-to-one", "fkColumn": None},
        {"from": "vaccination", "to": "staff", "type": "many-to-one", "fkColumn": None},
    ]
    return reg


def _setup_noref(tmp_path):
    out = str(tmp_path)
    _write_registry(out, _registry_with_relationships())
    _write_schema(out, "staff.ts", _STAFF)
    _write_schema(out, "pets.ts", _PETS)
    _write_schema(out, "appointments.ts", _APPTS_NOREF)
    _write_schema(out, "vaccinations.ts", _VACC_NOREF)
    return out


def test_fallback_vetid_select_source_from_relationship(tmp_path):
    """No `.references()`: vetId (name ≠ target) pairs to staff by elimination
    (petId → pet by name), and its Select source is repointed."""
    out = _setup_noref(tmp_path)
    fp = _write_form(out, "appointments/new.json", _form(
        "CreateAppointment",
        _field("Select", "vetId", optionsFrom={"source": "pets", "value": "id", "label": "name"}),
    ))

    res = reconcile_fk_sources(out)
    assert res["fixed"] >= 1

    node = _find(_load(fp), "vetId")
    assert node["props"]["optionsFrom"]["source"] == "staff"


def test_fallback_uuid_input_promoted_via_relationship(tmp_path):
    """administeredById is a free-text Input feeding a uuid → promote to a Select
    bound to staff (paired by elimination against petId → pet)."""
    out = _setup_noref(tmp_path)
    fp = _write_form(out, "vaccinations/new.json", _form(
        "CreateVaccination",
        _field("Input", "administeredById"),
    ))

    res = reconcile_fk_sources(out)
    assert res["promoted"] >= 1

    node = _find(_load(fp), "administeredById")
    assert node["type"] == "Select"
    assert node["props"]["optionsFrom"]["source"] == "staff"


def test_fallback_is_idempotent(tmp_path):
    out = _setup_noref(tmp_path)
    fp = _write_form(out, "appointments/new.json", _form(
        "CreateAppointment",
        _field("Select", "vetId", optionsFrom={"source": "pets", "value": "id", "label": "name"}),
    ))

    reconcile_fk_sources(out)
    after_first = _load(fp)
    res = reconcile_fk_sources(out)
    assert res["fixed"] == 0 and res["promoted"] == 0
    assert _load(fp) == after_first

"""remove_field / edit_field — the destructive & renaming siblings of add_field.

Surgical registry + Drizzle edits: every other column stays byte-identical, and
the engine-managed columns (pk, timestamps) are refused. The reference side (a
workflow/form that still names a dropped/renamed column) is the ripple checks'
job — these cover the source surgery.
"""
import json
from pathlib import Path

import pytest

from services.edit_field_seam import (
    build_remove_field_bundle, build_edit_field_bundle, EditFieldError,
)

_DRIZZLE = '''import { pgTable, uuid, varchar, integer } from "drizzle-orm/pg-core";

export const records = pgTable("records", {
  id: uuid("id").primaryKey().defaultRandom(),
  fullName: varchar("full_name", { length: 255 }).notNull(),
  gender: varchar("gender", { length: 50 }),
  age: integer("age"),
});
'''


@pytest.fixture()
def app(tmp_path):
    (tmp_path / "contracts").mkdir()
    (tmp_path / "src" / "db" / "schema").mkdir(parents=True)
    (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps({"entities": [
        {"name": "Record", "slug": "records", "table": "records", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "fullName", "type": "varchar", "length": 255},
            {"name": "gender", "type": "varchar", "length": 50},
            {"name": "age", "type": "integer"}]}]}))
    (tmp_path / "src" / "db" / "schema" / "records.ts").write_text(_DRIZZLE)
    return tmp_path


def _apply(app, ops):
    for op in ops:
        (app / op.path).write_text(op.content)


def _fields(app):
    reg = json.loads((app / "contracts" / "resource-registry.json").read_text())
    return [f["name"] for f in reg["entities"][0]["fields"]]


def _schema(app):
    return (app / "src" / "db" / "schema" / "records.ts").read_text()


def test_remove_field_drops_registry_and_column(app):
    _apply(app, build_remove_field_bundle(str(app), entity="Record", field_name="gender"))
    assert "gender" not in _fields(app)
    assert "gender:" not in _schema(app)
    # other columns untouched
    assert 'fullName: varchar("full_name", { length: 255 }).notNull(),' in _schema(app)


def test_remove_field_refuses_the_primary_key(app):
    with pytest.raises(EditFieldError, match="managed"):
        build_remove_field_bundle(str(app), entity="Record", field_name="id")


def test_remove_field_unknown_is_refused(app):
    with pytest.raises(EditFieldError, match="not found"):
        build_remove_field_bundle(str(app), entity="Record", field_name="nope")


def test_edit_field_rename_updates_var_column_and_registry(app):
    _apply(app, build_edit_field_bundle(str(app), entity="Record",
                                        field_name="fullName", new_name="displayName"))
    assert "displayName" in _fields(app) and "fullName" not in _fields(app)
    assert 'displayName: varchar("display_name", { length: 255 }).notNull(),' in _schema(app)


def test_edit_field_retype_swaps_the_builder(app):
    _apply(app, build_edit_field_bundle(str(app), entity="Record",
                                        field_name="age", new_type="varchar"))
    reg = json.loads((app / "contracts" / "resource-registry.json").read_text())
    age = next(f for f in reg["entities"][0]["fields"] if f["name"] == "age")
    assert age["type"] == "varchar"
    assert 'age: varchar("age")' in _schema(app)


def test_edit_field_rename_collision_is_refused(app):
    with pytest.raises(EditFieldError, match="already has a field"):
        build_edit_field_bundle(str(app), entity="Record", field_name="age", new_name="gender")


def test_edit_field_requires_a_change(app):
    with pytest.raises(EditFieldError, match="nothing to change"):
        build_edit_field_bundle(str(app), entity="Record", field_name="age")

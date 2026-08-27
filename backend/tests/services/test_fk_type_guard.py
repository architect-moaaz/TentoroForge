"""Tests for the FK-column-type guard."""
from services.fk_type_guard import guard_fk_types, pk_type_to_fk_type


def _schema(root, name, text):
    d = root / "src" / "db" / "schema"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.ts").write_text(text)


LANDLORD = '''import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";
export const landlords = pgTable("landlords", {
  id: uuid("id").primaryKey().defaultRandom(),
  fullName: varchar("full_name", { length: 255 }).notNull(),
});
'''

# properties.landlordId is integer but landlords.id is uuid — the classic bug.
PROPERTY_BAD = '''import { pgTable, uuid, varchar, foreignKey, integer } from "drizzle-orm/pg-core";
import { landlords } from "./landlord";
export const properties = pgTable("properties", {
  id: uuid("id").primaryKey().defaultRandom(),
  landlordId: integer("landlord_id").notNull(),
  name: varchar("name", { length: 255 }).notNull(),
}, (table) => ({
  landlordIdFk: foreignKey({ columns: [table.landlordId], foreignColumns: [landlords.id] }),
}));
'''


def test_pk_type_mapping():
    assert pk_type_to_fk_type("uuid") == "uuid"
    assert pk_type_to_fk_type("serial") == "integer"      # serial PK → integer FK
    assert pk_type_to_fk_type("bigserial") == "bigint"
    assert pk_type_to_fk_type("integer") == "integer"


def test_fixes_integer_fk_to_uuid(tmp_path):
    _schema(tmp_path, "landlord", LANDLORD)
    _schema(tmp_path, "property", PROPERTY_BAD)

    res = guard_fk_types(tmp_path)
    assert res["fixed"] == 1
    ch = res["changes"][0]
    assert (ch["column"], ch["from"], ch["to"], ch["references"]) == (
        "landlordId", "integer", "uuid", "landlords")

    out = (tmp_path / "src/db/schema/property.ts").read_text()
    assert 'landlordId: uuid("landlord_id")' in out
    assert 'landlordId: integer' not in out
    # uuid was already imported; integer is now unused → pruned.
    assert "integer" not in out.split("pgTable")[0]


def test_serial_pk_fk_should_be_integer(tmp_path):
    _schema(tmp_path, "user", '''import { pgTable, serial, varchar } from "drizzle-orm/pg-core";
export const users = pgTable("users", { id: serial("id").primaryKey(), email: varchar("email") });
''')
    _schema(tmp_path, "post", '''import { pgTable, uuid, foreignKey } from "drizzle-orm/pg-core";
import { users } from "./user";
export const posts = pgTable("posts", {
  id: uuid("id").primaryKey().defaultRandom(),
  authorId: uuid("author_id").notNull(),
}, (table) => ({
  fk: foreignKey({ columns: [table.authorId], foreignColumns: [users.id] }),
}));
''')
    res = guard_fk_types(tmp_path)
    assert res["fixed"] == 1
    out = (tmp_path / "src/db/schema/post.ts").read_text()
    assert 'authorId: integer("author_id")' in out
    assert "integer" in out.split("pgTable")[0]  # import added


def test_inline_references_form(tmp_path):
    _schema(tmp_path, "org", '''import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";
export const organizations = pgTable("organizations", { id: uuid("id").primaryKey(), name: varchar("name") });
''')
    _schema(tmp_path, "member", '''import { pgTable, uuid, integer, varchar } from "drizzle-orm/pg-core";
import { organizations } from "./org";
export const members = pgTable("members", {
  id: uuid("id").primaryKey().defaultRandom(),
  orgId: integer("org_id").references(() => organizations.id),
});
''')
    res = guard_fk_types(tmp_path)
    assert res["fixed"] == 1
    out = (tmp_path / "src/db/schema/member.ts").read_text()
    assert 'orgId: uuid("org_id")' in out


def test_idempotent_on_consistent_schema(tmp_path):
    _schema(tmp_path, "landlord", LANDLORD)
    # A correct property schema (landlordId already uuid).
    _schema(tmp_path, "property", PROPERTY_BAD.replace(
        'landlordId: integer("landlord_id")', 'landlordId: uuid("landlord_id")'
    ).replace(", integer ", " "))
    res = guard_fk_types(tmp_path)
    assert res["fixed"] == 0


def test_leaves_unrelated_columns_alone(tmp_path):
    # A varchar column that is NOT an FK must not be touched.
    _schema(tmp_path, "landlord", LANDLORD)
    _schema(tmp_path, "property", PROPERTY_BAD)
    guard_fk_types(tmp_path)
    out = (tmp_path / "src/db/schema/property.ts").read_text()
    assert 'name: varchar("name", { length: 255 })' in out  # untouched


def test_no_schema_dir(tmp_path):
    assert guard_fk_types(tmp_path) == {"checked": 0, "fixed": 0, "changes": []}

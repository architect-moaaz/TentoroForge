from pathlib import Path
from services.user_fk_types import reconcile_user_fk_types


def _schema(tmp: Path, users_id: str):
    d = tmp / "src" / "db" / "schema"; d.mkdir(parents=True)
    (d / "user.ts").write_text(
        'import { pgTable, ' + ('serial' if users_id == 'serial' else 'uuid') + ', text } from "drizzle-orm/pg-core";\n'
        f'export const users = pgTable("users", {{ id: {users_id}("id").primaryKey() }});', encoding="utf-8")
    (d / "property.ts").write_text(
        'import { pgTable, uuid, text } from "drizzle-orm/pg-core";\n'
        'export const properties = pgTable("properties", {\n'
        '  id: uuid("id").primaryKey(),\n'
        '  landlordId: uuid("landlord_id").notNull(),\n'   # user FK -> integer
        '  tenantId: uuid("tenant_id"),\n'                  # domain FK -> stays uuid
        '});', encoding="utf-8")
    return d


def test_rewrites_owner_fk_to_integer_when_users_id_serial(tmp_path):
    d = _schema(tmp_path, "serial")
    rep = reconcile_user_fk_types(tmp_path)
    assert rep["reconciled"] and rep["columns"] == 1
    txt = (d / "property.ts").read_text(encoding="utf-8")
    assert 'landlordId: integer("landlord_id")' in txt   # user FK rewritten
    assert 'tenantId: uuid("tenant_id")' in txt           # domain FK untouched
    assert "integer" in txt.splitlines()[0]               # import added


def test_noop_when_users_id_uuid(tmp_path):
    _schema(tmp_path, "uuid")
    assert reconcile_user_fk_types(tmp_path)["reconciled"] is False

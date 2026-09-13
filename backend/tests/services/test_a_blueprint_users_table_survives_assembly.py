"""The projected users table is the application's; the scaffold's is a default.

Criterion Refunds v2 declared a User entity with `role` (eight approval roles)
and `homePropertyId`. `emit_entity_module` produced the right file — the
platform's columns, then those two — and assembly copied the template's
`user.ts` over it on every build because the file was listed as
scaffold-owned. The users table had no role column and every queue was empty.
"""
from pathlib import Path

from services.blueprint import assembly
from services.blueprint.projection import project_data_layer


def _doc():
    return {"data": {"entities": [
        {"id": "ENTITY-002", "name": "User", "table": "users", "status": "PROPOSED", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "email", "type": "string", "required": True},
            {"name": "role", "type": "string", "enumValues": ["FOM", "GM"]},
            {"name": "homePropertyId", "type": "uuid"}]}],
        "relationships": []}}


def test_the_users_file_is_a_default_not_an_owned_file():
    assert "src/db/schema/user.ts" in assembly.SCAFFOLD_DEFAULTS
    assert "src/db/schema/user.ts" not in assembly.SCAFFOLD_OWNED


def test_the_projection_writes_users_with_the_blueprints_columns(tmp_path):
    project_data_layer(_doc(), tmp_path)
    text = (tmp_path / "src" / "db" / "schema" / "user.ts").read_text()
    assert 'password: text("password")' in text          # the platform's column, kept
    assert 'role: text("role")' in text                    # the Blueprint's, added
    assert 'homePropertyId: uuid("home_property_id")' in text


def test_the_barrel_exports_user_once(tmp_path):
    project_data_layer(_doc(), tmp_path)
    barrel = (tmp_path / "src" / "db" / "schema" / "index.ts").read_text()
    assert barrel.count('from "./user"') == 1


def test_assembly_does_not_overwrite_a_projected_users_file(tmp_path, monkeypatch):
    """A default fills a hole; a projected file stands."""
    out = tmp_path / "app"
    (out / "src" / "db" / "schema").mkdir(parents=True)
    projected = out / "src" / "db" / "schema" / "user.ts"
    projected.write_text("// projected\nexport const users = 1;\n")
    template_root = tmp_path / "tmpl"
    (template_root / "src" / "db" / "schema").mkdir(parents=True)
    (template_root / "src" / "db" / "schema" / "user.ts").write_text("// scaffold default\n")
    monkeypatch.setattr(assembly, "_template_dirs", lambda: [template_root])
    assembly.copy_scaffold(out, project_short_id="t1")
    assert projected.read_text().startswith("// projected")


def test_the_password_column_is_masked_under_the_platforms_name():
    """`GET /api/data/users` returned the bcrypt hash: the manifest said
    `passwordHash`, the platform column is `password`."""
    from services.blueprint.projection import sensitive_columns
    doc = {"data": {"entities": [
        {"id": "ENTITY-002", "name": "User", "table": "users", "fields": [
            {"name": "id", "type": "uuid"}, {"name": "email", "type": "string"},
            {"name": "passwordHash", "type": "string"}, {"name": "role", "type": "string"}]}]}}
    manifest = sensitive_columns(doc)
    assert "password" in manifest["users"]
    assert "passwordHash" not in manifest["users"]
    assert manifest["users"]["password"]["readers"] == []

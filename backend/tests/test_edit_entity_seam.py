"""edit_entity — rename an entity and/or its table. The last managed structural
change; the highest cascade, so the tool gates it and the invariant surfaces refs.
"""
import json
from pathlib import Path

import pytest

from services.edit_entity_seam import build_edit_entity_bundle, EditEntityError


@pytest.fixture()
def app(tmp_path):
    (tmp_path / "contracts").mkdir()
    (tmp_path / "src" / "db" / "schema").mkdir(parents=True)
    (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps({"entities": [
        {"name": "Draft", "slug": "draft", "table": "drafts",
         "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "title", "type": "varchar"}]},
        {"name": "User", "slug": "user", "table": "users",
         "fields": [{"name": "id", "type": "uuid"}, {"name": "passwordHash", "type": "varchar"}]}]}))
    (tmp_path / "src" / "db" / "schema" / "draft.ts").write_text(
        'import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";\n\n'
        'export const draft = pgTable("drafts", {\n'
        '  id: uuid("id").primaryKey().defaultRandom(),\n'
        '  title: varchar("title", { length: 255 }),\n'
        '});\n')
    (tmp_path / "src" / "db" / "schema" / "index.ts").write_text(
        'export { draft } from "./draft";\nexport { user } from "./user";\n')
    return tmp_path


def _apply(app, ops):
    for op in ops:
        p = app / op.path
        if op.kind == "delete":
            if p.exists():
                p.unlink()
        else:
            p.write_text(op.content)


def test_rename_moves_registry_module_const_table_and_barrel(app):
    _apply(app, build_edit_entity_bundle(str(app), entity="Draft", new_name="Post"))
    reg = json.loads((app / "contracts" / "resource-registry.json").read_text())
    post = next(e for e in reg["entities"] if e["name"] == "Post")
    assert post["slug"] == "post" and post["table"] == "posts"
    assert not (app / "src" / "db" / "schema" / "draft.ts").exists()
    mod = (app / "src" / "db" / "schema" / "post.ts").read_text()
    assert 'export const post = pgTable("posts"' in mod
    assert "title:" in mod   # columns preserved
    barrel = (app / "src" / "db" / "schema" / "index.ts").read_text()
    assert 'export { post } from "./post";' in barrel
    assert "draft" not in barrel and "user" in barrel


def test_table_only_rename_keeps_the_module_and_name(app):
    _apply(app, build_edit_entity_bundle(str(app), entity="Draft", new_table="draft_records"))
    reg = json.loads((app / "contracts" / "resource-registry.json").read_text())
    draft = next(e for e in reg["entities"] if e["name"] == "Draft")
    assert draft["table"] == "draft_records"
    assert (app / "src" / "db" / "schema" / "draft.ts").exists()
    assert 'pgTable("draft_records"' in (app / "src" / "db" / "schema" / "draft.ts").read_text()


def test_rename_into_the_auth_namespace_is_refused(app):
    with pytest.raises(EditEntityError, match="auth namespace"):
        build_edit_entity_bundle(str(app), entity="Draft", new_name="Account")


def test_renaming_the_auth_entity_is_refused(app):
    with pytest.raises(EditEntityError, match="auth-managed"):
        build_edit_entity_bundle(str(app), entity="User", new_name="Member")


def test_collision_with_an_existing_entity_is_refused(app):
    with pytest.raises(EditEntityError, match="already exists"):
        build_edit_entity_bundle(str(app), entity="Draft", new_name="User")


def test_no_change_is_refused(app):
    with pytest.raises(EditEntityError, match="nothing to change"):
        build_edit_entity_bundle(str(app), entity="Draft")


def test_unknown_entity_is_refused(app):
    with pytest.raises(EditEntityError, match="not found"):
        build_edit_entity_bundle(str(app), entity="Ghost", new_name="X")

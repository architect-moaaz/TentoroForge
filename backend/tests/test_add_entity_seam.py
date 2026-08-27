"""S5-T5 — add_entity seam tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.add_entity_seam import AddEntityError, build_add_entity_bundle


def _seed_app(tmp_path: Path, seed_entity: str = "Candidate") -> Path:
    (tmp_path / "contracts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "db" / "schema").mkdir(parents=True, exist_ok=True)
    (tmp_path / "contracts" / "resource-registry.json").write_text(
        json.dumps({
            "version": "1.0",
            "entities": [{
                "name":  seed_entity,
                "table": seed_entity.lower() + "s",
                "slug":  seed_entity.lower(),
                "fields": [
                    {"name": "id", "type": "uuid", "notNull": True},
                    {"name": "fullName", "type": "varchar"},
                ],
            }],
        })
    )
    (tmp_path / "src" / "db" / "schema" / "index.ts").write_text(
        f'export {{ {seed_entity.lower()} }} from "./{seed_entity.lower()}";\n'
    )
    return tmp_path


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #

def test_add_entity_writes_three_ops(tmp_path):
    app = _seed_app(tmp_path)
    ops = build_add_entity_bundle(
        str(app),
        name="Assessor",
        fields=[
            {"name": "id",        "type": "uuid", "notNull": True},
            {"name": "fullName",  "type": "varchar"},
            {"name": "email",     "type": "varchar", "notNull": True},
            {"name": "specialty", "type": "varchar"},
        ],
    )
    paths = [op.path for op in ops]
    assert "contracts/resource-registry.json" in paths
    assert "src/db/schema/assessor.ts" in paths
    assert "src/db/schema/index.ts" in paths
    assert len(ops) == 3


def test_registry_gains_new_entity(tmp_path):
    app = _seed_app(tmp_path)
    ops = build_add_entity_bundle(
        str(app), name="Assessor",
        fields=[{"name": "email", "type": "varchar", "notNull": True}],
    )
    reg_op = next(o for o in ops if o.path == "contracts/resource-registry.json")
    reg = json.loads(reg_op.content)
    names = [e["name"] for e in reg["entities"]]
    assert "Candidate" in names, "existing entity must survive"
    assert "Assessor" in names, "new entity must be appended"
    # The new entity has table + slug set.
    new_entry = next(e for e in reg["entities"] if e["name"] == "Assessor")
    assert new_entry["table"] == "assessors"
    assert new_entry["slug"] == "assessor"


def test_drizzle_file_carries_imports_and_column_defs(tmp_path):
    app = _seed_app(tmp_path)
    ops = build_add_entity_bundle(
        str(app), name="Assessor",
        fields=[
            {"name": "email",     "type": "varchar", "notNull": True},
            {"name": "specialty", "type": "varchar"},
        ],
    )
    dz_op = next(o for o in ops if o.path.endswith(".ts") and "schema/assessor" in o.path)
    src = dz_op.content
    # Drizzle imports include every builder we used.
    assert "pgTable" in src and "varchar" in src and "uuid" in src and "timestamp" in src
    assert 'pgTable("assessors"' in src
    # Column defs — camelCase var names + real col names in snake.
    assert "email:" in src and 'varchar("email"' in src and ".notNull()" in src
    assert "specialty:" in src and 'varchar("specialty"' in src
    # Auto-injected id + timestamps.
    assert 'id: uuid("id").primaryKey().defaultRandom()' in src
    assert "createdAt:" in src and "updatedAt:" in src


def test_barrel_gains_export_line(tmp_path):
    app = _seed_app(tmp_path)
    ops = build_add_entity_bundle(
        str(app), name="Assessor",
        fields=[{"name": "email", "type": "varchar"}],
    )
    barrel_op = next(o for o in ops if o.path.endswith("schema/index.ts"))
    src = barrel_op.content
    # Old export preserved.
    assert 'from "./candidate";' in src
    # New export appended.
    assert 'export { assessor } from "./assessor";' in src


def test_kebab_case_slug_for_multiword_entity(tmp_path):
    app = _seed_app(tmp_path)
    ops = build_add_entity_bundle(
        str(app), name="InterviewFeedback",
        fields=[{"name": "notes", "type": "text"}],
    )
    slug_ok = any("schema/interview-feedback.ts" in o.path for o in ops)
    assert slug_ok, "multi-word entity should slugify with kebab-case"


# --------------------------------------------------------------------------- #
# Error paths
# --------------------------------------------------------------------------- #

def test_refuses_existing_entity(tmp_path):
    app = _seed_app(tmp_path, seed_entity="Candidate")
    with pytest.raises(AddEntityError, match=r"already exists"):
        build_add_entity_bundle(
            str(app), name="Candidate",
            fields=[{"name": "email", "type": "varchar"}],
        )


def test_refuses_existing_entity_case_insensitively(tmp_path):
    app = _seed_app(tmp_path, seed_entity="Candidate")
    with pytest.raises(AddEntityError, match=r"already exists"):
        build_add_entity_bundle(
            str(app), name="CANDIDATE",  # different case
            fields=[{"name": "email", "type": "varchar"}],
        )


def test_refuses_bad_name(tmp_path):
    app = _seed_app(tmp_path)
    with pytest.raises(AddEntityError, match=r"identifier"):
        build_add_entity_bundle(
            str(app), name="",
            fields=[{"name": "email", "type": "varchar"}],
        )
    with pytest.raises(AddEntityError, match=r"identifier"):
        build_add_entity_bundle(
            str(app), name="123bad",  # starts with digit
            fields=[{"name": "email", "type": "varchar"}],
        )


def test_refuses_empty_fields(tmp_path):
    app = _seed_app(tmp_path)
    with pytest.raises(AddEntityError, match=r"fields"):
        build_add_entity_bundle(str(app), name="Assessor", fields=[])


def test_refuses_missing_output_dir(tmp_path):
    with pytest.raises(AddEntityError, match=r"output_dir missing"):
        build_add_entity_bundle(
            str(tmp_path / "no-such-dir"),
            name="Assessor",
            fields=[{"name": "email", "type": "varchar"}],
        )


def test_refuses_missing_registry(tmp_path):
    (tmp_path / "src" / "db" / "schema").mkdir(parents=True)
    # No contracts/registry.json.
    with pytest.raises(AddEntityError, match=r"registry not found"):
        build_add_entity_bundle(
            str(tmp_path), name="Assessor",
            fields=[{"name": "email", "type": "varchar"}],
        )

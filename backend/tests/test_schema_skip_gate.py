"""Regression test for the schema LLM-skip gate (Pipeline Reliability Atlas A1).

`_schema_files_complete` decides whether the deterministic `build_schema_files`
output already covers every entity — if True, the LLM schema agent is skipped.

The bug: the gate computed the expected filename with the hint-BLIND
`contract_generator._to_slug`, but `build_schema_files` writes the file under
the hint-AWARE Canonical Resource Registry slug. When a plan carries a `table`
hint whose plurality differs from `to_slug(name)` (e.g. hint `equipment`
vs `to_slug` → `equipments`), the gate looked for the WRONG filename, returned
False, and the LLM schema agent ran OVER the already-complete deterministic
build → duplicate schema files (`equipment.ts` AND `equipments.ts`) →
`unknown table` + build break.

The fix: the gate consults the same registry slug the writer uses.
"""

from pathlib import Path

from services.schema_builder import build_schema_files
from routers.generate import _schema_files_complete


def _equipment_plan():
    """Plan whose `Equipment` entity carries a `table:"equipment"` hint whose
    plurality differs from the hint-blind `to_slug` ("equipments")."""
    return {
        "data_models": [
            {
                "name": "Equipment",
                "table": "equipment",
                "fields": [
                    {"name": "id", "type": "serial", "primaryKey": True},
                    {"name": "name", "type": "varchar", "nullable": False},
                    {"name": "serialNumber", "type": "varchar"},
                ],
            },
        ],
    }


def test_gate_true_for_registry_slug_the_writer_wrote(tmp_path):
    plan = _equipment_plan()
    result = build_schema_files(plan, str(tmp_path))
    assert not result["errors"], result["errors"]

    # The writer wrote the hint-aware slug file, NOT the pluralized one.
    assert (tmp_path / "src" / "db" / "schema" / "equipment.ts").exists()
    assert not (tmp_path / "src" / "db" / "schema" / "equipments.ts").exists()

    # The gate must recognise the build as complete (finds equipment.ts).
    assert _schema_files_complete(str(tmp_path), plan) is True


def test_old_to_slug_logic_would_have_misfired(tmp_path):
    """Demonstrate the pre-fix gate (hint-blind `to_slug`) returns False on the
    exact same complete build — proving the bug and that the fix closes it."""
    plan = _equipment_plan()
    build_schema_files(plan, str(tmp_path))

    from services.contract_generator import _to_slug, _to_table
    from services.schema_builder import _normalize_models, RESERVED_TABLES

    def _old_gate(output_dir: str, plan: dict) -> bool:
        root = Path(output_dir)
        models = _normalize_models(plan.get("data_models"))
        if not models:
            return False
        for m in models:
            if _to_table(m["name"]) in RESERVED_TABLES:
                continue
            slug = _to_slug(m["name"])
            if not (root / "src" / "db" / "schema" / f"{slug}.ts").exists():
                return False
            if not (root / "src" / "types" / f"{slug}.ts").exists():
                return False
        return True

    # OLD logic looks for "equipments.ts" → misfires (False) on a complete build.
    assert _old_gate(str(tmp_path), plan) is False
    # NEW logic (the fix) correctly reports the build complete.
    assert _schema_files_complete(str(tmp_path), plan) is True


def test_reserved_users_entity_not_required(tmp_path):
    """A `User` entity maps to the auth-reserved `users` table and writes no
    builder file — the gate must not demand `users.ts`/`user.ts`."""
    plan = {
        "data_models": [
            {
                "name": "User",
                "fields": [
                    {"name": "id", "type": "serial", "primaryKey": True},
                    {"name": "email", "type": "varchar", "nullable": False},
                ],
            },
            {
                "name": "Project",
                "fields": [
                    {"name": "id", "type": "serial", "primaryKey": True},
                    {"name": "name", "type": "varchar", "nullable": False},
                ],
            },
        ],
    }
    build_schema_files(plan, str(tmp_path))
    # User writes no file; only Project does.
    assert not (tmp_path / "src" / "db" / "schema" / "users.ts").exists()
    assert (tmp_path / "src" / "db" / "schema" / "projects.ts").exists()
    # Gate is complete despite no users.ts (reserved entity is skipped).
    assert _schema_files_complete(str(tmp_path), plan) is True

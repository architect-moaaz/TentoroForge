"""Slice E T1 — workflow_tasks Drizzle schema template.

The runtime's persistPendingTask writes to a `workflow_tasks` table
(see backend/templates/runtime/workflows/index.ts:186). Without a
Drizzle schema shipped alongside the runtime, `drizzle-kit generate`
never emits a migration for it and the INSERT swallows silently
(the runtime already wraps it in try/catch as best-effort).

This test locks in:
  1. the schema template file exists at the expected path
  2. it declares every column the INSERT statement writes
  3. runtime_injector.copy_forge_extras is wired to ship it into
     every generated app's src/db/schema/ tree AND register the
     export in the barrel index.ts
"""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile

import pytest


_BACKEND = Path(__file__).parent.parent.parent
_TEMPLATE = _BACKEND / "templates" / "runtime" / "db" / "workflow-tasks.schema.ts"


# Columns the runtime's persistPendingTask INSERT writes today
# (backend/templates/runtime/workflows/index.ts:203-227). Keeping this
# authoritative — if the runtime learns to write a new column, the
# schema template must grow to match or migrations will drift.
_INSERT_COLUMNS = (
    "id",
    "workflow_id",
    "workflow_instance_id",
    "node_id",
    "node_label",
    "task_type",
    "status",
    "assignee_id",
    "assignee_role",
    "assignee_group_id",
    "entity_type",
    "entity_id",
    "form_data",
    "form_binding",
    "process_variables",
    "due_at",
    "created_at",
)

# Lifecycle columns not written by persistPendingTask yet, but needed
# by the task-completion path (Slice E T2/T5). Include them now so
# the future writer has somewhere to land.
_LIFECYCLE_COLUMNS = ("completed_at", "completed_by", "decision")


def test_schema_template_exists():
    assert _TEMPLATE.is_file(), (
        f"expected workflow_tasks schema template at {_TEMPLATE}"
    )


def test_schema_table_name_matches_runtime_insert():
    text = _TEMPLATE.read_text(encoding="utf-8")
    # Drizzle table declaration: pgTable("workflow_tasks", { ... })
    assert 'pgTable("workflow_tasks"' in text, (
        "table name must be exactly workflow_tasks (matches runtime INSERT)"
    )


def test_schema_declares_every_insert_column():
    text = _TEMPLATE.read_text(encoding="utf-8")
    for col in _INSERT_COLUMNS:
        # Every column must show up as its snake_case DB name inside
        # a Drizzle column helper — e.g. text("workflow_id"), uuid("id").
        assert f'"{col}"' in text, (
            f"schema missing column {col!r} that persistPendingTask INSERTs"
        )


def test_schema_declares_lifecycle_columns_for_completion_path():
    text = _TEMPLATE.read_text(encoding="utf-8")
    for col in _LIFECYCLE_COLUMNS:
        assert f'"{col}"' in text, (
            f"schema missing lifecycle column {col!r} — "
            f"Slice E T2/T5 completion path will have nowhere to write"
        )


def test_schema_exports_named_forgeWorkflowTasks():
    text = _TEMPLATE.read_text(encoding="utf-8")
    # The barrel export line in runtime_injector expects this exact name
    # (mirrors forgeNotifications / forgeSchedules convention).
    assert "export const forgeWorkflowTasks" in text


def test_runtime_injector_ships_schema_and_registers_barrel(tmp_path):
    """End-to-end: run _inject_file_storage against a minimal fake app
    tree and check the workflow_tasks schema file lands + the barrel
    index.ts learns to export it. The workflow_tasks copy is grouped
    into the same forge-extras helper that ships forge_files /
    forge_notifications / forge_schedules — one seam, one test."""
    from services import runtime_injector

    # Minimal app skeleton: needs src/db/schema/index.ts as the barrel.
    schema_dir = tmp_path / "src" / "db" / "schema"
    schema_dir.mkdir(parents=True)
    (schema_dir / "index.ts").write_text(
        '// existing schema barrel\n', encoding="utf-8"
    )
    (tmp_path / "src" / "lib").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "app" / "api").mkdir(parents=True, exist_ok=True)

    written = runtime_injector._inject_file_storage(tmp_path)
    assert isinstance(written, list)

    dst = schema_dir / "_forge_workflow_tasks.ts"
    assert dst.is_file(), (
        f"runtime_injector did not ship workflow_tasks schema; "
        f"written files: {written}"
    )
    assert "src/db/schema/_forge_workflow_tasks.ts" in written

    barrel = (schema_dir / "index.ts").read_text(encoding="utf-8")
    assert "forgeWorkflowTasks" in barrel, (
        "runtime_injector did not add forgeWorkflowTasks export to barrel"
    )
    # Idempotent: running twice does not double-export.
    runtime_injector._inject_file_storage(tmp_path)
    barrel2 = (schema_dir / "index.ts").read_text(encoding="utf-8")
    assert barrel2.count("forgeWorkflowTasks") == 1

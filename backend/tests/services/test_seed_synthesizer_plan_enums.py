"""Seed synthesizer must honor PLAN enum_values for plain-varchar columns.

The Drizzle schema only carries values for pgEnum columns; plans routinely
type status/priority as varchar WITH enum_values. Those columns used to fall
through to the generic string family and seed literals like "Status 10" —
which then surfaced as kanban lanes and badge labels (cwx1stzz)."""
from __future__ import annotations

import json
from pathlib import Path

from services.seed_synthesizer import _plan_enum_values, synthesize_seed_rows

PLAN = {"entities": {"Task": {"table": "tasks", "fields": [
    {"name": "id", "type": "uuid"},
    {"name": "title", "type": "varchar"},
    {"name": "status", "type": "varchar",
     "enum_values": ["todo", "in_progress", "done"]},
]}}}

SCHEMA_TS = '''
import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";
export const tasks = pgTable("tasks", {
  id: uuid("id").primaryKey().defaultRandom(),
  title: varchar("title", { length: 255 }).notNull(),
  status: varchar("status", { length: 64 }).notNull(),
});
'''


def _seed_app(root: Path) -> None:
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "db" / "schema").mkdir(parents=True)
    (root / "contracts").mkdir(parents=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps(PLAN), encoding="utf-8")
    (root / "src" / "db" / "schema" / "tasks.ts").write_text(SCHEMA_TS, encoding="utf-8")
    (root / "contracts" / "seed-plan.json").write_text(json.dumps({
        "tables": [{"name": "tasks", "row_count": 6}]}), encoding="utf-8")


def test_plan_enum_map_keys_by_entity_and_table(tmp_path):
    _seed_app(tmp_path)
    m = _plan_enum_values(str(tmp_path))
    assert m[("tasks", "status")] == ["todo", "in_progress", "done"]
    assert m[("task", "status")] == ["todo", "in_progress", "done"]


def test_varchar_status_seeded_with_plan_enums(tmp_path):
    _seed_app(tmp_path)
    res = synthesize_seed_rows(str(tmp_path))
    assert res["rows_total"] == 6
    plan = json.loads((tmp_path / "contracts" / "seed-plan.json").read_text(encoding="utf-8"))
    rows = plan["tables"][0]["seed_data"]
    statuses = {r["status"] for r in rows}
    assert statuses <= {"todo", "in_progress", "done"}
    assert not any(s.startswith("Status") for s in statuses)
    # non-enum varchar keeps the readable generic value
    assert rows[0]["title"].startswith("Task")

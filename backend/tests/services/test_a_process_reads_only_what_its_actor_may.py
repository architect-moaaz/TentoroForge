"""A workflow's own database steps are kept to what the acting person may
reach, by the same ownership rules the data API applies.

`db_query`, `db_update` and `db_delete` built their WHERE from the step's
config alone, so a process started by one vendor read and changed every
vendor's rows while the vendor's pages could not (2026-10-12). A run with
no acting person — a schedule, another system's event — is the
application's own and is not scoped."""
from __future__ import annotations

import re
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "templates" / "runtime"


def test_the_engine_lends_its_scope_to_a_table():
    engine = (RUNTIME / "data-engine.ts").read_text()
    assert "export async function scopeForTable(" in engine
    assert "export async function accessConditions(" in engine
    body = engine.split("export async function scopeForTable(", 1)[1].split("\n}\n", 1)[0]
    assert "if (!user?.id) return undefined;" in body, "no acting person: the application's own, unscoped"
    assert "accessConditions(name, rec, { user }, op)" in body, "the same rules the data API applies"


def test_every_reading_and_writing_step_asks_for_it():
    index = (RUNTIME / "workflows" / "index.ts").read_text()
    for handler, op in (("db_update", "write"), ("db_delete", "write"), ("db_query", "read")):
        block = index.split(f'registerActionHandler("{handler}"', 1)[1].split("registerActionHandler(", 1)[0]
        assert f'_scoped(table, where, ctx, "{op}")' in block, f"{handler} runs unscoped"
    assert re.search(r"q\.where\(await _scoped\(table, where, ctx, \"write\"\)\)\.returning\(\)", index), "db_update writes through the scope"

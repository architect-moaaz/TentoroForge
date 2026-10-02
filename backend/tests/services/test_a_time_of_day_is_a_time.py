"""Med Tracker on forge-v3 (egqkhylj), 2026-09-29. "Preferred time" is a time
of day, and the data model said `time`; the projection made it a timestamp.
The form sent "09:00", no date could be made of it, and the required column
got null. Correcting the column type then met `drizzle-kit push --force`,
which reads a type change as data loss and truncates the table.
"""
from __future__ import annotations

from pathlib import Path

from services.blueprint.projection import drizzle_column

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


def test_a_time_field_is_a_time_column():
    line, builder = drizzle_column({"name": "preferredTime", "type": "time", "required": True})
    assert builder == "time" and line == 'preferredTime: time("preferred_time").notNull(),'
    assert drizzle_column({"name": "takenAt", "type": "datetime"})[1] == "timestamp"


def test_a_changed_type_is_converted_before_push_keeping_the_rows():
    prep = (TEMPLATES / "app-foundation/src/db/prepare-schema.ts").read_text()
    assert "timestamp: [\"time\", \"date\"]" in prep and "USING ${quote(column_name)}::${want}" in prep
    assert "converted = await convertTypes(sql);" in prep
    # Only conversions that keep what the value meant; anything else stays with push.
    assert "if (!(KEEPS_ITS_MEANING[have] ?? []).includes(want)) continue;" in prep


def test_seeded_rows_give_a_time_column_a_time():
    seed = (TEMPLATES / "runtime/seed.ts").read_text()
    assert 'else if (ct === "pgtime") out[key] = "09:00:00";' in seed
    assert 'val = m ? m[1] : "09:00:00";' in seed

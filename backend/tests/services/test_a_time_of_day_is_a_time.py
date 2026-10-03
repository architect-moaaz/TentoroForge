"""Med Tracker on forge-v3 (egqkhylj), 2026-09-29. "Preferred time" is a time
of day, and the data model said `time`; the projection made it a timestamp.
The form sent "09:00", no date could be made of it, and the required column
got null. Correcting the column type then met `drizzle-kit push --force`,
which reads a type change as data loss and truncates the table.
"""
from __future__ import annotations

import re
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
    assert "if ((KEEPS_ITS_MEANING[have] ?? []).includes(family(want))) {" in prep


def test_seeded_rows_give_a_time_column_a_time():
    seed = (TEMPLATES / "runtime/seed.ts").read_text()
    assert 'else if (ct === "pgtime") out[key] = "09:00:00";' in seed
    assert 'val = m ? m[1] : "09:00:00";' in seed


# --- RK_Test (jbih8cj3), 2026-09-28: "Doctor's appointment slot is showing junk
# value in place of time". The sample slot was "Start Time 12"; the seed's
# `new Date("Start Time 12")` is 1 December 2001, and every slot showed a date.

def test_a_sample_time_of_day_is_a_time_and_an_end_follows_its_start():
    from services.blueprint.projection import _seed_value
    starts = [_seed_value({"name": "startTime", "type": "time"}, "Slot", r) for r in range(1, 9)]
    ends = [_seed_value({"name": "endTime", "type": "time"}, "Slot", r) for r in range(1, 9)]
    assert all(re.fullmatch(r"\d{2}:\d{2}", v) for v in starts + ends)
    assert len(set(starts)) > 4                                      # a spread, not one time
    assert all(e > s for s, e in zip(starts, ends))
    assert _seed_value({"name": "slotEndTime", "type": "time"}, "Slot", 1) == "10:00"
    assert _seed_value({"name": "attendeeTime", "type": "time"}, "Slot", 1) == "09:00"


def test_a_time_fields_own_examples_are_used_when_they_are_times():
    from services.blueprint.projection import _seed_value
    field = {"name": "opensAt", "type": "time", "examples": ["10:15", "Morning", "16:00"]}
    assert [_seed_value(field, "Shop", r) for r in (1, 2, 3)] == ["10:15", "16:00", "10:15"]


def test_no_sample_record_carries_a_label_for_a_time():
    from services.blueprint.projection import seed_rows
    doc = {"data": {"entities": [{"id": "ENTITY-001", "name": "AvailabilitySlot", "table": "availability_slots",
                                  "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                                             {"name": "date", "type": "date"},
                                             {"name": "startTime", "type": "time"},
                                             {"name": "endTime", "type": "time"}]}]}}
    rows = seed_rows(doc)["availability_slots"]
    assert rows and all(re.fullmatch(r"\d{2}:\d{2}", r["startTime"]) for r in rows)
    assert not any("Time" in str(v) for r in rows for v in r.values())


def test_the_seed_does_not_read_a_label_as_a_date():
    seed = (TEMPLATES / "runtime/seed.ts").read_text()
    assert 'const dated = typeof val !== "string" || /^\\d{4}-\\d{2}-\\d{2}/.test(val.trim());' in seed
    assert "const d = dated ? new Date(val as any) : new Date(NaN);" in seed

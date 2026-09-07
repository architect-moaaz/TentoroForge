"""Registry accuracy: extractor reads real notNull/default (incl. multi-line column
defs), reconcile_entities folds accurate fields onto the singular plan key, and the
deterministic builder marks required (NOT NULL, no default) fields. Regression for
the "create reservation: null check_in_date" crash + empty FK dropdowns."""
from pathlib import Path

from services.registry_extractor import extract_entities_from_schema
from services.registry import reconcile_entities
from services.deterministic_pages import build_crud_page, _is_required

SCHEMA_TS = '''
import { pgTable, uuid, varchar, timestamp, integer } from "drizzle-orm/pg-core";

export const reservations = pgTable("reservations", {
  id: uuid("id").primaryKey().defaultRandom(),
  guestId: uuid("guest_id")
    .references(() => guests.id)
    .notNull(),
  roomId: uuid("room_id").references(() => rooms.id).notNull(),
  checkInDate: timestamp("check_in_date").notNull(),
  actualCheckIn: timestamp("actual_check_in"),
  adults: integer("adults").notNull().default(1),
  status: varchar("status", { length: 50 }).notNull().default("confirmed"),
  source: varchar("source", { length: 50 }),
});
'''


def _extract(tmp_path) -> dict:
    sd = tmp_path / "src" / "db" / "schema"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "reservation.ts").write_text(SCHEMA_TS, encoding="utf-8")
    return extract_entities_from_schema(str(tmp_path))


def test_extractor_handles_multiline_notnull(tmp_path):
    f = _extract(tmp_path)["Reservations"]["fields"]
    # guestId/roomId have .notNull() on wrapped lines — must still be notNull.
    assert f["guestId"]["nullable"] is False
    assert f["roomId"]["nullable"] is False
    assert f["checkInDate"]["nullable"] is False
    # genuinely nullable
    assert f["actualCheckIn"]["nullable"] is True
    assert f["source"]["nullable"] is True


def test_extractor_captures_hasdefault(tmp_path):
    f = _extract(tmp_path)["Reservations"]["fields"]
    assert f["adults"].get("hasDefault") is True
    assert f["status"].get("hasDefault") is True
    assert f["id"].get("hasDefault") is True  # defaultRandom()
    assert f["checkInDate"].get("hasDefault", False) is False


def test_reconcile_folds_onto_singular_plan_key(tmp_path):
    extracted = _extract(tmp_path)
    plan = {"entities": {"Reservation": {"fields": {
        k: {"type": "x", "nullable": False, "primaryKey": (k == "id")} for k in extracted["Reservations"]["fields"]
    }}}}
    rec = reconcile_entities(plan, extracted)
    # No duplicate plural entity; singular key gains accurate metadata.
    assert "Reservations" not in rec["entities"]
    assert rec["entities"]["Reservation"]["fields"]["actualCheckIn"]["nullable"] is True
    assert rec["entities"]["Reservation"]["fields"]["adults"]["hasDefault"] is True


def test_is_required_logic():
    assert _is_required({"nullable": False}) is True
    assert _is_required({"nullable": False, "hasDefault": True}) is False  # defaulted
    assert _is_required({"nullable": True}) is False
    assert _is_required({"notNull": True}) is True


def test_builder_marks_required_from_accurate_meta(tmp_path):
    rec = reconcile_entities(
        {"entities": {"Reservation": {"fields": {k: {"nullable": False} for k in _extract(tmp_path)["Reservations"]["fields"]}}}},
        _extract(tmp_path),
    )
    page = build_crud_page("form", "Reservation", rec["entities"]["Reservation"]["fields"],
                           "/reservations/new", {}, entities=rec["entities"])
    req = {}
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") in ("Select", "DatePicker", "Input", "Textarea"):
                req[n["props"]["name"]] = n["props"].get("validators", {}).get("required", False)
            for c in n.get("children") or []:
                walk(c)
    walk(page["root"])
    assert req["guestId"] is True and req["roomId"] is True
    assert req["checkInDate"] is True
    assert req["actualCheckIn"] is False  # nullable
    assert req["source"] is False         # nullable

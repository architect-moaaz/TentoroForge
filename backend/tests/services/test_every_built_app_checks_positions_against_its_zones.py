"""Geofencing, phase 2 (2026-11-16): a position that reaches the tracking route is checked against the app's zones.
The route imports `@/lib/geofence`, so the library and the tables must ship wherever the route does, or the app does not build.
The check must never fail or hold up the position: an app without the tables, or a database blip, still tracks."""
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "templates" / "runtime"
INJECTOR = (Path(__file__).resolve().parents[2] / "services" / "runtime_injector.py").read_text(encoding="utf-8")


def test_the_tracking_route_checks_both_kinds_of_position():
    route = (RUNTIME / "api-tracking-update" / "route.ts").read_text(encoding="utf-8")
    assert 'from "@/lib/geofence"' in route
    assert route.count("checkPosition(") == 2, "a trip position and a fleet (waiting) position are both checked"
    assert 'out !== "old"' in route and 'result !== "old"' in route, "a position that was not believed is not checked"


def test_the_library_ships_with_the_route_and_the_tables_ship_in_the_schema():
    assert '"tracking", "geofence"]' in INJECTOR
    assert "forge-geofences.schema.ts" in INJECTOR
    for table in ("forgeGeofences", "forgeGeofenceAssignments", "forgeGeofenceState", "forgeGeofenceEvents", "forgeGeofenceRules"):
        assert table in INJECTOR
        assert f"export const {table} " in (RUNTIME / "db" / "forge-geofences.schema.ts").read_text(encoding="utf-8")


def test_the_check_never_throws():
    src = (RUNTIME / "geofence" / "index.ts").read_text(encoding="utf-8")
    body = src[src.index("export async function checkPosition"):]
    assert "try {" in body and "catch (err)" in body


def test_an_event_is_announced_with_a_key_so_the_bus_cannot_start_a_process_twice():
    src = (RUNTIME / "geofence" / "index.ts").read_text(encoding="utf-8")
    assert "dedupeKey" in src and "e.id" in src


def test_the_shipped_geofence_files_import_nothing_the_app_lacks():
    import re
    for f in (RUNTIME / "geofence").glob("*.ts"):
        for m in re.finditer(r'from "([^"]+)"', f.read_text(encoding="utf-8")):
            spec = m.group(1)
            assert spec.startswith(".") or spec in ("@/db", "@/auth", "drizzle-orm") or spec.startswith("@/lib/"), (f.name, spec)


def test_a_crossing_goes_through_the_rules_and_a_held_or_failed_rule_is_put_on_the_bus():
    src = (RUNTIME / "geofence" / "index.ts").read_text(encoding="utf-8")
    assert "await actOn(e)" in src
    assert "geofence.action_" in src and "hasEvidence" in src


def test_the_rules_table_can_hold_the_confirmation_a_sensitive_rule_needs():
    schema = (RUNTIME / "db" / "forge-geofences.schema.ts").read_text(encoding="utf-8")
    assert 'confirm: jsonb("confirm")' in schema and 'sensitive: boolean("sensitive")' in schema


def test_the_bus_tells_the_geofence_library_when_an_event_was_processed_so_held_actions_can_be_released():
    bus = (RUNTIME / "events" / "bus.ts").read_text(encoding="utf-8")
    assert "confirmationArrived(evt)" in bus
    assert 'startsWith("geofence.")' in bus, "a geofence event must not loop back into the release"


def test_the_live_zone_line_ships_and_shows_each_person_only_what_they_may_open():
    route = (RUNTIME / "api-geofence-stream" / "route.ts").read_text(encoding="utf-8")
    assert "visibleIds(entity)" in route and "whoIs()" in route
    assert "seeing.has(e.entityId)" in route
    assert '"api-geofence-stream", "stream"' in INJECTOR and '"api" / "geofence"' in INJECTOR

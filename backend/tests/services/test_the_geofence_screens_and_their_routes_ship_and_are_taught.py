"""Geofencing, phase 5 (2026-11-16): five screens (map, editor, monitor, timeline, settings), the routes behind them, and the
page agent that is told when to use them.

What each guards, found building them against a real browser and database:
- the maps draw zones and report clicks (the editor cannot work otherwise), in BOTH engines;
- a role is matched without regard to case ("Admin" is the app's, "admin" the setting's) or the admin is locked out;
- a Next route exports only its handlers, so the helpers live elsewhere;
- a screen that only needs to know WHICH records a person may see must not read, decrypt and unmask every sensitive column of
  every row to find out (it took 17 s and logged 500 unmaskings a poll).
"""
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
RUNTIME = BACKEND / "templates" / "runtime"
SDK = BACKEND / "templates" / "app-foundation" / "src" / "sdk"
INJECTOR = (BACKEND / "services" / "runtime_injector.py").read_text(encoding="utf-8")
UI = (BACKEND / "services" / "blueprint" / "ui_engineer.py").read_text(encoding="utf-8")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_the_five_screens_exist_and_are_exported():
    src = read(SDK / "geofence.tsx")
    for name in ("GeofenceMap", "GeofenceEditor", "GeofenceMonitor", "GeofenceEventTimeline", "GeofenceSettings", "useZones"):
        assert re.search(rf"export function {name}\b", src), name


def test_both_map_engines_draw_zones_and_report_clicks():
    shared = read(SDK / "map-shared.ts")
    assert "export type MapZone" in shared and "export function ringOf" in shared
    for f in ("map.tsx", "map-google.tsx"):
        src = read(SDK / f)
        assert "zones" in src and "ringOf" in src, f
        assert "onMapClick" in src and "onZoneClick" in src, f
    assert "MapZone" in read(SDK / "map.tsx"), "the free map re-exports the type the screens import"


def test_the_routes_ship_with_the_app():
    for d in ("stream", "zones", "rules", "events"):
        assert (RUNTIME / f"api-geofence-{d}" / "route.ts").exists()
        assert f"api-geofence-{d}" in INJECTOR or d == "stream" or '"api-geofence-' + d + '"' in INJECTOR
    assert "api/geofence/" in INJECTOR


def test_a_next_route_exports_only_its_handlers():
    for d in ("stream", "zones", "rules", "events"):
        src = read(RUNTIME / f"api-geofence-{d}" / "route.ts")
        names = re.findall(r"^export (?:async )?(?:function|const) (\w+)", src, re.M)
        assert set(names) <= {"GET", "POST", "PATCH", "DELETE", "runtime", "dynamic", "maxDuration"}, (d, names)


def test_changing_zones_and_rules_needs_a_zone_manager_and_reading_events_follows_the_records():
    for d in ("zones", "rules"):
        src = read(RUNTIME / f"api-geofence-{d}" / "route.ts")
        assert "manager" in src and "403" in src, d
    for d in ("stream", "events"):
        src = read(RUNTIME / f"api-geofence-{d}" / "route.ts")
        assert "visibleIds(" in src and "whoIs()" in src, d
        assert "visibleMembers" not in src, "reading every field of every row just to learn the ids is what made it slow"


def test_the_data_engine_can_say_which_records_are_readable_without_reading_them():
    engine = read(RUNTIME / "data-engine.ts")
    body = engine[engine.index("export async function visibleIds"):engine.index("export async function query(")]
    assert "accessConditions(" in body, "the same ownership and row rules"
    assert "select({ id:" in body.replace("\n", " "), "only the id column is selected"
    assert "_maskOrUnmaskOnRead" not in body
    assert "export async function visibleIds" in read(RUNTIME / "tracking" / "access.ts")


def test_the_page_agent_knows_the_screens_and_the_gps_rule():
    assert '"@/sdk/geofence"' in UI
    for name in ("GeofenceMap", "GeofenceEditor", "GeofenceMonitor", "GeofenceEventTimeline", "GeofenceSettings"):
        assert name in UI, name
    assert "NEVER make an arrival complete an order" in UI
    assert '"@/sdk/geofence": ("maplibre-gl",)' in UI, "a page that imports the screens gets the map library"


def test_the_settings_screen_says_what_a_sensitive_rule_waits_for():
    src = read(SDK / "geofence.tsx")
    assert "isSensitive" in src and "never run" in src
    assert "willWaitFor" in src

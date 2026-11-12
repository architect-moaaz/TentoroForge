"""Google Maps is an optional second map; the free one stays the default. A route
(line, distance, arrival time) comes from Google when the app has a server key,
from a free service otherwise, and a screen never shows a dead grey box."""
import shutil
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
FOUNDATION = BACKEND / "templates" / "app-foundation"
SDK = FOUNDATION / "src" / "sdk"
RUNTIME = BACKEND / "templates" / "runtime"


def _t(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_the_free_map_is_the_default_and_google_needs_its_own_key():
    m = _t(SDK / "map.tsx")
    assert "NEXT_PUBLIC_GOOGLE_MAPS_API_KEY" in m and "NEXT_PUBLIC_MAP_PROVIDER" in m
    assert 'DEFAULT_STYLE = "https://tiles.openfreemap.org' in m
    assert "onFail" in m and "MapLibreView" in m  # falls back by itself when Google refuses


def test_the_google_map_reports_a_refused_key_instead_of_staying_grey():
    g = _t(SDK / "map-google.tsx")
    assert "gm_authFailure" in g and "forge-google-refused" in g


def test_the_route_server_key_never_reaches_a_browser_or_a_log():
    r = _t(RUNTIME / "api-maps-route" / "route.ts")
    assert "GOOGLE_MAPS_SERVER_KEY" in r
    assert "NEXT_PUBLIC_GOOGLE_MAPS_API_KEY" in r  # only to say which map is drawn
    assert "X-Goog-Api-Key" in r
    for line in r.splitlines():
        if "console." in line:
            code = line.split("//")[0]  # a comment may say "never the key"; the code must not print it
            assert "process.env" not in code and "Api-Key" not in code
    # only the signed-in may ask, and they may not hammer it
    assert "whoIs()" in r and "MIN_GAP_MS" in r and "CACHE_MS" in r


def test_the_route_falls_back_in_order_and_says_what_to_enable():
    r = _t(RUNTIME / "api-maps-route" / "route.ts")
    assert r.index("viaGoogle(o, d, mode)") < r.index("viaOsrm(o, d, mode)") < r.index("straight(o, d, mode)")
    assert "Enable the Routes API" in r
    assert "routes.polyline.encodedPolyline" in r  # ask only for the fields used (keeps the bill small)


def test_every_built_app_carries_the_route_and_the_live_map_shows_distance_and_time():
    injector = _t(BACKEND / "services" / "runtime_injector.py")
    assert "api-maps-route" in injector and "api/maps/route" in injector
    t = _t(SDK / "tracking.tsx")
    assert "useRoute(" in t and "data-route-summary" in t and "routeSource(" in t


@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to run the shipped code")
def test_the_road_suite_passes():
    out = subprocess.run(["node", "--experimental-strip-types", "--no-warnings",
                          str(RUNTIME / "__tests__" / "the-road-between-two-places.test.mts")],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]

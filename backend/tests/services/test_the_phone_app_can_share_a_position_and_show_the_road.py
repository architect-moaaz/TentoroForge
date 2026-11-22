"""The phone app can do what the web driver page does: share a position, show a map with the road, the distance left and the
arrival time. The native builder is taught to use it, and every phone project carries it."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services.blueprint.native_projection import native_root, project_fixed_half

BACKEND = Path(__file__).resolve().parents[2]
NATIVE = BACKEND / "templates" / "native"
SDK = NATIVE / "src" / "sdk"
DOC = {"application": {"name": "Rides"}}


def _t(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_the_sdk_exports_the_pieces_a_screen_uses():
    index = _t(SDK / "index.ts")
    for name in ("MapView", "useRoute", "minutesText", "useLiveTrip", "useShareLocation", "ShareLocation", "FleetBeacon", "LiveTrackingMap"):
        assert name in index, name


def test_a_phone_project_carries_the_maps_package_and_the_location_permissions(tmp_path):
    project_fixed_half(DOC, tmp_path)
    root = native_root(tmp_path)
    assert (root / "src" / "sdk" / "tracking.tsx").is_file() and (root / "src" / "sdk" / "map.tsx").is_file()
    assert json.loads(_t(root / "package.json"))["dependencies"]["react-native-maps"]
    expo = json.loads(_t(root / "app.json"))["expo"]
    assert "ACCESS_FINE_LOCATION" in expo["android"]["permissions"]
    assert "while it is open" in expo["ios"]["infoPlist"]["NSLocationWhenInUseUsageDescription"]


def test_the_android_maps_key_comes_from_the_environment_and_is_empty_without_it(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_ANDROID_KEY", raising=False)
    project_fixed_half(DOC, tmp_path / "a")
    assert json.loads(_t(native_root(tmp_path / "a") / "app.json"))["expo"]["android"]["config"]["googleMaps"]["apiKey"] == ""
    monkeypatch.setenv("GOOGLE_MAPS_ANDROID_KEY", "test-key-123")
    project_fixed_half(DOC, tmp_path / "b")
    assert json.loads(_t(native_root(tmp_path / "b") / "app.json"))["expo"]["android"]["config"]["googleMaps"]["apiKey"] == "test-key-123"


def test_the_native_builder_is_taught_when_and_how_to_use_it():
    readme = _t(NATIVE / "README.md")
    assert "Live tracking and maps" in readme
    for name in ("FleetBeacon", "LiveTrackingMap", "ShareLocation", "useRoute"):
        assert name in readme, name
    assert "Do NOT draw a map for a page that only shows an address" in readme
    assert "never add a second" in readme.lower()
    from services.blueprint import native_engineer
    assert "README.md" in Path(native_engineer.__file__).read_text(encoding="utf-8")


def test_a_phone_can_follow_a_trip_without_an_open_line():
    # the phone's fetch cannot stream: the stream route answers once on request, with the same access checks first
    for route in (BACKEND / "templates" / "runtime" / "api-tracking-stream" / "route.ts",):
        text = _t(route)
        assert 'params.get("snapshot") === "1"' in text
        assert text.index("jobFor(entity, id)") < text.index('params.get("snapshot")'), "access is checked before anything is answered"
    assert "snapshot=1" in _t(SDK / "tracking.tsx")


def test_the_phone_never_sends_the_server_key_or_logs_a_position():
    code = _t(SDK / "tracking.tsx") + _t(SDK / "route.ts") + _t(SDK / "tracking-core.ts")
    assert "GOOGLE_MAPS_SERVER_KEY" not in code
    assert "console.log" not in code


@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to run the shipped code")
def test_the_phone_logic_runs_under_node():
    out = subprocess.run(["node", "-e", "process.exit(typeof require('node:module').registerHooks === 'function' ? 0 : 3)"], capture_output=True)
    if out.returncode != 0:
        pytest.skip("the native tests need a node with module.registerHooks (v22.15 or later)")
    run = subprocess.run(["node", "--experimental-strip-types", "--no-warnings",
                          str(NATIVE / "__tests__" / "a-driver-keeps-sharing-and-the-road-counts-down.test.mts")],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]


def test_the_web_picture_of_the_phone_app_gets_a_stand_in_map_instead_of_a_broken_bundle():
    # react-native-maps draws on a phone only; importing it for the web fails the bundle (the Editor's phone preview)
    web = _t(SDK / "map.web.tsx")
    assert "react-native-maps" not in web.replace("react-native-maps draws", "")
    for name in ("export const MapView", "MapPoint", "MapViewProps", "MapHandle"):
        assert name in web, name
    native = _t(SDK / "map.tsx")
    assert 'from "react-native-maps"' in native


# ---- a map that IS the screen -------------------------------------------------------------------------------------

def test_the_kit_has_the_parts_of_a_map_first_screen_and_the_guide_says_when_to_use_them():
    index = _t(NATIVE / "src" / "ui" / "index.ts")
    for name in ("MapScreen", "BottomSheet", "FloatingPanel", "FloatingButton"):
        assert name in index, name
    for f in ("MapScreen.tsx", "BottomSheet.tsx", "Floating.tsx", "MapScreenContext.ts"):
        assert (NATIVE / "src" / "ui" / f).is_file(), f
    readme = _t(NATIVE / "README.md")
    assert "A map that IS the screen" in readme
    assert "ONE STATE, ONE SHEET" in readme and "Do NOT use it for a form, a list or a settings page" in readme


def test_the_phone_and_web_maps_share_one_set_of_types_and_the_sheet_never_dims_the_map():
    assert "map-types" in _t(SDK / "map.tsx") and "map-types" in _t(SDK / "map.web.tsx")
    assert 'height?: number | "fill"' in _t(SDK / "map-types.ts")
    sheet = _t(NATIVE / "src" / "ui" / "BottomSheet.tsx")
    assert "Modal" not in sheet.replace("`Sheet` is the other one", "")   # stays on the screen, does not block what is behind
    assert "settleSheet" in sheet and "dragShown" in sheet and "PanResponder" in sheet


def test_the_screen_follows_the_real_position_and_says_when_it_cannot():
    screen = _t(NATIVE / "src" / "ui" / "MapScreen.tsx")
    assert "useDevicePosition" in screen
    for words in ("Location is blocked", "could not be found", "No new location for a while"):
        assert words in screen, words
    pos = _t(SDK / "position.ts")
    assert "ensureForegroundLocation" in pos and "watchPositionAsync" in pos


def test_two_screens_never_both_put_the_location_question_and_a_parked_phone_is_not_stale():
    # found on a real emulator: a map asked while the home screen's question was up and waited for ever
    perm = _t(SDK / "permission.ts")
    assert "getForegroundPermissionsAsync" in perm and "canAskAgain" in perm and "asking" in perm
    for f in ("position.ts", "tracking.tsx"):
        text = _t(SDK / f)
        assert "ensureForegroundLocation" in text, f
        assert "requestForegroundPermissionsAsync" not in text, f   # asked only through the one helper
    pos = _t(SDK / "position.ts")
    assert "distanceInterval: 0" in pos and "GIVE_UP_MS" in pos      # reports while parked; never "finding" for ever
    assert "getLastKnownPositionAsync()\n" in pos.replace("\r\n", "\n")   # not waited for
    screen = _t(NATIVE / "src" / "ui" / "MapScreen.tsx")
    assert "const high" in screen and "opacity: high ? 0 : 1" in screen   # the buttons step aside when the sheet is tall


def test_an_android_build_carries_the_maps_key_and_says_expo_go_may_stay_blank():
    app = _t(NATIVE / "app.json")
    assert "__GOOGLE_MAPS_ANDROID_KEY__" in app
    assert "Expo Go's own setup does" in _t(SDK / "map.tsx")

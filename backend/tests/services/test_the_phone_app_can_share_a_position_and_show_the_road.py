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

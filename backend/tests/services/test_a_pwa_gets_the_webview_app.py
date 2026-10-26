"""A PWA's phone app is the WebView shell: made on demand, pointing at the live address, built by EAS like any Expo project.

Choosing PWA means the website is what people install; the shell is the small app that opens it inside an app, which can
go in the stores. Full generation makes the shell; an app built any other way did not have one (Habit Pal, 2026-10-21)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import native_build

URL = "https://habit.example.test"


def doc(surface, name="Habit Pal"):
    return {"application": {"name": name}, "mobile": {"surface": surface, "native": {"enabled": False}},
            "designSystem": {"colors": {"primary": "#C96A3B"}}}


def app_json(root):
    return json.loads((Path(root) / "mobile" / "app.json").read_text("utf-8"))["expo"]


def test_a_pwa_choice_builds_the_shell_even_before_it_exists(tmp_path):
    target = native_build.choose_target(tmp_path, doc("pwa_only"))
    assert target is not None and target.kind == "shell" and target.dir == tmp_path / "mobile"
    assert native_build.choose_target(tmp_path, doc("web_pwa")).kind == "shell"


@pytest.mark.parametrize("surface", ["web", None])
def test_a_website_alone_has_no_phone_app_to_build_unless_a_shell_is_already_there(tmp_path, surface):
    assert native_build.choose_target(tmp_path, doc(surface)) is None
    (tmp_path / "mobile").mkdir()
    assert native_build.choose_target(tmp_path, doc(surface)).kind == "shell"


def test_the_shell_is_written_with_the_address_the_brand_and_a_unique_slug(tmp_path):
    root = native_build.prepare_shell(tmp_path, doc("pwa_only"), URL + "/")
    expo = app_json(tmp_path)
    assert root == tmp_path / "mobile"
    assert expo["name"] == "Habit Pal" and expo["extra"]["appUrl"] == URL, "the address, without a trailing slash"
    assert expo["slug"].startswith("habit-pal-") and expo["slug"] != "habit-pal", "unique to this application"
    assert expo["scheme"] == expo["slug"]
    assert expo["android"]["package"] == "com.tentoro.habitpal"
    assert expo["splash"]["backgroundColor"].lower() == "#c96a3b", "the app's own colour"
    assert (tmp_path / "mobile" / "App.tsx").is_file() and (tmp_path / "mobile" / "eas.json").is_file()
    assert (tmp_path / "mobile" / "assets" / "icon.png").stat().st_size > 0


def test_preparing_again_keeps_the_expo_project_and_its_owner(tmp_path):
    native_build.prepare_shell(tmp_path, doc("pwa_only"), URL)
    path = tmp_path / "mobile" / "app.json"
    data = json.loads(path.read_text("utf-8"))
    data["expo"]["owner"] = "tentoro"
    data["expo"]["extra"]["eas"]["projectId"] = "proj-123"
    path.write_text(json.dumps(data), "utf-8")
    native_build.prepare_shell(tmp_path, doc("pwa_only"), URL + "/new")
    expo = app_json(tmp_path)
    assert expo["owner"] == "tentoro" and expo["extra"]["eas"]["projectId"] == "proj-123"
    assert expo["extra"]["appUrl"] == URL + "/new", "the address is the current one"


# ---- the camera is for apps that use it ----------------------------------------------------------------------------------

def test_an_app_without_a_scanner_gets_no_camera_prompt_no_scan_button_and_no_camera_permission(tmp_path):
    native_build.prepare_shell(tmp_path, doc("pwa_only"), URL)
    expo = app_json(tmp_path)
    assert expo["extra"]["camera"] is False
    assert expo["android"]["permissions"] == [], "no camera, microphone or storage permission"
    assert set(expo["android"]["blockedPermissions"]) == {
        "android.permission.CAMERA", "android.permission.RECORD_AUDIO",
        "android.permission.READ_EXTERNAL_STORAGE", "android.permission.WRITE_EXTERNAL_STORAGE"}, "and the library's own are removed"
    plist = expo["ios"]["infoPlist"]
    assert not any(k in plist for k in ("NSCameraUsageDescription", "NSMicrophoneUsageDescription", "NSPhotoLibraryUsageDescription"))


def test_an_app_with_a_barcode_scanner_keeps_the_camera(tmp_path):
    d = doc("pwa_only")
    d["pageCode"] = [{"page": "PAGE-001", "view": "import { BarcodeScanner } from '@/sdk/client';"}]
    assert native_build.uses_camera(d) is True
    native_build.prepare_shell(tmp_path, d, URL)
    expo = app_json(tmp_path)
    assert expo["extra"]["camera"] is True and "CAMERA" in expo["android"]["permissions"]
    assert "blockedPermissions" not in expo["android"], "nothing is removed from an app that scans"
    assert "NSCameraUsageDescription" in expo["ios"]["infoPlist"]


def test_a_capture_page_counts_as_using_the_camera():
    assert native_build.uses_camera({"pages": [{"id": "PAGE-001", "pattern": "capture"}]}) is True
    assert native_build.uses_camera({"pages": [{"id": "PAGE-001", "pattern": "entity_list"}]}) is False


def test_the_shell_shows_its_scan_button_and_camera_prompt_only_when_asked_to_and_never_sticks_a_spinner_on():
    app = (Path(__file__).resolve().parents[2] / "templates" / "mobile" / "App.tsx").read_text(encoding="utf-8")
    assert "Constants.expoConfig?.extra?.camera !== false" in app, "absent means yes: older shells keep their camera"
    assert "{CAMERA_ENABLED && (" in app and app.count("{CAMERA_ENABLED && (") == 2, "the Scan button and the scanner"
    assert "CAMERA_ENABLED && camPermission" in app, "the start-up prompt"
    assert "setLoading" not in app, "no loader overlay that waits for a 'finished' that may never come"
    assert "setTimeout(() => setProgress(1), 10000)" in app, "and a progress bar gives up after ten seconds"

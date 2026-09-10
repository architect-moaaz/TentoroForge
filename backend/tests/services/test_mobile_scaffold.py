"""Tests for services.mobile_scaffold — MOBILE-A anchor.

Covers:
  * Placeholder substitution — no ``__…__`` tokens leak through.
  * Idempotency — second run doesn't corrupt prior state.
  * eas-project-id preservation — once the user runs `eas init`, that
    id survives every subsequent scaffold.
  * Brand-color derivation from design_spec.json + graceful fallback.
  * Placeholder PNGs are valid, matching-dimension, matching-color.
  * app.json is JSON-valid + the deployed URL lands in expo.extra.appUrl.
"""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest

from services.mobile_scaffold import (
    _DEFAULT_BRAND_HEX,
    _normalize_hex,
    _slugify,
    scaffold_mobile,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

def _make_project(tmp_path: Path, *, plan: dict | None = None,
                  design_spec: dict | None = None) -> Path:
    """Minimal fake generated-app folder."""
    out = tmp_path / "app"
    out.mkdir()
    if plan is not None:
        (out / "contracts").mkdir()
        (out / "contracts" / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    if design_spec is not None:
        (out / "design_spec.json").write_text(json.dumps(design_spec), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# Substitution                                                                 #
# --------------------------------------------------------------------------- #

class TestSubstitution:
    def test_app_name_slug_bundle_url_land_in_files(self, tmp_path):
        out = _make_project(tmp_path)
        scaffold_mobile(
            str(out),
            app_name="Recipe Collection",
            deployed_url="https://recipes.tentoro.ai",
            brand_hex="#FF5722",
        )
        # app.json — every substitution shows up.
        app_json = json.loads((out / "mobile" / "app.json").read_text(encoding="utf-8"))
        expo = app_json["expo"]
        assert expo["name"] == "Recipe Collection"
        assert expo["slug"] == "recipe-collection"
        assert expo["ios"]["bundleIdentifier"] == "com.tentoro.recipecollection"
        assert expo["android"]["package"] == "com.tentoro.recipecollection"
        assert expo["extra"]["appUrl"] == "https://recipes.tentoro.ai"
        assert expo["splash"]["backgroundColor"] == "#FF5722"

    def test_no_placeholders_leak_through(self, tmp_path):
        """A future refactor that renames a placeholder must be caught —
        placeholder text remaining in any written file is a bug."""
        out = _make_project(tmp_path)
        scaffold_mobile(str(out), app_name="X", deployed_url="https://x.io")
        mobile = out / "mobile"
        for path in mobile.rglob("*"):
            if path.is_dir() or path.suffix == ".png":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in ("__APP_NAME__", "__APP_SLUG__", "__BUNDLE_ID__",
                          "__BRAND_COLOR__", "__DEPLOYED_URL__"):
                assert token not in text, f"{token} left in {path.name}"

    def test_empty_deployed_url_still_writes_valid_config(self, tmp_path):
        """Publish may not have run yet — app.json must stay valid so
        `eas build` doesn't crash on parse."""
        out = _make_project(tmp_path)
        scaffold_mobile(str(out), app_name="X", deployed_url="")
        app_json = json.loads((out / "mobile" / "app.json").read_text(encoding="utf-8"))
        assert app_json["expo"]["extra"]["appUrl"] == ""


# --------------------------------------------------------------------------- #
# Idempotency + prior eas-project-id preservation                              #
# --------------------------------------------------------------------------- #

class TestIdempotency:
    def test_second_run_is_stable(self, tmp_path):
        out = _make_project(tmp_path)
        scaffold_mobile(str(out), app_name="X", deployed_url="https://x.io")
        first = (out / "mobile" / "app.json").read_text(encoding="utf-8")
        scaffold_mobile(str(out), app_name="X", deployed_url="https://x.io")
        second = (out / "mobile" / "app.json").read_text(encoding="utf-8")
        assert first == second

    def test_rebrand_updates_color_and_url(self, tmp_path):
        """The point of re-running is to pick up new brand / new URL."""
        out = _make_project(tmp_path)
        scaffold_mobile(str(out), app_name="X", deployed_url="https://old.io",
                        brand_hex="#000000")
        scaffold_mobile(str(out), app_name="X", deployed_url="https://new.io",
                        brand_hex="#FFFFFF")
        app_json = json.loads((out / "mobile" / "app.json").read_text(encoding="utf-8"))
        assert app_json["expo"]["extra"]["appUrl"] == "https://new.io"
        assert app_json["expo"]["splash"]["backgroundColor"] == "#FFFFFF"

    def test_prior_eas_project_id_survives(self, tmp_path):
        """After `eas init`, app.json has a real projectId — future
        re-runs must NOT wipe it (would break the EAS project link)."""
        out = _make_project(tmp_path)
        # First scaffold, then simulate `eas init` writing a real id.
        scaffold_mobile(str(out), app_name="X", deployed_url="https://x.io")
        app_json_path = out / "mobile" / "app.json"
        data = json.loads(app_json_path.read_text(encoding="utf-8"))
        data["expo"]["extra"]["eas"]["projectId"] = "abc-123-def-456"
        app_json_path.write_text(json.dumps(data), encoding="utf-8")

        # Re-scaffold.
        scaffold_mobile(str(out), app_name="X", deployed_url="https://x.io")
        after = json.loads(app_json_path.read_text(encoding="utf-8"))
        assert after["expo"]["extra"]["eas"]["projectId"] == "abc-123-def-456"


# --------------------------------------------------------------------------- #
# Brand color derivation                                                       #
# --------------------------------------------------------------------------- #

class TestBrandDerivation:
    def test_reads_design_spec_color_palette(self, tmp_path):
        out = _make_project(
            tmp_path,
            design_spec={"colorPalette": {"primary": "#EF4444"}},
        )
        scaffold_mobile(str(out), app_name="X", deployed_url="")
        app_json = json.loads((out / "mobile" / "app.json").read_text(encoding="utf-8"))
        assert app_json["expo"]["splash"]["backgroundColor"] == "#EF4444"

    def test_falls_back_to_default_when_no_spec(self, tmp_path):
        out = _make_project(tmp_path)  # no design_spec.json
        scaffold_mobile(str(out), app_name="X", deployed_url="")
        app_json = json.loads((out / "mobile" / "app.json").read_text(encoding="utf-8"))
        assert app_json["expo"]["splash"]["backgroundColor"] == _DEFAULT_BRAND_HEX

    def test_explicit_brand_wins_over_spec(self, tmp_path):
        """Caller override beats design_spec."""
        out = _make_project(
            tmp_path,
            design_spec={"colorPalette": {"primary": "#111111"}},
        )
        scaffold_mobile(str(out), app_name="X", deployed_url="",
                        brand_hex="#22FF22")
        app_json = json.loads((out / "mobile" / "app.json").read_text(encoding="utf-8"))
        assert app_json["expo"]["splash"]["backgroundColor"] == "#22FF22"

    def test_normalize_hex_short_form(self):
        assert _normalize_hex("#fff") == "#FFFFFF"
        assert _normalize_hex("abc") == "#AABBCC"

    def test_normalize_hex_rejects_junk(self):
        assert _normalize_hex("not-a-color") == _DEFAULT_BRAND_HEX
        assert _normalize_hex("") == _DEFAULT_BRAND_HEX
        assert _normalize_hex(None) == _DEFAULT_BRAND_HEX


# --------------------------------------------------------------------------- #
# App-name inference                                                           #
# --------------------------------------------------------------------------- #

class TestAppNameInference:
    def test_reads_plan_name(self, tmp_path):
        out = _make_project(tmp_path, plan={"name": "Planters Nursery"})
        scaffold_mobile(str(out), deployed_url="")
        app_json = json.loads((out / "mobile" / "app.json").read_text(encoding="utf-8"))
        assert app_json["expo"]["name"] == "Planters Nursery"
        assert app_json["expo"]["slug"] == "planters-nursery"

    def test_falls_back_to_module_name(self, tmp_path):
        out = _make_project(tmp_path, plan={"module_name": "recipes"})
        scaffold_mobile(str(out), deployed_url="")
        app_json = json.loads((out / "mobile" / "app.json").read_text(encoding="utf-8"))
        assert app_json["expo"]["name"] == "recipes"


# --------------------------------------------------------------------------- #
# Placeholder PNGs                                                             #
# --------------------------------------------------------------------------- #

class TestPlaceholderPngs:
    """These files must be valid PNGs with matching dimensions — EAS
    build will reject app.json if the icon can't be parsed."""

    def test_all_four_asset_files_written(self, tmp_path):
        out = _make_project(tmp_path)
        scaffold_mobile(str(out), app_name="X", deployed_url="")
        assets = out / "mobile" / "assets"
        for name in ("icon.png", "adaptive-icon.png",
                     "splash.png", "favicon.png"):
            assert (assets / name).is_file(), f"{name} missing"

    def test_pngs_have_valid_signature_and_ihdr(self, tmp_path):
        out = _make_project(tmp_path)
        scaffold_mobile(str(out), app_name="X", deployed_url="")
        assets = out / "mobile" / "assets"
        for name, w, h in [
            ("icon.png", 1024, 1024),
            ("adaptive-icon.png", 1024, 1024),
            ("splash.png", 1242, 2436),
            ("favicon.png", 48, 48),
        ]:
            data = (assets / name).read_bytes()
            # PNG signature.
            assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{name} bad signature"
            # IHDR chunk: 4 bytes length, "IHDR", 13 bytes data, 4 bytes CRC.
            assert data[12:16] == b"IHDR"
            ihdr_w, ihdr_h = struct.unpack(">II", data[16:24])
            assert ihdr_w == w, f"{name} width {ihdr_w} != {w}"
            assert ihdr_h == h, f"{name} height {ihdr_h} != {h}"


# --------------------------------------------------------------------------- #
# Small helpers                                                                #
# --------------------------------------------------------------------------- #

class TestSlugify:
    @pytest.mark.parametrize("name, expected", [
        ("Planters Nursery Management", "planters-nursery-management"),
        ("Recipe Collection", "recipe-collection"),
        ("simple", "simple"),
        ("With!Special#Chars", "with-special-chars"),
        ("   trim   ", "trim"),
        ("", "app"),  # empty string falls back to a safe default
    ])
    def test_slugify_normalizes_names(self, name, expected):
        assert _slugify(name) == expected


class TestBundleIdShape:
    def test_default_bundle_id_uses_slug(self, tmp_path):
        out = _make_project(tmp_path)
        scaffold_mobile(str(out), app_name="Recipe Collection",
                        deployed_url="")
        app_json = json.loads((out / "mobile" / "app.json").read_text(encoding="utf-8"))
        assert app_json["expo"]["ios"]["bundleIdentifier"] == "com.tentoro.recipecollection"

    def test_explicit_bundle_id_overrides(self, tmp_path):
        out = _make_project(tmp_path)
        scaffold_mobile(str(out), app_name="X", deployed_url="",
                        bundle_id="com.acme.customapp")
        app_json = json.loads((out / "mobile" / "app.json").read_text(encoding="utf-8"))
        assert app_json["expo"]["ios"]["bundleIdentifier"] == "com.acme.customapp"
        assert app_json["expo"]["android"]["package"] == "com.acme.customapp"


class TestMobileTemplateCameraFixes:
    """Back-ported dxlc5m31 fixes must stay in the template source."""

    def _template(self):
        from pathlib import Path
        return (Path(__file__).resolve().parents[2] / "templates" / "mobile"
                / "App.tsx").read_text(encoding="utf-8")

    def test_no_scrollview_around_webview(self):
        # A WebView nested in a ScrollView breaks Android's video-surface
        # composition — camera preview renders black.
        src = self._template()
        assert "<ScrollView" not in src
        assert "pullToRefreshEnabled" in src  # refresh still covered

    def test_startup_camera_permission_request(self):
        # WebView auto-grant covers only the web layer; the OS CAMERA
        # permission must be requested by the app itself at startup.
        src = self._template()
        assert "canAskAgain" in src
        assert src.count("requestCamPermission()") >= 2  # startup + scanner

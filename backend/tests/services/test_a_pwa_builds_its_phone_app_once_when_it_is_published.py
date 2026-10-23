"""A PWA's Android app is built for the person once, when the app first reaches production.

The shell opens the live site, so a republish changes nothing inside it and must not spend a build. An app that is not a
PWA is never built for."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.mobile_autobuild import decide

URL = "https://habit.example.test"


def test_a_pwa_with_an_address_and_no_build_is_built():
    assert decide("pwa_only", URL, [], "") == ""
    assert decide("web_pwa", URL, [], "") == ""


@pytest.mark.parametrize("surface", [None, "web", "web_native", "native_only"])
def test_anything_that_is_not_a_pwa_is_left_alone(surface):
    assert "not the WebView shell" in decide(surface, URL, [], "")


def test_nothing_is_built_before_there_is_an_address():
    assert "no published address" in decide("pwa_only", "", [], "")


def test_a_build_already_running_is_not_started_again():
    assert "already being built" in decide("pwa_only", URL, [("preview", "in_progress")], "")
    assert "already being built" in decide("pwa_only", URL, [("preview", "pending"), ("preview", "failed")], "")


def test_a_republish_to_the_same_address_does_not_spend_another_build():
    assert "already built" in decide("pwa_only", URL, [("preview", "completed")], URL + "/")


def test_a_new_address_is_built_for_and_a_failed_build_is_tried_again():
    assert decide("pwa_only", "https://new.example.test", [("preview", "completed")], URL) == ""
    assert decide("pwa_only", URL, [("preview", "failed")], URL) == ""


def test_a_store_build_does_not_stand_in_for_the_preview_app():
    assert decide("pwa_only", URL, [("production", "completed")], URL) == ""


def test_the_publish_starts_it_only_when_the_app_went_live_on_production():
    text = (Path(__file__).resolve().parents[2] / "routers" / "deployments.py").read_text(encoding="utf-8")
    assert "if went_live and side == envs.PRODUCTION:" in text
    assert "mobile_autobuild.start_phone_app(project.id, user.id)" in text

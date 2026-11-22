"""A delivery under way shares its position by itself; the driver is never asked to press a button.

`ShareLocation` is a Start / End button, off until pressed. On Zomato's active delivery the driver was never told to press it, so
the customer's tracking page said "Waiting for the driver to share their location…" for the whole trip and the admin saw nothing
(2026-11-16). `TripBeacon` sends the trip's position while it is on screen, and the native writer is taught to use it.
"""
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
NATIVE = BACKEND / "templates" / "native"
TRACKING = (NATIVE / "src" / "sdk" / "tracking.tsx").read_text(encoding="utf-8")


def test_the_phone_kit_has_a_beacon_that_shares_a_trip_with_no_button():
    start = TRACKING.index("export function TripBeacon")
    body = TRACKING[start:TRACKING.index("export type LiveTrackingMapProps")]
    assert "useShareLocation(entity, trip, true, stage)" in body      # on from the first render
    assert "Button" not in body                                       # nothing to press


def test_the_beacon_is_exported_for_screens():
    assert "TripBeacon" in (NATIVE / "src" / "sdk" / "index.ts").read_text(encoding="utf-8")


def test_the_native_writer_is_told_to_use_it_for_a_job_under_way():
    from services.blueprint.native_engineer import MAP_FIRST_RULES
    assert "TripBeacon" in MAP_FIRST_RULES and "NEVER a \"Start sharing\" button" in MAP_FIRST_RULES


def test_the_kit_guide_says_which_to_use_when():
    readme = (NATIVE / "README.md").read_text(encoding="utf-8")
    assert "<TripBeacon" in readme and "USE THIS for the mover's" in readme

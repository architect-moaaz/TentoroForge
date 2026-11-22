"""The phone's map can be Google's or a free one, by one setting; a build with no Google key does not close the app.

Found trying the free option on Zomato's phone app (2026-11-16): tile.openstreetmap.org answers an app that does not identify itself
with "Access blocked" (403), and CARTO's raster tiles stamp "API KEY REQUIRED" across the map, so the default free tiles are Esri's
public street map; `EXPO_PUBLIC_MAP_TILES` names a tile service for a shipped app.
"""
from pathlib import Path

MAP = (Path(__file__).resolve().parents[2] / "templates" / "native" / "src" / "sdk" / "map.tsx").read_text(encoding="utf-8")


def test_one_setting_chooses_the_free_map():
    assert 'process.env.EXPO_PUBLIC_MAP_PROVIDER === "openfreemap"' in MAP
    assert 'mapType={FREE_MAP ? "none" : "standard"}' in MAP        # Google's own tiles are not drawn
    assert "<UrlTile" in MAP and "FREE_MAP ?" in MAP


def test_the_free_tiles_are_ones_that_work_for_an_app():
    default = MAP[MAP.index("const FREE_TILES"):].splitlines()[0]
    assert "tile.openstreetmap.org" not in default                  # refuses an app with no identifying header
    assert "cartocdn" not in default                                # stamps "API KEY REQUIRED" on every tile
    assert "arcgisonline.com" in default and "EXPO_PUBLIC_MAP_TILES" in default


def test_the_map_says_whose_tiles_they_are():
    assert "Tiles © Esri" in MAP


def test_google_stays_the_default_and_a_build_without_a_key_still_does_not_mount_it():
    assert 'EXPO_PUBLIC_MAP_PROVIDER === "openfreemap"' in MAP and "ANDROID_MAPS_KEY_SET" in MAP

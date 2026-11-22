"""One Google Maps key is set once on the Settings page and reaches every app under the three names it is read as
(services/node_config_specs.py, services/env_writer.py, routers/deployments.py).

What matters: ONE box (not three); the names the apps and the phone project READ are the ones the one key is handed to (a
renamed name on one side would leave maps silently on the free map for ever); the key is hidden once saved; the page says which
Google APIs to turn on; and both the built app's .env.local and a published app get all three names."""
from __future__ import annotations

from pathlib import Path

from services.node_config_specs import KEY_ALIASES, alias_names, all_providers, keys_for_provider, platform_only_keys, with_aliases

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
READ_AS = {"NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "GOOGLE_MAPS_SERVER_KEY", "GOOGLE_MAPS_ANDROID_KEY"}


def test_the_page_offers_one_box():
    assert "google_maps" in all_providers()
    assert [e.key for e in keys_for_provider("google_maps")] == ["GOOGLE_MAPS_API_KEY"]


def test_the_one_key_is_handed_to_every_name_the_code_reads():
    assert set(KEY_ALIASES["GOOGLE_MAPS_API_KEY"]) == READ_AS
    route = (BACKEND / "templates" / "runtime" / "api-maps-route" / "route.ts").read_text(encoding="utf-8")
    assert "NEXT_PUBLIC_GOOGLE_MAPS_API_KEY" in route and "GOOGLE_MAPS_SERVER_KEY" in route
    phone = (BACKEND / "services" / "blueprint" / "native_projection.py").read_text(encoding="utf-8")
    assert "GOOGLE_MAPS_ANDROID_KEY" in phone
    got = with_aliases({"GOOGLE_MAPS_API_KEY": "k", "OTHER": "o"})
    assert all(got[n] == "k" for n in READ_AS) and got["OTHER"] == "o"
    assert alias_names() == READ_AS


def test_no_key_means_no_names():
    assert not (READ_AS & set(with_aliases({"OTHER": "o"}))), "an unset key writes nothing: the free map takes over"
    assert not (READ_AS & set(with_aliases({"GOOGLE_MAPS_API_KEY": ""})))


def test_a_saved_key_is_never_shown_again_and_is_not_required():
    (e,) = keys_for_provider("google_maps")
    assert e.kind == "password" and not e.required


def test_the_page_says_which_google_apis_to_turn_on():
    (e,) = keys_for_provider("google_maps")
    for api in ("Maps JavaScript", "Routes", "Directions", "Geocoding", "Maps SDK for Android"):
        assert api in e.label, api
    card = (ROOT / "frontend" / "src" / "app" / "org" / "[orgId]" / "settings" / "integrations" / "catalogue.ts").read_text(encoding="utf-8")
    assert "google_maps:" in card and "One key does it all" in card and "Routes API" in card


def test_a_built_and_a_published_app_both_get_the_names():
    writer = (BACKEND / "services" / "env_writer.py").read_text(encoding="utf-8")
    assert "with_aliases(desired)" in writer and "alias_names()" in writer
    publish = (BACKEND / "routers" / "deployments.py").read_text(encoding="utf-8")
    assert "with_aliases(out)" in publish
    assert "GOOGLE_MAPS_API_KEY" not in platform_only_keys()

"""Smith asks for the Google Maps key when the plan has a map (services/smith/maps_key.py).

What matters: it asks only when the plan has a map and no key is set; once; with the box and the list of Google APIs to turn on;
the box is the one Settings stores (same provider and key, so a pasted key is the one the apps get); the key never appears in
the words; the ask never stops a build; and the panel's "saved" / "free map" replies are recognised only after the ask."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.node_config_specs import keys_for_provider
from services.smith import maps_key as mk

BACKEND = Path(__file__).resolve().parents[2]
ZONES = {"geofencing": {"enabled": True, "zones": []}}
PHONE = {"mobile": {"mapFirstRoles": ["Driver"]}}
SCREEN = {"pages": [{"name": "Live", "sections": [{"name": "Where", "shows": "map"}]}]}
PLAIN = {"pages": [{"name": "Recipes", "sections": [{"name": "All", "shows": "list"}]}]}


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    for n in ("GOOGLE_MAPS_API_KEY", "NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "GOOGLE_MAPS_SERVER_KEY"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setattr("services.figma.integrations.config_for", lambda *_a, **_k: {})


@pytest.mark.parametrize("doc", [ZONES, PHONE, SCREEN])
def test_a_plan_with_a_map_has_a_reason(doc):
    assert mk.why_maps(doc)


@pytest.mark.parametrize("doc", [PLAIN, {}, {"geofencing": {"enabled": False}}])
def test_a_plan_without_a_map_is_not_asked(doc, tmp_path):
    assert not mk.why_maps(doc)
    assert mk.ask(doc, tmp_path) is None


def test_the_ask_has_the_box_the_apis_and_a_way_out(tmp_path):
    msg = mk.ask(SCREEN, tmp_path)
    assert msg and msg["secret"]["provider"] == "google_maps" and msg["secret"]["key"] == "GOOGLE_MAPS_API_KEY"
    for api in mk.APIS:
        assert api in msg["text"], api
    assert "never written into this conversation" in msg["text"]
    assert mk.SKIP in msg["options"] and msg["status"] == "asked"


def test_the_box_stores_the_key_settings_has(tmp_path):
    """A different key name here would save a value no app ever reads."""
    msg = mk.ask(ZONES, tmp_path)
    assert [e.key for e in keys_for_provider(msg["secret"]["provider"])] == [msg["secret"]["key"]]


def test_it_asks_once(tmp_path):
    assert mk.ask(ZONES, tmp_path)
    assert mk.ask(ZONES, tmp_path) is None


def test_a_key_already_set_is_not_asked_for(tmp_path, monkeypatch):
    monkeypatch.setattr("services.figma.integrations.config_for", lambda *_a, **_k: {"GOOGLE_MAPS_API_KEY": "x"})
    assert mk.key_set(tmp_path) and mk.ask(ZONES, tmp_path) is None


def test_a_server_that_has_its_own_key_is_not_asked_either(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_SERVER_KEY", "x")
    assert mk.ask(ZONES, tmp_path) is None


def test_a_lookup_that_fails_asks_rather_than_blocks(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("db down")
    monkeypatch.setattr("services.figma.integrations.config_for", boom)
    assert mk.ask(ZONES, tmp_path)


def test_saved_and_free_map_are_recognised_only_after_the_ask():
    ask = ("smith", mk.TEXT.format(why="a screen shows records on a map"))
    later = [ask, ("smith", "Building the pages…"), ("smith", "Done.")]   # the build carried on after the ask
    assert mk.key_saved_in(mk.SAVED, later) and mk.skipped_in(mk.SKIP, later)
    other = [("smith", "Anything else?")]
    assert not mk.key_saved_in(mk.SAVED, other) and not mk.skipped_in(mk.SKIP, other)
    assert not mk.key_saved_in("hello", later) and not mk.key_saved_in(mk.SAVED, [])


def test_the_chat_asks_without_stopping_the_build_and_answers_the_panel():
    src = (BACKEND / "routers" / "blueprint_generate.py").read_text(encoding="utf-8")
    gate = src.index("maps_key.ask(svc.doc, output_dir)")
    assert src.index("ui_designer.gate(svc.doc, output_dir)", src.index("_add_to_the_brief(svc, description)") - 600) < gate
    around = src[gate - 300: gate + 400]
    assert "return" not in around.split("emit(")[0], "the ask is a suggestion, never a stop"
    assert "maps_key.key_saved_in(req.message, _history)" in src and "maps_key.skipped_in(req.message, _history)" in src

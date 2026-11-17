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


def test_the_ask_comes_with_the_first_plan_from_what_is_saved(tmp_path):
    """Before any definition exists the only signs of a map are the saved plans: the zones plan and a map-first role."""
    from services.blueprint import geofence_plan

    assert mk.ask_after_turn(tmp_path) is None, "nothing saved, nothing to ask"
    geofence_plan.write(tmp_path, geofence_plan.analyse("Delivery app. Drivers deliver orders. Alert the customer when the driver is within 300 m."))
    msg = mk.ask_after_turn(tmp_path)
    assert msg and msg["secret"]["key"] == "GOOGLE_MAPS_API_KEY" and "zones" in msg["text"]
    assert mk.ask_after_turn(tmp_path) is None, "once"


def test_a_map_first_role_asks_too(tmp_path, monkeypatch):
    monkeypatch.setattr("services.blueprint.platform_plan.map_first_roles", lambda _d: ["Driver"])
    msg = mk.ask_after_turn(tmp_path)
    assert msg and "phone app" in msg["text"]


def test_the_saved_definition_counts_as_well(tmp_path):
    import json
    cur = tmp_path / ".forge" / "blueprint" / "current.json"
    cur.parent.mkdir(parents=True)
    cur.write_text(json.dumps(SCREEN), encoding="utf-8")
    assert mk.ask_after_turn(tmp_path)


def test_a_failing_read_never_breaks_a_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(mk, "ask", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert mk.ask_after_turn(tmp_path) is None


def test_the_chat_asks_after_each_answer_the_build_gate_never_stops_and_the_panel_is_answered_first():
    src = (BACKEND / "routers" / "blueprint_generate.py").read_text(encoding="utf-8")
    assert src.count("maps_key.ask_after_turn(output_dir, ") == 2, "after the answer before a definition and after it"
    gate = src.index("maps_key.ask(svc.doc, output_dir)")
    around = src[gate - 300: gate + 400]
    assert "return" not in around.split("emit(")[0], "the ask is a suggestion, never a stop"
    saved = src.index("maps_key.key_saved_in(req.message, _chat_so_far)")
    assert saved < src.index("# DEFECT-STATUS-VERB"), "the panel's words are met at the start of the turn, with no definition needed"
    assert saved < src.index("maps_key.ask_after_turn(output_dir, ")


def test_the_very_first_answer_asks_from_the_brief_alone(tmp_path):
    """Smith's first answer is the plan question, before anything is saved: only the typed brief shows a map is coming."""
    brief = "Food delivery app. Drivers share live GPS. Admin sees all drivers on a live map."
    msg = mk.ask_after_turn(tmp_path, brief)
    assert msg and msg["secret"]["key"] == "GOOGLE_MAPS_API_KEY"


@pytest.mark.parametrize("brief", ["A recipe app with a roadmap page", "A todo app for a family", "", "A site map generator"])
def test_a_brief_without_a_map_does_not_ask(brief, tmp_path):
    assert mk.ask_after_turn(tmp_path, brief) is None


def test_the_chat_reads_the_brief_when_it_asks():
    src = (BACKEND / "routers" / "blueprint_generate.py").read_text(encoding="utf-8")
    assert src.count("maps_key.ask_after_turn(output_dir, _brief_from(req.history, req.message))") == 2

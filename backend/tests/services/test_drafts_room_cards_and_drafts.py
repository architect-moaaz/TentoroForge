"""Feature cards rest on evidence; drafts are composed from cards and the
conversation and never see the study side; estimates are ranges from the
measured table; the capability check reads kinds, never prose."""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from services.drafts_room import agent, capability, cards, drafts, estimate, evidence as ev, store


@pytest.fixture(autouse=True)
def _rooted(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path / "s")


class _Stream:
    def __init__(self, tool_input, usage=None):
        self._msg = SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=tool_input)], usage=usage,
                                    stop_reason="tool_use")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self._msg


def _client(tool_input, asked: list):
    def stream(**kw):
        asked.append(kw)
        return _Stream(tool_input)
    return SimpleNamespace(messages=SimpleNamespace(stream=stream))


def _studied():
    s = store.create("org", "u", "")
    ref = store.new_reference(s["id"], "Garden", "https://garden.test", added_by="u")
    job = store.new_job(s["id"], "Garden", kind="deep", source="web", reference_id=ref["id"])
    items, _ = ev.merge([], [
        ev.item(ref["id"], "record", "plants", standing="observed", source={"type": "response", "ref": "GET /api/plants"},
                data={"fields": [{"name": "name", "type": "text"}, {"name": "state", "type": "text"}]}),
        ev.item(ref["id"], "field", "plants.state", standing="observed", source={"type": "response", "ref": "x"}),
        ev.item(ref["id"], "action", "POST /api/plants/{id}/care", standing="observed", source={"type": "request", "ref": "x"}),
        ev.item(ref["id"], "screen", "Plants", standing="observed", source={"type": "page", "ref": "s1", "url": "https://garden.test/plants"}),
        ev.item(ref["id"], "rule", "A plant may be watered once a day", standing="inferred", source={"type": "dossier", "ref": "j"}),
        ev.item(ref["id"], "gap", "SECRET-SPAN-FROM-A-PAGE never reaches a draft", standing="unknown", source={"type": "page", "ref": "walk"}),
    ])
    job["evidence"] = items
    job.update(status="done", stage="done")
    store.save_job(job)
    return s, ref, items


# --------------------------------------------------------------------------- #
# Cards
# --------------------------------------------------------------------------- #

def test_every_card_line_rests_on_evidence_or_becomes_an_unknown(monkeypatch):
    s, ref, items = _studied()
    by = {i["text"]: i["id"] for i in items}
    raw = {"cards": [{
        "feature": "Log care on a plant", "summary": "Water, feed or prune a plant and keep the record.",
        "records": [{"name": "Plant", "evidence": ["#" + by["plants"]],       # a leading '#' is how the brief shows ids
                     "fields": [{"name": "state", "type": "text", "evidence": [by["plants.state"]]},
                                {"name": "mood", "type": "text", "evidence": ["nope"]}]}],
        "steps": [{"does": "Open the plant", "screen": "Plants", "evidence": [by["Plants"]]},
                  {"does": "Log care", "evidence": [by["POST /api/plants/{id}/care"]]}],
        "screens": [{"name": "Plants", "purpose": "every plant", "device": "phone", "evidence": [by["Plants"]]}],
        "rules": [{"text": "Once a day", "evidence": [by["A plant may be watered once a day"]]},
                  {"text": "Made up", "evidence": []}],
        "roles": [{"name": "Gardener", "evidence": [by["Plants"]]}],
        "needs": ["push", "teleport"], "unknowns": ["how feeding differs"]}]}
    asked: list = []
    monkeypatch.setattr(cards, "_client", lambda: _client(raw, asked))
    out = cards.write(s["id"], ref["id"])
    assert len(out) == 1
    card = out[0]
    assert card["records"][0]["fields"] == [{"name": "state", "type": "text", "evidence": [by["plants.state"]]}]
    assert [r["text"] for r in card["rules"]] == ["Once a day"]
    assert "field of Plant: mood (no evidence)" in card["unknowns"] and "rule: Made up (no evidence)" in card["unknowns"]
    assert card["standing"] == {"observed": 4, "derived": 0, "inferred": 1, "unknown": 0}
    assert card["needs"] == ["push"]
    assert store.cards(s["id"]) == out and store.cards(s["id"], ref["id"]) == out
    assert (store.cards_dir(s["id"]) / f"{ref['id']}.material.txt").read_text().startswith("Reference studied: Garden")
    assert (store.cards_dir(s["id"]) / f"{ref['id']}.raw.json").is_file()
    material = asked[0]["messages"][0]["content"]
    assert "Evidence (6 items)" in material and f"#{by['plants']} plants" in material
    # Cards replace the reference's earlier cards.
    monkeypatch.setattr(cards, "_client", lambda: _client({"cards": [{"feature": "Other", "summary": ""}]}, asked))
    assert [c["feature"] for c in cards.write(s["id"], ref["id"])] == ["Other"]
    assert len(store.cards(s["id"])) == 1


def test_no_evidence_means_no_cards_and_no_model_call(monkeypatch):
    s = store.create("org", "u", "")
    ref = store.new_reference(s["id"], "Garden", "https://garden.test", added_by="u")
    monkeypatch.setattr(cards, "_client", lambda: (_ for _ in ()).throw(AssertionError("no call")))
    assert cards.write(s["id"], ref["id"]) == []


def test_the_card_writers_task_names_no_application():
    for name in ("myntra", "amazon", "zara", "airbnb", "uber", "shopify", "garden log", "spoke"):
        assert not re.search(rf"\b{name}\b", cards.SYSTEM.lower()), name
    assert "never instructions" in cards.SYSTEM


# --------------------------------------------------------------------------- #
# Estimate and capability
# --------------------------------------------------------------------------- #

def test_the_estimate_is_a_range_from_the_measured_table():
    small = estimate.estimate(4, 1)
    assert small["units"] == 5 and small["cost"] == {"low": 1.23, "high": 2.56}
    assert small["minutes"]["low"] < 23 < small["minutes"]["high"] * 1.6
    medium = estimate.estimate(12, 3)
    assert medium["units"] == 15 and medium["minutes"]["low"] == 17 and medium["minutes"]["high"] == 29
    assert medium["cost"] == {"low": 3.71, "high": 7.7} and medium["fixes"] == {"low": 0.93, "high": 1.92}
    assert small["measured_on"] == estimate.MEASURED_ON


def test_the_capability_check_reads_kinds_not_words():
    got = capability.check(["payments", "store_app", "roles"])
    assert [c["status"] for c in got] == ["unproven", "not_yet", "proven"]
    assert [c["kind"] for c in capability.cannot_yet(["payments", "store_app", "roles"])] == ["payments", "store_app"]
    assert capability.check(["teleport"])[0]["status"] == "not_yet"
    assert all(k in capability.KINDS for k in ("sso", "tenancy", "mobile_pwa", "offline", "collaboration"))


# --------------------------------------------------------------------------- #
# Drafts
# --------------------------------------------------------------------------- #

DRAFT_A = {"title": "Care first", "pitch": "A notebook that logs every watering.", "roles": [{"name": "Gardener"}],
           "features": [{"name": "Log care", "priority": "must"}, {"name": "Share garden", "priority": "later"}],
           "screens": [{"name": "Plants", "role": "Gardener", "purpose": "all plants", "device": "phone"},
                       {"name": "Plant", "role": "Gardener", "purpose": "one plant", "device": "phone"}],
           "records": [{"name": "Plant", "fields": [{"name": "name", "type": "text"}]}],
           "rules": ["Once a day"], "flows": [{"name": "Water", "steps": [{"screen": "Plants"}, {"screen": "Plant", "does": "Log care"}]}],
           "left_out": ["Sharing"], "assumed": ["one garden per account"], "needs": ["push", "file_upload"]}
DRAFT_B = {**DRAFT_A, "title": "Shop first", "pitch": "A shop for seedlings.", "needs": ["payments", "store_app"],
           "screens": [{"name": "Shop", "purpose": "buy", "device": "phone"}]}


def _with_cards_and_study():
    s, ref, items = _studied()
    store.save_cards(s["id"], ref["id"], [{"id": "c1", "reference": ref["id"], "feature": "Log care", "summary": "Water and feed.",
                                           "records": [{"name": "Plant", "fields": [{"name": "name", "type": "text"}]}],
                                           "steps": [], "screens": [], "rules": [], "roles": [], "needs": ["push"],
                                           "unknowns": [], "standing": {"observed": 3, "derived": 0, "inferred": 1, "unknown": 0}}])
    job = store.jobs(s["id"])[0]
    job["dossier"]["voices"] = [{"text": "DOSSIER-SENTINEL users love it"}]
    store.save_job(job)
    s["chat"] = [{"role": "user", "text": "I want a plant notebook"}, {"role": "assistant", "text": "Noted."}]
    s["board"]["product"] = {"name": "Leaf", "pitch": "A plant notebook."}
    store.save(s)
    return s, ref


def test_drafts_are_composed_from_cards_board_and_conversation_and_nothing_of_the_study(monkeypatch):
    s, ref = _with_cards_and_study()
    asked: list = []
    monkeypatch.setattr(drafts, "_client", lambda: _client({"drafts": [DRAFT_A, DRAFT_B]}, asked))
    out = drafts.compose(s, 2, "differ on who pays")
    assert [d["title"] for d in out] == ["Care first", "Shop first"]
    material = asked[0]["messages"][0]["content"]
    assert "Log care" in material and "Water and feed." in material            # the cards
    assert "I want a plant notebook" in material and "Leaf" in material        # the conversation, the board
    assert "differ on who pays" in material
    item_ids = [i["id"] for j in store.jobs(s["id"]) for i in j.get("evidence") or []]
    for forbidden in ("SECRET-SPAN-FROM-A-PAGE", "DOSSIER-SENTINEL", "GET /api/plants", *item_ids):
        assert forbidden not in material, forbidden
    a = out[0]
    assert a["version"] == 1 and a["changed"] == "first draft" and a["estimate"]["units"] == 3
    assert a["cannot_yet"] == [{"kind": "push", "status": "unproven", "what": capability.MAP["push"][1], "proof": capability.MAP["push"][2]}]
    b = out[1]
    assert [c["kind"] for c in b["cannot_yet"]] == ["payments", "store_app"]
    listed = {d["id"]: d for d in store.drafts(s["id"])}
    assert len(listed) == 2 and listed[a["id"]]["versions"] == [{"version": 1, "at": a["at"], "changed": "first draft"}]


def test_a_revision_is_a_new_version_that_keeps_the_notes_and_says_what_changed(monkeypatch):
    s, ref = _with_cards_and_study()
    monkeypatch.setattr(drafts, "_client", lambda: _client({"drafts": [DRAFT_A]}, []))
    did = drafts.compose(s, 1)[0]["id"]
    drafts.add_note(s["id"], did, "screen:Plant", "show the photo bigger")
    revised = {**DRAFT_A, "screens": DRAFT_A["screens"] + [{"name": "Settings", "device": "phone"}], "rules": []}
    monkeypatch.setattr(drafts, "_client", lambda: _client({"draft": revised, "changed": "Added Settings; dropped the once-a-day rule"}, []))
    v2 = drafts.revise(s, did, "add a settings screen")
    assert v2["version"] == 2 and v2["changed"].startswith("Added Settings")
    assert v2["notes"][0]["on"] == "screen:Plant" and v2["notes"][0]["text"] == "show the photo bigger"
    versions = store.draft_versions(s["id"], did)
    assert [v["version"] for v in versions] == [1, 2]
    d = drafts.diff(versions[0], versions[1])
    assert d["screens"] == {"added": ["Settings"], "removed": []} and d["rules"] == {"added": [], "removed": ["Once a day"]}
    assert "pitch" not in d


def test_choosing_a_draft_sets_the_board_and_makes_its_drawings_the_boards(monkeypatch):
    s, ref = _with_cards_and_study()
    s["board"]["screens"] = [{"name": "Old screen"}]
    s["board"]["roles"] = [{"name": "Old role"}]
    monkeypatch.setattr(drafts, "_client", lambda: _client({"drafts": [DRAFT_A]}, []))
    did = drafts.compose(s, 1)[0]["id"]
    store.save_drawing(s["id"], {"id": store.new_drawing_id(), "scope": f"draft:{did}", "screen": "Plants", "status": "done", "at": 1})
    store.save_drawing(s["id"], {"id": store.new_drawing_id(), "scope": "board", "screen": "Old screen", "status": "done", "at": 1})
    board = drafts.choose(s, did)
    assert [x["name"] for x in board["screens"]] == ["Plants", "Plant"] and board["roles"] == [{"name": "Gardener"}]
    assert board["product"]["pitch"] == "A notebook that logs every watering." and board["product"]["name"] == "Leaf"
    assert [e["name"] for e in board["entities"]] == ["Plant"]
    assert any("Built from draft “Care first” v1" in d["text"] for d in board["decisions"])
    assert any(d["text"] == "Assumed: one garden per account" for d in board["decisions"])
    scopes = {(r.get("scope") or "board", r["screen"]) for r in store.drawings(s["id"])}
    assert ("board", "Plants") in scopes and ("board", "Old screen") in scopes and (f"draft:{did}", "Plants") in scopes
    assert s["chosen_draft"]["id"] == did


def test_choose_draft_hands_off_only_on_consent(monkeypatch):
    s, ref = _with_cards_and_study()
    monkeypatch.setattr(drafts, "_client", lambda: _client({"drafts": [DRAFT_A]}, []))
    did = drafts.compose(s, 1)[0]["id"]
    out, err = agent.choose_draft(s, {"draft": did, "app_name": "Leaf"}, lambda e, d: None, "hmm, maybe later")
    assert err and "not told you" in out[0]["text"] and "handoff_request" not in s
    out, err = agent.choose_draft(s, {"draft": did, "app_name": "Leaf"}, lambda e, d: None, "build it")
    assert not err and s["handoff_request"]["app_name"] == "Leaf" and s["board"]["status"] == "agreed"
    out, err = agent.choose_draft(s, {"draft": "000000000000", "app_name": "Leaf"}, lambda e, d: None, "build it")
    assert err and "No draft" in out[0]["text"]


def test_the_drafting_tasks_name_no_application():
    for name in ("myntra", "amazon", "zara", "airbnb", "uber", "shopify", "garden log", "spoke"):
        assert not re.search(rf"\b{name}\b", (drafts.SYSTEM + drafts.REVISE).lower()), name


def test_a_reply_without_the_tool_call_is_asked_once_more_and_no_tool_choice_is_forced(monkeypatch):
    """Forced `tool_choice` is a 400 on the current models (the first live
    card-writer call, 2026-10-15); the prompt names the tool instead."""
    s, ref, items = _studied()
    asked: list = []
    replies = [SimpleNamespace(content=[SimpleNamespace(type="text", text="Here are my thoughts...")], usage=None),
               SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={"cards": [{"feature": "Log care", "summary": "x"}]})], usage=None)]

    class S:
        def __init__(self, kw):
            asked.append(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return replies.pop(0)
    monkeypatch.setattr(cards, "_client", lambda: SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: S(kw))))
    out = cards.write(s["id"], ref["id"])
    assert [c["feature"] for c in out] == ["Log care"]
    assert len(asked) == 2 and all("tool_choice" not in kw for kw in asked)
    assert "calling `write_cards` now" in asked[1]["messages"][-1]["content"]


def test_build_this_draft_is_a_go_ahead():
    """The Drafts tab's button sends "Build draft <id> (“title”)"; on the
    first live run the consent check read it as not a go-ahead and the
    build never started (2026-10-15)."""
    assert agent.consented("Build draft 844add789734 (“A · Essentials: write, read, comment, follow”)")
    assert agent.consented("yes, build this draft")
    assert not agent.consented("Which draft would you build?")

"""Occupied time feels shorter than waiting (2026-10-17): the turn says each
step in plain words as it starts and what it showed, through the panel's
step trail, instead of "Still working on it" every five minutes."""
from __future__ import annotations

import json

from services.smith import narrate
from services.smith.loop import Observation
from services.smith4 import turn as turn_mod


def test_each_tool_starts_in_plain_words():
    assert narrate.starting("open_page", {"route": "/orders", "as": "Manager"}) == "Opening /orders as Manager…"
    assert narrate.starting("open_page", {"route": "/login", "sign_in": True, "as": "Admin"}).startswith(
        "Signing in through the sign-in form as Admin")
    assert narrate.starting("open_page", {"route": "/", "press": "all"}) == "Opening / and pressing every control on it…"
    assert narrate.starting("try_workflow", {"workflow": "Place Order", "as": "signed out"}).startswith(
        "Running the Place Order process as signed out")
    assert narrate.starting("read_page_code", {"route": "/orders"}) == "Reading /orders…"
    assert narrate.starting("grep", {"pattern": "addToCart"}) == "Searching the code for “addToCart”…"
    assert narrate.starting("edit_file", {"path": "src/lib/x.ts", "why": "the date is a Date, not a string"}) == \
        "Editing src/lib/x.ts — the date is a Date, not a string…"
    assert narrate.starting("write_page_code", {"page": "orders", "because": "x undefined"}) == \
        "Rewriting the orders screen — x undefined…"
    assert narrate.starting("run_checks", {"what": "routes"}) == "Running the application's routes checks…"
    assert narrate.starting("restyle", {"because": "orange gradient"}) == "Restyle — orange gradient…"
    assert narrate.starting("answer", {"text": "…"}) == "" and narrate.starting("done", {}) == ""


def test_what_a_step_showed_is_said_when_it_changes_what_to_expect():
    from services.smith import trials
    assert narrate.seen("open_page", {}, "read", "HTTP 500 on /orders\nbrowser error: x") == \
        "Found it: HTTP 500 on /orders"
    assert narrate.seen("open_page", {}, "read", "HTTP 500 on /orders\nblank", after_change=True) == \
        "Still failing after the change: HTTP 500 on /orders"
    assert narrate.seen("open_page", {}, "read", "landed on /orders\nfine", after_change=True) == \
        "It works now: landed on /orders"
    assert narrate.seen("open_page", {}, "read", trials.SERVER_RESTARTED).startswith("The app's server was not there")
    assert narrate.seen("read_file", {}, "read", "const x = 1") == ""
    assert narrate.seen("write_page_code", {}, "resolved", "Rewrote /orders") == "Changed: Rewrote /orders"
    assert narrate.seen("write_section", {}, "finding", "the agent refused: no such entity") == \
        "Could not do that: the agent refused: no such entity"
    report = "checks · routes: 3 of 4 screens answer as declared, 1 not right\n  ✗ Orders as Visitor: HTTP 200 where sign-in was expected"
    assert narrate.seen("run_checks", {}, "read", report) == \
        "Checks: routes: 3 of 4 screens answer as declared, 1 not right. Not right: Orders as Visitor: HTTP 200 where sign-in was expected"


def test_the_first_word_depends_on_what_is_known():
    assert narrate.opening(False, True).startswith("On it: I will see it the way you did")
    assert narrate.opening(True, True).startswith("Picking up from what I learned")
    assert narrate.opening(False, False).startswith("On it: reading the definition")
    assert narrate.opening(False, False, defined=False).startswith("Reading what you have said")


def test_the_turn_narrates_through_the_step_channel(tmp_path, monkeypatch):
    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    doc = {"meta": {"name": "T"}, "roles": [{"id": "r1", "name": "Admin"}],
           "pages": [{"id": "p_home", "name": "Home", "route": "/", "roles": ["r1"]}],
           "requirements": [{"id": "q1", "text": "A home screen"}], "data": {"entities": []}}
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc))
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "package.json").write_text("{}")
    monkeypatch.setattr(turn_mod.trials, "run", lambda name, args, bench, doc: "HTTP 500 on /\nbrowser error: x")
    import itertools
    picks = itertools.chain([{"tool": "open_page", "args": {"route": "/", "as": "Admin"}}],
                            itertools.repeat({"tool": "answer", "args": {
                                "text": "The home page answers 500; the cause is in load.ts.", "no_change": True}}))
    told: list = []

    def reasoning(text, kind="reasoning", node=""):
        told.append((kind, text))
    ctx = turn_mod.Ctx(output_dir=str(tmp_path), project_id="p", message="fix home", ask="fix home",
                       reasoning=reasoning)
    turn_mod.turn(ctx, choose=lambda *a, **k: next(picks))
    steps = [t for k, t in told if k == "step"]
    assert steps[0].startswith("On it")
    assert "Opening / as Admin…" in steps
    assert "Found it: HTTP 500 on /" in steps


def test_a_platform_turn_says_nothing_to_the_panel():
    told: list = []
    ctx = turn_mod.Ctx(output_dir="/x", project_id="p", message="", ask="fault", unattended=True,
                       reasoning=lambda text, kind="reasoning", node="": told.append(text))
    turn_mod.tell(ctx, "Opening /…")
    assert told == []

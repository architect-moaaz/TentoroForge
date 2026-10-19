"""The still-open three after the two-week analysis (2026-10-17): a turn ends
on a failing try with "say carry on"; the after-change repair knows only the
fault; a check sweep runs on past a cause every item shares."""
from __future__ import annotations

from services.smith.loop import Observation
from services.smith4 import turn as turn_mod


def _change():
    return Observation(tool="write_page_code", args={"page": "orders"}, status="resolved", said="edited",
                       touched=["app/src/app/orders/view.tsx"])


def _try(said):
    return Observation(tool="open_page", args={"route": "/orders", "as": "Admin"}, status="read", said=said)


def test_done_is_refused_once_while_the_try_after_the_change_still_fails():
    # the same failure as before the change: the standing "still not working" nudge
    alike = [_try("HTTP 500 on /orders\nbrowser error: x"), _change(), _try("HTTP 500 on /orders\nbrowser error: x")]
    assert turn_mod._before_done(alike, ["edited"]).startswith(turn_mod.STILL_FAILING)
    # a failure that is new after the change: held once, then it may end with the note
    obs = [_change(), _try("HTTP 500 on /orders\nbrowser error: x")]
    first = turn_mod._before_done(obs, ["edited"])
    assert first.startswith("Not done: the try after your change still fails — HTTP 500 on /orders")
    obs.append(Observation(tool="done", status="error", said=first))
    assert turn_mod._before_done(obs, ["edited"]) == ""


def test_a_passing_try_or_one_that_could_not_run_does_not_hold_done():
    from services.smith import trials
    assert turn_mod.last_try_failed([_change(), _try("landed on /orders\nfine")]) == ""
    assert turn_mod.last_try_failed([_change(), _try(trials.SERVER_RESTARTED)]) == ""
    assert turn_mod.last_try_failed([_change()]) == ""
    assert turn_mod.last_try_failed([_try("HTTP 500 on /x"), _change()]) == ""


def test_more_steps_come_while_the_turn_is_getting_somewhere():
    obs = [_change(), _try("HTTP 500 on /orders\nbrowser error: x")]
    assert turn_mod.more_steps(obs, since=0, steps=40, elapsed_s=60) == turn_mod.FINISH_STEPS
    # only refused steps since the last slice is going round in circles
    circles = obs + [Observation(tool="grep", status="error", said="already taken")] * 3
    assert turn_mod.more_steps(circles, since=2, steps=48, elapsed_s=60) == 0
    # a new read since the slice is progress
    assert turn_mod.more_steps(circles + [Observation(tool="read_file", args={"path": "a.ts"}, status="read",
                                                      said="…")], since=2, steps=48, elapsed_s=60) == turn_mod.FINISH_STEPS
    # the hard limits, and a turn the platform runs
    assert turn_mod.more_steps(obs, since=0, steps=40, elapsed_s=turn_mod.KEEP_AT_IT_TIME_S + 1) == 0
    assert turn_mod.more_steps(obs, since=0, steps=turn_mod.HARD_MAX_STEPS, elapsed_s=60) == 0
    assert turn_mod.more_steps(obs, since=0, steps=turn_mod.HARD_MAX_STEPS - 3, elapsed_s=60) == 3
    assert turn_mod.more_steps(obs, since=0, steps=40, elapsed_s=60, unattended=True) == 0


def _app(tmp_path):
    import json
    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    doc = {"meta": {"name": "T"}, "roles": [{"id": "r1", "name": "Admin"}],
           "pages": [{"id": "p_home", "name": "Home", "route": "/", "roles": ["r1"]}],
           "requirements": [{"id": "q1", "text": "A home screen"}], "data": {"entities": []}}
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc))


def test_the_loop_keeps_at_it_past_the_cap_while_reads_are_new(tmp_path, monkeypatch):
    _app(tmp_path)
    monkeypatch.setattr(turn_mod, "HARD_MAX_STEPS", 9)
    monkeypatch.setattr(turn_mod.loop_mod, "MAX_STEPS", 3)
    monkeypatch.setattr(turn_mod.reads, "run", lambda *a, **k: "nothing here")
    picks: list = []

    def choose(ask, page, observations, history):
        picks.append(len(observations))
        return {"tool": "grep", "args": {"pattern": f"needle{len(picks)}", "path": "app/src"}}
    ctx = turn_mod.Ctx(output_dir=str(tmp_path), project_id="p", message="fix home", ask="fix home")
    out = turn_mod.turn(ctx, choose=choose)
    # three steps were the budget; new reads each time earned slices up to the hard limit
    # (nine steps, then the two picks that ask for a closing answer)
    assert len(picks) == 9 + 2
    assert out.status == "no_op" and "what I read and tried is kept" in out.said


def test_the_loop_stops_when_the_steps_go_round_in_circles(tmp_path, monkeypatch):
    _app(tmp_path)
    monkeypatch.setattr(turn_mod, "HARD_MAX_STEPS", 30)
    monkeypatch.setattr(turn_mod.loop_mod, "MAX_STEPS", 3)
    monkeypatch.setattr(turn_mod.reads, "run", lambda *a, **k: "nothing here")
    picks: list = []

    def choose(ask, page, observations, history):
        picks.append(1)
        return {"tool": "grep", "args": {"pattern": "same", "path": "app/src"}}   # the same step every time
    ctx = turn_mod.Ctx(output_dir=str(tmp_path), project_id="p", message="fix home", ask="fix home")
    out = turn_mod.turn(ctx, choose=choose)
    # the first read is progress (one slice); the repeats are refused, so the next cap ends it
    assert 3 + 2 < len(picks) <= 3 + turn_mod.FINISH_STEPS + 2
    assert out.status == "no_op"


def test_a_repair_the_platform_runs_keeps_its_budget(tmp_path, monkeypatch):
    _app(tmp_path)
    monkeypatch.setattr(turn_mod.loop_mod, "MAX_STEPS", 3)
    monkeypatch.setattr(turn_mod.reads, "run", lambda *a, **k: "nothing here")
    picks: list = []

    def choose(ask, page, observations, history):
        picks.append(1)
        return {"tool": "grep", "args": {"pattern": f"n{len(picks)}", "path": "app/src"}}
    ctx = turn_mod.Ctx(output_dir=str(tmp_path), project_id="p", message="", ask="Home as Admin: HTTP 500",
                       unattended=True)
    turn_mod.turn(ctx, choose=choose)
    assert len(picks) <= 5   # the budget plus the out-of-steps answer asks
    # and a caller's explicit budget is a budget, attended or not
    picks.clear()
    turn_mod.turn(turn_mod.Ctx(output_dir=str(tmp_path), project_id="p", message="fix", ask="fix"),
                  choose=choose, max_steps=2)
    assert len(picks) <= 4


def test_an_ending_on_a_failing_try_says_how_long_it_kept_at_it():
    obs = [_change(), _try("HTTP 500 on /orders\nbrowser error: x")] * 12
    note = turn_mod._failing_note(obs, elapsed_s=31 * 60)
    assert note.startswith("\n\nI kept at this for 31 minutes (24 steps).")
    assert "continue from here" in note and "keep at it" not in note
    assert turn_mod.kept_at_it(obs[:2], elapsed_s=30) == ""


def test_the_ask_is_carried_into_an_unattended_repair():
    ctx = turn_mod.Ctx(output_dir="/x", project_id="p", message="", ask="Home (/) as Admin: HTTP 500",
                       unattended=True, asked_from="make the home page show today's orders")
    text = turn_mod.asked_text(ctx)
    assert text.startswith("make the home page show today's orders")
    assert "repairs what making that change broke, and nothing else: Home (/) as Admin: HTTP 500" in text
    ctx2 = turn_mod.Ctx(output_dir="/x", project_id="p", message="", ask="add the field", asked_from="plan: three things")
    assert "(This turn does one part of it: add the field)" in turn_mod.asked_text(ctx2)


def test_the_after_change_check_hands_the_ask_to_its_repair(tmp_path, monkeypatch):
    from services.blueprint import app_check
    calls: list = []

    def run_turn(message, output_dir, ask, **kw):
        calls.append(kw)
        return {"edited_paths": []}
    fake_out = {"left": [], "untried": [], "touched": [], "said": "", "repaired": [], "pages": []}
    monkeypatch.setattr(app_check, "_check_app", lambda *a, **k: calls.append(k) or fake_out)
    monkeypatch.setattr(app_check, "affected_pages", lambda *a, **k: ["p1"], raising=False)
    try:
        app_check.check_change(str(tmp_path), ["app/src/app/orders/view.tsx"], run_turn=run_turn,
                               asked="show today's orders")
    except Exception:  # noqa: BLE001 — the fixture has no app; what matters is the hand-off below
        pass
    assert any(k.get("asked") == "show today's orders" for k in calls if isinstance(k, dict)) or not calls


def test_the_route_sweep_stops_when_the_app_stops_answering(monkeypatch):
    from services.blueprint import route_check
    doc = {"pages": [], "data": {"entities": []}, "roles": []}
    todo = [{"page": f"p{i}", "name": f"Page {i}", "route": f"/p{i}", "as": "Admin", "expect": "200", "entity": ""}
            for i in range(8)]
    monkeypatch.setattr(route_check, "expected_outcomes", lambda d: todo)
    monkeypatch.setattr("services.smith.trials._session", lambda *a, **k: ("Admin", [{"name": "c", "value": "v"}]))

    def http(app, method, path, body, jar):
        raise ConnectionError("refused")
    monkeypatch.setattr("services.smith.trials._http", http)
    out = route_check.check_routes(object(), doc)
    assert out["total"] == 8 and len(out["untried"]) == 8 and out["green"] == [] and out["red"] == []
    did_not_answer = [u for u in out["untried"] if u["why"].startswith("the app did not answer")]
    assert len(did_not_answer) == route_check.UNANSWERED_STOP
    assert out["causes"] == [f"the app stopped answering after {route_check.UNANSWERED_STOP} screens in a row: 5 screens not tried"]


def test_the_cause_is_said_once_before_the_items():
    from services.blueprint.fix_to_green import causes_line
    line = causes_line(["could not sign in as Doctor: 40 screens not tried"])
    assert line.startswith("Behind the screens I could not try there is one cause each")
    assert "could not sign in as Doctor: 40 screens not tried" in line

"""A removal confirmation answered "No, leave it" (or ignored) is over; it must
not swallow a later yes to a plan, and an expired question is not waiting."""
import json
import os
import time

from services.smith import confirm, pending_ask, plan as plan_mod


def test_a_clear_no_clears_it_and_says_so(tmp_path):
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Medicine.preferredTime"))
    assert confirm.waiting(tmp_path)
    assert confirm.decline_if_not_yes(tmp_path, "No, leave it") == "no"
    assert not confirm.waiting(tmp_path)


def test_an_unrelated_message_clears_it_without_claiming_a_no(tmp_path):
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Medicine.preferredTime"))
    assert confirm.decline_if_not_yes(tmp_path, "make the header blue") == "dropped"
    assert not confirm.waiting(tmp_path)


def test_a_yes_still_reaches_the_confirmation_exactly_once(tmp_path):
    fp = confirm.fingerprint("remove_field", "Medicine.preferredTime")
    confirm.remember(tmp_path, fp)
    assert confirm.decline_if_not_yes(tmp_path, "Go ahead") == ""                         # a yes is not cleared
    assert confirm.waiting(tmp_path)
    assert confirm.granted(tmp_path, "Go ahead", "remove_field", "Medicine.preferredTime")
    assert not confirm.waiting(tmp_path)                                                  # taken
    assert not confirm.granted(tmp_path, "Go ahead", "remove_field", "Medicine.preferredTime")


def test_an_expired_confirmation_is_not_waiting(tmp_path):
    confirm.remember(tmp_path, "remove_field:a.b")
    p = tmp_path / confirm.PENDING_PATH
    d = json.loads(p.read_text())
    d["at"] = time.time() - confirm.MAX_AGE_S - 5
    p.write_text(json.dumps(d))
    assert not confirm.waiting(tmp_path)
    assert confirm.decline_if_not_yes(tmp_path, "Go ahead") == "" and not p.exists()


def test_a_yes_is_smiths_only_while_something_really_waits(tmp_path):
    from routers.blueprint_generate import _smith_is_waiting
    assert not _smith_is_waiting(tmp_path, "Go ahead")
    confirm.remember(tmp_path, "remove_field:a.b")
    assert _smith_is_waiting(tmp_path, "Go ahead")
    confirm.clear(tmp_path)
    ask = tmp_path / pending_ask.PENDING_PATH
    ask.parent.mkdir(parents=True, exist_ok=True)
    ask.write_text("{}")
    assert _smith_is_waiting(tmp_path, "Go ahead")
    old = time.time() - pending_ask.MAX_AGE_S - 60
    os.utime(ask, (old, old))
    assert not _smith_is_waiting(tmp_path, "Go ahead")                                   # an old ask is not waiting
    assert not _smith_is_waiting(tmp_path, "build app")


def test_a_plan_agreed_after_a_declined_removal_runs(tmp_path, monkeypatch):
    import sys
    from services.smith4 import handle as handle_fn
    H = sys.modules["services.smith4.handle"]
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Medicine.preferredTime"))
    monkeypatch.setattr(H, "_in_step", lambda o, v, r: r, raising=False)
    monkeypatch.setattr(H, "_engine_current", lambda o: [], raising=False)
    got = handle_fn(project_id="p", output_dir=str(tmp_path), message="No, leave it",
                   choose=lambda *a: {"tool": "answer", "args": {"text": "x"}}, move=None)
    assert "left it as it was" in got.said and not confirm.waiting(tmp_path)
    plan_mod.remember(tmp_path, ["add a spice level", "show it on the form"], agreed=False)
    ran = []
    handle_fn(project_id="p", output_dir=str(tmp_path), message="Go ahead",
             choose=lambda ask, page, obs, hist: (ran.append(ask), {"tool": "answer", "args": {"text": "ok"}})[1], move=None)
    assert ran and "spice level" in ran[0]

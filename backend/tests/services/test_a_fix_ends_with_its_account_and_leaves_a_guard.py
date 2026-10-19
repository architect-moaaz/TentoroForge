"""Against the Claude Code standard the owner held up (2026-10-17): a fix
says what was happening, what changed and what proved it, and leaves behind
the try that proved it, so the application's own checks hold it."""
from __future__ import annotations

import json

from services.smith import account, guards, trials
from services.smith.loop import Observation


def _fail():
    return Observation(tool="try_workflow", args={"workflow": "Place Order", "as": "Shopper", "input": {"qty": 1}},
                       status="read", said='Place Order as Shopper: HTTP 422\n   2. [check_stock] failed: qty undefined')


def _change():
    return Observation(tool="edit_file", args={"path": "app/src/lib/workflows/definitions/place-order.json",
                                               "why": "the stock check read quantity, the form sends qty"},
                       status="resolved", said="edited", touched=["app/src/lib/workflows/definitions/place-order.json"])


def _pass():
    return Observation(tool="try_workflow", args={"workflow": "Place Order", "as": "Shopper", "input": {"qty": 1}},
                       status="read", said="Place Order as Shopper: HTTP 200 — finished\n  wrote orders: 1 row")


def test_the_evidence_of_a_fix_is_the_same_try_failing_then_passing():
    ev = account.fix_evidence([_fail(), _change(), _pass()])
    assert ev and ev["failed"].said.startswith("Place Order as Shopper: HTTP 422") and ev["passed"].said.startswith("Place Order as Shopper: HTTP 200")
    # a different try passing proves nothing about the one that failed
    other = Observation(tool="open_page", args={"route": "/"}, status="read", said="landed on /\nfine")
    assert account.fix_evidence([_fail(), _change(), other]) is None
    assert account.fix_evidence([_change(), _pass()]) is None
    assert account.fix_evidence([_fail(), _pass()]) is None


def test_the_account_has_three_parts_and_falls_back_without_a_model():
    obs = [_fail(), _change(), _pass()]
    fake = lambda system, user, schema: json.dumps({"account": "Placing an order as a shopper failed at the stock check. The check read a field called quantity while the form sends qty, so it never saw the amount."})  # noqa: E731
    text = account.compose("the order button does nothing", obs, "Changed place-order.json: read qty.", client=fake)
    parts = text.split("\n\n")
    assert parts[0].startswith("What was happening: Placing an order as a shopper failed")
    assert parts[1] == "Changed place-order.json: read qty."
    assert parts[2].startswith("What proved it: running Place Order as Shopper showed “Place Order as Shopper: HTTP 422")
    assert "came back “Place Order as Shopper: HTTP 200" in parts[2]
    # no model: the deterministic lines, with the change's own reason
    broken = lambda system, user, schema: (_ for _ in ()).throw(RuntimeError("no credit"))  # noqa: E731
    text = account.compose("x", obs, "Changed.", client=broken)
    assert text.startswith("What was happening: running Place Order as Shopper showed")
    assert "The cause: the stock check read quantity, the form sends qty." in text
    # not a fix: the receipt stands alone
    assert account.compose("x", [_change()], "Changed.", client=fake) == "Changed."


def test_a_fix_leaves_a_guard_and_a_later_fix_of_the_same_try_replaces_it(tmp_path):
    row = guards.record(tmp_path, "the order button does nothing", [_fail(), _change(), _pass()])
    assert row and row["tool"] == "try_workflow" and row["args"]["workflow"] == "Place Order"
    assert row["before"].startswith("Place Order as Shopper: HTTP 422") and row["after"].startswith("Place Order as Shopper: HTTP 200")
    assert len(guards.load(tmp_path)) == 1
    guards.record(tmp_path, "again", [_fail(), _change(), _pass()])
    assert len(guards.load(tmp_path)) == 1 and guards.load(tmp_path)[0]["ask"] == "again"
    assert guards.record(tmp_path, "nothing", [_change()]) is None


class _Bench:
    running = False

    def __init__(self, output_dir):
        self.output_dir = str(output_dir)

    def app(self):
        return object()

    def server_said(self):
        return []


def test_guards_run_again_and_a_broken_one_is_marked(tmp_path, monkeypatch):
    guards.record(tmp_path, "the order button does nothing", [_fail(), _change(), _pass()])
    monkeypatch.setattr(trials, "run", lambda name, args, bench, doc: "Place Order as Shopper: HTTP 200 — finished")
    out = guards.run(_Bench(tmp_path), {})
    assert out["total"] == 1 and len(out["green"]) == 1 and out["lines"][0] == "checks · guards: 1 of 1 earlier fixes still hold"
    monkeypatch.setattr(trials, "run", lambda name, args, bench, doc: "Place Order as Shopper: HTTP 422\n   2. [check_stock] failed: x")
    out = guards.run(_Bench(tmp_path), {})
    assert out["red"] and out["red"][0].startswith("  ✗ try_workflow") and "it was “Place Order as Shopper: HTTP 200" in out["red"][0]
    assert trials.failed("\n".join(out["lines"]))


def test_run_checks_guards_is_a_kind(tmp_path, monkeypatch):
    guards.record(tmp_path, "the order button does nothing", [_fail(), _change(), _pass()])
    real_run = trials.run

    def fake(name, args, bench, doc):
        if name == "run_checks":
            return real_run(name, args, bench=bench, doc=doc)
        return "Place Order as Shopper: HTTP 200 — finished"
    monkeypatch.setattr(trials, "run", fake)
    said = trials.run("run_checks", {"what": "guards"}, bench=_Bench(tmp_path), doc={"pages": [], "data": {"entities": []}})
    assert "checks · guards: 1 of 1 earlier fixes still hold" in said


def test_a_fix_turn_ends_with_the_account_and_writes_the_guard(tmp_path, monkeypatch):
    from services.smith4 import turn as turn_mod
    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    doc = {"meta": {"name": "T"}, "roles": [{"id": "r1", "name": "Admin"}],
           "pages": [{"id": "p_home", "name": "Home", "route": "/", "roles": ["r1"]}],
           "requirements": [{"id": "q1", "text": "A home screen"}], "data": {"entities": []}}
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc))
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "package.json").write_text("{}")
    (tmp_path / "app" / "src").mkdir()
    (tmp_path / "app" / "src" / "x.ts").write_text("const a = 1;\n")
    tries = iter(["HTTP 500 on /\nbrowser error: a is not defined", "landed on /\nfine"])
    monkeypatch.setattr(turn_mod.trials, "run", lambda name, args, bench, doc: next(tries))
    monkeypatch.setattr(account, "_client", lambda system, user, schema: json.dumps({"account": "The home page crashed on load because a value was read before it existed."}))
    picks = iter([
        {"tool": "open_page", "args": {"route": "/", "as": "Admin"}},
        {"tool": "edit_file", "args": {"path": "app/src/x.ts", "find": "const a = 1;", "replace": "const a = 2;",
                                       "why": "a was read before it was set", "requested": "true"}},
        {"tool": "open_page", "args": {"route": "/", "as": "Admin"}},
        {"tool": "done", "args": {}},
    ])
    ctx = turn_mod.Ctx(output_dir=str(tmp_path), project_id="p", message="the home page is blank", ask="the home page is blank")
    out = turn_mod.turn(ctx, choose=lambda *a, **k: next(picks))
    assert out.status == "resolved", out.said
    assert out.said.startswith("What was happening: The home page crashed on load")
    assert "What proved it: opening / as Admin showed “HTTP 500 on /”" in out.said
    rows = guards.load(tmp_path)
    assert len(rows) == 1 and rows[0]["tool"] == "open_page" and rows[0]["args"]["route"] == "/"

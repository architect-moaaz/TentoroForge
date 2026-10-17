"""Why Smith was not like Claude (forge-v3, 2026-10-17): every step of a turn
was decided by the one-shot Sonnet with a 4k thinking budget while the build's
specialists ran on the strongest models; opening a page pressed every control
from a fresh load (four minutes an open on a calculator); and twenty steps
ran out with the change made and the try left. Three settings, each tested."""
from __future__ import annotations

from types import SimpleNamespace

from services.smith import loop, trials, understand_ask


def test_the_step_is_chosen_by_smiths_model(monkeypatch):
    from services.blueprint.executors import SMITH_MODEL
    monkeypatch.delenv("FORGE_SMITH_LOOP_MODEL", raising=False)
    assert understand_ask.loop_model() == SMITH_MODEL and "sonnet" not in SMITH_MODEL
    monkeypatch.setenv("FORGE_SMITH_LOOP_MODEL", "claude-fable-5")
    assert understand_ask.loop_model() == "claude-fable-5"
    seen = {}

    def complete(**kw):
        seen.update(kw)
        return '{"tool": "done", "args": {}, "why": "x"}'
    import services.llm_client as llm
    monkeypatch.setattr(llm, "complete", complete)
    understand_ask._default_provider("decide")
    assert seen["model"] == "claude-fable-5" and seen["max_tokens"] == 12000


def test_a_page_is_opened_to_be_seen_and_pressed_only_when_asked(monkeypatch):
    calls = []

    def run_shots(app, pages, out_dir, *, probe=True, states=True):
        calls.append(probe)
        return [{"id": "p", "url": "/", "status": 200, "text": "Calculator 7 8 9", "controls": [], "errors": []}]
    from services.blueprint import page_review
    monkeypatch.setattr(page_review, "run_shots", run_shots)
    monkeypatch.setattr(trials, "_session", lambda app, doc, as_, guest: ("Admin", {"c": "1"}))
    monkeypatch.setattr(trials, "_role", lambda doc, as_: ("Admin", True))
    bench = SimpleNamespace(app=lambda: object(), guest="g", output_dir="/tmp/x", restarts=0, server_said=lambda: [])
    doc = {"pages": [{"id": "PAGE-001", "route": "/", "name": "Calculator"}], "data": {"entities": []}}
    said = trials.run("open_page", {"route": "/", "as": "Admin"}, bench=bench, doc=doc)
    assert calls == [False] and "controls not pressed" in said and 'press: "all"' in said
    said = trials.run("open_page", {"route": "/", "as": "Admin", "press": "all"}, bench=bench, doc=doc)
    assert calls == [False, True] and "controls not pressed" not in said
    assert "`press`" in next(d for n, d, a in trials.TRIALS if n == "open_page") or "press" in next(a for n, d, a in trials.TRIALS if n == "open_page")


def test_a_turn_has_forty_steps():
    assert loop.MAX_STEPS == 40

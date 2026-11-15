"""A Smith turn reads the application back from the cache.

forge-v3, 30 days to 2026-11-11: Smith cost $204, $140 of it writing to the
prompt cache, and three quarters of those writes were the application's own
block missing while the rules and tools around it were read back. Three
things moved it:
  - the state a turn begins from (an agreed plan's waiting steps, the
    notebook, the live line) changes every turn and sat at the top of that
    block, so every turn wrote the whole application again;
  - a change rebuilt the page, and the page AND every step of the turn
    cached behind it were written again, 40-60k tokens a time, after a third
    of all steps;
  - a screenshot led the prompt, so a turn with one shared no cached prefix
    with any other.
The state now goes in the turn's own part, a change says what it moved on
its own step, and pictures follow the cached blocks.
"""
from __future__ import annotations

import json

from services.smith import loop
from services.smith.loop import TURN_STATE, Observation
from tests.services._loop_fixtures import _repo


def _blocks(monkeypatch):
    sent: list[list[dict]] = []

    def provider(prompt, reasoning=None, images=()):
        sent.append(prompt)
        return json.dumps({"tool": "done", "args": {}, "why": "x"})
    monkeypatch.setattr("services.smith.understand_ask._default_provider", provider)
    return sent


def test_the_turns_state_is_not_in_the_applications_cached_block(monkeypatch):
    sent = _blocks(monkeypatch)
    loop.next_step("next", "THE APP" + TURN_STATE + "NOTEBOOK: turn one learned this", [], [])
    loop.next_step("next", "THE APP" + TURN_STATE + "NOTEBOOK: turn two learned that", [], [])
    (rules1, app1, *rest1), (rules2, app2, *rest2) = sent
    assert app1 == app2 and "NOTEBOOK" not in app1["text"], "the application block is the same text in both turns"
    assert "turn one learned this" in rest1[0]["text"] and "turn two learned that" in rest2[0]["text"]
    assert "WHERE THINGS STOOD WHEN THIS TURN BEGAN" in rest1[0]["text"]
    loop.next_step("next", "THE APP", [], [])
    assert "WHERE THINGS STOOD" not in sent[-1][2]["text"], "no state, no heading"


def test_a_screenshot_follows_the_cached_blocks(monkeypatch, tmp_path):
    from services.blueprint import executors
    from services.smith import understand_ask
    got: list = []
    monkeypatch.setattr("services.llm_client.complete", lambda **kw: got.append(kw["content"]) or "{}")
    monkeypatch.setattr(executors, "image_block", lambda path: {"type": "image", "source": str(path)})
    blocks = [{"type": "text", "text": "RULES", "cache_control": {"type": "ephemeral"}},
              {"type": "text", "text": "APP", "cache_control": {"type": "ephemeral"}},
              {"type": "text", "text": "THE ASK"}]
    understand_ask._default_provider(blocks, None, images=[tmp_path / "shot.png"])
    assert [b.get("text") or b["type"] for b in got[0]] == ["RULES", "APP", "image", "THE ASK"]
    understand_ask._default_provider("one text", None, images=[tmp_path / "shot.png"])
    assert got[1][0]["type"] == "image", "a prompt with nothing cached still leads with the picture"


def test_page_changes_says_what_moved_or_that_the_page_should_go_again():
    from services.smith4.context import page_changes
    before = "\n".join(f"line {i}" for i in range(40))
    after = before.replace("line 7", "line 7, renamed")
    moved = page_changes(before, after)
    assert moved == "  line 6\n- line 7\n+ line 7, renamed"
    assert page_changes(before, before) == ""
    assert page_changes(before, "something else entirely") is None, "most of it moved: send the page"


class _Records:
    def __init__(self, *steps: dict):
        self.steps = list(steps)
        self.pages: list[str] = []
        self.seen: list[list[Observation]] = []

    def __call__(self, ask, page, observations, history):
        self.pages.append(page)
        self.seen.append(list(observations))
        return self.steps.pop(0) if self.steps else {"tool": "answer", "args": {"text": "Done."}, "why": ""}


def test_a_change_is_said_on_its_step_and_the_page_stays(tmp_path, monkeypatch):
    from services.smith4 import context, handle, turn as turn_mod
    _repo(tmp_path)
    monkeypatch.setattr(context, "defined", lambda _out: True)
    (tmp_path / "app" / "a.ts").write_text("export const a = 1;\n")
    pages = iter(["SCREENS:\n- Orders\n- Customers\n" + "x\n" * 60,
                  "SCREENS:\n- Orders\n- Customers\n- Invoices\n" + "x\n" * 60])
    last = {"page": ""}

    def opening(*a, **k):
        last["page"] = next(pages, last["page"])
        return last["page"]
    monkeypatch.setattr(turn_mod, "opening", opening)
    monkeypatch.setattr(turn_mod, "asked_for", lambda words, change: True)
    chooser = _Records(
        {"tool": "edit_file", "args": {"path": "app/a.ts", "find": "1", "replace": "2", "why": "asked",
                                       "requested": True}},
        {"tool": "read_file", "args": {"path": "app/a.ts"}, "why": ""})
    handle(project_id="p", output_dir=str(tmp_path), message="set a to 2", choose=chooser, max_steps=4)
    assert len(chooser.pages) >= 2
    assert len({p.partition(TURN_STATE)[0] for p in chooser.pages}) == 1, "the page is the one the turn began with"
    change = next(o for o in chooser.seen[1] if o.tool == "edit_file")
    assert change.now == "  - Customers\n+ - Invoices", change.now
    assert "THE APPLICATION NOW" in change.line() and "+ - Invoices" in change.line()


def test_a_change_that_moves_most_of_the_page_sends_the_page(tmp_path, monkeypatch):
    from services.smith4 import context, handle, turn as turn_mod
    _repo(tmp_path)
    monkeypatch.setattr(context, "defined", lambda _out: True)
    (tmp_path / "app" / "a.ts").write_text("export const a = 1;\n")
    pages = iter(["THERE IS NO APPLICATION YET.", "SCREENS:\n" + "\n".join(f"- Screen {i}" for i in range(30))])
    last = {"page": ""}

    def opening(*a, **k):
        last["page"] = next(pages, last["page"])
        return last["page"]
    monkeypatch.setattr(turn_mod, "opening", opening)
    monkeypatch.setattr(turn_mod, "asked_for", lambda words, change: True)
    chooser = _Records(
        {"tool": "edit_file", "args": {"path": "app/a.ts", "find": "1", "replace": "2", "why": "asked",
                                       "requested": True}},
        {"tool": "read_file", "args": {"path": "app/a.ts"}, "why": ""})
    handle(project_id="p", output_dir=str(tmp_path), message="set a to 2", choose=chooser, max_steps=4)
    assert chooser.pages[0].startswith("THERE IS NO APPLICATION YET")
    assert chooser.pages[1].startswith("SCREENS:"), "a whole new page is sent as the page"
    change = next(o for o in chooser.seen[1] if o.tool == "edit_file")
    assert change.now == ""

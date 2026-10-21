"""The page a turn's steps are chosen from stays the same text from step to
step until something changes, so the cache is read, not written again.

pah7lhfz (2026-10-21): the page was rebuilt every step with a live line
("N min so far") and the turn's own checkpoint at its top; every call wrote
~32k tokens to the cache — $74 of a $92 unattended hour on Opus — and from
step two the turn was shown its own checkpoint as a turn that was lost.
"""
from __future__ import annotations

import itertools

from tests.services._loop_fixtures import _repo


def _defined(monkeypatch):
    from services.smith4 import context
    monkeypatch.setattr(context, "defined", lambda _out: True)


class _Records:
    def __init__(self, *steps: dict):
        self.steps = list(steps)
        self.pages: list[str] = []

    def __call__(self, ask: str, page: str, observations: list, history: list) -> dict:
        self.pages.append(page)
        return self.steps.pop(0) if self.steps else {"tool": "answer", "args": {"text": "Read them."}, "why": ""}


def test_reads_and_tries_leave_the_page_as_it_was(tmp_path, monkeypatch):
    from services import run_registry
    from services.smith4 import handle
    _repo(tmp_path)
    _defined(monkeypatch)
    tick = itertools.count()
    monkeypatch.setattr(run_registry, "live_state", lambda _out: f"RIGHT NOW: a check, {next(tick)} min so far")
    (tmp_path / "app" / "a.ts").write_text("export const a = 1;\n")
    (tmp_path / "app" / "b.ts").write_text("export const b = 2;\n")
    chooser = _Records({"tool": "read_file", "args": {"path": "app/a.ts"}, "why": ""},
                       {"tool": "read_file", "args": {"path": "app/b.ts"}, "why": ""},
                       {"tool": "grep", "args": {"pattern": "export"}, "why": ""})
    handle(project_id="p", output_dir=str(tmp_path), message="what do a and b export?",
           choose=chooser, max_steps=6)
    assert len(chooser.pages) >= 3
    assert len(set(chooser.pages)) == 1, "the page moved between steps that changed nothing"
    assert "0 min so far" in chooser.pages[0]
    assert "this turn was lost" not in chooser.pages[-1], "the turn was shown its own checkpoint"


def test_the_head_is_what_the_turn_began_with(tmp_path, monkeypatch):
    from services import run_registry
    from services.smith4.context import opening, turn_head
    _repo(tmp_path)
    _defined(monkeypatch)
    monkeypatch.setattr(run_registry, "live_state", lambda _out: "RIGHT NOW: nothing")
    head = turn_head(str(tmp_path))
    monkeypatch.setattr(run_registry, "live_state", lambda _out: "RIGHT NOW: something else")
    kept = opening("p", str(tmp_path), "anything", head=head)
    assert "RIGHT NOW: nothing" in kept and "something else" not in kept
    assert "something else" in opening("p", str(tmp_path), "anything")

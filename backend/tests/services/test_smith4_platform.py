"""A turn the platform starts — self-heal, the verify pass, the journey verifier.

They read the shape the legacy agent returned; `smith4.platform.smith_result`
keeps that shape over the loop. Commit only when the caller measures in
commits; honour a caller's step budget; report the steps as the trace.
"""
from __future__ import annotations

import subprocess

from services.smith4 import platform
from services.smith4.outcome import Outcome
from tests.services._loop_fixtures import _Chooser, _Writes, _rename, _repo


def _git(tmp_path, *args):
    return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()


def test_the_legacy_shape_is_kept_over_the_loop(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(platform, "handle", lambda **k: Outcome(
        status="resolved", said="Rewrote /x.", touched=["app/src/x.tsx"], steps=["read_page_code", "write_page_code"]))
    out = platform.smith_result("p1", str(tmp_path), "a crash happened")
    assert out["answer"] == "Rewrote /x." and out["question"] is None
    assert out["edited_paths"] == ["app/src/x.tsx"]
    assert out["trace"] == [{"tool": "read_page_code"}, {"tool": "write_page_code"}]


def test_a_question_lands_in_question_not_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(platform, "handle", lambda **k: Outcome(status="asked", said="Which page?"))
    out = platform.smith_result("p1", str(tmp_path), "x")
    assert out["question"] == "Which page?" and out["answer"] is None and out["edited_paths"] == []


def test_a_commit_is_made_only_when_asked_and_only_of_what_was_touched(tmp_path, monkeypatch):
    import services.smith4.platform as plat
    from services.smith4 import handle as real_handle
    _repo(tmp_path)
    (tmp_path / "unrelated.txt").write_text("someone else's work\n")
    writes = _Writes(tmp_path)
    head = _git(tmp_path, "rev-parse", "HEAD")

    def turn_that_renames(target):
        def choose(ask, page, seen, history):
            return _rename(target, "X") if not seen else {"tool": "done", "args": {}, "why": ""}
        return lambda **k: real_handle(**{**k, "choose": choose, "move": writes})

    monkeypatch.setattr(plat, "handle", turn_that_renames("src/a.json"))
    out = platform.smith_result("p1", str(tmp_path), "rename A", commit=False)
    assert out["edited_paths"] and _git(tmp_path, "rev-parse", "HEAD") == head    # touched, not committed

    monkeypatch.setattr(plat, "handle", turn_that_renames("src/b.json"))
    out = platform.smith_result("p1", str(tmp_path), "rename B", commit=True,
                                commit_message="smith(verify round 1)")
    assert _git(tmp_path, "rev-parse", "HEAD") != head
    assert "smith(verify round 1)" in _git(tmp_path, "log", "-1", "--format=%s")
    committed = _git(tmp_path, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert "src/b.json" in committed and "unrelated.txt" not in committed


def test_a_callers_step_budget_is_honoured(tmp_path):
    _repo(tmp_path)
    writes = _Writes(tmp_path)
    chooser = _Chooser(*[_rename(f"src/{i}.json", f"L{i}") for i in range(6)])
    from services.smith4 import handle
    out = handle(project_id="p1", output_dir=str(tmp_path), message="many", choose=chooser,
                 move=writes, max_steps=2)
    assert len(writes.calls) == 2 and "2 steps" in out.said
    assert out.steps == ["rename", "rename"]


def test_verify_pages_is_a_tool_that_reports_per_page(tmp_path, monkeypatch):
    from services.smith import tools, writes
    assert tools.is_write("verify_pages")
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load", classmethod(
        lambda cls, output_dir: type("S", (), {"doc": {"pages": [
            {"id": "PAGE-001", "route": "/tools"}, {"id": "PAGE-002", "route": "/rentals"}]}})()))
    monkeypatch.setattr("services.blueprint.orchestrator.review_coded_pages", lambda svc, root, only=None: {
        "pages": {"PAGE-001": {"passed": True, "rewritten": False, "scores": [8]},
                  "PAGE-002": {"passed": False, "rewritten": True, "scores": [5, 6],
                               "review": {"broken": ["the Accept button does nothing"]}}}})
    out = writes.run("verify_pages", {"routes": ["/tools", "/rentals"]}, output_dir=str(tmp_path))
    assert out["applied"] and "Rewrote: /rentals" in out["said"] and "Passing: /tools" in out["said"]
    assert "/rentals (6/10): the Accept button does nothing" in out["finding"]
    bad = writes.run("verify_pages", {"routes": ["/nowhere"]}, output_dir=str(tmp_path))
    assert "None of /nowhere" in bad["finding"]

"""`scripts/forge_by_hand.py`: build through Forge's own code with a person answering where a model would.

Other sessions drive it from files, so the file protocol is what is pinned here: which requests wait, how
an answer is written, that a wrong answer is refused before the platform tries to decode it, and that no
model key can survive into the process."""
from __future__ import annotations

import json
import threading
import time

import pytest

from scripts import forge_by_hand as fbh

import os as _os
import subprocess as _subprocess
import sys as _sys

#: The process as this file found it: the last test checks nothing in here changed it for the tests after.
_BEFORE = {"cwd": _os.getcwd(), "path": list(_sys.path), "popen": _subprocess.Popen.__init__,
           "env": {k: v for k, v in _os.environ.items() if k != "PYTEST_CURRENT_TEST"}}


def test_only_the_requests_worth_an_answer_wait():
    assert fbh.kind_of(fbh._COVERAGE_OPENING + " covers what", "Requirements: ...") == "coverage"
    assert fbh.kind_of("system", "Decide how to build this page — do not write it yet.") == "pageplan"
    assert fbh.kind_of("system", "Write this page.\n\n```json") == "page"
    assert fbh.kind_of("system", "Here is the Blueprint as it stands. Propose the artifacts your stage owns.") is None


def test_a_step_with_nothing_to_add_gets_the_empty_envelope_without_waiting(tmp_path):
    model = fbh.FileModel(tmp_path, wait_s=0.2, poll_s=0.01, log=lambda *_: None)
    reply = json.loads(model(system="s", user="Here is the Blueprint as it stands."))
    assert reply["proposals"] == [] and not list(tmp_path.glob("*.request.md"))


def _ask_in_a_thread(model, **kw):
    box = {}

    def run():
        box["reply"] = model(**kw)

    t = threading.Thread(target=run)
    t.start()
    return t, box


def test_a_request_is_written_and_waits_until_it_is_answered(tmp_path):
    model = fbh.FileModel(tmp_path, wait_s=5, poll_s=0.01, log=lambda *_: None)
    user = 'Write this page.\n```json\n{"page": {"id": "PAGE-001", "name": "Browse"}}\n```'
    t, box = _ask_in_a_thread(model, system="sys", user=user, schema={"type": "object"})
    deadline = time.time() + 5
    while not list(tmp_path.glob("*.request.md")) and time.time() < deadline:
        time.sleep(0.01)
    request = next(tmp_path.glob("*.request.md"))
    assert request.name == "001-page-PAGE-001.request.md"
    text = request.read_text(encoding="utf-8")
    assert "# SYSTEM" in text and "# USER" in text and "# SCHEMA" in text and "Browse" in text
    assert fbh._waiting(tmp_path) == [request] and "reply" not in box, "it waits"
    fbh._write_answer(request, json.dumps({"rationale": "r", "load": "l", "view": "v"}))
    t.join(5)
    assert json.loads(box["reply"]) == {"rationale": "r", "load": "l", "view": "v"}
    assert fbh._waiting(tmp_path) == []


def test_numbering_continues_after_earlier_requests(tmp_path):
    (tmp_path / "007-page-PAGE-009.request.md").write_text("x")
    (tmp_path / "007-page-PAGE-009.response.json").write_text("{}")
    model = fbh.FileModel(tmp_path, wait_s=0.3, poll_s=0.01, log=lambda *_: None)
    with pytest.raises(TimeoutError):
        model(system=fbh._COVERAGE_OPENING, user="u")
    assert (tmp_path / "008-coverage.request.md").exists()


def test_nobody_answering_is_an_error_not_a_silent_hang(tmp_path):
    model = fbh.FileModel(tmp_path, wait_s=0.1, poll_s=0.01, log=lambda *_: None)
    with pytest.raises(TimeoutError, match="nobody answered"):
        model(system="s", user="Write this page.")


def test_an_answer_that_is_not_json_is_refused_before_the_platform_decodes_it(tmp_path):
    request = tmp_path / "001-coverage.request.md"
    request.write_text("x")
    with pytest.raises(json.JSONDecodeError):
        fbh._write_answer(request, "not json")
    assert not (tmp_path / "001-coverage.response.json").exists()


def test_the_commands_find_a_request_by_a_part_of_its_name_and_answer_it(tmp_path, capsys):
    for stem in ("003-page-PAGE-001", "004-pageplan-PAGE-003"):
        (tmp_path / f"{stem}.request.md").write_text("x")
    q = ["--queue", str(tmp_path)]
    assert fbh.main(q + ["pending"]) == 0
    assert capsys.readouterr().out.split() == ["003-page-PAGE-001", "004-pageplan-PAGE-003"]

    load, view = tmp_path / "l.ts", tmp_path / "v.tsx"
    load.write_text("export async function load() { return {}; }")
    view.write_text('"use client"; export default function V() { return null; }')
    assert fbh.main(q + ["answer-page", "PAGE-001", "--load", str(load), "--view", str(view),
                         "--rationale", " a calm list "]) == 0
    body = json.loads((tmp_path / "003-page-PAGE-001.response.json").read_text())
    assert body == {"rationale": "a calm list", "load": load.read_text(), "view": view.read_text()}

    assert fbh.main(q + ["answer-plan", "PAGE-003", "--state", "None", "--section", "Form", "--section", "Footer",
                         "--behaviour", "runs List Tool"]) == 0
    plan = json.loads((tmp_path / "004-pageplan-PAGE-003.response.json").read_text())
    assert plan == {"state": "None", "sections": ["Form", "Footer"], "behaviours": ["runs List Tool"]}
    capsys.readouterr()
    fbh.main(q + ["pending"])
    assert capsys.readouterr().out.strip() == "nothing is waiting"


def test_an_ambiguous_name_is_refused_rather_than_guessed(tmp_path):
    for stem in ("003-page-PAGE-001", "009-page-PAGE-001"):
        (tmp_path / f"{stem}.request.md").write_text("x")
    with pytest.raises(SystemExit, match="matches 2"):
        fbh._resolve(tmp_path, "PAGE-001")


def test_installing_blanks_every_model_key_and_swaps_the_router(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")
    monkeypatch.setenv("KIMI_API_KEY", "kimi-real")
    monkeypatch.setenv("FORGE_UI_DESIGNER", "uxpilot")
    import os
    import subprocess
    import sys

    from services.blueprint import executors, observer

    # `install` changes the process: it moves into backend/, puts it on sys.path, loads backend/.env into the
    # environment and (on Windows) patches subprocess.Popen. None of that may outlast this test.
    monkeypatch.chdir(os.getcwd())                                       # restored when the test ends
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(subprocess.Popen, "__init__", subprocess.Popen.__init__)
    saved_env = dict(os.environ)
    real_router, real_observer = executors.tiered_router, observer.anthropic_observer
    try:
        model = fbh.install(tmp_path)
        assert os.environ["ANTHROPIC_API_KEY"] == "" and os.environ["KIMI_API_KEY"] == ""
        assert os.environ["FORGE_UI_DESIGNER"] == "", "nobody has decided for the platform"
        assert executors.tiered_router() is model and observer.anthropic_observer() is None
    finally:
        executors.tiered_router, observer.anthropic_observer = real_router, real_observer
        os.environ.clear()
        os.environ.update(saved_env)


def test_zz_installing_left_the_process_as_it_was():
    """`install` moves the process into backend/, edits sys.path, loads backend/.env and patches Popen: undone."""
    assert _os.getcwd() == _BEFORE["cwd"]
    assert _sys.path == _BEFORE["path"]
    assert _subprocess.Popen.__init__ is _BEFORE["popen"]
    assert {k: v for k, v in _os.environ.items() if k != "PYTEST_CURRENT_TEST"} == _BEFORE["env"]

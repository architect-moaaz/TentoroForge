"""Building the phone screens in parallel does not fight over the project, and a missing toolchain is not retried for ever.

Every page of a build is written and compiled on its own thread and every round asked for the shared native project, which
was rewritten (about a hundred files) while the other threads' compiler read it: a half-written file was a compile error
sent back to the model. And when `npm install` could not run (no network), every screen's compile tried it again, up to
25 minutes each, one after another."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from services.blueprint import native_engineer, native_projection


@pytest.fixture(autouse=True)
def clean():
    native_engineer.forget_toolchain_failures()
    native_projection._PROJECTED.clear()
    yield
    native_engineer.forget_toolchain_failures()
    native_projection._PROJECTED.clear()


def test_a_toolchain_that_did_not_install_is_not_installed_again_by_the_next_screen(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_NATIVE_TOOLCHAIN", str(tmp_path / "tc"))
    monkeypatch.setattr(native_engineer.shutil, "which", lambda name: "npm")
    calls = []

    def run(*a, **k):
        calls.append(a)
        return SimpleNamespace(returncode=1, stderr="getaddrinfo ENOTFOUND registry.npmjs.org", stdout="")

    for _ in range(5):
        assert native_engineer.ensure_toolchain(run=run) is None
    assert len(calls) == 1, "one `npm install`, not one per screen and round"
    native_engineer.forget_toolchain_failures()
    assert native_engineer.ensure_toolchain(run=run) is None and len(calls) == 2, "forgotten: tried again"


def test_the_project_is_projected_once_for_every_thread_that_asks(monkeypatch, tmp_path):
    seen = {"fixed": 0, "modules": 0}

    def fixed(doc, out):
        seen["fixed"] += 1
        time.sleep(0.05)                       # long enough for every other thread to arrive meanwhile
        return []

    def modules(doc, out):
        seen["modules"] += 1
        return []

    monkeypatch.setattr(native_projection, "project_fixed_half", fixed)
    monkeypatch.setattr(native_projection, "project_generated_modules", modules)
    (tmp_path / "native").mkdir()
    doc = {"application": {"name": "A"}}
    threads = [threading.Thread(target=native_projection.ensure_native_project, args=(doc, tmp_path)) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert seen == {"fixed": 1, "modules": 1}


def test_a_changed_document_is_projected_again(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(native_projection, "project_fixed_half", lambda d, o: seen.append(1) or [])
    monkeypatch.setattr(native_projection, "project_generated_modules", lambda d, o: [])
    (tmp_path / "native").mkdir()
    native_projection.ensure_native_project({"application": {"name": "A"}}, tmp_path)
    native_projection.ensure_native_project({"application": {"name": "A"}}, tmp_path)
    native_projection.ensure_native_project({"application": {"name": "B"}}, tmp_path)
    assert len(seen) == 2


def test_a_file_is_replaced_in_one_step_never_written_in_place(monkeypatch, tmp_path):
    """The new content goes to a sibling file and replaces the old one; the file itself is never opened for writing."""
    target = tmp_path / "src" / "sdk" / "schema.ts"
    native_projection._write(target, "old")
    steps = []
    real_replace = native_projection.os.replace
    monkeypatch.setattr(native_projection.os, "replace",
                        lambda src, dst: steps.append((src, str(dst))) or real_replace(src, dst))
    assert native_projection._write(target, "new") is True
    assert len(steps) == 1 and steps[0][1] == str(target) and steps[0][0] != str(target)
    assert target.read_text("utf-8") == "new"
    assert not list(target.parent.glob("*.tmp")), "no temporary file is left behind"
    assert native_projection._write(target, "new") is False, "unchanged content is not written at all"


def test_a_file_held_open_by_a_reader_is_still_written(monkeypatch, tmp_path):
    """Windows refuses to replace a file another process has open: the write falls back to in place, it does not fail."""
    target = tmp_path / "schema.ts"
    native_projection._write(target, "old")

    def refuse(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(native_projection.os, "replace", refuse)
    monkeypatch.setattr(native_projection.threading.Event, "wait", lambda self, t=None: True)
    native_projection._write(target, "new")
    assert target.read_text("utf-8") == "new"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(__import__("os").name == "nt", reason="a Python reader holds the file open on Windows; Node's tsc does not")
def test_a_reader_racing_the_writer_never_sees_half_a_file(tmp_path):
    target = tmp_path / "src" / "sdk" / "schema.ts"
    old, new = "A" * 200_000, "B" * 200_000
    native_projection._write(target, old)
    stop, torn = threading.Event(), []

    def read():
        while not stop.is_set():
            try:
                text = target.read_text(encoding="utf-8")
            except OSError:
                continue
            if text not in (old, new):
                torn.append(len(text))

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        for i in range(60):
            native_projection._write(target, new if i % 2 == 0 else old)
    finally:
        stop.set()
        reader.join(timeout=5)
    assert torn == []

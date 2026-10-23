"""`next build` can end with `uncaughtException [Error: kill EPERM]` on Windows: Windows says no to ending a worker that has
already ended. The platform's `assemble` step took that as a failed build (Cart Buddy, 2026-10-22), and the same command run
by hand exited 0. That one error is tried once more. A compile error never is, and a second failure is still a failure."""
from __future__ import annotations

import types

import pytest

from services.blueprint import assembly

KILL = "uncaughtException [Error: kill EPERM] { errno: -4048, code: 'EPERM', syscall: 'kill' }"


def runner(*replies):
    calls = []

    def run(cmd, **kw):
        calls.append(tuple(cmd))
        rc, out, err = replies[min(len(calls), len(replies)) - 1]
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    return run, calls


def build(monkeypatch, tmp_path, *replies):
    run, calls = runner(*replies)
    monkeypatch.setattr(assembly.subprocess if hasattr(assembly, "subprocess") else __import__("subprocess"), "run", run)
    out = assembly.verify_build(tmp_path, install=False, dispatches=False)
    return out, calls


def test_a_kill_race_is_tried_once_more_and_a_good_second_run_passes(monkeypatch, tmp_path):
    out, calls = build(monkeypatch, tmp_path, (1, "", KILL), (0, "compiled", ""))
    assert out["build"] == 0 and len(calls) == 2


def test_a_build_that_passes_is_run_once(monkeypatch, tmp_path):
    out, calls = build(monkeypatch, tmp_path, (0, "compiled", ""))
    assert out["build"] == 0 and len(calls) == 1


def test_a_compile_error_is_never_tried_again(monkeypatch, tmp_path):
    with pytest.raises(assembly.BuildFailed):
        build(monkeypatch, tmp_path, (1, "Failed to compile.\n./src/app/page.tsx\nType error: nope", ""), (0, "compiled", ""))
    run, calls = runner((1, "Failed to compile.\nType error: nope", ""), (0, "compiled", ""))
    monkeypatch.setattr(__import__("subprocess"), "run", run)
    with pytest.raises(assembly.BuildFailed):
        assembly.verify_build(tmp_path, install=False, dispatches=False)
    assert len(calls) == 1


def test_a_second_kill_race_is_still_a_failure(monkeypatch, tmp_path):
    with pytest.raises(assembly.BuildFailed):
        build(monkeypatch, tmp_path, (1, "", KILL), (1, "", KILL))

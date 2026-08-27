"""Unit tests for SV-7 git-helpers in services.self_verify_pass.

Uses a real git repo in tmp_path (git is a hard dep everywhere Forge
runs) — mocking git would only test the mock.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.self_verify_pass import (
    _git_head,
    _git_revert_head,
    _sig_from_raw_fault,
    _stamp_verify_commit,
)


def _init_repo(tmp: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.co"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp, check=True)


def _commit(tmp: Path, filename: str, msg: str) -> str:
    (tmp / filename).write_text("data")
    subprocess.run(["git", "add", filename], cwd=tmp, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg, "--no-verify"],
                   cwd=tmp, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp,
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_git_head_returns_none_outside_repo(tmp_path: Path) -> None:
    assert _git_head(str(tmp_path)) is None


def test_git_head_returns_sha_inside_repo(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    sha = _commit(tmp_path, "a.txt", "initial")
    assert _git_head(str(tmp_path)) == sha


def test_stamp_verify_commit_amends_message(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "a.txt", "initial")
    _stamp_verify_commit(str(tmp_path), "[verify:run_abc:round_1]")
    body = subprocess.run(
        ["git", "log", "-1", "--format=%B"], cwd=tmp_path,
        capture_output=True, text=True, check=True,
    ).stdout
    assert "[verify:run_abc:round_1]" in body
    assert "initial" in body  # original message preserved


def test_stamp_is_idempotent(tmp_path: Path) -> None:
    """Stamping twice with same tag doesn't duplicate."""
    _init_repo(tmp_path)
    _commit(tmp_path, "a.txt", "initial")
    _stamp_verify_commit(str(tmp_path), "[verify:x:round_1]")
    _stamp_verify_commit(str(tmp_path), "[verify:x:round_1]")
    body = subprocess.run(
        ["git", "log", "-1", "--format=%B"], cwd=tmp_path,
        capture_output=True, text=True, check=True,
    ).stdout
    assert body.count("[verify:x:round_1]") == 1


def test_git_revert_head_undoes_last_commit(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    sha1 = _commit(tmp_path, "a.txt", "first")
    _commit(tmp_path, "b.txt", "second")
    assert (tmp_path / "b.txt").exists()
    ok = _git_revert_head(str(tmp_path))
    assert ok is True
    assert not (tmp_path / "b.txt").exists()
    assert _git_head(str(tmp_path)) == sha1


def test_sig_from_raw_fault_classifies_correctly() -> None:
    raw = {
        "interaction_id": "route:/",
        "interaction": {"id": "route:/", "kind": "route",
                        "route": "/", "requires_auth": True},
        "evidence": {"status": 500, "stack_trace": "ENOENT /var/task/x.json"},
    }
    assert _sig_from_raw_fault(raw) == "SSR_500_ENOENT_JSON"


def test_sig_from_raw_fault_unclassified_on_junk() -> None:
    assert _sig_from_raw_fault({}) == "UNCLASSIFIED"

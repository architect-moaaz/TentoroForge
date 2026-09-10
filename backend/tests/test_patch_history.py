"""Tests for services/patch_history.py (Phase 1b — revert_last_patch)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.patch_history import (
    get_last_patch,
    revert_last_patch,
)


def _run(cwd: Path, *args: str):
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with two commits: initial + one Smith-style edit."""
    _run(tmp_path, "git", "init", "-q", "-b", "main")
    _run(tmp_path, "git", "config", "user.email", "smith@test")
    _run(tmp_path, "git", "config", "user.name", "Smith")
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-q", "-m", "initial")

    # Simulate a Smith edit — modify a file, commit it.
    (tmp_path / "app.py").write_text("print('goodbye')\n", encoding="utf-8")
    (tmp_path / "src.json").write_text('{"changed": true}\n', encoding="utf-8")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-q", "-m",
         "fix(page): remove Department field")
    return tmp_path


class TestGetLastPatch:
    def test_returns_last_commit_metadata(self, repo: Path):
        r = get_last_patch(str(repo))
        assert r["ok"] is True
        assert r["subject"] == "fix(page): remove Department field"
        assert set(r["files"]) == {"app.py", "src.json"}
        assert len(r["sha"]) >= 7

    def test_not_a_git_repo(self, tmp_path: Path):
        (tmp_path / "empty.txt").write_text("", encoding="utf-8")
        r = get_last_patch(str(tmp_path))
        assert r["ok"] is False
        assert "git" in r["error"].lower()

    def test_missing_dir(self):
        r = get_last_patch("/nonexistent/definitely/nope")
        assert r["ok"] is False


class TestRevertLastPatch:
    def test_reverts_and_creates_new_commit(self, repo: Path):
        before = (repo / "app.py").read_text(encoding="utf-8")
        assert before == "print('goodbye')\n"

        r = revert_last_patch(str(repo))
        assert r["ok"] is True
        assert r["subject"] == "fix(page): remove Department field"
        assert set(r["files"]) == {"app.py", "src.json"}
        assert "restored" in r["summary"].lower()

        # The revert is a NEW commit — the original stays in the log.
        log = subprocess.run(
            ["git", "log", "--pretty=format:%s"],
            cwd=str(repo), capture_output=True, text=True,
        )
        subjects = log.stdout.splitlines()
        # Newest first: revert message → original message → initial.
        assert len(subjects) == 3
        assert "fix(page): remove Department field" in subjects[1]

        # File content is restored to the state before the reverted commit.
        after = (repo / "app.py").read_text(encoding="utf-8")
        assert after == "print('hello')\n"
        assert not (repo / "src.json").exists()

    def test_no_prior_commit(self, tmp_path: Path):
        # Repo with no commits at all.
        _run(tmp_path, "git", "init", "-q", "-b", "main")
        _run(tmp_path, "git", "config", "user.email", "x@y.z")
        _run(tmp_path, "git", "config", "user.name", "x")
        r = revert_last_patch(str(tmp_path))
        assert r["ok"] is False

    def test_not_a_git_repo(self, tmp_path: Path):
        r = revert_last_patch(str(tmp_path))
        assert r["ok"] is False

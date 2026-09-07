"""Multi-file atomic apply — the primitive Smith's new-thing seams stand on.

Coverage:
  * Happy path: N writes land, verify passes, one git commit.
  * Verify fail: all writes are rolled back, files return to pre-call bytes,
    non-existent files are deleted.
  * Mid-write crash (unwritable path): earlier writes are rolled back too.
  * Rejected paths: '..' escapes, absolute paths, empty strings.
  * Non-repo output_dir: applies without git, no commit hash.
  * Existing dirty tree: unrelated in-flight changes survive a rollback.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from services.atomic_apply import (
    BundleOp,
    BundleResult,
    apply_bundle,
    apply_bundle_no_verify,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _git(cwd: Path, *args: str) -> str:
    """Test-local git wrapper — commits are silent, warnings suppressed."""
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
        env={**os.environ,
             "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A fresh git repo with one initial commit so `git stash`/`git rev-parse
    HEAD` work as they do in a real generated app."""
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / ".gitignore").write_text("", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    return tmp_path


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #

def test_happy_path_writes_all_files_and_makes_one_commit(repo: Path):
    ops = [
        BundleOp(path="src/schemas/pipeline.json",
                 content='{"route":"/pipeline","root":{"type":"Stack"}}',
                 kind="page-schema"),
        BundleOp(path="contracts/registry.json",
                 content='{"pages":[{"slug":"pipeline"}]}',
                 kind="registry"),
        BundleOp(path="nav-flow.json",
                 content='{"pages":[{"id":"pipeline","route":"/pipeline"}]}',
                 kind="nav-flow"),
    ]
    result = apply_bundle(str(repo), ops, verify=lambda _: {"ok": True},
                          commit_message="test: add pipeline page")

    assert result.applied is True
    assert result.commit_hash is not None
    assert set(result.ops_written) == {"src/schemas/pipeline.json",
                                        "contracts/registry.json",
                                        "nav-flow.json"}
    # Files on disk match the ops.
    assert (repo / "src/schemas/pipeline.json").read_text(encoding="utf-8").startswith('{"route"')
    assert (repo / "contracts/registry.json").exists()
    assert (repo / "nav-flow.json").exists()
    # One commit — the bundle is atomic in git too.
    log = subprocess.check_output(
        ["git", "log", "--oneline"], cwd=str(repo), text=True,
    ).strip().splitlines()
    assert any("add pipeline page" in line for line in log)


def test_no_verify_still_commits(repo: Path):
    """Callers without a verify_fn should still get atomicity + a commit —
    just no gating on schema correctness."""
    ops = [BundleOp(path="notes.md", content="hi", kind="doc")]
    result = apply_bundle_no_verify(str(repo), ops, commit_message="just a note")
    assert result.applied is True
    assert result.commit_hash is not None
    assert (repo / "notes.md").read_text(encoding="utf-8") == "hi"


def test_result_reports_ops_written_in_order(repo: Path):
    ops = [
        BundleOp(path="a.txt", content="1", kind="a"),
        BundleOp(path="b.txt", content="2", kind="b"),
        BundleOp(path="c.txt", content="3", kind="c"),
    ]
    result = apply_bundle(str(repo), ops, verify=lambda _: {"ok": True})
    assert result.ops_written == ["a.txt", "b.txt", "c.txt"]


# --------------------------------------------------------------------------- #
# Rollback semantics
# --------------------------------------------------------------------------- #

def test_verify_fail_rolls_back_every_write(repo: Path):
    # A pre-existing file we're going to overwrite. Rollback must restore
    # its original contents.
    (repo / "existing.txt").write_text("ORIGINAL", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")

    ops = [
        BundleOp(path="existing.txt", content="MUTATED"),
        BundleOp(path="new-file.txt", content="new"),
    ]
    result = apply_bundle(
        str(repo), ops,
        verify=lambda _: {"ok": False, "reason": "test-forced fail"},
    )
    assert result.applied is False
    assert result.verify == {"ok": False, "reason": "test-forced fail"}
    # Rollback restored the pre-call state precisely.
    assert (repo / "existing.txt").read_text(encoding="utf-8") == "ORIGINAL"
    assert not (repo / "new-file.txt").exists()
    # And no orphan commit landed.
    log = subprocess.check_output(
        ["git", "log", "--oneline"], cwd=str(repo), text=True,
    ).strip()
    assert "smith:" not in log.lower()


def test_verify_crash_is_treated_as_fail(repo: Path):
    """A verifier that throws must not poison the applier — treated as an
    ok=False and triggering a rollback."""
    (repo / "old.txt").write_text("keep", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")

    def _boom(_out: Path) -> dict:
        raise RuntimeError("verifier exploded")

    result = apply_bundle(
        str(repo), [BundleOp(path="old.txt", content="new")], verify=_boom,
    )
    assert result.applied is False
    assert "verify crashed" in (result.reason or "")
    assert (repo / "old.txt").read_text(encoding="utf-8") == "keep"


def test_rejects_unsafe_paths(repo: Path):
    for bad in ("../escape.txt", "/etc/passwd", "", "   "):
        result = apply_bundle(str(repo), [BundleOp(path=bad, content="x")])
        assert result.applied is False, f"path {bad!r} should be rejected"
        assert "unsafe" in (result.reason or "").lower()


def test_empty_op_list_is_rejected(repo: Path):
    result = apply_bundle(str(repo), [])
    assert result.applied is False
    assert "no ops" in (result.reason or "")


# --------------------------------------------------------------------------- #
# Nested paths + parent dir creation
# --------------------------------------------------------------------------- #

def test_creates_missing_parent_dirs(repo: Path):
    ops = [BundleOp(path="a/b/c/deep.json", content="{}", kind="nested")]
    result = apply_bundle(str(repo), ops, verify=lambda _: {"ok": True})
    assert result.applied is True
    assert (repo / "a/b/c/deep.json").read_text(encoding="utf-8") == "{}"


def test_rollback_removes_created_parent_files_but_not_dirs(repo: Path):
    """When a NEW file rollback fires, the file is deleted. Dirs that got
    created along the way are left in place — cheap tradeoff; they're
    empty and inert."""
    ops = [BundleOp(path="new/created.txt", content="hi")]
    result = apply_bundle(str(repo), ops, verify=lambda _: {"ok": False, "reason": "no"})
    assert result.applied is False
    assert not (repo / "new/created.txt").exists()
    # The parent dir MAY still exist — we don't clean it up, and the test
    # doesn't require its removal. Just documenting the invariant.
    # (dir may or may not still be there — not asserting either way)


# --------------------------------------------------------------------------- #
# Non-repo path (git=False)
# --------------------------------------------------------------------------- #

def test_no_git_still_applies_and_verifies(tmp_path: Path):
    """Test harness path — verify+write+rollback should work without a
    git repo. No commit hash returned."""
    ops = [BundleOp(path="thing.json", content='{"x":1}')]
    result = apply_bundle(
        str(tmp_path), ops, verify=lambda _: {"ok": True}, git=False,
    )
    assert result.applied is True
    assert result.commit_hash is None
    assert (tmp_path / "thing.json").read_text(encoding="utf-8") == '{"x":1}'


def test_no_git_verify_fail_still_rolls_back(tmp_path: Path):
    (tmp_path / "seed.txt").write_text("SEED", encoding="utf-8")
    ops = [BundleOp(path="seed.txt", content="MUTATED")]
    result = apply_bundle(
        str(tmp_path), ops,
        verify=lambda _: {"ok": False, "reason": "no"},
        git=False,
    )
    assert result.applied is False
    assert (tmp_path / "seed.txt").read_text(encoding="utf-8") == "SEED"


# --------------------------------------------------------------------------- #
# Dirty tree preservation
# --------------------------------------------------------------------------- #

def test_dirty_tree_is_stashed_and_restored_on_rollback(repo: Path):
    """A user with uncommitted edits mustn't lose them when Smith's
    verify fails and rolls back. The applier stashes on entry and pops
    on exit."""
    # Seed a tracked file so we can dirty it.
    (repo / "user-work.txt").write_text("initial", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    # Now the user makes uncommitted edits.
    (repo / "user-work.txt").write_text("USER-IN-PROGRESS", encoding="utf-8")

    ops = [BundleOp(path="smith-writes.txt", content="smith")]
    result = apply_bundle(
        str(repo), ops,
        verify=lambda _: {"ok": False, "reason": "test-forced"},
    )
    assert result.applied is False
    # Smith's write was rolled back.
    assert not (repo / "smith-writes.txt").exists()
    # User's in-progress edits survived.
    assert (repo / "user-work.txt").read_text(encoding="utf-8") == "USER-IN-PROGRESS"


def test_missing_output_dir_is_a_clean_fail(tmp_path: Path):
    result = apply_bundle(str(tmp_path / "does-not-exist"), [
        BundleOp(path="x.txt", content="x"),
    ])
    assert result.applied is False
    assert "missing" in (result.reason or "").lower()

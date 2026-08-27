"""V&F 2.0 M3 — unit tests for the round-level regression guard.

Covers:
    - snapshot_before_round returns commit_sha for a real git repo
    - snapshot_before_round returns empty commit_sha for a non-repo dir
    - compare_and_maybe_revert triggers revert when a previously-passing
      interaction now fails
    - compare_and_maybe_revert triggers revert when total pass count drops
    - compare_and_maybe_revert does nothing when pass count improves / same
    - compare_and_maybe_revert on non-repo dir returns
      reverted=False, reason='not-a-repo'
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.journey_verifier.regression_guard import (
    RevertResult,
    RoundSnapshot,
    compare_and_maybe_revert,
    snapshot_before_round,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _init_repo(path: Path) -> str:
    """Init a git repo at `path`, drop a file, commit, return HEAD sha."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name",  "t"],   cwd=path, check=True)
    (path / "seed.txt").write_text("seed")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed", "--no-verify",
         "--no-gpg-sign"],
        cwd=path, check=True,
    )
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path, check=True, capture_output=True, text=True,
    )
    return r.stdout.strip()


def _add_commit(path: Path, name: str, body: str) -> str:
    (path / name).write_text(body)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", f"add {name}", "--no-verify",
         "--no-gpg-sign"],
        cwd=path, check=True,
    )
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path, check=True, capture_output=True, text=True,
    )
    return r.stdout.strip()


def _fault(iid: str) -> dict:
    return {"interaction": {"id": iid, "route": f"/{iid}"}, "evidence": {}}


# ── snapshot_before_round ──────────────────────────────────────────────────


def test_snapshot_returns_commit_sha_for_repo(tmp_path: Path):
    sha = _init_repo(tmp_path)
    snap = snapshot_before_round(tmp_path, faults_before=[_fault("a")])
    assert isinstance(snap, RoundSnapshot)
    assert snap.commit_sha == sha
    assert snap.fault_count == 1


def test_snapshot_returns_empty_sha_for_non_repo(tmp_path: Path):
    # tmp_path is NOT a git repo (no `.git/`).
    snap = snapshot_before_round(tmp_path, faults_before=[])
    assert snap.commit_sha == ""
    assert snap.fault_count == 0


def test_snapshot_records_pass_set_from_caller(tmp_path: Path):
    """The snapshot's ``interaction_pass_set`` is caller-supplied — the
    guard only knows the pre-round FAILING ids from the fault list, so
    the passing set has to be handed in (empty when unknown)."""
    _init_repo(tmp_path)
    snap = snapshot_before_round(
        tmp_path, faults_before=[_fault("a"), _fault("b")],
        passing_ids=["x", "y", "z"],
    )
    assert set(snap.interaction_pass_set) == {"x", "y", "z"}
    assert snap.fault_count == 2
    assert snap.pass_count == 3


# ── compare_and_maybe_revert ────────────────────────────────────────────────


def test_revert_on_newly_broken_interaction(tmp_path: Path):
    """An interaction that was passing (in pre-round passing set) but
    is failing after the round → regression → revert."""
    sha_before = _init_repo(tmp_path)
    snap = snapshot_before_round(
        tmp_path, faults_before=[_fault("a")],
        passing_ids=["b", "c"],
    )
    # A new commit that supposedly comes from the Smith round.
    _add_commit(tmp_path, "bad.txt", "regressed edit")
    # Round-2 faults: "b" is now failing but "b" was not in round-1's
    # failing set → newly broken.
    round2 = [_fault("a"), _fault("b")]
    res = compare_and_maybe_revert(snap, round2, tmp_path)
    assert isinstance(res, RevertResult)
    assert res.reverted is True
    assert "b" in res.newly_broken_ids
    # And HEAD should have moved back to the pre-round sha.
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    assert r.stdout.strip() == sha_before


def test_revert_on_pass_count_drop(tmp_path: Path):
    """No newly-broken IDs, but the total fault count went UP — still
    treated as a regression (a fault could have been reworded into a
    different-id fault the id-diff wouldn't catch)."""
    sha_before = _init_repo(tmp_path)
    snap = snapshot_before_round(
        tmp_path, faults_before=[_fault("a")],
    )
    _add_commit(tmp_path, "worse.txt", "worse")
    round2 = [_fault("a"), _fault("z"), _fault("y")]  # count went from 1 → 3
    res = compare_and_maybe_revert(snap, round2, tmp_path)
    assert res.reverted is True
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    assert r.stdout.strip() == sha_before


def test_no_revert_when_faults_improve(tmp_path: Path):
    sha_before = _init_repo(tmp_path)
    snap = snapshot_before_round(
        tmp_path, faults_before=[_fault("a"), _fault("b")],
    )
    sha_after = _add_commit(tmp_path, "good.txt", "good")
    # Round-2 has fewer faults and no NEW ids.
    round2 = [_fault("a")]
    res = compare_and_maybe_revert(snap, round2, tmp_path)
    assert res.reverted is False
    assert res.newly_broken_ids == []
    # HEAD is unchanged.
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    assert r.stdout.strip() == sha_after


def test_no_revert_when_faults_equal(tmp_path: Path):
    _init_repo(tmp_path)
    snap = snapshot_before_round(
        tmp_path, faults_before=[_fault("a")],
    )
    _add_commit(tmp_path, "same.txt", "same")
    round2 = [_fault("a")]
    res = compare_and_maybe_revert(snap, round2, tmp_path)
    assert res.reverted is False


def test_non_repo_dir_returns_not_a_repo(tmp_path: Path):
    """A non-git output_dir → snapshot commit_sha is empty → revert is
    a no-op with reason='not-a-repo'."""
    snap = snapshot_before_round(tmp_path, faults_before=[_fault("a")])
    assert snap.commit_sha == ""
    res = compare_and_maybe_revert(snap, [_fault("a"), _fault("b")], tmp_path)
    assert res.reverted is False
    assert res.reason == "not-a-repo"


def test_reset_to_recorded_sha_even_after_multiple_commits(tmp_path: Path):
    """Regression: even after the round wrote MULTIPLE commits, the
    guard rewinds all the way back to the recorded sha (not HEAD~1).
    Guards against a partial revert leaving a half-broken state."""
    sha_before = _init_repo(tmp_path)
    snap = snapshot_before_round(
        tmp_path, faults_before=[_fault("a")],
    )
    _add_commit(tmp_path, "one.txt", "1")
    _add_commit(tmp_path, "two.txt", "2")
    round2 = [_fault("a"), _fault("b")]  # fault count went 1 → 2
    res = compare_and_maybe_revert(snap, round2, tmp_path)
    assert res.reverted is True
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    assert r.stdout.strip() == sha_before

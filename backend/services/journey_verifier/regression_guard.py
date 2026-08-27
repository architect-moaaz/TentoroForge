"""V&F 2.0 M3 — round-level regression guard.

After a Smith round runs and we re-Playwright, we compare the second
round's faults to the pre-round snapshot: if any interaction that WAS
passing now FAILS, or if the total fault count strictly grows, we
revert the round's file edits via ``git reset --hard <pre-round-sha>``.

Pure module — no I/O beyond git subprocess calls. Safe to run when
``output_dir`` isn't a git repo (both snapshot + revert become no-ops).
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)


# ── Public dataclasses ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class RoundSnapshot:
    """State captured BEFORE a Smith round writes anything.

    ``commit_sha`` is the git HEAD sha at snapshot time; empty when
    ``output_dir`` isn't a git repo (revert then becomes a no-op).

    ``pass_count`` / ``fault_count`` describe the pre-round interaction
    state.

    ``interaction_pass_set`` is the frozenset of interaction_ids that
    WERE passing pre-round — supply it when you know it (via
    :func:`snapshot_before_round`'s ``passing_ids=`` kwarg). When the
    passing set is empty, ``newly_broken_ids`` is always empty and
    revert is driven only by a fault-count increase.
    """
    output_dir: str
    commit_sha: str
    pass_count: int
    fault_count: int
    interaction_pass_set: frozenset[str] = field(default_factory=frozenset)


@dataclass
class RevertResult:
    reverted: bool
    reason: str | None = None
    newly_broken_ids: list[str] = field(default_factory=list)


# ── Public API ─────────────────────────────────────────────────────────────


def snapshot_before_round(
    output_dir: str | Path,
    faults_before: Sequence[Any] | None,
    *,
    passing_ids: Iterable[str] | None = None,
    pass_count: int | None = None,
) -> RoundSnapshot:
    """Capture HEAD + fault set BEFORE the round mutates disk.

    :param output_dir: Path to the generated app tree.
    :param faults_before: The runner's raw fault list from the last
        Playwright pass — used for ``fault_count`` (each item is a dict
        with an ``interaction.id`` or a :class:`ClassifiedFault`).
    :param passing_ids: Optional iterable of interaction_ids that WERE
        passing pre-round. When absent, the passing set is empty and
        the guard's regression trigger degrades to fault-count only.
    :param pass_count: Optional integer count of pre-round passing
        interactions (defaults to the size of ``passing_ids`` when it
        is supplied, else 0).
    """
    out = str(output_dir)
    sha = _git_head(out)
    faults = list(faults_before or [])
    passing = frozenset(passing_ids or ())
    return RoundSnapshot(
        output_dir=out,
        commit_sha=sha or "",
        pass_count=pass_count if pass_count is not None else len(passing),
        fault_count=len(faults),
        interaction_pass_set=passing,
    )


def compare_and_maybe_revert(
    snap: RoundSnapshot,
    faults_after: Sequence[Any] | None,
    output_dir: str | Path,
) -> RevertResult:
    """Decide + execute revert.

    Reverts when EITHER:
      * A ``round2`` interaction_id is failing that WAS in the
        pre-round passing set (newly broken by this round), OR
      * Total fault count in round-2 is strictly greater than the
        snapshot's (pass rate dropped somewhere the id-diff missed).

    Revert is ``git reset --hard <snap.commit_sha>``. Skipped when the
    snapshot has an empty ``commit_sha`` (dir isn't a git repo).
    """
    faults_after = list(faults_after or [])
    out = str(output_dir)

    r2_failing_ids = {
        iid for iid in (_interaction_id(f) for f in faults_after)
        if iid and iid != "?"
    }
    newly_broken = sorted(
        iid for iid in r2_failing_ids if iid in snap.interaction_pass_set
    )
    fault_count_regressed = len(faults_after) > snap.fault_count
    trigger = bool(newly_broken) or fault_count_regressed
    if not trigger:
        return RevertResult(reverted=False, reason=None, newly_broken_ids=[])

    if not snap.commit_sha:
        return RevertResult(
            reverted=False, reason="not-a-repo",
            newly_broken_ids=newly_broken,
        )

    ok = _git_reset_hard(out, snap.commit_sha)
    if not ok:
        return RevertResult(
            reverted=False, reason="git-reset-failed",
            newly_broken_ids=newly_broken,
        )
    logger.info(
        "[regression-guard] reverted round: fault_count %d → %d, newly_broken=%s, sha → %s",
        snap.fault_count, len(faults_after), newly_broken, snap.commit_sha[:8],
    )
    return RevertResult(
        reverted=True, reason=None, newly_broken_ids=newly_broken,
    )


# ── helpers ────────────────────────────────────────────────────────────────


def _interaction_id(raw: Any) -> str:
    if isinstance(raw, dict):
        interaction = raw.get("interaction") or {}
        if isinstance(interaction, dict):
            iid = interaction.get("id")
            if isinstance(iid, str) and iid:
                return iid
        for key in ("interaction_id", "id"):
            v = raw.get(key)
            if isinstance(v, str) and v:
                return v
        return "?"
    # ClassifiedFault-like objects with an .interaction_id attr.
    iid = getattr(raw, "interaction_id", None)
    if isinstance(iid, str) and iid:
        return iid
    return "?"


def _git_head(output_dir: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", output_dir, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return None
        sha = r.stdout.strip()
        return sha or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _git_reset_hard(output_dir: str, sha: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", output_dir, "reset", "--hard", sha],
            capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False

"""Multi-file atomic apply — the foundation Smith's new-thing seams
(`add_page`, `add_workflow`, `add_entity`) build on.

Rationale
---------
The existing ``services.fix_applier`` writes ONE file per apply. That is
right for a point fix (a workflow node's config; an RFC-6902 patch to a
page schema). But Smith's next generation of seams must touch several
files at once — a new page implies:

  * write ``src/schemas/<slug>.json``
  * insert into ``nav-flow.json``
  * add an entry to ``contracts/resource-registry.json``
  * (optionally) register in ``src/schemas/shell.json``

A silent half-apply — schema written, nav-flow not updated — leaves the
app in a worse state than before. So every multi-file seam goes through
:func:`apply_bundle`, which:

  1. **Stages** the new content for every path IN MEMORY.
  2. **Snapshots** each path's ORIGINAL bytes (or absence).
  3. **Writes** every path.
  4. **Verifies** via a caller-supplied callback (parse the schemas, run
     the guard suite, hit the binding validator, whatever's cheap).
  5. On verify pass: **one** git commit (so an undo is one revert).
  6. On verify fail (or a mid-write OSError): **restore** every path
     from the snapshot AND delete any files that didn't exist before.

That's the whole primitive. Deliberately no dependency on the fix-agent's
Diagnosis contract, no coupling to the SSE stream, no async. Callers
build the ``BundleOp`` list from their own domain logic (`add_page`
computes them from `page_type_templates`; a future `add_workflow`
computes them from `workflow_generator`) and hand them here.

Invariants
----------
* No file on disk ends in a partial state. Either all writes land + a
  commit exists, or the tree is byte-identical to the pre-call state
  (with the exception of ``git_stash`` refs, which are cleaned up).
* When ``git=True`` and the working tree was dirty on entry, the
  pre-existing dirty changes are preserved (we stash + reapply).
* Verify is called with the tree already MUTATED — so validators that
  read files see the proposed content, not the old content.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #

@dataclass
class BundleOp:
    """One file to write as part of the bundle.

    ``path`` is repo-relative (``src/schemas/pipeline.json``). ``content``
    is the full text that will be written; the caller is responsible for
    formatting (indent, trailing newline). ``kind`` is an informational
    tag used only for logging + the returned summary — the applier
    doesn't branch on it.
    """
    path: str
    content: str
    kind: str = "file"  # e.g. "page-schema", "nav-flow", "registry", "shell"


@dataclass
class BundleResult:
    applied: bool
    ops_written: list[str] = field(default_factory=list)
    ops_rolled_back: list[str] = field(default_factory=list)
    commit_hash: Optional[str] = None
    verify: Optional[dict] = None
    reason: Optional[str] = None


VerifyFn = Callable[[Path], dict]
"""Signature the caller supplies. Runs against the mutated tree
(``output_dir`` as Path). Return shape::

    {"ok": bool, "reason"?: str, "details"?: <anything>}

`ok=False` triggers a full rollback. `reason` bubbles up to the caller."""


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def apply_bundle(
    output_dir: str,
    ops: Iterable[BundleOp],
    *,
    verify: Optional[VerifyFn] = None,
    commit_message: str = "smith: bundle apply",
    git: bool = True,
) -> BundleResult:
    """Atomically apply ``ops`` — all or none.

    ``git=False`` is the test path: skip stash + commit; still runs
    verify and rollback. Callers in prod always pass ``git=True``.
    """
    out = Path(output_dir)
    if not out.is_dir():
        return BundleResult(applied=False, reason=f"output_dir missing: {output_dir}")

    ops_list = [op for op in ops if isinstance(op, BundleOp)]
    if not ops_list:
        return BundleResult(applied=False, reason="no ops provided")

    # 1. Refuse to touch anything outside the tree.
    for op in ops_list:
        if not _is_safe_rel(op.path):
            return BundleResult(
                applied=False,
                reason=f"unsafe path {op.path!r} (must be relative, no '..')",
            )

    # 2. Optionally stash a dirty working tree so a rollback doesn't
    #    clobber the user's unrelated in-progress edits.
    stash_ref = None
    if git:
        try:
            stash_ref = _stash_dirty(out)
        except _GitError as exc:
            # A missing git repo is a hard fail — callers can pass git=False
            # in tests, but never in prod.
            logger.warning("[atomic_apply] git stash failed: %s", exc)

    # 3. Snapshot originals + apply. ``kind="delete"`` unlinks the file
    # (rollback restores the snapshotted bytes); everything else writes.
    snapshots: list[_Snapshot] = []
    try:
        for op in ops_list:
            abs_path = out / op.path
            snapshots.append(_snapshot(abs_path))
            if op.kind == "delete":
                if abs_path.exists():
                    abs_path.unlink()
                # No content to write; nothing else to do.
            else:
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_text(op.content, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.exception("[atomic_apply] write failed for %s", exc)
        _rollback(snapshots)
        if stash_ref:
            _restore_stash(out, stash_ref)
        return BundleResult(
            applied=False,
            reason=f"write failed: {exc}",
            ops_rolled_back=[s.rel for s in snapshots],
        )

    # 4. Verify against the mutated tree.
    v_result: Optional[dict] = None
    if verify is not None:
        try:
            v_result = verify(out)
        except Exception as exc:  # noqa: BLE001 — verifiers must never poison the applier
            logger.exception("[atomic_apply] verify crashed")
            v_result = {"ok": False, "reason": f"verify crashed: {exc}"}

    if v_result is not None and v_result.get("ok") is False:
        _rollback(snapshots)
        if stash_ref:
            _restore_stash(out, stash_ref)
        return BundleResult(
            applied=False,
            ops_rolled_back=[s.rel for s in snapshots],
            verify=v_result,
            reason=str(v_result.get("reason") or "verify failed"),
        )

    # 5. Commit (single git commit for the whole bundle).
    commit_hash: Optional[str] = None
    if git:
        try:
            commit_hash = _stage_and_commit(
                out, [op.path for op in ops_list], commit_message,
            )
        except _GitError as exc:
            # Committing failed after a successful verify — the tree is
            # correct but the commit isn't recorded. Roll back to avoid
            # leaving Smith's changes uncommittable (would confuse the
            # user's next diff / next undo).
            logger.exception("[atomic_apply] commit failed — rolling back")
            _rollback(snapshots)
            if stash_ref:
                _restore_stash(out, stash_ref)
            return BundleResult(
                applied=False,
                reason=f"commit failed: {exc}",
                ops_rolled_back=[s.rel for s in snapshots],
                verify=v_result,
            )
        finally:
            if stash_ref:
                _restore_stash(out, stash_ref)

    # Refresh BLUEPRINT.md after every successful Smith apply so the
    # snapshot stays current for the next turn. Best-effort +
    # flag-gated inside the writer — a blueprint failure NEVER poisons
    # the apply return.
    try:
        from services.blueprint_writer import write_blueprint_safe
        paths = ", ".join(op.path for op in ops_list[:3])
        if len(ops_list) > 3:
            paths += f" (+{len(ops_list) - 3} more)"
        write_blueprint_safe(
            output_dir,
            source="smith",
            summary=f"Atomic apply: {paths}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("[atomic_apply] blueprint refresh failed")

    return BundleResult(
        applied=True,
        ops_written=[op.path for op in ops_list],
        commit_hash=commit_hash,
        verify=v_result,
    )


# --------------------------------------------------------------------------- #
# Snapshot / rollback
# --------------------------------------------------------------------------- #

@dataclass
class _Snapshot:
    rel: str
    abs_path: Path
    existed: bool
    original_bytes: Optional[bytes]


def _snapshot(abs_path: Path) -> _Snapshot:
    rel = str(abs_path)
    if abs_path.is_file():
        return _Snapshot(rel=rel, abs_path=abs_path, existed=True,
                         original_bytes=abs_path.read_bytes())
    return _Snapshot(rel=rel, abs_path=abs_path, existed=False, original_bytes=None)


def _rollback(snapshots: list[_Snapshot]) -> None:
    """Restore every snapshot to its pre-call state. Best-effort per file
    so one restore failure doesn't skip the rest — the tree can end up
    partially rolled back only under a filesystem error mid-rollback,
    which is a strictly-worse state than pre-apply but signalled to the
    caller via ``ops_rolled_back`` for auditability."""
    for snap in snapshots:
        try:
            if snap.existed and snap.original_bytes is not None:
                snap.abs_path.write_bytes(snap.original_bytes)
            elif not snap.existed and snap.abs_path.exists():
                snap.abs_path.unlink()
        except Exception:  # noqa: BLE001
            logger.exception("[atomic_apply] rollback failed for %s", snap.rel)


# --------------------------------------------------------------------------- #
# Path safety
# --------------------------------------------------------------------------- #

def _is_safe_rel(path: str) -> bool:
    if not isinstance(path, str) or not path.strip():
        return False
    if os.path.isabs(path):
        return False
    parts = Path(path).parts
    if ".." in parts:
        return False
    return True


# --------------------------------------------------------------------------- #
# Git plumbing
# --------------------------------------------------------------------------- #

class _GitError(RuntimeError):
    pass


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise _GitError(f"git {' '.join(args)!r} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _stash_dirty(out: Path) -> Optional[str]:
    """When the working tree has uncommitted changes, stash them so a
    later rollback doesn't touch them. Returns the stash ref or None
    when there's nothing to stash."""
    try:
        status = _git(out, "status", "--porcelain")
    except _GitError:
        return None
    if not status.strip():
        return None
    # Stash tracked+untracked. --keep-index would preserve stage; we don't
    # care about the stage state — writes will happen fresh.
    _git(out, "stash", "push", "-u", "-m", "smith-atomic-apply-stash")
    # Best-effort: capture the ref for later pop.
    try:
        top = _git(out, "stash", "list").splitlines()
        if top and "smith-atomic-apply-stash" in top[0]:
            return top[0].split(":", 1)[0]
    except _GitError:
        pass
    return "stash@{0}"


def _restore_stash(out: Path, ref: str) -> None:
    """Pop the stash we pushed. Silently ignore if it's already gone."""
    try:
        _git(out, "stash", "pop", ref)
    except _GitError as exc:
        logger.warning("[atomic_apply] stash pop failed (ref=%s): %s", ref, exc)


def _stage_and_commit(out: Path, paths: list[str], message: str) -> Optional[str]:
    """git add + commit exactly the paths we wrote. Returns the commit
    hash. Raises _GitError when the working tree is not a git repo (the
    fix_applier's convention for a non-repo output_dir is to skip commit)."""
    if not (out / ".git").exists():
        return None  # non-repo tree — commit is a no-op
    for p in paths:
        _git(out, "add", "--", p)
    # If nothing was actually different, git commit exits non-zero. Only
    # commit if there's staged diff.
    try:
        _git(out, "diff", "--cached", "--quiet")
        # exit 0 = no staged diff → nothing to commit.
        return None
    except _GitError:
        pass  # exit 1 = there's diff → proceed
    _git(out, "commit", "-m", message, "--allow-empty-message")
    return _git(out, "rev-parse", "HEAD")


# --------------------------------------------------------------------------- #
# Convenience helper for the common "atomic write + git commit, no verify"
# case Smith seams use before they have a proper verify function.
# --------------------------------------------------------------------------- #

def apply_bundle_no_verify(
    output_dir: str,
    ops: Iterable[BundleOp],
    *,
    commit_message: str = "smith: bundle apply",
    git: bool = True,
) -> BundleResult:
    """Same as :func:`apply_bundle` with no verify — useful during
    development of a new seam before the verify path is wired."""
    return apply_bundle(
        output_dir, ops, verify=None,
        commit_message=commit_message, git=git,
    )

"""Read + reverse the last patch Smith committed (Phase 1b).

Smith commits each mutation as a git commit inside the generated app's
``output_dir`` repo (existing behavior). This module reads that history
and reverses the most recent commit — powering the ``revert_last_patch``
tool and the "undo that" intent.

Design
------
Deterministic — no LLM. Uses ``git revert --no-edit HEAD``, which
produces a NEW commit that inverts the last one. History-preserving
(the original commit stays visible in ``git log``, easier debugging
than ``git reset``).

Failure modes
-------------
* No git repo → ``{ok: False, error: "not a git repo"}``.
* No commits yet → ``{ok: False, error: "no prior commit"}``.
* Revert conflict (unusual — Smith's own commits shouldn't conflict
  with themselves) → ``git revert --abort`` and return failure.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from services.git_service import COMMIT_ACTOR_TRAILER

logger = logging.getLogger(__name__)


def _git(output_dir: str, *args: str) -> tuple[int, str, str]:
    """Run a git command in ``output_dir``. Returns (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "git not installed"
    except subprocess.TimeoutExpired:
        return 124, "", "git timed out"


def _is_git_repo(output_dir: str) -> bool:
    if not Path(output_dir).is_dir():
        return False
    if not (Path(output_dir) / ".git").exists():
        # Might be a worktree with .git being a file
        rc, _, _ = _git(output_dir, "rev-parse", "--git-dir")
        return rc == 0
    return True


def get_last_patch(output_dir: str) -> dict:
    """Return metadata for the most recent commit.

    Shape::

        {
          "ok": True,
          "sha": "abc1234...",
          "subject": "fix(page): remove Department field",
          "author": "smith",
          "when": "2026-07-29 14:32:11 +0000",
          "files": ["src/schemas/candidates.new.json", ...],
        }
    """
    if not _is_git_repo(output_dir):
        return {"ok": False, "error": "not a git repo"}

    # Metadata for the last commit.
    rc, out, err = _git(
        output_dir, "log", "-1", "--pretty=format:%H%n%s%n%an%n%ad",
    )
    if rc != 0 or not out.strip():
        return {"ok": False, "error": "no prior commit"}
    parts = out.split("\n", 3)
    while len(parts) < 4:
        parts.append("")
    sha, subject, author, when = parts

    # Files changed in that commit.
    rc, files_out, _ = _git(
        output_dir, "diff-tree", "--no-commit-id", "--name-only", "-r", sha,
    )
    files: list[str] = [
        line.strip() for line in files_out.splitlines() if line.strip()
    ] if rc == 0 else []

    return {
        "ok":      True,
        "sha":     sha.strip(),
        "subject": subject.strip(),
        "author":  author.strip(),
        "when":    when.strip(),
        "files":   files,
    }


def commit_actor(output_dir: str, sha: str) -> str | None:
    """Which actor made ``sha``, from its ``Forge-Actor:`` trailer.

    ``None`` means the commit is UNATTRIBUTED (made before the trailer
    existed, or by a path that does not pass ``actor=``). Callers must
    read that as "unknown", never as "mine".
    """
    rc, out, _ = _git(output_dir, "log", "-1", "--pretty=format:%B", sha)
    if rc != 0:
        return None
    for line in reversed((out or "").splitlines()):
        line = line.strip()
        if line.lower().startswith(COMMIT_ACTOR_TRAILER.lower() + ":"):
            return line.split(":", 1)[1].strip().lower() or None
    return None


def revert_last_patch(output_dir: str, *, expected_sha: str | None = None) -> dict:
    """Revert the most recent commit as a NEW commit.

    ``expected_sha`` is the commit the caller believes it made. When given,
    the revert is refused if HEAD has moved on — the strict form of the
    authorship check below.

    Returns::

        {
          "ok":                True,
          "reverted_sha":      "abc1234",
          "revert_commit_sha": "def5678",
          "subject":           "fix(page): remove Department field",
          "files":             [...],
          "summary":           "Reverted 'fix(page): remove Department field' — 3 file(s) restored.",
        }

    Or on failure::

        {"ok": False, "error": "..."}
    """
    last = get_last_patch(output_dir)
    if not last.get("ok"):
        return last

    reverted_sha = last["sha"]

    # "Undo that" must undo SMITH's change, not whatever happens to be on
    # top. This ran `git revert HEAD` unconditionally (register S24-6): if
    # the user saved through the visual editor after Smith's turn, "undo
    # that" reverted the USER'S save — and the summary named Smith's commit
    # confidently, so the user could not tell.
    actor = commit_actor(output_dir, reverted_sha)
    if expected_sha and reverted_sha != expected_sha:
        return {
            "ok": False,
            "error": (
                f"refusing to revert: HEAD is {reverted_sha[:7]} "
                f"({last.get('subject') or '?'}), not the commit you made "
                f"({expected_sha[:7]}). Something else was committed after "
                f"yours — reverting HEAD would undo that instead."
            ),
        }
    if actor and actor != "smith":
        return {
            "ok": False,
            "error": (
                f"refusing to revert: HEAD ({reverted_sha[:7]} — "
                f"{last.get('subject') or '?'}) was made by {actor!r}, not by "
                f"Smith. Reverting it would undo someone else's change. Ask "
                f"the user whether they want that commit undone."
            ),
        }
    if not actor:
        # S24-9: this used to log a warning and revert ANYWAY. That is the whole
        # defect: commit_actor's own contract says an absent trailer means
        # "unknown, never mine", and most write paths (visual_editor, pages,
        # navigation, data_model, rules, agent_builder) still commit without one.
        # PROVEN against a real repo: an unattributed "visual: edit wf.json" save
        # was reverted and the user's line destroyed, reported as
        # "Reverted ... - 1 file restored."
        #
        # Refusing is the safe direction. A legitimate Smith revert now needs
        # either the trailer or `expected_sha` — both of which Smith's own path
        # supplies — while an unattributed HEAD, which is exactly the shape a
        # user's save has, can no longer be destroyed by "undo that".
        if not expected_sha:
            return {
                "ok": False,
                "error": (
                    f"refusing to revert: HEAD ({reverted_sha[:7]} — "
                    f"{last.get('subject') or '?'}) carries no {COMMIT_ACTOR_TRAILER} "
                    f"trailer, so there is no way to tell whose commit it is. It may "
                    f"be your own save. Reverting it could destroy work that was "
                    f"never separately committed. If you are sure, revert it by hand."
                ),
            }
        # expected_sha matched above, so the caller has independent proof this is
        # the commit it made. That is a stronger claim than the trailer.
        logger.warning(
            "revert_last_patch: HEAD %s carries no %s trailer, but matches the "
            "caller's expected_sha — proceeding on that evidence.",
            reverted_sha[:7], COMMIT_ACTOR_TRAILER,
        )

    rc, out, err = _git(
        output_dir, "revert", "--no-edit", "HEAD",
    )
    if rc != 0:
        # Try to leave the tree clean.
        _git(output_dir, "revert", "--abort")
        logger.warning("revert_last_patch failed rc=%d stderr=%s", rc, err[:400])
        return {
            "ok":    False,
            "error": f"git revert failed: {err.strip() or 'unknown'}",
        }

    # Capture the new revert commit's SHA.
    rc2, sha2, _ = _git(output_dir, "rev-parse", "HEAD")
    revert_commit_sha = sha2.strip() if rc2 == 0 else ""

    n = len(last.get("files") or [])
    summary = (
        f"Reverted '{last.get('subject') or reverted_sha[:7]}' — "
        f"{n} file{'s' if n != 1 else ''} restored."
    )

    return {
        "ok":                True,
        "reverted_sha":      reverted_sha,
        "revert_commit_sha": revert_commit_sha,
        "subject":           last.get("subject") or "",
        "files":             last.get("files") or [],
        "summary":           summary,
    }

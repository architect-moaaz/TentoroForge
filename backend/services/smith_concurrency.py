"""Concurrency + editor integration for the Blueprint.

Spec: §10.6 (multi-Smith) and §6.5 / §6.6 (editor mirroring +
staleness detection).

Two seams:

  * :func:`save_if_unchanged` — optimistic locking. Callers that
    loaded the blueprint at fingerprint X can save only if the
    on-disk fingerprint is still X. Loser gets
    :class:`ConcurrentModificationError` and can choose to reload
    + re-plan + retry.

  * :class:`EditorMirror` — the visual editor calls
    ``record_edit(...)`` after saving a schema/workflow file, so
    Smith's next turn sees the change in ``change_log`` with
    ``source="editor"``. The mirror handles concurrent Smith
    writes by reloading + retrying once before giving up.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from services.smith_blueprint import Blueprint


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Optimistic locking
# --------------------------------------------------------------------------- #

class ConcurrentModificationError(RuntimeError):
    """The blueprint on disk changed between our load and our save.

    Raised so the caller can reload, re-plan, and either retry or
    surface the conflict to the user (§10.6 — architect voice on
    conflict, not stack trace)."""


def file_fingerprint(path: str | Path) -> str:
    """Content fingerprint of one file — ``""`` when it does not exist.

    The file-level twin of :meth:`Blueprint.fingerprint`, so the
    optimistic-lock story is the same shape for every artefact Smith
    writes rather than existing only for the blueprint.
    """
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise ConcurrentModificationError(
            f"cannot fingerprint {path}: {exc}"
        ) from exc


def check_unchanged(path: str | Path, *, expected_fingerprint: str | None) -> str:
    """Assert the file at ``path`` still matches ``expected_fingerprint``.

    Returns the current fingerprint (so the caller can hand it back to
    whoever will edit next). ``expected_fingerprint=None`` means the
    caller holds no prior read and the check is skipped.

    This exists because the optimistic lock was written for the blueprint
    and used nowhere else (register S23-2), while Smith's workflow writes
    — the ones that happen with no human watching — had no staleness check
    at all (register S23-1). The editor route already answers this exact
    collision with a 409; the agent path answered it by overwriting.
    """
    current = file_fingerprint(path)
    if expected_fingerprint is not None and current != expected_fingerprint:
        raise ConcurrentModificationError(
            f"{Path(path).name} changed on disk since it was read: expected "
            f"{(expected_fingerprint or '<absent>')[:12]}…, found "
            f"{(current or '<absent>')[:12]}…. Re-read the file and re-apply "
            f"the change — overwriting would discard someone else's edit."
        )
    return current


def save_file_if_unchanged(
    path: str | Path,
    writer: Callable[[], None],
    *,
    expected_fingerprint: str | None,
) -> str:
    """Run ``writer()`` iff the file at ``path`` still matches.

    The file-level twin of :func:`save_if_unchanged`, which only ever
    guarded the Blueprint (register S23-2) while Smith's workflow writes
    — the ones that happen with no human watching — had no lock at all.

    ``writer`` performs the actual write (the caller keeps its own atomic
    write / formatting), so this adds the guarantee without taking over
    serialization. Returns the fingerprint AFTER the write, for the caller
    to hand back as ``expected_fingerprint`` next time.

    Raises :class:`ConcurrentModificationError` before touching anything
    if the file moved since ``expected_fingerprint`` was taken.
    """
    check_unchanged(path, expected_fingerprint=expected_fingerprint)
    writer()
    return file_fingerprint(path)


def save_if_unchanged(
    bp: Blueprint, *, expected_fingerprint: str,
) -> None:
    """Save `bp` iff the on-disk blueprint's fingerprint matches
    `expected_fingerprint`.

    Reads the current on-disk blueprint fresh, compares fingerprints,
    then saves. Non-atomic across processes (two writers who race
    between the check and the save can both succeed on the same
    fingerprint) but sufficient for the single-process backend
    Smith runs in today. The git commit that follows any real
    Smith move is the authoritative atomic gate; this check exists
    to catch the common case early with a clean error."""
    if not bp._output_dir:  # noqa: SLF001 — talking to Blueprint's own field
        raise RuntimeError("save_if_unchanged needs bp loaded from disk")

    on_disk = Blueprint.load(
        project_id=bp.project_id, output_dir=bp._output_dir,  # noqa: SLF001
    )
    current_fp = on_disk.fingerprint()
    if current_fp != expected_fingerprint:
        raise ConcurrentModificationError(
            f"blueprint changed on disk since load: expected "
            f"{expected_fingerprint[:12]}…, found {current_fp[:12]}…"
        )
    bp.save()


# --------------------------------------------------------------------------- #
# Editor mirroring
# --------------------------------------------------------------------------- #

_MAX_MIRROR_RETRIES = 2


class EditorMirror:
    """Reflects editor-driven changes into the blueprint's change_log.

    The editor is authoritative for its own edits (the user actually
    saved the change through the UI). This class just records what
    happened so Smith's next turn understands the app has moved.

    Retry semantics: if a concurrent Smith write lands between the
    mirror's load and its save, we reload + retry (up to
    ``_MAX_MIRROR_RETRIES``). If we keep losing the race — highly
    unusual — we raise the last ConcurrentModificationError and let
    the editor UI surface it."""

    def __init__(self, *, project_id: str, output_dir: str) -> None:
        self.project_id = project_id
        self.output_dir = output_dir

    def record_edit(
        self, *,
        artifact_path: str,
        summary: str,
        why: str,
    ) -> None:
        last_err: Exception | None = None
        for _ in range(_MAX_MIRROR_RETRIES):
            bp = Blueprint.load(
                project_id=self.project_id, output_dir=self.output_dir,
            )
            fp = bp.fingerprint()
            bp.append_change_log(
                at=_now_iso(),
                user_ask="",
                smith_move=f"editor: modified `{artifact_path}`",
                diff_summary=summary,
                verified_by=["editor save-handler"],
                why=why,
                source="editor",
            )
            try:
                save_if_unchanged(bp, expected_fingerprint=fp)
                return
            except ConcurrentModificationError as exc:
                logger.info(
                    "EditorMirror: concurrent write on %s (%s); retrying",
                    self.project_id, exc,
                )
                last_err = exc
                continue
        # Retries exhausted — raise so the editor UI can surface it.
        raise last_err or ConcurrentModificationError("mirror lost every retry")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

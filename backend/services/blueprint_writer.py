"""Atomic writer + mutation log for the per-app BLUEPRINT.md.

The builder (:mod:`services.blueprint_builder`) is pure — it reads
contracts + schemas and returns Markdown. This module is the write
side: it wraps the builder, writes ``BLUEPRINT.md`` atomically, and
records the mutation in ``.blueprint-log.jsonl`` for the "Generation
Log" section of the next build.

Flag-gated on ``FORGE_BLUEPRINT`` (default: on). When disabled the
writer is a no-op — useful for tests or environments where the extra
file would be noise.

Idempotency
-----------
If the rendered content is byte-identical to what's already on disk
(excluding the header's timestamp line, which always changes), the
write is skipped so the file's mtime doesn't churn on every save.
The mutation log entry is still appended so the "Generation Log"
reflects the trigger.

Ordering
--------
Log-append happens BEFORE the build so the new entry appears in the
build we're about to write. That means the file the reader sees always
matches the log they see in it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.blueprint_builder import build_blueprint

logger = logging.getLogger(__name__)


_ENV_FLAG = "FORGE_BLUEPRINT"
_BLUEPRINT_FILE = "BLUEPRINT.md"
_LOG_FILE = ".blueprint-log.jsonl"
_HEADER_TS_RE = re.compile(r"^_Last built:.*_$", re.MULTILINE)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def write_blueprint(
    output_dir: str | Path,
    *,
    source: str = "generation",
    summary: str = "",
) -> dict[str, Any]:
    """Build + write ``<output_dir>/BLUEPRINT.md`` atomically.

    ``source`` is one of ``"generation" | "editor" | "smith"``. It's
    recorded in the mutation log and drives the "Source" column of the
    Generation Log section. Anything else is accepted but only the three
    canonical values are colored in the UI.

    Returns ``{written: bool, path: str, byte_size: int}``.
    ``written=False`` means the emitted content matched what was already
    on disk (idempotency skip) OR the flag is disabled.
    """
    if not _flag_enabled():
        return {"written": False, "path": "", "byte_size": 0, "reason": "flag disabled"}

    root = Path(output_dir)
    if not root.is_dir():
        logger.warning("blueprint_writer: %s is not a directory; skipping", root)
        return {"written": False, "path": "", "byte_size": 0,
                "reason": "output_dir missing"}

    # 1. Append mutation log FIRST so the build reads it.
    _append_log(root, source=source, summary=summary)

    # 2. Build — annotate the mutation source into the header so a reader
    # can see which seam wrote the on-disk file.
    try:
        content = build_blueprint(root, mutation_source=source)
    except Exception as exc:  # noqa: BLE001 — writer must never crash callers
        logger.exception("blueprint_writer: build_blueprint failed: %s", exc)
        return {"written": False, "path": "", "byte_size": 0,
                "reason": f"build failed: {exc}"}

    dest = root / _BLUEPRINT_FILE

    # 3. Idempotency: compare with the timestamp line normalized out so
    # a same-second re-run doesn't churn the file.
    if dest.exists():
        try:
            existing = dest.read_text(encoding="utf-8")
            if _canonical(existing) == _canonical(content):
                return {"written": False, "path": str(dest),
                        "byte_size": len(existing.encode("utf-8")),
                        "reason": "unchanged"}
        except OSError:
            pass  # fall through — writing again is safe

    # 4. Atomic write.
    try:
        _atomic_write(dest, content)
    except OSError as exc:
        logger.exception("blueprint_writer: write to %s failed: %s", dest, exc)
        return {"written": False, "path": str(dest), "byte_size": 0,
                "reason": f"write failed: {exc}"}

    return {"written": True, "path": str(dest),
            "byte_size": len(content.encode("utf-8"))}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _flag_enabled() -> bool:
    """FORGE_BLUEPRINT defaults to ON. Accept "0" / "false" / "off" to disable."""
    from services.flag_profile import is_on
    return is_on(_ENV_FLAG, default=True)


def _append_log(root: Path, *, source: str, summary: str) -> None:
    """Append one JSON line to ``.blueprint-log.jsonl``. Failures are logged
    and swallowed — the mutation-log is diagnostic, not load-bearing."""
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "source": str(source or "unknown"),
        "summary": str(summary or "")[:400],
    }
    try:
        with (root / _LOG_FILE).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("blueprint_writer: append to %s failed: %s",
                       root / _LOG_FILE, exc)


def _canonical(text: str) -> str:
    """Strip the always-changing ``_Last built: …_`` header line so we
    can compare bodies for idempotency."""
    return _HEADER_TS_RE.sub("", text)


def _atomic_write(dest: Path, content: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".blueprint-", suffix=".tmp", dir=str(dest.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, dest)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


# --------------------------------------------------------------------------- #
# Convenience — safe wrapper for pipeline callers
# --------------------------------------------------------------------------- #

def write_blueprint_safe(
    output_dir: str | Path,
    *,
    source: str = "generation",
    summary: str = "",
) -> dict[str, Any]:
    """Same as :func:`write_blueprint` but never raises — pipeline seams
    call this so an unrelated blueprint problem never crashes generation
    or an editor save."""
    try:
        return write_blueprint(output_dir, source=source, summary=summary)
    except Exception as exc:  # noqa: BLE001
        logger.exception("blueprint_writer: unexpected failure: %s", exc)
        return {"written": False, "path": "", "byte_size": 0,
                "reason": f"unexpected: {exc}"}

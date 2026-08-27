"""Emit the Docker artifacts needed by the containerized verify runner.

Copies (idempotently):
  - Dockerfile.verify
  - docker-compose.verify.yml
  - .dockerignore   (only when absent — don't clobber user's)

Called from post_generate_fixes for every generated app so JV-15b's
``containerized_app`` can spin up a fresh container per verify.

Never touches the app's canonical `docker-compose.yml` (Postgres-only,
host-dev mode) — the verify overlay is a separate file.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_TEMPLATES = Path(__file__).parent.parent / "templates" / "app-foundation"


def emit_verify_container_artifacts(output_dir: str) -> dict:
    """Copy the three artifacts. Returns a summary suitable for logging
    from post_generate_fixes."""
    out = Path(output_dir)
    if not out.exists():
        return {"skipped": True, "reason": "output dir missing"}

    src_dockerfile = _TEMPLATES / "Dockerfile.verify"
    src_compose = _TEMPLATES / "docker-compose.verify.yml"
    src_ignore = _TEMPLATES / ".dockerignore"

    if not (src_dockerfile.exists() and src_compose.exists()):
        # Templates missing on this checkout — nothing to do. Log so the
        # gap surfaces on the next dev sync.
        logger.warning("emit_verify_container_artifacts: template files "
                       "missing in %s", _TEMPLATES)
        return {"skipped": True, "reason": "templates missing"}

    written = []

    # Dockerfile + compose are safe to overwrite — regenerated per build,
    # never hand-edited in a way we care about preserving.
    for src, name in [(src_dockerfile, "Dockerfile.verify"),
                      (src_compose, "docker-compose.verify.yml")]:
        dst = out / name
        shutil.copy(src, dst)
        written.append(name)

    # .dockerignore: only write when absent. If the user already has one
    # they probably meant it (host-mode dev tooling may add entries we'd
    # otherwise blow away).
    dockerignore_dst = out / ".dockerignore"
    if not dockerignore_dst.exists():
        shutil.copy(src_ignore, dockerignore_dst)
        written.append(".dockerignore")

    return {"skipped": False, "written": written}

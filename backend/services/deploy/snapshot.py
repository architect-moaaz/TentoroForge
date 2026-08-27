"""Turn a generated-app directory into the Vercel files[] payload.

Two shapes, one directory walk:

  - `build_snapshot(root)` returns the INLINE shape
    `[{file, data, encoding?}]` — utf-8 text ships plain, binaries
    ship base64. Fine when the whole app fits in Vercel's 10 MB v13
    request-body cap; blows up above it with a 400 "Request body too
    large" from POST /v13/deployments.

  - `build_snapshot_upload(root)` returns the UPLOAD shape
    `[{file, sha, size, raw}]` — raw bytes held in memory alongside
    the SHA1 digest and byte count, ready to be POSTed to
    /v2/files first and then referenced sha-only in the deployment
    body. This is the path any nontrivial generated app must take;
    the deployment body drops to a few KB regardless of file count.

Filters (identical for both shapes):
  - node_modules/, .next/, .git/, .vercel/, dist/, .turbo/, .cache/
    (target rebuilds these)
  - .env, .env.local, .env.production (secrets flow via env-sync,
    not the file tree — leaking these into the deploy would burn the
    integrations sync work)
  - .DS_Store and similar editor artifacts
  - files > 100 MB (Vercel's per-file limit)
  - total > 250 MB (self-imposed guard against runaway payloads)

Deterministic ordering: files come back sorted by relative path so
test assertions are stable and deploy digests are reproducible.
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any, Iterator

# Excluded at ANY depth — these are always build/dep artifacts we
# never want in the snapshot, no matter where they appear.
_EXCLUDE_DIRS_ANYWHERE = {
    "node_modules", ".next", ".git", ".vercel", ".turbo", ".cache",
}
# Excluded ONLY at the project root — deeper occurrences are legitimate
# (e.g. `vendor/@tentoroforge/engine/dist/index.js` IS what the vendored
# package resolves `main` to; stripping it would break the build).
_EXCLUDE_DIRS_ROOT_ONLY = {
    "dist",
    # Expo/React-Native scaffold — a sibling deliverable (APK/IPA), never part
    # of the Next.js web deploy. Its android/.gradle + ios/Pods artifacts can
    # exceed the per-file upload limit.
    "mobile",
}
_EXCLUDE_FILES = {
    ".env", ".env.local", ".env.production", ".env.development", ".DS_Store",
}
_MAX_FILE_BYTES = 100 * 1024 * 1024   # Vercel per-file limit
_MAX_TOTAL_BYTES = 250 * 1024 * 1024


class SnapshotTooLarge(Exception):
    """Raised when a single file or the whole snapshot exceeds Vercel's
    inline-deploy limits. Caller should either shrink the app or switch
    to the upload-first-then-deploy flow."""


def _iter_files(root: Path) -> Iterator[Path]:
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if set(rel.parts) & _EXCLUDE_DIRS_ANYWHERE:
            continue
        if rel.parts and rel.parts[0] in _EXCLUDE_DIRS_ROOT_ONLY:
            continue
        # Next.js route groups named "(dev-only)" host in-app editor
        # UI that pulls @tentoroforge/editor — a heavy dep we don't
        # vendor into deployed apps. Strip them from production
        # snapshots so the phantom import doesn't reach webpack.
        if any(part == "(dev-only)" for part in rel.parts):
            continue
        if p.name in _EXCLUDE_FILES:
            continue
        yield p


def build_snapshot(root: Path) -> list[dict[str, Any]]:
    """Read the app dir into a Vercel-shaped files list.

    Raises SnapshotTooLarge for oversized single files or oversized
    total payloads.
    """
    files: list[dict[str, Any]] = []
    total = 0
    for path in _iter_files(root):
        raw = path.read_bytes()
        size = len(raw)
        if size > _MAX_FILE_BYTES:
            raise SnapshotTooLarge(
                f"{path.relative_to(root)} is {size} bytes (limit {_MAX_FILE_BYTES})"
            )
        total += size
        if total > _MAX_TOTAL_BYTES:
            raise SnapshotTooLarge(
                f"snapshot exceeds {_MAX_TOTAL_BYTES} bytes total"
            )
        rel = str(path.relative_to(root))
        try:
            text = raw.decode("utf-8")
            files.append({"file": rel, "data": text})
        except UnicodeDecodeError:
            files.append(
                {
                    "file": rel,
                    "data": base64.b64encode(raw).decode("ascii"),
                    "encoding": "base64",
                }
            )
    return files


def build_snapshot_upload(root: Path) -> list[dict[str, Any]]:
    """Read the app dir into the upload-shape files list.

    Each entry is `{file, sha, size, raw}` where `raw` is the file's
    bytes, `sha` is its SHA1 hex digest (Vercel keys uploads by SHA1),
    and `size` is the byte count. The caller uploads each `raw` to
    /v2/files with `x-vercel-digest: <sha>`, then passes the
    same list (minus `raw`) as the deployment `files` field.

    Same filters as `build_snapshot`. Same SnapshotTooLarge rules.
    """
    files: list[dict[str, Any]] = []
    total = 0
    for path in _iter_files(root):
        raw = path.read_bytes()
        size = len(raw)
        if size > _MAX_FILE_BYTES:
            raise SnapshotTooLarge(
                f"{path.relative_to(root)} is {size} bytes (limit {_MAX_FILE_BYTES})"
            )
        total += size
        if total > _MAX_TOTAL_BYTES:
            raise SnapshotTooLarge(
                f"snapshot exceeds {_MAX_TOTAL_BYTES} bytes total"
            )
        rel = str(path.relative_to(root))
        sha = hashlib.sha1(raw).hexdigest()
        files.append({"file": rel, "sha": sha, "size": size, "raw": raw})
    return files

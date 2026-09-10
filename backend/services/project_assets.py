"""Put a user-supplied image where BOTH preview surfaces can actually serve it.

WHY THIS IS NOT `chat_attachments`
----------------------------------
`chat_attachments` stores files under ``output/_attachments/<project_id>/`` and
serves them from ``GET /api/projects/{id}/attachments/{att_id}``. That route is
guarded by ``Depends(get_current_user)``, and `auth.py` builds its dependency on
``HTTPBearer()`` — the credential must arrive in an ``Authorization`` header. A
browser fetching ``<img src="…">`` sends no such header, and the render-scaffold
(a separate origin on :6503) holds no token at all. So an attachment URL can
never be the ``src`` of an image in the canvas or the preview: it would 401 on
every load. Chat attachments are the right home for *conversation* inputs; a
picture the user pins onto a Hero is a project source asset, and it belongs in
the project's own output tree next to the schema that references it.

What IS reused from `chat_attachments`: `classify()`, `MAX_BYTES` and
`AttachmentError`, so "what counts as an image" and "how big is too big" have
exactly one definition in the backend rather than two that drift.

WHY THE BYTES ARE WRITTEN TWICE
-------------------------------
The URL we emit is ``/api/asset/<short_id>/figma/<file>``, which two different
Next.js apps serve from their own copies of the same route handler:

  frontend/src/app/api/asset/[projectId]/figma/[file]/route.ts   (editor, :6501)
  apps/render-scaffold/src/app/api/asset/[projectId]/figma/[file]/route.ts (:6503)

Both call a `resolveProject()` — and the two implementations DISAGREE:

  frontend/src/lib/resolveProject.ts          → always ``output/<id>``
  apps/render-scaffold/src/lib/resolveProject.ts → ``output/<id>/app`` when
                                                   ``<id>/app/src/schemas`` exists

Project ``gh0mlpbp`` has both ``output/gh0mlpbp/src/schemas`` and
``output/gh0mlpbp/app/src/schemas``, so the editor reads
``output/gh0mlpbp/public/figma/`` while the preview reads
``output/gh0mlpbp/app/public/figma/``. One URL, two readers, two directories.
Writing to a single one would give the user an image that appears in the canvas
and a broken box in the preview (or the reverse) with no error to explain it.
So we write into every root a reader might probe. The files are content-hashed
and idempotent, so the duplicate costs one extra copy of a ≤10 MB asset and
nothing else.

WHY THE ``figma/`` SEGMENT
--------------------------
The asset route's path segment is the string literal ``figma`` in both copies.
Serving uploads from a differently-named directory would mean editing two
mirrored route handlers in two apps for a cosmetic gain, so uploads land in the
directory that is already served. The name is about the URL space, not the
provenance.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from services.chat_attachments import (
    KIND_IMAGE,
    MAX_BYTES,
    AttachmentError,
    classify,
)

logger = logging.getLogger(__name__)

# Mirrors chat_attachments._IMAGE_MEDIA, inverted. Only these four media types
# can reach us — classify() refuses everything else as KIND_UNSUPPORTED, SVG
# included (it is not in chat_attachments._IMAGE_EXT, and an SVG is a script
# carrier, so widening the set here would be a security decision, not a
# convenience one).
_EXT_FOR_MEDIA: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_MEDIA_FOR_EXT: dict[str, str] = {v: k for k, v in _EXT_FOR_MEDIA.items()}

_MEDIA_ALIASES = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg"}

_EXT_FALLBACK: dict[str, str] = {
    ".png": ".png", ".jpg": ".jpg", ".jpeg": ".jpg",
    ".gif": ".gif", ".webp": ".webp",
}


def asset_roots(output_dir: str | Path) -> list[Path]:
    """Every directory a `resolveProject()` implementation might call the
    project root, in the order the two surfaces probe them.

    See the module docstring: the editor and the scaffold resolve the same
    project id to different directories when a Blueprint-projected ``app/``
    subtree exists. Returning both is what lets one URL serve both.
    """
    base = Path(output_dir)
    roots = [base]
    nested = base / "app"
    # Probed on ``src/schemas``, not on ``app`` alone — apps/render-scaffold's
    # resolveProject uses exactly that test, and an empty ``app/`` template
    # floor is not a root it would ever return.
    if (nested / "src" / "schemas").is_dir():
        roots.append(nested)
    return roots


def _extension(filename: str, content_type: str) -> str:
    ct = _MEDIA_ALIASES.get((content_type or "").lower().strip(),
                            (content_type or "").lower().strip())
    if ct in _EXT_FOR_MEDIA:
        return _EXT_FOR_MEDIA[ct]
    return _EXT_FALLBACK.get(Path(filename or "").suffix.lower(), ".png")


def save_project_image(
    output_dir: str | Path,
    short_id: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> dict:
    """Store one image in the project's servable asset dirs; return its record.

    Raises ``AttachmentError`` (which the route turns into a 400 with the
    message shown verbatim) for a non-image or an oversized file — the same
    refusals, with the same wording, the chat composer already gives.
    """
    if not data:
        raise AttachmentError(f"{filename or 'file'} is empty.")
    if len(data) > MAX_BYTES:
        raise AttachmentError(
            f"{filename} is too large ({len(data) / 1024 / 1024:.1f} MB); "
            f"limit is {MAX_BYTES // 1024 // 1024} MB")

    kind = classify(filename, content_type)
    if kind != KIND_IMAGE:
        raise AttachmentError(
            f"{filename} is not an image — pick a PNG, JPEG, GIF or WebP file.")

    ext = _extension(filename, content_type)
    # Content-addressed, like figma_asset_downloader's sha1-of-URL names:
    # re-uploading the same picture reuses the same file and the same URL, so
    # a user who drops the same logo on ten nodes stores it once.
    name = f"u{hashlib.sha256(data).hexdigest()[:16]}{ext}"

    written: list[str] = []
    for root in asset_roots(output_dir):
        dest_dir = root / "public" / "figma"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name
        if not dest.exists():
            dest.write_bytes(data)
        written.append(str(dest))

    logger.info("project image saved: short_id=%s file=%s bytes=%d roots=%d",
                short_id, name, len(data), len(written))

    return {
        "url": f"/api/asset/{short_id}/figma/{name}",
        "file": name,
        "filename": filename,
        "media_type": _MEDIA_FOR_EXT.get(ext, "image/png"),
        "bytes": len(data),
        "paths": written,
    }

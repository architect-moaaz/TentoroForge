"""Where the owner's logo comes to rest, so the generated application can carry it.

A logo already reached this platform. ``/api/brand/extract/logo`` takes the
upload, ``brand_extractor`` clusters its pixels into a palette, and the bytes
are then dropped on the floor — the colours survived the round trip and the
mark did not. That is why "put our brand colours, the green from our logo"
worked and "put our logo in the corner" did not.

WHERE IT LANDS, AND WHY NOT IN THE ATTACHMENTS
----------------------------------------------
``chat_attachments`` is how a file reaches a *conversation*: it stores what the
person put on one turn so the model can look at it. That is a chat artifact —
scoped to the project's chat, swept with it, and meaningless to a build that
replays the Blueprint on a fresh tree.

The logo is not that. It is part of what the application IS, so it lives beside
the definition that claims it: ``<output_dir>/brand/<digest>.<ext>``, the
Blueprint's own neighbour. A rebuild that reads nothing but ``current.json``
still finds the mark, because ``designSystem.logo.file`` is a path relative to
that directory. An attachment is a fine way to HAND the file over
(:func:`from_attachment` is exactly that bridge); it is not a place to keep it.

Content-addressed, so uploading the same mark twice writes one file and
replacing it never has to decide whether the old one is still referenced.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

#: 4 MB. A logo is a logo; a 10 MB one is a photograph someone mislabelled,
#: and it would be shipped to every visitor of every page of the generated app.
MAX_BYTES = 4 * 1024 * 1024

#: What a browser can paint in an ``<img>``. Wider than
#: ``chat_attachments``'s list on purpose: that one is bounded by what the
#: vision API accepts, and nothing here asks a model to look at the file.
#: SVG is the format most brand marks actually arrive in.
_EXT_BY_MEDIA = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}

_MEDIA_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}

#: Browsers send these for JPEG and SVG; neither is a real media type.
_ALIASES = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg",
            "image/svg": "image/svg+xml", "text/svg+xml": "image/svg+xml"}

#: The stored name is ours. A logo whose `file` is anything but this shape is a
#: document that has been edited by hand or by something that should not have.
STORED_NAME = re.compile(r"^brand/[0-9a-f]{16}\.(png|jpg|gif|webp|svg)$")

DIR = "brand"


class BrandLogoError(ValueError):
    """A refusal the owner should see: wrong kind of file, or too large."""


# --------------------------------------------------------------------------- #
# what kind of image this is
# --------------------------------------------------------------------------- #

def media_type(filename: str, content_type: str = "") -> str:
    """The media type to store this under, or raise.

    Content type first when it is one we know — a drag-drop carries a real one
    and often a meaningless name. Extension second, because an upload from a
    design tool frequently carries ``application/octet-stream``.
    """
    ct = (content_type or "").strip().lower().split(";")[0]
    ct = _ALIASES.get(ct, ct)
    if ct in _EXT_BY_MEDIA:
        return ct
    ext = Path(filename or "").suffix.lower()
    if ext in _MEDIA_BY_EXT:
        return _MEDIA_BY_EXT[ext]
    raise BrandLogoError(
        f"{filename or 'that file'} is not an image this can use — "
        f"a PNG, JPEG, GIF, WebP or SVG.")


def _dimensions(data: bytes, media: str) -> tuple[int, int] | None:
    """Intrinsic size, or None when it cannot be read.

    None is a real answer, not a failure: the shell falls back to a square box
    for a mark whose proportions it does not know, which is what it already
    does for the initial it draws today.
    """
    if media == "image/svg+xml":
        return _svg_dimensions(data)
    try:
        from io import BytesIO

        from PIL import Image
        with Image.open(BytesIO(data)) as im:
            w, h = im.size
    except Exception as exc:  # noqa: BLE001 — an unreadable header is not fatal
        logger.info("brand logo: could not measure %s: %s", media, exc)
        return None
    return (int(w), int(h)) if w > 0 and h > 0 else None


_VIEWBOX = re.compile(rb'viewBox\s*=\s*["\']\s*[-\d.]+[,\s]+[-\d.]+[,\s]+([\d.]+)[,\s]+([\d.]+)')
_SVG_DIM = re.compile(rb'\b(width|height)\s*=\s*["\'](\d+(?:\.\d+)?)(?:px)?["\']')


def _svg_dimensions(data: bytes) -> tuple[int, int] | None:
    """An SVG's aspect, from its ``viewBox`` or its width/height attributes.

    Read from the markup rather than rendered: rendering an SVG needs a
    rasteriser this platform does not ship, and all the shell wants is the
    ratio. A mark with neither is simply unmeasured.
    """
    head = data[:4096]
    m = _VIEWBOX.search(head)
    if m:
        try:
            w, h = float(m.group(1)), float(m.group(2))
        except ValueError:
            return None
        return (round(w), round(h)) if w > 0 and h > 0 else None
    dims = {k.decode(): float(v) for k, v in _SVG_DIM.findall(head)}
    w, h = dims.get("width"), dims.get("height")
    if w and h and w > 0 and h > 0:
        return round(w), round(h)
    return None


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #

def store(output_dir: str | Path, filename: str, content_type: str,
          data: bytes) -> dict:
    """Write the mark beside the Blueprint; return the ``designSystem.logo`` body.

    The returned dict is the contract shape and nothing more — it is written
    into the document verbatim by the seam, so anything extra here would be a
    field the contract does not declare.
    """
    if not data:
        raise BrandLogoError("that file is empty.")
    if len(data) > MAX_BYTES:
        raise BrandLogoError(
            f"{filename or 'that logo'} is {len(data) // 1024} KB; a logo the "
            f"application ships on every page has to be under "
            f"{MAX_BYTES // 1024 // 1024} MB.")

    media = media_type(filename, content_type)
    digest = hashlib.sha256(data).hexdigest()[:16]
    rel = f"{DIR}/{digest}{_EXT_BY_MEDIA[media]}"

    dest = Path(output_dir) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    logo: dict = {"file": rel, "mediaType": media, "alt": ""}
    size = _dimensions(data, media)
    if size:
        logo["width"], logo["height"] = size
    logger.info("brand logo stored: %s (%d bytes, %s)", rel, len(data),
                f"{size[0]}x{size[1]}" if size else "unmeasured")
    return logo


def from_attachment(output_dir: str | Path, attachments_root: str | Path,
                    project_id: str, attachment_id: str,
                    filename: str = "") -> dict:
    """Store the mark from a file the owner already attached to the chat.

    The bridge, not a second store: the attachment is read once and handed to
    :func:`store`, which is still the only thing that writes.
    """
    from services import chat_attachments

    blob = chat_attachments.read_attachment(attachments_root, project_id,
                                            attachment_id)
    if blob is None:
        raise BrandLogoError(
            "I could not read that file any more — attach it again and I will "
            "put it in.")
    data, media = blob
    return store(output_dir, filename or attachment_id, media, data)


def path_of(output_dir: str | Path, logo: dict | None) -> Path | None:
    """The stored file for a ``designSystem.logo``, or None if it is not there.

    The name is checked against :data:`STORED_NAME` rather than merely joined:
    ``file`` comes out of a JSON document, and a document that has been edited
    by hand could point it at ``../../../etc/passwd``, which the projection
    would then copy into a tree that gets published.
    """
    rel = str((logo or {}).get("file") or "")
    if not STORED_NAME.match(rel):
        if rel:
            logger.warning("brand logo: refusing stored path %r", rel)
        return None
    p = Path(output_dir) / rel
    return p if p.is_file() else None


__all__ = ["BrandLogoError", "MAX_BYTES", "STORED_NAME", "from_attachment",
           "media_type", "path_of", "store"]

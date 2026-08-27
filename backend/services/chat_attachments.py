"""Turn user-attached images and documents into Anthropic content blocks.

A user who pastes a screenshot into chat means "build this" or "make it
look like this". A user who attaches a PDF spec means "read this and use
it". Both are first-class generation inputs, and until now neither could
reach the model — `ChatRequest` carried a bare string.

WHAT THIS MODULE IS, AND IS NOT
-------------------------------
It is the *transport and safety* layer: classify, store, and re-emit as
content blocks. It deliberately contains no prompting and no judgement
about relevance — the caller decides what to do with the blocks, and the
model decides whether the attachment is useful. Keeping policy out of here
is what lets the same function serve Smith, the planner, and the brief
author without three divergent copies.

The vision/document call itself needs no new code: `services.llm_client`
passes anthropic-style block lists through verbatim, which is how
`visual_qa_critic` and `fidelity_scorer` already send images.

THREE THINGS THAT MUST NOT GO WRONG
-----------------------------------
1. **Filenames are attacker-controlled.** They are stored as display
   metadata only; the on-disk name is a generated id. `../../etc/passwd`
   is a legal thing for a browser to send.

2. **Unsupported means unsupported, out loud.** `.docx` and `.xlsx` are
   zip containers we have no reader for. Accepting one and quietly
   attaching nothing is indistinguishable, from the user's seat, from the
   model ignoring their file. So we refuse at upload time, where there is
   a human present to see the message.

3. **Media types must be exactly what the API accepts.** Browsers send
   `image/jpg`, which the API rejects; PDFs must ride in a `document`
   block, not an `image` one.

Storage lives under ``output/_attachments/<project_id>/`` — alongside the
existing ``output/_usage`` ledger, so it lands on the same persistent bind
mount on UAT and survives container recreates.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

KIND_IMAGE = "image"
KIND_PDF = "pdf"
KIND_TEXT = "text"
KIND_UNSUPPORTED = "unsupported"

# 10 MB. Base64 inflates ~33%, so this is ~13 MB on the wire per file —
# comfortably inside the API's limits and still generous for a screenshot
# or a spec document.
MAX_BYTES = 10 * 1024 * 1024

# Enough for "here are the four screens I want"; small enough that a
# runaway paste cannot turn one turn into a minutes-long request.
MAX_ATTACHMENTS = 8

# Per text file. Long enough for a real spec, short enough that one
# attachment cannot crowd the actual conversation out of the context.
MAX_TEXT_CHARS = 40_000

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml"}

# The API accepts exactly these four. Anything else must be mapped or refused.
_IMAGE_MEDIA = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# `image/jpg` is not a real media type but browsers send it constantly.
_MEDIA_ALIASES = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg"}

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class AttachmentError(ValueError):
    """Refusal the user should see — bad type, too large, bad project id."""


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #

def classify(filename: str, content_type: str = "") -> str:
    """One of the ``KIND_*`` constants.

    Content type wins when it is decisive (a browser drag-drop often has a
    correct type and a meaningless name); extension is the fallback, since
    pasted screenshots frequently arrive with neither a real name nor a
    trustworthy type.
    """
    ct = _MEDIA_ALIASES.get((content_type or "").lower().strip(),
                            (content_type or "").lower().strip())
    if ct in set(_IMAGE_MEDIA.values()):
        return KIND_IMAGE
    if ct == "application/pdf":
        return KIND_PDF

    ext = Path(filename or "").suffix.lower()
    if ext in _IMAGE_EXT:
        return KIND_IMAGE
    if ext == ".pdf":
        return KIND_PDF
    if ext in _TEXT_EXT:
        return KIND_TEXT
    if ct.startswith("text/"):
        return KIND_TEXT
    return KIND_UNSUPPORTED


def _media_type(filename: str, content_type: str, kind: str) -> str:
    if kind == KIND_PDF:
        return "application/pdf"
    ct = _MEDIA_ALIASES.get((content_type or "").lower().strip(),
                            (content_type or "").lower().strip())
    if ct in set(_IMAGE_MEDIA.values()):
        return ct
    return _IMAGE_MEDIA.get(Path(filename or "").suffix.lower(), "image/png")


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #

def _project_dir(root: str | Path, project_id: str) -> Path:
    """Reject any project id that is not a plain token.

    The id reaches us from a path parameter; `..` in it would let one
    project read another's attachments.
    """
    pid = str(project_id or "")
    if not _SAFE_ID.match(pid):
        raise AttachmentError(f"invalid project id: {pid!r}")
    return Path(root) / pid


def save_attachment(root: str | Path, project_id: str, filename: str,
                    content_type: str, data: bytes) -> dict:
    """Persist one attachment; return its record.

    Raises ``AttachmentError`` for anything we will not be able to send —
    refusing here means the user finds out while they are still looking at
    the composer, not silently at answer time.
    """
    if len(data) > MAX_BYTES:
        raise AttachmentError(
            f"{filename} is too large ({len(data) // 1024 // 1024} MB); "
            f"limit is {MAX_BYTES // 1024 // 1024} MB")

    kind = classify(filename, content_type)
    if kind == KIND_UNSUPPORTED:
        raise AttachmentError(
            f"{filename} is not supported — attach an image (PNG/JPEG/GIF/WebP), "
            f"a PDF, or a text file (TXT/MD/CSV/JSON).")

    d = _project_dir(root, project_id)
    d.mkdir(parents=True, exist_ok=True)

    # The stored name is ours, never theirs. `filename` survives only as
    # display metadata in the sidecar.
    att_id = uuid.uuid4().hex
    (d / att_id).write_bytes(data)

    rec = {
        "id": att_id,
        "filename": filename,
        "kind": kind,
        "media_type": _media_type(filename, content_type, kind),
        "bytes": len(data),
    }
    (d / f"{att_id}.meta.json").write_text(json.dumps(rec), encoding="utf-8")
    return rec


def _load_record(d: Path, att_id: str) -> dict | None:
    if not _SAFE_ID.match(str(att_id or "")):
        return None                     # traversal attempt, or junk
    meta = d / f"{att_id}.meta.json"
    blob = d / att_id
    if not meta.is_file() or not blob.is_file():
        return None
    try:
        rec = json.loads(meta.read_text(encoding="utf-8"))
    except Exception:                   # noqa: BLE001 — corrupt sidecar
        return None
    rec["_path"] = blob
    return rec


# --------------------------------------------------------------------------- #
# content blocks
# --------------------------------------------------------------------------- #

def load_blocks(root: str | Path, project_id: str,
                attachment_ids: list[str]) -> list[dict]:
    """Anthropic content blocks for the given attachments, in order.

    Every attachment is preceded by a text block naming it, so the model can
    refer to "the dashboard.png you attached" rather than "the second image".

    Never raises: a missing or unreadable attachment is skipped. By the time
    we are assembling a prompt the user is gone, and losing one image is far
    better than losing the whole turn.
    """
    try:
        d = _project_dir(root, project_id)
    except AttachmentError:
        return []
    if not d.is_dir():
        return []

    blocks: list[dict] = []
    used = 0
    for att_id in (attachment_ids or []):
        if used >= MAX_ATTACHMENTS:
            logger.info("chat_attachments: capped at %d, dropping the rest",
                        MAX_ATTACHMENTS)
            break
        rec = _load_record(d, str(att_id))
        if rec is None:
            continue
        try:
            raw = rec["_path"].read_bytes()
        except Exception:               # noqa: BLE001
            continue

        name = rec.get("filename") or rec["id"]
        kind = rec.get("kind")

        if kind == KIND_TEXT:
            text = raw.decode("utf-8", errors="replace")
            if len(text) > MAX_TEXT_CHARS:
                text = (text[:MAX_TEXT_CHARS]
                        + f"\n\n…[truncated — {len(text) - MAX_TEXT_CHARS} "
                          f"more characters not shown]")
            blocks.append({"type": "text",
                           "text": f"Attached document: {name}\n\n{text}"})
            used += 1
            continue

        blocks.append({"type": "text", "text": f"Attached file: {name}"})
        source = {"type": "base64",
                  "media_type": rec.get("media_type") or "image/png",
                  "data": base64.standard_b64encode(raw).decode("ascii")}
        blocks.append({"type": "document" if kind == KIND_PDF else "image",
                       "source": source})
        used += 1

    return blocks


def attachments_root() -> Path:
    """``output/_attachments`` — beside the ``_usage`` ledger.

    Resolved the same way ``project_service.OUTPUT_BASE`` is, so on UAT this
    lands on the persistent ``/output`` bind mount and attachments survive a
    container recreate.
    """
    root = Path(__file__).parent.parent.parent / "output" / "_attachments"
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_attachment(root: str | Path, project_id: str,
                    attachment_id: str) -> tuple[bytes, str] | None:
    """``(bytes, media_type)`` for one attachment, or None.

    Used to serve the file back to the chat transcript. Returns None rather
    than raising on a traversal attempt, so the route answers 404 and leaks
    nothing about what does or does not exist on disk.
    """
    try:
        d = _project_dir(root, project_id)
    except AttachmentError:
        return None
    rec = _load_record(d, str(attachment_id))
    if rec is None:
        return None
    try:
        data = rec["_path"].read_bytes()
    except Exception:                   # noqa: BLE001
        return None
    media = rec.get("media_type") or "application/octet-stream"
    if rec.get("kind") == KIND_TEXT:
        media = "text/plain; charset=utf-8"
    return data, media


def describe(root: str | Path, project_id: str,
             attachment_ids: list[str]) -> list[dict]:
    """Records (no bytes) for the given ids — for logging and for echoing
    the attachment list back into the conversation history."""
    try:
        d = _project_dir(root, project_id)
    except AttachmentError:
        return []
    out = []
    for att_id in (attachment_ids or []):
        rec = _load_record(d, str(att_id))
        if rec:
            rec.pop("_path", None)
            out.append(rec)
    return out

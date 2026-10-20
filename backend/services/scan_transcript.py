"""A scanned PDF, read by Claude and kept as text.

A PDF with no text layer — pages photographed or run through a scanner — has
nothing pypdf can extract, so `services.document_text` says it is a scan. Until
now that was where it ended: the person was told to find the original Word file.
Often there is none; the signed-off BRD exists only as the scan.

Claude reads PDF pages as images as well as text, so a scan can be handed to it
as a `document` block with one instruction: write out what the pages say. That
happens ONCE, at upload, and the transcript is stored exactly where an extracted
document's text goes. Everything downstream — the definition reading it, Smith
opening it with `read_file` — cannot tell a transcribed scan from a typed PDF,
which is the point; the record says `transcribed` so the composer can.

Bounds, each said to the person rather than silently applied:

- `MAX_PAGES` pages. A longer scan is refused with the reason, not half read.
- A reply cut off by the output cap keeps what was written and says it is cut,
  the same way `document_text` marks a long document.
- A refusal or an API failure becomes `Unreadable` with the reason, and the
  upload keeps the file with that warning — as a scan was kept before.

What it cost goes on the usage ledger against the application, the person and
the organisation, like every other model call.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any

from services.document_text import Unreadable

logger = logging.getLogger(__name__)

#: Longest scan transcribed. Each page is read as an image; past this a single
#: upload becomes a long wait and a large bill for one attachment.
MAX_PAGES = 100
#: The model that reads the pages.
MODEL = os.environ.get("FORGE_TRANSCRIBE_MODEL", "claude-opus-5-5")
#: Room for the transcript. Dense requirements run to ~700 tokens a page, so a
#: 100-page scan needs most of this; streamed, so the size cannot time out.
MAX_TOKENS = 128_000

INSTRUCTION = (
    "These pages are a scanned document. Transcribe them as plain text, faithfully and completely: "
    "every heading, paragraph, list item and table, in reading order. Do not summarise, correct, "
    "or add anything. Mark headings with # (## for sub-headings), list items with '- ', and write "
    "tables as rows of cells separated by ' | '. Begin each page with a line '[page N]'. Where a "
    "word cannot be read, write [illegible]. Reply with the transcript only."
)


def _client() -> Any:
    import anthropic

    # Same transport settings as the build's agents (`executors.AnthropicModel`):
    # `read` is the gap between chunks, so a long streamed transcript never
    # trips it while a dead socket does.
    return anthropic.Anthropic(
        timeout=anthropic.Timeout(connect=15.0, read=300.0, write=60.0, pool=15.0),
        max_retries=3,
    )


def transcribe(data: bytes, pages: int, *, filename: str = "", project: str = "",
               user: str = "", org: str = "") -> dict:
    """`{"text", "truncated"}` for a scanned PDF, or `Unreadable` with the reason."""
    if pages > MAX_PAGES:
        raise Unreadable(f"it looks like scanned pages, and at {pages} pages it is longer than the "
                         f"{MAX_PAGES} Forge transcribes. Attach the original Word document, a PDF with "
                         f"selectable text, or the scan split into parts of {MAX_PAGES} pages or fewer.")
    started = time.monotonic()
    try:
        with _client().beta.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            # Copying text out is not a reasoning task; the least thinking will do.
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {
                    "type": "base64", "media_type": "application/pdf",
                    "data": base64.standard_b64encode(data).decode("ascii")}},
                {"type": "text", "text": INSTRUCTION},
            ]}],
        ) as stream:
            msg = stream.get_final_message()
    except Exception as exc:  # noqa: BLE001 — the upload stays; the reason is said
        logger.warning("scan transcription failed for %s: %s", filename or "a PDF", exc)
        raise Unreadable("it looks like scanned pages, and reading them failed this time. Try attaching "
                         "it again, or attach the original Word document.") from exc

    usage = getattr(msg, "usage", None)
    try:
        from services.build_usage import record_usage
        record_usage(
            project=project, agent="scan_transcript", model=getattr(msg, "model", None) or MODEL,
            usage={k: getattr(usage, k, 0) or 0 for k in (
                "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")},
            duration_ms=int((time.monotonic() - started) * 1000), num_turns=1,
            kind="document", user=user, org=org)
    except Exception:  # noqa: BLE001 — accounting never fails an upload
        logger.debug("scan transcription usage not recorded", exc_info=True)

    if getattr(msg, "stop_reason", None) == "refusal":
        raise Unreadable("it looks like scanned pages, and they could not be transcribed. Attach the "
                         "original Word document, or a PDF with selectable text.")
    text = "".join(getattr(b, "text", "") for b in (msg.content or []) if getattr(b, "type", "") == "text").strip()
    if not text:
        raise Unreadable("it looks like scanned pages, and no text could be read from them. Attach the "
                         "original Word document, or a PDF with selectable text.")
    truncated = getattr(msg, "stop_reason", None) == "max_tokens"
    if truncated:
        text += "\n\n[The transcript stops here; the rest of the scan was not transcribed.]"
    return {"text": text, "truncated": truncated}


__all__ = ["MAX_PAGES", "MODEL", "transcribe"]

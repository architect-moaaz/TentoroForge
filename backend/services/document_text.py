"""A requirements document — a BRD, a PRD, a specification — as plain text.

People hand Forge their requirements as Word files and PDFs. The chat refused
the first and quietly ignored the second, so a BRD had to be pasted in by hand
to be read at all. This turns either into the text the definition reads
(`services.blueprint.documents`) and Smith can open with `read_file`:

- **Word (.docx)** is a zip of XML; the standard library reads it, so no
  dependency is added. Headings keep their level as `#` marks, list items
  become `- ` lines, and tables become `|`-separated rows, because a
  requirements table read as one run-on paragraph loses which cell said what.
- **PDF** is read with pypdf, page by page, each page marked so a reader can
  say "page 7". A PDF with no text layer — a scan — is said to be one, with
  the way round it, rather than accepted as an empty document.

Lines are wrapped at `WRAP` characters: Smith's file reader cuts lines longer
than 240, and a paragraph cut there would lose its second half without anyone
noticing.
"""
from __future__ import annotations

import io
import re
import textwrap
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

#: Longest line written. Below `services.smith.reads.MAX_LINE` (240).
WRAP = 200
#: A document longer than this is cut and says so; roughly 60-80 pages of prose.
MAX_CHARS = 200_000
#: A PDF page with fewer readable characters than this, on average, has no text layer.
SCANNED_BELOW = 30

DOCUMENT_EXT = {".docx", ".pdf", ".txt", ".md", ".markdown"}

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class Unreadable(ValueError):
    """The document cannot be read as text. The message says why and what to do."""


def _wrap(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        if len(line) <= WRAP:
            out.append(line)
            continue
        indent = re.match(r"^(\s*(?:[-*]\s+|#+\s+)?)", line).group(1)
        out.extend(textwrap.wrap(line, WRAP, subsequent_indent=" " * len(indent),
                                 break_long_words=True, break_on_hyphens=False) or [""])
    return "\n".join(out)


def _cap(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_CHARS:
        return text, False
    cut = text[:MAX_CHARS].rsplit("\n", 1)[0]
    return cut + f"\n\n[The document continues; only its first {MAX_CHARS:,} characters were kept.]", True


# --------------------------------------------------------------------------- #
# Word
# --------------------------------------------------------------------------- #

def _run_text(p: ET.Element) -> str:
    parts: list[str] = []
    for node in p.iter():
        tag = node.tag
        if tag == f"{_W}t" and node.text:
            parts.append(node.text)
        elif tag == f"{_W}tab":
            parts.append("\t")
        elif tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts).strip()


def _heading_level(p: ET.Element) -> int:
    style = p.find(f"{_W}pPr/{_W}pStyle")
    name = (style.get(f"{_W}val") if style is not None else "") or ""
    if name.lower() == "title":
        return 1
    m = re.match(r"(?i)heading\s*(\d)", name)
    return min(int(m.group(1)), 6) if m else 0


def _is_list_item(p: ET.Element) -> bool:
    return p.find(f"{_W}pPr/{_W}numPr") is not None


def _docx(data: bytes) -> tuple[str, int | None]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise Unreadable("it is not a Word document Forge can open (it may be damaged, or an older .doc "
                         "renamed). Open it in Word and save it again as .docx, or as PDF.") from exc
    pages = None
    try:
        app = ET.fromstring(z.read("docProps/app.xml"))
        node = next((n for n in app.iter() if n.tag.endswith("}Pages")), None)
        pages = int(node.text) if node is not None and node.text and node.text.isdigit() else None
    except Exception:  # noqa: BLE001 — a page count is a nicety
        pages = None
    body = ET.fromstring(xml).find(f"{_W}body")
    lines: list[str] = []
    for child in list(body) if body is not None else []:
        if child.tag == f"{_W}p":
            text = _run_text(child)
            if not text:
                continue
            level = _heading_level(child)
            if level:
                lines += ["", "#" * level + " " + text, ""]
            elif _is_list_item(child):
                lines.append("- " + text)
            else:
                lines += [text, ""]
        elif child.tag == f"{_W}tbl":
            rows = []
            for tr in child.iter(f"{_W}tr"):
                cells = [" ".join(_run_text(p) for p in tc.iter(f"{_W}p")).strip() for tc in tr.iter(f"{_W}tc")]
                if any(cells):
                    rows.append("| " + " | ".join(c.replace("\n", " ") for c in cells) + " |")
            if rows:
                lines += [""] + rows + [""]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text, pages


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #

def _pdf(data: bytes) -> tuple[str, int | None]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # the image installs it; a bare environment may not
        raise Unreadable("PDF reading is not available on this server yet. Attach the document as .docx, "
                         "or paste its text.") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:  # noqa: BLE001
                ok = 0
            if not ok:
                raise Unreadable("it is protected with a password. Save an unprotected copy and attach that.")
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            pages.append((i, (page.extract_text() or "").strip()))
    except Unreadable:
        raise
    except Exception as exc:  # noqa: BLE001 — a damaged file is said, not raised as a 500
        raise Unreadable("it could not be opened as a PDF (it may be damaged). Export it again, or attach "
                         "it as .docx.") from exc
    total = sum(len(t) for _, t in pages)
    if not pages or total < SCANNED_BELOW * len(pages):
        raise Unreadable("it has no text Forge can read — it looks like scanned pages. Attach the original "
                         "Word document, or export a PDF with selectable text.")
    blocks = [f"[page {i}]\n{t}" for i, t in pages if t]
    return "\n\n".join(blocks), len(pages)


# --------------------------------------------------------------------------- #
# The one entry point
# --------------------------------------------------------------------------- #

def is_document(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in DOCUMENT_EXT


def extract(filename: str, data: bytes) -> dict:
    """`{"text", "pages", "chars", "truncated"}` for a document, or `Unreadable`."""
    ext = Path(filename or "").suffix.lower()
    if ext == ".docx":
        text, pages = _docx(data)
    elif ext == ".pdf":
        text, pages = _pdf(data)
    elif ext in (".txt", ".md", ".markdown"):
        text, pages = data.decode("utf-8", errors="replace").strip(), None
    else:
        raise Unreadable(f"{ext or 'this file'} is not a document type Forge reads.")
    if not text.strip():
        raise Unreadable("it is empty.")
    text, truncated = _cap(_wrap(text))
    return {"text": text, "pages": pages, "chars": len(text), "truncated": truncated}


__all__ = ["DOCUMENT_EXT", "MAX_CHARS", "Unreadable", "WRAP", "extract", "is_document"]

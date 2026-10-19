"""A BRD or PRD attached as Word or PDF is read, not refused or ignored.

The chat refused .docx and quietly ignored PDFs, so a requirements document
had to be pasted in by hand to be read at all (2026-10-19)."""
from __future__ import annotations

import io
import zipfile

import pytest

from services import chat_attachments as ca
from services import document_text as dt

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _docx(body: str, pages: int | None = 3) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>')
        if pages:
            z.writestr("docProps/app.xml", f'<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Pages>{pages}</Pages></Properties>')
    return buf.getvalue()


def _p(text: str, style: str = "", listed: bool = False) -> str:
    ppr = ""
    if style or listed:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + \
              ("<w:numPr><w:ilvl w:val=\"0\"/></w:numPr>" if listed else "") + "</w:pPr>"
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _pdf(page_texts: list[str]) -> bytes:
    """A minimal PDF with one text line per page (no third-party writer needed)."""
    objs: list[bytes] = []
    kids = []
    n_pages = len(page_texts)
    # 1 catalog, 2 pages, 3 font, then (page, content) pairs
    for i, t in enumerate(page_texts):
        page_no, content_no = 4 + 2 * i, 5 + 2 * i
        kids.append(f"{page_no} 0 R")
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, t in enumerate(page_texts):
        content_no = 5 + 2 * i
        stream = (f"BT /F1 12 Tf 72 720 Td ({t}) Tj ET" if t else "").encode()
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_no} 0 R >>".encode())
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def test_a_word_document_keeps_its_headings_lists_and_tables():
    body = (_p("FitTrackr BRD", "Title") + _p("Members", "Heading2") + _p("A member signs up with email.") +
            _p("Owner sees dues", listed=True) +
            '<w:tbl><w:tr><w:tc>' + _p("Plan") + '</w:tc><w:tc>' + _p("Price") + '</w:tc></w:tr>'
            '<w:tr><w:tc>' + _p("Gold") + '</w:tc><w:tc>' + _p("2000") + '</w:tc></w:tr></w:tbl>')
    out = dt.extract("FitTrackr-BRD.docx", _docx(body))
    t = out["text"]
    assert "# FitTrackr BRD" in t and "## Members" in t and "A member signs up with email." in t
    assert "- Owner sees dues" in t and "| Plan | Price |" in t and "| Gold | 2000 |" in t
    assert out["pages"] == 3 and not out["truncated"]


def test_a_pdf_is_read_page_by_page_and_a_scan_is_said_to_be_one():
    pytest.importorskip("pypdf")
    out = dt.extract("PRD.pdf", _pdf(["Members can book classes and see their dues on the home screen",
                                       "Trainers mark attendance for every class they run that day"]))
    assert out["pages"] == 2
    assert "[page 1]" in out["text"] and "Members can book classes" in out["text"]
    assert "[page 2]" in out["text"] and "Trainers mark attendance" in out["text"]
    with pytest.raises(dt.Unreadable) as scanned:
        dt.extract("scan.pdf", _pdf(["", ""]))
    assert "scanned" in str(scanned.value)


def test_long_lines_are_wrapped_so_the_file_reader_does_not_cut_them():
    out = dt.extract("notes.md", ("word " * 300).encode())
    assert max(len(line) for line in out["text"].splitlines()) <= dt.WRAP


def test_the_chat_accepts_a_word_document_and_keeps_its_text(tmp_path):
    rec = ca.save_attachment(tmp_path, "proj1", "FitTrackr-BRD.docx", "", _docx(_p("Members", "Heading1") + _p("Sign up")))
    assert rec["kind"] == ca.KIND_DOCUMENT and rec["document"] is True and rec["pages"] == 3
    docs = ca.document_texts(tmp_path, "proj1", [rec["id"]])
    assert docs[0]["filename"] == "FitTrackr-BRD.docx" and "# Members" in docs[0]["text"]
    # A damaged Word file and the old .doc format are refused with the way round.
    with pytest.raises(ca.AttachmentError) as bad:
        ca.save_attachment(tmp_path, "proj1", "broken.docx", "", b"not a zip")
    assert "save it again as .docx" in str(bad.value)
    with pytest.raises(ca.AttachmentError) as old:
        ca.save_attachment(tmp_path, "proj1", "old.doc", "", b"\xd0\xcf\x11\xe0")
    assert "save a copy as .docx" in str(old.value)


def test_a_pdf_without_text_is_kept_and_said_unreadable(tmp_path):
    pytest.importorskip("pypdf")
    rec = ca.save_attachment(tmp_path, "proj1", "scan.pdf", "application/pdf", _pdf([""]))
    assert rec["kind"] == ca.KIND_PDF and "scanned" in rec["unreadable"]
    docs = ca.document_texts(tmp_path, "proj1", [rec["id"]])
    assert "text" not in docs[0] and "scanned" in docs[0]["unreadable"]
    # An image is not a document.
    img = ca.save_attachment(tmp_path, "proj1", "shot.png", "image/png", b"\x89PNG\r\n")
    assert ca.document_texts(tmp_path, "proj1", [img["id"]]) == []


def test_a_built_app_turn_stores_the_document_and_tells_smith_where_it_is(tmp_path):
    from routers.blueprint_generate import _document_evidence, _document_note
    out = tmp_path / "app1"
    out.mkdir()
    docs = [{"filename": "PRD.docx", "pages": 4, "text": "## Payments\nDues are monthly.", "truncated": False},
            {"filename": "scan.pdf", "unreadable": "no text"}]
    note = _document_note(str(out), docs)
    assert "PRD.docx, 4 pages: its text is at `.forge/documents/document-1.md`" in note and "read_file" in note
    assert "scan.pdf" not in note
    stored = (out / ".forge" / "documents" / "document-1.md").read_text()
    assert stored == _document_evidence(docs[0]) and "Dues are monthly." in stored
    # Sending it again does not store a second copy.
    _document_note(str(out), docs)
    assert len(list((out / ".forge" / "documents").glob("document-*.md"))) == 1


@pytest.mark.asyncio
async def test_uploading_a_word_brd_answers_with_what_was_read(auth_client, org_id, monkeypatch, tmp_path):
    monkeypatch.setattr("services.chat_attachments.attachments_root", lambda: tmp_path)
    project = (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "FitTrackr"})).json()
    files = {"file": ("FitTrackr-BRD.docx", _docx(_p("Members", "Heading1") + _p("A member signs up.")),
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    r = await auth_client.post(f"/api/projects/{project['id']}/attachments", files=files)
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["document"] is True and rec["pages"] == 3 and rec["kind"] == "document"
    r = await auth_client.post(f"/api/projects/{project['id']}/attachments",
                               files={"file": ("old.doc", b"\\xd0\\xcf", "application/msword")})
    assert r.status_code == 400 and "save a copy as .docx" in r.json()["detail"]

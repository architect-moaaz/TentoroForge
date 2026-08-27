"""User-attached images and documents, turned into Anthropic content blocks.

The hard parts here are NOT "call the vision API" — the transport already
carries image blocks verbatim (see services/llm_client). They are:

* **Path safety.** The filename comes from a browser and is attacker-
  controlled. It must never reach the filesystem as a path segment.
* **Honest degradation.** A `.docx` we cannot read must say so. Silently
  attaching nothing looks identical to "the model ignored my file", which
  is the worst possible failure for a user who just uploaded a spec.
* **Media-type discipline.** The API rejects `image/jpg`; the browser sends
  it anyway. And a PDF must go out as a `document` block, not an `image`.
* **Caps.** Base64 inflates ~33%. An unbounded upload becomes an unbounded
  request body and a very expensive, very slow call.
"""
from __future__ import annotations

import pytest

from services.chat_attachments import (KIND_IMAGE, KIND_PDF, KIND_TEXT,
                                       KIND_UNSUPPORTED, MAX_ATTACHMENTS,
                                       MAX_BYTES, AttachmentError, classify,
                                       load_blocks, read_attachment,
                                       save_attachment)


class TestClassify:
    @pytest.mark.parametrize("name,ctype", [
        ("shot.png", "image/png"),
        ("photo.jpg", "image/jpeg"),
        ("photo.JPG", ""),               # extension only, uppercase
        ("anim.gif", "image/gif"),
        ("modern.webp", "image/webp"),
    ])
    def test_images(self, name, ctype):
        assert classify(name, ctype) == KIND_IMAGE

    def test_pdf_is_its_own_kind_not_an_image(self):
        """PDFs go out as `document` blocks; conflating them with images
        produces a 400 from the API."""
        assert classify("spec.pdf", "application/pdf") == KIND_PDF

    @pytest.mark.parametrize("name", [
        "notes.txt", "README.md", "rows.csv", "data.json", "cols.tsv",
    ])
    def test_text_formats(self, name):
        assert classify(name, "") == KIND_TEXT

    @pytest.mark.parametrize("name", ["report.docx", "book.xlsx", "app.exe"])
    def test_unsupported_is_explicit(self, name):
        assert classify(name, "") == KIND_UNSUPPORTED

    def test_content_type_wins_over_a_lying_extension(self):
        assert classify("screenshot", "image/png") == KIND_IMAGE


class TestSave:
    def test_roundtrip_returns_a_record(self, tmp_path):
        rec = save_attachment(tmp_path, "p1", "shot.png", "image/png", b"\x89PNG\r\n\x1a\n")
        assert rec["kind"] == KIND_IMAGE
        assert rec["filename"] == "shot.png"
        assert rec["bytes"] == 8
        assert rec["id"]

    def test_filename_is_never_a_path_segment(self, tmp_path):
        """`../../etc/passwd` must not escape the project directory."""
        rec = save_attachment(tmp_path, "p1", "../../etc/passwd.txt", "", b"x")
        stored = tmp_path / "p1" / rec["id"]
        assert stored.is_file()
        assert stored.parent == tmp_path / "p1"
        # The display name is preserved for the user, but never used as a path.
        assert rec["filename"] == "../../etc/passwd.txt"

    def test_project_id_is_also_sanitised(self, tmp_path):
        with pytest.raises(AttachmentError):
            save_attachment(tmp_path, "../escape", "a.txt", "", b"x")

    def test_oversize_is_refused_loudly(self, tmp_path):
        with pytest.raises(AttachmentError, match="too large"):
            save_attachment(tmp_path, "p1", "big.png", "image/png",
                            b"x" * (MAX_BYTES + 1))

    def test_unsupported_type_is_refused_at_the_door(self, tmp_path):
        """Better to reject on upload than to accept and silently drop it
        at prompt-assembly time."""
        with pytest.raises(AttachmentError, match="not supported"):
            save_attachment(tmp_path, "p1", "report.docx", "", b"x")


class TestLoadBlocks:
    def _save(self, root, name, ctype, data=b"hello"):
        return save_attachment(root, "p1", name, ctype, data)["id"]

    def test_image_becomes_an_image_block(self, tmp_path):
        i = self._save(tmp_path, "shot.png", "image/png")
        blocks = load_blocks(tmp_path, "p1", [i])
        img = [b for b in blocks if b["type"] == "image"]
        assert len(img) == 1
        assert img[0]["source"]["type"] == "base64"
        assert img[0]["source"]["media_type"] == "image/png"

    def test_jpg_is_normalised_to_jpeg(self, tmp_path):
        """The API rejects `image/jpg`. Browsers send it regularly."""
        i = self._save(tmp_path, "p.jpg", "image/jpg")
        img = [b for b in load_blocks(tmp_path, "p1", [i]) if b["type"] == "image"]
        assert img[0]["source"]["media_type"] == "image/jpeg"

    def test_pdf_becomes_a_document_block(self, tmp_path):
        i = self._save(tmp_path, "spec.pdf", "application/pdf")
        docs = [b for b in load_blocks(tmp_path, "p1", [i]) if b["type"] == "document"]
        assert len(docs) == 1
        assert docs[0]["source"]["media_type"] == "application/pdf"

    def test_text_becomes_a_labelled_text_block(self, tmp_path):
        i = self._save(tmp_path, "notes.md", "", b"# Spec\nBuild a CRM.")
        text = "\n".join(b["text"] for b in load_blocks(tmp_path, "p1", [i])
                         if b["type"] == "text")
        assert "Build a CRM." in text
        assert "notes.md" in text, "the model must know which file this is"

    def test_each_attachment_is_announced_by_name(self, tmp_path):
        """Without a label the model cannot say 'per your screenshot X'."""
        i = self._save(tmp_path, "dashboard.png", "image/png")
        assert any("dashboard.png" in b.get("text", "")
                   for b in load_blocks(tmp_path, "p1", [i]))

    def test_missing_id_is_skipped_not_fatal(self, tmp_path):
        i = self._save(tmp_path, "a.png", "image/png")
        assert load_blocks(tmp_path, "p1", [i, "does-not-exist"])

    def test_empty_list_yields_no_blocks(self, tmp_path):
        assert load_blocks(tmp_path, "p1", []) == []

    def test_traversal_id_cannot_read_outside_the_project(self, tmp_path):
        (tmp_path / "secret.txt").write_text("classified")
        assert load_blocks(tmp_path, "p1", ["../secret.txt"]) == []

    def test_attachment_count_is_capped(self, tmp_path):
        ids = [self._save(tmp_path, f"s{n}.png", "image/png")
               for n in range(MAX_ATTACHMENTS + 3)]
        blocks = load_blocks(tmp_path, "p1", ids)
        assert len([b for b in blocks if b["type"] == "image"]) == MAX_ATTACHMENTS

    def test_read_attachment_roundtrip(self, tmp_path):
        i = self._save(tmp_path, "shot.png", "image/png", b"\x89PNG")
        data, media = read_attachment(tmp_path, "p1", i)
        assert data == b"\x89PNG"
        assert media == "image/png"

    def test_read_attachment_refuses_traversal_without_leaking(self, tmp_path):
        """404 territory — must not distinguish 'blocked' from 'absent'."""
        (tmp_path / "secret.txt").write_text("classified")
        assert read_attachment(tmp_path, "p1", "../secret.txt") is None
        assert read_attachment(tmp_path, "p1", "nope") is None

    def test_long_text_is_truncated_with_a_visible_marker(self, tmp_path):
        i = self._save(tmp_path, "big.txt", "", b"A" * 200_000)
        text = "\n".join(b["text"] for b in load_blocks(tmp_path, "p1", [i])
                         if b["type"] == "text")
        assert len(text) < 200_000
        assert "truncated" in text.lower()

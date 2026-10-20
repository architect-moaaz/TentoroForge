"""Smith sees the screenshot a person attaches to an after-build message.

"Check the attached image" was stored, designated a reference, and never
put in front of the model, which answered "I cannot see the attached
image" (rafm22pm, 2026-09-26). The picture now leads the prompt of every
step of that turn, and the ask says it is there.
"""
from pathlib import Path

from services.smith import loop, understand_ask
import importlib

handle_mod = importlib.import_module("services.smith4.handle")


def _png(tmp_path: Path) -> Path:
    p = tmp_path / "shot.png"
    p.write_bytes(bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da6364f8cfc0000002ef01a7b1a4a0d40000000049454e44ae426082"))
    return p


def test_the_default_provider_puts_the_picture_before_the_words(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr("services.llm_client.complete", lambda **kw: seen.update(kw) or '{"tool": "done", "args": {}}')
    understand_ask._default_provider("the prompt", None, images=[_png(tmp_path)])
    content = seen["content"]
    assert isinstance(content, list) and content[0]["type"] == "image" and content[-1] == {"type": "text", "text": "the prompt"}
    understand_ask._default_provider("plain", None)
    assert seen["content"] == "plain", "no picture, no blocks"


def test_the_loop_tells_the_model_a_screenshot_is_attached(tmp_path):
    prompts = []
    loop.next_step("its showing 404", "ctx", [], [], provider=lambda p: prompts.append(p) or '{"tool": "done", "args": {}}',
                   images=[str(_png(tmp_path))])
    assert "1 screenshot attached by the person" in prompts[0]
    loop.next_step("its showing 404", "ctx", [], [], provider=lambda p: prompts.append(p) or '{"tool": "done", "args": {}}')
    assert "screenshot attached" not in prompts[1]


def test_the_turn_hands_its_image_attachments_to_the_chooser():
    # A PDF reaches here only when it was marked as a design (`_turn_attachments`),
    # and is shown like a picture; a sheet is not; a record with no path cannot be.
    assert handle_mod._image_paths([{"path": "/a/shot.png", "mime": "image/png"},
                                    {"path": "/a/mockups.pdf", "media_type": "application/pdf"},
                                    {"path": "/a/rows.xlsx"}, {"path": "/a/photo.JPG"}, {"filename": "x.png"}]) \
        == ["/a/shot.png", "/a/mockups.pdf", "/a/photo.JPG"]
    src = Path(handle_mod.__file__).read_text()
    assert "_default_choose(reasoning, images=_image_paths(attachments))" in src


def test_the_builder_chat_shows_smith_the_pictures_and_design_pdfs_with_what_each_is_for(tmp_path, monkeypatch):
    """The builder chat stored and designated an attached picture and passed
    none of them to the turn: Smith answered "make it look like this" without
    having seen "this" (2026-10-20). A requirements PDF stays text; a PDF the
    person marked as a design is shown."""
    from routers import blueprint_generate as bg
    from services import chat_attachments as ca, design_reference
    monkeypatch.setattr(ca, "attachments_root", lambda: tmp_path)
    shot = ca.save_attachment(tmp_path, "p1", "bug.png", "image/png", b"\x89PNG\r\n")
    mock = ca.save_attachment(tmp_path, "p1", "mock.png", "image/png", b"\x89PNG\r\n")
    brd = ca.save_attachment(tmp_path, "p1", "BRD.md", "text/markdown", b"# Members\nA member signs up.")
    design_reference.set_design_references(tmp_path, "p1", [mock["id"]])

    shown, note = bg._turn_attachments("p1", [shot["id"], mock["id"], brd["id"]])
    assert [r["filename"] for r in shown] == ["bug.png", "mock.png"] and all(r.get("path") for r in shown)
    assert "bug.png: a picture of what they mean" in note and "mock.png: a DESIGN REFERENCE" in note
    assert "BRD.md" not in note
    # The requirements document is still read as one; a designated file is not.
    assert [d["filename"] for d in bg._attached_documents("p1", [shot["id"], brd["id"]])] == ["BRD.md"]
    design_reference.set_design_references(tmp_path, "p1", [brd["id"]])
    assert bg._attached_documents("p1", [brd["id"]]) == []


def test_the_chat_request_carries_the_attachments_to_the_turn():
    import inspect
    from services import smith_chat_v2
    assert "attachments=list(req.attachments or [])" in inspect.getsource(smith_chat_v2.handle_chat_v2)
    assert smith_chat_v2.ChatV2Request(project_id="p", output_dir="/o", message="m").attachments == []

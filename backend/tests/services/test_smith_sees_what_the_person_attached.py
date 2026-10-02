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
    assert handle_mod._image_paths([{"path": "/a/shot.png", "mime": "image/png"}, {"path": "/a/brief.pdf", "mime": "application/pdf"},
                                    {"path": "/a/photo.JPG"}, {"filename": "x.png"}]) == ["/a/shot.png", "/a/photo.JPG"]
    src = Path(handle_mod.__file__).read_text()
    assert "_default_choose(reasoning, images=_image_paths(attachments))" in src

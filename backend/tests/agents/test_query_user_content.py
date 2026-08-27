"""The Smith LLM boundary must carry image/document blocks, not flatten them.

`_default_query` builds each turn's user message by string-joining the last
user turn with the tool observations and the "respond with JSON" trailer.
That was safe while `content` was always a string. Once attachments landed,
`content` became an anthropic-style block list and two things broke:

1. `"\\n\\n".join([...])` raised
   ``TypeError: sequence item 0: expected str instance, list found`` —
   surfaced to the user as "I hit a problem working on that (TypeError)".
2. Even with the join fixed, flattening to one string would *silently* drop
   every image. A dropped screenshot is worse than a crash: Smith answers
   confidently about a picture it never saw.

So the contract is: text stays joined, media blocks pass through, and the
JSON instruction stays LAST so the model's final instruction is not buried
behind an image.
"""
from __future__ import annotations

from agents.fix_chat_agent import _compose_user_content

_IMG = {"type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "iVBOR"}}
_PDF = {"type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBER"}}

_TRAILER = 'Respond with a single JSON object.'


class TestPlainStringUnchanged:
    """No attachments ⇒ byte-identical to the pre-attachment behaviour."""

    def test_returns_a_plain_string(self):
        out = _compose_user_content("fix the login page", [], _TRAILER)
        assert isinstance(out, str)
        assert out == f"fix the login page\n\n{_TRAILER}"

    def test_tool_results_are_folded_in(self):
        out = _compose_user_content("x", ["[tool read] ok"], _TRAILER)
        assert isinstance(out, str)
        assert "Tool results so far:" in out and "[tool read] ok" in out
        assert out.endswith(_TRAILER), "the JSON instruction must come last"


class TestBlocksSurvive:
    def test_image_block_is_preserved(self):
        out = _compose_user_content(
            [{"type": "text", "text": "make it look like this"}, _IMG], [], _TRAILER)
        assert isinstance(out, list)
        assert _IMG in out, "the image must reach the model, not be flattened away"

    def test_pdf_document_block_is_preserved(self):
        out = _compose_user_content([{"type": "text", "text": "read this"}, _PDF],
                                    [], _TRAILER)
        assert _PDF in out

    def test_the_ask_still_reaches_the_model(self):
        out = _compose_user_content(
            [{"type": "text", "text": "make it look like this"}, _IMG], [], _TRAILER)
        text = " ".join(b["text"] for b in out if b["type"] == "text")
        assert "make it look like this" in text

    def test_json_instruction_is_the_last_block(self):
        """Buried behind an image, the model tends to narrate instead of
        emitting the tool-call JSON the runner parses."""
        out = _compose_user_content([{"type": "text", "text": "hi"}, _IMG],
                                    ["[tool read] ok"], _TRAILER)
        assert out[-1]["type"] == "text"
        assert _TRAILER in out[-1]["text"]

    def test_tool_results_ride_with_the_trailer(self):
        out = _compose_user_content([{"type": "text", "text": "hi"}, _IMG],
                                    ["[tool read] ok"], _TRAILER)
        assert "[tool read] ok" in out[-1]["text"]

    def test_multiple_attachments_all_survive(self):
        out = _compose_user_content(
            [{"type": "text", "text": "these two"}, _IMG, _PDF], [], _TRAILER)
        assert _IMG in out and _PDF in out


class TestDegenerateInputs:
    def test_empty_content(self):
        assert isinstance(_compose_user_content("", [], _TRAILER), str)

    def test_block_list_with_no_media_collapses_to_a_string(self):
        """All-text blocks carry no image, so the cheaper string form is
        correct — and keeps the request shape identical to before."""
        out = _compose_user_content([{"type": "text", "text": "just words"}],
                                    [], _TRAILER)
        assert isinstance(out, str)
        assert "just words" in out

    def test_unknown_block_shape_does_not_raise(self):
        out = _compose_user_content([{"weird": "shape"}, _IMG], [], _TRAILER)
        assert isinstance(out, list) and _IMG in out

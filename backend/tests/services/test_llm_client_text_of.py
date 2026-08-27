"""`_text_of` must read the blocks `_to_message` actually produces.

The bug this pins
-----------------
`complete()` returned an EMPTY STRING for every prompt — no exception, valid
API key, working model. The chain was fine all the way to the end:

    chat.invoke(...)  -> AIMessage(content='OK')
    _to_message(...)  -> [TextBlock(text='OK', type='text')]
    _text_of(...)     -> ''            <-- here

`_text_of` handled `str` and `dict` blocks. `_to_message` emits anthropic
`TextBlock` OBJECTS. Neither branch matched, the parts list stayed empty, and
every caller got "" and treated it as "the model had nothing to say".

Two components each holding a plausible contract with nothing checking they
agree — and the failure is silent, which is why it survived. It affects every
one-shot caller: design briefs, collection maquettes, screenshot briefs,
discovery intent, the binding resolver.
"""

from services.llm_client import _text_of


class _Block:
    """Stand-in for anthropic's TextBlock — attribute access, not a dict."""

    def __init__(self, text, type="text"):
        self.text = text
        self.type = type


class _Thinking:
    def __init__(self, thinking):
        self.thinking = thinking
        self.type = "thinking"


def test_a_plain_string_passes_through():
    assert _text_of("hello") == "hello"


def test_dict_blocks_still_work():
    assert _text_of([{"type": "text", "text": "a"},
                     {"type": "text", "text": "b"}]) == "ab"


def test_text_block_objects_are_read():
    """The live failure: objects, not dicts."""
    assert _text_of([_Block("OK")]) == "OK"


def test_mixed_objects_and_dicts_concatenate():
    assert _text_of([_Block("a"), {"type": "text", "text": "b"}, "c"]) == "abc"


def test_non_text_blocks_are_skipped():
    """A thinking block carries no answer and must not leak into the text."""
    assert _text_of([_Thinking("hmm"), _Block("answer")]) == "answer"


def test_an_empty_list_is_an_empty_string():
    assert _text_of([]) == ""

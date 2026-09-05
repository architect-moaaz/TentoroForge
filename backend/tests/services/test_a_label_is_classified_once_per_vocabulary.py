"""The action classifier asks once per (label, vocabulary), not once per page.

It is a real model call per button, made inside the transform. A design's
rail is the same buttons on every screen and the fan-out composes twelve
screens at once, so one label was classified fifteen times in parallel and the
API throttled the build into a stall — 342 s in `page_layouts`, nothing
composed, the process idle on back-off. Same label, same routes and workflows,
same answer.
"""
from services import figma_action_llm, jsx_to_schema
from services.figma_llm_ctx import reset_figma_llm_context, set_figma_llm_context


def _counting(calls):
    def fake(label, **_kw):
        calls.append(label)
        return figma_action_llm.FigmaActionBinding(kind="navigate", target="/", confidence=0.9)
    return fake


def test_the_same_label_under_the_same_vocabulary_is_asked_once(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(figma_action_llm, "classify_figma_action_llm", _counting(calls))
    monkeypatch.setattr(jsx_to_schema, "_figma_llm_enabled", lambda: True)
    jsx_to_schema._ACTION_MEMO.clear()
    set_figma_llm_context(routes=["/"], workflows=["FLOW-001"])
    try:
        for _ in range(15):
            out = jsx_to_schema._classify_button_action_with_llm("⬡Dashboard", "", "")
        assert out == {"navigate": "/"}
        assert calls == ["⬡Dashboard"]
    finally:
        reset_figma_llm_context()


def test_a_different_vocabulary_is_a_different_question(monkeypatch):
    """The answer depends on what may be bound to; a new page set must not
    inherit an old answer."""
    calls: list[str] = []
    monkeypatch.setattr(figma_action_llm, "classify_figma_action_llm", _counting(calls))
    monkeypatch.setattr(jsx_to_schema, "_figma_llm_enabled", lambda: True)
    jsx_to_schema._ACTION_MEMO.clear()
    try:
        set_figma_llm_context(routes=["/"], workflows=None)
        jsx_to_schema._classify_button_action_with_llm("Cases", "", "")
        reset_figma_llm_context()
        set_figma_llm_context(routes=["/", "/cases"], workflows=None)
        jsx_to_schema._classify_button_action_with_llm("Cases", "", "")
        assert calls == ["Cases", "Cases"]
    finally:
        reset_figma_llm_context()


def test_a_cached_answer_is_a_copy():
    """A caller that mutates its result must not poison the next page."""
    jsx_to_schema._ACTION_MEMO.clear()
    jsx_to_schema._ACTION_MEMO[("x", "", "", (), ())] = {"navigate": "/"}
    reset_figma_llm_context()
    a = jsx_to_schema._classify_button_action_with_llm("x", "", "")
    a["navigate"] = "/changed"
    assert jsx_to_schema._classify_button_action_with_llm("x", "", "") == {"navigate": "/"}

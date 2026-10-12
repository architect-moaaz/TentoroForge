"""Brain Juice: a person and Smith work an idea out, then hand it to a build (2026-10-08).

These hold what needs no network: the idea board, the session on disk, the
consent a hand-off needs, and one whole turn of Smith driven by a stand-in
model — a search the server paused, a board change, a hand-off refused
without a go-ahead and accepted with one.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.brain_juice import agent, board, store


@pytest.fixture(autouse=True)
def _rooted(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path / "bj")


# --------------------------------------------------------------------------- #
# The idea board
# --------------------------------------------------------------------------- #

def test_an_item_with_the_same_name_is_replaced_and_others_are_kept():
    b, _ = board.apply(board.empty(), {"features": [{"name": "Wishlist", "priority": "must"},
                                                    {"name": "Size guide", "priority": "later"}]})
    b, _ = board.apply(b, {"features": [{"name": "wishlist", "detail": "save for later"}]})
    names = [f["name"] for f in b["features"]]
    assert names == ["wishlist", "Size guide"] and b["features"][0]["priority"] == "must", \
        "same name (any case) is the same item, merged"
    b, notes = board.apply(b, {"remove": {"features": ["Size guide", "Nope"]}})
    assert [f["name"] for f in b["features"]] == ["wishlist"]
    assert any("nothing called 'Nope'" in n for n in notes)


def test_the_board_says_what_does_not_fit_together_but_keeps_it():
    b, notes = board.apply(board.empty(), {
        "screens": [{"name": "Home"}],
        "flows": [{"name": "Buy", "steps": [{"screen": "Home"}, {"screen": "Basket"}]}],
        "entities": [{"name": "Order", "links": [{"to": "Customer", "kind": "one"}]}],
        "features": [{"name": "Returns", "priority": "soon"}]})
    assert any("'Basket', which is not a screen" in n for n in notes)
    assert any("links to 'Customer'" in n for n in notes)
    assert b["features"][0]["priority"] == "should" and len(b["flows"]) == 1, "a draft is never refused"


def test_product_and_look_merge_field_by_field():
    b, _ = board.apply(board.empty(), {"product": {"name": "Threadline", "pitch": "clothes"}})
    b, _ = board.apply(b, {"product": {"audience": "young shoppers"}, "status": "agreed"})
    assert b["product"] == {"name": "Threadline", "pitch": "clothes", "audience": "young shoppers"}
    assert b["status"] == "agreed"


# --------------------------------------------------------------------------- #
# The session on disk
# --------------------------------------------------------------------------- #

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_a_session_keeps_its_files_and_lists_by_organisation():
    s = store.create("org-a", "u1", "")
    meta = store.add_file(s, PNG, name="shot.png", media_type=store.sniff(PNG), origin="upload")
    store.save(s)
    again = store.load(s["id"])
    assert again["files"][0]["id"] == meta["id"] and store.file_path(again, meta["id"]).read_bytes() == PNG
    store.create("org-b", "u2", "other")
    assert [r["id"] for r in store.listed("org-a")] == [s["id"]]
    with pytest.raises(ValueError, match="pictures and PDFs"):
        store.add_file(s, b"hello", name="x.txt", media_type=store.sniff(b"hello"), origin="upload")
    with pytest.raises(store.NotFound):
        store.load("../../etc")


def test_what_the_person_drops_in_reaches_the_model_as_what_it_is():
    s = store.create("org", "u", "")
    pic = store.add_file(s, PNG, name="home.png", media_type="image/png", origin="upload")
    pdf = store.add_file(s, b"%PDF-1.4 x", name="brief.pdf", media_type="application/pdf", origin="upload")
    content = agent.user_content(s, "Like this", [pic["id"], pdf["id"]])
    kinds = [c["type"] for c in content]
    assert kinds[0] == "image" and "document" in kinds and content[-1] == {"type": "text", "text": "Like this"}
    assert any("idea board" in c.get("text", "") for c in content)


# --------------------------------------------------------------------------- #
# Consent
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("words", ["Build it", "yes, go ahead!", "let's build", "Build this app"])
def test_a_plain_go_ahead_is_consent(words, monkeypatch):
    monkeypatch.setattr("services.llm_client.complete", lambda **_: pytest.fail("no model for a plain yes"))
    assert agent.consented(words)


def test_anything_else_is_asked_of_a_small_model_and_not_knowing_is_no(monkeypatch):
    monkeypatch.setattr("services.llm_client.complete", lambda **_: "NO")
    assert not agent.consented("what about a wishlist?")
    def boom(**_):
        raise RuntimeError("offline")
    monkeypatch.setattr("services.llm_client.complete", boom)
    assert not agent.consented("sure, sounds good, maybe build it later")


# --------------------------------------------------------------------------- #
# One turn, with a stand-in model
# --------------------------------------------------------------------------- #

class _Msg:
    def __init__(self, content, stop):
        self._content, self.stop_reason = content, stop
        self.usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                     cache_creation_input_tokens=0, server_tool_use=None)

    def to_dict(self, mode="json"):
        return {"content": self._content}


class _Stream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for b in self.msg._content:
            if b.get("type") == "text":
                yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=b["text"]))

    def get_final_message(self):
        return self.msg


def _model(replies, seen):
    def stream(**kw):
        seen.append([m["role"] for m in kw["messages"]])
        return _Stream(replies.pop(0))
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))


def test_a_turn_resumes_a_paused_search_changes_the_board_and_refuses_an_unasked_hand_off(monkeypatch):
    s = store.create("org", "u", "")
    seen: list = []
    replies = [
        _Msg([{"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "shop app features"}}],
             "pause_turn"),
        _Msg([{"type": "text", "text": "Here is what I found."},
              {"type": "tool_use", "id": "t1", "name": "update_board",
               "input": {"features": [{"name": "Wishlist", "priority": "must"}]}},
              {"type": "tool_use", "id": "t2", "name": "hand_off", "input": {"app_name": "Threadline"}}],
             "tool_use"),
        _Msg([{"type": "text", "text": "Shall I build it?"}], "end_turn"),
    ]
    monkeypatch.setattr(agent, "_client", lambda: _model(replies, seen))
    monkeypatch.setattr(agent, "consented", lambda words: False)
    events: list = []
    entry = agent.turn(s, "Tell me about shop apps", [], lambda e, d: events.append((e, d)))

    assert seen[1][-1] == "assistant", "a paused turn is resumed with nothing added"
    assert [f["name"] for f in s["board"]["features"]] == ["Wishlist"]
    results = s["turns"][-2]["content"]
    assert results[0]["tool_use_id"] == "t1" and results[1]["is_error"] is True, \
        "both results go back in one message; the hand-off without a go-ahead is refused"
    assert not s.get("handoff_request")
    assert entry["text"] == "Here is what I found.\n\nShall I build it?"
    assert "Searched the web: shop app features" in entry["steps"]
    assert any(e == "board" for e, _ in events)


def test_with_a_go_ahead_the_hand_off_is_asked_for_and_the_board_agreed(monkeypatch):
    s = store.create("org", "u", "")
    replies = [
        _Msg([{"type": "tool_use", "id": "t1", "name": "hand_off", "input": {"app_name": "Threadline"}}], "tool_use"),
        _Msg([{"type": "text", "text": "Creating Threadline now."}], "end_turn"),
    ]
    monkeypatch.setattr(agent, "_client", lambda: _model(replies, []))
    agent.turn(s, "Build it", [], lambda e, d: None)
    assert s["handoff_request"]["app_name"] == "Threadline" and s["board"]["status"] == "agreed"


def test_the_writers_task_names_no_application():
    import re
    from services.brain_juice import document
    for text in (agent.SYSTEM, document.WRITER):
        for brand in ("myntra", "amazon", "zara", "airbnb", "uber", "shopify"):
            assert not re.search(rf"\b{brand}\b", text.lower()), brand

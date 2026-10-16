"""Each screen on the idea board is drawn as a page in the company's brand.

The Screens tab used to be text cards with, at most, a thumbnail of the
reference screenshot a screen was modelled on. Now each screen is drawn —
one self-contained document per screen, in the company's design language or
the board's look — as it lands or changes on the board, and the drawing is
the person's page, never the reference's.
"""
from __future__ import annotations

import re
import time
from types import SimpleNamespace

import pytest

from services.drafts_room import agent, brand as brands, drawer, store


@pytest.fixture(autouse=True)
def _rooted(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path / "dr")


COMPANY = {"source": "company", "company": "Acme", "colors": {"primary": "#1B7F5A", "background": "#FFFFFF"},
           "fonts": {"body": "Inter", "heading": "Inter"}, "radius": "8px", "elevation": "none", "density": "airy",
           "voice": "", "logo": None}
LOOK = {"mood": "calm", "palette": [{"name": "moss", "hex": "#4A6B3A"}], "fonts": ["Fraunces", "Inter"],
        "layout": "cards", "avoid": "neon"}
SCREEN = {"name": "Plant detail", "role": "Gardener", "purpose": "One plant's story",
          "shows": ["name", "last watered"], "actions": ["Log care"]}
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
DOC = "<!doctype html><html><head><style>:root{--primary:#1B7F5A}</style></head><body><h1>Acme</h1></body></html>"


def _session(screens=(SCREEN,), look=None) -> dict:
    s = store.create("org", "u", "")
    s["board"]["product"] = {"name": "Garden Log", "pitch": "A notebook for gardeners.", "platforms": ["web"]}
    s["board"]["screens"] = [dict(x) for x in screens]
    if look:
        s["board"]["look"] = look
    return s


# --------------------------------------------------------------------------- #
# The brand
# --------------------------------------------------------------------------- #

def test_the_companys_brand_comes_first_and_the_boards_look_fills_the_rest():
    merged = brands.merged(COMPANY, {"look": LOOK})
    assert merged["source"] == "company" and merged["colors"] == COMPANY["colors"]
    assert merged["fonts"] == COMPANY["fonts"]
    assert merged["mood"] == "calm" and merged["layout"] == "cards" and merged["avoid"] == "neon"

    from_board = brands.merged({}, {"look": LOOK})
    assert from_board["source"] == "board"
    assert from_board["colors"] == {"moss": "#4A6B3A"}
    assert from_board["fonts"] == {"body": "Inter", "heading": "Fraunces"}

    assert brands.merged({}, {})["source"] == "none"
    assert "choose one restrained" in brands.described(brands.merged({}, {}))


@pytest.mark.asyncio
async def test_the_companys_brand_is_read_from_its_profile_with_the_logo_inlined(tmp_path, monkeypatch):
    logo = tmp_path / "mark.png"
    logo.write_bytes(PNG)
    from services.brand_discovery import store as brand_store
    monkeypatch.setattr(brand_store, "logo_file", lambda org_id, meta: logo if meta else None)
    profile = SimpleNamespace(usable=True, company_name="Acme", identity={"voice": "plain"},
                              design={"colors": {"primary": "#1B7F5A", "ring": ""}, "typography": {"fontFamilyBase": "Inter"},
                                      "radius": {"md": "8px"}, "logo": {"file": "mark.png", "mediaType": "image/png"}})

    class Db:
        async def execute(self, stmt):
            return SimpleNamespace(scalar_one_or_none=lambda: profile)
    got = await brands.for_org("00000000-0000-0000-0000-000000000001", Db())
    assert got["source"] == "company" and got["company"] == "Acme"
    assert got["colors"] == {"primary": "#1B7F5A"} and got["fonts"] == {"body": "Inter"} and got["radius"] == "8px"
    assert got["logo"]["data_uri"].startswith("data:image/png;base64,")
    assert "Acme's own design language" in brands.described(got) and "primary #1B7F5A" in brands.described(got)

    profile.usable = False
    assert await brands.for_org("00000000-0000-0000-0000-000000000001", Db()) == {}


def test_a_drawing_is_dated_by_its_screen_its_brand_or_its_product_and_nothing_else():
    product = {"name": "Garden Log", "platforms": ["web"]}
    base = drawer.fingerprint(SCREEN, COMPANY, product)
    assert drawer.fingerprint(dict(SCREEN), dict(COMPANY), dict(product)) == base
    assert drawer.fingerprint({**SCREEN, "shows": ["name"]}, COMPANY, product) != base
    assert drawer.fingerprint(SCREEN, {**COMPANY, "colors": {"primary": "#000"}}, product) != base
    assert drawer.fingerprint(SCREEN, COMPANY, {**product, "name": "Leaf"}) != base
    assert drawer.fingerprint(SCREEN, COMPANY, {**product, "platforms": ["iOS"]}) != base   # phone, not desktop
    assert drawer.fingerprint(SCREEN, COMPANY, {**product, "pitch": "changed"}) == base
    assert drawer.fingerprint({**SCREEN, "device": "desktop"}, COMPANY, product) == base      # already a desktop
    assert drawer.fingerprint({**SCREEN, "device": "phone"}, COMPANY, product) != base


def test_the_viewport_follows_the_products_platforms():
    assert drawer.viewport_for({"platforms": ["iOS", "Android"]}) == "phone"
    assert drawer.viewport_for({"platforms": ["web"], "kind": "mobile app"}) == "phone"
    assert drawer.viewport_for({"platforms": ["web"]}) == "desktop"
    assert drawer.viewport_for({}) == "desktop"
    # The screen's own device comes first: a mechanic's desk beside a customer's phone.
    assert drawer.viewport_for({"platforms": ["iOS"]}, {"device": "desktop"}) == "desktop"
    assert drawer.viewport_for({"platforms": ["web"]}, {"device": "phone"}) == "phone"


# --------------------------------------------------------------------------- #
# What the drawer is sent
# --------------------------------------------------------------------------- #

def test_a_screen_modelled_on_a_screenshot_is_sent_it_with_the_no_copy_rule():
    s = _session()
    shot = store.add_file(s, PNG, name="ref.png", media_type="image/png", origin="screenshot")
    with_like = drawer.content_for(s, {**SCREEN, "like": shot["id"]}, COMPANY)
    kinds = [b["type"] for b in with_like]
    assert "image" in kinds
    rule = next(b["text"] for b in with_like if b["type"] == "text" and "modelled on" in b["text"])
    assert "take none of its wording, logo, pictures or colours" in rule

    without = drawer.content_for(s, SCREEN, COMPANY)
    assert all(b["type"] == "text" for b in without)
    text = "\n".join(b["text"] for b in without)
    assert "Garden Log" in text and "Plant detail" in text and "Log care" in text and "1280x800" in text
    assert "Acme's own design language" in text

    noted = drawer.content_for(s, SCREEN, COMPANY, note="bigger cards")
    assert noted[0]["type"] == "text" and "bigger cards" in noted[0]["text"]


def test_the_logo_travels_as_the_data_uri_it_must_be_used_as():
    s = _session()
    brand = {**COMPANY, "logo": {"media_type": "image/png", "data_uri": "data:image/png;base64,AAAA"}}
    text = "\n".join(b["text"] for b in drawer.content_for(s, SCREEN, brand) if b["type"] == "text")
    assert "data:image/png;base64,AAAA" in text


def test_the_drawers_task_names_no_application():
    for name in ("myntra", "amazon", "zara", "airbnb", "uber", "shopify", "garden log"):
        assert not re.search(rf"\b{name}\b", drawer.SYSTEM.lower()), name
    assert "never" in drawer.SYSTEM and "<script>" in drawer.SYSTEM


# --------------------------------------------------------------------------- #
# The document
# --------------------------------------------------------------------------- #

def test_only_a_document_that_stands_alone_is_a_drawing():
    assert drawer._document("Here it is:\n" + DOC + "\nDone.") == DOC
    assert drawer._document("<html><body>no doctype</body></html>") is None
    for bad in ("<script>alert(1)</script>", '<img src="https://x.test/a.png">', "<style>@import url(x)</style>",
                '<link rel="stylesheet" href="x">', "<style>body{background:url(https://x.test/b.png)}</style>",
                '<iframe src="x"></iframe>'):
        assert drawer._document(f"<!doctype html><html><body>{bad}</body></html>") is None, bad
    ok = '<!doctype html><html><body><img src="data:image/png;base64,AAAA"></body></html>'
    assert drawer._document(ok) == ok


class _Stream:
    def __init__(self, text):
        self._msg = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], usage=None, stop_reason="end_turn")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self._msg


def _client(replies: list[str], asked: list[list[dict]]):
    def stream(**kw):
        asked.append(kw["messages"])
        return _Stream(replies.pop(0))
    return SimpleNamespace(messages=SimpleNamespace(stream=stream))


def test_a_reply_that_is_not_a_document_is_asked_for_once_more_then_fails(monkeypatch):
    asked: list = []
    monkeypatch.setattr(drawer, "_client", lambda: _client(["Sure! <p>no document</p>", DOC], asked))
    assert drawer.draw(_session(), SCREEN, COMPANY) == DOC
    assert len(asked) == 2 and "document only" in asked[1][-1]["content"]

    asked.clear()
    monkeypatch.setattr(drawer, "_client", lambda: _client(["nope", "<script>x</script>"], asked))
    with pytest.raises(RuntimeError, match="stands alone"):
        drawer.draw(_session(), SCREEN, COMPANY)
    assert len(asked) == 2


# --------------------------------------------------------------------------- #
# Drawing as the board changes
# --------------------------------------------------------------------------- #

def _settled(sid: str, n: int, timeout: float = 5.0) -> list[dict]:
    end = time.time() + timeout
    while time.time() < end:
        rows = store.drawings(sid)
        if len(rows) >= n and all(r["status"] != "drawing" for r in rows):
            return rows
        time.sleep(0.05)
    raise AssertionError(f"drawings did not settle: {store.drawings(sid)}")


def test_screens_are_drawn_when_missing_or_out_of_date_and_left_alone_otherwise(monkeypatch):
    drawn: list[str] = []
    monkeypatch.setattr(drawer, "draw", lambda session, screen, brand, note="": drawn.append(screen["name"]) or DOC)
    monkeypatch.setattr(drawer, "picture", lambda html, viewport: PNG)
    other = {"name": "Plant list", "purpose": "Every plant", "shows": ["name"], "actions": ["Add plant"]}
    s = _session((SCREEN, other))

    started = drawer.start(s, None, COMPANY)
    assert sorted(d["screen"] for d in started) == ["Plant detail", "Plant list"]
    rows = _settled(s["id"], 2)
    assert all(r["status"] == "done" and r["html"] and r["png"] for r in rows)
    one = next(r for r in rows if r["screen"] == "Plant detail")
    assert store.drawing_path(s["id"], one["id"], "html").read_text() == DOC
    assert store.drawing_path(s["id"], one["id"], "png").read_bytes() == PNG
    assert one["caption"] == "Plant detail — drawn in Acme's brand" and one["brand_source"] == "company"
    assert one["viewport"] == "desktop"

    # Current drawings are not drawn again…
    assert drawer.start(s, None, COMPANY) == []
    # …a changed screen is, and only that one…
    s["board"]["screens"][0]["shows"] = ["name", "last watered", "photo"]
    assert [d["screen"] for d in drawer.start(s, None, COMPANY)] == ["Plant detail"]
    _settled(s["id"], 2)
    assert drawn.count("Plant detail") == 2 and drawn.count("Plant list") == 1
    # …a changed brand dates every drawing…
    assert len(drawer.start(s, None, {**COMPANY, "colors": {"primary": "#000"}})) == 2
    _settled(s["id"], 2)
    # …and a note redraws the named screen whatever its state.
    assert [d["screen"] for d in drawer.start(s, ["plant list"], COMPANY, note="denser")] == ["Plant list"]
    _settled(s["id"], 2)
    assert drawn[-1] == "Plant list"


def test_a_drawing_that_fails_says_so_on_its_card(monkeypatch):
    def boom(session, screen, brand, note=""):
        raise RuntimeError("the drawer did not answer with a document that stands alone")
    monkeypatch.setattr(drawer, "draw", boom)
    s = _session()
    drawer.start(s, None, COMPANY)
    row = _settled(s["id"], 1)[0]
    assert row["status"] == "failed" and "stands alone" in row["error"] and not row["html"]
    # Draw all / Redraw starts a failed one again without a note.
    monkeypatch.setattr(drawer, "draw", lambda session, screen, brand, note="": DOC)
    monkeypatch.setattr(drawer, "picture", lambda html, viewport: None)
    assert len(drawer.start(s, None, COMPANY)) == 1
    row = _settled(s["id"], 1)[0]
    assert row["status"] == "done" and row["html"] and not row["png"]


def test_a_drawing_redrawn_meanwhile_is_not_replaced_by_the_older_result():
    s = _session()
    first = {"id": store.new_drawing_id(), "screen": "Plant detail", "status": "drawing", "at": time.time()}
    store.save_drawing(s["id"], first)
    second = {"id": store.new_drawing_id(), "screen": "Plant detail", "status": "drawing", "at": time.time()}
    store.save_drawing(s["id"], second)
    assert store.save_drawing(s["id"], {**first, "status": "done"}, if_current=True) is False
    assert store.drawings(s["id"])[0]["id"] == second["id"]
    assert store.save_drawing(s["id"], {**second, "status": "done"}, if_current=True) is True
    assert store.drawings(s["id"])[0]["status"] == "done"


def test_the_look_smith_puts_on_the_board_this_turn_counts(monkeypatch):
    """The brand is merged with the board where it is used, not once at the
    start of the turn: a `look` set by the same turn's `update_board` dated
    every drawing made before it (live, 2026-10-15)."""
    s = _session(())
    s["company_brand"] = {}
    agent.update_board(s, {"look": {"mood": "calm"}}, lambda e, d: None)
    assert agent.brand_of(s)["mood"] == "calm" and agent.brand_name(s) == "the board's look"
    s["company_brand"] = COMPANY
    assert agent.brand_name(s) == "Acme's brand"


def test_a_drawing_the_server_restarted_under_shows_as_failed(monkeypatch):
    s = _session()
    store.save_drawing(s["id"], {"id": store.new_drawing_id(), "screen": "Plant detail", "status": "drawing",
                                 "at": time.time() - store.STALE_AFTER - 1})
    row = store.drawings(s["id"])[0]
    assert row["status"] == "failed" and "restarted" in row["error"]


def test_update_board_draws_the_screens_it_adds_or_changes(monkeypatch):
    drawn: list[str] = []
    monkeypatch.setattr(drawer, "draw", lambda session, screen, brand, note="": drawn.append(screen["name"]) or DOC)
    monkeypatch.setattr(drawer, "picture", lambda html, viewport: None)
    s = _session(())
    s["company_brand"] = COMPANY
    events: list = []
    out, err = agent.update_board(s, {"screens": [SCREEN]}, lambda e, d: events.append((e, d)))
    assert not err and "Drawing 1 screen in Acme's brand: Plant detail" in out[0]["text"]
    assert [d["drawing"]["screen"] for e, d in events if e == "drawing"]
    _settled(s["id"], 1)
    # A change elsewhere on the board draws nothing.
    out, err = agent.update_board(s, {"decisions": ["Keep it simple"]}, lambda e, d: None)
    assert "Drawing" not in out[0]["text"]
    assert drawn == ["Plant detail"]


def test_draw_screens_redraws_what_the_person_asked_with_their_note(monkeypatch):
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(drawer, "draw", lambda session, screen, brand, note="": seen.append((screen["name"], note)) or DOC)
    monkeypatch.setattr(drawer, "picture", lambda html, viewport: None)
    s = _session()
    s["company_brand"] = COMPANY
    drawer.start(s, None, COMPANY)
    _settled(s["id"], 1)
    out, err = agent.draw_screens(s, {"screens": ["Plant detail"], "note": "bigger photo"}, lambda e, d: None)
    assert not err and "Plant detail" in out[0]["text"]
    _settled(s["id"], 1)
    assert seen[-1] == ("Plant detail", "bigger photo")
    out, err = agent.draw_screens(s, {"screens": ["Nowhere"]}, lambda e, d: None)
    assert err and "Not on the board: Nowhere" in out[0]["text"]
    out, err = agent.draw_screens(s, {}, lambda e, d: None)
    assert not err and "current already" in out[0]["text"]


def test_the_drawers_spend_is_counted_to_the_session(monkeypatch):
    class Msg:
        usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                cache_creation_input_tokens=0, server_tool_use=None)
        content = [SimpleNamespace(type="text", text=DOC)]
        stop_reason = "end_turn"

    class S:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return Msg()
    monkeypatch.setattr(drawer, "_client", lambda: SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: S())))
    monkeypatch.setattr(drawer, "picture", lambda html, viewport: None)
    s = _session()
    store.save(s)
    drawer.start(s, None, COMPANY)
    _settled(s["id"], 1)
    assert s["usage"]["output_tokens"] == 5
    assert store.load(s["id"])["usage"]["output_tokens"] == 5


def test_smith_and_the_writer_are_told_the_companys_brand():
    """The first live run (Spoke, 2026-10-15): Smith put an orange-and-cream
    look of his own on the board while the screens were drawn in the
    company's teal, and the requirements document then told the build the
    drawings 'came out in another brand's styling'."""
    from services.drafts_room import document
    s = _session()
    s["company_brand"] = COMPANY
    told = "\n".join(b["text"] for b in agent.user_content(s, "hello", []) if b["type"] == "text")
    assert "Acme's own design language" in told and "never replace its colours" in told
    material = document.material_for(s)
    assert "built in it and the drawings are in it" in material and "primary #1B7F5A" in material
    s["company_brand"] = {}
    assert "brand on record" not in document.material_for(s)
    assert "brand on record" not in "\n".join(b["text"] for b in agent.user_content(s, "hello", []) if b["type"] == "text")

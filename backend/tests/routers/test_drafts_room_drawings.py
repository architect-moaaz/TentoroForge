"""The drawings' routes, and the drawings' pictures handed to the build."""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import pytest

from routers import blueprint_generate
from routers import drafts_room as router
from services.drafts_room import document, drawer, store


@pytest.fixture(autouse=True)
def _rooted(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path / "sessions")


DOC = "<!doctype html><html><body><h1>Plant detail</h1></body></html>"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def _drawn(session: dict, screen: str = "Plant detail", png: bool = True) -> dict:
    did = store.new_drawing_id()
    store.drawing_path(session["id"], did, "html").parent.mkdir(parents=True, exist_ok=True)
    store.drawing_path(session["id"], did, "html").write_text(DOC)
    if png:
        store.drawing_path(session["id"], did, "png").write_bytes(PNG)
    entry = {"id": did, "screen": screen, "status": "done", "viewport": "desktop", "fingerprint": "x", "html": True,
             "png": png, "caption": "", "brand_source": "company", "like": "", "error": None, "at": time.time()}
    store.save_drawing(session["id"], entry)
    return entry


def test_the_drawing_is_served_as_a_document_that_may_load_nothing(monkeypatch):
    s = store.create("org", "u", "")
    row = _drawn(s)
    monkeypatch.setattr(router, "_session", _ok)
    res = asyncio.run(router.read_drawing(uuid.uuid4(), s["id"], row["id"], user=None, db=None))
    assert res.media_type.startswith("text/html") and res.body.decode() == DOC
    assert res.headers["content-security-policy"].startswith("default-src 'none'")


async def _ok(org_id, sid, user, db):
    return store.load(sid)


def test_a_drawing_of_another_session_or_without_a_picture_is_not_found(monkeypatch):
    from fastapi import HTTPException
    s = store.create("org", "u", "")
    other = store.create("org", "u", "")
    row = _drawn(other)
    monkeypatch.setattr(router, "_session", _ok)
    with pytest.raises(HTTPException) as got:
        asyncio.run(router.read_drawing(uuid.uuid4(), s["id"], row["id"], user=None, db=None))
    assert got.value.status_code == 404
    bare = _drawn(s, "Plant list", png=False)
    with pytest.raises(HTTPException) as got:
        asyncio.run(router.read_drawing_picture(uuid.uuid4(), s["id"], bare["id"], user=None, db=None))
    assert got.value.status_code == 404 and "no picture" in got.value.detail
    pic = asyncio.run(router.read_drawing_picture(uuid.uuid4(), s["id"], _drawn(s, "Care log")["id"], user=None, db=None))
    assert pic.media_type == "image/png"


def test_draw_all_starts_the_boards_screens_in_the_companys_brand(monkeypatch):
    s = store.create("org", "u", "")
    s["board"]["product"] = {"name": "Garden Log", "platforms": ["web"]}
    s["board"]["screens"] = [{"name": "Plant detail", "purpose": "One plant"}]
    store.save(s)
    monkeypatch.setattr(router, "_session", _ok)

    async def company(org_id, db):
        return {"source": "company", "company": "Acme", "colors": {"primary": "#123456"}}
    monkeypatch.setattr(router.brands, "for_org", company)
    asked: list = []
    monkeypatch.setattr(drawer, "start", lambda session, names, brand, note="", emit=None:
                        asked.append((names, brand["source"], brand["company"], note)) or [])
    out = asyncio.run(router.draw(uuid.uuid4(), s["id"], router.Draw(screens=["Plant detail"], note="  denser  "),
                                  user=None, db=None))
    assert asked == [(["Plant detail"], "company", "Acme", "denser")] and out == []
    shown = router._shown(store.load(s["id"]) | {"company_brand": {"source": "company", "company": "Acme"}})
    assert shown["brand"] == {"source": "company", "company": "Acme"} and shown["drawings"] == []
    assert "company_brand" not in store.load(s["id"]) and "company_brand" not in shown   # transient


@pytest.mark.asyncio
async def test_the_drawings_pictures_reach_the_build_as_design_references(test_db, monkeypatch):
    from sqlalchemy import select
    from database import async_session
    from models.project import Project
    from services.blueprint import references

    monkeypatch.setattr(document, "write", lambda session: "# Threadline\n")

    async def tree(project, db):
        out = Path(project.output_dir)
        return out, str(out / "app")
    monkeypatch.setattr(blueprint_generate, "prepare_project_tree", tree)

    def start(loop, project, **kw):
        fut: asyncio.Future = loop.create_future()
        fut.set_result({"status": "complete"})
        return fut
    monkeypatch.setattr(blueprint_generate, "start_build_in_background", start)

    s = store.create("org", "u", "")
    s["board"]["product"]["pitch"] = "A wardrobe app."
    s["board"]["screens"] = [{"name": "Outfit of the day"}, {"name": "Wardrobe"}]
    s["handoff_request"] = {"app_name": "Threadline", "note": "", "at": 1.0}
    _drawn(s, "Outfit of the day")
    _drawn(s, "Wardrobe", png=False)
    _drawn(s, "Old screen")                         # drawn once, no longer on the board: not carried
    events: list = []
    await router._hand_off(s, uuid.uuid4(), uuid.uuid4(), lambda e, d: events.append((e, d)))
    async with async_session() as db:
        project = (await db.execute(select(Project))).scalars().one()
    kept = [p.name for p in references.paths(project.output_dir)]
    assert kept == ["Outfit-of-the-day-drawn-in-the-Drafts-Room.png"]
    assert any("1 drawn screen as design references" in d.get("text", "") for e, d in events if e == "step")

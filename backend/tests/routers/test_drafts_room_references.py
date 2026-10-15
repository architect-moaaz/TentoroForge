"""The reference, recording, evidence, card and draft routes."""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from fastapi import HTTPException

from routers import drafts_room as router
from services.drafts_room import agent, capture, drafts, researcher, store


@pytest.fixture(autouse=True)
def _rooted(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path / "sessions")


async def _ok(org_id, sid, user, db):
    return store.load(sid)


def _started(monkeypatch):
    seen: list = []
    monkeypatch.setattr(researcher, "start", lambda session, name, focus="", reference_id="":
                        seen.append(("surface", name, reference_id)) or store.new_job(session["id"], name, reference_id=reference_id))
    monkeypatch.setattr(capture, "start", lambda session, ref, focus="":
                        seen.append(("deep", ref["name"], ref["id"])) or store.new_job(session["id"], ref["name"], kind="deep", source="web", reference_id=ref["id"]))
    from services.smith import web
    monkeypatch.setattr(web, "check_url", lambda url, said: url)
    return seen


def test_adding_a_reference_starts_both_studies(monkeypatch):
    seen = _started(monkeypatch)
    s = store.create("org", "u", "")
    store.save(s)
    monkeypatch.setattr(router, "_session", _ok)
    refs = asyncio.run(router.add_reference(uuid.uuid4(), s["id"], router.NewReference(name="Garden", url="https://garden.test"),
                                            user=None, db=None))
    assert len(refs) == 1 and refs[0]["name"] == "Garden" and set(refs[0]["studies"]) == {"surface", "deep"}
    assert [k for k, _, _ in seen] == ["surface", "deep"] and seen[0][2] == refs[0]["id"]
    shown = router._shown(store.load(s["id"]))
    assert shown["references"][0]["id"] == refs[0]["id"] and len(shown["research"]) == 2
    assert {j["kind"] for j in shown["research"]} == {"surface", "deep"}
    assert shown["research"][0]["evidence"] == {"observed": 0, "derived": 0, "inferred": 0, "unknown": 0}


def test_a_reference_the_person_did_not_name_is_refused(monkeypatch):
    from services.smith import web
    monkeypatch.setattr(web, "check_url", lambda url, said: (_ for _ in ()).throw(web.WebRefused("not named")))
    s = store.create("org", "u", "")
    out, err = agent.add_reference(s, {"name": "X", "url": "https://x.test"}, lambda e, d: None)
    assert err and "not named" in out[0]["text"] and store.references(s["id"]) == []


def test_a_recording_lands_as_a_study_and_the_evidence_route_filters(monkeypatch, tmp_path):
    monkeypatch.setattr(router, "_session", _ok)
    monkeypatch.setattr(capture, "_cards_after", lambda sid, rid: None)
    s = store.create("org", "u", "")
    ref = store.new_reference(s["id"], "Shop", "https://app.shop.test", added_by="u")
    har = {"log": {"entries": [{"request": {"method": "GET", "url": "https://app.shop.test/api/orders", "headers": []},
                                "response": {"status": 200, "headers": [], "content": {"mimeType": "application/json",
                                                                                      "text": json.dumps([{"id": 1, "status": "paid"}])}}}]}}

    class Up:
        async def read(self, n):
            return json.dumps(har).encode()
    out = asyncio.run(router.upload_recording(uuid.uuid4(), s["id"], ref["id"], file=Up(), user=None, db=None))
    assert out["calls"] == 1 and out["reference"]["har"]["calls"] == 1 and "evidence" not in out["study"]
    jid = out["study"]["id"]
    rows = asyncio.run(router.read_evidence(uuid.uuid4(), s["id"], jid, standing="observed", kind="record", user=None, db=None))
    assert [r["text"] for r in rows] == ["orders"] and rows[0]["sources"][0]["type"] == "har"
    assert asyncio.run(router.read_evidence(uuid.uuid4(), s["id"], jid, standing="unknown", kind="", user=None, db=None)) == []

    class Bad:
        async def read(self, n):
            return b"<html>"
    with pytest.raises(HTTPException) as got:
        asyncio.run(router.upload_recording(uuid.uuid4(), s["id"], ref["id"], file=Bad(), user=None, db=None))
    assert got.value.status_code == 422


def test_draft_routes_serve_versions_diffs_notes_and_drawings(monkeypatch):
    monkeypatch.setattr(router, "_session", _ok)
    s = store.create("org", "u", "")
    s["board"]["product"] = {"name": "Leaf", "platforms": ["web"]}
    store.save(s)
    did = store.new_draft_id()
    v1 = {"id": did, "version": 1, "title": "A", "pitch": "p", "screens": [{"name": "Plants", "purpose": "all"}], "records": [],
          "rules": ["r1"], "notes": [], "changed": "first draft", "created": 1.0, "at": 1.0}
    store.save_draft_version(s["id"], did, v1)
    store.save_draft_version(s["id"], did, {**v1, "version": 2, "rules": [], "changed": "dropped r1", "at": 2.0})
    one = asyncio.run(router.read_draft(uuid.uuid4(), s["id"], did, user=None, db=None))
    assert one["latest"]["version"] == 2 and one["diffs"] == [{"from": 1, "to": 2, "changed": "dropped r1",
                                                               "diff": {"rules": {"added": [], "removed": ["r1"]}}}]
    noted = asyncio.run(router.pin_note(uuid.uuid4(), s["id"], did, router.Note(on="screen:Plants", text="bigger"), user=None, db=None))
    assert noted["notes"][0]["text"] == "bigger"
    listed = asyncio.run(router.list_drafts(uuid.uuid4(), s["id"], user=None, db=None))
    assert listed[0]["version"] == 2 and [v["version"] for v in listed[0]["versions"]] == [1, 2]

    async def company(org_id, db):
        return {}
    monkeypatch.setattr(router.brands, "for_org", company)
    from services.drafts_room import drawer
    asked: list = []
    monkeypatch.setattr(drawer, "start", lambda session, names, brand, note="", emit=None, scope="board", screens=None:
                        asked.append((scope, [x["name"] for x in screens or []])) or [])
    asyncio.run(router.draw_draft(uuid.uuid4(), s["id"], did, user=None, db=None))
    assert asked == [(f"draft:{did}", ["Plants"])]
    with pytest.raises(HTTPException):
        asyncio.run(router.read_draft(uuid.uuid4(), s["id"], "000000000000", user=None, db=None))


def test_a_stop_asks_the_deep_study_to_stop_at_its_next_page(monkeypatch):
    monkeypatch.setattr(router, "_session", _ok)
    s = store.create("org", "u", "")
    job = store.new_job(s["id"], "Garden", kind="deep", source="web")
    out = asyncio.run(router.stop_study(uuid.uuid4(), s["id"], job["id"], user=None, db=None))
    assert out["stopping"] is True and (store.job_dir(s["id"], job["id"]) / "stop").is_file()

"""The Drafts Room's hand-off: the app is created with the pitch as its
description, the document is kept and handed to the builder's Smith, and the
build is started here — not by the person's browser arriving.

Before this the description was `pitch or document[:500]`, the opening carried
the whole document, and the build began only when the project page replayed
that opening from sessionStorage.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from routers import blueprint_generate
from routers import drafts_room as router
from services.drafts_room import document, store

DOC = "# Threadline\n\n## Overview\nA wardrobe app.\n\n## Features\n- [must] Log an outfit\n"
PITCH = "A wardrobe app that helps people wear what they own."


def _session(pitch: str = PITCH) -> dict:
    s = store.create("org", "u", "")
    s["board"]["product"]["pitch"] = pitch
    s["handoff_request"] = {"app_name": "Threadline", "note": "", "at": 1.0}
    return s


@pytest.mark.asyncio
async def test_the_app_is_created_described_briefed_and_built(test_db, tmp_path, monkeypatch):
    from sqlalchemy import select
    from database import async_session
    from models.project import Project

    monkeypatch.setattr(document, "write", lambda session: DOC)

    async def tree(project, db):
        out = Path(project.output_dir)
        return out, str(out / "app")
    monkeypatch.setattr(blueprint_generate, "prepare_project_tree", tree)
    asked: list[dict] = []

    def start(loop, project, **kw):
        asked.append({"project": project, **kw})
        fut: asyncio.Future = loop.create_future()
        fut.set_result({"status": "complete"})
        return fut
    monkeypatch.setattr(blueprint_generate, "start_build_in_background", start)

    s = _session()
    events: list = []
    await router._hand_off(s, uuid.uuid4(), uuid.uuid4(), lambda e, d: events.append((e, d)))

    async with async_session() as db:
        project = (await db.execute(select(Project))).scalars().one()
    assert project.name == "Threadline" and project.description == PITCH
    assert Path(project.output_dir, "requirements.md").read_text() == DOC
    assert len(asked) == 1 and asked[0]["project"].id == project.id
    assert asked[0]["description"] == PITCH and asked[0]["documents"] == [DOC]
    assert asked[0]["message"].startswith("Build Threadline") and DOC not in asked[0]["message"]
    assert asked[0]["app_name"] == "Threadline" and asked[0]["app_root"].endswith("/app")
    assert s["handoff"]["build"] == "started" and s["handoff"]["description"] == PITCH
    handoff = next(d for e, d in events if e == "handoff")
    assert handoff["build"] == "started" and handoff["description"] == PITCH and "opening" not in handoff
    assert [d["text"] for e, d in events if e == "step"] == [
        "Writing the requirements document…", "Creating Threadline…", "Starting the build…"]
    assert "being built" in s["chat"][-1]["text"] and s["chat"][-1]["handoff"]["project_id"] == str(project.id)


@pytest.mark.asyncio
async def test_a_build_that_does_not_start_still_leaves_the_app(test_db, tmp_path, monkeypatch):
    from sqlalchemy import select
    from database import async_session
    from models.project import Project

    monkeypatch.setattr(document, "write", lambda session: DOC)

    async def tree(project, db):
        out = Path(project.output_dir)
        return out, str(out / "app")
    monkeypatch.setattr(blueprint_generate, "prepare_project_tree", tree)

    def start(loop, project, **kw):
        raise RuntimeError("no executor")
    monkeypatch.setattr(blueprint_generate, "start_build_in_background", start)

    s = _session()
    events: list = []
    await router._hand_off(s, uuid.uuid4(), uuid.uuid4(), lambda e, d: events.append((e, d)))

    async with async_session() as db:
        assert (await db.execute(select(Project))).scalars().one().name == "Threadline"
    assert s["handoff"]["build"] == "not_started" and "no executor" in s["handoff"]["error"]
    handoff = next(d for e, d in events if e == "handoff")
    assert handoff["build"] == "not_started" and handoff["error"] == "no executor"
    assert "did not start" in s["chat"][-1]["text"]


@pytest.mark.asyncio
async def test_a_request_without_a_pitch_creates_nothing(test_db, monkeypatch):
    from sqlalchemy import select
    from database import async_session
    from models.project import Project

    monkeypatch.setattr(document, "write", lambda session: DOC)
    s = _session(pitch="")
    events: list = []
    await router._hand_off(s, uuid.uuid4(), uuid.uuid4(), lambda e, d: events.append((e, d)))
    async with async_session() as db:
        assert (await db.execute(select(Project))).scalars().all() == []
    assert "handoff_request" not in s and not s.get("handoff")
    assert any(e == "error" and "pitch" in d["message"] for e, d in events)

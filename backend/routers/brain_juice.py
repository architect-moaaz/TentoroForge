"""Brain Juice — Smith and a person work an idea out, outside any app.

    GET    /api/orgs/{org}/brain-juice                      the organisation's sessions
    POST   /api/orgs/{org}/brain-juice                      a new session
    GET    /api/orgs/{org}/brain-juice/{sid}                one session: chat, board, files, hand-off
    DELETE /api/orgs/{org}/brain-juice/{sid}
    POST   /api/orgs/{org}/brain-juice/{sid}/files          drop in a picture or a PDF
    GET    /api/orgs/{org}/brain-juice/{sid}/files/{fid}    one of the session's files
    POST   /api/orgs/{org}/brain-juice/{sid}/message        a message; Smith's answer streams back (SSE)

The answer streams as `step` (what Smith is doing), `delta` (his words as they
come), `file` (a screenshot he took), `board` (the idea board changed),
`research` (a study the Researcher started or that Smith read),
`message` (his whole answer), `handoff` (the app made, its build to start),
`done` and `error`. The turn runs on its own: hanging up does not lose it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from routers.discovery import _require_org_member_simple
from services.brain_juice import store

logger = logging.getLogger(__name__)
router = APIRouter(tags=["brain-juice"])

#: One turn at a time per session.
_BUSY: set[str] = set()


class NewSession(BaseModel):
    title: str = ""


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    files: list[str] = Field(default_factory=list)


async def _session(org_id: uuid.UUID, sid: str, user: PlatformUser, db: AsyncSession) -> dict:
    await _require_org_member_simple(org_id, user, db)
    try:
        session = store.load(sid)
    except store.NotFound:
        raise HTTPException(status_code=404, detail="No such Brain Juice session") from None
    if session.get("org_id") != str(org_id):
        raise HTTPException(status_code=404, detail="No such Brain Juice session")
    return session


def _shown(session: dict) -> dict:
    """The session as the page reads it: not the model's own transcript; and
    the Researcher's studies, as far as each has got."""
    studies = [{**j, "steps": (j.get("steps") or [])[-60:]} for j in store.jobs(session["id"])]
    return {k: v for k, v in session.items() if k not in ("turns",)} | {"busy": session["id"] in _BUSY,
                                                                       "research": studies}


@router.get("/api/orgs/{org_id}/brain-juice")
async def list_sessions(org_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    await _require_org_member_simple(org_id, user, db)
    return store.listed(str(org_id))


@router.post("/api/orgs/{org_id}/brain-juice", status_code=201)
async def new_session(org_id: uuid.UUID, req: NewSession, user: PlatformUser = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    await _require_org_member_simple(org_id, user, db)
    return _shown(store.create(str(org_id), str(user.id), req.title))


@router.get("/api/orgs/{org_id}/brain-juice/{sid}")
async def read_session(org_id: uuid.UUID, sid: str, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    return _shown(await _session(org_id, sid, user, db))


@router.delete("/api/orgs/{org_id}/brain-juice/{sid}", status_code=204)
async def delete_session(org_id: uuid.UUID, sid: str, user: PlatformUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    await _session(org_id, sid, user, db)
    store.delete(sid)


@router.post("/api/orgs/{org_id}/brain-juice/{sid}/files", status_code=201)
async def upload(org_id: uuid.UUID, sid: str, file: UploadFile = File(...),
                 user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await _session(org_id, sid, user, db)
    data = await file.read(store.MAX_UPLOAD + 1)
    kind = store.sniff(data)
    try:
        meta = store.add_file(session, data, name=file.filename or "upload", media_type=kind, origin="upload")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    store.save(session)
    return meta


@router.get("/api/orgs/{org_id}/brain-juice/{sid}/files/{fid}")
async def read_file(org_id: uuid.UUID, sid: str, fid: str, user: PlatformUser = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    session = await _session(org_id, sid, user, db)
    try:
        meta = store.file_meta(session, fid)
        path = store.file_path(session, fid)
    except store.NotFound:
        raise HTTPException(status_code=404, detail="No such file") from None
    return FileResponse(str(path), media_type=meta["media_type"])


@router.post("/api/orgs/{org_id}/brain-juice/{sid}/message")
async def send_message(org_id: uuid.UUID, sid: str, req: Message,
                       user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await _session(org_id, sid, user, db)
    if sid in _BUSY:
        raise HTTPException(status_code=409, detail="Smith is still answering the last message")
    for fid in req.files:
        try:
            store.file_meta(session, fid)
        except store.NotFound:
            raise HTTPException(status_code=422, detail=f"No file {fid} in this session") from None

    session.setdefault("chat", []).append({"role": "user", "text": req.text, "files": list(req.files),
                                           "at": time.time()})
    if len([m for m in session["chat"] if m.get("role") == "user"]) == 1 and session.get("title") == "New idea":
        session["title"] = " ".join(req.text.split())[:80]
    store.save(session)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: str, data: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, data))

    async def work() -> None:
        from services.brain_juice import agent
        _BUSY.add(sid)
        try:
            entry = await asyncio.to_thread(agent.turn, session, req.text, list(req.files), emit)
            session["chat"].append(entry)
            name = ((session.get("board") or {}).get("product") or {}).get("name")
            if name and session.get("title", "").startswith(" ".join(req.text.split())[:20]):
                session["title"] = name
            store.save(session)
            emit("message", entry)
            if session.get("handoff_request") and not session.get("handoff"):
                await _hand_off(session, org_id, user.id, emit)
            emit("done", {"status": "ok"})
        except Exception as exc:  # noqa: BLE001 — said to the person, kept in the log
            logger.exception("brain juice turn %s", sid)
            store.save(session)
            emit("error", {"message": f"{type(exc).__name__}: {str(exc)[:300]}"})
        finally:
            _BUSY.discard(sid)
            emit("__end__", {})

    asyncio.create_task(work())

    async def stream():
        while True:
            event, data = await queue.get()
            if event == "__end__":
                return
            yield {"event": event, "data": json.dumps(data, default=str)}

    return EventSourceResponse(stream())


async def _hand_off(session: dict, org_id: uuid.UUID, owner_id: uuid.UUID, emit) -> None:
    """The agreed idea, made into an app: the requirements document written,
    the app created, the document kept in it — and the page told where to
    go and what to send, so the build starts as the person arrives."""
    from database import async_session
    from services.brain_juice import document
    from services.project_service import create_project

    request = session["handoff_request"]
    emit("step", {"text": "Writing the requirements document…"})
    doc = await asyncio.to_thread(document.write, session)
    emit("step", {"text": f"Creating {request['app_name']}…"})
    pitch = ((session.get("board") or {}).get("product") or {}).get("pitch") or ""
    # ITS OWN DATABASE SESSION: this runs after the answer began streaming,
    # when the request's session may already be closed.
    async with async_session() as db:
        project = await create_project(org_id=org_id, owner_id=owner_id, name=request["app_name"],
                                       description=pitch or doc[:500], db=db)
        await db.commit()
        await db.refresh(project)
    try:
        Path(project.output_dir, "requirements.md").write_text(doc)
    except OSError:
        logger.warning("brain juice: could not keep requirements.md in %s", project.output_dir)
    opening = document.opening(doc, request["app_name"])
    session["handoff"] = {"project_id": str(project.id), "app_name": request["app_name"], "document": doc,
                          "opening": opening, "at": time.time()}
    session.setdefault("chat", []).append({
        "role": "assistant", "at": time.time(), "files": [], "steps": [],
        "text": f"{request['app_name']} is created and its build is starting from the requirements document.",
        "handoff": {"project_id": str(project.id), "app_name": request["app_name"]}})
    store.save(session)
    emit("handoff", {"project_id": str(project.id), "org_id": str(org_id), "app_name": request["app_name"],
                     "opening": opening})

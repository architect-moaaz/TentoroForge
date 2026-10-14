"""the Drafts Room — Smith and a person work an idea out, outside any app.

    GET    /api/orgs/{org}/drafts-room                      the organisation's sessions
    POST   /api/orgs/{org}/drafts-room                      a new session
    GET    /api/orgs/{org}/drafts-room/{sid}                one session: chat, board, files, hand-off
    DELETE /api/orgs/{org}/drafts-room/{sid}
    POST   /api/orgs/{org}/drafts-room/{sid}/files          drop in a picture or a PDF
    GET    /api/orgs/{org}/drafts-room/{sid}/files/{fid}    one of the session's files
    POST   /api/orgs/{org}/drafts-room/{sid}/message        a message; Smith's answer streams back (SSE)
    GET    /api/orgs/{org}/drafts-room/{sid}/drawings/{id}.html   a screen drawn in the company's brand
    GET    /api/orgs/{org}/drafts-room/{sid}/drawings/{id}.png    its picture (404 without a browser)
    POST   /api/orgs/{org}/drafts-room/{sid}/draw           draw (again) screens of the board

The answer streams as `step` (what Smith is doing), `delta` (his words as they
come), `file` (a screenshot he took), `board` (the idea board changed),
`research` (a study the Researcher started or that Smith read),
`drawing` (a screen's drawing started or landed),
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
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from routers.discovery import _require_org_member_simple
from services.drafts_room import brand as brands
from services.drafts_room import store

logger = logging.getLogger(__name__)
router = APIRouter(tags=["drafts-room"])

#: One turn at a time per session.
_BUSY: set[str] = set()


class NewSession(BaseModel):
    title: str = ""


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    files: list[str] = Field(default_factory=list)


class Draw(BaseModel):
    screens: list[str] = Field(default_factory=list)
    note: str = Field(default="", max_length=2000)


async def _brand(session: dict, org_id: uuid.UUID, db: AsyncSession) -> dict:
    """The company's brand, read afresh so a company that edits its brand
    sees the next drawing in it; returned merged with the board as it
    stands (the agent merges again as the board moves)."""
    try:
        company = await brands.for_org(org_id, db)
    except Exception:  # noqa: BLE001 — no brand readable is a drawing in the board's look
        logger.exception("drafts room: the company's brand could not be read")
        company = {}
    session["company_brand"] = company
    return brands.merged(company, session.get("board") or {})


async def _session(org_id: uuid.UUID, sid: str, user: PlatformUser, db: AsyncSession) -> dict:
    await _require_org_member_simple(org_id, user, db)
    try:
        session = store.load(sid)
    except store.NotFound:
        raise HTTPException(status_code=404, detail="No such the Drafts Room session") from None
    if session.get("org_id") != str(org_id):
        raise HTTPException(status_code=404, detail="No such the Drafts Room session")
    return session


def _shown(session: dict) -> dict:
    """The session as the page reads it: not the model's own transcript; and
    the Researcher's studies, as far as each has got."""
    studies = [{**j, "steps": (j.get("steps") or [])[-60:]} for j in store.jobs(session["id"])]
    from services.drafts_room import drawer
    known = "company_brand" in session
    brand = brands.merged(session.get("company_brand") or {}, session.get("board") or {})
    # `stale` says the screen, the brand or the product changed since the
    # drawing — known only when the brand was read (the session GET and a turn).
    rows = (list(drawer.current(session, brand).values()) if known else store.drawings(session["id"]))
    return {k: v for k, v in session.items() if k not in ("turns", "company_brand")} | {
        "busy": session["id"] in _BUSY, "research": studies, "drawings": rows,
        "brand": {"source": brand.get("source") or "none", "company": brand.get("company") or ""}}


@router.get("/api/orgs/{org_id}/drafts-room")
async def list_sessions(org_id: uuid.UUID, user: PlatformUser = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    await _require_org_member_simple(org_id, user, db)
    return store.listed(str(org_id))


@router.post("/api/orgs/{org_id}/drafts-room", status_code=201)
async def new_session(org_id: uuid.UUID, req: NewSession, user: PlatformUser = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    await _require_org_member_simple(org_id, user, db)
    return _shown(store.create(str(org_id), str(user.id), req.title))


@router.get("/api/orgs/{org_id}/drafts-room/{sid}")
async def read_session(org_id: uuid.UUID, sid: str, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    session = await _session(org_id, sid, user, db)
    await _brand(session, org_id, db)
    return _shown(session)


@router.delete("/api/orgs/{org_id}/drafts-room/{sid}", status_code=204)
async def delete_session(org_id: uuid.UUID, sid: str, user: PlatformUser = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    await _session(org_id, sid, user, db)
    store.delete(sid)


@router.post("/api/orgs/{org_id}/drafts-room/{sid}/files", status_code=201)
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


@router.get("/api/orgs/{org_id}/drafts-room/{sid}/files/{fid}")
async def read_file(org_id: uuid.UUID, sid: str, fid: str, user: PlatformUser = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    session = await _session(org_id, sid, user, db)
    try:
        meta = store.file_meta(session, fid)
        path = store.file_path(session, fid)
    except store.NotFound:
        raise HTTPException(status_code=404, detail="No such file") from None
    return FileResponse(str(path), media_type=meta["media_type"])


@router.get("/api/orgs/{org_id}/drafts-room/{sid}/drawings/{did}.html")
async def read_drawing(org_id: uuid.UUID, sid: str, did: str, user: PlatformUser = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """The drawn page itself. It is shown in a sandboxed frame; the policy
    says it may load nothing from anywhere."""
    await _session(org_id, sid, user, db)
    try:
        path = store.drawing_path(sid, did, "html")
        html = path.read_text()
    except (store.NotFound, OSError):
        raise HTTPException(status_code=404, detail="No such drawing") from None
    return Response(html, media_type="text/html; charset=utf-8", headers={
        "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:",
        "Cache-Control": "private, max-age=3600"})


@router.get("/api/orgs/{org_id}/drafts-room/{sid}/drawings/{did}.png")
async def read_drawing_picture(org_id: uuid.UUID, sid: str, did: str,
                               user: PlatformUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _session(org_id, sid, user, db)
    try:
        path = store.drawing_path(sid, did, "png")
    except store.NotFound:
        raise HTTPException(status_code=404, detail="No such drawing") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="This drawing has no picture")
    return FileResponse(str(path), media_type="image/png")


@router.post("/api/orgs/{org_id}/drafts-room/{sid}/draw")
async def draw(org_id: uuid.UUID, sid: str, req: Draw, user: PlatformUser = Depends(get_current_user),
               db: AsyncSession = Depends(get_db)):
    """Draw (again) screens of the board — the Screens tab's Draw all and
    Redraw. Returns the drawings as they now stand; they fill in while the
    page polls."""
    from services.drafts_room import drawer
    session = await _session(org_id, sid, user, db)
    if not (session.get("board") or {}).get("screens"):
        raise HTTPException(status_code=422, detail="There are no screens on the board to draw yet")
    brand = await _brand(session, org_id, db)
    names = [n for n in req.screens if n.strip()] or None
    drawer.start(session, names, brand, note=" ".join(req.note.split()))
    return store.drawings(sid)


@router.post("/api/orgs/{org_id}/drafts-room/{sid}/message")
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

    await _brand(session, org_id, db)                   # what this turn's drawings are drawn in
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
        from services.drafts_room import agent
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
            logger.exception("drafts room turn %s", sid)
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


def _adopt_drawings(session: dict, output_dir: Path) -> int:
    """The drawings' pictures, placed beside the new app's Blueprint as its
    design references, so the pages are built to the screens that were
    agreed. A drawing without a picture (no browser here) is passed over."""
    from services.blueprint import references
    count = 0
    for row in store.drawings(session["id"]):
        if row.get("status") != "done" or not row.get("png"):
            continue
        try:
            data = store.drawing_path(session["id"], row["id"], "png").read_bytes()
        except (store.NotFound, OSError):
            continue
        stored = references.adopt_bytes(output_dir, f"{row['screen']} drawn in the Drafts Room.png", data,
                                        media_type="image/png", fallback=row["id"])
        count += 1 if stored is not None else 0
    return count


async def _hand_off(session: dict, org_id: uuid.UUID, owner_id: uuid.UUID, emit) -> None:
    """The agreed idea, made into an app: the requirements document written,
    the app created with the board's pitch as its description, the document
    kept beside the Blueprint for the agents that read documents, the app
    builder's Smith told to build from it, and the build started here on the
    platform — not by the person's browser arriving."""
    from database import async_session
    from routers.blueprint_generate import prepare_project_tree, start_build_in_background
    from services.drafts_room import agent, document
    from services.project_service import create_project

    request = session["handoff_request"]
    name = request["app_name"]
    description = agent.pitch_of(session)
    if not description:
        # `hand_off` refuses without a pitch; a request recorded before that
        # rule is sent back the same way rather than given a made-up one.
        session.pop("handoff_request", None)
        store.save(session)
        emit("error", {"message": "The board has no pitch yet, so the app was not created. "
                                  "Ask Smith to set the pitch, then say build again."})
        return
    emit("step", {"text": "Writing the requirements document…"})
    doc = await asyncio.to_thread(document.write, session)
    emit("step", {"text": f"Creating {name}…"})
    # ITS OWN DATABASE SESSION: this runs after the answer began streaming,
    # when the request's session may already be closed.
    async with async_session() as db:
        project = await create_project(org_id=org_id, owner_id=owner_id, name=name,
                                       description=description, db=db)
        await db.commit()
        await db.refresh(project)
        output_dir, app_root = await prepare_project_tree(project, db)
    adopted = _adopt_drawings(session, output_dir)
    if adopted:
        emit("step", {"text": f"Handing over {adopted} drawn screen{'s' if adopted != 1 else ''} as design references…"})
    try:
        Path(project.output_dir, "requirements.md").write_text(doc)
    except OSError:
        logger.warning("drafts room: could not keep requirements.md in %s", project.output_dir)
    opening = document.opening(name, description)
    handoff: dict = {"project_id": str(project.id), "app_name": name, "description": description,
                     "document": doc, "opening": opening, "at": time.time()}
    emit("step", {"text": "Starting the build…"})
    try:
        start_build_in_background(asyncio.get_running_loop(), project, message=opening, description=description,
                                  documents=[doc], app_name=name, output_dir=output_dir, app_root=app_root)
        handoff["build"] = "started"
        said = f"{name} is created and being built from the requirements document. Open it to watch."
    except Exception as exc:  # noqa: BLE001 — the app exists; the build can be asked for there
        logger.exception("drafts room: the build of %s did not start", project.id)
        handoff["build"] = "not_started"
        handoff["error"] = str(exc)
        said = (f"{name} is created, but its build did not start ({type(exc).__name__}). "
                "Open it and ask Smith to build it.")
    session["handoff"] = handoff
    session.setdefault("chat", []).append({
        "role": "assistant", "at": time.time(), "files": [], "steps": [], "text": said,
        "handoff": {"project_id": str(project.id), "app_name": name}})
    store.save(session)
    emit("handoff", {"project_id": str(project.id), "org_id": str(org_id), "app_name": name,
                     "description": description, "build": handoff["build"],
                     **({"error": handoff["error"]} if "error" in handoff else {})})

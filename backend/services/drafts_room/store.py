"""A Drafts Room session on disk.

One directory per session under the platform's data directory
(`data/drafts_room/<id>/`): `session.json` holds who it belongs to, the
conversation as the person sees it, the conversation as the model was sent it
(`turns`, append-only so its thinking stays valid), the idea board and the
hand-off; `files/` holds the screenshots Smith took and what the person
dropped in; `drawings/` holds each screen of the board drawn in the
company's brand. Sessions are files rather than rows: they are a working space,
not part of any application, and they carry pictures.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("FORGE_DRAFTS_ROOM_DIR") or _BACKEND / "data" / "drafts_room")

#: What the person may drop in: pictures and PDFs, by what the bytes are.
KINDS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
         "application/pdf": "pdf"}
MAX_UPLOAD = 20 * 1024 * 1024

_LOCK = threading.RLock()
_ID = re.compile(r"^[0-9a-f]{32}$")


class NotFound(LookupError):
    pass


def _dir(sid: str) -> Path:
    if not _ID.match(str(sid or "")):
        raise NotFound(sid)
    return ROOT / sid


def _empty_board() -> dict:
    from services.drafts_room.board import empty
    return empty()


def create(org_id: str, user_id: str, title: str = "") -> dict:
    sid = uuid.uuid4().hex
    now = time.time()
    session = {"id": sid, "org_id": str(org_id), "user_id": str(user_id),
               "title": title.strip()[:120] or "New idea", "created_at": now, "updated_at": now,
               "chat": [], "turns": [], "board": _empty_board(), "files": [],
               "handoff": None, "usage": {"input_tokens": 0, "output_tokens": 0,
                                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                                          "web_search_requests": 0}}
    with _LOCK:
        (_dir(sid) / "files").mkdir(parents=True, exist_ok=True)
        _write(session)
    return session


#: Held on the session while a request runs, never written: the company's
#: brand is read afresh each turn (and carries the logo's bytes).
TRANSIENT = ("company_brand",)


def _write(session: dict) -> None:
    path = _dir(session["id"]) / "session.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: v for k, v in session.items() if k not in TRANSIENT}, default=str))
    tmp.replace(path)


def load(sid: str) -> dict:
    try:
        return json.loads((_dir(sid) / "session.json").read_text())
    except (OSError, ValueError) as exc:
        raise NotFound(sid) from exc


def save(session: dict) -> None:
    with _LOCK:
        session["updated_at"] = time.time()
        _write(session)


def listed(org_id: str) -> list[dict]:
    """The organisation's sessions, newest first, without their contents."""
    out = []
    if not ROOT.is_dir():
        return out
    for d in ROOT.iterdir():
        try:
            s = json.loads((d / "session.json").read_text())
        except (OSError, ValueError):
            continue
        if s.get("org_id") != str(org_id):
            continue
        out.append({"id": s["id"], "title": s.get("title"), "updated_at": s.get("updated_at"),
                    "created_at": s.get("created_at"), "user_id": s.get("user_id"),
                    "agreed": (s.get("board") or {}).get("status") == "agreed",
                    "messages": len(s.get("chat") or []),
                    "project_id": (s.get("handoff") or {}).get("project_id")})
    return sorted(out, key=lambda r: r.get("updated_at") or 0, reverse=True)


def delete(sid: str) -> None:
    import shutil
    with _LOCK:
        shutil.rmtree(_dir(sid), ignore_errors=True)


# ── files ──────────────────────────────────────────────────────────────────

def add_file(session: dict, data: bytes, *, name: str, media_type: str, origin: str,
             caption: str = "", source: str = "") -> dict:
    """A picture or a PDF kept with the session: one the person dropped in
    (`origin: upload`) or one Smith took (`origin: screenshot`)."""
    if media_type not in KINDS:
        raise ValueError(f"{media_type or 'that kind of file'} cannot be studied; pictures and PDFs can")
    if len(data) > MAX_UPLOAD:
        raise ValueError("that file is larger than 20 MB")
    fid = uuid.uuid4().hex[:16]
    path = _dir(session["id"]) / "files" / f"{fid}.{KINDS[media_type]}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    meta = {"id": fid, "name": re.sub(r"[\r\n\t]", " ", name)[:160] or fid, "media_type": media_type,
            "origin": origin, "caption": caption[:300], "source": source[:500], "size": len(data),
            "at": time.time()}
    session.setdefault("files", []).append(meta)
    return meta


def file_meta(session: dict, fid: str) -> dict:
    """A file of the session's — the person's, Smith's, or one the
    Researcher took for a study (`job` names it)."""
    for f in session.get("files") or []:
        if f.get("id") == fid:
            return f
    for job in jobs(session["id"]):
        for f in job.get("files") or []:
            if f.get("id") == fid:
                return f
    raise NotFound(fid)


def file_path(session: dict, fid: str) -> Path:
    meta = file_meta(session, fid)
    folder = _dir(session["id"]) / "research" / meta["job"] if meta.get("job") else _dir(session["id"])
    return folder / "files" / f"{fid}.{KINDS[meta['media_type']]}"


# ── research jobs ──────────────────────────────────────────────────────────
#
# A study the Researcher makes of a reference, kept in a folder of its own
# (`research/<job>/job.json` and its screenshots) so the background work and
# the conversation never write the same file.

#: A job that has said nothing for this long is not running any more (the
#: server was restarted under it).
STALE_AFTER = 600
_JOB = re.compile(r"^[0-9a-f]{12}$")


def _job_dir(sid: str, jid: str) -> Path:
    if not _JOB.match(str(jid or "")):
        raise NotFound(jid)
    return _dir(sid) / "research" / jid


def new_job(sid: str, reference: str, focus: str = "", *, kind: str = "surface", source: str = "",
            reference_id: str = "") -> dict:
    """A study: `surface` (the Researcher reading public pages) or `deep`
    (the platform browser recording a product, `source: web`, or the
    person's own recording, `source: har`). Both hold `evidence`."""
    from services.drafts_room.dossier import empty
    jid = uuid.uuid4().hex[:12]
    now = time.time()
    job = {"id": jid, "session_id": sid, "reference": reference[:200], "focus": focus[:1000],
           "kind": kind, "source": source, "reference_id": reference_id,
           "status": "running", "stage": "scouting" if kind == "surface" else "waiting", "started": now,
           "heartbeat": now, "finished": None,
           "steps": [], "surfaces": [], "dossier": empty(), "summary": "", "files": [], "error": None,
           "read": False, "evidence": [], "capture": {"pages": 0, "calls": 0, "hosts": [], "stopped_on": None},
           "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                     "cache_creation_input_tokens": 0, "web_search_requests": 0}}
    (_job_dir(sid, jid) / "files").mkdir(parents=True, exist_ok=True)
    save_job(job)
    return job


def save_job(job: dict) -> None:
    with _LOCK:
        path = _job_dir(job["session_id"], job["id"]) / "job.json"
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(job, default=str))
        tmp.replace(path)


def load_job(sid: str, jid: str) -> dict:
    try:
        job = json.loads((_job_dir(sid, jid) / "job.json").read_text())
    except (OSError, ValueError) as exc:
        raise NotFound(jid) from exc
    if job.get("status") == "running" and time.time() - float(job.get("heartbeat") or 0) > STALE_AFTER:
        job["status"] = "stopped"
        job["error"] = job.get("error") or "the study stopped part-way (the server restarted)"
    return job


def jobs(sid: str) -> list[dict]:
    root = _dir(sid) / "research"
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        try:
            out.append(load_job(sid, d.name))
        except NotFound:
            continue
    return sorted(out, key=lambda j: j.get("started") or 0)


def job_dir(sid: str, jid: str) -> Path:
    """A study's own folder (its capture record lives under `capture/`)."""
    return _job_dir(sid, jid)


# ── references ─────────────────────────────────────────────────────────────
#
# What the person pointed at, with what they allowed: `public` (its public
# pages, by the platform browser) and `session` (a recording of their own
# signed-in session, which only they can make).

_REF = re.compile(r"^[0-9a-f]{12}$")


def _refs_dir(sid: str) -> Path:
    return _dir(sid) / "references"


def new_reference(sid: str, name: str, url: str, *, added_by: str, allowed: list[str] | None = None) -> dict:
    rid = uuid.uuid4().hex[:12]
    ref = {"id": rid, "session_id": sid, "name": " ".join(str(name or "").split())[:120] or url[:120],
           "url": str(url or "")[:500], "added_by": str(added_by), "at": time.time(),
           "allowed": list(allowed or ["public"]), "studies": {}, "har": None}
    save_reference(ref)
    return ref


def save_reference(ref: dict) -> None:
    with _LOCK:
        folder = _refs_dir(ref["session_id"])
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{ref['id']}.json"
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(ref, default=str))
        tmp.replace(path)


def load_reference(sid: str, rid: str) -> dict:
    if not _REF.match(str(rid or "")):
        raise NotFound(rid)
    try:
        return json.loads((_refs_dir(sid) / f"{rid}.json").read_text())
    except (OSError, ValueError) as exc:
        raise NotFound(rid) from exc


def references(sid: str) -> list[dict]:
    root = _refs_dir(sid)
    if not root.is_dir():
        return []
    out = []
    for f in root.glob("*.json"):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda r: r.get("at") or 0)


# ── feature cards ──────────────────────────────────────────────────────────
#
# One file per reference: the card writer replaces a reference's cards whole.

def cards(sid: str, reference_id: str | None = None) -> list[dict]:
    root = _dir(sid) / "cards"
    if not root.is_dir():
        return []
    out: list[dict] = []
    for f in sorted(root.glob("*.json")):
        if reference_id and f.stem != reference_id:
            continue
        try:
            out.extend(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return out


def save_cards(sid: str, reference_id: str, rows: list[dict]) -> None:
    if not _REF.match(str(reference_id or "")):
        raise NotFound(reference_id)
    with _LOCK:
        folder = _dir(sid) / "cards"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{reference_id}.json"
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(rows, default=str))
        tmp.replace(path)


# ── drafts ─────────────────────────────────────────────────────────────────
#
# A draft is a folder of versions (`v1.json`, `v2.json` …); the latest is
# the draft as it stands, the others are its history.

_DRAFT = re.compile(r"^[0-9a-f]{12}$")


def _draft_dir(sid: str, did: str) -> Path:
    if not _DRAFT.match(str(did or "")):
        raise NotFound(did)
    return _dir(sid) / "drafts" / did


def new_draft_id() -> str:
    return uuid.uuid4().hex[:12]


def save_draft_version(sid: str, did: str, version: dict) -> dict:
    with _LOCK:
        folder = _draft_dir(sid, did)
        folder.mkdir(parents=True, exist_ok=True)
        n = int(version.get("version") or 0)
        path = folder / f"v{n}.json"
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(version, default=str))
        tmp.replace(path)
    return version


def draft_versions(sid: str, did: str) -> list[dict]:
    folder = _draft_dir(sid, did)
    if not folder.is_dir():
        raise NotFound(did)
    rows = []
    for f in folder.glob("v*.json"):
        try:
            rows.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    if not rows:
        raise NotFound(did)
    return sorted(rows, key=lambda v: int(v.get("version") or 0))


def drafts(sid: str) -> list[dict]:
    """Every draft as it stands (its latest version), with its version list."""
    root = _dir(sid) / "drafts"
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        try:
            versions = draft_versions(sid, d.name)
        except NotFound:
            continue
        latest = dict(versions[-1])
        latest["versions"] = [{"version": v.get("version"), "at": v.get("at"), "changed": v.get("changed")}
                              for v in versions]
        out.append(latest)
    return sorted(out, key=lambda v: v.get("created") or 0)


def add_job_file(job: dict, data: bytes, *, name: str, media_type: str, caption: str = "",
                 source: str = "") -> dict:
    """A screenshot the Researcher took, kept with its study."""
    if media_type not in KINDS:
        raise ValueError(f"{media_type} cannot be kept")
    fid = uuid.uuid4().hex[:16]
    path = _job_dir(job["session_id"], job["id"]) / "files" / f"{fid}.{KINDS[media_type]}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    meta = {"id": fid, "name": re.sub(r"[\r\n\t]", " ", name)[:160] or fid, "media_type": media_type,
            "origin": "research", "job": job["id"], "caption": caption[:300], "source": source[:500],
            "size": len(data), "at": time.time()}
    job.setdefault("files", []).append(meta)
    return meta


# ── drawings ───────────────────────────────────────────────────────────────
#
# Each screen on the board, drawn in the company's brand: one HTML document
# (and a picture of it when a browser was there) per screen, with an index of
# their own (`drawings/index.json`) written only by the drawer's threads —
# never `session.json`, which the conversation owns.

_DRAWING = re.compile(r"^[0-9a-f]{16}$")


def _drawings_dir(sid: str) -> Path:
    return _dir(sid) / "drawings"


def drawings(sid: str) -> list[dict]:
    """The session's drawings, one per screen, in board order of first drawing.
    One still `drawing` after `STALE_AFTER` is reported failed: the server
    restarted under it."""
    path = _drawings_dir(sid) / "index.json"
    try:
        rows = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    out = []
    for row in rows:
        if row.get("status") == "drawing" and time.time() - float(row.get("at") or 0) > STALE_AFTER:
            row = {**row, "status": "failed", "error": row.get("error") or "the drawing stopped part-way (the server restarted)"}
        out.append(row)
    return out


def _scope(row: dict) -> str:
    return str(row.get("scope") or "board")


def save_drawing(sid: str, entry: dict, *, if_current: bool = False) -> bool:
    """Put `entry` in the index in place of the one for the same screen in
    the same scope (the board's, or a draft's). With `if_current`, only
    while that one is this very drawing: a screen redrawn while its first
    drawing was still running has a newer entry, and the older thread's late
    result must not replace it."""
    same = lambda r: r.get("screen") == entry.get("screen") and _scope(r) == _scope(entry)  # noqa: E731
    with _LOCK:
        held = [r for r in drawings(sid) if same(r)]
        if if_current and held and held[0].get("id") != entry.get("id"):
            return False
        rows = [r for r in drawings(sid) if not same(r)]
        rows.append(entry)
        folder = _drawings_dir(sid)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "index.json"
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(rows, default=str))
        tmp.replace(path)
    return True


def new_drawing_id() -> str:
    return uuid.uuid4().hex[:16]


def drawing_path(sid: str, did: str, kind: str) -> Path:
    """Where a drawing's document (`html`) or picture (`png`) lives."""
    if not _DRAWING.match(str(did or "")) or kind not in ("html", "png"):
        raise NotFound(did)
    return _drawings_dir(sid) / f"{did}.{kind}"


def sniff(data: bytes) -> str:
    """What the bytes are, whatever the upload said."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    return ""


__all__ = ["ROOT", "KINDS", "NotFound", "create", "load", "save", "listed", "delete", "add_file",
           "file_meta", "file_path", "sniff", "new_job", "save_job", "load_job", "jobs", "add_job_file",
           "STALE_AFTER", "drawings", "save_drawing", "new_drawing_id", "drawing_path", "job_dir",
           "new_reference", "save_reference", "load_reference", "references", "cards", "save_cards",
           "new_draft_id", "save_draft_version", "draft_versions", "drafts"]

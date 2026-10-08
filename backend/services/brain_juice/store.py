"""A Brain Juice session on disk.

One directory per session under the platform's data directory
(`data/brain_juice/<id>/`): `session.json` holds who it belongs to, the
conversation as the person sees it, the conversation as the model was sent it
(`turns`, append-only so its thinking stays valid), the idea board and the
hand-off; `files/` holds the screenshots Smith took and what the person
dropped in. Sessions are files rather than rows: they are a working space,
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
ROOT = Path(os.environ.get("FORGE_BRAIN_JUICE_DIR") or _BACKEND / "data" / "brain_juice")

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
    from services.brain_juice.board import empty
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


def _write(session: dict) -> None:
    path = _dir(session["id"]) / "session.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(session, default=str))
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


def new_job(sid: str, reference: str, focus: str = "") -> dict:
    from services.brain_juice.dossier import empty
    jid = uuid.uuid4().hex[:12]
    now = time.time()
    job = {"id": jid, "session_id": sid, "reference": reference[:200], "focus": focus[:1000],
           "status": "running", "stage": "scouting", "started": now, "heartbeat": now, "finished": None,
           "steps": [], "surfaces": [], "dossier": empty(), "summary": "", "files": [], "error": None,
           "read": False, "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
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
           "STALE_AFTER"]

"""Pictures a person puts on a page.

An uploaded picture becomes a file under the app's ``public/uploads`` — the
place Next serves as-is — and the page refers to it by its root-relative
address (``/uploads/team-3f2a9c1e.png``). The same file travels with the app
when it is published, so the address holds in the editor, in the running
app and after a publish. The editor's canvas cannot reach the app's files
by address (it runs on the platform, not in the app), so the platform also
serves them, read-only, from the same directory.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from services.react_editor.service import EditorError, Project

#: What a page may show as a picture, by extension, with the type it is served as.
IMAGE_TYPES: dict[str, str] = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".svg": "image/svg+xml", ".avif": "image/avif", ".ico": "image/x-icon",
}
MAX_BYTES = 10 * 1024 * 1024
UPLOADS = "uploads"


def public_dir(project: Project) -> Path:
    return project.app_root / "public"


def save(project: Project, filename: str, data: bytes) -> dict[str, str]:
    """Store a picture; its address on the page and its path in the app."""
    ext = Path(filename or "").suffix.lower()
    if ext not in IMAGE_TYPES:
        raise EditorError(422, "not-a-picture", "Choose a picture file — PNG, JPEG, GIF, WebP, SVG or AVIF.")
    if not data:
        raise EditorError(422, "empty", "That file is empty.")
    if len(data) > MAX_BYTES:
        raise EditorError(422, "too-big", "That picture is over 10 MB — make it smaller first.")
    stem = re.sub(r"[^a-z0-9]+", "-", Path(filename).stem.lower()).strip("-")[:40] or "picture"
    digest = hashlib.sha1(data).hexdigest()[:8]
    name = f"{stem}-{digest}{ext}"
    target = public_dir(project) / UPLOADS / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)
    rel = f"{UPLOADS}/{name}"
    return {"url": f"/{rel}", "path": f"public/{rel}", "type": IMAGE_TYPES[ext], "bytes": str(len(data))}


def resolve(project: Project, rel: str) -> tuple[Path, str]:
    """The file a root-relative address names under the app's public dir, and its type."""
    clean = rel.lstrip("/")
    if not clean or ".." in clean.split("/") or clean.startswith("/"):
        raise EditorError(404, "no-such-file", "There is no such picture.")
    base = public_dir(project).resolve()
    path = (base / clean).resolve()
    if base not in path.parents or not path.is_file():
        raise EditorError(404, "no-such-file", "There is no such picture.")
    ctype = IMAGE_TYPES.get(path.suffix.lower())
    if not ctype:
        raise EditorError(404, "no-such-file", "There is no such picture.")
    return path, ctype


def listing(project: Project) -> list[dict[str, str]]:
    """The pictures the app already has, newest first."""
    base = public_dir(project)
    if not base.is_dir():
        return []
    out = []
    for p in base.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_TYPES and "node_modules" not in p.parts:
            out.append({"url": "/" + p.relative_to(base).as_posix(), "name": p.name, "mtime": str(int(p.stat().st_mtime))})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out[:200]

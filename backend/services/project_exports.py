"""Files an owner takes away — where they are written, and how they reach them.

Smith can now hand a business owner their own records (`records_out`), and a
file is not a sentence in a chat bubble. This is the transport half: where the
bytes land, and the one route that gives them back.

THE PROJECT'S OWN DIRECTORY, NOT A SHARED ROOT. Chat attachments live under
``output/_attachments/<project_id>/`` and have to sanitise that id because it
arrives as a path parameter. An export has somewhere better to be: the
project's ``output_dir``, which the caller does not supply — it is read off
the project row that ``get_project_with_auth`` already authorised. There is no
id in the path that could name another project's directory, because the
directory is not addressed by an id at all. That is what "no export path may
cross projects" looks like when it is structural rather than checked.

The export id still has to be a plain token, for the same reason an attachment
id does: it is the last segment of the download URL and ``..`` is a legal
thing for a browser to send.

WHAT IS NOT HERE. No S3, no signed url, no expiry sweeper. The file sits in
the project's directory on the same persistent volume as everything else the
pipeline writes, and the owner downloads it while their session is live. An
export is a snapshot of data the owner already owns; it is not a capability
handed to anyone else, and it must never become one — which is why the route
that serves it authenticates the platform user and matches them to the project
exactly as every other project route does.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")

#: Anything else is stripped out of the name the browser is told to save under.
#: The name is built from an application's own title, and a title is whatever
#: somebody typed — a quote or a newline in it would break out of the
#: `Content-Disposition` header the route writes it into.
_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(filename: str) -> str:
    """The download name, reduced to what a header can carry."""
    cleaned = _UNSAFE_IN_FILENAME.sub("-", str(filename or "")).strip("-.")
    return cleaned or "export"


class ExportError(ValueError):
    """Refusal the caller should see."""


def exports_root(output_dir: str | Path) -> Path:
    """``<output_dir>/.forge/exports`` — created on demand."""
    root = Path(output_dir) / ".forge" / "exports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_export(output_dir: str | Path, filename: str, data: bytes,
                media_type: str, *, describes: str = "") -> dict:
    """Write one downloadable file and return the record naming it.

    ``filename`` is what the owner's browser should save it as — it is written
    into the sidecar and echoed in the Content-Disposition, never used as the
    name on disk. The name on disk is the generated id, so nothing a Blueprint
    spells can decide where the bytes land.
    """
    root = exports_root(output_dir)
    export_id = uuid.uuid4().hex
    (root / export_id).write_bytes(data)
    rec = {
        "id": export_id,
        "filename": safe_filename(filename),
        "media_type": media_type,
        "bytes": len(data),
        "describes": describes,
    }
    (root / f"{export_id}.meta.json").write_text(json.dumps(rec), encoding="utf-8")
    logger.info("export saved: dir=%s id=%s bytes=%d", output_dir, export_id, len(data))
    return rec


def save_export_from(output_dir: str | Path, filename: str, source: str | Path,
                    media_type: str, *, describes: str = "") -> dict:
    """The same, for a file already written to disk — it is moved into place.

    A whole application's records do not want to exist twice in memory at
    once. The rows stream into a CSV on disk, the CSVs stream into a zip on
    disk, and this hands the finished file over without ever holding it.
    """
    root = exports_root(output_dir)
    src = Path(source)
    if not src.is_file():
        raise ExportError(f"nothing to publish at {src}")
    export_id = uuid.uuid4().hex
    size = src.stat().st_size
    shutil.move(str(src), str(root / export_id))
    rec = {
        "id": export_id,
        "filename": safe_filename(filename),
        "media_type": media_type,
        "bytes": size,
        "describes": describes,
    }
    (root / f"{export_id}.meta.json").write_text(json.dumps(rec), encoding="utf-8")
    logger.info("export saved: dir=%s id=%s bytes=%d", output_dir, export_id, size)
    return rec


def read_export(output_dir: str | Path, export_id: str) -> tuple[bytes, str, str] | None:
    """``(bytes, media_type, filename)``, or None.

    None rather than an exception on a junk or traversing id, so the route
    answers 404 and leaks nothing about what is or is not on disk.
    """
    if not _SAFE_ID.match(str(export_id or "")):
        return None
    root = Path(output_dir) / ".forge" / "exports"
    blob, meta = root / str(export_id), root / f"{export_id}.meta.json"
    if not blob.is_file() or not meta.is_file():
        return None
    try:
        rec = json.loads(meta.read_text(encoding="utf-8"))
        data = blob.read_bytes()
    except (OSError, ValueError):        # corrupt sidecar, unreadable blob
        return None
    return (data,
            str(rec.get("media_type") or "application/octet-stream"),
            str(rec.get("filename") or export_id))


def download_path(project_id: str, export_id: str) -> str:
    """The URL the owner follows. Relative on purpose.

    The UI rewrites ``/api/projects/*`` to the backend, so a relative path
    works wherever the platform is served from — and a chat bubble that
    hard-coded a host would hand a UAT owner a link to localhost.
    """
    return f"/api/projects/{project_id}/exports/{export_id}"


__all__ = ["ExportError", "download_path", "exports_root", "read_export",
           "safe_filename", "save_export", "save_export_from"]

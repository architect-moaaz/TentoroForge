"""Where a company's mark lives on the platform.

`services.brand_logo` already knows how to keep a logo beside an application:
content-addressed under `<output_dir>/brand/`, with the media type and the
intrinsic size measured on the way in. An organisation's mark is the same
problem one level up — it belongs to the company, and every application built
for that company copies it — so this reuses that module rather than growing a
second way to hold an image.

`output/_brand/<org_id>/` sits beside `output/_attachments`, resolved the same
way, so on UAT it lands on the persistent bind mount and a company's mark
survives a container recreate. Never inside a project: a project can be
deleted, and deleting one application must not take the company's logo with
it.

THE BYTES, NOT A LINK. The candidate came off someone else's CDN; a generated
application pointing at it is an application whose header goes blank the day
the company reorganises their assets. The file is fetched once, here, and
every build copies from here.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def brand_root() -> Path:
    """``output/_brand`` — beside ``_attachments`` and the ``_usage`` ledger."""
    root = Path(__file__).resolve().parent.parent.parent.parent / "output" / "_brand"
    root.mkdir(parents=True, exist_ok=True)
    return root


def org_dir(org_id: str) -> Path:
    """The directory holding one organisation's brand files.

    The id is checked rather than trusted: it reaches this from a URL path,
    and a `..` in it would write outside the store.
    """
    name = str(org_id)
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"not an organisation id: {org_id!r}")
    path = brand_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_logo(org_id: str, filename: str, content_type: str,
               data: bytes) -> dict:
    """Keep the mark for this organisation; return the `BrandLogo` body.

    The returned `file` is relative to `org_dir(org_id)`, which is what makes
    it portable: the same string means the same image whether the store moves
    or the platform is restored from a backup elsewhere.
    """
    from services import brand_logo

    return brand_logo.store(org_dir(org_id), filename, content_type, data)


def logo_file(org_id: str, logo: dict | None) -> Path | None:
    """The path of a stored mark, or None when it is missing or not ours.

    Validated against `brand_logo.STORED_NAME`, so a `file` edited in the
    database to `../../etc/passwd` reads as no logo rather than as a file.
    """
    from services import brand_logo

    name = str((logo or {}).get("file") or "")
    if not name or not brand_logo.STORED_NAME.match(name):
        return None
    path = org_dir(org_id) / name
    return path if path.is_file() else None

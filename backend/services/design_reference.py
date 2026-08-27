"""Which uploaded image is the app's DESIGN REFERENCE.

`brief_from_screenshot` turns a montage into a locked palette, type scale
and radius. The missing half was knowing which upload to feed it.

Designation is explicit, and deliberately so. Users attach screenshots far
more often to report a defect than to set a direction, so a rule like "use
every image on this project" would let a picture of a broken table pick the
brand colour — a plumbing mistake that would read as a model hallucination.
Only ids the user pointed at are ever loaded.

The designation lives beside the attachments themselves
(``output/_attachments/<project>/design-references.json``) rather than in a
column, so it survives the same way the bytes do and needs no migration.
Every read is best-effort: brief authoring must never block a build.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from services import chat_attachments
from services.chat_attachments import AttachmentError

logger = logging.getLogger(__name__)

_FILENAME = "design-references.json"


def _designation_path(root: str | Path, project_id: str) -> Path | None:
    """Path to the marker file, or None when the project id is unsafe."""
    try:
        return chat_attachments._project_dir(root, project_id) / _FILENAME
    except AttachmentError:
        # `..` in the id — refuse rather than resolve outside the root.
        return None


def set_design_references(
    root: str | Path, project_id: str, attachment_ids: list[str],
) -> list[str]:
    """Designate `attachment_ids` as THE design references for this project.

    Replaces any previous designation — a project has one visual direction,
    not an accumulating pile. Passing `[]` clears it. Returns what was
    stored.
    """
    path = _designation_path(root, project_id)
    if path is None:
        return []
    ids = [str(a) for a in (attachment_ids or []) if str(a).strip()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ids": ids}, indent=2), encoding="utf-8")
    logger.info("[design-ref] project=%s designated %d reference(s)",
                project_id, len(ids))
    return ids


def read_design_references(root: str | Path, project_id: str) -> list[str]:
    """The designated attachment ids, or `[]`. Never raises."""
    path = _designation_path(root, project_id)
    if path is None or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — corrupt marker → no reference
        logger.info("[design-ref] project=%s unreadable designation; ignoring",
                    project_id)
        return []
    ids = payload.get("ids") if isinstance(payload, dict) else None
    if not isinstance(ids, list):
        return []
    return [str(a) for a in ids if str(a).strip()]


def load_design_reference_blocks(
    root: str | Path, project_id: str,
) -> list[dict]:
    """Anthropic content blocks for the designated references.

    Returns `[]` when nothing is designated, when the attachment is gone, or
    when the ids resolve to no image — `extract_screenshot_tokens` treats an
    empty block list as "no reference", which falls back to the normal brief
    path rather than failing the build.
    """
    ids = read_design_references(root, project_id)
    if not ids:
        return []
    try:
        return chat_attachments.load_blocks(root, project_id, ids)
    except Exception as e:  # noqa: BLE001 — best-effort by contract
        logger.info("[design-ref] project=%s block load failed: %s", project_id, e)
        return []

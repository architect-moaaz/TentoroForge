"""Smith `edit_brief` tool — apply partial patches to the persisted brief.

Phase 3: user says "make it more compact" or "change the accent to green
#4A7A3E" and Smith invokes this to update the brief on disk.

Pure module — file I/O only. The design-brief LLM is NOT called here;
Smith already knows what the user wants and encodes it directly as a
patch. The base antipattern floor is preserved on every edit.

Cascades (token recompile, per-page revision) are the caller's job —
see :mod:`services.brief_loop_cascade`.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from schemas.design_brief import DesignBrief
from services.design_brief_antipatterns import BASE_ANTI_PATTERNS

logger = logging.getLogger(__name__)


class BriefEditError(RuntimeError):
    """Raised when a patch fails to apply or the result is invalid."""


def _deep_merge(dst: dict, src: dict) -> dict:
    """Merge ``src`` into a copy of ``dst``, recursing into nested dicts.

    Lists are REPLACED wholesale (last-write-wins). This matches user
    intent when they say "change the signature moves to X" — they mean
    the new set, not "append to the old set".
    """
    out = dict(dst)
    for k, v in src.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# Spec A Slice 6c: sections whose sub-fields can be locked. Layout /
# palette / typography carry per-field lock sets; a patch that targets
# any locked sub-field is rejected wholesale. The Smith tool + frontend
# surface the resulting error to the user.
_LOCKABLE_SECTIONS: tuple[str, ...] = ("palette", "typography", "layout")


def _find_locked_violations(current: DesignBrief, patch: dict[str, Any]) -> list[str]:
    """Return dotted-paths of locked fields the patch would mutate.

    Only inspects the three lockable sections. A patch that only touches
    other sections (signature_moves, identity, anti_patterns) is allowed.
    """
    violations: list[str] = []
    for section in _LOCKABLE_SECTIONS:
        section_patch = patch.get(section)
        if not isinstance(section_patch, dict):
            continue
        section_obj = getattr(current, section, None)
        locked = set(getattr(section_obj, "locked_fields", set()) or set())
        if not locked:
            continue
        for field in section_patch:
            if field in locked:
                violations.append(f"{section}.{field}")
    return violations


def apply_patch(current: DesignBrief, patch: dict[str, Any]) -> DesignBrief:
    """Return a new brief with ``patch`` applied over ``current``.

    Patch is a nested dict matching the brief schema; only the paths you
    supply are overwritten. Base antipatterns are always re-merged so a
    user or Smith patch can't strip them.

    Slice 6c: refuses to mutate any field listed in the corresponding
    section's ``locked_fields``. Figma-sourced briefs use this to keep
    palette/typography/radius byte-exact through editor round-trips.

    Raises:
        BriefEditError: on empty patch, locked-field mutation, or
            schema-invalid result. The message names the offending
            field(s) so the Smith tool / frontend can display it.
    """
    if not patch:
        raise BriefEditError("empty patch")

    violations = _find_locked_violations(current, patch)
    if violations:
        raise BriefEditError(
            f"cannot edit locked field(s): {', '.join(violations)} — "
            "these fields are locked from the Figma source. "
            "Unlock in project settings to override."
        )

    current_dict = current.model_dump()
    merged = _deep_merge(current_dict, patch)

    # Guarantee base blocklist survives every edit.
    ap = set(merged.get("anti_patterns") or [])
    ap.update(BASE_ANTI_PATTERNS)
    merged["anti_patterns"] = sorted(ap)

    try:
        return DesignBrief.model_validate(merged)
    except ValidationError as exc:
        raise BriefEditError(f"invalid brief after patch: {exc!s}") from exc


def read_brief(output_dir: str | Path) -> DesignBrief | None:
    """Load the brief from ``contracts/brief.json`` if present."""
    path = Path(output_dir) / "contracts" / "brief.json"
    if not path.exists():
        return None
    try:
        return DesignBrief.model_validate_json(path.read_text())
    except Exception as exc:  # noqa: BLE001
        logger.warning("[brief] read failed: %s", exc)
        return None


def write_brief(output_dir: str | Path, brief: DesignBrief) -> Path:
    """Persist ``brief`` to ``contracts/brief.json`` (atomic write)."""
    path = Path(output_dir) / "contracts" / "brief.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(brief.model_dump_json(indent=2))
    tmp.replace(path)
    return path


def edit_brief_on_disk(
    output_dir: str | Path, patch: dict[str, Any],
) -> tuple[DesignBrief, DesignBrief]:
    """Read → patch → write. Convenience wrapper the Smith tool calls.

    Returns ``(before, after)`` — callers may diff for cascade decisions.

    Raises:
        BriefEditError: no brief on disk, or patch is invalid.
    """
    before = read_brief(output_dir)
    if before is None:
        raise BriefEditError(
            f"no brief.json in {output_dir} — run Discovery with "
            "FORGE_BRIEF_AUTHOR=1 first"
        )
    after = apply_patch(before, patch)
    write_brief(output_dir, after)
    logger.info("[brief] edited on disk: %s → %s", output_dir, path_summary(after))
    return before, after


def path_summary(brief: DesignBrief) -> str:
    """One-line summary suitable for logs / Smith trace."""
    return brief.summary_line()


__all__ = [
    "BriefEditError",
    "apply_patch",
    "read_brief",
    "write_brief",
    "edit_brief_on_disk",
    "path_summary",
]

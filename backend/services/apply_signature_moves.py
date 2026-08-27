"""Spec C2 — Apply signature moves to page schemas.

Walks every ``src/schemas/*.json`` under the generated app, and for
each brief-declared signature move: finds nodes whose type matches the
move's applicability predicate and rewrites them via the renderer.

Idempotent — the renderers are additive (set a prop / style key). Two
runs on the same tree produce the same output.

Flag-gated on ``FORGE_POLISH_SIGNATURE_MOVES`` (default off; ships
behind the same rollout order as the other C-slice polish passes).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from services import signature_moves as _sm

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    return os.getenv("FORGE_POLISH_SIGNATURE_MOVES", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _iter_pages(output_dir: Path):
    sdir = output_dir / "src" / "schemas"
    if not sdir.is_dir():
        return
    for p in sorted(sdir.glob("**/*.json")):
        if p.name in ("shell.json", "nav-flow.json"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        yield p, data


def _walk_nodes(node: Any):
    """DFS every dict-shaped node in a page-schema tree."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_nodes(item)


def _load_brief(output_dir: Path) -> dict | None:
    """Read the persisted brief. Absent → None."""
    for rel in (
        "src/contracts/brief.json",
        "src/contracts/design-brief.json",
    ):
        p = output_dir / rel
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
    return None


def _brief_moves(brief: dict | None) -> list[dict]:
    """Return the list of ``{kind, detail}`` entries the brief declares."""
    if not isinstance(brief, dict):
        return []
    raw = brief.get("signature_moves")
    if not isinstance(raw, list):
        return []
    return [m for m in raw if isinstance(m, dict) and isinstance(m.get("kind"), str)]


def apply_signature_moves(
    output_dir: str,
    *,
    brief: dict | None = None,
) -> dict:
    """Rewrite every page schema in place with brief-declared moves.

    Args:
        output_dir: generated app root.
        brief: optional brief dict override (tests). Otherwise read from
            ``src/contracts/brief.json`` or ``design-brief.json``.

    Returns ``{moves_applied, nodes_touched, files, unknown_kinds}``.
    Unknown move kinds are logged and skipped — never raise.
    """
    root = Path(output_dir)
    if not root.is_dir():
        return {"moves_applied": 0, "nodes_touched": 0, "files": 0, "unknown_kinds": []}

    active_brief = brief if brief is not None else _load_brief(root)
    moves = _brief_moves(active_brief)
    if not moves:
        return {"moves_applied": 0, "nodes_touched": 0, "files": 0, "unknown_kinds": []}

    # Resolve moves → registry entries; collect unknowns for the return value.
    known: list[tuple[dict, _sm.MoveEntry]] = []
    unknown_kinds: list[str] = []
    for m in moves:
        entry = _sm.get(m["kind"])
        if entry is None:
            unknown_kinds.append(m["kind"])
            logger.warning("[signature-moves] unknown kind '%s' — skipping", m["kind"])
            continue
        known.append((m, entry))

    ctx: dict = {"brief": active_brief}
    moves_applied = 0
    nodes_touched = 0
    files_changed = 0

    for path, schema in _iter_pages(root):
        page_touched = False
        for node in _walk_nodes(schema.get("root")):
            for _move, entry in known:
                try:
                    if entry.applies_to(node, ctx):
                        entry.render(node, ctx)
                        moves_applied += 1
                        nodes_touched += 1
                        page_touched = True
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[signature-moves] '%s' failed on %s: %s",
                        entry.kind, path.name, exc,
                    )
        if page_touched:
            try:
                path.write_text(
                    json.dumps(schema, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                files_changed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("[signature-moves] write failed %s: %s", path, exc)

    return {
        "moves_applied": moves_applied,
        "nodes_touched": nodes_touched,
        "files": files_changed,
        "unknown_kinds": sorted(set(unknown_kinds)),
    }


__all__ = ["apply_signature_moves", "is_enabled"]

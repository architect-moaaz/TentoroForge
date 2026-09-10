"""Sprint 9 — Page design memory (cross-page continuity).

Right now every page is authored + critiqued in isolation. Design
becomes coherent only when page N knows what pages 1..N-1 committed to:
which signature moves they applied, how many brand echoes they carried,
which hero patterns they used.

This module maintains a per-project ledger at
``<output>/reports/page-critic/_memory.json``. After each page is
critiqued we call :func:`record_page` to append that page's fingerprint.
Before the next page is authored we call :func:`memory_block_for_prompt`
to render prior fingerprints as a short DCP block — the LLM reads it and
either extends the same visual DNA (usually right) or deliberately picks
a fresh direction (also fine, but a choice, not an accident).

Best-effort at every layer — memory failures never break generation.

Env flag: ``FORGE_PAGE_DESIGN_MEMORY`` (default off). When off,
``memory_block_for_prompt`` returns ``""`` and ``record_page`` is a
no-op — the ledger file isn't even created.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_MEMORY_FLAG = "FORGE_PAGE_DESIGN_MEMORY"
_LEDGER_NAME = "_memory.json"
_MAX_PAGES_IN_PROMPT = 6  # cap prior-page context to keep prompt bounded


def design_memory_enabled() -> bool:
    """Cross-page memory is off by default — opt in when we've proven it
    doesn't degrade design in the observability window."""
    return os.environ.get(_MEMORY_FLAG, "0") == "1"


def _ledger_path(output_dir: str) -> Path:
    return Path(output_dir) / "reports" / "page-critic" / _LEDGER_NAME


def load_memory(output_dir: str) -> dict:
    """Return the current ledger, or an empty scaffold if none exists /
    the file is malformed. Never raises."""
    empty = {"pages": []}
    try:
        p = _ledger_path(output_dir)
        if not p.exists():
            return empty
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
            return empty
        return data
    except Exception:  # noqa: BLE001
        logger.exception("[page-memory] load_memory failed for %s", output_dir)
        return empty


def record_page(
    output_dir: str,
    *,
    slug: str,
    page_type: str,
    critique: dict,
) -> None:
    """Append this page's fingerprint to the ledger.

    We record only what a peer page would need to make coherent choices:
    the moves detected, the brand-echo count, and the critic verdict.
    We deliberately do NOT store the schema (bulky, private to the page)
    or the LLM prose (not machine-actionable across pages).
    """
    if not design_memory_enabled():
        return
    try:
        data = load_memory(output_dir)
        detectors = critique.get("_detectors") or {}
        sig = detectors.get("signature_moves") or {}
        brand = detectors.get("brand_echo") or {}
        entry = {
            "slug":            slug,
            "page_type":       page_type or "",
            "moves_applied":   list(sig.get("detected") or []),
            "brand_echoes":    int(brand.get("total_echoes") or 0),
            "score":           critique.get("score"),
            "passes":          bool(critique.get("passes", False)),
        }
        # De-dupe by slug: re-authoring a page REPLACES its prior entry.
        pages = [p for p in data.get("pages", []) if p.get("slug") != slug]
        pages.append(entry)
        data["pages"] = pages
        p = _ledger_path(output_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.exception(
            "[page-memory] record_page failed for %s / %s", output_dir, slug,
        )


def memory_block_for_prompt(output_dir: str) -> str:
    """Render prior-page fingerprints as a DCP block. Returns ``""`` when
    the memory flag is off OR no prior pages exist yet (nothing to say)."""
    if not design_memory_enabled():
        return ""
    try:
        data = load_memory(output_dir)
        pages = data.get("pages") or []
        if not pages:
            return ""
        # Show the LAST N pages — recency matters more than depth of history,
        # and the LLM does not need every past page to grasp the running rhythm.
        recent = pages[-_MAX_PAGES_IN_PROMPT:]

        lines = ["<prior-pages-in-this-app>"]
        lines.append(
            "These pages already exist in this app. Extend their visual"
            " DNA when it serves the current page — or deliberately choose a"
            " fresh direction that still respects the brand. Do not"
            " reinvent the palette or the move set at random."
        )
        lines.append("")
        for p in recent:
            slug = p.get("slug", "?")
            ptype = p.get("page_type", "")
            moves = p.get("moves_applied") or []
            echoes = p.get("brand_echoes", 0)
            moves_txt = ", ".join(moves) if moves else "(none detected)"
            head = f"· {slug}"
            if ptype:
                head += f" [{ptype}]"
            lines.append(head)
            lines.append(f"    signature moves applied: {moves_txt}")
            lines.append(f"    brand echoes on the page: {echoes}")
        lines.append("</prior-pages-in-this-app>")
        return "\n".join(lines)
    except Exception:  # noqa: BLE001
        logger.exception("[page-memory] memory_block_for_prompt failed")
        return ""


__all__ = [
    "design_memory_enabled",
    "load_memory",
    "record_page",
    "memory_block_for_prompt",
]

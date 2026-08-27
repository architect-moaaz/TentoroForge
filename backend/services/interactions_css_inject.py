"""Spec C Slice 4 + Slice 8 — inject library interaction/dark stylesheets.

Post-generation pass that appends the library's ``interactions.css``
(hover/press/focus transitions) and ``theme-dark.css`` (dark-mode token
overrides) into the generated app's global stylesheet. Runs behind
``FORGE_POLISH_INTERACTIONS`` and ``FORGE_POLISH_DARK_MODE`` flags —
either flag independent, both default off.

Why post-gen instead of vendoring or CSS import: the current library
vendor pass copies compiled JS but not CSS assets. Appending into
``src/app/globals.css`` reuses the app's existing stylesheet load path
without touching the template glue or the vendor pipeline.

Idempotent: sentinel comments (``/* forge:interactions:start */``)
mark previously-injected blocks; a second run replaces the block
in-place. Never duplicates.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Sentinels that let the pass find + replace its own previous injection.
_INTERACTIONS_START = "/* forge:interactions:start */"
_INTERACTIONS_END = "/* forge:interactions:end */"
_DARK_START = "/* forge:theme-dark:start */"
_DARK_END = "/* forge:theme-dark:end */"
_A11Y_START = "/* forge:a11y-focus-ring:start */"
_A11Y_END = "/* forge:a11y-focus-ring:end */"
_HIGH_CONTRAST_START = "/* forge:high-contrast:start */"
_HIGH_CONTRAST_END = "/* forge:high-contrast:end */"

# Library CSS sources, resolved relative to this file so the pass finds
# them regardless of the process cwd. Falls back to a compiled dist copy
# if the workspace layout ever changes.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LIB_STYLE = _REPO_ROOT / "packages" / "library" / "src" / "style"
_INTERACTIONS_PATH = _LIB_STYLE / "interactions.css"
_DARK_PATH = _LIB_STYLE / "theme-dark.css"
_FOCUS_RING_PATH = _LIB_STYLE / "focus-ring.css"


def _polish_interactions_on() -> bool:
    return os.getenv("FORGE_POLISH_INTERACTIONS", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _polish_dark_on() -> bool:
    return os.getenv("FORGE_POLISH_DARK_MODE", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _a11y_on() -> bool:
    # Default OFF, matching the flag convention of its siblings. Turn
    # on for the accessibility rollout; long-term this becomes the
    # default once every downstream test suite is on the new baseline.
    return os.getenv("FORGE_POLISH_A11Y", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _high_contrast_on() -> bool:
    return os.getenv("FORGE_POLISH_HIGH_CONTRAST", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _read_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _replace_or_append(
    doc: str, start: str, end: str, body: str,
) -> tuple[str, bool]:
    """Insert or replace a sentinel-bracketed block. Returns (new_doc,
    changed). Reaches a fixed point after one replacement — repeat
    calls with the same body produce byte-identical output.
    """
    body_block = f"{start}\n{body.rstrip()}\n{end}\n"
    if start in doc and end in doc:
        pre, rest = doc.split(start, 1)
        _, post = rest.split(end, 1)
        # Normalize surrounding whitespace: exactly one leading blank
        # line before the block, and preserve post as-is with its
        # existing newline discipline (also normalize trailing).
        pre = pre.rstrip() + "\n\n" if pre.strip() else ""
        post = post.lstrip("\n")
        new = pre + body_block + post
        return (new, new != doc)
    # First-time append. Preserve a trailing newline on the original.
    if doc and not doc.endswith("\n"):
        doc = doc + "\n"
    if doc:
        doc = doc + "\n"  # blank line between existing rules and injected block
    return (doc + body_block, True)


def inject_polish_stylesheets(output_dir: str) -> dict:
    """Append/replace the interaction + dark-mode stylesheets in the
    generated app's globals.css. Returns a small stats dict; never raises.

    No-op when both flags are off. No-op when globals.css doesn't exist
    (some templates emit their tokens elsewhere; the pass silently skips
    rather than creating a phantom file).
    """
    interactions_on = _polish_interactions_on()
    dark_on = _polish_dark_on()
    a11y_on = _a11y_on()
    high_contrast_on = _high_contrast_on()
    if not (interactions_on or dark_on or a11y_on or high_contrast_on):
        # Sentinel kept as ``both_flags_off`` for downstream compatibility
        # even though the pass now covers four flags — callers key on
        # this string.
        return {"ok": True, "skipped": "both_flags_off"}

    root = Path(output_dir)
    globals_path = root / "src" / "app" / "globals.css"
    if not globals_path.is_file():
        return {"ok": True, "skipped": "no_globals_css"}

    try:
        doc = globals_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("interactions_css_inject: read failed: %s", exc)
        return {"ok": False, "reason": f"read: {exc}"}

    changed = False
    injected: list[str] = []

    if interactions_on:
        body = _read_or_empty(_INTERACTIONS_PATH)
        if body:
            doc, _c = _replace_or_append(
                doc, _INTERACTIONS_START, _INTERACTIONS_END, body,
            )
            if _c:
                changed = True
                injected.append("interactions")
        else:
            logger.warning("interactions_css_inject: source missing %s",
                           _INTERACTIONS_PATH)

    if dark_on:
        body = _read_or_empty(_DARK_PATH)
        if body:
            doc, _c = _replace_or_append(
                doc, _DARK_START, _DARK_END, body,
            )
            if _c:
                changed = True
                injected.append("theme-dark")
        else:
            logger.warning("interactions_css_inject: source missing %s",
                           _DARK_PATH)

    if a11y_on:
        body = _read_or_empty(_FOCUS_RING_PATH)
        if body:
            doc, _c = _replace_or_append(
                doc, _A11Y_START, _A11Y_END, body,
            )
            if _c:
                changed = True
                injected.append("focus-ring")
        else:
            logger.warning("interactions_css_inject: source missing %s",
                           _FOCUS_RING_PATH)

    if high_contrast_on:
        # Lazy import to keep the accessibility_pass module tree-shakable.
        try:
            from services.high_contrast_pass import build_high_contrast_css
            hc_body = build_high_contrast_css()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "interactions_css_inject: high_contrast_pass failed: %s", exc,
            )
            hc_body = ""
        if hc_body:
            doc, _c = _replace_or_append(
                doc, _HIGH_CONTRAST_START, _HIGH_CONTRAST_END, hc_body,
            )
            if _c:
                changed = True
                injected.append("high-contrast")

    if not changed:
        return {"ok": True, "injected": injected, "no_op": True}

    try:
        globals_path.write_text(doc, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("interactions_css_inject: write failed: %s", exc)
        return {"ok": False, "reason": f"write: {exc}"}

    return {"ok": True, "injected": injected, "bytes_written": len(doc)}

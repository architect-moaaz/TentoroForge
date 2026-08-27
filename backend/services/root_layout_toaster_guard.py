"""Root-layout Toaster guard (IRF-M3-T5).

Post-generation pass that reads ``plan.app_shape`` and injects
``<Toaster />`` into the emitted ``src/app/layout.tsx`` when the
derived function ``needs_root_toaster()`` says so.

Fixes the AC10-copy class of bug permanently: shell-less pages
(``layout.shell="none"``), modal auth (``auth.surface="modal"``),
and fire-and-forget workflows all need Toaster mounted at ROOT (not
inside the dashboard shell), otherwise ``toast.error(...)`` calls on
hero pages / login modals / dispatch-form-pages silently vanish.

Runs as a deterministic post-gen pass — string-based injection into
an emitted TSX file. Idempotent (won't double-inject when
``Toaster`` already present). Tolerant of missing files or missing
plan fields (no-op).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from services.shape_profile_derived import needs_root_toaster


LAYOUT_TSX_REL = Path("src") / "app" / "layout.tsx"


_SONNER_IMPORT = 'import { Toaster } from "sonner";'
_TOASTER_JSX = '        <Toaster position="top-right" richColors />'


def apply_toaster_guard(output_dir: str, plan: dict[str, Any] | None) -> dict[str, Any]:
    """Apply the Toaster injection if the plan's effective shape
    calls for it. Returns a report dict describing what happened.

    Never raises — a missing layout.tsx or a plan without app_shape
    yields ``{"applied": false, "reason": "..."}``.
    """
    if not isinstance(plan, dict):
        return {"applied": False, "reason": "plan missing / not a dict"}
    shape = plan.get("app_shape")
    if not isinstance(shape, dict):
        return {"applied": False, "reason": "plan.app_shape missing"}
    if not needs_root_toaster(shape):
        return {"applied": False, "reason": "shape does not require root Toaster"}

    layout_path = Path(output_dir) / LAYOUT_TSX_REL
    if not layout_path.exists():
        return {"applied": False, "reason": f"{LAYOUT_TSX_REL} not present"}

    try:
        original = layout_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"applied": False, "reason": f"read failed: {exc}"}

    updated = inject_toaster(original)
    if updated == original:
        return {"applied": False, "reason": "already present or no insertion site"}

    try:
        layout_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return {"applied": False, "reason": f"write failed: {exc}"}

    return {
        "applied": True,
        "reason": "Toaster injected — shape requires root-mounted toaster",
        "path": str(LAYOUT_TSX_REL),
    }


def inject_toaster(source: str) -> str:
    """Pure string transform. Two edits:

    1. Add ``import { Toaster } from "sonner";`` if the sonner import
       isn't already there.
    2. Insert ``<Toaster position="top-right" richColors />`` inside
       the ``<body>...</body>`` tags, right before ``</body>``.

    Idempotent: returns the input unchanged when both edits would be
    no-ops (Toaster already imported AND already in JSX)."""
    changed = source

    # Import — insert after the last existing import line
    if "from \"sonner\"" not in changed and "from 'sonner'" not in changed:
        changed = _insert_import(changed, _SONNER_IMPORT)

    # JSX — insert before </body>
    if "<Toaster" not in changed:
        changed = _insert_before_closing_body(changed, _TOASTER_JSX)

    return changed


def _insert_import(source: str, import_line: str) -> str:
    """Insert an import line after the last existing import in the
    file. Falls back to top-of-file when no imports exist."""
    lines = source.splitlines(keepends=True)
    last_import_idx = -1
    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("import "):
            last_import_idx = idx
    if last_import_idx < 0:
        # No imports — put it at the top, before the first non-blank line
        return import_line + "\n" + source
    lines.insert(last_import_idx + 1, import_line + "\n")
    return "".join(lines)


def _insert_before_closing_body(source: str, jsx_line: str) -> str:
    """Insert ``jsx_line`` immediately before the last ``</body>`` in
    the source. No-op if ``</body>`` not found (unusual for a layout
    file — respected as safety)."""
    marker = "</body>"
    idx = source.rfind(marker)
    if idx < 0:
        return source
    # Preserve the indentation of </body> where we insert
    line_start = source.rfind("\n", 0, idx) + 1
    body_indent = source[line_start:idx]
    if not body_indent.isspace():
        body_indent = "      "  # sensible default
    insert = f"{body_indent}{jsx_line.strip()}\n"
    return source[:idx] + insert + body_indent + marker.lstrip() + source[idx + len(marker):]

"""IR Export Service — eject from IR or export IR for backup.

Eject: strips all IR boundary comments, deletes .ir/ directory.
       After ejection, the project is code-only.

Export: downloads the IR JSON for backup or migration.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def eject_from_ir(output_dir: str) -> dict[str, Any]:
    """Eject a project from IR management.

    1. Strips @ir-node/@ir-end boundary comments from all TSX files
    2. Removes the .ir/ directory
    3. Returns summary of changes

    This is a one-way operation — the project becomes code-only.
    """
    ir_dir = Path(output_dir) / ".ir"
    src_dir = Path(output_dir) / "src"

    result = {
        "ejected": False,
        "files_stripped": 0,
        "ir_deleted": False,
    }

    if not ir_dir.exists():
        return result

    # Strip boundary comments from all TSX files
    if src_dir.exists():
        for tsx_file in src_dir.rglob("*.tsx"):
            content = tsx_file.read_text(encoding="utf-8")
            if "@ir-node:" in content or "@ir-end:" in content:
                stripped = _strip_boundaries(content)
                tsx_file.write_text(stripped, encoding="utf-8")
                result["files_stripped"] += 1
                logger.info("Stripped IR boundaries: %s", tsx_file.relative_to(output_dir))

    # Remove .ir directory
    shutil.rmtree(ir_dir, ignore_errors=True)
    result["ir_deleted"] = True
    result["ejected"] = True

    logger.info(
        "Ejected from IR: %d files stripped, .ir/ deleted",
        result["files_stripped"],
    )
    return result


def export_ir(output_dir: str) -> dict[str, Any] | None:
    """Export the IR JSON for backup or migration.

    Returns the full IR document, or None if no IR exists.
    """
    manifest_path = Path(output_dir) / ".ir" / "manifest.json"
    if not manifest_path.exists():
        return None

    ir = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Add export metadata
    ir["_export"] = {
        "version": "1.0",
        "source_dir": str(output_dir),
    }

    return ir


def import_ir(output_dir: str, ir: dict[str, Any]) -> bool:
    """Import an IR document into a project.

    Saves the IR and triggers compilation.
    Returns True if successful.
    """
    from services.ir_compiler import save_ir

    # Remove export metadata if present
    ir.pop("_export", None)

    # Validate basic structure
    if "$schema" not in ir or "pages" not in ir:
        return False

    import asyncio
    asyncio.get_event_loop().run_until_complete(save_ir(output_dir, ir))
    return True


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _strip_boundaries(content: str) -> str:
    """Remove all IR boundary comments from file content."""
    import re
    # Remove lines that are just boundary comments
    lines = content.split("\n")
    stripped = []
    for line in lines:
        trimmed = line.strip()
        if re.match(r'\{/\*\s*@ir-node:.*\*/\}', trimmed):
            continue
        if re.match(r'\{/\*\s*@ir-end:.*\*/\}', trimmed):
            continue
        stripped.append(line)

    # Clean up double blank lines left behind
    result = "\n".join(stripped)
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")

    return result

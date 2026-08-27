"""AHTML Compiler Service — orchestrates annotated HTML → TSX conversion.

1. Calls the TypeScript parser (packages/ahtml) to extract semantic model
2. Calls the LLM agent to generate TSX from the parsed model + raw HTML
3. Validates the output
4. Writes TSX files to the output directory
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from agents.ahtml_conversion_agent import (
    run_ahtml_to_tsx_agent,
    extract_tsx_from_response,
)

logger = logging.getLogger(__name__)

# Path to the ahtml package
_PACKAGES_DIR = Path(__file__).resolve().parent.parent.parent / "packages"
_AHTML_DIR = _PACKAGES_DIR / "ahtml"


class AHTMLCompileError(Exception):
    """Raised when AHTML compilation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"AHTML compilation failed with {len(errors)} error(s)")


# ---------------------------------------------------------------------------
# Parse annotated HTML (TypeScript side)
# ---------------------------------------------------------------------------

async def parse_ahtml(html: str) -> dict[str, Any]:
    """Parse annotated HTML and extract the semantic model.

    Calls the TypeScript parser via Node.js subprocess.

    Returns:
        Parsed page context with metadata, data sources, state, summary.
    """
    script = f"""
import {{ buildTsxContext }} from '{_AHTML_DIR}/dist/html-to-tsx.js';
const html = {json.dumps(html)};
const ctx = buildTsxContext(html);
process.stdout.write(JSON.stringify(ctx));
"""
    result = await _run_node(script, timeout=15.0)
    return json.loads(result)


# ---------------------------------------------------------------------------
# Convert AHTML → TSX (full pipeline)
# ---------------------------------------------------------------------------

async def compile_ahtml_to_tsx(
    html: str,
    page_id: str | None = None,
) -> dict[str, Any]:
    """Convert annotated HTML to TSX.

    Args:
        html: The annotated HTML content (single page or full document).
        page_id: Optional specific page to compile.

    Returns:
        Dict with:
        - pages: list of { pageId, route, tsx } dicts
        - errors: list of error strings
        - warnings: list of warning strings
    """
    # Step 1: Parse the HTML to extract semantic model
    try:
        ctx = await parse_ahtml(html)
    except Exception as e:
        logger.error("Failed to parse AHTML: %s", e)
        return {"pages": [], "errors": [f"Parse error: {e}"], "warnings": []}

    pages_ctx = ctx.get("pages", [])
    if page_id:
        pages_ctx = [p for p in pages_ctx if p.get("pageId") == page_id]

    if not pages_ctx:
        return {"pages": [], "errors": ["No pages found in AHTML"], "warnings": []}

    # Step 2: Convert each page via LLM agent
    results = []
    errors = []
    warnings = []

    for page_ctx in pages_ctx:
        try:
            tsx = await _convert_page(page_ctx)
            if tsx:
                results.append({
                    "pageId": page_ctx["pageId"],
                    "route": page_ctx["route"],
                    "tsx": tsx,
                })
            else:
                errors.append(f"Failed to generate TSX for page {page_ctx['pageId']}")
        except Exception as e:
            logger.error("TSX conversion failed for page %s: %s", page_ctx.get("pageId"), e)
            errors.append(f"Page {page_ctx.get('pageId')}: {e}")

    return {"pages": results, "errors": errors, "warnings": warnings}


async def _convert_page(page_ctx: dict) -> str | None:
    """Convert a single page context to TSX via LLM."""
    messages = []
    async for msg in run_ahtml_to_tsx_agent(
        page_html=page_ctx.get("html", ""),
        page_metadata=page_ctx,
        tsx_hints=page_ctx.get("tsxHints"),
    ):
        messages.append(msg)

    return extract_tsx_from_response(messages)


# ---------------------------------------------------------------------------
# Write compiled TSX files
# ---------------------------------------------------------------------------

async def write_ahtml_tsx_files(
    output_dir: str,
    pages: list[dict[str, str]],
    src_prefix: str = "src",
) -> list[str]:
    """Write compiled TSX to the output directory.

    Args:
        output_dir: Project output directory.
        pages: List of { pageId, route, tsx } dicts.
        src_prefix: Source directory prefix (default: "src").

    Returns:
        List of written file paths (relative to output_dir).
    """
    written = []

    for page in pages:
        route = page.get("route", "/")
        tsx = page.get("tsx", "")

        if not tsx:
            continue

        # Convert route to file path
        # /dashboard → src/app/dashboard/page.tsx
        # / → src/app/page.tsx
        route_parts = route.strip("/").split("/") if route != "/" else []
        file_path = Path(output_dir) / src_prefix / "app" / "/".join(route_parts) / "page.tsx"

        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the file
        file_path.write_text(tsx, encoding="utf-8")
        rel_path = str(file_path.relative_to(output_dir))
        written.append(rel_path)
        logger.info("Wrote TSX: %s", rel_path)

    return written


# ---------------------------------------------------------------------------
# IR → AHTML conversion (calls TypeScript package)
# ---------------------------------------------------------------------------

async def ir_to_ahtml(ir: dict[str, Any]) -> dict[str, Any]:
    """Convert AppIR JSON to annotated HTML pages.

    Calls the TypeScript irToAnnotatedHtml function via Node.js subprocess.

    Returns:
        AnnotatedApp dict with pages containing HTML strings.
    """
    script = f"""
import {{ irToAnnotatedHtml }} from '{_AHTML_DIR}/dist/ir-to-html.js';
const ir = {json.dumps(ir)};
const result = irToAnnotatedHtml(ir);
process.stdout.write(JSON.stringify(result));
"""
    result = await _run_node(script, timeout=30.0)
    return json.loads(result)


# ---------------------------------------------------------------------------
# Validate AHTML (calls TypeScript package)
# ---------------------------------------------------------------------------

async def validate_ahtml(html: str) -> dict[str, Any]:
    """Validate annotated HTML against the schema.

    Returns:
        Validation result with valid, errors, warnings, stats.
    """
    script = f"""
import {{ validateAnnotatedHtml }} from '{_AHTML_DIR}/dist/validate.js';
const html = {json.dumps(html)};
const result = validateAnnotatedHtml(html);
process.stdout.write(JSON.stringify(result));
"""
    result = await _run_node(script, timeout=10.0)
    return json.loads(result)


# ---------------------------------------------------------------------------
# Node.js runner (same pattern as ir_compiler.py)
# ---------------------------------------------------------------------------

async def _run_node(script: str, timeout: float = 30.0) -> str:
    """Run a Node.js script and return stdout.

    Uses the same subprocess pattern as backend/services/ir_compiler.py.
    """
    proc = await asyncio.create_subprocess_exec(
        "node",
        "--input-type=module",
        "-e",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "NODE_NO_WARNINGS": "1"},
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise AHTMLCompileError([f"Node.js subprocess timed out after {timeout}s"])

    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace").strip()
        logger.error("Node.js error: %s", err_text)
        raise AHTMLCompileError([err_text or "Unknown Node.js error"])

    return stdout.decode("utf-8")

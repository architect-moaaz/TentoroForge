"""Design Router — API endpoints for the annotated HTML design editor.

Provides CRUD operations for .design/ files and AHTML → TSX compilation.
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.ahtml_storage import (
    load_all_pages,
    load_page,
    save_pages,
    has_design,
)
from services.ahtml_compiler import (
    compile_ahtml_to_tsx,
    write_ahtml_tsx_files,
    validate_ahtml,
    ir_to_ahtml,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/design", tags=["design"])

# Shared helper to resolve output dir (same pattern as ir.py)
OUTPUT_BASE = Path(__file__).resolve().parent.parent.parent / "output"


async def _output_dir(project_id: str) -> str:
    """Resolve project output directory — DB lookup for UUIDs, fallback to direct path."""
    try:
        from database import get_db
        from models.project import Project
        from sqlalchemy import select

        async for db in get_db():
            try:
                pid = uuid_mod.UUID(project_id)
            except ValueError:
                break
            stmt = select(Project).where(Project.id == pid)
            result = await db.execute(stmt)
            project = result.scalar_one_or_none()
            if project and project.output_dir:
                return project.output_dir
            break
    except Exception:
        pass

    return str(OUTPUT_BASE / project_id)


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------

class SaveDesignRequest(BaseModel):
    pages: list[dict[str, Any]]


class CompileResponse(BaseModel):
    pages: list[dict[str, str]]
    files: list[str]
    errors: list[str]
    warnings: list[str]


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[dict[str, str]]
    warnings: list[dict[str, str]]
    stats: dict[str, int]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def get_design(project_id: str) -> dict[str, Any]:
    """Load all annotated HTML pages for a project.

    Returns:
        { pages: [...], hasDesign: bool, themeCSS: str }
    """
    output_dir = await _output_dir(project_id)
    pages = load_all_pages(output_dir)

    # Load project's globals.css for canvas theme injection
    theme_css = ""
    globals_path = Path(output_dir) / "src" / "app" / "globals.css"
    if globals_path.exists():
        try:
            raw = globals_path.read_text(encoding="utf-8")
            # Strip @tailwind directives and @import — canvas loads Tailwind CDN separately
            import re
            theme_css = re.sub(r'@tailwind\s+\w+\s*;', '', raw)
            theme_css = re.sub(r'@import\s+["\'][^"\']+["\']\s*;?', '', theme_css)
        except (OSError, UnicodeDecodeError):
            pass

    return {
        "pages": pages,
        "hasDesign": len(pages) > 0,
        "themeCSS": theme_css,
    }


@router.put("")
async def save_design(project_id: str, body: SaveDesignRequest) -> dict[str, Any]:
    """Save annotated HTML pages from the GrapeJS editor.

    Returns:
        { saved: [...file_paths] }
    """
    output_dir = await _output_dir(project_id)
    saved = save_pages(output_dir, body.pages)

    return {"saved": saved}


@router.post("/compile")
async def compile_design(project_id: str) -> CompileResponse:
    """Compile design pages to TSX.

    Fast path: If MCP code exists in .design/mcp-code/, wraps it as Next.js pages directly.
    Slow path: Calls LLM agent to convert AHTML → TSX.

    Returns:
        CompileResponse with pages, files, errors, warnings.
    """
    output_dir = await _output_dir(project_id)

    all_results: list[dict[str, str]] = []
    all_files: list[str] = []
    all_errors: list[str] = []
    all_warnings: list[str] = []

    # --- Fast path: compile MCP code directly to Next.js TSX ---
    mcp_dir = Path(output_dir) / ".design" / "mcp-code"
    if mcp_dir.exists():
        import re

        design_pages = load_all_pages(output_dir)
        page_routes = {p["pageId"]: p.get("route", f"/{p['pageId']}") for p in design_pages}

        for tsx_file in sorted(mcp_dir.glob("*.tsx")):
            code = tsx_file.read_text(encoding="utf-8")
            page_id = tsx_file.stem

            # Wrap MCP code as a Next.js "use client" page
            # Extract the function body and add "use client" directive
            func_match = re.search(
                r'export\s+default\s+function\s+(\w+)\s*\(\)\s*\{',
                code,
            )
            component_name = func_match.group(1) if func_match else f"Page_{page_id.replace('-', '_')}"

            # Semanticize: convert visual divs to real buttons, inputs, selects
            from services.mcp_semanticizer import semanticize_mcp_code
            code = semanticize_mcp_code(code)

            tsx_code = f'"use client";\n\n{code}'

            # Determine route
            route = page_routes.get(page_id, f"/{page_id}")
            route_parts = route.strip("/").split("/") if route != "/" else []
            file_path = Path(output_dir) / "src" / "app" / "/".join(route_parts) / "page.tsx"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(tsx_code, encoding="utf-8")

            rel_path = str(file_path.relative_to(output_dir))
            all_files.append(rel_path)
            all_results.append({"pageId": page_id, "route": route, "tsx": tsx_code[:200]})

        if all_files:
            return CompileResponse(
                pages=all_results,
                files=all_files,
                errors=[],
                warnings=["Compiled from MCP code (fast path)"],
            )

    # --- Slow path: AHTML → LLM → TSX ---
    if not has_design(output_dir):
        raise HTTPException(status_code=404, detail="No design files found")

    pages = load_all_pages(output_dir)
    if not pages:
        raise HTTPException(status_code=404, detail="No design pages found")

    for page in pages:
        result = await compile_ahtml_to_tsx(
            html=page["html"],
            page_id=page["pageId"],
        )

        if result["pages"]:
            all_results.extend(result["pages"])

            # Write TSX files
            written = await write_ahtml_tsx_files(output_dir, result["pages"])
            all_files.extend(written)

        all_errors.extend(result.get("errors", []))
        all_warnings.extend(result.get("warnings", []))

    return CompileResponse(
        pages=all_results,
        files=all_files,
        errors=all_errors,
        warnings=all_warnings,
    )


@router.post("/validate")
async def validate_design(project_id: str) -> ValidateResponse:
    """Validate annotated HTML pages against the schema.

    Returns:
        Validation result with errors, warnings, and stats.
    """
    output_dir = await _output_dir(project_id)
    pages = load_all_pages(output_dir)

    if not pages:
        raise HTTPException(status_code=404, detail="No design pages found")

    # Validate each page
    combined_errors: list[dict[str, str]] = []
    combined_warnings: list[dict[str, str]] = []
    combined_stats = {
        "pages": 0,
        "slots": 0,
        "bindings": 0,
        "actions": 0,
        "repeaters": 0,
        "dataSources": 0,
        "components": 0,
    }
    all_valid = True

    for page in pages:
        result = await validate_ahtml(page["html"])
        if not result.get("valid", True):
            all_valid = False

        for err in result.get("errors", []):
            combined_errors.append({
                "page": page["pageId"],
                "selector": err.get("selector", ""),
                "attribute": err.get("attribute", ""),
                "message": err.get("message", ""),
            })

        for warn in result.get("warnings", []):
            combined_warnings.append({
                "page": page["pageId"],
                "selector": warn.get("selector", ""),
                "attribute": warn.get("attribute", ""),
                "message": warn.get("message", ""),
            })

        stats = result.get("stats", {})
        for key in combined_stats:
            combined_stats[key] += stats.get(key, 0)

    return ValidateResponse(
        valid=all_valid,
        errors=combined_errors,
        warnings=combined_warnings,
        stats=combined_stats,
    )


@router.post("/fix-images")
async def fix_images_endpoint(project_id: str) -> dict[str, Any]:
    """Inject local images into existing AHTML pages.

    Replaces gray placeholder divs with <img> tags pointing to
    images in public/images/ based on images_manifest.json.

    Returns:
        { fixed: int, pages: { page_id: count } }
    """
    output_dir = await _output_dir(project_id)

    from services.ahtml_image_fixer import fix_ahtml_images

    results = fix_ahtml_images(output_dir)
    total = sum(results.values())
    return {"fixed": total, "pages": results}


@router.post("/regenerate-from-figma")
async def regenerate_from_figma(project_id: str) -> dict[str, Any]:
    """Regenerate AHTML pages from styles.json (Figma source).

    Re-runs the LLM-based conversion with the latest prompt rules
    (which now include image asset references).

    Returns:
        { pages: int, files: [...] }
    """
    output_dir = await _output_dir(project_id)
    styles_path = Path(output_dir) / "styles.json"

    if not styles_path.exists():
        raise HTTPException(status_code=404, detail="No styles.json found. Project must be a Figma import.")

    import json
    from services.figma_to_ir import convert_figma_styles_to_ahtml
    from services.ahtml_storage import save_pages

    styles_data = json.loads(styles_path.read_text(encoding="utf-8"))

    # Parse frames
    frames: list[tuple[str, dict]] = []
    if isinstance(styles_data, dict) and "children" in styles_data:
        frames = [(styles_data.get("name", "main"), styles_data)]
    elif isinstance(styles_data, dict):
        for fid, fdata in styles_data.items():
            if isinstance(fdata, dict):
                frames.append((fdata.get("name", fid), fdata))

    # Convert each frame
    ahtml_pages: list[dict[str, Any]] = []
    for i, (frame_name, frame_data) in enumerate(frames):
        # Generate semantic page id from frame name
        page_id = (
            frame_name.lower()
            .replace("commitbiz_intentai_", "")
            .replace(" ", "-")
            .replace("/", "-")
            .strip("-")
        ) or f"page-{i}"
        route = f"/{page_id}"
        title = frame_name.replace("Commitbiz_intentai_", "").replace("_", " ").title()

        ahtml = await convert_figma_styles_to_ahtml(
            styles_data=frame_data,
            page_id=page_id,
            route=route,
            title=title,
        )

        if ahtml:
            ahtml_pages.append({
                "pageId": page_id,
                "route": route,
                "title": title,
                "html": ahtml,
            })

    if ahtml_pages:
        saved = save_pages(output_dir, ahtml_pages)
        return {"pages": len(saved), "files": saved}

    return {"pages": 0, "files": []}


@router.post("/from-ir")
async def design_from_ir(project_id: str) -> dict[str, Any]:
    """Generate annotated HTML for the design editor.

    Routing logic:
    - Figma project (styles.json exists): use Figma-aware path that reads
      the actual design tree, preserving colors/layout from the Figma file.
    - Non-Figma project: convert IR manifest to generic theme-based AHTML.

    Returns:
        { pages: int, files: [...], source: "figma" | "ir" }
    """
    output_dir = await _output_dir(project_id)
    import json

    # --- Figma path (preferred for Figma projects) ---
    styles_path = Path(output_dir) / "styles.json"
    if styles_path.exists():
        logger.info("from-ir: Figma project detected, routing to figma-aware path")
        try:
            from services.figma_to_ir import convert_figma_styles_to_ahtml
            from services.ahtml_storage import save_pages

            styles_data = json.loads(styles_path.read_text(encoding="utf-8"))

            # Parse frames
            frames: list[tuple[str, dict]] = []
            if isinstance(styles_data, dict) and "children" in styles_data:
                frames = [(styles_data.get("name", "main"), styles_data)]
            elif isinstance(styles_data, dict):
                for fid, fdata in styles_data.items():
                    if isinstance(fdata, dict):
                        frames.append((fdata.get("name", fid), fdata))

            ahtml_pages: list[dict[str, Any]] = []
            for i, (frame_name, frame_data) in enumerate(frames):
                page_id = (
                    frame_name.lower()
                    .replace("commitbiz_intentai_", "")
                    .replace(" ", "-")
                    .replace("/", "-")
                    .strip("-")
                ) or f"page-{i}"
                route = f"/{page_id}"
                title = frame_name.replace("_", " ").title()

                ahtml = await convert_figma_styles_to_ahtml(
                    styles_data=frame_data,
                    page_id=page_id,
                    route=route,
                    title=title,
                )
                if ahtml:
                    ahtml_pages.append({
                        "pageId": page_id,
                        "route": route,
                        "title": title,
                        "html": ahtml,
                    })

            if ahtml_pages:
                saved = save_pages(output_dir, ahtml_pages)
                # Run image fixer to inject local images
                try:
                    from services.ahtml_image_fixer import fix_ahtml_images
                    fix_ahtml_images(output_dir)
                except Exception as e:
                    logger.warning("Image fix failed (non-fatal): %s", e)

                return {
                    "pages": len(saved),
                    "files": saved,
                    "source": "figma",
                }
        except Exception as e:
            logger.error("Figma path failed, falling back to IR: %s", e)

    # --- IR path (fallback for non-Figma or when Figma fails) ---
    ir_file = Path(output_dir) / ".ir" / "manifest.json"
    if not ir_file.exists():
        # Try auto-migration (registry → IR) for projects that have schema but no IR
        registry_path = Path(output_dir) / "registry.json"
        if registry_path.exists():
            from services.ir_migrate import migrate_to_ir
            await migrate_to_ir(output_dir)

    if not ir_file.exists():
        raise HTTPException(
            status_code=404,
            detail="No IR manifest or Figma styles found. Generate the project first.",
        )

    ir = json.loads(ir_file.read_text(encoding="utf-8"))
    annotated_app = await ir_to_ahtml(ir)

    from services.ahtml_storage import save_annotated_app
    saved = save_annotated_app(output_dir, annotated_app)

    return {
        "pages": len(annotated_app.get("pages", [])),
        "files": saved,
        "source": "ir",
    }


@router.post("/from-code")
async def design_from_code(project_id: str) -> dict[str, Any]:
    """Reverse-compile generated TSX pages into annotated HTML.

    Reads all ``src/app/**/page.tsx`` files, converts JSX → HTML,
    extracts data-source metadata from useQuery calls, and saves
    the result as ``.design/*.design.html`` files.

    This enables Build & Design to reflect the current state of the
    code, including any changes made in Live Edit.
    """
    output_dir = await _output_dir(project_id)
    root = Path(output_dir)

    app_dir = root / "src" / "app"
    if not app_dir.exists():
        raise HTTPException(
            status_code=404,
            detail="No src/app directory found. Generate the project first.",
        )

    from services.tsx_to_ahtml import reverse_compile_project

    pages = reverse_compile_project(output_dir)
    if not pages:
        raise HTTPException(
            status_code=404,
            detail="No page.tsx files found to reverse-compile.",
        )

    # Clear old .design/ files so we don't get duplicates from prior IR generation
    design_dir = root / ".design"
    if design_dir.exists():
        for old_file in design_dir.glob("*.design.html"):
            old_file.unlink(missing_ok=True)
        for old_file in design_dir.glob("*.design.css"):
            old_file.unlink(missing_ok=True)
        for old_file in design_dir.glob("*.meta.json"):
            old_file.unlink(missing_ok=True)

    saved = save_pages(output_dir, pages)

    return {
        "pages": len(pages),
        "files": saved,
        "source": "code",
    }


# ---------------------------------------------------------------------------
# Figma MCP code ingestion
# ---------------------------------------------------------------------------

class FigmaMCPCodeRequest(BaseModel):
    """Request body for saving Figma MCP get_design_context output."""
    node_id: str
    code: str


class FigmaMCPBatchRequest(BaseModel):
    """Request body for saving multiple frames of MCP code."""
    frames: list[FigmaMCPCodeRequest]


@router.post("/figma-mcp-code")
async def save_figma_mcp_code_endpoint(
    project_id: str,
    body: FigmaMCPBatchRequest,
) -> dict[str, Any]:
    """Save Figma MCP get_design_context output for later use by the pipeline.

    The Figma MCP is only accessible from the Claude Code session.
    This endpoint allows pre-fetched MCP code to be saved to disk
    so the generation pipeline can use it.

    Returns:
        { saved: int, files: [...] }
    """
    output_dir = await _output_dir(project_id)

    from services.figma_to_ir import save_figma_mcp_code

    files = []
    for frame in body.frames:
        path = save_figma_mcp_code(output_dir, frame.node_id, frame.code)
        files.append(path)

    return {"saved": len(files), "files": files}


@router.post("/figma-to-ahtml")
async def convert_figma_mcp_to_ahtml(
    project_id: str,
) -> dict[str, Any]:
    """Convert pre-saved Figma MCP code to annotated HTML.

    Reads .design/mcp-code/*.tsx files, converts each to AHTML,
    saves to .design/*.html.

    Returns:
        { pages: int, files: [...] }
    """
    output_dir = await _output_dir(project_id)

    mcp_dir = Path(output_dir) / ".design" / "mcp-code"
    if not mcp_dir.exists():
        raise HTTPException(status_code=404, detail="No Figma MCP code found. Save MCP code first.")

    from services.figma_to_ir import convert_figma_frame_to_ahtml

    ahtml_pages: list[dict[str, Any]] = []
    for tsx_file in sorted(mcp_dir.glob("*.tsx")):
        code = tsx_file.read_text(encoding="utf-8")
        node_id = tsx_file.stem.replace("-", ":")
        page_id = tsx_file.stem
        route = f"/{page_id}"
        title = page_id.replace("-", " ").title()

        ahtml = await convert_figma_frame_to_ahtml(
            figma_code=code,
            page_id=page_id,
            route=route,
            title=title,
        )

        if ahtml:
            ahtml_pages.append({
                "pageId": page_id,
                "route": route,
                "title": title,
                "html": ahtml,
            })

    if ahtml_pages:
        saved = save_pages(output_dir, ahtml_pages)
        return {"pages": len(ahtml_pages), "files": saved}

    return {"pages": 0, "files": []}

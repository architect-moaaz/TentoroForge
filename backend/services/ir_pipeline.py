"""IR Pipeline — generates frontend via the IR system instead of LLM agents.

Replaces the component_agent + page_agent phases with deterministic IR generation:
  plan → design spec → AppSpec → AppIR → compile → write files

Handles both text-based and Figma-based generation in a single unified pipeline.
Feature-flagged via IR_FRONTEND_ENABLED env var.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, AsyncIterator

from sse_helpers import sse_event

logger = logging.getLogger(__name__)

# Feature flag
IR_FRONTEND_ENABLED = os.getenv("IR_FRONTEND_ENABLED", "false").lower() in ("true", "1", "yes")


async def run_ir_frontend_pipeline(
    output_dir: str,
    plan: dict[str, Any],
    description: str,
    domain_context: dict[str, Any] | None = None,
    figma_context: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> AsyncIterator[dict]:
    """Run the unified IR-based frontend generation pipeline.

    Handles both text and Figma paths:
      1. Load design spec (produced by Design Agent earlier in the pipeline)
      2. Detect domain, load Figma tokens if available
      3. Convert plan → AppSpec (with design spec or industry fallback)
      4. Generate AppIR from AppSpec
      5. If Figma: run Figma IR Agent, merge page IR into AppIR
      6. Compile AppIR → TSX files
      7. Write files + save IR

    Yields SSE events for streaming progress.
    """
    from agents.design_agent import load_design_spec
    from services.ir_adapter import plan_to_app_spec
    from services.ir_compiler import (
        generate_and_compile,
        compile_ir,
        write_compiled_files,
        save_ir,
        IRCompileError,
    )

    start_time = time.time()

    # --- Step 1: Load design spec from Design Agent ---
    design_spec = load_design_spec(output_dir)
    if design_spec:
        yield sse_event("log", {"text": "[IR] Using LLM Design Agent spec for theming"})
    else:
        yield sse_event("log", {"text": "[IR] No design spec found — using industry defaults"})

    # --- Step 2: Domain + Figma tokens ---
    if not domain_context:
        from services.domain_context import detect_domain
        domain_context = detect_domain(description)

    domain_label = domain_context.get("domain", "General")
    yield sse_event("log", {"text": f"[IR] Domain: {domain_label}"})

    figma_tokens = None
    figma_context_path = os.path.join(output_dir, "src", "contracts", "figma-context.json")
    if os.path.exists(figma_context_path):
        try:
            figma_tokens = json.loads(open(figma_context_path).read()).get("design_tokens")
        except Exception:
            pass

    # --- Step 3: Convert plan to AppSpec ---
    yield sse_event("status", {"message": f"Preparing IR generation ({domain_label})..."})

    app_name = plan.get("module_name", "My App")
    app_spec = plan_to_app_spec(
        plan, app_name,
        domain_context=domain_context,
        figma_tokens=figma_tokens,
        design_spec=design_spec,
    )

    entity_count = len(app_spec.get("entities", []))
    entity_names = [e["name"] for e in app_spec.get("entities", [])]
    yield sse_event("log", {
        "text": f"[IR] AppSpec: {entity_count} entities ({', '.join(entity_names)})",
    })

    # --- Step 3.5: Generate page layout skeletons via LLM ---
    skeletons = None
    skeleton_path = os.path.join(output_dir, "src", "contracts", "page-skeletons.json")
    if os.path.exists(skeleton_path):
        try:
            skeletons = json.loads(open(skeleton_path).read())
            yield sse_event("log", {"text": f"[IR] Loaded {len(skeletons)} page skeletons from cache"})
        except Exception:
            pass

    if skeletons is None:
        from pathlib import Path as _P
        from services.agent_messages import AssistantMessage, ResultMessage, TextBlock

        entity_names = [e["name"] for e in app_spec.get("entities", [])]

        # --- Figma path: convert styles.json frames ---
        styles_path = _P(output_dir) / "styles.json"
        has_figma = figma_context and styles_path.exists()

        if has_figma:
            yield sse_event("status", {"message": "Converting Figma design..."})

            from services.figma_to_ir import (
                convert_figma_frame_to_ir,
                convert_figma_frame_to_ahtml,
                convert_figma_styles_to_ahtml,
                fetch_figma_code_for_frame,
                build_figma_code_from_styles,
            )

            try:
                styles_data = json.loads(styles_path.read_text(encoding="utf-8"))

                # Parse frames from styles.json
                frames: list[tuple[str, str, dict]] = []  # (frame_name, node_id, data)
                if isinstance(styles_data, dict) and "children" in styles_data:
                    frames = [(styles_data.get("name", "main"), "0:1", styles_data)]
                elif isinstance(styles_data, dict):
                    for fid, fdata in styles_data.items():
                        if isinstance(fdata, dict):
                            frames.append((fdata.get("name", fid), fid, fdata))

                plan_pages = plan.get("pages", [])
                figma_url = figma_context.get("figma_url", "")

                # Extract file_key from figma_url
                file_key = None
                if figma_url:
                    from figma_parser import parse_figma_url
                    try:
                        parsed = parse_figma_url(figma_url)
                        file_key = parsed.get("file_key")
                    except Exception:
                        pass

                from services.ahtml_storage import save_pages
                ahtml_pages: list[dict] = []
                figma_skeletons: list[dict] = []

                for i, (frame_name, node_id, frame_data) in enumerate(frames):
                    page_info = plan_pages[i] if i < len(plan_pages) else {}
                    route = page_info.get("route", f"/page-{i}")
                    title = page_info.get("name", frame_name)
                    page_id = title.lower().replace(" ", "-").replace("/", "-").strip("-") or f"page-{i}"

                    mcp_code = None
                    ahtml = None

                    # --- Strategy 1: Figma MCP get_design_context (pixel-perfect) ---
                    if file_key:
                        yield sse_event("log", {"text": f"[IR] Checking for MCP code for '{frame_name}' ({node_id})..."})
                        mcp_code = await fetch_figma_code_for_frame(file_key, node_id, output_dir=output_dir)

                    if mcp_code:
                        yield sse_event("log", {"text": f"[IR] ✓ Got {len(mcp_code)} chars from Figma MCP"})

                        # Convert MCP React+Tailwind → AHTML (small transform)
                        ahtml = await convert_figma_frame_to_ahtml(
                            figma_code=mcp_code,
                            page_id=page_id,
                            route=route,
                            title=title,
                            entity_names=entity_names,
                        )

                        # Also use MCP code for IR path (higher fidelity than pseudo-JSX)
                        page_ir = await convert_figma_frame_to_ir(
                            figma_code=mcp_code,
                            page_id=page_id,
                            route=route,
                            title=title,
                            entity_names=entity_names,
                        )
                        if page_ir:
                            figma_skeletons.append(page_ir)

                    # --- Strategy 2: styles.json → AHTML (fallback) ---
                    if not ahtml:
                        yield sse_event("log", {"text": f"[IR] Falling back to styles.json for '{frame_name}'..."})
                        ahtml = await convert_figma_styles_to_ahtml(
                            styles_data=frame_data,
                            page_id=page_id,
                            route=route,
                            title=title,
                            entity_names=entity_names,
                        )

                    if ahtml:
                        ahtml_pages.append({
                            "pageId": page_id,
                            "route": route,
                            "title": title,
                            "html": ahtml,
                        })
                        yield sse_event("log", {"text": f"[IR] ✓ Frame '{frame_name}' → AHTML"})
                    else:
                        yield sse_event("log", {"text": f"[IR] ✗ Frame '{frame_name}' conversion failed"})

                    # IR fallback if MCP didn't produce one
                    if not mcp_code:
                        pseudo_jsx = build_figma_code_from_styles(frame_data)
                        page_ir = await convert_figma_frame_to_ir(
                            figma_code=pseudo_jsx,
                            page_id=page_id,
                            route=route,
                            title=title,
                            entity_names=entity_names,
                        )
                        if page_ir:
                            figma_skeletons.append(page_ir)

                # Save AHTML pages
                if ahtml_pages:
                    saved = save_pages(output_dir, ahtml_pages)
                    yield sse_event("log", {"text": f"[IR] Saved {len(saved)} AHTML pages to .design/"})

                if figma_skeletons:
                    skeletons = figma_skeletons
                    yield sse_event("log", {"text": f"[IR] Converted {len(figma_skeletons)}/{len(frames)} frames to IR skeletons"})
            except Exception as e:
                yield sse_event("log", {"text": f"[IR] Figma conversion error: {e} — falling back to layout agent"})

        # --- Text path (or Figma fallback): LLM generates page skeletons ---
        if skeletons is None:
            yield sse_event("status", {"message": "Designing page layouts..."})
            yield sse_event("log", {"text": "[IR] Running Page Layout Agent..."})

            from agents.page_layout_agent import run_page_layout_agent, extract_skeletons as _extract_skeletons

            figma_screenshots = sorted(str(p) for p in _P(output_dir).glob("reference*.png"))

            layout_text = ""
            async for message in run_page_layout_agent(
                output_dir, plan,
                design_spec=design_spec,
                domain_context=domain_context,
                figma_screenshots=figma_screenshots if figma_screenshots else None,
            ):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            layout_text += block.text
                elif isinstance(message, ResultMessage):
                    pass

            skeletons = _extract_skeletons(layout_text)
            if skeletons:
                yield sse_event("log", {"text": f"[IR] Generated {len(skeletons)} page skeletons"})
            else:
                yield sse_event("log", {"text": "[IR] Could not extract skeletons — falling back to pattern generator"})

        # Cache skeletons for reuse
        if skeletons:
            contracts_dir = os.path.join(output_dir, "src", "contracts")
            os.makedirs(contracts_dir, exist_ok=True)
            with open(skeleton_path, "w") as f:
                json.dump(skeletons, f, indent=2)

    # --- Step 4: Generate IR and compile ---
    yield sse_event("status", {"message": "Generating UI via IR compiler..."})

    try:
        if skeletons:
            # Skeleton-based: LLM layouts + pattern library data filling
            yield sse_event("log", {"text": "[IR] Compiling with LLM-designed page layouts..."})
            from services.ir_compiler import generate_ir_from_skeletons
            result = await generate_ir_from_skeletons(skeletons, app_spec)
        else:
            # Fallback: deterministic pattern generator
            yield sse_event("log", {"text": "[IR] Compiling with default patterns..."})
            result = await generate_and_compile(app_spec)
    except IRCompileError as e:
        yield sse_event("log", {"text": f"[IR] Compilation failed: {'; '.join(e.errors)}"})
        # Try fallback if skeleton compilation failed
        if skeletons:
            yield sse_event("log", {"text": "[IR] Retrying with default patterns..."})
            try:
                result = await generate_and_compile(app_spec)
            except IRCompileError as e2:
                yield sse_event("log", {"text": f"[IR] Fallback also failed: {'; '.join(e2.errors)}"})
                return
        else:
            return

    ir = result["ir"]
    files = result["files"]
    warnings = result.get("warnings", [])

    # --- Step 5: Figma page injection (if Figma context available) ---
    if figma_context and figma_context.get("figma_url"):
        yield sse_event("log", {"text": "[IR] Figma context detected — running Figma IR Agent..."})

        try:
            from agents.figma_ir_agent import run_figma_ir_agent, extract_page_ir
            from services.agent_messages import AssistantMessage, ResultMessage, TextBlock

            # Fetch Figma context for the IR agent
            figma_ctx = await _fetch_figma_context(output_dir, figma_context)

            response_text = ""
            async for message in run_figma_ir_agent(
                figma_context=figma_ctx,
                page_name="figma-page",
                route="/",
            ):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            response_text += block.text
                elif isinstance(message, ResultMessage):
                    pass  # End of agent — no content

            figma_page_ir = extract_page_ir(response_text)
            if figma_page_ir:
                yield sse_event("log", {"text": f"[IR] Figma page IR extracted: {figma_page_ir.get('$id', 'unnamed')}"})

                # Inject Figma page into IR (replace dashboard or insert at 0)
                existing_idx = next(
                    (i for i, p in enumerate(ir["pages"]) if p["$id"] == "dashboard" or p["route"] == "/"),
                    None,
                )
                if existing_idx is not None:
                    ir["pages"][existing_idx] = figma_page_ir
                else:
                    ir["pages"].insert(0, figma_page_ir)

                # Recompile with Figma page
                try:
                    result2 = await compile_ir(ir)
                    if not result2.get("errors"):
                        files = result2["files"]
                        yield sse_event("log", {"text": "[IR] Recompiled with Figma page successfully"})
                    else:
                        yield sse_event("log", {"text": f"[IR] Recompile warnings: {result2['errors'][:2]}"})
                except Exception as e:
                    yield sse_event("log", {"text": f"[IR] Recompile failed: {e} — using base IR"})
            else:
                yield sse_event("log", {"text": "[IR] Could not extract Figma page IR — using pattern-generated pages"})
        except Exception as e:
            yield sse_event("log", {"text": f"[IR] Figma IR Agent error: {e} — continuing with pattern pages"})

    # --- Step 6: Write files ---
    page_count = len(ir.get("pages", []))
    file_count = len(files)
    total_lines = sum(content.count("\n") + 1 for content in files.values())

    yield sse_event("log", {
        "text": f"[IR] Compiled: {page_count} pages → {file_count} files ({total_lines} lines)",
    })

    if warnings:
        for w in warnings[:5]:
            yield sse_event("log", {"text": f"[IR] Warning: {w}"})

    yield sse_event("status", {"message": "Writing IR-compiled files..."})

    written = await write_compiled_files(output_dir, files, src_prefix="src")
    for rel_path in written:
        yield sse_event("file_created", {"path": rel_path})

    yield sse_event("log", {"text": f"[IR] Wrote {len(written)} file(s)"})

    # --- Step 7: Save IR ---
    ir_path = await save_ir(output_dir, ir)
    yield sse_event("log", {"text": f"[IR] Saved IR manifest: {ir_path}"})

    # --- Step 7.5: Inject runtime (workflows + rules + FEEL-lite) ---
    try:
        from services.runtime_injector import inject_runtime
        result = inject_runtime(output_dir, project_id=project_id)
        yield sse_event("log", {
            "text": f"[Runtime] Injected {len(result['copied'])} runtime files",
        })
        if result["errors"]:
            for err in result["errors"][:3]:
                yield sse_event("log", {"text": f"[Runtime] ⚠ {err}"})
    except Exception as e:
        logger.warning("Runtime injection failed (non-fatal): %s", e)
        yield sse_event("log", {"text": f"[Runtime] Skipped: {e}"})

    # --- Step 8: Generate AHTML for the design editor ---
    # Always run for Figma projects (preserves design fidelity).
    # For non-Figma projects, gated on AHTML_FRONTEND_ENABLED env var.
    is_figma_project = bool(figma_context) or _P(output_dir).joinpath("styles.json").exists()

    if is_figma_project or os.environ.get("AHTML_FRONTEND_ENABLED"):
        try:
            if is_figma_project:
                yield sse_event("log", {"text": "[IR] Generating Figma-aware AHTML..."})
                from services.figma_to_ir import convert_figma_styles_to_ahtml
                from services.ahtml_storage import save_pages
                from services.ahtml_image_fixer import fix_ahtml_images

                styles_path = _P(output_dir) / "styles.json"
                if styles_path.exists():
                    styles_data = json.loads(styles_path.read_text(encoding="utf-8"))
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

                        yield sse_event("log", {"text": f"[IR] Converting Figma frame '{frame_name}'..."})
                        try:
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
                        except Exception as fe:
                            logger.warning("Frame %s conversion failed: %s", frame_name, fe)

                    if ahtml_pages:
                        saved = save_pages(output_dir, ahtml_pages)
                        yield sse_event("log", {
                            "text": f"[IR] Saved {len(saved)} Figma AHTML pages to .design/",
                        })
                        # Inject local images
                        try:
                            fixed = fix_ahtml_images(output_dir)
                            if fixed:
                                yield sse_event("log", {
                                    "text": f"[IR] Injected images into {len(fixed)} pages",
                                })
                        except Exception as fe:
                            logger.warning("Image fix failed: %s", fe)
            else:
                from services.ahtml_compiler import ir_to_ahtml
                from services.ahtml_storage import save_annotated_app

                yield sse_event("log", {"text": "[IR] Generating annotated HTML..."})
                annotated_app = await ir_to_ahtml(ir)
                ahtml_files = save_annotated_app(output_dir, annotated_app)
                yield sse_event("log", {
                    "text": f"[IR] Saved {len(ahtml_files)} AHTML file(s) to .design/",
                })
        except Exception as e:
            logger.warning("AHTML generation failed (non-fatal): %s", e, exc_info=True)
            yield sse_event("log", {
                "text": f"[IR] AHTML generation skipped: {e}",
            })

    # --- Summary ---
    duration_ms = int((time.time() - start_time) * 1000)

    yield sse_event("agent_result", {
        "num_turns": 0,
        "cost_usd": 0.01 if figma_context else 0,
        "duration_ms": duration_ms,
        "ir_mode": True,
        "figma_mode": bool(figma_context),
        "pages_generated": page_count,
        "files_generated": file_count,
        "lines_generated": total_lines,
    })

    yield sse_event("log", {
        "text": (
            f"[IR] Frontend generation complete in {duration_ms}ms — "
            f"{page_count} pages, {total_lines} lines"
        ),
    })


async def _fetch_figma_context(
    output_dir: str,
    figma_context: dict[str, Any],
) -> dict[str, Any]:
    """Build Figma context dict for the IR agent from available files."""
    from pathlib import Path

    context: dict[str, Any] = {}

    # Check for reference screenshot
    ref_png = Path(output_dir) / "reference.png"
    if ref_png.exists():
        context["screenshot"] = str(ref_png)

    # Check for pre-fetched context dir
    figma_dir = Path(output_dir) / "figma_context"
    if figma_dir.exists():
        for f in figma_dir.iterdir():
            if f.suffix == ".json":
                try:
                    context[f.stem] = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    pass

    context["figma_url"] = figma_context.get("figma_url", "")
    context["file_key"] = figma_context.get("file_key", "")
    context["node_id"] = figma_context.get("node_id", "")

    return context

"""Figma → IR Pipeline — converts Figma designs to IR pages.

Flow:
  1. Fetch Figma design context (screenshot, code hints, tokens)
  2. Run Figma IR Agent → produces PageIR
  3. Build full AppIR (with data sources from plan)
  4. Compile IR → TSX files
  5. Write files + save IR

This replaces the old figma_ui_agent → raw TSX path.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, AsyncIterator

from sse_helpers import sse_event

logger = logging.getLogger(__name__)


async def run_figma_ir_pipeline(
    output_dir: str,
    plan: dict[str, Any],
    description: str,
    figma_url: str,
    figma_token: str,
) -> AsyncIterator[dict]:
    """Run the Figma → IR pipeline.

    Yields SSE events for streaming progress.
    """
    from agents.figma_ir_agent import run_figma_ir_agent, extract_page_ir
    from services.ir_adapter import plan_to_app_spec
    from services.ir_compiler import (
        generate_and_compile,
        write_compiled_files,
        save_ir,
        IRCompileError,
    )
    from services.agent_messages import AssistantMessage, ResultMessage, TextBlock

    start_time = time.time()

    # ── Step 1: Get Figma context ──
    yield sse_event("log", {"text": "[IR-Figma] Fetching Figma design context..."})

    figma_context = await _fetch_figma_context(output_dir, figma_url, figma_token)

    yield sse_event("log", {"text": f"[IR-Figma] Design context ready (code hints: {'yes' if figma_context.get('code') else 'no'})"})

    # ── Step 2: Run Figma IR Agent ──
    yield sse_event("status", {"message": "AI analyzing Figma design → IR..."})
    yield sse_event("log", {"text": "[IR-Figma] Running Figma IR Agent..."})

    response_text = ""
    async for message in run_figma_ir_agent(
        figma_context=figma_context,
        page_name="figma-page",
        route="/",
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    response_text += block.text
        elif isinstance(message, ResultMessage):
            # ResultMessage signals end of agent — no content to extract
            pass

    # Extract the page IR from the agent's response
    figma_page_ir = extract_page_ir(response_text)

    if figma_page_ir:
        yield sse_event("log", {"text": f"[IR-Figma] Page IR extracted: {figma_page_ir.get('$id', 'unnamed')}"})
    else:
        yield sse_event("log", {"text": "[IR-Figma] Failed to extract page IR from agent. Falling back to pattern generation."})
        figma_page_ir = None

    # ── Step 3: Build full AppIR ──
    yield sse_event("status", {"message": "Building IR from design + plan..."})

    app_name = plan.get("module_name", description.split()[:3] or ["My App"])
    if isinstance(app_name, list):
        app_name = " ".join(app_name)

    # Detect domain and load Figma design tokens
    from services.domain_context import detect_domain
    from services.industry_design import get_industry_design
    domain_ctx = detect_domain(description)
    domain_label = domain_ctx.get("domain", "General")
    yield sse_event("log", {"text": f"[IR-Figma] Domain: {domain_label}, Theme: {get_industry_design(domain_label)['theme']}"})

    # Load Figma design tokens if available
    figma_tokens = None
    figma_context_path = os.path.join(output_dir, "src", "contracts", "figma-context.json")
    if os.path.exists(figma_context_path):
        try:
            figma_tokens = json.loads(open(figma_context_path).read()).get("design_tokens")
        except Exception:
            pass

    # Generate the standard IR from the plan (entities, CRUD pages, auth) with industry design
    app_spec = plan_to_app_spec(plan, app_name, domain_context=domain_ctx, figma_tokens=figma_tokens)

    try:
        result = await generate_and_compile(app_spec)
    except IRCompileError as e:
        yield sse_event("log", {"text": f"[IR-Figma] Base IR compilation failed: {'; '.join(e.errors)}"})
        return

    ir = result["ir"]
    files = result["files"]

    # Inject the Figma-generated page into the IR
    if figma_page_ir:
        # Replace the dashboard or add as a new page
        existing_idx = next(
            (i for i, p in enumerate(ir["pages"]) if p["$id"] == "dashboard" or p["route"] == "/"),
            None,
        )
        if existing_idx is not None:
            ir["pages"][existing_idx] = figma_page_ir
        else:
            ir["pages"].insert(0, figma_page_ir)

        # Recompile with the Figma page included
        from services.ir_compiler import compile_ir
        try:
            result2 = await compile_ir(ir)
            if not result2.get("errors"):
                files = result2["files"]
            else:
                yield sse_event("log", {"text": f"[IR-Figma] Recompile with Figma page had errors: {result2['errors'][:2]}"})
        except Exception as e:
            yield sse_event("log", {"text": f"[IR-Figma] Recompile failed: {e}"})

    # ── Step 4: Write files ──
    yield sse_event("status", {"message": "Writing IR-compiled files..."})

    written = await write_compiled_files(output_dir, files, src_prefix="src")
    for rel_path in written:
        yield sse_event("file_created", {"path": rel_path})

    # ── Step 5: Save IR ──
    await save_ir(output_dir, ir)

    page_count = len(ir.get("pages", []))
    file_count = len(files)
    total_lines = sum(c.count("\n") + 1 for c in files.values())
    duration_ms = int((time.time() - start_time) * 1000)

    yield sse_event("agent_result", {
        "num_turns": 1,
        "cost_usd": 0.01,  # estimate for Figma IR agent call
        "duration_ms": duration_ms,
        "ir_mode": True,
        "figma_mode": True,
        "pages_generated": page_count,
        "files_generated": file_count,
    })

    yield sse_event("log", {
        "text": (
            f"[IR-Figma] Complete in {duration_ms}ms — "
            f"{page_count} pages, {file_count} files, {total_lines} lines"
        ),
    })


# ---------------------------------------------------------------------------
# Figma context fetcher
# ---------------------------------------------------------------------------

async def _fetch_figma_context(
    output_dir: str,
    figma_url: str,
    figma_token: str,
) -> dict[str, Any]:
    """Fetch Figma design context.

    Tries the Figma MCP server first, falls back to reading
    any previously fetched context from disk.
    """
    from pathlib import Path

    context: dict[str, Any] = {}

    # Check for previously fetched context
    figma_dir = Path(output_dir) / "figma_context"
    if figma_dir.exists():
        for f in figma_dir.iterdir():
            if f.suffix == ".json":
                try:
                    context[f.stem] = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
            elif f.suffix == ".txt":
                context[f.stem] = f.read_text(encoding="utf-8")

    # Check for reference screenshot
    ref_png = Path(output_dir) / "reference.png"
    if ref_png.exists():
        context["screenshot"] = str(ref_png)

    # If we have the Figma parser available, extract from URL
    try:
        from figma_parser import parse_figma_url
        parsed = parse_figma_url(figma_url)
        if parsed:
            context["figma_url"] = figma_url
            context["file_key"] = parsed.get("file_key")
            context["node_id"] = parsed.get("node_id")
    except Exception:
        pass

    # Add the URL itself as context if nothing else
    if not context:
        context["figma_url"] = figma_url
        context["description"] = f"Figma design from: {figma_url}"

    return context

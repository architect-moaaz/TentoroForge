"""Tentoro Forge — FastAPI server for the conversational app builder platform."""

import asyncio
import json
import os
import uuid
import zipfile
from io import BytesIO
from pathlib import Path

# Strip env vars that prevent the bundled Claude CLI from launching
# (it refuses to run inside another Claude Code session)
os.environ.pop("CLAUDECODE", None)
os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)

# Raise the bundled-CLI output ceiling for every agent subprocess (planner, api,
# bizlogic, components, pages…). The CLI default is 32000 tokens, which a large plan
# (e.g. a multi-entity HVAC field-service app) overruns -> "response exceeded the
# 32000 output token maximum". 64000 is the model's max for sonnet. Set here (not just
# in start-all.sh) so it holds no matter how the backend was launched; subprocesses
# inherit this process's environment at spawn time. setdefault keeps any explicit override.
os.environ.setdefault("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "64000")

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agent import run_agent, run_reviewer_agent, run_fixer_agent, run_refinement_agent, _prefetch_figma_data, MAX_REVIEW_ITERATIONS
from figma_parser import parse_figma_url
from screenshot import capture_screenshot
from preview import start_preview, stop_preview, stop_all_previews, get_preview_port
from services.agent_messages import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock, ToolResultBlock

from config import ALLOWED_ORIGINS, RATE_LIMIT_REQUESTS_PER_MINUTE, RATE_LIMIT_BURST, SENTRY_DSN, APP_ENV

# Routers
from routers.auth import router as auth_router
from routers.orgs import router as orgs_router
from routers.project_events import router as project_events_router
# Schema editor (Phase 5 port): output_projects must be registered BEFORE the
# UUID-based projects router so non-UUID ids ('test-app', etc.) reach the
# filesystem-backed editor endpoints.
from routers.output_projects import router as output_projects_router
from routers.projects import router as projects_router
from routers.schema_edit import router as schema_edit_router
from routers.field_interactions import router as field_interactions_router
from routers.plan_adjust import router as plan_adjust_router
from routers.mobile_builds import router as mobile_builds_router
from routers.platform_integrations import router as platform_integrations_router
from routers.platform_mcp_servers import router as platform_mcp_servers_router
from routers.preview_proxy import router as preview_proxy_router
from routers.deployments import router as deployments_router
from routers.verify import router as verify_router
from routers.generate import router as generate_router
from routers.blueprint_generate import router as blueprint_generate_router
from routers.templates import router as templates_router
from routers.discovery import router as discovery_router
from routers.data_model import router as data_model_router
from routers.rules import router as rules_router
from routers.workflows import router as workflows_router
from routers.decisions import router as decisions_router
from routers.open_decisions import router as open_decisions_router
from routers.pages import router as pages_router
from routers.navigation import router as navigation_router
from routers.agent_builder import router as agent_builder_router
from routers.ai_features import router as ai_features_router
from routers.portal import router as portal_router
from routers.health import router as health_router
from routers.quality import router as quality_router
from routers.runtime_exceptions import router as runtime_exceptions_router
from routers.notifications import router as notifications_router
from routers.sso import router as sso_router
from routers.audit import router as audit_router
from routers.attachments import router as attachments_router
from routers.files import router as files_router
from routers.environments import router as environments_router
from routers.webhooks import router as webhooks_router
from routers.visual_editor import router as visual_editor_router
from routers.modules import router as modules_router
from routers.export import router as export_router
from routers.ir import router as ir_router
from routers.design import router as design_router
from routers.brand import router as brand_router
from routers.usage import router as usage_router

# Middleware
from middleware.rate_limit import RateLimitMiddleware
from middleware.security_headers import SecurityHeadersMiddleware
from middleware.logging import StructuredLoggingMiddleware, setup_structured_logging
from middleware.error_handler import ErrorHandlerMiddleware
from middleware.metrics import MetricsMiddleware, metrics_endpoint

load_dotenv()

# Strip Claude Code nesting-detection env vars so the Agent SDK can
# spawn its own CLI subprocess without the "cannot be launched inside
# another Claude Code session" error.
os.environ.pop("CLAUDECODE", None)
os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)

# ---------------------------------------------------------------------------
# Sentry (optional — error tracking)
# ---------------------------------------------------------------------------
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[FastApiIntegration(), StarletteIntegration()],
            traces_sample_rate=0.1 if APP_ENV == "production" else 1.0,
            environment=APP_ENV,
        )
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Tentoro Forge",
    description="Conversational + visual app builder platform",
    docs_url="/docs" if APP_ENV != "production" else None,
    redoc_url="/redoc" if APP_ENV != "production" else None,
)

# Set up structured logging
from config import LOG_LEVEL
setup_structured_logging(LOG_LEVEL)

# Middleware stack (outermost → innermost)
app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=RATE_LIMIT_REQUESTS_PER_MINUTE,
    burst=RATE_LIMIT_BURST,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health_router)
app.include_router(quality_router)
app.include_router(runtime_exceptions_router)
app.include_router(project_events_router)
app.include_router(auth_router)
app.include_router(orgs_router)
# output_projects BEFORE projects so /api/projects/<short-id> routes win
# first-match for non-UUID ids (the schema editor uses filesystem dirs).
app.include_router(output_projects_router)
app.include_router(projects_router)
app.include_router(schema_edit_router)
app.include_router(field_interactions_router)
app.include_router(plan_adjust_router)
app.include_router(mobile_builds_router)
app.include_router(platform_integrations_router)
app.include_router(platform_mcp_servers_router)
app.include_router(preview_proxy_router)
app.include_router(deployments_router)
app.include_router(verify_router)
app.include_router(generate_router)
# §115 — generation through the Living Blueprint, registered beside the legacy
# chain rather than replacing it, so the old path keeps working while the new
# one is proven and a caller can see from the URL which engine it asked for.
app.include_router(blueprint_generate_router)
app.include_router(templates_router)
app.include_router(discovery_router)
app.include_router(data_model_router)
app.include_router(rules_router)
from routers.app_actions import router as app_actions_router
app.include_router(app_actions_router)

# Debug-only: regenerate schemas for an existing project (manual exercise of
# schema-mode pipeline). Remove once schema-mode generations are routine.
from routers._debug_schema import router as _debug_schema_router
app.include_router(_debug_schema_router)
# Debug-only: render + score a page and append to fidelity-log.json.
from routers._debug_fidelity import router as _debug_fidelity_router
app.include_router(_debug_fidelity_router)
app.include_router(workflows_router)
app.include_router(decisions_router)
app.include_router(open_decisions_router)
app.include_router(pages_router)
app.include_router(navigation_router)
app.include_router(agent_builder_router)
app.include_router(ai_features_router)
app.include_router(portal_router)
app.include_router(notifications_router)
app.include_router(sso_router)
app.include_router(audit_router)
app.include_router(files_router)
app.include_router(attachments_router)
app.include_router(environments_router)
app.include_router(webhooks_router)
app.include_router(visual_editor_router)
app.include_router(modules_router)
app.include_router(export_router)
app.include_router(ir_router)
app.include_router(design_router)
app.include_router(brand_router)
app.include_router(usage_router)

# Metrics endpoint (Prometheus format)
app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], tags=["monitoring"])

OUTPUT_BASE = Path(__file__).parent.parent / "output"
OUTPUT_BASE.mkdir(exist_ok=True)

# Static mount for org-uploaded assets (logos, etc.). Backend serves the
# file directly; nginx/Caddy already proxies /static/* to the backend.
# Anonymous read is intentional — org logos are inherently semi-public
# (they appear on login pages that show the org's branded landing).
from fastapi.staticfiles import StaticFiles
ORG_LOGOS_DIR = OUTPUT_BASE / "org-logos"
ORG_LOGOS_DIR.mkdir(exist_ok=True)
app.mount("/static/org-logos", StaticFiles(directory=ORG_LOGOS_DIR), name="org-logos")


class GenerateRequest(BaseModel):
    figma_url: str
    figma_token: str


class RefineRequest(BaseModel):
    instruction: str


@app.on_event("startup")
async def _log_forge_gates():
    """Startup banner listing every last-24h feature flag and its
    resolved state. Grep for ``[forge-gates]`` in prod logs to confirm
    what's on for a given generation without digging into env
    inspection."""
    import logging

    from services.flag_profile import is_on as _flag_on

    def _truthy(name: str, default: str = "0") -> bool:
        # Route through flag_profile so FORGE_QUALITY=full flips this whole
        # startup registry to "on" and the log stays truthful.
        return _flag_on(name, default=(default not in ("0", "false", "off", "no", "")))

    gates: dict[str, bool] = {
        # Spec A — brief-canonical pipeline
        "brief_author":       _truthy("FORGE_BRIEF_AUTHOR"),
        "brief_consume":      _truthy("FORGE_BRIEF_CONSUME"),
        "brief_canonical":    _truthy("FORGE_BRIEF_CANONICAL"),
        "legacy_design_esc":  _truthy("FORGE_LEGACY_DESIGN_AGENT"),
        # Spec B — form polish
        "form_context_panel": _truthy("FORGE_FORM_CONTEXT_PANEL"),
        "field_visibility":   _truthy("FORGE_FIELD_VISIBILITY"),
        # Spec C — post-gen polish (one per slice)
        "polish_dashboard":   _truthy("FORGE_POLISH_DASHBOARD"),
        "polish_sig_moves":   _truthy("FORGE_POLISH_SIGNATURE_MOVES"),
        "polish_interactions": _truthy("FORGE_POLISH_INTERACTIONS"),
        "polish_dark_mode":   _truthy("FORGE_POLISH_DARK_MODE"),
        "polish_edge_pages":  _truthy("FORGE_POLISH_EDGE_PAGES"),
        "polish_variety":     _truthy("FORGE_POLISH_VARIETY"),
        "polish_motion":      _truthy("FORGE_POLISH_MOTION"),
        "polish_logo":        _truthy("FORGE_POLISH_LOGO"),
        # Spec D — authorship consolidation
        "cleanup_wave_4":     _truthy("FORGE_CLEANUP_WAVE_4"),
        "figma_llm":          _truthy("FORGE_FIGMA_LLM"),
        # Spec E — advanced UX
        "e_interactions":     _truthy("FORGE_E_INTERACTIONS"),
        "e_patterns":         _truthy("FORGE_E_PATTERNS"),
        "a11y_gate":          _truthy("FORGE_A11Y_GATE"),
        "a11y_gate_strict":   _truthy("FORGE_A11Y_GATE_STRICT"),
        "high_contrast":      _truthy("FORGE_POLISH_HIGH_CONTRAST"),
        # Blueprint (source-of-truth per-app doc)
        "blueprint":          _truthy("FORGE_BLUEPRINT", default="1"),
    }
    on  = [k for k, v in gates.items() if v]
    off = [k for k, v in gates.items() if not v]
    logging.getLogger("forge.startup").info(
        "[forge-gates] on=%s off=%s", ",".join(on), ",".join(off),
    )


@app.on_event("startup")
async def _start_timer_scheduler():
    from runtime.timer_scheduler import TimerScheduler
    from services.main_loop import set_main_loop
    set_main_loop(asyncio.get_running_loop())
    app.state.timer_scheduler = TimerScheduler()
    await app.state.timer_scheduler.start()


@app.on_event("shutdown")
async def _shutdown():
    stop_all_previews()
    if hasattr(app.state, "timer_scheduler"):
        await app.state.timer_scheduler.stop()


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """Start generation — streams SSE events as the agent works."""
    project_id = str(uuid.uuid4())[:8]
    output_dir = str(OUTPUT_BASE / project_id)

    async def event_stream():
        yield {
            "event": "status",
            "data": json.dumps({"message": "Fetching Figma design data...", "project_id": project_id}),
        }

        try:
            # Pre-fetch phase: extract data, export images
            parsed = parse_figma_url(req.figma_url)
            prefetch_info = await _prefetch_figma_data(
                file_key=parsed["file_key"],
                node_id=parsed.get("node_id"),
                output_dir=output_dir,
                figma_token=req.figma_token,
            )
            frames = prefetch_info.get("frames_processed", [])
            yield {
                "event": "status",
                "data": json.dumps({
                    "message": f"Extracted {len(frames)} frame(s), exported images. Starting code generation..."
                }),
            }

            # --- Phase 1: Code generation ---
            gen_result = None
            async for message in run_agent(
                figma_url=req.figma_url,
                figma_token=req.figma_token,
                output_dir=output_dir,
                prefetch_info=prefetch_info,
            ):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            yield {
                                "event": "log",
                                "data": json.dumps({"text": block.text}),
                            }
                        elif isinstance(block, ToolUseBlock):
                            tool_name = block.name
                            # Detect file creation
                            if tool_name == "Write":
                                file_path = block.input.get("file_path", "")
                                # Make path relative to output dir
                                rel_path = file_path
                                if file_path.startswith(output_dir):
                                    rel_path = file_path[len(output_dir):].lstrip("/")
                                yield {
                                    "event": "file_created",
                                    "data": json.dumps({"path": rel_path}),
                                }
                            yield {
                                "event": "tool_call",
                                "data": json.dumps({
                                    "tool": tool_name,
                                    "args": _safe_serialize(block.input),
                                }),
                            }
                        elif isinstance(block, ToolResultBlock):
                            pass  # Skip tool results in stream

                elif isinstance(message, ResultMessage):
                    gen_result = message

            # --- Phase 2: Visual review loop ---
            total_cost = gen_result.total_cost_usd if gen_result else 0
            total_turns = gen_result.num_turns if gen_result else 0
            total_duration = gen_result.duration_ms if gen_result else 0
            review_iteration = 0

            for iteration in range(MAX_REVIEW_ITERATIONS):
                review_iteration = iteration + 1

                # 2a. Screenshot the running app
                yield {
                    "event": "review_start",
                    "data": json.dumps({
                        "message": f"Taking screenshot and reviewing (iteration {review_iteration}/{MAX_REVIEW_ITERATIONS})...",
                        "iteration": review_iteration,
                        "max_iterations": MAX_REVIEW_ITERATIONS,
                    }),
                }

                screenshot_path = await capture_screenshot(output_dir)
                if not screenshot_path:
                    yield {
                        "event": "review_issues",
                        "data": json.dumps({
                            "message": "Could not capture screenshot — skipping review.",
                            "issues": None,
                            "iteration": review_iteration,
                        }),
                    }
                    break

                # 2b. Run reviewer agent
                issues = await run_reviewer_agent(output_dir)

                # 2c. Check if approved
                if not issues or "APPROVED" in issues.upper():
                    yield {
                        "event": "review_approved",
                        "data": json.dumps({
                            "message": f"Design match approved after {review_iteration} review iteration(s)!",
                            "iteration": review_iteration,
                        }),
                    }
                    break

                # 2d. Report issues found
                yield {
                    "event": "review_issues",
                    "data": json.dumps({
                        "message": f"Found visual differences (iteration {review_iteration}).",
                        "issues": issues,
                        "iteration": review_iteration,
                    }),
                }

                # 2e. Run fixer agent
                yield {
                    "event": "fix_start",
                    "data": json.dumps({
                        "message": f"Applying fixes (iteration {review_iteration}/{MAX_REVIEW_ITERATIONS})...",
                        "iteration": review_iteration,
                    }),
                }

                async for message in run_fixer_agent(output_dir, issues):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock) and block.text.strip():
                                yield {
                                    "event": "log",
                                    "data": json.dumps({"text": f"[Fix {review_iteration}] {block.text}"}),
                                }
                            elif isinstance(block, ToolUseBlock):
                                tool_name = block.name
                                if tool_name in ("Write", "Edit"):
                                    file_path = block.input.get("file_path", "")
                                    rel_path = file_path
                                    if file_path.startswith(output_dir):
                                        rel_path = file_path[len(output_dir):].lstrip("/")
                                    yield {
                                        "event": "file_created",
                                        "data": json.dumps({"path": rel_path}),
                                    }
                                yield {
                                    "event": "tool_call",
                                    "data": json.dumps({
                                        "tool": tool_name,
                                        "args": _safe_serialize(block.input),
                                    }),
                                }
                    elif isinstance(message, ResultMessage):
                        total_cost += message.total_cost_usd or 0
                        total_turns += message.num_turns or 0
                        total_duration += message.duration_ms or 0
            else:
                # Exhausted all iterations without approval
                yield {
                    "event": "review_issues",
                    "data": json.dumps({
                        "message": f"Reached max review iterations ({MAX_REVIEW_ITERATIONS}). Finishing.",
                        "issues": None,
                        "iteration": review_iteration,
                    }),
                }

            # --- Final complete event ---
            yield {
                "event": "complete",
                "data": json.dumps({
                    "project_id": project_id,
                    "num_turns": total_turns,
                    "cost_usd": total_cost,
                    "duration_ms": total_duration,
                    "review_iterations": review_iteration,
                }),
            }

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}),
            }

    return EventSourceResponse(event_stream(), ping=15)


def _safe_serialize(obj: dict) -> str:
    """Serialize tool args, truncating long values."""
    truncated = {}
    for k, v in obj.items():
        s = str(v)
        if len(s) > 200:
            truncated[k] = s[:200] + "..."
        else:
            truncated[k] = v
    return json.dumps(truncated)


@app.get("/api/projects/{project_id}/files")
async def list_files(project_id: str):
    """List all files in a generated project."""
    project_dir = OUTPUT_BASE / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    files = []
    for path in sorted(project_dir.rglob("*")):
        if path.is_file() and not path.name.startswith("."):
            rel = str(path.relative_to(project_dir))
            files.append(rel)

    return {"project_id": project_id, "files": files}


@app.get("/api/projects/{project_id}/file")
async def read_file(project_id: str, path: str = Query(...)):
    """Read a specific file from a generated project."""
    project_dir = OUTPUT_BASE / project_id
    file_path = project_dir / path

    # Prevent path traversal
    if not file_path.resolve().is_relative_to(project_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    content = file_path.read_text(errors="replace")
    return {"path": path, "content": content}


@app.get("/api/projects/{project_id}/asset")
async def serve_asset(project_id: str, path: str = Query(...)):
    """Serve a raw file (image, font, etc.) from a generated project."""
    from fastapi.responses import FileResponse
    import mimetypes

    project_dir = OUTPUT_BASE / project_id
    file_path = project_dir / path

    if not file_path.resolve().is_relative_to(project_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type)


@app.get("/api/projects/{project_id}/download")
async def download_project(project_id: str):
    """Download the entire generated project as a ZIP file."""
    project_dir = OUTPUT_BASE / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(project_dir.rglob("*")):
            if path.is_file():
                arcname = str(path.relative_to(project_dir))
                zf.write(path, arcname)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=design2ui-{project_id}.zip"},
    )


# ---------------------------------------------------------------------------
# Preview endpoints
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/preview/start")
async def preview_start(project_id: str):
    """Start a Next.js dev server for live preview."""
    project_dir = OUTPUT_BASE / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        port = await start_preview(project_id, str(project_dir))
        return {"port": port}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/{project_id}/preview/stop")
async def preview_stop(project_id: str):
    """Stop the dev server for a project."""
    stopped = stop_preview(project_id)
    return {"stopped": stopped}


@app.get("/api/projects/{project_id}/preview/status")
async def preview_status(project_id: str):
    """Check if a preview dev server is running for a project."""
    from preview import get_preview_port
    port = get_preview_port(project_id)
    return {"running": port is not None, "port": port}


# ---------------------------------------------------------------------------
# Refinement endpoint
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/refine")
async def refine(project_id: str, req: RefineRequest):
    """Apply a natural language refinement — streams SSE events."""
    project_dir = OUTPUT_BASE / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    async def event_stream():
        yield {
            "event": "refine_start",
            "data": json.dumps({"message": f"Applying: {req.instruction}"}),
        }

        try:
            result = None
            async for message in run_refinement_agent(
                output_dir=str(project_dir),
                instruction=req.instruction,
            ):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            yield {
                                "event": "log",
                                "data": json.dumps({"text": block.text}),
                            }
                        elif isinstance(block, ToolUseBlock):
                            tool_name = block.name
                            if tool_name in ("Write", "Edit"):
                                file_path = block.input.get("file_path", "")
                                rel_path = file_path
                                if file_path.startswith(str(project_dir)):
                                    rel_path = file_path[len(str(project_dir)):].lstrip("/")
                                yield {
                                    "event": "file_created",
                                    "data": json.dumps({"path": rel_path}),
                                }
                            yield {
                                "event": "tool_call",
                                "data": json.dumps({
                                    "tool": tool_name,
                                    "args": _safe_serialize(block.input),
                                }),
                            }
                elif isinstance(message, ResultMessage):
                    result = message

            # Post-refinement invariant restoration. The refinement agent uses
            # Write/Edit on TSX files; if it clobbered a shell/nav artifact OR
            # left the sidebar out of sync with newly-added routes, the app
            # renders a blank dashboard with no menus (reported as B-008/B-010:
            # "created a dashboard without any menus and functionalities").
            # Re-running the same idempotent passes the generation pipeline
            # uses restores shell.json's menu from nav-flow and reconciles any
            # stale route.
            try:
                from services.shell_menu_sync import sync_shell_menu
                from services.nav_route_reconcile_guard import reconcile_nav_routes
                sync_shell_menu(str(project_dir))
                reconcile_nav_routes(str(project_dir))
            except Exception as _e:  # noqa: BLE001
                # Non-fatal — the refinement itself already applied.
                logging.getLogger(__name__).warning(
                    "post-refinement invariant sync failed: %s", _e,
                )

            yield {
                "event": "refine_complete",
                "data": json.dumps({
                    "message": "Refinement complete",
                    "num_turns": result.num_turns if result else 0,
                    "cost_usd": result.total_cost_usd if result else 0,
                    "duration_ms": result.duration_ms if result else 0,
                }),
            }

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}),
            }

    return EventSourceResponse(event_stream(), ping=15)

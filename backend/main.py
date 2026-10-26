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

from services.windows_commands import resolve_tools_on_windows

resolve_tools_on_windows()  # Windows: npm is npm.cmd, so the build's install step could not start

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
from routers.app_mcp import router as app_mcp_router
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
from routers.phone_preview import router as phone_preview_router
from routers.phone_live import router as phone_live_router
from routers.deployments import router as deployments_router
from routers.domains import router as domains_router
from routers.verify import router as verify_router
from routers.generate import router as generate_router
from routers.blueprint_generate import router as blueprint_generate_router
from routers.templates import router as templates_router
from routers.project_templates import router as project_templates_router
from routers.discovery import router as discovery_router
from routers.data_model import router as data_model_router
from routers.rules import router as rules_router
from routers.business_rules import router as business_rules_router
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
from routers.incidents import router as incidents_router
from routers.notifications import router as notifications_router
from routers.sso import router as sso_router
from routers.mock_idp import router as mock_idp_router
from routers.audit import router as audit_router
from routers.attachments import router as attachments_router
from routers.exports import router as exports_router
from routers.files import router as files_router
from routers.environments import router as environments_router
from routers.webhooks import router as webhooks_router
from routers.visual_editor import router as visual_editor_router
from routers.react_editor import router as react_editor_router
from routers.modules import router as modules_router
from routers.export import router as export_router
from routers.ir import router as ir_router
from routers.design import router as design_router
from routers.brand import router as brand_router
from routers.brand_discovery import router as brand_discovery_router
from routers.usage import router as usage_router
from routers.drafts_room import router as drafts_room_router
from routers.admin import router as admin_router
from routers.admin_credits import router as admin_credits_router
from routers.admin_live import router as admin_live_router
from routers.features import router as features_router, admin_router as admin_features_router

# Middleware
from middleware.rate_limit import RateLimitMiddleware
from middleware.security_headers import SecurityHeadersMiddleware
from middleware.impersonation_audit import ImpersonationAuditMiddleware
from middleware.live_activity import LiveActivityMiddleware
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
# Inside the security headers, so the request id it sets is on the record.
app.add_middleware(ImpersonationAuditMiddleware)
app.add_middleware(LiveActivityMiddleware)
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
app.include_router(incidents_router)
app.include_router(project_events_router)
app.include_router(auth_router)
app.include_router(orgs_router)
app.include_router(brand_discovery_router)
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
app.include_router(phone_preview_router)
app.include_router(phone_live_router)
app.include_router(deployments_router)
app.include_router(app_mcp_router)
app.include_router(domains_router)
app.include_router(verify_router)
app.include_router(generate_router)
# §115 — generation through the Living Blueprint, registered beside the legacy
# chain rather than replacing it, so the old path keeps working while the new
# one is proven and a caller can see from the URL which engine it asked for.
app.include_router(blueprint_generate_router)
app.include_router(templates_router)
app.include_router(project_templates_router)
app.include_router(discovery_router)
app.include_router(data_model_router)
app.include_router(rules_router)
app.include_router(business_rules_router)
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
app.include_router(mock_idp_router)
app.include_router(audit_router)
app.include_router(files_router)
app.include_router(attachments_router)
app.include_router(exports_router)
app.include_router(environments_router)
app.include_router(webhooks_router)
app.include_router(visual_editor_router)
# The visual React editor — the Editor tab over a Blueprint's coded pages.
app.include_router(react_editor_router)
app.include_router(modules_router)
app.include_router(export_router)
app.include_router(ir_router)
app.include_router(design_router)
app.include_router(brand_router)
app.include_router(usage_router)
# The Drafts Room: Smith and a person work an idea out, study references and
# agree a draft before any app exists; agreeing creates and builds the app.
app.include_router(drafts_room_router)
app.include_router(admin_router)
app.include_router(admin_credits_router)
app.include_router(admin_live_router)
app.include_router(features_router)
app.include_router(admin_features_router)

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


@app.on_event("startup")
async def _stacks_on_signal():
    """`kill -USR1 <pid>` writes every thread's stack to stderr. A build step
    that made no call, ran no process and wrote no line for minutes could not
    be looked into without root (Ecom L1, 2026-10-11)."""
    import faulthandler
    import signal

    # POSIX only: Windows has neither the signal nor `faulthandler.register`,
    # and the missing attribute failed the whole startup there.
    if hasattr(faulthandler, "register") and hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)


@app.on_event("startup")
async def _close_orphaned_ledgers():
    """A run ledger left open by the process before this one is closed, so
    the panel does not read a killed build as running (`run_registry`)."""
    import logging

    from services import run_registry
    from services.project_paths import OUTPUT_ROOT
    closed = run_registry.close_orphaned_ledgers(OUTPUT_ROOT)
    if closed:
        logging.getLogger("forge.startup").info("[ledgers] closed %d left open by the last process: %s",
                                                len(closed), ", ".join(closed[:6]))
        await _tell_whose_turn_was_lost(list(run_registry.CLOSED_PATHS))
        run_registry.CLOSED_PATHS.clear()


async def _tell_whose_turn_was_lost(paths: list[str]) -> None:
    """THE PERSON IS TOLD (`services.lost_runs`). A turn the restart killed used
    to leave the chat on "Still working on it" for good (pcn4owv7, 2026-10-15)."""
    from services import lost_runs
    await lost_runs.tell(paths, "restarted")


@app.on_event("startup")
async def _start_lost_run_watch():
    """A ledger that stops pulsing while the platform is up — a worker died,
    not the container — is closed and its person told; see `services.lost_runs`."""
    from services import lost_runs
    app.state.lost_run_watch = asyncio.create_task(lost_runs.watch_forever())


@app.on_event("startup")
async def _start_dev_server_reaper():
    """Ends the app servers nobody is using — see `services.dev_servers`."""
    from services import dev_servers
    app.state.dev_server_reaper = asyncio.create_task(dev_servers.reaper())


@app.on_event("startup")
async def _start_domain_watch():
    """Checks the apps' addresses until they answer — see `services.deploy.domain_watch`."""
    from services.deploy import domain_watch
    app.state.domain_watch = asyncio.create_task(domain_watch.watch_forever())


@app.on_event("shutdown")
async def _shutdown():
    stop_all_previews()
    from services import phone_live
    phone_live.stop_all()
    if hasattr(app.state, "dev_server_reaper"):
        app.state.dev_server_reaper.cancel()
    if hasattr(app.state, "domain_watch"):
        app.state.domain_watch.cancel()
    if hasattr(app.state, "timer_scheduler"):
        await app.state.timer_scheduler.stop()




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






@app.get("/api/projects/{project_id}/asset")
async def serve_asset(project_id: str, path: str = Query(...)):
    """A picture or font from a project's PUBLIC folder: the legacy IR editor
    draws `/images/...` through here, from an `<img>` that cannot send a sign-in.

    It served any file under the project with no sign-in, the app's
    `.env.local` (database address, secrets, encryption key) included, and a
    published app's address names its project (2026-10-26). Only what the app
    publishes anyway is served now: a path inside `public/` (or `app/public/`),
    never a hidden file."""
    from fastapi.responses import FileResponse
    import mimetypes

    rel = Path(path)
    if rel.is_absolute() or not rel.parts or rel.parts[0] != "public" or any(
            part.startswith(".") for part in rel.parts):
        raise HTTPException(status_code=404, detail="File not found")
    project_dir = (OUTPUT_BASE / project_id).resolve()
    for base in (project_dir, project_dir / "app"):
        public = (base / "public").resolve()
        file_path = (base / rel).resolve()
        if file_path.is_relative_to(public) and file_path.is_relative_to(project_dir) and file_path.is_file():
            media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            return FileResponse(file_path, media_type=media_type)
    raise HTTPException(status_code=404, detail="File not found")




# ---------------------------------------------------------------------------
# Preview endpoints
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# Refinement endpoint
# ---------------------------------------------------------------------------


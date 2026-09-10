"""Application configuration loaded from environment variables."""

import os
import sys
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://tentoroforge:tentoroforge@localhost:5432/tentoroforge",
)

# For Alembic (sync driver)
DATABASE_URL_SYNC = DATABASE_URL.replace("+asyncpg", "")

# ---------------------------------------------------------------------------
# Auth / JWT
# ---------------------------------------------------------------------------

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_EXPIRE_MINUTES", "60"))
JWT_REFRESH_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "7"))

# Backwards compat — old env var
_jwt_hours = os.getenv("JWT_EXPIRE_HOURS")
if _jwt_hours:
    JWT_ACCESS_EXPIRE_MINUTES = int(_jwt_hours) * 60

# Account lockout
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
LOCKOUT_DURATION_MINUTES = int(os.getenv("LOCKOUT_DURATION_MINUTES", "15"))

# ---------------------------------------------------------------------------
# AI / Anthropic
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# Redis (optional — used for caching and job queues)
# ---------------------------------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ---------------------------------------------------------------------------
# Email (optional — SendGrid or SMTP)
# ---------------------------------------------------------------------------

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "noreply@tentoroforge.dev")

# ---------------------------------------------------------------------------
# S3 / Object Storage (optional)
# ---------------------------------------------------------------------------

S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

# ---------------------------------------------------------------------------
# Sentry (optional — error tracking)
# ---------------------------------------------------------------------------

SENTRY_DSN = os.getenv("SENTRY_DSN", "")

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

# THE EDITOR SATURATES ITS OWN BUDGET AT 120/min.
# The visual editor's persister debounces autosave at 500ms, which is exactly
# 120 writes a minute at a steady edit rate — the entire old allowance, before
# the schema/theme/preview-data reads the same page issues. The observed result
# was a red "COULDN'T SAVE — src/theme/tokens.custom.json -> HTTP 429" banner
# with the user's changes left unsaved, i.e. a rate limit for abusive clients
# was silently costing a legitimate one their work.
# 600/min with a 100 burst leaves the editor headroom while still bounding a
# genuinely hostile caller; the client also retries a 429 once (see
# frontend/src/lib/persistence.ts) so a brief overrun never surfaces at all.
RATE_LIMIT_REQUESTS_PER_MINUTE = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "600"))
RATE_LIMIT_BURST = int(os.getenv("RATE_LIMIT_BURST", "100"))

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

APP_ENV = os.getenv("APP_ENV", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:6501,http://127.0.0.1:6501",
).split(",")

# ---------------------------------------------------------------------------
# Fidelity mode (Task 36)
# ---------------------------------------------------------------------------

# When enabled (default), the schema-mode pipeline runs the design_compiler
# step and the schema-prompt builder injects design-spec + gold-example
# context into the LLM prompt. Setting FIDELITY_MODE_ENABLED=false reverts
# to the pre-fidelity prompt (defaultTokens + structural-only guidance).
FIDELITY_MODE_ENABLED = os.getenv("FIDELITY_MODE_ENABLED", "true").strip().lower() not in {"false", "0", "no", "off", ""}

# ---------------------------------------------------------------------------
# Fidelity render loop (Phase 12.5 + 13)
# ---------------------------------------------------------------------------

# Render service URL (where the backend reaches the Playwright-driven service)
RENDER_SERVICE_URL = os.getenv("RENDER_SERVICE_URL", "http://localhost:6502")

# Scaffold runtime URL (where the render service drives Playwright at)
RENDER_SCAFFOLD_URL = os.getenv("RENDER_SCAFFOLD_URL", "http://localhost:6503")

# Per-render timeout, ms
RENDER_TIMEOUT_MS = int(os.getenv("RENDER_TIMEOUT_MS", "15000"))

# Phase 12.5: render-only feature flag (Preview tab + debug endpoints)
FIDELITY_RENDER_ENABLED = os.getenv("FIDELITY_RENDER_ENABLED", "true").strip().lower() not in {"false", "0", "no", "off", ""}

# Phase 13: single-shot scoring feature flag (CritiquePanel + score endpoint)
FIDELITY_SCORING_ENABLED = os.getenv("FIDELITY_SCORING_ENABLED", "true").strip().lower() not in {"false", "0", "no", "off", ""}

# ---------------------------------------------------------------------------
# Fidelity loop + reference grounding (Phase 14 + 15)
# ---------------------------------------------------------------------------

# Phase 14: closed loop with patch agent (default ON — set FIDELITY_LOOP_ENABLED=false to disable per-generation)
FIDELITY_LOOP_ENABLED = os.getenv("FIDELITY_LOOP_ENABLED", "true").strip().lower() not in {"false", "0", "no", "off", ""}

# Phase 15: reference grounding bank (default true once seeded)
REFERENCE_GROUNDING_ENABLED = os.getenv("REFERENCE_GROUNDING_ENABLED", "true").strip().lower() not in {"false", "0", "no", "off", ""}

# /api/_debug/fidelity-stats endpoint
FIDELITY_STATS_ENABLED = os.getenv("FIDELITY_STATS_ENABLED", "true").strip().lower() not in {"false", "0", "no", "off", ""}

# Per-page wall-clock budget for the fidelity loop, ms
FIDELITY_LOOP_PAGE_TIMEOUT_MS = int(os.getenv("FIDELITY_LOOP_PAGE_TIMEOUT_MS", "90000"))

# Project-wide cost cap for the fidelity loop, USD
FIDELITY_LOOP_PROJECT_COST_CAP_USD = float(os.getenv("FIDELITY_LOOP_PROJECT_COST_CAP_USD", "5.0"))

# Max patch iterations per page (excluding iter 0 baseline)
FIDELITY_LOOP_MAX_ITERATIONS = int(os.getenv("FIDELITY_LOOP_MAX_ITERATIONS", "3"))

# Page-level concurrency through the loop (matches render-service browser pool)
FIDELITY_LOOP_CONCURRENCY = int(os.getenv("FIDELITY_LOOP_CONCURRENCY", "4"))

# ---------------------------------------------------------------------------
# Production validation — fail fast on missing critical env vars
# ---------------------------------------------------------------------------

if APP_ENV == "production":
    _missing = []
    if SECRET_KEY == "dev-secret-change-in-production":
        _missing.append("SECRET_KEY")
    if not ANTHROPIC_API_KEY:
        _missing.append("ANTHROPIC_API_KEY")
    if _missing:
        logger.critical("Missing required environment variables in production: %s", ", ".join(_missing))
        sys.exit(1)

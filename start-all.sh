#!/usr/bin/env bash
# Start all four Tentoroforge services in the background, log to /tmp,
# print URLs at the end. Idempotent — kills any prior instance on each
# port before starting.

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
NEXT_BIN="$ROOT/node_modules/.bin/next"

# Raise the Claude Code CLI output cap (default 32000) that the backend's
# claude_agent_sdk subprocesses inherit. Schema/page/component agents can emit
# large files and otherwise hit "response exceeded the 32000 output token
# maximum". 64000 is the practical ceiling for the Sonnet models in use; a
# single agent legitimately needing more is a signal to chunk its work instead.
export CLAUDE_CODE_MAX_OUTPUT_TOKENS="${CLAUDE_CODE_MAX_OUTPUT_TOKENS:-64000}"

# Master verify flag — enables the Verify & Fix chip on the completion
# card + the full self-verify pipeline (interaction runner + journey
# gate + autofix dispatcher). One switch, whole feature. Override with
# FORGE_SELF_VERIFY=0 to hide.
export FORGE_SELF_VERIFY="${FORGE_SELF_VERIFY:-1}"

# Point the backend at the local Playwright sidecar (Fastify @ :6600).
# Default (from services/forge_verify_client.py) is "http://forge-verify:6600"
# — the docker-compose hostname, which won't resolve on a dev laptop.
# Setting this makes the interaction pass actually run locally instead
# of falling back to "runner unreachable".
export FORGE_VERIFY_URL="${FORGE_VERIFY_URL:-http://localhost:6600}"

# JV-27/A1 — Preview base URL Playwright loads for interaction + journey
# passes. Default in code is "http://backend:6500" (docker-compose hostname)
# so the sidecar-in-a-container can reach us — but that hostname doesn't
# resolve on a dev laptop and turns every navigation into
# net::ERR_NAME_NOT_RESOLVED, which gets counted as a runtime fault.
export FORGE_INTERNAL_BASE_URL="${FORGE_INTERNAL_BASE_URL:-http://localhost:6500}"

# V&F 2.0 (self-healing generator) — classify each Playwright fault into
# a taxonomy, run deterministic handlers for known classes, dispatch the
# rest to Smith with a curated context slice, guard rounds with git
# snapshot + auto-revert on regression. Additive — the legacy 4-handler
# path still runs alongside; the v2 output lands in row.report["autofix_v2"].
# Set FORGE_AUTOFIX_V2=0 to disable.
export FORGE_AUTOFIX_V2="${FORGE_AUTOFIX_V2:-1}"
# Whole-run Smith turn budget across all Smith-dispatched faults (default 15).
export FORGE_AUTOFIX_SMITH_BUDGET="${FORGE_AUTOFIX_SMITH_BUDGET:-15}"

# Resolve the python that has the backend deps installed. Prefer the
# system framework Python that has been used all session; fall back to
# whatever python3 is on PATH.
PYTHON="${PYTHON:-/Library/Frameworks/Python.framework/Versions/3.11/bin/python3}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3)"
fi

free_port() {
  local port=$1
  local pid
  pid="$(lsof -tnP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$pid" ]; then
    echo "  freeing port $port (killing pid $pid)"
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
  fi
}

wait_ready() {
  local url=$1
  local label=$2
  local timeout=${3:-60}
  local i=0
  while [ "$i" -lt "$timeout" ]; do
    if curl -sf -m 1 -o /dev/null "$url" 2>/dev/null; then
      echo "  ✓ $label ready"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  echo "  ⚠ $label did not become ready in ${timeout}s — check log"
  return 1
}

echo "▶ Stopping any existing services on 6500–6503, 6600…"
free_port 6500
free_port 6501
free_port 6502
free_port 6503
free_port 6600

echo
echo "▶ Starting backend (uvicorn, port 6500)…"
cd "$ROOT/backend"
# Load API key from .env if present
if [ -f .env ]; then set -a; source .env; set +a; fi
# NO --reload: generation runs as a long-lived in-process asyncio task. With
# --reload, ANY file change under backend/ (a .pyc written by a lazy import
# during the run, an editor save, a tool touching a file) makes watchfiles
# restart uvicorn mid-generation — the event loop is torn down, the planner task
# dies, the SSE drops, and the app "never builds". Reproduced live. Run without
# reload so a generation can't be killed under it. For hot-reload during backend
# dev, start uvicorn manually with --reload in a separate shell (no gen running).
nohup "$PYTHON" -m uvicorn main:app --port 6500 --host 0.0.0.0 \
  > /tmp/tentoroforge-backend.log 2>&1 &
disown
echo "  pid $! → /tmp/tentoroforge-backend.log"

echo "▶ Starting render-service (port 6502)…"
nohup "$PYTHON" -m services.render_service \
  > /tmp/tentoroforge-render-service.log 2>&1 &
disown
echo "  pid $! → /tmp/tentoroforge-render-service.log"

echo "▶ Starting render-scaffold (Next.js, port 6503)…"
cd "$ROOT/apps/render-scaffold"
NODE_OPTIONS="--max-old-space-size=4096" nohup "$NEXT_BIN" dev -p 6503 \
  > /tmp/tentoroforge-scaffold.log 2>&1 &
disown
echo "  pid $! → /tmp/tentoroforge-scaffold.log"

echo "▶ Starting frontend (Next.js, port 6501)…"
cd "$ROOT/frontend"
nohup "$NEXT_BIN" dev -p 6501 \
  > /tmp/tentoroforge-frontend.log 2>&1 &
disown
echo "  pid $! → /tmp/tentoroforge-frontend.log"

echo "▶ Starting forge-verify (Playwright sidecar, port 6600)…"
cd "$ROOT/docker/forge-verify"
# tsx dev-mode — no build step; auto-reload on file change. Chromium
# comes from playwright's default cache (~/Library/Caches/ms-playwright).
# If npm install / npx playwright install chromium hasn't been run in
# this dir, the server will crash-loop; check the log if healthz fails.
#
# MAX_CONTEXTS=6 (up from prod default 3) — 93-interaction runs on a
# real localhost app take 10+ min sequentially; 6 parallel Chromium
# contexts cut wall-clock ~4-5×. Overridable via env if this pegs CPU.
nohup env PORT=6600 FORGE_VERIFY_MAX_CONTEXTS="${FORGE_VERIFY_MAX_CONTEXTS:-6}" npm run dev \
  > /tmp/tentoroforge-forge-verify.log 2>&1 &
disown
echo "  pid $! → /tmp/tentoroforge-forge-verify.log"

echo
echo "▶ Waiting for services to become reachable…"
wait_ready "http://localhost:6500/health"  "backend (:6500)"        30
wait_ready "http://localhost:6502/health"  "render-service (:6502)" 30
wait_ready "http://localhost:6503/"        "render-scaffold (:6503)" 90
wait_ready "http://localhost:6501/"        "frontend (:6501)"        90
wait_ready "http://localhost:6600/healthz" "forge-verify (:6600)"    30

cat <<'EOF'

────────────────────────────────────────────────────────────────────
All services up. Useful URLs:

  Backend API ………………… http://localhost:6500
  Frontend (editor) …… http://localhost:6501
  Render service ………… http://localhost:6502
  Render scaffold ……… http://localhost:6503
  Forge-verify (SV) …… http://localhost:6600

  Today's project (task tracker):
    http://localhost:6503/p/genmetrics-1778439719/tasks/list
    http://localhost:6503/p/genmetrics-1778439719/tasks/detail
    http://localhost:6503/p/genmetrics-1778439719/users/list

Logs:
  tail -f /tmp/tentoroforge-{backend,frontend,scaffold,render-service,forge-verify}.log

To stop everything:
  pkill -9 -f "uvicorn main:app --port 6500"
  pkill -9 -f "services.render_service"
  pkill -9 -f "next dev -p 6501"
  pkill -9 -f "next dev -p 6503"
  pkill -9 -f "docker/forge-verify"
────────────────────────────────────────────────────────────────────
EOF

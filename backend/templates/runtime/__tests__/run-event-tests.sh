#!/usr/bin/env bash
# Runs the event-layer runtime tests (R1/R2/R3):
#   event-cron.test.mts — pure cron matcher (node type stripping, no build)
#   event-bus.test.mts  — trigger matching + emit_event node + wait_for_event
#                         pause/resume through the real engine (esbuild
#                         bundle, since engine.ts imports ../feel-lite)
# Exits non-zero on any assertion failure.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

node --experimental-strip-types "$DIR/event-cron.test.mts"

# esbuild lives in the repo root node_modules; fall back to npx.
BIN="$(cd "$DIR/../../../.." && pwd)/node_modules/.bin"
if [ -x "$BIN/esbuild" ]; then
  ESBUILD="$BIN/esbuild"
else
  ESBUILD="npx esbuild"
fi
$ESBUILD "$DIR/event-bus.test.mts" --bundle --platform=node --format=esm \
  --external:fs --external:path --outfile=/tmp/event-bus-test.mjs >/dev/null 2>&1
node /tmp/event-bus-test.mjs

#!/usr/bin/env bash
# Runs the runtime rule-set test. Bundles with esbuild (engine imports ../feel-lite)
# then executes with node. Exits non-zero on assertion failure.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$(cd "$DIR/../../../../.." && pwd)/node_modules/.bin"
"$BIN/esbuild" "$DIR/rule-set.test.mts" --bundle --platform=node --format=esm \
  --external:fs --external:path --outfile=/tmp/rule-set-test.mjs >/dev/null 2>&1
node /tmp/rule-set-test.mjs

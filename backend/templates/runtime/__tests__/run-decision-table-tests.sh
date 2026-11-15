#!/usr/bin/env bash
# Runs the decision-table tests. Bundles with esbuild (engine imports ../feel-lite)
# then executes with node. Exits non-zero on assertion failure.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

# Four levels up is the repo root: __tests__ -> runtime -> templates -> backend.
# It was five, which resolved outside the repo entirely; combined with the
# bundle step discarding its own stderr, the script then exited on `set -e`
# having printed nothing, and a silent no-op is indistinguishable from a pass.
BIN="$(cd "$DIR/../../../.." && pwd)/node_modules/.bin"
if [ -x "$BIN/esbuild" ]; then
  ESBUILD="$BIN/esbuild"
else
  ESBUILD="npx esbuild"
fi
$ESBUILD "$DIR/decision-table.test.mts" --bundle --platform=node --format=esm \
  --external:fs --external:path --outfile=/tmp/decision-table-test.mjs >/dev/null
node /tmp/decision-table-test.mjs

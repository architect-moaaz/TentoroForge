#!/usr/bin/env bash
# Business rules are in force wherever a record is written, and a rule changed
# on disk is in force without a restart. Bundled with esbuild (the engine
# imports ../feel-lite), then run with node. Non-zero on any failed assertion.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$(cd "$DIR/../../../.." && pwd)/node_modules/.bin"
if [ -x "$BIN/esbuild" ]; then ESBUILD="$BIN/esbuild"; else ESBUILD="npx esbuild"; fi
for t in rules-are-enforced rules-reload; do
  $ESBUILD "$DIR/$t.test.mts" --bundle --platform=node --format=esm \
    --external:fs --external:path --external:node:fs --external:node:os --external:node:path \
    --outfile="/tmp/forge-$t-test.mjs" --log-level=error
  node "/tmp/forge-$t-test.mjs"
done

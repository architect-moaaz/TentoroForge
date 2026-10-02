#!/usr/bin/env bash
# The Data Engine's query resolver: measures by dimensions, scoped to the reader.
# Runs the SHIPPED data-engine.ts against a fake db that really groups.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-transform-types --no-warnings "$DIR/resolve-query.test.mts"
# What a lookup step publishes, and a FEEL count over it (bundled: feel-lite
# imports without extensions).
BIN="$(cd "$DIR/../../../.." && pwd)/node_modules/.bin"
ESBUILD="$BIN/esbuild"; [ -x "$ESBUILD" ] || ESBUILD="npx esbuild"
$ESBUILD "$DIR/query-result.test.mts" --bundle --platform=node --format=esm --outfile=/tmp/query-result-test.mjs --log-level=error
node /tmp/query-result-test.mjs

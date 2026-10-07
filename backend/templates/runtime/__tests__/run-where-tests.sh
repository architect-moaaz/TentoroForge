#!/usr/bin/env bash
# where-makes-a-comparison.test.mts — the SHIPPED workflows/index.ts, its
# imports stubbed. No bundler: node's own type stripping runs the source.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/where-makes-a-comparison.test.mts"

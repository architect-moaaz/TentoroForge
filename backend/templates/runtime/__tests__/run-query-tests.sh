#!/usr/bin/env bash
# The Data Engine's query resolver: measures by dimensions, scoped to the reader.
# Runs the SHIPPED data-engine.ts against a fake db that really groups.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-transform-types --no-warnings "$DIR/resolve-query.test.mts"

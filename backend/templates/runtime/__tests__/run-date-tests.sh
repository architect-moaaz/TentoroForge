#!/usr/bin/env bash
# a-date-from-a-form-is-a-date.test.mts — the SHIPPED data-engine.ts with REAL
# drizzle column types and a fake database that serialises like the driver.
#   FORGE_NODE_MODULES  a node_modules with drizzle-orm (any generated app's)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$FORGE_NODE_MODULES/drizzle-orm/index.js" ]; then
  echo "SKIP date tests: set FORGE_NODE_MODULES to a generated app's node_modules"
  exit 0
fi
node --experimental-transform-types --no-warnings "$DIR/a-date-from-a-form-is-a-date.test.mts"

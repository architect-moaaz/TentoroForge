#!/usr/bin/env bash
# seed-applies-an-import-before-the-demo-rows.test.mts — the SHIPPED seed.ts
# with the database stubbed. No bundler: node's own type stripping runs it.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/seed-applies-an-import-before-the-demo-rows.test.mts"

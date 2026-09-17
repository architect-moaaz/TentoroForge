#!/usr/bin/env bash
# seed-never-inserts-a-readable-credential.test.mts — the SHIPPED seed.ts with
# the database stubbed. No bundler: node's own type stripping runs the source.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/seed-never-inserts-a-readable-credential.test.mts"

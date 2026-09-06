#!/usr/bin/env bash
# seed-reads-the-projected-file-in-rounds.test.mts — the SHIPPED seed.ts with
# the database stubbed. No bundler: node's own type stripping runs the source.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/seed-reads-the-projected-file-in-rounds.test.mts"

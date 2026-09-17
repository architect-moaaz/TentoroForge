#!/usr/bin/env bash
# seed-applies-the-account-roster.test.mts — the SHIPPED seed.ts with the
# database stubbed. No bundler: node's own type stripping runs the source.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/seed-applies-the-account-roster.test.mts"

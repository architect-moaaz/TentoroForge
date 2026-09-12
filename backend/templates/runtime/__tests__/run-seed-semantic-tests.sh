#!/usr/bin/env bash
# seed-coerces-bad-dates-and-resolves-semantic-fks.test.mts — the SHIPPED
# seed.ts with the database stubbed; verifies bad-date coercion + semantic FK.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/seed-coerces-bad-dates-and-resolves-semantic-fks.test.mts"

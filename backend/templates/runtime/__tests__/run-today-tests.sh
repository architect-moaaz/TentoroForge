#!/usr/bin/env bash
# The SHIPPED engine: $today is YYYY-MM-DD; date columns kept as text get text.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/today-is-a-calendar-date.test.mts"

#!/usr/bin/env bash
# a-month-on-is-a-calendar-month.test.mts — the SHIPPED feel-lite: P1M/P1Y are
# calendar months and years; a duration that is not one is refused.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-transform-types --no-warnings "$DIR/a-month-on-is-a-calendar-month.test.mts"

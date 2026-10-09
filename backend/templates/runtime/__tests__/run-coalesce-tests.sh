#!/usr/bin/env bash
# a-value-or-else-another.test.mts — `??` in the SHIPPED feel-lite formula language.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-transform-types --no-warnings "$DIR/a-value-or-else-another.test.mts"

#!/usr/bin/env bash
# a-decision-cell-can-be-a-word.test.mts — the SHIPPED rules/engine.ts and
# feel-lite: a decision table's unquoted word output is that word.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-transform-types --no-warnings "$DIR/a-decision-cell-can-be-a-word.test.mts"

#!/usr/bin/env bash
# a-decision-output-is-what-it-says.test.mts — the SHIPPED decision-table,
# rules engine and workflow decision step: an output cell is what it says,
# and a record's field takes one value.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-transform-types --no-warnings "$DIR/a-decision-output-is-what-it-says.test.mts"

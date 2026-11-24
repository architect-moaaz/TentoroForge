#!/usr/bin/env bash
# a-formula-reads-a-list-item-by-position.test.mts — the SHIPPED feel-lite.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-transform-types --no-warnings "$DIR/a-formula-reads-a-list-item-by-position.test.mts"

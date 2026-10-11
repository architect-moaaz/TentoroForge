#!/usr/bin/env bash
# The SHIPPED webhook route verifies, dedupes and refuses.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-webhook-is-verified-before-it-is-believed.test.mts"

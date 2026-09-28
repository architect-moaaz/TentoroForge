#!/usr/bin/env bash
# for-each-carries-each-id-forward.test.mts — the SHIPPED workflows/index.ts
# runs steps once per item, each new id carried to the next step.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/for-each-carries-each-id-forward.test.mts"

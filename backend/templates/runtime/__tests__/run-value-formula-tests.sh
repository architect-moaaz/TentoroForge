#!/usr/bin/env bash
# a-formula-as-a-value-is-worked-out.test.mts — the SHIPPED workflows/index.ts
# `_resolveRef` with the SHIPPED feel-lite: a sole `{{formula}}` is evaluated.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-transform-types --no-warnings "$DIR/a-formula-as-a-value-is-worked-out.test.mts"

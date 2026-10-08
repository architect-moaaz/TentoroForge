#!/usr/bin/env bash
# a-default-quantity-is-a-quantity.test.mts — the SHIPPED engine.ts reads
# `{{a ?? b}}` fallbacks in a set_variable step, with the real FEEL evaluator.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-transform-types --no-warnings "$DIR/a-default-quantity-is-a-quantity.test.mts"

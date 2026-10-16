#!/usr/bin/env bash
# A sealed number is read by its readers and totalled by the engine.
# Runs the SHIPPED data-engine.ts against a fake db that really groups.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-transform-types --no-warnings "$DIR/a-sealed-number-is-read-and-totalled.test.mts"

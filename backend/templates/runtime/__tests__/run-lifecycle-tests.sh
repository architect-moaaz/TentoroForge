#!/usr/bin/env bash
# a-record-moves-only-as-its-life-cycle-allows.test.mts — the SHIPPED
# workflows/index.ts life-cycle guard, with its app-only imports stubbed.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-record-moves-only-as-its-life-cycle-allows.test.mts"

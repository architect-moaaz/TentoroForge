#!/usr/bin/env bash
# insert-binds-what-the-driver-takes.test.mts — the SHIPPED workflows/index.ts
# `_finalizeInsert`, with its app-only imports stubbed by the module hook.
# No bundler: node's own type stripping runs the source directly.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/insert-binds-what-the-driver-takes.test.mts"

#!/usr/bin/env bash
# a-person-changes-their-own-password.test.mts — the SHIPPED workflows/index.ts
# `set_password` action, with its app-only imports stubbed by the module hook.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-person-changes-their-own-password.test.mts"

#!/usr/bin/env bash
# a-read-that-failed-is-said.test.mts — the SHIPPED sdk/server.ts prints and
# reports a read that failed instead of returning an empty answer in silence.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-read-that-failed-is-said.test.mts"

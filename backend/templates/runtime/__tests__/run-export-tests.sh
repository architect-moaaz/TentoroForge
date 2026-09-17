#!/usr/bin/env bash
# export-answers-only-who-may-read.test.mts — the SHIPPED api-export route with
# the database, the session and both projections stubbed.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/export-answers-only-who-may-read.test.mts"

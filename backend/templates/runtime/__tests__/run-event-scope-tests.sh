#!/usr/bin/env bash
# The SHIPPED workflows/index.ts `_scoped`: an event's run is the application's own; a person's run is scoped.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/an-event-run-is-the-applications-own.test.mts"

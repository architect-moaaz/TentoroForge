#!/usr/bin/env bash
# A wait is a pause the clock ends; a schedule is read in its own zone.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-wait-is-a-pause-not-a-sleep.test.mts"
node --experimental-strip-types --no-warnings "$DIR/the-clock-reads-the-zone.test.mts"

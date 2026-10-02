#!/usr/bin/env bash
# reporter-sends-names-never-values.test.mts — the SHIPPED error_reporter.ts,
# with its incident-map import stubbed by the module hook. No bundler: node's
# own type stripping runs the source directly.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/reporter-sends-names-never-values.test.mts"

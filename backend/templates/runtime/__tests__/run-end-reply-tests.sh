#!/usr/bin/env bash
# a-run-answers-what-its-end-declares.test.mts — the SHIPPED engine.ts fills an
# end's `reply` and `redirect` for the page that ran it; a refused end never redirects.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-run-answers-what-its-end-declares.test.mts"

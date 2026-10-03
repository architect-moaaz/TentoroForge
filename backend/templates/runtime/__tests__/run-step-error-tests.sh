#!/usr/bin/env bash
# a-step-that-answers-an-error-failed.test.mts — the SHIPPED engine logs a
# step whose handler answered { error } as failed.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-step-that-answers-an-error-failed.test.mts"

#!/usr/bin/env bash
# a-workflow-runs-a-business-rule.test.mts — the SHIPPED workflow engine runs
# a business rule of the app as a decision step, and branches on it.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-transform-types --no-warnings "$DIR/a-workflow-runs-a-business-rule.test.mts"

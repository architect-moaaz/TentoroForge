#!/usr/bin/env bash
# The SHIPPED audit.ts chains, verifies and bounds the trail.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/every-change-is-on-the-record.test.mts"

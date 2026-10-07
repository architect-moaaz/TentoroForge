#!/usr/bin/env bash
# a-person-lands-on-their-own-page.test.mts — the SHIPPED lib/landing.ts, its
# account module stubbed. No bundler: node's own type stripping runs the source.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-person-lands-on-their-own-page.test.mts"

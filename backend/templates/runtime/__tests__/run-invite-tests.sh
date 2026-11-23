#!/usr/bin/env bash
# a-login-for-someone-else-is-made-by-the-process.test.mts — the SHIPPED
# workflows/index.ts `invite_account` handler over a stubbed database and mailer.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-login-for-someone-else-is-made-by-the-process.test.mts"
node --experimental-strip-types --no-warnings "$DIR/a-persons-role-is-changed-by-the-process.test.mts"

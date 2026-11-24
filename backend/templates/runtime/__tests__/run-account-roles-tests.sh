#!/usr/bin/env bash
# only-the-account-roles-get-the-account-record.test.mts — the SHIPPED seed.ts
# with the database stubbed, with and without `security.accountRoles`.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
ACCOUNT_ROLES_DECLARED=1 node --experimental-strip-types --no-warnings "$DIR/only-the-account-roles-get-the-account-record.test.mts"
ACCOUNT_ROLES_DECLARED=0 node --experimental-strip-types --no-warnings "$DIR/only-the-account-roles-get-the-account-record.test.mts"
ACCOUNT_ROLES_DECLARED=1 node --experimental-strip-types --no-warnings "$DIR/a-signup-makes-the-account-record-only-for-its-roles.test.mts"
ACCOUNT_ROLES_DECLARED=0 node --experimental-strip-types --no-warnings "$DIR/a-signup-makes-the-account-record-only-for-its-roles.test.mts"

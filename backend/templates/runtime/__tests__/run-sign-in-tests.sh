#!/usr/bin/env bash
# The SHIPPED lib/sign-in.ts: providers by name, domains, roles from claims,
# magic tokens as digests; and the sign-in cookies under the app's prefix.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-person-signs-in-the-way-the-policy-says.test.mts"

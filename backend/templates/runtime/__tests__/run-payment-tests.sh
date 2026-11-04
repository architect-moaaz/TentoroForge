#!/usr/bin/env bash
# The SHIPPED payments modules: every gateway's signature and events, its API
# calls, units, routing, the ledger's moves, subscription access, the stand-in.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-payment-is-believed-only-from-a-signed-event.test.mts"
node --experimental-strip-types --no-warnings "$DIR/every-gateway-is-believed-only-from-itself.test.mts"

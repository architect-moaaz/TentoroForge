#!/usr/bin/env bash
# The SHIPPED payments modules: Stripe's signature and events, units, the stand-in.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-payment-is-believed-only-from-a-signed-event.test.mts"

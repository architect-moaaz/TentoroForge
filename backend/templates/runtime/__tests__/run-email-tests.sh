#!/usr/bin/env bash
# send-email-says-when-it-did-not-send.test.mts — the SHIPPED
# workflows/index.ts `send_email` handler against a stubbed provider, a
# stubbed secret resolver and the projected connection map. Checks the four
# outcomes a step can have and that only the connected one claims a send.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/send-email-says-when-it-did-not-send.test.mts"

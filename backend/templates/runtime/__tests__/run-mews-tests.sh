#!/usr/bin/env bash
# a-step-reaches-mews-the-way-mews-reads-it.test.mts — the SHIPPED http_call
# handler signs a Mews call in its body, on the demo or live host.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-step-reaches-mews-the-way-mews-reads-it.test.mts"

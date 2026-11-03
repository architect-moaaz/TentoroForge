#!/usr/bin/env bash
# a-step-reaches-mews-the-way-mews-reads-it.test.mts — the SHIPPED http_call
# handler signs a Mews call in its body, on the demo or live host;
# a-mews-call-reaches-the-property-it-names.test.mts — with the token of the
# property a step names, and only the administrator manages properties;
# a-stay-is-found-in-mews.test.mts — a desk finds a stay by number, name or room.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-step-reaches-mews-the-way-mews-reads-it.test.mts"
node --experimental-strip-types --no-warnings "$DIR/a-mews-call-reaches-the-property-it-names.test.mts"
node --experimental-strip-types --no-warnings "$DIR/a-stay-is-found-in-mews.test.mts"

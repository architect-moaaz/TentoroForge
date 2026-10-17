#!/usr/bin/env bash
# The SHIPPED /api/read/<op> route answers each of a page's reads over HTTP.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/the-reads-a-page-makes-are-answered-over-http.test.mts"

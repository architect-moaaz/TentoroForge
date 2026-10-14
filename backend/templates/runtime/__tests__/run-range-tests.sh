#!/usr/bin/env bash
# The SHIPPED _buildWhere ANDs several comparisons on one field (a range).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/a-filter-can-hold-a-range.test.mts"

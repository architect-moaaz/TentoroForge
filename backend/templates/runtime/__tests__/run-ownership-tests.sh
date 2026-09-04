#!/usr/bin/env bash
# Row-level scoping tests for the data engine.
#
# Two steps, one fixture. The real projection renders the ownership manifest
# from ownership-fixture.blueprint.json; the node test then runs the SHIPPED
# data-engine.ts against it with drizzle and the db stubbed out. Nothing here
# is a transcription of the code under test.
#
# No bundler: node's own type stripping runs the .ts/.mts sources directly, and
# a module resolve hook supplies the per-app modules a generated app would have.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$(cd "$DIR/../../.." && pwd)"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

PYTHONPATH="$BACKEND" python3 -c "
import json, sys
from services.blueprint.projection import project_ownership_rules
doc = json.load(open('$DIR/ownership-fixture.blueprint.json'))
print(project_ownership_rules(doc, '$OUT'), file=sys.stderr)
"

# --experimental-transform-types, not --experimental-strip-types: feel-lite's
# tokenizer declares a TypeScript `enum`, which has to be transformed rather
# than erased. Transform mode is a superset, so both tests run under it.
node --experimental-transform-types "$DIR/ownership-scope.test.mts" "$OUT/src/lib/ownership-rules.ts"
node --experimental-transform-types "$DIR/row-access-sql.test.mts"

#!/usr/bin/env bash
# The runtime tests no other runner ran — record inputs (the signed-in person
# as a record), required inputs, conditions, decisions, joins, the query
# builder. Each is plain `node` with type stripping.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
for t in bridge-unresolved-route-id build-where condition-log decision dry-run-stand-in join-barrier \
         notification-reaches-the-person-it-names record-inputs required-inputs resolve-aggregate; do
  node --experimental-strip-types --no-warnings "$DIR/$t.test.mts"
done

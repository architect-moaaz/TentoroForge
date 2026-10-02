#!/usr/bin/env bash
# Embedding fields on a real Postgres with pgvector: fill on write, rank on
# read, scoped, vectors never returned. Runs the SHIPPED data-engine.ts and
# embeddings.ts against real drizzle; only the embedding model is faked.
#
#   VECTOR_TEST_DATABASE_URL  a Postgres with pgvector available, e.g.
#       docker run -d -p 5499:5432 -e POSTGRES_PASSWORD=postgres \
#         -e POSTGRES_DB=vectortest pgvector/pgvector:pg16
#       → postgresql://postgres:postgres@localhost:5499/vectortest
#   FORGE_NODE_MODULES        a node_modules with drizzle-orm and postgres
#                             (any generated app's)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -z "$VECTOR_TEST_DATABASE_URL" ] || [ ! -f "$FORGE_NODE_MODULES/drizzle-orm/index.js" ]; then
  echo "SKIP resolve-similar: set VECTOR_TEST_DATABASE_URL and FORGE_NODE_MODULES (see this script)"
  exit 0
fi
node --experimental-transform-types --no-warnings "$DIR/resolve-similar.test.mts"

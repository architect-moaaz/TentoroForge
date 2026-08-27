#!/usr/bin/env bash
# Runs the ai_identify_product handler test. Bundles ai-identify-product.test.mts
# with esbuild, aliasing the two dynamic-imported modules (@/lib/integrations/resolver
# and @anthropic-ai/sdk) to the local stubs so the handler runs end-to-end without
# a real SDK or key. Exits non-zero on assertion failure.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$(cd "$DIR/../../../.." && pwd)/node_modules/.bin"
"$BIN/esbuild" "$DIR/ai-identify-product.test.mts" \
  --bundle --platform=node --format=esm \
  --alias:@/lib/integrations/resolver="$DIR/ai-stub-resolver.mts" \
  --alias:@anthropic-ai/sdk="$DIR/ai-stub-anthropic.mts" \
  --outfile=/tmp/ai-identify-test.mjs >/dev/null 2>&1
node /tmp/ai-identify-test.mjs

#!/usr/bin/env bash
# The fixed half of the native app, without a device: the pure logic under plain
# node (no react-native, no network). The node must have `registerHooks`
# (v22.15+). `NODE22` may name one when the default `node` is older. Run from anywhere.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
NODE="${NODE22:-node}"
if ! "$NODE" -e 'process.exit(typeof require("node:module").registerHooks === "function" ? 0 : 1)' 2>/dev/null; then
  echo "native tests need a node with module.registerHooks (v22.15 or later); set NODE22 to one." >&2
  exit 1
fi
for t in "$DIR"/__tests__/*.test.mts; do
  echo "== $(basename "$t")"
  "$NODE" --experimental-strip-types --no-warnings "$t"
done

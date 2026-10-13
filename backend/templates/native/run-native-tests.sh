#!/usr/bin/env bash
# The fixed half of the native app, without a device: the pure logic under plain
# node (no react-native, no network). The node must have `registerHooks`
# (v22.15+), which the machine's default v22.11 lacks; NODE22 may name one that
# does. Run from anywhere.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
NODE="${NODE22:-node}"
if [ "$NODE" = node ] && [ -x "C:/Users/Tentoro/AppData/Local/nvm/v22.20.0/node.exe" ]; then
  NODE="C:/Users/Tentoro/AppData/Local/nvm/v22.20.0/node.exe"
fi
for t in "$DIR"/__tests__/*.test.mts; do
  echo "== $(basename "$t")"
  "$NODE" --experimental-strip-types --no-warnings "$t"
done

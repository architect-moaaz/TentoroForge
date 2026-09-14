#!/usr/bin/env bash
# Run the remaining three sweeps once the props sweep has finished.
#
# They MUST be sequential: all four drive the same editor against the same
# scratch project, and the persister rewrites nav-flow.json and
# tokens.custom.json on every single flush (persistence.ts:62-74). Two sweeps at
# once would be last-writer-wins on both files, silently corrupting each other's
# state and producing findings about the harness rather than the product.
set -u

CFG="tests/e2e/tier2.config.ts"
export E2E_PROJECT_URL="${E2E_PROJECT_URL:-http://localhost:3000/editor/e2e-scratch}"
LOG_DIR="${TEMP:-/tmp}"

echo "[chain] waiting for the props sweep to finish…"
# Wait for the marker the props spec prints at the very end, or for its log to
# stop existing. Bounded so a crashed run cannot hang the chain forever.
for _ in $(seq 1 360); do
  if grep -q '\[SWEEP\] DONE' "$LOG_DIR/sweep-props.log" 2>/dev/null; then
    echo "[chain] props finished"
    break
  fi
  sleep 10
done

run() {
  local name="$1"
  echo ""
  echo "=============================================================="
  echo "[chain] $name"
  echo "=============================================================="
  npx playwright test -c "$CFG" "$name" 2>&1 | tee "$LOG_DIR/$name.log" \
    | grep -E '^\[STYLE\]|^\[BIND\]|^\[TOK\]|passed|failed'
}

run sweep-style
run sweep-bindings
run sweep-tokens

echo ""
echo "[chain] all sweeps complete"

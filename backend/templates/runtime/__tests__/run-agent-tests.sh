#!/usr/bin/env bash
# agent-runtime.test.mts — the SHIPPED templates/runtime/agents/* loop, guardrails,
# memory and tool runner, with the model, tools and database faked.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/agent-runtime.test.mts"

# Human handoff: who may work the inbox, assignment, and that nothing after the record can fail it.
node --experimental-strip-types --no-warnings "$DIR/agent-handoff.test.mts"

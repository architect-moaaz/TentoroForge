#!/usr/bin/env bash
# agent-runtime.test.mts — the SHIPPED templates/runtime/agents/* loop, guardrails,
# memory and tool runner, with the model, tools and database faked.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/agent-runtime.test.mts"

# Human handoff: who may work the inbox, assignment, and that nothing after the record can fail it.
node --experimental-strip-types --no-warnings "$DIR/agent-handoff.test.mts"

# Who may open the handoff inbox and whose handoffs it shows: nobody when nobody is named, never a customer, and only the
# handler's own organisation, through the real route and store on an in-memory database.
node --experimental-strip-types --no-warnings "$DIR/agent-handoff-inbox.test.mts"

# Confirm before changing, and per-person limits.
node --experimental-strip-types --no-warnings "$DIR/agent-safety.test.mts"

# Watching the app live: the secret, what goes to the builder, and what the tools did in the app.
node --experimental-strip-types --no-warnings "$DIR/agent-debug.test.mts"

# Watching the real chat live: the feed, the observer, and the runtime's phases.
node --experimental-strip-types --no-warnings "$DIR/agent-watch.test.mts"

# What each turn cost and how it went, the thumbs up/down under an answer, and recording that can never hurt a chat.
node --experimental-strip-types --no-warnings "$DIR/agent-turns.test.mts"

# The cost-and-quality report built from the recorded turns, and the route that is shut like the debug route.
node --experimental-strip-types --no-warnings "$DIR/agent-insights.test.mts"

# Sending every turn to the platform (insights-shipper.ts): events as the contract says and nothing private in them,
# batching by count and time, size and gzip limits, back-off with Retry-After, a refused batch, a network that throws
# or hangs, the bounded queue, nothing at all when the app is not connected.
node --experimental-strip-types --no-warnings "$DIR/agent-insights-shipper.test.mts"

# The same batches checked against the platform's written ingest rules (field types, lengths, hex keys, 20 tools, ids).
node --experimental-strip-types --no-warnings "$DIR/agent-insights-contract.test.mts"

# The outbox on the app's own database: written first, marked sent on a 202, caught up oldest first by the tick, ratings
# and hand-offs, a week's retention, and an app whose database has not been updated yet.
node --experimental-strip-types --no-warnings "$DIR/agent-insights-outbox.test.mts"

# The catch-up route and the cron tick's call to it.
node --experimental-strip-types --no-warnings "$DIR/agent-insights-tick.test.mts"

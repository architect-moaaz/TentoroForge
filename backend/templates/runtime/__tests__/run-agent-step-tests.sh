#!/usr/bin/env bash
# An assistant as one step of a workflow (agent_step): the SHIPPED agents/workflow-*.ts, the workflow engine's
# handling of the step, the dry-run stand-in and the chat route's workflowOnly rule, with the model, the tools,
# the data layer and the clock faked.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

# The headless run: the two phases, each autonomy mode and its gates, the answer's schema and retry, every failure
# with every onFailure, the limits, the depth guard, the assistant's guardrails and the turn that is recorded.
node --experimental-strip-types --no-warnings "$DIR/agent-step-run.test.mts"

# Who the step acts as: an in-process actor holding exactly the assistant's tools, nothing on the wire, every call logged.
node --experimental-strip-types --no-warnings "$DIR/agent-step-identity.test.mts"

# A real workflow run through the shipped engine and handler: envelope, onFailure, execution log, stub, Watch live.
node --experimental-strip-types --no-warnings "$DIR/agent-step-workflow.test.mts"

# The build-time dry run: a model-free sample answer, per field type, and what resolves against it.
node --experimental-strip-types --no-warnings "$DIR/agent-step-dry-run.test.mts"

# An assistant made for a workflow is neither listed nor answered by the chat; every other chat behaviour unchanged.
node --experimental-strip-types --no-warnings "$DIR/agent-workflow-only.test.mts"

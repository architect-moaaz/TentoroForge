#!/usr/bin/env bash
# mcp-step-finds-its-server.test.mts — the SHIPPED workflows/index.ts finds
# the MCP server a step means, or says it found none.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/mcp-step-finds-its-server.test.mts"

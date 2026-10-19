#!/usr/bin/env bash
# an-assistant-acts-as-the-person.test.mts — the SHIPPED MCP protocol and route:
# tools by role, each through the screen's own route as the token's person.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
node --experimental-strip-types --no-warnings "$DIR/an-assistant-acts-as-the-person.test.mts"

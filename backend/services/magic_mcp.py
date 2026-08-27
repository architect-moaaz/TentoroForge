"""21st.dev Magic MCP wiring for the design agent.

Optional stdio MCP server that exposes 21st.dev's curated catalog of
React/Tailwind components + design inspiration.

Gated behind BOTH:
  - FORGE_21ST_MCP        — truthy flag (on/1/true/warn/strict)
  - FORGE_21ST_API_KEY    — fresh key from https://21st.dev/mcp
                            (old @21st-dev/magic keys were reset)

Rationale for the two-gate design: the flag lets an operator turn the
integration off without unsetting the key, and the key check keeps us
from spawning the subprocess only for it to fail at handshake time when
no credential is configured.

The MCP is a thin stdio proxy (`npx -y @21st-dev/magic@latest`) that
speaks MCP to Claude and forwards every message to the hosted 21st MCP
at https://21st.dev/api/mcp. Tool names we care about:
  - generate         — synthesize a React/Tailwind component
  - get_inspiration  — browse curated component variants
  - search_logo      — brand logo lookup

We ship SCHEMA JSON, not JSX. The design agent uses this MCP as a
REFERENCE — extracting palette, typography, and structural decisions,
never pasting JSX into any output file. See PROMPT_BLOCK below.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable

logger = logging.getLogger(__name__)

SERVER_NAME = "magic-mcp"
# Actual tool names exposed by the current 21st.dev MCP server (verified via
# tools/list on 2026-08-12). The old @21st-dev/magic README advertised
# `generate` / `get_inspiration` / `search_logo`; the current unified server
# exposes richer + differently-named tools. The stdio compat proxy accepts the
# legacy names too, but we allowlist the real names so the LLM sees the true
# capability set. `get_component` is PAID (uses daily quota).
TOOL_NAMES = ("search", "get_component", "generate", "get_theme")
# claude_agent_sdk exposes MCP tools to the LLM as `mcp__<server>__<tool>`.
ALLOWED_TOOLS = [f"mcp__{SERVER_NAME}__{t}" for t in TOOL_NAMES]

_TRUTHY = {"1", "true", "on", "yes", "warn", "strict"}


def _flag_on() -> bool:
    return (os.environ.get("FORGE_21ST_MCP") or "").strip().lower() in _TRUTHY


def _api_key() -> str:
    return (os.environ.get("FORGE_21ST_API_KEY") or "").strip()


def is_enabled() -> bool:
    """True iff BOTH the flag is on AND an API key is configured."""
    return _flag_on() and bool(_api_key())


def get_mcp_config() -> dict | None:
    """Build the stdio McpServer config; None when the integration is off.

    Returns a dict shaped for claude_agent_sdk's ClaudeAgentOptions.mcp_servers.
    Passes the key via env (TWENTY_FIRST_API_KEY + API_KEY_21ST — both names
    are accepted by the compat proxy). Avoids putting the key in argv so it
    doesn't appear in ps output.
    """
    if not is_enabled():
        return None
    api_key = _api_key()
    return {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@21st-dev/magic@latest"],
        "env": {
            "TWENTY_FIRST_API_KEY": api_key,
            "API_KEY_21ST": api_key,
        },
    }


def merge_into(
    mcp_servers: dict | None,
    allowed_tools: Iterable[str],
) -> tuple[dict, list[str]]:
    """Merge Magic MCP into an existing ClaudeAgentOptions config.

    Returns ``(mcp_servers_dict, allowed_tools_list)`` with the Magic MCP
    server added and the ``mcp__magic-mcp__*`` tool names appended (only
    if not already present). When the integration is disabled, returns
    the inputs unchanged (except for defensive copies).
    """
    servers = dict(mcp_servers or {})
    tools = list(allowed_tools)
    cfg = get_mcp_config()
    if cfg is not None:
        servers[SERVER_NAME] = cfg
        for t in ALLOWED_TOOLS:
            if t not in tools:
                tools.append(t)
    return servers, tools


PROMPT_BLOCK = """\
## 21st.dev Magic MCP (INSPIRATION ONLY — do not ship JSX)

You have access to the 21st.dev catalog via these tools:
  - `mcp__magic-mcp__search` — FREE: browse the catalog by query. Returns
    metadata (name, description, preview image, component id) only. Use
    for discovery. Pass `type: "component"` to scope to React components.
  - `mcp__magic-mcp__get_component` — PAID: fetch a component's real JSX
    by id (from a prior `search`). Uses the account's daily quota — call
    at most ONCE per authoring pass, on the single best match.
  - `mcp__magic-mcp__get_theme` — FREE: fetch a theme's CSS by uuid.
  - `mcp__magic-mcp__generate` — PAID: synthesize a new component from a
    prompt. Prefer `search` + `get_component` over this (real components
    beat AI-generated ones for structural inspiration).

WHEN TO USE
  - Before committing to a palette or type pairing, `search` for 2–3
    curated components matching the domain's primary layout. Pick the
    best-matching id, then `get_component` for its real JSX. Extract the
    *decisions* — hex codes, font families, contrast ratios, spacing
    rhythm, structural moves — not the JSX.
  - When the domain has ambiguous chrome ("wellness studio": spa? gym?
    editorial? warm? clinical?), `search` to see how designers resolve it.

STRICT RULES
  - The MCP returns React/Tailwind JSX. We SHIP SCHEMA JSON, not JSX.
    Read the JSX, extract the design decisions, and translate them into
    our design-spec.json (colorPalette, typography, spacing, radius).
  - NEVER paste raw JSX into any file you write. NEVER copy class names
    verbatim — translate them into our tokens.
  - Budget: ONE `search` + at most ONE `get_component` per authoring pass.
    `get_component` is paid and rate-limited.
  - If the MCP fails or returns nothing useful, proceed with the domain
    signals and knowledge-base rules already in your prompt. Do not block.
"""

"""Local agent message + options types (LG-4 of the LangGraph migration).

These used to come from ``claude_agent_sdk.types``. The SDK's bundled-CLI
executor is no longer part of the runtime (the agent loop runs on LangGraph /
LangChain — see services.langgraph_agent_runner), but its message shapes are
the streaming contract every agent and the SSE layer speak. Owning them as
plain dataclasses removes the last hard dependency on ``claude-agent-sdk``.

Shapes mirror the SDK's exactly (field names AND semantics), so swapping the
import is the whole migration for a consumer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union


@dataclass
class TextBlock:
    text: str


@dataclass
class ThinkingBlock:
    thinking: str
    signature: str = ""


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: Any = None
    is_error: bool | None = None


ContentBlock = Union[TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock]


@dataclass
class AssistantMessage:
    content: list[ContentBlock]
    model: str
    error: str | None = None


@dataclass
class UserMessage:
    content: str | list[ContentBlock]


@dataclass
class SystemMessage:
    subtype: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultMessage:
    subtype: str
    duration_ms: int
    duration_api_ms: int
    is_error: bool
    num_turns: int
    session_id: str
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None


Message = Union[AssistantMessage, UserMessage, SystemMessage, ResultMessage]


@dataclass
class AgentOptions:
    """The option surface Forge's agents actually construct (a strict subset
    of the SDK's ClaudeAgentOptions — cwd/model/max_turns/system_prompt/
    allowed_tools/permission_mode, plus mcp_servers carried for the Figma
    pipeline's tool declarations). Unknown legacy fields are accepted and
    ignored via **-tolerant call sites, not stored here."""
    system_prompt: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    permission_mode: str | None = None
    max_turns: int | None = None
    model: str | None = None
    cwd: str | Path | None = None
    mcp_servers: dict[str, Any] | str | Path = field(default_factory=dict)
    settings: str | None = None
    env: dict[str, str] = field(default_factory=dict)


# Drop-in alias — call sites keep their `ClaudeAgentOptions(...)` spelling.
ClaudeAgentOptions = AgentOptions

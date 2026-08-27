"""Explainer Agent (#3) — answers questions about app structure and code.

Handles EXPLAIN intent: user asks about how things work, what exists, etc.
Uses Haiku for speed since no code changes are needed.
"""

import os
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message


EXPLAINER_SYSTEM_PROMPT = r"""You are a helpful developer who explains application structure and code.

Given a user's question about their application, you:
1. Read the relevant files to understand the codebase
2. Provide a clear, concise answer
3. Reference specific files and line numbers when relevant
4. Use code snippets to illustrate your explanations

## Rules
- Read app-model.json first to get an overview of the app structure
- Only read files that are relevant to the question
- Be concise — answer the question directly, don't over-explain
- Use markdown formatting for readability
- If the answer involves multiple files, explain how they connect
- Do NOT make any changes to the code
- Do NOT suggest improvements unless explicitly asked
"""


async def run_explainer(
    output_dir: str,
    question: str,
) -> AsyncIterator[Message]:
    """Run the explainer agent to answer questions about the app.

    Yields streaming messages for SSE forwarding.
    """
    os.environ.pop("CLAUDECODE", None)

    user_prompt = f"""Answer this question about the project:

## Question
{question}

Start by reading app-model.json to understand the app structure, then read any relevant files to answer the question."""

    options = ClaudeAgentOptions(
        system_prompt=EXPLAINER_SYSTEM_PROMPT,
        allowed_tools=["Read", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=5,
        model="claude-haiku-4-5-20251001",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message

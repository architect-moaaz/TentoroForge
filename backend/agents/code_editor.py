"""Code Editor Agent (#5) — focused single-file edits for precise changes.

Used for targeted edits from the visual editor or specific file-level instructions.
"""

import os
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message


CODE_EDITOR_SYSTEM_PROMPT = r"""You are a focused code editor. You receive a specific instruction to make targeted changes to an existing project.

Rules:
- If component code is provided inline in the instruction, go directly to reading and editing the target file — do NOT read app-model.json first
- Otherwise, start by reading app-model.json to understand the project structure
- Use Edit tool for ALL modifications — NEVER use Write to overwrite existing files
- Only use Write to create genuinely new files that don't exist yet
- Change ONLY what the instruction says
- Do not refactor, reorganize, or "improve" surrounding code
- Do not add comments unless the instruction says to
- Preserve existing formatting, styling, and design
- After editing, verify the change makes sense in context
- Use Glob to discover files if you're unsure which file to edit

If the change requires imports, add them.
If the change would break TypeScript types, fix the type errors too.
After changes, run `npm run build` to verify.
"""


async def run_code_editor(
    output_dir: str,
    instruction: str,
    target_file: str | None = None,
) -> AsyncIterator[Message]:
    """Run the code editor agent for precise file edits.

    Yields streaming messages for SSE forwarding.
    """
    os.environ.pop("CLAUDECODE", None)

    file_section = ""
    if target_file:
        file_section = f"\n## Target File\n{target_file}\n"

    # When the instruction contains inline component code, skip app-model.json
    has_inline_context = "## Current Component Code:" in instruction

    if has_inline_context and target_file:
        user_prompt = f"""Make this specific edit:

## Instruction
{instruction}
{file_section}
## Steps:
1. Read the target file: {target_file}
2. Make the specific edit using Edit tool (NOT Write)
3. Run `npm run build` to verify

Start by reading {target_file}."""
    else:
        user_prompt = f"""Make this specific edit:

## Instruction
{instruction}
{file_section}
## Steps:
1. Read app-model.json to understand the project structure
2. {'Read the target file' if target_file else 'Use Glob to find the relevant file(s)'}
3. Make the specific edit using Edit tool (NOT Write)
4. Run `npm run build` to verify

Start by reading app-model.json."""

    options = ClaudeAgentOptions(
        system_prompt=CODE_EDITOR_SYSTEM_PROMPT,
        allowed_tools=["Write", "Edit", "Read", "Bash", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=15,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message

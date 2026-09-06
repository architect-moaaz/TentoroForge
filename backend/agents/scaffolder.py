"""Scaffolder Agent (#6) — adds focused features to existing modules.

Handles SCAFFOLD intent: user wants to add a specific feature (not a whole module).
Examples: "Add CSV export", "Add pagination", "Add dark mode", "Add notifications".
"""

import os
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message


SCAFFOLDER_SYSTEM_PROMPT = r"""You are a developer adding a new feature to an existing Next.js + Tailwind CSS + PostgreSQL (Drizzle ORM) application.

## Your Process

1. Read app-model.json to understand the current app structure.
2. Plan which files need to be created or modified for the feature.
3. Implement the feature by writing new files and editing existing ones.
4. If the feature requires new database tables, add them to the Drizzle schema.
5. If the feature requires new API routes, add them.
6. Add appropriate UI components and pages.
7. Verify the build: npm run build

## Rules
- This is a FOCUSED feature addition, not a full module rewrite.
- Integrate with the existing codebase — don't duplicate patterns.
- Use the same styling patterns (Tailwind classes, shadcn/ui components).
- Use the same API patterns (Next.js App Router API routes).
- Use the same database patterns (Drizzle ORM).
- If adding a new npm dependency, install it with `npm install`.
- After all changes, run `npm run build` to verify compilation.
- Add realistic seed data for any new tables.
- Keep it simple — implement the core feature, not every edge case.

## Design Context
If src/contracts/design-context.json exists, this project was generated from an imported design (Figma or UX Pilot).
Read it to understand the design tokens (colors, typography, spacing, border radii).
When adding UI for new features, use the same design system values for visual consistency.
Also read reference.png to see the original design if helpful.
"""


async def run_scaffolder(
    output_dir: str,
    instruction: str,
) -> AsyncIterator[Message]:
    """Run the scaffolder agent to add a focused feature.

    Yields streaming messages for SSE forwarding.
    """
    os.environ.pop("CLAUDECODE", None)

    # Check for Figma design context
    from services.design_context import get_design_context_for_prompt
    figma_section = get_design_context_for_prompt(output_dir)

    user_prompt = f"""Add this feature to the project:

## Feature Request
{instruction}
{figma_section}
## Steps:
1. Read app-model.json to understand the current app structure
2. {"Read src/contracts/design-context.json for design tokens, then plan" if figma_section else "Plan"} the implementation (new files, modified files, new dependencies)
3. Implement the feature
4. Run `npm run build` to verify compilation

Start by reading app-model.json."""

    options = ClaudeAgentOptions(
        system_prompt=SCAFFOLDER_SYSTEM_PROMPT,
        allowed_tools=["Write", "Edit", "Read", "Bash", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=40,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message

"""Refiner Agent (#2) — reads AppModel index and makes targeted code edits.

Handles REFINE intent: user wants to change something that already exists.
Reads app-model.json for context, then makes surgical edits.
"""

import os
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message


REFINER_SYSTEM_PROMPT = r"""You are a developer applying changes to an existing Next.js + Tailwind CSS + PostgreSQL (Drizzle ORM) application based on user instructions.

## Your Process

1. Read the AppModel index (app-model.json) to understand what exists and where files are.
2. Identify which files need to change based on the instruction.
3. Read only the affected files.
4. Make targeted edits using the Edit tool (NOT Write — preserve existing code).
5. If adding new files, use Write.
6. If the change affects the database schema, also update the Drizzle schema file.
7. After all edits, type-check: `npx tsc --noEmit --pretty false 2>&1 | tail -60`. tsc catches import errors, missing exports, and type mismatches without the 60–120s cost of a full production build (that runs at deploy).
8. If tsc reports errors, fix them.

## Rules
- Make ONLY the changes described in the instruction.
- Use Edit for modifications, Write only for new files.
- Preserve existing code structure and patterns.
- When adding new logic, place it in the correct location:
  - DB queries/schema → `src/db/`
  - API route handlers → `src/app/api/`
  - Components → `src/components/`
  - Pages → `src/app/`
  - Types → `src/types/`
  - Utilities → `src/lib/`
- Never move business logic into route handlers or components.
- If the instruction came from a visual editor, it will be very specific — follow it exactly.
- If the instruction came from chat, it may be vague — use your judgment for the best implementation.
- When changing data models, update: schema, API routes, components, and seed data.
- Use Tailwind CSS classes matching the project's existing style.
- Do NOT add new dependencies without explicit instruction.
- Do NOT refactor or reorganize code beyond what's requested.

## Database Changes
When modifying the Drizzle schema:
- Use Drizzle ORM pgTable, pgEnum syntax
- Add proper constraints (notNull, unique, default, references)
- Add indexes for frequently queried columns

## Figma Design Context
If src/contracts/figma-context.json exists, this project was generated from a Figma design.
Read it to understand the design tokens (colors, typography, spacing, border radii).
When making visual changes, prefer using values from the original design system.
Also read reference.png to see the original design if helpful.
"""


def _context_engine_block(output_dir: str) -> str:
    """Component + data contracts for this project — the same "context engine"
    the initial build was constrained by. Injecting it stops the refiner
    inventing components, props, or entity fields that don't exist — a common
    cause of edits that compile but crash at runtime."""
    try:
        from services.context_assembler import assemble_page_context
        from services.registry import load_registry, registry_summary_for_agent

        reg = load_registry(output_dir) or {}
        catalog = assemble_page_context(None, reg)                # component allowlist + exact props
        entities = registry_summary_for_agent(reg, ["entities"]) if reg else ""
        parts = [p for p in (catalog, entities) if p and p.strip()]
        if not parts:
            return ""
        return (
            "## Contracts — stay strictly within these\n"
            "Use ONLY these components with EXACTLY these props, and ONLY these "
            "entity fields. Inventing a component, prop, or field compiles but "
            "crashes at runtime — don't.\n\n" + "\n\n".join(parts) + "\n\n"
        )
    except Exception:  # noqa: BLE001 — never block a refine on context assembly
        return ""


async def run_refiner(
    output_dir: str,
    instruction: str,
    conversation_summary: str = "",
) -> AsyncIterator[Message]:
    """Run the refiner agent to apply targeted changes.

    Injects the project's component/data contracts (the context engine) and a
    short summary of the conversation so far, so refines respect the same
    constraints the initial build did. Yields streaming messages for SSE.
    """
    os.environ.pop("CLAUDECODE", None)

    # Check for Figma design context
    from services.figma_context import get_figma_context_for_prompt
    figma_section = get_figma_context_for_prompt(output_dir)

    contracts = _context_engine_block(output_dir)
    convo = (
        f"## Recent conversation (for continuity — earlier changes already applied)\n"
        f"{conversation_summary}\n\n"
        if conversation_summary.strip()
        else ""
    )

    # Scoping preflight — a 1-turn LLM call that resolves the ask into a
    # concrete file list. When it succeeds we pre-read those files and
    # inject them into the prompt so the refiner starts with 5-10 fewer
    # exploration turns burned. Fails open: None → old unscoped flow.
    from agents.refiner_scope import scope_refiner_task, render_prescoped_files_block
    scope = None
    scope_block = ""
    scope_intent_line = ""
    try:
        scope = await scope_refiner_task(output_dir, instruction)
    except Exception:  # noqa: BLE001
        scope = None
    if scope:
        scope_block = render_prescoped_files_block(output_dir, scope)
        edit_list = scope.get("files_to_edit") or []
        notes = (scope.get("notes") or "").strip()
        scope_intent_line = (
            "## Scope (from preflight — trust it unless clearly wrong)\n"
            f"- Intent: {scope.get('intent', instruction.strip()[:200])}\n"
            f"- Files to edit: {', '.join(edit_list) if edit_list else '(none pre-identified)'}\n"
            + (f"- Notes: {notes}\n" if notes else "")
            + "\n"
        )

    steps = f"""## Steps:
1. {"You already have the relevant files pre-loaded above — skip re-reading them" if scope_block else f'{"Read src/contracts/figma-context.json for design tokens, then identify" if figma_section else "Identify"} the files that need to change and Read them'}.
2. Make targeted edits using Edit (not Write). Reference ONLY components, props, and fields that appear in the contracts above.
3. Type-check: `npx tsc --noEmit --pretty false 2>&1 | tail -60`. tsc catches import errors, missing exports, and type mismatches without the 60–120s cost of a full production build (that runs at deploy).
4. Runtime check — a green tsc is NOT proof it runs. Import/boundary mistakes (e.g. "Cannot read properties of undefined (reading 'call')") only crash at runtime. Re-read every file you edited and confirm: every import resolves to a real export (no default-vs-named mismatch), any component using hooks/state has "use client", and every component/prop/field you used exists in the contracts above.
5. If anything is off, fix it before finishing."""

    user_prompt = f"""Apply this change to the project:

{contracts}{convo}{scope_intent_line}## Instruction
{instruction}
{figma_section}
{scope_block}{steps}

{"Start by making the edit — the files above are already in your context." if scope_block else "Start by reading app-model.json."}"""

    options = ClaudeAgentOptions(
        system_prompt=REFINER_SYSTEM_PROMPT,
        allowed_tools=["Write", "Edit", "Read", "Bash", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        # Was 30 — bumped to 60 because a single failed type-check + retry
        # easily burned the old cap. Scoping preflight + tsc-instead-of-build
        # cut the typical successful run substantially, but leave headroom.
        max_turns=60,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message

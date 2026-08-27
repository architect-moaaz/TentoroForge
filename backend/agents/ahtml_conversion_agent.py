"""AHTML-to-TSX Conversion Agent

Uses Claude to convert annotated HTML pages to valid Next.js TSX components.
The agent receives a structured prompt with page metadata, data sources,
state bindings, actions, and the raw annotated HTML body.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import AsyncIterator

from services.sdk_agent_runner import query
from services.agent_messages import Message, AssistantMessage, TextBlock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

AHTML_TO_TSX_SYSTEM_PROMPT = """You are an expert React/Next.js developer.
Your task is to convert annotated HTML pages to valid Next.js "use client" TSX components.

## Annotated HTML Conventions

The input HTML uses these data-* attributes to encode logic:

### Data Sources
- `data-source="name"` — references a data source (REST API endpoint)
- `data-source-method="GET|POST|..."` — HTTP method
- `data-source-path="/api/..."` — API endpoint

### State Binding
- `data-bind="state:fieldName"` — two-way state binding → useState + onChange
- `data-bind="state:form.field"` — nested state binding

### Actions
- `data-action="navigate" data-action-to="/path"` → `router.push("/path")`
- `data-action="mutate" data-action-source="sourceName"` → `mutation.mutate()`
- `data-action="openModal" data-modal-trigger="modalId"` → `setModalOpen(true)`
- `data-action="setState" data-action-value="..."` → `setState(value)`
- `data-action-confirm="message"` → `window.confirm("message")`

### Repeaters
- `data-repeat="sourceName"` → `.map()` over data source items
- `data-repeat-key="id"` → React key field
- `data-field="fieldName"` → access item.fieldName

### Conditional Rendering
- `data-visible="expression"` → `{expression && (...)}`
- `data-visible-not="expression"` → `{!expression && (...)}`

### Components
- `data-component="DataTable"` → use `<DataTable>` from shadcn/ui
- `data-component="Card"` → use `<Card>` + `<CardContent>`
- `data-component="Tabs"` → use `<Tabs>` + `<TabsList>` etc.
- `data-component="Form"` → `<form>` with proper onSubmit

### Slots (unfilled placeholders)
- `data-slot="entity-table"` → leave as TODO comment with the slot type

## Output Rules

1. Output ONLY the TSX code inside ```tsx markers
2. Start with "use client" directive
3. Use shadcn/ui component imports from @/components/ui/
4. Use @tanstack/react-query for data fetching (useQuery for GET, useMutation for mutations)
5. Use next/navigation for routing (useRouter)
6. Use lucide-react for icons (data-icon attribute values)
7. PRESERVE ALL Tailwind classes exactly as they appear in the HTML
8. PRESERVE ALL visual styles, colors, spacing, layout
9. Convert `class` to `className`
10. Convert HTML boolean attributes properly
11. Export the component as default
12. Name the component: {PageId}Page (PascalCase)
"""


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------

async def run_ahtml_to_tsx_agent(
    page_html: str,
    page_metadata: dict,
    tsx_hints: dict | None = None,
) -> AsyncIterator[Message]:
    """Convert a single annotated HTML page to TSX.

    Args:
        page_html: The annotated HTML body content.
        page_metadata: Page info (pageId, route, title, dataSources, state, etc.).
        tsx_hints: Optional hints about imports and hooks needed.

    Yields:
        Messages from the Claude agent.
    """
    os.environ.pop("CLAUDECODE", None)
    os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)

    page_id = page_metadata.get("pageId", "page")
    route = page_metadata.get("route", "/")
    title = page_metadata.get("title", "Untitled")
    data_sources = page_metadata.get("dataSources", {})
    state_fields = page_metadata.get("stateFields", {})
    modals = page_metadata.get("modals", {})
    summary = page_metadata.get("summary", {})

    # Build the user prompt
    prompt_parts = [
        f"Convert this annotated HTML to a Next.js TSX component.",
        f"\n## Page: {title}",
        f"- ID: {page_id}",
        f"- Route: {route}",
    ]

    if data_sources:
        prompt_parts.append(f"\n## Data Sources\n```json\n{json.dumps(data_sources, indent=2)}\n```")

    if state_fields:
        prompt_parts.append(f"\n## Initial State\n```json\n{json.dumps(state_fields, indent=2)}\n```")

    if modals:
        prompt_parts.append(f"\n## Modals\n```json\n{json.dumps(modals, indent=2)}\n```")

    if summary:
        prompt_parts.append(f"\n## Bindings Summary")
        if summary.get("stateBindings"):
            prompt_parts.append(f"- State: {', '.join(b.get('expression', '') for b in summary['stateBindings'])}")
        if summary.get("dataSourceRefs"):
            prompt_parts.append(f"- Data sources: {', '.join(summary['dataSourceRefs'])}")
        if summary.get("actions"):
            prompt_parts.append(f"- Actions: {', '.join(a.get('type', '') for a in summary['actions'])}")

    if tsx_hints:
        hint_lines = []
        for imp in tsx_hints.get("libraryImports", []):
            hint_lines.append(imp)
        if tsx_hints.get("reactImports"):
            hint_lines.append(f'import {{ {", ".join(tsx_hints["reactImports"])} }} from "react";')
        if hint_lines:
            prompt_parts.append(f"\n## Suggested Imports\n```typescript\n{chr(10).join(hint_lines)}\n```")

    prompt_parts.append(f"\n## Annotated HTML\n```html\n{page_html}\n```")
    prompt_parts.append(f"\nComponent name: {_pascal_case(page_id)}Page")

    user_prompt = "\n".join(prompt_parts)

    from services.agent_messages import ClaudeAgentOptions

    options = ClaudeAgentOptions(
        system_prompt=AHTML_TO_TSX_SYSTEM_PROMPT,
        model="claude-sonnet-4-6",
        max_turns=1,
        permission_mode="bypassPermissions",
    )

    async for msg in query(prompt=user_prompt, options=options):
        yield msg


# ---------------------------------------------------------------------------
# Extract TSX from agent response
# ---------------------------------------------------------------------------

def extract_tsx_from_response(messages: list[Message]) -> str | None:
    """Extract TSX code from agent response messages."""
    full_text = ""
    for msg in messages:
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    full_text += block.text

    # Try to extract from ```tsx markers first, then ```
    tsx_match = re.search(r"```tsx\s*\n(.*?)```", full_text, re.DOTALL)
    if tsx_match:
        return tsx_match.group(1).strip()

    generic_match = re.search(r"```\s*\n(.*?)```", full_text, re.DOTALL)
    if generic_match:
        return generic_match.group(1).strip()

    # If no code block, check if the entire response looks like TSX
    if full_text.strip().startswith('"use client"') or full_text.strip().startswith("'use client'"):
        return full_text.strip()

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pascal_case(s: str) -> str:
    """Convert a string to PascalCase."""
    return "".join(
        part.capitalize()
        for part in re.split(r"[-_\s]+", s)
        if part
    )

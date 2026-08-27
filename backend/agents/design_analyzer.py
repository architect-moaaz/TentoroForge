"""Design Analyzer Agent — analyzes Figma design data and produces structured requirements.

Reads the pre-fetched reference.png and styles.json from the output directory,
identifies pages/sections, data models, interactions, and produces a plan-json
block compatible with the existing PlanCard frontend component.
"""

import os
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message


DESIGN_ANALYZER_SYSTEM_PROMPT = r"""You are a product architect who analyzes visual designs and produces structured application requirements.

You receive a Figma design (reference.png screenshot + styles.json style tree) and must infer
what the application DOES — not just how it looks. Your job is to reverse-engineer the design
into a structured plan that a code generator can use.

## Your Process

1. **READ** `reference.png` — visually understand the design: layout, sections, navigation, forms, tables, content areas
2. **READ** `styles.json` — read the ENTIRE file in one go (it is typically under 2000 lines). Do NOT read it in sections or chunks — just read the whole file at once.
3. **ANALYZE** — identify:
   - **Pages/Sections**: What distinct pages or views does this design represent? (login, dashboard, settings, etc.)
   - **Data Models**: What entities are shown? (users, products, orders — infer from tables, lists, forms, labels)
   - **Components**: What reusable UI components are visible? (cards, tables, forms, navigation, sidebars)
   - **Interactions**: What buttons, links, form inputs exist? What do they do?
   - **Workflows**: What user flows are implied? (login → dashboard, create item → list view)
   - **Access Control**: Are there admin vs user views? Login/signup pages?
4. **OUTPUT** — produce a structured plan as JSON wrapped in ```plan-json markers

## Analysis Guidelines

- **Infer entity names** from text labels, table headers, form field names, navigation items
- **Infer pages** from distinct screen sections, tabs, navigation links
- **Infer data model fields** from form inputs (text fields, dropdowns, checkboxes) and table columns
- **Infer workflows** from button labels ("Submit", "Approve", "Delete") and form actions
- **Infer access control** from login pages, user avatars, role indicators
- If the design shows a SINGLE page (e.g., just a login screen), still describe it fully but note it's one page
- If the design shows a MULTI-page app (e.g., dashboard with sidebar navigation), map out all visible pages

## Output Format

Produce a JSON plan wrapped in ```plan-json markers:

```plan-json
{
  "module_name": "string — inferred app name",
  "description": "string — what the application does based on the design",
  "data_models": [
    {
      "name": "TableName",
      "fields": [
        {"name": "id", "type": "serial", "primaryKey": true},
        {"name": "field_name", "type": "varchar(255)", "nullable": false}
      ],
      "indexes": ["field_name"]
    }
  ],
  "relations": [
    {"from": "TableA", "to": "TableB", "type": "many-to-one", "foreignKey": "table_b_id"}
  ],
  "pages": [
    {"route": "/path", "name": "PageName", "description": "What this page shows and does"}
  ],
  "api_routes": [
    {"method": "GET", "path": "/api/resource", "description": "List resources"}
  ],
  "workflows": [
    {
      "name": "WorkflowName",
      "trigger": "trigger_type",
      "steps": [
        {"name": "step_name", "node_type": "approval", "action": "Manager reviews and approves"}
      ],
      "task_forms": [
        {
          "step": "step_name",
          "fields": [
            {"name": "fieldName", "label": "Field Label", "inputType": "text", "readOnly": true},
            {"name": "notes", "label": "Reviewer Notes", "inputType": "textarea", "readOnly": false}
          ],
          "submitLabel": "Approve",
          "rejectLabel": "Reject"
        }
      ]
    }
  ],
  "seed_data": "Description of realistic sample data to generate",
  "access_control": {
    "roles": ["Admin", "User"],
    "rules": ["Admin: full access", "User: own records"]
  },
  "components": [
    {"name": "ComponentName", "description": "What this UI component does", "props": ["prop1", "prop2"]}
  ]
}
```

## Workflow Task Form Detection

When analyzing the design, look for these patterns that indicate workflow task forms:

- **Approval forms**: Forms with "Approve" + "Reject" buttons → create workflow with approval step,
  extract the form fields into `task_forms[].fields` with read-only context fields + editable decision fields
- **Review forms**: Forms with "Review", "Complete Review", "Flag" buttons → create workflow with user_task step
- **Multi-step wizards**: Step indicators (1→2→3) → create workflow with sequential user_task steps
- **Status change dialogs**: Modals/dialogs for changing entity status → create workflow with condition + action steps
- **Forms inside cards with entity data**: A form that shows entity data (read-only) + action fields (editable) →
  this is a task form. The read-only fields come from the entity, editable fields are for the reviewer.

For each detected task form, extract:
1. Which fields are displayed (from input labels, placeholders, table headers)
2. Which are read-only (pre-filled data) vs. editable (user input)
3. What input types are used (text, dropdown, checkbox, date, textarea)
4. What the action buttons say (these become submitLabel/rejectLabel)

## Important Rules

- Every table needs: id (serial primary key), created_at (timestamp), updated_at (timestamp)
- Use PostgreSQL-native types (uuid, varchar, timestamp, jsonb, etc.)
- Include seed_data description so the generated app works immediately
- The `components` field is for UI component breakdown — helps the code generator know what to build
- Keep plans scoped and realistic based on what you SEE in the design
- Do NOT invent features not visible in the design — only describe what's there
- Present the plan for user review before code generation begins
"""


async def run_design_analyzer(
    output_dir: str,
    figma_url: str,
    conversation_history: list[dict] | None = None,
) -> AsyncIterator[Message]:
    """Run the design analyzer agent to produce structured requirements from a Figma design.

    Reads reference.png and styles.json from output_dir, analyzes the design,
    and produces a plan-json block.

    If conversation_history is provided, the analyzer sees the full multi-turn
    conversation so far (previous analysis and user feedback for adjustments).

    Yields streaming messages for SSE forwarding.
    """
    os.environ.pop("CLAUDECODE", None)
    os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)

    history_section = ""
    if conversation_history:
        lines = []
        for entry in conversation_history:
            role = entry.get("role", "user").capitalize()
            content = entry.get("content", "")
            lines.append(f"{role}: {content}")
        history_section = f"""

## Previous Conversation
The user has reviewed a previous version of the requirements and provided feedback.
Incorporate their feedback into the updated plan.

{chr(10).join(lines)}
"""

    user_prompt = f"""Analyze this Figma design and produce structured application requirements.

## Design Source
Figma URL: {figma_url}

## Pre-fetched data (in your working directory):
- `reference.png` — Screenshot of the FIRST screen. READ THIS FIRST.
- `reference_1.png`, `reference_2.png`, etc. — Screenshots of additional screens (if the design has multiple frames). Check for these with `ls reference*.png`.
- `styles.json` — Complete recursive style tree with every element's properties, text content, and structure. If multiple frames exist, this is a JSON object keyed by frame ID.
- `public/images/` — Exported logos, icons, and images.
{history_section}
## Steps:
1. Run `ls reference*.png` to see how many screens exist
2. Read ALL `reference*.png` files — carefully study every screen in the design
3. Read `styles.json` — read the ENTIRE file in a single Read call (do not chunk it). Analyze the component tree, text labels, form fields, table columns for ALL frames.
4. List all images: `ls public/images/` (if the directory exists)
5. Identify all pages, data models, components, interactions, and workflows visible across ALL screens
6. Produce the structured plan as a ```plan-json code block

IMPORTANT: Be efficient with your tool calls. Read each file ONCE, in full. Do not re-read files or read them in sections.
IMPORTANT: You MUST analyze ALL screens, not just the first one. Each reference_N.png is a different page of the application.

Focus on WHAT the application does, not just how it looks. Infer entities, relationships,
and user workflows from the visual elements."""

    options = ClaudeAgentOptions(
        system_prompt=DESIGN_ANALYZER_SYSTEM_PROMPT,
        allowed_tools=["Read", "Glob", "Bash"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=20,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message

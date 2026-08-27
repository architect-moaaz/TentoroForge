"""Figma → IR Agent — converts Figma design context into IR page nodes.

Instead of generating code directly from Figma, this agent produces
structured IR metadata that the compiler converts to code deterministically.

The AI's job is narrowed to:
1. Spatial layout analysis → layout node selection (Row, Stack, Grid)
2. Element classification → node type mapping
3. Text extraction → content props
4. Color extraction → token mapping
5. Interaction inference → action and binding setup
"""

import json
import logging
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message

logger = logging.getLogger(__name__)

FIGMA_IR_SYSTEM_PROMPT = r"""You are a Figma-to-IR conversion agent. You analyze Figma design context
(screenshot + component hints) and produce structured IR (Intermediate Representation)
that compiles to React/Tailwind code.

## YOUR JOB
Convert the Figma design into a single PageIR JSON structure. Do NOT generate code.
Generate only the IR node tree that represents the design.

## OUTPUT FORMAT
Respond with a complete page IR inside ```ir-page markers:

```ir-page
{
  "$id": "page-name",
  "route": "/route",
  "title": "Page Title",
  "state": {},
  "root": {
    "node": "Stack",
    "gap": "lg",
    "padding": "lg",
    "children": [...]
  }
}
```

## NODE TYPES AVAILABLE

Layout: Stack (vertical), Row (horizontal), Grid (grid), Spacer, Divider
Content: Text, Icon, Image, Avatar, Badge, Tag, Button, StatCard, EmptyState
Input: TextInput, TextArea, Select, Checkbox, Toggle, RadioGroup, DatePicker
Composite: DataTable, Form, Card, Tabs, Accordion, Chart
Control: Slot (conditional), Repeater (loop), AsyncSlot (async data)

## KEY PROPERTIES

### Layout
- Stack/Row: gap (xs|sm|md|lg|xl), padding, align (start|center|end), justify (start|center|end|between)
- Grid: columns (number), gap

### Text
- typography: heading-1, heading-2, heading-3, body, body-sm, caption, overline
- weight: normal, medium, semibold, bold
- color: primary, muted, danger, success, warning, default

### Spacing tokens
xs = 4px, sm = 8px, md = 16px, lg = 24px, xl = 32px

## CONVERSION RULES

1. **Spatial Analysis**: Determine if elements are stacked vertically (Stack), side by side (Row), or in a grid (Grid)
2. **Spacing**: Map pixel gaps to the nearest token: 0-6px→xs, 7-12px→sm, 13-20px→md, 21-28px→lg, 29+px→xl
3. **Typography**: Map font sizes: 24px+→heading-1, 20px→heading-2, 18px→heading-3, 14px→body, 12px→caption
4. **Colors**: Map to tokens when possible. Use muted for secondary text, primary for interactive elements
5. **Components**: Identify buttons, badges, inputs, cards, tables by their visual appearance
6. **Repeated elements**: Use Repeater with a template for lists of similar items
7. **Data binding**: Use {{item.field}} for dynamic content, source:dataName for data fetching
8. **Responsive**: Assume desktop-first. Use responsive columns for Grid: {"default": 1, "md": 2, "lg": 3}
9. **Cards**: Group related content in Card nodes with appropriate padding
10. **Tables**: Use DataTable for tabular data with columns definition

## IMPORTANT
- Produce VALID JSON — double-check all brackets and commas
- Every node MUST have a "node" property
- Stack/Row/Grid/Card must have "children" array
- Text must have "content" string
- Button must have "label" string
- Use realistic placeholder data for content (not "lorem ipsum")
"""


async def run_figma_ir_agent(
    figma_context: dict,
    page_name: str = "figma-page",
    route: str = "/",
) -> AsyncIterator[Message]:
    """Convert Figma design context to IR.

    Args:
        figma_context: Dict with keys like 'screenshot', 'code', 'annotations', 'tokens'
            (from the Figma MCP server's get_design_context).
        page_name: ID for the generated page.
        route: Route path for the generated page.

    Yields:
        Agent messages. Final result contains ```ir-page block.
    """
    # Build prompt from Figma context
    parts = [f"## Target Page\nID: {page_name}\nRoute: {route}\n"]

    if figma_context.get("code"):
        parts.append(f"## Figma Component Code Hints\n```\n{figma_context['code']}\n```")

    if figma_context.get("annotations"):
        parts.append(f"## Design Annotations\n{figma_context['annotations']}")

    if figma_context.get("tokens"):
        parts.append(f"## Design Tokens\n```json\n{json.dumps(figma_context['tokens'], indent=2)}\n```")

    if figma_context.get("screenshot"):
        parts.append("## Screenshot\n(See the attached screenshot image for the visual design)")

    parts.append(
        "\nAnalyze this design and produce a complete page IR with proper layout, "
        "components, typography, and spacing. Output the IR inside ```ir-page markers."
    )

    user_prompt = "\n\n".join(parts)

    messages = query(
        prompt=user_prompt,
        options=ClaudeAgentOptions(
            system_prompt=FIGMA_IR_SYSTEM_PROMPT,
            allowed_tools=[],
            max_turns=3,
            model="claude-sonnet-4-6",
        ),
    )

    async for message in messages:
        yield message


def extract_page_ir(text: str) -> dict | None:
    """Extract a PageIR from agent response text.

    Looks for ```ir-page ... ``` blocks and parses the JSON.
    Returns None if no valid IR found.
    """
    import re

    match = re.search(r"```ir-page\s*\n(.*?)```", text, re.DOTALL)
    if not match:
        # Try plain JSON object
        match = re.search(r'\{\s*"\$id".*?\n\}', text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    try:
        return json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        logger.warning("Failed to parse Figma IR: %s", match.group(1)[:200])
        return None

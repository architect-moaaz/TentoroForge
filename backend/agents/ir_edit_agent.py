"""IR Edit Agent — processes user instructions and returns IR operations.

Instead of rewriting code, this agent understands the IR schema and produces
structured operations (setProp, addChild, removeChild, etc.) that the IR
system applies deterministically.

For simple edits (text changes, prop tweaks), this is instant and free compared
to the LLM rewriting entire files.
"""

import json
import logging
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — teaches the LLM the IR operation language
# ---------------------------------------------------------------------------

IR_EDIT_SYSTEM_PROMPT = r"""You are an IR (Intermediate Representation) editor for a UI builder platform.

## YOUR JOB
Given a user instruction and the current page IR (JSON), produce a list of IR operations to apply.
Do NOT generate code. Do NOT write files. Only output structured IR operations.

## IR OPERATION TYPES

```json
{ "type": "setProp", "path": [0, 1], "prop": "content", "value": "New text" }
```
Changes a property on the node at the given path.

```json
{ "type": "addChild", "path": [0], "index": 2, "node": { "node": "Text", "content": "Hello" } }
```
Inserts a new node as a child at the given index.

```json
{ "type": "removeChild", "path": [0], "index": 1 }
```
Removes the child at the given index from the parent at path.

```json
{ "type": "moveChild", "path": [], "from": [0], "fromIndex": 2, "to": [0], "toIndex": 0 }
```
Moves a child from one position to another.

```json
{ "type": "wrapWith", "path": [0, 1], "wrapper": { "node": "Card", "padding": "md" } }
```
Wraps the node at path inside a new container node.

```json
{ "type": "unwrap", "path": [0, 1] }
```
Removes a container node, promoting its children to the parent.

```json
{ "type": "duplicate", "path": [0, 1] }
```
Duplicates the node at path, inserting the copy right after it.

```json
{ "type": "replace", "path": [0, 1], "node": { "node": "Button", "label": "Click" } }
```
Replaces the node at path entirely.

## NODE PATH

A path is an array of indices from the root node's children:
- `[0]` = root.children[0]
- `[0, 1]` = root.children[0].children[1]
- `[2, 0, 3]` = root.children[2].children[0].children[3]

## AVAILABLE NODE TYPES

Layout: Stack, Row, Grid, Spacer, Divider
Content: Text, Icon, Image, Avatar, Badge, Tag, Button, StatCard, EmptyState, Skeleton
Input: TextInput, TextArea, Select, Checkbox, Toggle, RadioGroup, DatePicker, FilePicker
Composite: DataTable, Form, Card, Tabs, Accordion, Chart, ModalTrigger
Control: Slot, Repeater, AsyncSlot, Custom

## NODE PROPERTIES (common)

Text: content, typography (heading-1/heading-2/heading-3/body/body-sm/caption), weight, color, align, truncate
Button: label, variant (primary/secondary/ghost/outline/danger/link), size (sm/md/lg), icon, action
Badge: content, variant, colorMap, size
TextInput: bind, label, placeholder, type, icon, debounce, required
Select: bind, label, options, searchable, placeholder
Stack/Row: gap (xs/sm/md/lg/xl), padding, align, justify, width, height, scroll
Grid: columns, gap, padding
Card: padding, hoverable, border
DataTable: data, columns, pagination, sorting, onRowClick

## ACTIONS
Navigate: { "type": "navigate", "to": "/path" }
Set State: { "type": "setState", "path": "field", "value": "new" }
Mutate: { "type": "mutate", "source": "dataSourceName" }
Toast: { "type": "toast", "variant": "success", "message": "Done!" }
Open Modal: { "type": "openModal", "modal": "modal-name" }
Sequence: { "type": "sequence", "steps": [...actions] }

## OUTPUT FORMAT

Respond with ONLY a JSON array of operations wrapped in ```ir-ops markers:

```ir-ops
[
  { "type": "setProp", "path": [0, 0], "prop": "content", "value": "Updated Title" },
  { "type": "addChild", "path": [0], "index": 2, "node": { "node": "Button", "label": "New Button", "variant": "primary" } }
]
```

## RULES
1. Analyze the current IR to find the correct paths for the nodes you want to modify.
2. Use the MINIMUM number of operations. Don't rebuild what you can setProp.
3. For text changes, use setProp with prop="content" or prop="label".
4. For style changes, use setProp with the appropriate token value.
5. For adding new components, use addChild with a complete node definition.
6. For structural changes, prefer wrapWith/unwrap over remove+add.
7. Verify paths are correct by counting children in the IR tree.
"""


async def run_ir_edit_agent(
    page_ir: dict,
    user_instruction: str,
    data_sources: dict | None = None,
) -> AsyncIterator[Message]:
    """Run the IR edit agent to produce operations from a user instruction.

    Args:
        page_ir: The current page IR (single page, not full AppIR).
        user_instruction: What the user wants to change.
        data_sources: Available data sources (optional context).

    Yields:
        Messages from the agent. The final result contains ```ir-ops block.
    """
    # Build the user prompt with current IR context
    ir_json = json.dumps(page_ir, indent=2)

    user_prompt = f"""## Current Page IR

```json
{ir_json}
```

{f"## Available Data Sources" + chr(10) + json.dumps(data_sources, indent=2) if data_sources else ""}

## User Instruction

{user_instruction}

Analyze the IR tree, find the correct node paths, and produce the minimal set of IR operations to fulfill this instruction.
"""

    messages = query(
        prompt=user_prompt,
        options=ClaudeAgentOptions(
            system_prompt=IR_EDIT_SYSTEM_PROMPT,
            allowed_tools=[],  # No tools — pure text output
            max_turns=3,
            model="claude-sonnet-4-6",
        ),
    )

    async for message in messages:
        yield message


def extract_ir_operations(text: str) -> list[dict] | None:
    """Extract IR operations from agent response text.

    Looks for ```ir-ops ... ``` blocks and parses the JSON.
    Returns None if no valid operations found.
    """
    import re

    # Find ir-ops code block
    match = re.search(r"```ir-ops\s*\n(.*?)```", text, re.DOTALL)
    if not match:
        # Try plain JSON array
        match = re.search(r"\[\s*\{.*?\}\s*\]", text, re.DOTALL)
        if not match:
            return None
        try:
            ops = json.loads(match.group(0))
            if isinstance(ops, list):
                return ops
        except json.JSONDecodeError:
            return None
        return None

    try:
        ops = json.loads(match.group(1).strip())
        if isinstance(ops, list):
            return ops
    except json.JSONDecodeError:
        logger.warning("Failed to parse IR operations: %s", match.group(1)[:200])
        return None

    return None

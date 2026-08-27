"""Figma-to-IR Converter — converts Figma MCP code output to IR page skeletons.

Uses the Figma MCP's `get_design_context` to get pixel-accurate React+Tailwind
code for each frame, then has an LLM convert that JSX to IR nodes.

This produces much higher fidelity than screenshot-based analysis because
the MCP gives exact colors, layout structure, spacing, and text content.

Flow:
  1. Call Figma MCP get_design_context per frame → React+Tailwind JSX
  2. LLM converts JSX → IR skeleton with $slot markers for data areas
  3. Slot filler replaces $slots with entity bindings
  4. IR compiler produces final TSX
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# The system prompt teaches the LLM the JSX-to-IR mapping rules
JSX_TO_IR_SYSTEM_PROMPT = r"""You convert React+Tailwind JSX code (from Figma) into IR (Intermediate Representation) JSON.

## Mapping Rules

### Layout Elements
- `<div className="flex flex-col ...">` → `{ "node": "Stack", ... }`
- `<div className="flex flex-row ...">` or `<div className="flex ...">` → `{ "node": "Row", ... }`
- `<div className="grid grid-cols-N ...">` → `{ "node": "Grid", "columns": N, ... }`

### Content Elements
- `<p>`, `<h1>`-`<h6>`, `<span>` with text → `{ "node": "Text", "content": "...", "typography": "heading-N|body|body-sm|caption" }`
- `<img src="...">` → `{ "node": "Image", "src": "...", ... }`
- `<button>` → `{ "node": "Button", "label": "...", "variant": "primary|secondary|ghost" }`
- `<input>` → `{ "node": "TextInput", "placeholder": "...", "label": "..." }`
- `<select>` → `{ "node": "Select", ... }`

### Style Extraction
- Extract exact colors from Tailwind classes or style props: `text-[#841013]` → `"color": "#841013"`
- Extract background: `bg-[#841013]` or `style={{ background: "..." }}` → use on Stack/Row node
- Extract spacing from gap/padding classes: `gap-4` → `"gap": "md"`, `p-6` → `"padding": "lg"`
- Extract width: `w-1/2` → `"width": "50%"`, `w-full` → `"width": "full"`
- Extract border radius: `rounded-lg` → keep as style property

### Data-Bound Areas
When you see content that looks like dynamic data (tables, lists of cards, form fields for CRUD),
replace them with PlaceholderSlot nodes:
- Tables → `{ "node": "PlaceholderSlot", "$slot": "entity-table", "entity": "EntityName" }`
- Forms → `{ "node": "PlaceholderSlot", "$slot": "entity-form", "entity": "EntityName" }`
- Stat cards → `{ "node": "PlaceholderSlot", "$slot": "stat-cards" }`

### Preserve Branding
- Logo images, app names, taglines → keep as concrete Image/Text nodes with actual values
- Background gradients → preserve as style properties
- Brand colors → use exact hex values from the JSX

### Style Property on Nodes
For styles that don't map to IR tokens, use a `"style"` property with a CSS object:
```json
{ "node": "Stack", "style": { "background": "linear-gradient(135deg, #841013, #9f5253)" } }
```

## Output Format

Produce a single PageIR JSON wrapped in ```ir-page markers:

```ir-page
{
  "$id": "page-id",
  "route": "/route",
  "title": "Page Title",
  "root": { "node": "Stack", "children": [...] }
}
```

## Rules
1. PRESERVE exact colors, gradients, spacing from the JSX
2. Use PlaceholderSlot ONLY for data-bound areas (tables, forms, dynamic lists)
3. Keep decorative elements as concrete IR nodes
4. The IR must visually match the original Figma design when rendered
5. Keep the node tree reasonably flat — don't over-nest
"""


async def convert_figma_frame_to_ir(
    figma_code: str,
    page_id: str,
    route: str,
    title: str,
    entity_names: list[str] | None = None,
) -> dict | None:
    """Convert Figma MCP JSX code to an IR page skeleton.

    Args:
        figma_code: React+Tailwind JSX from Figma MCP get_design_context
        page_id: The $id for the page
        route: The route for the page
        title: The page title
        entity_names: Available entity names for PlaceholderSlot mapping

    Returns:
        PageIR dict or None if conversion fails
    """
    from services.agent_messages import ClaudeAgentOptions
    from services.sdk_agent_runner import query
    from services.agent_messages import AssistantMessage, ResultMessage, TextBlock

    os.environ.pop("CLAUDECODE", None)
    os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)

    entity_list = ", ".join(entity_names) if entity_names else "none specified"

    # Truncate very long JSX to avoid token limits
    code = figma_code
    if len(code) > 30000:
        code = code[:30000] + "\n// ... (truncated)"

    user_prompt = f"""Convert this Figma React+Tailwind code to IR JSON.

Page ID: {page_id}
Route: {route}
Title: {title}
Available entities: {entity_list}

## Figma JSX Code:

```tsx
{code}
```

Convert this to IR format. Preserve the exact visual design — colors, layout, spacing.
Use PlaceholderSlot for any data tables, forms, or dynamic lists.
Output a single PageIR JSON in ```ir-page markers."""

    options = ClaudeAgentOptions(
        system_prompt=JSX_TO_IR_SYSTEM_PROMPT,
        allowed_tools=[],
        permission_mode="bypassPermissions",
        max_turns=3,
        model="claude-sonnet-4-6",
    )

    response_text = ""
    async for message in query(prompt=user_prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    response_text += block.text
        elif isinstance(message, ResultMessage):
            pass

    # Extract IR page
    from services.json_extractor import extract_json
    result = extract_json(response_text, marker="```ir-page", expect_type=dict)

    if result:
        # Ensure required fields
        result.setdefault("$id", page_id)
        result.setdefault("route", route)
        result.setdefault("title", title)
        logger.info("Figma→IR conversion successful for %s (%s)", page_id, route)
    else:
        logger.warning("Figma→IR conversion failed for %s", page_id)

    return result


async def fetch_figma_code_for_frame(
    file_key: str,
    node_id: str,
    output_dir: str | None = None,
) -> str | None:
    """Load pre-fetched Figma MCP code for a frame.

    The Figma MCP get_design_context is only available in the Claude Code
    session (not in backend subprocess agents). So we pre-fetch the code
    via the /api/projects/{id}/design/fetch-figma endpoint and save it
    to .design/mcp-code/{node_id}.tsx files.

    This function reads those cached files.

    Returns the JSX code string or None if not available.
    """
    if not output_dir:
        return None

    from pathlib import Path
    safe_id = node_id.replace(":", "-")
    code_file = Path(output_dir) / ".design" / "mcp-code" / f"{safe_id}.tsx"

    if code_file.exists():
        code = code_file.read_text(encoding="utf-8")
        logger.info("Loaded MCP code for %s (%d chars)", node_id, len(code))
        return code

    logger.info("No pre-fetched MCP code for frame %s", node_id)
    return None


def save_figma_mcp_code(
    output_dir: str,
    node_id: str,
    code: str,
) -> str:
    """Save Figma MCP get_design_context output to disk.

    Called by the design router endpoint that receives MCP code
    (fetched by Claude Code which has MCP access).

    Returns the saved file path.
    """
    from pathlib import Path
    mcp_dir = Path(output_dir) / ".design" / "mcp-code"
    mcp_dir.mkdir(parents=True, exist_ok=True)

    safe_id = node_id.replace(":", "-")
    code_file = mcp_dir / f"{safe_id}.tsx"
    code_file.write_text(code, encoding="utf-8")
    logger.info("Saved MCP code for %s → %s", node_id, code_file)
    return str(code_file)


def build_figma_code_from_styles(styles_json: dict) -> str:
    """Build a simplified JSX representation from the styles.json extracted during prefetch.

    This is a fallback when the Figma MCP is not available.
    Converts the style tree into pseudo-JSX that the LLM can understand.
    """
    def _node_to_jsx(node: dict, depth: int = 0) -> str:
        indent = "  " * depth
        node_type = node.get("type", "FRAME")
        name = node.get("name", "")
        children = node.get("children", [])

        # Build style string
        styles = []
        if node.get("fills"):
            for fill in node["fills"]:
                if fill.get("type") == "SOLID" and fill.get("color"):
                    styles.append(f'background: "{fill["color"]}"')
                elif fill.get("type") == "GRADIENT_LINEAR" and fill.get("stops"):
                    colors = ", ".join(f'{s["color"]} {int(s["position"]*100)}%' for s in fill["stops"])
                    styles.append(f'background: "linear-gradient({colors})"')

        if node.get("layout"):
            layout = node["layout"]
            direction = layout.get("direction", "column")
            styles.append(f'display: "flex"')
            styles.append(f'flexDirection: "{direction}"')
            if layout.get("gap"):
                styles.append(f'gap: {layout["gap"]}')

        width = node.get("width", "")
        height = node.get("height", "")

        # Build tag
        if node_type == "TEXT":
            text = node.get("text", "")
            text_style = node.get("textStyle", {})
            font_size = text_style.get("fontSize", 14)
            color = node.get("textColor", "")
            return f'{indent}<p style={{{{ fontSize: {font_size}, color: "{color}" }}}}>{text}</p>'

        style_str = ", ".join(styles) if styles else ""
        tag_open = f'{indent}<div data-name="{name}" style={{{{ {style_str} }}}}'

        if not children:
            if node.get("imagePath"):
                return f'{indent}<img src="{node["imagePath"]}" alt="{name}" />'
            return f'{tag_open} />'

        lines = [f'{tag_open}>']
        for child in children:
            lines.append(_node_to_jsx(child, depth + 1))
        lines.append(f'{indent}</div>')
        return "\n".join(lines)

    return _node_to_jsx(styles_json)


# ---------------------------------------------------------------------------
# Figma JSX → Annotated HTML (AHTML) conversion
# ---------------------------------------------------------------------------

STYLES_TO_AHTML_SYSTEM_PROMPT = r"""You convert a Figma design tree (node hierarchy with styles) into annotated HTML that preserves the exact layout and visual design.

## Input Format
The input is a Figma design tree where each node has:
- `type`: FRAME, TEXT, RECTANGLE, VECTOR, etc.
- `name`: designer's layer name (often semantic: "Sign in Form", "Email Input", "Button")
- `fills`: background colors/gradients
- `layout`: flex direction, gap, padding, alignment
- `width`/`height`: dimensions in pixels
- `textStyle`: font size, weight, etc.
- `text`: actual text content (for TEXT nodes)
- `children`: child nodes

## Output Rules
1. Convert the tree to semantic HTML with Tailwind CSS classes
2. Map Figma flex layout → Tailwind flex classes (flex-col, flex-row, gap-N, p-N, items-center, justify-between)
3. Map Figma fills → Tailwind bg colors: use bg-[#hex] for exact colors
4. Map Figma text styles → Tailwind text classes (text-sm, text-xl, font-bold, text-[#hex])
5. Map Figma dimensions → Tailwind width/height where meaningful (w-full, h-screen, max-w-md, etc.)
6. **IMAGE ASSETS**: When a node has an `imagePath` field, ALWAYS render it as `<img src="{imagePath}" alt="{name}" class="..." />` with appropriate size classes. NEVER use placeholder gray boxes for image nodes — they have real image files at the imagePath.
7. **SVG ICONS**: For VECTOR nodes or nodes named "Icon", "Logo", or with an imagePath, render as `<img>` with the imagePath, sized appropriately (e.g., `w-6 h-6` for icons, original dimensions for logos).
8. Recognize semantic patterns from layer names:
   - "Form", "Input", "Email Input" → <form>, <input> with data-bind
   - "Button" → <button> with data-action
   - "Table", "List" → data-slot="entity-table"
   - "Card" → data-component="Card"
   - "Nav", "Sidebar" → semantic nav/aside elements
9. Add data-* annotations for interactive elements:
   - Forms → data-component="Form" data-bind="state:form"
   - Inputs → data-bind="state:form.fieldName"
   - Buttons → data-action="navigate" or data-action="mutate"
   - Repeated patterns → data-repeat="items"
10. PRESERVE exact colors as bg-[#hex] and text-[#hex]
11. PRESERVE exact spacing using Tailwind gap/padding classes
12. Output a COMPLETE page wrapped in <div data-page-id="..." data-route="..." data-title="...">

## Output
Return ONLY the HTML inside ```html markers.
"""


async def convert_figma_styles_to_ahtml(
    styles_data: dict,
    page_id: str,
    route: str,
    title: str,
    entity_names: list[str] | None = None,
) -> str | None:
    """Convert a Figma styles.json frame directly to annotated HTML.

    This produces much higher fidelity than the two-step styles→pseudo-JSX→IR
    path because it sends the full node tree to the LLM with all style data.
    """
    import re
    from services.sdk_agent_runner import query
    from services.agent_messages import AssistantMessage, TextBlock

    os.environ.pop("CLAUDECODE", None)
    os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)

    # Build a clean representation of the Figma tree
    def clean_node(node: dict, depth: int = 0) -> dict:
        """Extract relevant style info from a Figma node, limiting depth."""
        result: dict[str, Any] = {
            "type": node.get("type", "FRAME"),
            "name": node.get("name", ""),
        }

        # Image / SVG path (downloaded local asset)
        if node.get("imagePath"):
            result["imagePath"] = node["imagePath"]
        elif node.get("id"):
            # Use node ID to construct image path (e.g., "node_1_7.svg")
            node_id = node["id"].replace(":", "_")
            result["imagePath"] = f"/images/node_{node_id}.svg"

        # Fills (background colors)
        if node.get("fills"):
            colors = []
            for fill in node["fills"]:
                if fill.get("type") == "SOLID" and fill.get("color"):
                    colors.append(fill["color"])
            if colors:
                result["bg"] = colors[0] if len(colors) == 1 else colors

        # Layout
        if node.get("layout"):
            layout = node["layout"]
            result["layout"] = {
                k: v for k, v in layout.items()
                if k in ("direction", "gap", "padding", "alignItems", "justifyContent")
                and v is not None
            }

        # Dimensions
        w, h = node.get("width"), node.get("height")
        if w: result["width"] = round(w)
        if h: result["height"] = round(h)

        # Text
        if node.get("type") == "TEXT":
            result["text"] = node.get("text", "")
            if node.get("textStyle"):
                ts = node["textStyle"]
                result["textStyle"] = {
                    k: v for k, v in ts.items()
                    if k in ("fontSize", "fontWeight", "letterSpacing", "lineHeight")
                }
            if node.get("textColor"):
                result["textColor"] = node["textColor"]

        # Border radius
        if node.get("cornerRadius"):
            result["radius"] = node["cornerRadius"]

        # Children (limit depth to avoid token explosion)
        if depth < 8 and node.get("children"):
            result["children"] = [clean_node(c, depth + 1) for c in node["children"]]

        return result

    clean_tree = clean_node(styles_data)

    entities_hint = ""
    if entity_names:
        entities_hint = f"\nAvailable entities for data binding: {', '.join(entity_names)}"

    user_prompt = f"""Convert this Figma design tree to annotated HTML.

Page: {title}
Route: {route}
Page ID: {page_id}{entities_hint}

```json
{json.dumps(clean_tree, indent=2)}
```

Create a pixel-accurate HTML page that preserves the Figma layout, colors, spacing, and typography.
Wrap in <div data-page-id="{page_id}" data-route="{route}" data-title="{title}">."""

    from services.agent_messages import ClaudeAgentOptions

    from services.sdk_agent_runner import query

    options = ClaudeAgentOptions(
        system_prompt=STYLES_TO_AHTML_SYSTEM_PROMPT,
        model="claude-sonnet-4-6",
        max_turns=1,
        permission_mode="bypassPermissions",
    )

    full_text = ""
    async for msg in query(prompt=user_prompt, options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    full_text += block.text

    # Extract HTML
    html_match = re.search(r"```html\s*\n(.*?)```", full_text, re.DOTALL)
    if html_match:
        html = html_match.group(1).strip()
        if f'data-page-id="{page_id}"' not in html:
            html = f'<div data-page-id="{page_id}" data-route="{route}" data-title="{title}">\n{html}\n</div>'
        return html

    generic_match = re.search(r"```\s*\n(.*?)```", full_text, re.DOTALL)
    if generic_match:
        html = generic_match.group(1).strip()
        if f'data-page-id="{page_id}"' not in html:
            html = f'<div data-page-id="{page_id}" data-route="{route}" data-title="{title}">\n{html}\n</div>'
        return html

    logger.error("Failed to extract AHTML from LLM for page %s", page_id)
    return None


JSX_TO_AHTML_SYSTEM_PROMPT = r"""You convert React+Tailwind JSX code (from Figma) into annotated HTML.

## What is Annotated HTML?
Plain HTML with Tailwind CSS classes and data-* attributes for logic:

### Rules
1. PRESERVE all Tailwind classes exactly as-is
2. PRESERVE all colors, spacing, layout structure
3. Convert className to class
4. Strip React-specific syntax (hooks, imports, JSX expressions)
5. Add data-* annotations for data-bound areas:
   - Tables/lists with dynamic data → `data-slot="entity-table" data-entity="EntityName"`
   - Forms → `data-slot="entity-form" data-entity="EntityName"`
   - Stats/KPIs → `data-slot="stat-cards" data-entity="EntityName"`
   - Search inputs → `data-bind="state:search"`
   - Buttons → `data-action="navigate" data-action-to="/path"`
6. Use `data-component` to hint complex components: DataTable, Form, Card, Tabs, Chart
7. Use `data-repeat="sourceName"` for repeated items
8. Use `data-field="fieldName"` inside repeated items

## Output
Return ONLY the HTML inside ```html markers. No explanations.
The HTML should be a complete <div data-page-id="..." data-route="..." data-title="..."> element.
"""


async def convert_figma_frame_to_ahtml(
    figma_code: str,
    page_id: str,
    route: str,
    title: str,
    entity_names: list[str] | None = None,
) -> str | None:
    """Convert Figma MCP JSX output directly to annotated HTML.

    This is simpler than converting to IR JSON because the output format
    (HTML+Tailwind+data-*) is much closer to the input (React+Tailwind JSX).

    Args:
        figma_code: React+Tailwind code from Figma MCP get_design_context.
        page_id: Page identifier.
        route: URL route for the page.
        title: Page title.
        entity_names: Optional list of entity names for slot detection.

    Returns:
        Annotated HTML string, or None if conversion fails.
    """
    import re
    from services.sdk_agent_runner import query
    from services.agent_messages import AssistantMessage, TextBlock

    os.environ.pop("CLAUDECODE", None)
    os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)

    entities_hint = ""
    if entity_names:
        entities_hint = f"\nAvailable entities: {', '.join(entity_names)}"

    user_prompt = f"""Convert this Figma React+Tailwind code to annotated HTML.

Page: {title}
Route: {route}
Page ID: {page_id}{entities_hint}

```jsx
{figma_code}
```

Output the annotated HTML wrapped in a <div data-page-id="{page_id}" data-route="{route}" data-title="{title}"> root element."""

    from services.agent_messages import ClaudeAgentOptions as _Opts
    _options = _Opts(
        system_prompt=JSX_TO_AHTML_SYSTEM_PROMPT,
        model="claude-sonnet-4-6",
        max_turns=1,
        permission_mode="bypassPermissions",
    )

    full_text = ""
    async for msg in query(prompt=user_prompt, options=_options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    full_text += block.text

    # Extract HTML from ```html markers
    html_match = re.search(r"```html\s*\n(.*?)```", full_text, re.DOTALL)
    if html_match:
        html = html_match.group(1).strip()
        # Ensure page wrapper exists
        if f'data-page-id="{page_id}"' not in html:
            html = f'<div data-page-id="{page_id}" data-route="{route}" data-title="{title}">\n{html}\n</div>'
        return html

    # Try generic code block
    generic_match = re.search(r"```\s*\n(.*?)```", full_text, re.DOTALL)
    if generic_match:
        html = generic_match.group(1).strip()
        if f'data-page-id="{page_id}"' not in html:
            html = f'<div data-page-id="{page_id}" data-route="{route}" data-title="{title}">\n{html}\n</div>'
        return html

    logger.error("Failed to extract annotated HTML from LLM response for page %s", page_id)
    return None

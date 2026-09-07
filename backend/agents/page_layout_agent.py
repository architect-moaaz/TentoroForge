"""Page Layout Agent — LLM generates page skeletons with $slot markers.

For each page in the plan, the LLM decides the spatial layout, visual
composition, and component arrangement. Data-bound areas are marked
with PlaceholderSlot nodes that the pattern library fills in.

Two modes:
  - Text mode: LLM designs layouts from scratch based on design spec + domain
  - Figma mode: LLM reproduces the Figma design's spatial structure with slots
"""

import json
import os
from pathlib import Path
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message


PAGE_LAYOUT_SYSTEM_PROMPT = r"""You are a UI/UX layout architect. Your job is to design the spatial structure of each page in an application using IR (Intermediate Representation) JSON.

You produce page skeletons — NOT complete pages. Content areas that display entity data are marked with PlaceholderSlot nodes. The pattern library fills these slots with the correct data bindings.

## IR Node Types You Can Use

**Layout:** Stack (vertical), Row (horizontal), Grid (columns)
**Content:** Text, Icon, Image, Avatar, Badge, Button, StatCard, EmptyState, Divider, Spacer
**Containers:** Card (with optional header, footer, padding, shadow)

**PlaceholderSlot** — marks a content area to be filled by the pattern library:
```json
{ "node": "PlaceholderSlot", "$slot": "slot-type", "entity": "EntityName" }
```

## Available Slot Types

| Slot Type | Purpose | Requires entity? |
|-----------|---------|-------------------|
| entity-table | Data table for browsing records | Yes |
| entity-form | Create/edit form | Yes |
| entity-detail | Detail view of a record | Yes |
| auth-form | Login or signup form (config.variant: "login"/"signup") | No |
| stat-cards | Dashboard stat cards | Optional (all entities if omitted) |
| crud-actions | Header with title + "New" button | Yes |
| detail-tabs | Tabbed content for entity | Yes |
| recent-items | Recent items table | Yes |
| search-bar | Search input | Optional |
| branding | App name and logo | No |
| features-list | Feature highlights | No |
| empty-state | Empty state placeholder | Optional |

## Design Properties

Use these on Stack/Row/Grid nodes:
- gap: "xs"|"sm"|"md"|"lg"|"xl"
- padding: "xs"|"sm"|"md"|"lg"|"xl" or { x, y, top, right, bottom, left }
- align: "start"|"center"|"end"|"stretch"
- justify: "start"|"center"|"end"|"between"|"around"
- width: "full"|"400px"|"50%"
- height: "screen"|"full"

Use these on Card nodes:
- padding: "md"|"lg"
- shadow: "sm"|"md"
- radius: "md"|"lg"

Use these on Text nodes:
- typography: "heading-1"|"heading-2"|"heading-3"|"body"|"body-sm"|"caption"
- color: "primary"|"secondary"|"muted"|"danger"|"success"
- weight: "bold"|"semibold"|"medium"|"normal"

## Page Types and Shell Awareness

Page types: `auth`, `dashboard`, `form`, `list`, `detail`.

Auth pages render bare. All other types render inside the app shell — emit content only, not navigation chrome.

## Rules

1. Every page must have a root Stack or Row node
2. Use PlaceholderSlot for ALL data-bound content — never hardcode entity fields
3. You CAN hardcode decorative/branding text (app name, taglines, section headers)
4. Login pages should be creative — split panels, branded sidebars, gradients are encouraged
5. Dashboards should have stat cards at top, then a grid of content sections
6. List pages need crud-actions (header) + entity-table
7. Detail pages need entity-detail or detail-tabs
8. Create/edit pages need entity-form
9. Keep the skeleton concise — ~10-30 nodes per page, not 100+

## Shell-Aware Output

If the page's `type` is `auth`, render the FULL page — including any
branding (logo, app name) and visual chrome. Auth pages render bare
without a shell wrapper.

For ALL OTHER page types, the page renders INSIDE an app shell that
already provides the header (logo + primary nav + user menu), optional
sidebar, and optional footer. Your page schema MUST NOT include:

- A top navigation bar with Buttons routing to other pages
- A sidebar with app navigation
- An app-name header or logo image
- A site footer with copyright / company links

Emit ONLY the content specific to THIS page:
- Page title (Heading) at the top
- Page-level actions (e.g., "Create new", "Export") in a Row beside the title
- The main content (forms, tables, cards, body sections)

The shell's <PageOutlet /> slot will host your content. Trust the shell
to provide all global chrome.

## Output Format

Produce ALL page skeletons in a single ```ir-skeletons code block as a JSON array:

```ir-skeletons
[
  {
    "$id": "page-id",
    "route": "/route",
    "title": "Page Title",
    "root": { "node": "Stack", "children": [...] }
  },
  ...
]
```
"""


FIGMA_LAYOUT_SYSTEM_PROMPT = r"""You are a UI/UX layout architect that reproduces Figma designs as IR (Intermediate Representation) JSON.

You receive Figma screenshots and must reproduce their EXACT spatial layout using IR nodes. Data-bound areas (tables, forms, lists) are marked with PlaceholderSlot nodes.

## Your Process

1. READ each reference*.png screenshot carefully
2. Identify the spatial structure: columns, rows, sidebars, headers, cards, sections
3. Identify data-bound areas: tables, forms, lists, stat cards
4. Reproduce the layout using IR nodes, placing PlaceholderSlot where data goes
5. PRESERVE: colors, spacing, proportions, visual hierarchy from the Figma design

## Key Rules

- Decorative elements (logos, taglines, icons, branding) → concrete IR nodes
- Data tables, forms, entity lists → PlaceholderSlot nodes
- Colors from the Figma design → use hex values directly (e.g., color: "#841013")
- Background colors → use fills property or Card with bg color
- Split layouts → use Row with width percentages
- The output must LOOK like the Figma design when rendered

## Same slot types and output format as the standard layout agent.
""" + PAGE_LAYOUT_SYSTEM_PROMPT.split("## Output Format")[1]


async def run_page_layout_agent(
    output_dir: str,
    plan: dict,
    design_spec: dict | None = None,
    domain_context: dict | None = None,
    figma_screenshots: list[str] | None = None,
    page_type: str | None = None,
) -> AsyncIterator[Message]:
    """Generate page skeletons with PlaceholderSlot markers.

    In Figma mode (screenshots provided), reproduces the Figma layout.
    In text mode, generates creative layouts based on the design spec.
    """
    os.environ.pop("CLAUDECODE", None)
    os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)

    is_figma = bool(figma_screenshots and len(figma_screenshots) > 0)
    domain_label = domain_context.get("domain", "General") if domain_context else "General"
    entities = plan.get("data_models", [])
    pages = plan.get("pages", [])

    # Build entity summary
    entity_names = [e.get("name", "?") for e in entities]
    entity_list = ", ".join(entity_names)

    # Build page list
    page_lines = []
    for p in pages:
        page_lines.append(f"  - route={p.get('route', '?')}: {p.get('description', p.get('name', ''))}")

    # Design spec summary
    design_section = ""
    if design_spec:
        colors = design_spec.get("colorPalette", {})
        layout = design_spec.get("layout", {})
        design_section = f"""
## Design Spec (from Design Agent)
- Primary: {colors.get('primary', '?')}, Secondary: {colors.get('secondary', '?')}
- Navigation: {layout.get('navigation', '?')}
- Density: {layout.get('density', '?')}
- Border radius: {layout.get('borderRadius', '?')}
- Entity patterns: {json.dumps(design_spec.get('entityPatterns', {}))}
"""

    # Figma section
    figma_section = ""
    if is_figma:
        figma_section = f"""
## Figma Screenshots Available
Read these screenshots and reproduce their spatial layout:
{chr(10).join(f'- `{Path(s).name}`' for s in figma_screenshots)}

IMPORTANT: The generated layout must visually match the Figma design.
Use actual colors, spacing, and proportions from the screenshots.
"""

    user_prompt = f"""Generate page layout skeletons for this application.

## App: {plan.get('module_name', 'App')}
Description: {plan.get('description', '')}
Domain: {domain_label}

## Entities: {entity_list}

## Pages to generate:
{chr(10).join(page_lines)}

Also generate:
- /login (authentication page)
- /signup (registration page)
- /dashboard (main overview page)
{design_section}{figma_section}
Generate a skeleton for EACH page listed above. Use PlaceholderSlot nodes for all data-bound content.
{f"Page type: {page_type}" if page_type else ""}
"""

    system = FIGMA_LAYOUT_SYSTEM_PROMPT if is_figma else PAGE_LAYOUT_SYSTEM_PROMPT

    options = ClaudeAgentOptions(
        system_prompt=system,
        allowed_tools=["Read"] if is_figma else [],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=10,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message


def extract_skeletons(text: str) -> list[dict] | None:
    """Extract page skeletons from ```ir-skeletons markers."""
    from services.json_extractor import extract_json

    # Try primary marker first, then alternates
    for marker in ("```ir-skeletons", "```ir-skeleton", "```json"):
        result = extract_json(text, marker=marker, expect_type=list)
        if result is not None:
            return result

    return None

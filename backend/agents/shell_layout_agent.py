"""Shell Layout Agent — LLM picks an app shell flavor + composes regions.

Given the plan, nav-flow, brand, and domain context, the agent selects one
of four layout flavors (A-D) and emits a shell.json PageV2 schema with
header, optional sidebar, and optional footer regions annotated with
data-shell-region.  Exactly one PageOutlet node marks where page content
slots in.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SHELL_LAYOUT_SYSTEM_PROMPT = r"""You are an app shell architect. Given an app's plan, brand, and domain
context, design ONE app shell schema — the persistent chrome (header,
optional sidebar, optional footer) that wraps every authenticated page.

Your output is a single PageV2 JSON schema. Key constraints:

1. EXACTLY ONE PageOutlet node in the tree (type "PageOutlet", id "page-outlet")
   — this is where the current page's content slots in.

2. CHOOSE the shell structure THIS app's information architecture wants.
   Do NOT default to a dark-sidebar admin layout just because an app is data-heavy.
   Two apps in different domains should have STRUCTURALLY DIFFERENT shells. Pick the frame
   the IA (primary vs utility destinations, their count, the core workflow) calls for.
   Possibilities (mix freely — these are options, NOT a single layout to copy):
   - Top-bar: horizontal primary nav in the header — focused tools, dashboards, apps
     with few primary destinations
   - Command-bar: top bar + a prominent global search/command palette — search-first or
     power-user apps
   - Sectioned sidebar: vertical nav grouped into labeled sections — broad IA with many
     grouped destinations (use this when the IA genuinely warrants it, not by default)
   - Icon-rail + content: a slim icon rail (labels on hover/expand) — dense apps wanting
     maximum content width
   - Split workspace: a left list/rail + a detail pane — inbox / triage / record-centric apps
   - Header + footer: marketing / content / public-facing apps

3. Annotate each region with `data-shell-region` so the editor knows what
   it is:
   - Header → "header"
   - Sidebar → "sidebar"
   - Footer → "footer"

4. For navigation buttons, use:
   { "type": "Button",
     "props": { "label": "Dashboard", "navigate": "/dashboard", "variant": "ghost" } }
   The navigate value MUST be a route declared in nav-flow.pages (shell:true
   pages only — never auth routes).

5. For "Sign in" or "Get Started" CTAs use workflow:auth.signIn / signUp
   (no hardcoded navigate). For "Logout" use workflow:auth.signOut.

6. Do not include data-bound content (no PlaceholderSlot nodes).

7. Total schema ≤ 150 nodes.

## Region content menus

**Header content** (pick 2-4 based on app_type):
- Logo + app name (always): Text node with variant "logo" or Image with src from brand.logoUrl
- Primary nav (Button per shell:true page)
- Search bar (Input with placeholder "Search..." — for e-commerce, docs, SaaS)
- Cart icon (e-commerce only)
- Notifications bell
- User menu (Avatar + dropdown — "Profile", "Settings", "Logout")
- CTAs (Get Started / Login — for marketing only)

**Sidebar content** (Flavors B / D, pick 2-3):
- Logo (top)
- Vertical nav-items (Button per shell page, variant=ghost)
- Section dividers
- User menu (bottom-aligned, optional)
- Collapse toggle (optional)

**Footer content** (Flavors C / D, pick based on app_type):
- Link-column grid: 3-4 columns × 3-6 links each
  - SaaS / marketing: Product / Company / Resources / Contact
  - E-commerce: Shop / Customer Service / About / Payment methods
  - Content / blog: Topics / Authors / About / Newsletter
- Newsletter signup (Form with email Input + Button)
- Social icons row (Link with icon prop)
- Payment method badges (e-commerce: Visa, Mastercard, etc.)
- Copyright row at the very bottom

## Flavor structures

**Flavor A — Top-header only** (SaaS dashboards, simple admin):
```
Stack flex-col min-h-screen
  Container data-shell-region="header"
    Row: logo + primary-nav + user-menu
  PageOutlet id="page-outlet"
```

**Flavor B — Sidebar + top-header** (data-heavy admin, CRMs):
```
Row flex-row h-screen
  Container data-shell-region="sidebar" className="hidden md:block w-[240px]"
    Stack: logo, nav-items (vertical), user-menu (bottom)
  Stack flex-col flex-1
    Container data-shell-region="header"
      Row: hamburger(md:hidden) + page-title + user-menu
    PageOutlet id="page-outlet"
```

**Flavor C — Header + footer** (marketing sites, content/blog, public-facing):
```
Stack flex-col min-h-screen
  Container data-shell-region="header"
    Row: logo + nav + CTAs (Get Started, Login)
  PageOutlet id="page-outlet" (flex-grow-1)
  Container data-shell-region="footer"
    Grid: link-columns, newsletter, social, copyright row
```

**Flavor D — Header + sidebar + footer** (e-commerce, docs):
```
Stack flex-col min-h-screen
  Container data-shell-region="header"
    Row: logo + primary-nav + search + cart + user
  Row flex-row flex-grow-1
    Container data-shell-region="sidebar"
      Stack: category/section nav
    PageOutlet id="page-outlet"
  Container data-shell-region="footer"
    Grid: link-columns, payment-methods, social, copyright
```

## Choosing the structure

There is NO fixed app_type→layout rule — that produced identical sidebars for every
business app. Instead, choose from the structures in section 2 based on the IA you are
given (primary vs utility destinations, their count, the core workflow) and the brand
character. A data-heavy CRM might be a top-bar workspace, a split inbox, or a sectioned
sidebar — pick what the app actually needs. Marketing/content → header+footer.
Reserve a sidebar for IAs with many grouped destinations; do not make it the default.

## Output format

Wrap the schema in fenced ```ir-shell markers:

```ir-shell
{
  "schemaVersion": "2.0",
  "title": "App Shell",
  "id": "shell",
  "children": [
    {
      "type": "Stack",
      "props": { "className": "min-h-screen flex flex-col" },
      "children": [
        {
          "type": "Container",
          "props": { "data-shell-region": "header", "className": "border-b" },
          "children": [
            {
              "type": "Row",
              "props": { "className": "px-6 py-4 items-center justify-between" },
              "children": [
                { "type": "Text", "props": { "content": "MyApp", "className": "font-bold text-lg" } },
                {
                  "type": "Row",
                  "props": { "className": "gap-2" },
                  "children": [
                    { "type": "Button", "props": { "label": "Dashboard", "navigate": "/dashboard", "variant": "ghost" } }
                  ]
                },
                {
                  "type": "Row",
                  "props": { "className": "gap-2 items-center" },
                  "children": [
                    { "type": "Avatar", "props": { "size": "sm" } },
                    { "type": "Button", "props": { "label": "Logout", "onClick": "workflow:auth.signOut", "variant": "ghost" } }
                  ]
                }
              ]
            }
          ]
        },
        { "type": "PageOutlet", "id": "page-outlet" }
      ]
    }
  ]
}
```

## Format reference (NOT a layout to copy): a sidebar example — shows PageOutlet + data-shell-region + nav Button mechanics. Do NOT reproduce this structure by default; choose the frame the IA wants (section 2).

```ir-shell
{
  "schemaVersion": "2.0",
  "title": "App Shell",
  "id": "shell",
  "children": [
    {
      "type": "Row",
      "props": { "className": "h-screen" },
      "children": [
        {
          "type": "Container",
          "props": { "data-shell-region": "sidebar", "className": "w-64 border-r flex flex-col" },
          "children": [
            { "type": "Text", "props": { "content": "CRMApp", "className": "font-bold text-lg px-4 py-6" } },
            {
              "type": "Stack",
              "props": { "className": "flex-1 gap-1 px-2" },
              "children": [
                { "type": "Button", "props": { "label": "Dashboard", "navigate": "/dashboard", "variant": "ghost" } },
                { "type": "Button", "props": { "label": "Contacts", "navigate": "/contacts", "variant": "ghost" } },
                { "type": "Button", "props": { "label": "Deals", "navigate": "/deals", "variant": "ghost" } }
              ]
            },
            { "type": "Button", "props": { "label": "Logout", "onClick": "workflow:auth.signOut", "variant": "ghost", "className": "mx-2 mb-4" } }
          ]
        },
        {
          "type": "Stack",
          "props": { "className": "flex-1 flex-col overflow-hidden" },
          "children": [
            {
              "type": "Container",
              "props": { "data-shell-region": "header", "className": "border-b px-6 py-3" },
              "children": [
                {
                  "type": "Row",
                  "props": { "className": "items-center justify-between" },
                  "children": [
                    { "type": "Text", "props": { "content": "", "className": "font-semibold" } },
                    { "type": "Avatar", "props": { "size": "sm" } }
                  ]
                }
              ]
            },
            { "type": "PageOutlet", "id": "page-outlet" }
          ]
        }
      ]
    }
  ]
}
```

## Example: Flavor C (marketing / content)

```ir-shell
{
  "schemaVersion": "2.0",
  "title": "App Shell",
  "id": "shell",
  "children": [
    {
      "type": "Stack",
      "props": { "className": "min-h-screen flex flex-col" },
      "children": [
        {
          "type": "Container",
          "props": { "data-shell-region": "header", "className": "border-b" },
          "children": [
            {
              "type": "Row",
              "props": { "className": "px-8 py-4 items-center justify-between max-w-7xl mx-auto" },
              "children": [
                { "type": "Text", "props": { "content": "SiteName", "className": "font-bold text-xl" } },
                {
                  "type": "Row",
                  "props": { "className": "gap-4" },
                  "children": [
                    { "type": "Button", "props": { "label": "Home", "navigate": "/", "variant": "ghost" } },
                    { "type": "Button", "props": { "label": "Blog", "navigate": "/blog", "variant": "ghost" } }
                  ]
                },
                {
                  "type": "Row",
                  "props": { "className": "gap-2" },
                  "children": [
                    { "type": "Button", "props": { "label": "Sign In", "onClick": "workflow:auth.signIn", "variant": "outline" } },
                    { "type": "Button", "props": { "label": "Get Started", "onClick": "workflow:auth.signUp", "variant": "default" } }
                  ]
                }
              ]
            }
          ]
        },
        { "type": "PageOutlet", "id": "page-outlet", "props": { "className": "flex-1" } },
        {
          "type": "Container",
          "props": { "data-shell-region": "footer", "className": "bg-gray-900 text-white" },
          "children": [
            {
              "type": "Grid",
              "props": { "cols": 4, "className": "max-w-7xl mx-auto px-8 py-12 gap-8" },
              "children": [
                {
                  "type": "Stack",
                  "props": { "className": "gap-3" },
                  "children": [
                    { "type": "Text", "props": { "content": "Product", "className": "font-semibold" } },
                    { "type": "Text", "props": { "content": "Features", "className": "text-sm text-gray-400" } },
                    { "type": "Text", "props": { "content": "Pricing", "className": "text-sm text-gray-400" } }
                  ]
                },
                {
                  "type": "Stack",
                  "props": { "className": "gap-3" },
                  "children": [
                    { "type": "Text", "props": { "content": "Company", "className": "font-semibold" } },
                    { "type": "Text", "props": { "content": "About", "className": "text-sm text-gray-400" } },
                    { "type": "Text", "props": { "content": "Blog", "className": "text-sm text-gray-400" } }
                  ]
                }
              ]
            },
            {
              "type": "Row",
              "props": { "className": "max-w-7xl mx-auto px-8 py-4 border-t border-gray-700 justify-between" },
              "children": [
                { "type": "Text", "props": { "content": "© 2024 SiteName. All rights reserved.", "className": "text-sm text-gray-400" } }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

## Responsive Rules — STRICT

Every shell layout MUST work at 375px (mobile) up to 1920px (desktop).

For Flavor B (sidebar + top-header) and Flavor D (header + sidebar + footer):
- Sidebar Container MUST have className "hidden md:block w-[240px]" so it
  hides on mobile and shows on tablet+
- Header MUST include a hamburger menu Button (icon="menu") visible only
  on mobile: className "md:hidden". The Button's workflow can be
  "shell.toggleSidebar" (handler doesn't need to exist yet — it's a hook)
- Page content Container should be flex-1 and never use a fixed width

For Flavor C (header + footer):
- Header's primary nav Row should include "flex-wrap" so nav items wrap
  on narrow viewports instead of overflowing
- Footer link-column Grid MUST use columns: 4 (the renderer compiles this
  to "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4" automatically)

For Flavor A (header only):
- Top nav-tab Row should include "flex-wrap" so 6+ tabs flow onto
  multiple lines on small screens instead of overflowing

Example responsive header for Flavor B:
```json
{
  "type": "Container",
  "props": {
    "data-shell-region": "header",
    "className": "flex items-center gap-3 px-4 py-3 border-b"
  },
  "children": [
    { "type": "Button",
      "props": { "icon": "menu", "variant": "ghost",
                 "className": "md:hidden",
                 "workflow": "shell.toggleSidebar",
                 "aria-label": "Open menu" } },
    { "type": "Text", "props": { "content": "App Name", "className": "font-bold text-lg" } },
    { "type": "Container", "props": { "className": "flex-1" } },
    { "type": "Avatar", "props": { "name": "User", "size": "sm" } }
  ]
}
```

Example responsive Flavor B sidebar (hidden on mobile, visible on tablet+):
```json
{
  "type": "Container",
  "props": { "data-shell-region": "sidebar", "className": "hidden md:block w-[240px] border-r flex flex-col" },
  "children": [...]
}
```

## VISUAL QUALITY — Required Patterns

### 1. Icons on every nav item

Every navigation Button MUST include an `icon` prop with a Lucide icon name. Never
emit a nav button without an icon.

| Nav item label                     | icon value              |
|------------------------------------|-------------------------|
| Dashboard                          | "home" or "layout-dashboard" |
| My Requests / Requests             | "file-text" or "inbox"  |
| Approvals                          | "check-circle" or "clipboard-check" |
| Calendar / Team Calendar           | "calendar"              |
| Tasks                              | "list-todo" or "check-square" |
| Workflows                          | "git-branch" or "workflow" |
| Admin / Settings                   | "settings"              |
| Analytics / Reports                | "bar-chart-2"           |
| Users / Team                       | "users"                 |
| Logout                             | "log-out"               |

Pick a reasonable Lucide icon for any nav item not listed above — never omit `icon`.

### 2. Sidebar nav button styling

Use `variant: "ghost"` for all sidebar nav items. Use `className: "justify-start w-full"`
so labels align left. Never use default (filled) variant for sidebar nav.

```json
{ "type": "Button",
  "props": {
    "label": "Dashboard",
    "icon": "home",
    "variant": "ghost",
    "navigate": "/dashboard",
    "className": "justify-start w-full"
  } }
```

### 3. Brand row — logo monogram + app name

Replace plain Text nodes with a Row containing a colored monogram Container and a Heading.
Use the first letter of the app name as the monogram. NEVER use an Image with a random
`src` URL for the logo unless the brand spec explicitly provides a logoUrl.

```json
{ "type": "Row",
  "props": { "className": "items-center gap-2 px-4 py-3 border-b" },
  "children": [
    { "type": "Container",
      "props": { "className": "h-8 w-8 rounded-md bg-primary text-primary-foreground flex items-center justify-center font-semibold text-sm" },
      "children": [ { "type": "Text", "props": { "content": "L" } } ] },
    { "type": "Heading", "props": { "content": "LeaveHub", "level": 4 } }
  ] }
```

### 4. Avatar with initials — NOT a random src

Always emit Avatar with `name` prop. Do NOT pass `src` unless given a real avatar URL
in the brand or user spec. Avatar auto-renders initials from `name`.

```json
{ "type": "Avatar", "props": { "name": "User", "size": "sm" } }
```

### 5. Header structure

For shell pages the header must be:
- Left: hamburger (mobile-only, `className: "md:hidden"`) + page title placeholder
- Center/right grow: search bar (only on dashboard-type apps)
- Right: notifications bell + user avatar

Use `flex items-center gap-3 px-4 py-2.5 border-b bg-card` on the header Container.

### 6. Spacing density

Use `py-1.5 px-3` for nav items via className on each Button — NOT `py-3 px-4`.
Sidebar should be compact (`text-sm`). Do not add extra padding that makes the sidebar
look like a low-density wireframe.

### 7. Sidebar width

Use `w-60` (240px) on desktop. Place the user menu + logout button at the bottom
of the sidebar, pinned with `mt-auto` or a spacer Container with `className: "flex-1"`.

## Domain Aesthetic

Map `app_type` to visual style conventions:

- **saas / dashboard / admin**: `bg-card` sidebar, ghost-button nav, search bar prominent
  in header, compact nav density (`text-sm gap-0.5`).
- **crm**: same as saas, plus a quick-add "+" icon Button in the header for new lead/deal.
- **marketing / landing**: NO sidebar; centered-logo header; CTA Buttons in header
  (`Get Started` variant default, `Sign In` variant outline).
- **ecommerce**: sidebar with category nav, header has cart icon (+badge) + search + user.
- **docs**: sidebar with nested sections (use Stack + section headings); right TOC rail
  as a second Container on the page content side.
- **content / blog**: simple top-nav (Posts | About | Subscribe), no sidebar.

## Format reference #2 (NOT a layout to copy): another sidebar example for mechanics only — pick a structure that fits THIS app's IA, which is often NOT a sidebar.

```ir-shell
{
  "schemaVersion": "2.0",
  "title": "App Shell",
  "id": "shell",
  "children": [{
    "type": "Row",
    "props": { "className": "min-h-screen" },
    "children": [
      {
        "type": "Container",
        "props": {
          "data-shell-region": "sidebar",
          "className": "hidden md:flex flex-col w-60 border-r bg-card"
        },
        "children": [
          { "type": "Row",
            "props": { "className": "items-center gap-2 px-4 py-3 border-b" },
            "children": [
              { "type": "Container",
                "props": { "className": "h-8 w-8 rounded-md bg-primary text-primary-foreground flex items-center justify-center font-semibold text-sm" },
                "children": [ { "type": "Text", "props": { "content": "L" } } ]
              },
              { "type": "Heading", "props": { "content": "LeaveHub", "level": 4 } }
            ]
          },
          { "type": "Stack",
            "props": { "className": "flex-1 p-2 gap-0.5" },
            "children": [
              { "type": "Button", "props": { "label": "Dashboard", "icon": "home", "variant": "ghost", "navigate": "/dashboard", "className": "justify-start w-full" } },
              { "type": "Button", "props": { "label": "My Requests", "icon": "file-text", "variant": "ghost", "navigate": "/requests", "className": "justify-start w-full" } },
              { "type": "Button", "props": { "label": "Approvals", "icon": "check-circle", "variant": "ghost", "navigate": "/approvals", "className": "justify-start w-full" } },
              { "type": "Button", "props": { "label": "Team Calendar", "icon": "calendar", "variant": "ghost", "navigate": "/calendar", "className": "justify-start w-full" } },
              { "type": "Button", "props": { "label": "Settings", "icon": "settings", "variant": "ghost", "navigate": "/settings", "className": "justify-start w-full" } }
            ]
          },
          { "type": "Row",
            "props": { "className": "items-center gap-2 px-3 py-3 border-t" },
            "children": [
              { "type": "Avatar", "props": { "name": "User", "size": "sm" } },
              { "type": "Stack", "props": { "className": "flex-1 gap-0" }, "children": [
                { "type": "Text", "props": { "content": "User Name", "className": "text-sm font-medium" } },
                { "type": "Text", "props": { "content": "user@example.com", "className": "text-xs text-muted-foreground" } }
              ] },
              { "type": "Button", "props": { "icon": "log-out", "variant": "ghost", "workflow": "auth.signOut", "aria-label": "Logout" } }
            ]
          }
        ]
      },
      {
        "type": "Stack",
        "props": { "className": "flex-1 flex-col" },
        "children": [
          {
            "type": "Container",
            "props": {
              "data-shell-region": "header",
              "className": "flex items-center gap-3 px-4 py-2.5 border-b bg-card"
            },
            "children": [
              { "type": "Button", "props": { "icon": "menu", "variant": "ghost", "className": "md:hidden", "workflow": "shell.toggleSidebar" } },
              { "type": "Container", "props": { "className": "flex-1" } },
              { "type": "Input", "props": { "name": "search", "type": "text", "placeholder": "Search...", "className": "max-w-xs" } },
              { "type": "Button", "props": { "icon": "bell", "variant": "ghost", "aria-label": "Notifications" } },
              { "type": "Avatar", "props": { "name": "User", "size": "sm" } }
            ]
          },
          { "type": "PageOutlet", "id": "page-outlet" }
        ]
      }
    ]
  }]
}
```

## Inputs you'll receive in the user prompt

- App description and inferred app_type (saas|admin|crm|marketing|content|ecommerce|docs)
- Brand spec: primary color, app name, optional logo URL
- nav-flow.json: list of pages with shell:true/false and route
- Domain context: persona, industry hints

You decide:
- Which flavor (A/B/C/D) based on app_type + shell page count
- What goes in each region (within the menus above)
- Layout polish (gaps, padding, alignment)

Output ONLY the ```ir-shell block. No commentary outside the fence.
"""


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------


async def run_shell_layout_agent(
    plan: dict,
    nav_flow: dict,
    brand: dict | None = None,
    domain_context: dict | None = None,
    design_spec: dict | None = None,
) -> AsyncIterator[Message]:
    """Generate one app-shell schema for the project.

    Args:
        plan: planner's output with pages list + optional app_type
        nav_flow: nav-flow.json (used for route references + shell membership)
        brand: brand spec (colors, app name, logo)
        domain_context: industry / persona info

    Yields:
        Agent messages. Final result contains ```ir-shell block.
    """
    from services.shell_context import build_shell_context
    parts: list[str] = []
    # Rich, divergence-pressuring context (IA grouping + design-language hints +
    # brand character + anti-default directive) replaces the bare app/brand dump.
    parts.append(build_shell_context(plan, nav_flow, design_spec, domain_context))
    parts.append("")
    parts.append("## Brand")
    if brand:
        parts.append(json.dumps(brand, indent=2))
    else:
        parts.append("(none)")
    parts.append("")
    parts.append("## Nav-flow")
    parts.append("```json")
    parts.append(json.dumps({
        "pages": nav_flow.get("pages", []),
        "auth_routes": nav_flow.get("auth_routes", []),
    }, indent=2))
    parts.append("```")
    parts.append("")
    parts.append(
        "Design the app shell. Honour the [DOMAIN PROFILE] in your system "
        "prompt — its `Color anchors` and `Typography` lines are hard "
        "constraints for the shell's logo colour, nav-button hover state, "
        "and any decorative chrome. Its `Design patterns common in this "
        "domain` should guide which nav-group labels you pick (e.g. "
        "'Self-Service Portal' → group My Requests + My Calendar; "
        "'Hierarchical Approval Workflows' → surface a Pending Approvals "
        "nav entry). Output ```ir-shell block only."
    )

    user_prompt = "\n".join(parts)

    # Build the [DOMAIN PROFILE] block from the dossier — shell_layout_agent
    # gets persona-free sections (pitfalls + patterns + visual) since the
    # dossier doesn't carry a shell persona. The visual section pins palette
    # + typography to dossier hexes/fonts so the shell matches the body.
    from services.domain_context import build_domain_profile
    domain_profile = build_domain_profile(domain_context, "shell_layout_agent")

    messages = query(
        prompt=user_prompt,
        options=ClaudeAgentOptions(
            system_prompt=SHELL_LAYOUT_SYSTEM_PROMPT + domain_profile,
            allowed_tools=[],
            max_turns=3,
            model="claude-sonnet-4-5-20250929",
        ),
    )
    async for message in messages:
        yield message


# ---------------------------------------------------------------------------
# Schema extraction
# ---------------------------------------------------------------------------


def extract_shell(text: str) -> dict | None:
    """Extract a shell schema from agent response text.

    Looks for ```ir-shell fenced JSON block and parses it.
    Falls back to any ```json or plain ``` fence that contains "schemaVersion".
    Returns None if no valid schema found.
    """
    m = re.search(r"```ir-shell\s*\n(.*?)```", text, re.DOTALL)
    if not m:
        # Fallback: any ```json or ``` fence containing a schemaVersion key
        m = re.search(
            r"```(?:json)?\s*\n(\{[^`]*?\"schemaVersion\"[^`]*?\})\s*```",
            text,
            re.DOTALL,
        )
        if not m:
            return None
    try:
        return json.loads(m.group(1).strip())
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse shell schema: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Integration helper
# ---------------------------------------------------------------------------


async def generate_shell_to_file(
    output_dir: str | Any,  # str | Path
    plan: dict,
    nav_flow: dict,
    brand: dict | None = None,
    domain_context: dict | None = None,
    design_spec: dict | None = None,
) -> dict | None:
    """Run the shell layout agent, validate, and write shell.json.

    Collects all text from agent messages, extracts the schema, runs
    shell_validator, and writes <output_dir>/src/schemas/shell.json.

    Returns the shell dict on success, or None if the agent produced no
    parseable schema.  Validation errors are logged as warnings but do not
    prevent the file from being written — the pipeline caller decides whether
    to abort.
    """
    from pathlib import Path
    from services.shell_validator import validate_shell

    # SP4: deterministic IA-driven shell FIRST. The LLM shell agent reliably produced
    # one structure (a slate sidebar) and ignored the design tokens. The deterministic
    # builder selects a frame (sidebar / top-bar / icon-rail) by the app's information
    # architecture and paints with the real palette — structurally varied, token-correct,
    # and instant (no slow bundled-CLI call). Falls through to the LLM only if it errors.
    shell = None
    try:
        from services.shell_guardrail import is_renderable_shell
        from services.shell_templates import build_shell_deterministic

        # Spec D Wave 6 — brief-first shell authoring. When
        # ``contracts/brief.json`` exists, the brief-driven bridge
        # ``build_shell_from_brief`` is the primary path (Wave 1 made
        # the brief the authority for palette + visual stance +
        # layout numerics). The legacy ``build_shell_deterministic``
        # is the fallback for briefless projects.
        _brief_dict: dict | None = None
        try:
            import json as _json
            from pathlib import Path as _Path
            _brief_path = _Path(output_dir) / "contracts" / "brief.json"
            if _brief_path.exists():
                _brief_dict = _json.loads(_brief_path.read_text())
        except Exception:  # pragma: no cover - defensive read
            _brief_dict = None

        if _brief_dict:
            from services.shell_from_brief import build_shell_from_brief
            _cand = build_shell_from_brief(
                _brief_dict,
                {"plan": plan, "nav_flow": nav_flow,
                 "brand": brand, "design_spec": design_spec},
            )
            _path_used = "brief"
        else:
            _cand = build_shell_deterministic(plan, nav_flow, brand, design_spec)
            _path_used = "deterministic"
        if is_renderable_shell(_cand):
            shell = _cand
            logger.info("[shell] %s frame=%s (skipping LLM shell agent)",
                        _path_used, _cand.get("frame"))
    except Exception as _det_e:  # never let the builder break shell generation
        logger.warning("[shell] deterministic builder error, using LLM: %s", _det_e)

    # Phase 6c — Shell Authority. When FORGE_SHELL_AUTHORITY is on the
    # deterministic builder is the SOLE writer for shell.json. If the
    # builder can't produce a renderable shell, do NOT fall back to the
    # LLM path — return None so the caller decides how to proceed (a
    # blank shell is preferable to an LLM-generated one that ignores
    # the design tokens). Fail-open on any import error.
    _shell_authority_on = False
    try:
        from services.artifact_authority import is_authority_enabled
        _shell_authority_on = is_authority_enabled("shell")
    except Exception:  # noqa: BLE001
        pass

    if shell is None and _shell_authority_on:
        logger.warning(
            "[shell] deterministic builder produced no renderable shell "
            "and FORGE_SHELL_AUTHORITY is on — refusing LLM fallback",
        )
        return None

    if shell is None:
        from services.agent_messages import AssistantMessage, TextBlock
        pieces: list[str] = []
        async for msg in run_shell_layout_agent(plan, nav_flow, brand, domain_context, design_spec):
            if isinstance(msg, AssistantMessage):
                for block in (msg.content or []):
                    if isinstance(block, TextBlock):
                        pieces.append(block.text)

        text = "".join(pieces)
        shell = extract_shell(text)
        if not shell:
            logger.warning("[shell] agent produced no parseable schema")
            return None

        # Renderability guardrail (SP3.1): the LLM shell is freely generated, so check it
        # renders (one PageOutlet, registered node types, has nav) and repair the cheap
        # faults (duplicate PageOutlet). Never worse than today: an unrepairable shell
        # keeps the original parsed output.
        from services.shell_guardrail import validate_shell as _guard_validate, repair_shell
        _g_issues = _guard_validate(shell)
        if _g_issues:
            logger.warning("[shell] renderability issues: %s", _g_issues)
            _repaired = repair_shell(shell)
            if _repaired is not None:
                shell = _repaired
                logger.info("[shell] guardrail repaired shell")
    else:
        # Deterministic path produced the shell — stamp the composer
        # marker so guards can key off it (assert-mode plumbing lives
        # in :mod:`services.artifact_authority`).
        try:
            _meta = shell.get("meta") if isinstance(shell, dict) else None
            if not isinstance(_meta, dict):
                _meta = {}
            _meta["shell_deterministic_composed"] = True
            if isinstance(shell, dict):
                shell["meta"] = _meta
        except Exception:  # noqa: BLE001 — never let stamping break the write
            pass

    errs = validate_shell(shell, nav_flow)
    if errs:
        logger.warning("[shell] validation errors: %s", errs)
        # Still write so the user can inspect; the pipeline can decide to fail

    # Normalize LLM-emitted prop shapes — most critical here is Button.variant
    # where shadcn-trained LLMs emit "default" (not in our enum). Without this
    # the renderer falls back to `⚠ Button: invalid props` on every nav item.
    # Also rewrites `content` → `root` and `layout` → `root` if present.
    from services.schema_normalizer import (
        normalize_v2_schema,
        apply_page_shell_layout_to_schema,
    )
    normalize_v2_schema(shell)
    # Apply the page-shell heuristic (Row{sidebar + main} → viewport-fill +
    # sticky sidebar + scrollable main). The Figma pipeline already runs this
    # for Figma-driven apps; we run it here for description-generated apps so
    # both pipelines produce the same layout when the shell has the pattern.
    shell_was_transformed = apply_page_shell_layout_to_schema(shell)

    schemas_dir = Path(output_dir) / "src" / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    (schemas_dir / "shell.json").write_text(json.dumps(shell, indent=2))
    logger.info("[shell] wrote %s", schemas_dir / "shell.json")

    # When the page-shell heuristic fired, the schema now references
    # `.sidebar-scroll` / `.main-scroll` class hooks. Ensure the project's
    # globals.css carries the matching scrollbar styles so the runtime
    # actually paints the thin slate / soft-white thumbs we promised.
    if shell_was_transformed:
        _ensure_scrollbar_styles(Path(output_dir))

    return shell


_SCROLLBAR_CSS_SENTINEL = "/* tentoroforge:shell-scrollbars */"
_SCROLLBAR_CSS = f"""
{_SCROLLBAR_CSS_SENTINEL}
.sidebar-scroll::-webkit-scrollbar,
.main-scroll::-webkit-scrollbar {{ width: 8px; height: 8px; }}
.sidebar-scroll::-webkit-scrollbar-track,
.main-scroll::-webkit-scrollbar-track {{ background: transparent; }}
.sidebar-scroll::-webkit-scrollbar-thumb {{
  background-color: rgba(255, 255, 255, 0.18);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: content-box;
}}
.sidebar-scroll::-webkit-scrollbar-thumb:hover {{ background-color: rgba(255, 255, 255, 0.32); }}
.main-scroll::-webkit-scrollbar-thumb {{
  background-color: rgba(15, 23, 42, 0.18);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: content-box;
}}
.main-scroll::-webkit-scrollbar-thumb:hover {{ background-color: rgba(15, 23, 42, 0.32); }}
.sidebar-scroll {{ scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.22) transparent; }}
.main-scroll {{ scrollbar-width: thin; scrollbar-color: rgba(15,23,42,0.22) transparent; }}

/* Mobile drawer: slide the sidebar in when ShellStateProvider sets
   data-sidebar-open="true" on its wrapping div. The sidebar has
   `-translate-x-full` by default on mobile (set by the page-shell
   heuristic), and `data-sidebar-open` flips it to translate-x-0. */
@media (max-width: 767px) {{
  [data-sidebar-open="true"] [data-shell-sidebar] {{
    transform: translateX(0);
  }}
  [data-sidebar-open="true"] [data-sidebar-backdrop] {{
    opacity: 1;
    pointer-events: auto;
  }}
  /* Keep the sidebar's vertical sizing usable on mobile when it slides in
     — the md: utilities don't apply below 768px, so without these the
     drawer would be height:auto and clip its contents. */
  [data-shell-sidebar] {{
    width: 18rem;
    height: 100vh;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }}
}}
"""


def _ensure_scrollbar_styles(project_root: Path) -> None:
    """Append the .sidebar-scroll / .main-scroll CSS rules to the project's
    globals.css if they aren't already there. Idempotent via a sentinel
    comment so re-runs don't duplicate the block.
    """
    globals_css = project_root / "src" / "app" / "globals.css"
    existing = ""
    if globals_css.exists():
        try:
            existing = globals_css.read_text()
        except OSError:
            return
    if _SCROLLBAR_CSS_SENTINEL in existing:
        return
    try:
        globals_css.parent.mkdir(parents=True, exist_ok=True)
        with globals_css.open("a") as f:
            f.write(_SCROLLBAR_CSS)
        logger.info("[shell] appended scrollbar styles to %s", globals_css)
    except OSError as e:
        logger.warning("[shell] could not append scrollbar styles: %s", e)

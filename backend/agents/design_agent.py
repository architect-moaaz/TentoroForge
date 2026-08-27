"""Design Agent — LLM-powered UI/UX design researcher.

Runs AFTER the planner and BEFORE code generation.
Analyzes the app's domain, audience, and competitive landscape,
then generates a complete design specification (colors, typography,
layout, density, patterns) that flows into the IR compiler.

If Figma screenshots are available, extracts the visual design language
from them instead of generating from scratch.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

logger = logging.getLogger(__name__)
from services.sdk_agent_runner import query  # reliable Anthropic-SDK transport; bundled CLI wedges under throttle
from services.agent_messages import Message
from services.photo_picker import pick_photo_for


DESIGN_AGENT_SYSTEM_PROMPT = r"""You are a senior UI/UX Design Researcher with expertise in enterprise application design across all industries.

Your job: analyze the application plan and produce a comprehensive design specification that will be used to generate the UI. You are NOT copying templates — you are reasoning from first principles about what design best serves THIS specific application and its users.

## Your Research Process

1. **Understand the domain**: What industry is this? Who are the users? What are their daily workflows?
2. **Analyze the data density**: How much data do users need to see at once? Are they scanning quickly or studying deeply?
3. **Consider the emotional tone**: Is this high-stakes (medical, financial)? Playful (social, consumer)? Productive (project management)?
4. **Choose the color strategy**: Colors communicate meaning. Blue = trust. Green = growth/success. Purple = creativity. Red = urgency. Warm tones = hospitality. Dark themes = technical/developer tools.
5. **Select the navigation/layout**: Choose the nav the app's information architecture wants — top-bar (horizontal nav), sidebar, command-bar (search-first), split workspace (list + detail), or icon-rail. Do NOT default to a dark sidebar just because an app is data-heavy or a CRM/admin; reserve a sidebar for broad, grouped IAs. Two apps in different domains should have STRUCTURALLY DIFFERENT navigation.
6. **Determine density**: Compact for data-heavy workflows (finance, logistics). Comfortable for general business. Spacious for consumer-facing or educational apps.

## If Figma Screenshots Are Available

When reference*.png files exist, you must:
1. Read ALL screenshots to understand the visual design language
2. Extract: primary/secondary/accent colors, typography style, spacing patterns, border radius, navigation style
3. Preserve the Figma design's visual identity in your design spec
4. Do NOT override the Figma design with industry defaults — the Figma design IS the design

## Responsive Design Strategy

Every design spec MUST consider these breakpoints:
- **Mobile** (< 640px): single column, hamburger nav, stacked cards, bottom tab bar
- **Tablet** (640-1024px): 2-column grids, collapsible sidebar, compact tables
- **Desktop** (> 1024px): full layout with sidebar, multi-column dashboards, expanded tables

Choose a **mobile strategy** based on the domain:
- **Field workers** (logistics, inspections, maintenance): Mobile-FIRST — design for phone, scale up
- **Office workers** (CRM, ERP, finance): Desktop-first, responsive down
- **Mixed** (project management, collaboration): Balanced — both layouts equally important

## Imagery & Visual Assets Strategy

Based on the domain, recommend specific visual assets:

### Background images:
- Use Unsplash-style URLs from free services. Examples:
  - Healthcare: "https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?w=1920&q=80"
  - Finance: "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=1920&q=80"
  - Real estate: "https://images.unsplash.com/photo-1560518883-ce09059eeffa?w=1920&q=80"
  - Education: "https://images.unsplash.com/photo-1503676260728-1c00da094a0b?w=1920&q=80"
  - E-commerce: "https://images.unsplash.com/photo-1556742049-0cfed4f6a45d?w=1920&q=80"
  - Technology: "https://images.unsplash.com/photo-1518770660439-4636190af475?w=1920&q=80"

### Illustration style:
- Recommend a consistent illustration approach:
  - "geometric" — abstract shapes for tech/SaaS
  - "line-art" — minimal for professional/corporate
  - "isometric" — 3D-style for dashboards/data
  - "flat" — colorful for consumer/education
  - "photo" — real images for real estate/hospitality/healthcare

### Placeholder images for entities:
- Avatar defaults for user entities (colored initials in circles using primary/secondary)
- Product placeholders for inventory/e-commerce (gray box with icon)
- Map previews for location-based entities
- Document thumbnails for content management

## User Requirements Integration

When the user's original prompt contains specific design preferences, they OVERRIDE domain defaults:
- "modern design" → spacious layout, rounded-xl corners, subtle gradients
- "minimal" → clean lines, lots of whitespace, monochrome palette
- "professional" → conservative colors (navy, charcoal), serif accents
- "playful" → bright colors, rounded-full elements, fun illustrations
- "dark theme" → dark background, light text, accent colors pop
- "dashboard-heavy" → compact density, multiple data widgets (nav style still chosen by the IA — not auto dark-sidebar)
- "mobile-first" → bottom navigation, large touch targets, swipe gestures

Always read the user's description carefully and adapt the design to match their intent.

## Output Format

Produce a COMPREHENSIVE design specification wrapped in ```design-spec markers.
This is the SINGLE source of truth for the entire app's visual design. Every agent reads this.
It must be thorough enough that a developer can build the entire UI without asking questions.

### VALUE HYGIENE — NON-NEGOTIABLE
Every value in the JSON below must be a BARE machine-readable value: a hex
color (`"#0f6d5a"`), a CSS length (`"0.5rem"`), a number (`1.5`), a duration
(`"150ms"`), or a real CSS font stack (`"'Fraunces', Georgia, serif"`).
NO commentary, NO parentheses, NO em-dashes, NO Tailwind class names inside
values — a strict validator DROPS any polluted value and your design decision
is lost. Explanations belong ONLY in `designRationale` and the `*Layout`
description fields.

```design-spec
{
  "designRationale": "3-5 sentences: WHY these design choices fit this domain, these users, these workflows",

  "colorPalette": {
    "primary": "#0f6d5a",
    "primaryLight": "#e6f4f1",
    "secondary": "#d9e8e4",
    "accent": "#c96f2d",
    "background": "#f8f7f4",
    "surface": "#ffffff",
    "surfaceHover": "#f1efe9",
    "error": "#b3362b", "warning": "#b97a1f", "success": "#2f7d4f", "info": "#2b6cb0",
    "muted": "#8a8578",
    "border": "#e3e0d7",
    "textPrimary": "#1f1d17",
    "textSecondary": "#5a5648",
    "textTertiary": "#8a8578",
    "sidebarBg": "#1c2a26",
    "sidebarText": "#c8d4d0",
    "sidebarActiveItem": "#2a3e38"
  },

  "typography": {
    "fontFamily": "'Source Serif 4', Georgia, serif",
    "headingFontFamily": "'Fraunces', Georgia, serif",
    "headingWeight": "600",
    "bodyWeight": "400",
    "bodySize": "0.9375rem",
    "lineHeight": 1.55,
    "headingLineHeight": 1.2,
    "letterSpacing": "0",
    "headingLetterSpacing": "-0.01em",
    "scale": {
      "h1": "1.875rem",
      "h2": "1.375rem",
      "h3": "1.0625rem",
      "body": "0.9375rem",
      "caption": "0.75rem"
    }
  },

  "spacing": {
    "pagePadding": "2rem",
    "cardPadding": "1.25rem",
    "sectionGap": "1.5rem",
    "elementGap": "1rem",
    "inputGap": "0.75rem"
  },

  "shadows": {
    "sm": "0 1px 2px rgba(31,29,23,0.05)",
    "md": "0 4px 12px rgba(31,29,23,0.08)",
    "lg": "0 8px 25px rgba(31,29,23,0.10)",
    "xl": "0 16px 40px rgba(31,29,23,0.12)"
  },

  "borderRadius": {
    "sm": "0.25rem",
    "md": "0.5rem",
    "lg": "0.75rem",
    "xl": "1rem",
    "full": "9999px",
    "scale": "sharp|soft|round"
  },
  "radiusScale": "sharp|soft|round",
  "elevation": "flat|bordered|layered|floating",
  "motionLevel": "none|subtle|expressive",
  "scaleMode": "compact|balanced|display",

  "layout": {
    "navigation": "sidebar|topbar|sidebar-dark|bottom-tabs",
    "sidebarWidth": "240px on desktop, full overlay on mobile",
    "density": "compact|comfortable|spacious",
    "maxContentWidth": "max-w-7xl (1280px) for content areas",
    "gridColumns": "12-column base grid",
    "dashboardLayout": "describe: hero banner at top? stat cards? recent activity table? chart placement?",
    "listPageLayout": "describe: search bar position, filter location, table vs cards, pagination style",
    "detailPageLayout": "describe: hero header? tabs? sidebar summary? two-column?",
    "formPageLayout": "describe: centered card? sections? multi-step?"
  },

  "responsive": {
    "strategy": "mobile-first|desktop-first|balanced",
    "mobileNav": "bottom-tabs|hamburger|slide-drawer",
    "mobileBreakpoint": "768px (below = mobile layout)"
  },

  "animation": {
    "duration": "150ms for micro-interactions, 300ms for page transitions",
    "easing": "cubic-bezier(0.4, 0, 0.2, 1) — smooth deceleration",
    "hoverLift": "translateY(-2px) + shadow-lg on card hover",
    "buttonPress": "scale(0.98) on active",
    "pageEnter": "fade-in + translateY(4px) over 200ms",
    "skeletonShimmer": "gradient slide from left to right, 1.5s infinite"
  },

  "statusColors": {
    "EntityStatus1": { "color": "green|red|blue|yellow|purple|gray", "label": "Active|Critical|etc", "icon": "CheckCircle|AlertTriangle|etc", "useDot": true },
    "EntityStatus2": { "... for each status value in the domain" }
  },

  "imagery": {
    "loginBackground": "relevant Unsplash URL or null",
    "dashboardHero": "gradient banner description or Unsplash URL or null",
    "emptyStateStyle": "geometric|line-art|isometric|flat",
    "avatarStyle": "initials|icon|photo",
    "iconStyle": "outline (stroke) or solid (fill), 20px default size",
    "placeholderImages": { "EntityName": "description" }
  },

  "dashboardWidgets": [
    { "name": "domain-specific widget name", "description": "what data it shows", "placement": "top|left|right|bottom", "size": "full|half|quarter" }
  ],

  "entityPatterns": {
    "EntityName": {
      "listView": "simple-table|dense-table|card-grid|kanban|timeline|calendar",
      "detailView": "tabbed-hero|split-detail|profile-detail|timeline-detail",
      "formView": "single-column|two-column|sectioned|wizard",
      "keyColumns": ["field1", "field2", "field3"],
      "heroFields": ["field1", "field2"],
      "tabs": ["Tab1", "Tab2"]
    }
  },

  "componentStyle": {
    "buttons": { "shape": "rounded|sharp|pill", "sizes": ["sm: h-8 px-3 text-xs", "md: h-9 px-4 text-sm", "lg: h-11 px-6 text-base"] },
    "cards": { "style": "bordered|shadow|flat", "hover": "shadow-lg + lift | border-primary | bg-muted" },
    "tables": { "style": "striped|clean|bordered", "stickyHeader": true, "rowHover": "bg-muted/50" },
    "inputs": { "style": "outlined|filled|underlined", "focusRing": "ring-2 ring-primary/20" }
  },

  "navigation": {
    "groups": [
      { "label": "Group Name", "items": ["Page1", "Page2", "Page3"] }
    ],
    "primaryActions": ["Action1", "Action2"],
    "quickAccess": "description of quick-access area (recent items, favorites, etc.)"
  },

  "compliance": {
    "standard": "HIPAA|SOX|PCI|FERPA|GDPR|none",
    "requirements": ["requirement 1", "requirement 2"]
  }
}
```

## ALSO GENERATE: src/app/globals.css (COMPLETE, PRODUCTION-READY)

After producing the design-spec JSON, you MUST also write a COMPLETE `src/app/globals.css` file.
This is NOT just CSS variables — it's a full modern UI baseline. Use the Write tool to create it.

The file must include ALL of these sections (200+ lines minimum):

1. **@tailwind directives** (base, components, utilities — NOT @import "tailwindcss")
2. **:root CSS variables** — convert EVERY color from your design-spec hex to HSL format:
   - `--primary: H S% L%` (e.g., `--primary: 221 83% 53%`)
   - Include: background, foreground, card, popover, primary, secondary, muted, accent, destructive, border, input, ring, radius
   - Include: color-success, color-warning, color-error for status indicators
3. **Dark mode overrides** in `.dark { }`
4. **Global base styles** — CRITICAL: the shadcn CSS reset MUST be:
   ```css
   * { @apply border-border; }
   ```
   NOT `* { @apply border; }` — this ONE WRONG CHARACTER puts visible borders on EVERY element.
   Also: body font, antialiasing, background/foreground colors
5. **Micro-interactions** — ALL interactive elements get transitions:
   ```css
   button, a, input, select, textarea, [role="button"] {
     transition: all 150ms cubic-bezier(0.4, 0, 0.2, 1);
   }
   button:active:not(:disabled) { transform: scale(0.98); }
   input:focus { box-shadow: 0 0 0 3px hsl(var(--primary) / 0.1); border-color: hsl(var(--primary)); }
   ```
6. **Card hover lift** — `.card-interactive` with shadow + translateY on hover
7. **Table row hover** — `tbody tr:hover` with background highlight
8. **Sticky table headers** — `thead { position: sticky; top: 0; }`
9. **Status dots** — `.status-dot-success/warning/error/info` with pulse animation
10. **Loading animations** — `@keyframes shimmer` for skeletons, `@keyframes spin` for spinners
11. **Hero gradient** — `.hero-gradient` utility
12. **Gradient text** — `.gradient-text` utility
13. **Stat card variants** — `.stat-card-primary/secondary/success/warning` with gradient backgrounds
14. **Sidebar styles** — `.sidebar-active`, `.sidebar-item:hover`
15. **Focus ring** — `:focus-visible` with primary ring color
16. **Scrollbar styling** — custom thin scrollbar
17. **Form enhancements** — label styling, required indicator, disabled state
18. **Page transitions** — `@keyframes fade-in` for page enters
19. **Avatar fallback** — `.avatar-fallback` with primary/10 background
20. **Empty state** — `.empty-state` centered layout

This file is the FOUNDATION of the app's visual quality. A minimal CSS file = ugly app.

## Rules

- Every color must be a valid hex code
- The design must feel cohesive — colors, radius, density should tell a consistent story
- Do NOT default to generic blue for everything — reason about what color communicates the right message
- If Figma is provided, extract colors from the actual design — do not guess
- Be specific in entityPatterns — if you see a status-based entity, suggest kanban; if time-based, suggest timeline
- The designRationale is important — it helps the user understand your choices
- ALWAYS include responsive strategy — apps must work on mobile
- ALWAYS include imagery section — apps need visual context, not just text
- Read the user's description and honor any design preferences they expressed
- ALWAYS generate globals.css with the Write tool — do NOT skip this step
"""


async def run_design_agent(
    output_dir: str,
    plan: dict,
    domain_context: dict | None = None,
    figma_screenshots: list[str] | None = None,
    dna_brief: str | None = None,
) -> AsyncIterator[Message]:
    """Run the Design Agent to produce a design specification.

    Analyzes the plan + domain + optional Figma screenshots and produces
    a design-spec.json file in the output directory.
    """
    os.environ.pop("CLAUDECODE", None)
    os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)

    domain_label = domain_context.get("domain", "General Business") if domain_context else "General Business"
    description = plan.get("description", "")
    entities = plan.get("data_models", [])
    pages = plan.get("pages", [])
    workflows = plan.get("workflows", [])

    # Build the entity summary
    entity_summary = []
    for e in entities:
        fields = [f.get("name", "") for f in e.get("fields", [])[:8]]
        entity_summary.append(f"  - {e.get('name', '?')}: {', '.join(fields)}")

    page_summary = []
    for p in pages:
        page_summary.append(f"  - {p.get('route', '?')}: {p.get('description', p.get('name', ''))}")

    workflow_summary = []
    for w in workflows:
        steps = w.get("steps", [])
        step_names = [s if isinstance(s, str) else s.get("name", "?") for s in steps[:5]]
        workflow_summary.append(f"  - {w.get('name', '?')}: {' → '.join(step_names)}")

    # Check for Figma screenshots
    figma_section = ""
    if figma_screenshots and len(figma_screenshots) > 0:
        figma_section = f"""
## Figma Design Available
There are {len(figma_screenshots)} Figma screenshot(s) in your working directory:
{chr(10).join(f'- `{Path(s).name}`' for s in figma_screenshots)}

READ ALL SCREENSHOTS FIRST. Extract the visual design language from the actual Figma design.
The Figma design is the source of truth for colors, typography, spacing, and layout style.
"""
    else:
        figma_section = """
## No Figma Design
No Figma screenshots available. The [DOMAIN PROFILE] block in your system
prompt already contains the researched visual language (palette character,
typography tone, density preference) and design patterns common in this
domain — translate THOSE into a concrete design spec. Do not re-research
the domain from scratch.
"""

    dna_section = ""
    if dna_brief:
        dna_section = (
            "\n## Committed Design DNA\n"
            f"{dna_brief}\n"
            "This DNA was derived for THIS app from its domain and is your "
            "starting identity — refine it with domain insight (adjust hue "
            "within its family, tune surfaces, choose imagery), but do NOT "
            "revert to a generic look (Inter + blue + slate) or contradict "
            "its archetype. Your palette, fonts, radius scale, elevation and "
            "density must be recognizably THIS identity.\n"
        )

    # IRF-M3-T7: substrate layout.hero + layout.density → hard-constraint block.
    # Empty when the plan carries no app_shape (pre-substrate behavior preserved).
    from services.design_agent_shape_directive import build_directive as _shape_directive
    shape_directive_block = _shape_directive(plan)

    user_prompt = f"""Design a UI/UX specification for this application.

## App Details
- **Name**: {plan.get('module_name', 'App')}
- **Description**: {description}
- **Domain**: {domain_label}
{dna_section}{shape_directive_block}

## Data Entities ({len(entities)})
{chr(10).join(entity_summary) if entity_summary else '  (none)'}

## Pages ({len(pages)})
{chr(10).join(page_summary) if page_summary else '  (none)'}

## Workflows ({len(workflows)})
{chr(10).join(workflow_summary) if workflow_summary else '  (none)'}
{figma_section}
## Steps
1. {('Read all reference*.png screenshots and analyze the visual design' if figma_screenshots else 'Read the [DOMAIN PROFILE] block in your system prompt — its visualLanguage section is a HARD CONSTRAINT, not a suggestion. Specifically: encode `paletteCharacter` as concrete hex codes that visibly express that character (e.g. "warm earth tones" → terracotta + sage + cream, NOT blue/emerald defaults). Encode `typographyTone` as a real font family. Encode `densityPreference` as padding/spacing decisions. The dossier was approved by the user — honour it.')}
2. Choose a color palette **bound to the visualLanguage.paletteCharacter from the dossier**. If you find yourself reaching for `#3b82f6` (blue), `#10b981` (emerald), or `#475569` (slate) — STOP and check whether the dossier's palette character calls for those. If not, pick hex codes that actually match the character description.
3. Determine the layout archetype, component density (constrained by `visualLanguage.densityPreference`), and navigation style
4. For each entity, recommend the best UI pattern (table, kanban, cards, timeline, etc.) — favour the patterns named in the dossier's `designPatterns` section over generic CRUD shapes
5. Output the complete design-spec JSON
6. Create `src/contracts/` directory if it doesn't exist
7. Write `src/contracts/design-spec.json` with the design spec
8. Write `src/app/globals.css` with the COMPLETE modern CSS (200+ lines, all utilities, all animations) — its CSS variables must match the design-spec colorPalette

Be opinionated. Great design has a clear point of view.
The globals.css is the MOST IMPORTANT file you write — it defines the entire visual quality of the app.

## Mandatory output format for the design spec
End your reply with a fenced block exactly like:

```design-spec
{{
  "colorPalette": {{ "primary": "#…", "secondary": "#…", "accent": "#…", ... }},
  "typography": {{ ... }},
  "layout": {{ ... }},
  ...
}}
```

This fence is how the pipeline parses your output — without it, the system falls back to a generic industry palette and your visual design choices are lost."""

    from services.domain_context import build_domain_profile
    domain_profile = build_domain_profile(domain_context, "design_agent")

    # Product standards — the acceptance rubric for visual style. Adding
    # it up front lets the design agent author restraint (no excessive
    # gradients, mobile-first, consistent spacing) first-pass instead of
    # relying on post-gen guards that can only catch structural violations.
    from services.product_standards import render_for as _standards_for
    from services.taste_standards import render_for as _taste_for
    standards_block = _standards_for("design")
    # Design stance — ONE chosen stance (soft / minimalist / brutalist),
    # read from the brief, never offered as a menu. A menu is how every app
    # ends up looking like the average of three.
    try:
        from services.design_brief_to_prompt import load_brief_from_disk
        _taste_brief = load_brief_from_disk(str(output_dir))
    except Exception:
        _taste_brief = None
    taste_block = _taste_for("design", _taste_brief)

    # UI/UX Pro Max knowledge base (behind FORGE_UI_UX_PRO_MAX). Injects a
    # compact block of curated palette + typography + style + anti-pattern
    # rules matched to the brief's product-type. Off by default — opt-in per
    # run. See backend/skills/ui-ux-pro-max/ATTRIBUTION.md.
    from services.design_knowledge import compose_prompt as _ux_prompt
    _brief_domain = None
    if plan and isinstance(plan, dict):
        _brief_domain = plan.get("domain")
    ux_pro_max_block = _ux_prompt(_brief_domain)

    # 21st.dev Magic MCP (behind FORGE_21ST_MCP + FORGE_21ST_API_KEY).
    # Curated component variants as inspiration — the agent extracts
    # tokens (palette, typography, structural moves) and translates into
    # our schema. No JSX ever ships. See services/magic_mcp.py.
    from services import magic_mcp as _magic
    _mcp_servers, _allowed_tools = _magic.merge_into({}, ["Read", "Write", "Glob"])
    magic_block = _magic.PROMPT_BLOCK if _magic.is_enabled() else ""

    # 21st.dev pre-fetch happens up-front in generate.py (before the design
    # branch), so both canonical and legacy paths get references on disk.
    # Read whatever is there and inject it into the LLM prompt. Empty → no
    # references were fetched (feature disabled or fetch failed).
    magic_prefetch_hint = ""
    try:
        from services import magic_prefetch as _prefetch
        from pathlib import Path as _P
        _ref_dir = _P(output_dir) / "src" / "contracts" / "references"
        if _ref_dir.is_dir():
            _existing = sorted(p for p in _ref_dir.glob("*.json") if p.name != "index.json")
            magic_prefetch_hint = _prefetch.prompt_hint(_existing, output_dir)
    except Exception as _prefetch_exc:  # noqa: BLE001
        logger.warning("[design] magic reference read failed: %s", _prefetch_exc)

    options = ClaudeAgentOptions(
        system_prompt=DESIGN_AGENT_SYSTEM_PROMPT + domain_profile
                      + ("\n\n" + standards_block if standards_block else "")
                      + ("\n\n" + taste_block if taste_block else "")
                      + ("\n\n" + ux_pro_max_block if ux_pro_max_block else "")
                      + ("\n\n" + magic_block if magic_block else "")
                      + ("\n\n" + magic_prefetch_hint if magic_prefetch_hint else ""),
        allowed_tools=_allowed_tools,
        mcp_servers=_mcp_servers,
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=12,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message


def extract_design_spec(text: str) -> dict | None:
    """Extract design-spec JSON from ```design-spec markers in agent output."""
    from services.json_extractor import extract_json
    return extract_json(
        text,
        marker="```design-spec",
        expect_type=dict,
        required_fields=["colorPalette"],
    )


def _hex_to_hsl_channels(hex_color: str) -> str:
    """Convert ``"#F0F9FF"`` → ``"204 100% 97%"`` for use in a CSS var.

    Returns just the ``H S% L%`` triple, no ``hsl()`` wrapper — matches the
    shadcn/tailwind convention where vars hold the channels and consumers
    wrap with ``hsl(var(--x))``.
    """
    import colorsys

    s = hex_color.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"invalid hex color: {hex_color!r}")
    r = int(s[0:2], 16) / 255
    g = int(s[2:4], 16) / 255
    b = int(s[4:6], 16) / 255
    h, l, s_chan = colorsys.rgb_to_hls(r, g, b)
    return f"{round(h * 360)} {round(s_chan * 100)}% {round(l * 100)}%"


# Map design-spec colorPalette keys → CSS var names in globals.css :root.
# Names follow shadcn/ui's convention (which the rest of the scaffold uses).
_PALETTE_TO_CSS_VAR = {
    "background": "--background",
    "surface": "--card",  # surface in the spec is "card" in tailwind/shadcn
    "primary": "--primary",
    "secondary": "--secondary",
    "accent": "--accent",
    "muted": "--muted",
    "error": "--destructive",
    "success": "--color-success",
    "warning": "--color-warning",
    "info": "--color-info",
    "border": "--border",
    "textPrimary": "--foreground",
    "textSecondary": "--muted-foreground",
}


def _typography_register_from_spec(typography: dict | None) -> dict | None:
    """Build a `typography register` dict (heading_font/body_font/weights) from
    a design-spec ``typography`` block.

    Accepts BOTH shapes the spec may carry:

      1. Legacy flat keys (what ``_register_from_spec_fonts`` reads) —
         ``{"fontFamily": "Inter", "headingFontFamily": "Fraunces", ...}``.
      2. Visual-lock nested shape —
         ``{"display": {"family": "Fraunces", "weights": [500,700]},
             "body":    {"family": "Inter",    "weights": [400,500,600]}}``.

    Prefers the visual-lock shape when both are present (it carries the
    per-slot weight lists the @import URL needs). Returns None when
    neither shape yields a family name.
    """
    if not isinstance(typography, dict):
        return None
    disp = typography.get("display") if isinstance(typography.get("display"), dict) else {}
    body_slot = typography.get("body") if isinstance(typography.get("body"), dict) else {}
    heading_family = _first_font_family(disp.get("family")) if disp else None
    body_family    = _first_font_family(body_slot.get("family")) if body_slot else None

    if not heading_family:
        heading_family = _first_font_family(typography.get("headingFontFamily"))
    if not body_family:
        body_family = _first_font_family(typography.get("fontFamily"))

    if not heading_family and not body_family:
        return None
    heading_family = heading_family or body_family
    body_family    = body_family or heading_family

    heading_weights = disp.get("weights") if isinstance(disp.get("weights"), list) else None
    body_weights    = body_slot.get("weights") if isinstance(body_slot.get("weights"), list) else None
    # Fall back to the flat legacy scalar weights, then to sane defaults.
    heading_weight = (heading_weights[-1] if heading_weights else
                      typography.get("headingWeight") or 700)
    body_weight    = (body_weights[0] if body_weights else
                      typography.get("bodyWeight") or 400)
    return {
        "heading_font":   heading_family,
        "body_font":      body_family,
        "heading_weight": heading_weight,
        "body_weight":    body_weight,
        "heading_weights": list(heading_weights) if heading_weights else None,
        "body_weights":    list(body_weights) if body_weights else None,
        "heading_tracking": typography.get("headingTracking") or "-0.01em",
        "line_height":      typography.get("lineHeight"),
    }


def _build_google_fonts_import_from_typography(typography: dict | None) -> str | None:
    """Build a Google Fonts @import URL from a design-spec typography block.

    Handles both weight shapes — the visual-lock nested slot carries a
    ``weights: [400,500,600]`` list; the legacy flat keys only carry a
    single weight. Both are rolled into one two-family URL so a single
    request loads both display + body faces.

    Returns None when no family can be resolved (caller then skips the
    @import injection entirely — better than a broken URL).
    """
    reg = _typography_register_from_spec(typography)
    if not reg:
        return None
    head = reg["heading_font"].replace(" ", "+")
    body = reg["body_font"].replace(" ", "+")
    head_ws = reg.get("heading_weights") or [reg.get("heading_weight") or 700]
    body_ws = reg.get("body_weights") or [reg.get("body_weight") or 400]
    if reg["heading_font"] == reg["body_font"]:
        merged = sorted({_coerce_weight(w, 400) for w in [*head_ws, *body_ws]})
        return ("@import url('https://fonts.googleapis.com/css2?family="
                f"{head}:wght@{';'.join(str(w) for w in merged)}"
                "&display=swap');")
    hs = sorted({_coerce_weight(w, 700) for w in head_ws})
    bs = sorted({_coerce_weight(w, 400) for w in body_ws})
    return ("@import url('https://fonts.googleapis.com/css2?family="
            f"{head}:wght@{';'.join(str(w) for w in hs)}"
            f"&family={body}:wght@{';'.join(str(w) for w in bs)}"
            "&display=swap');")


def _inject_font_import_from_typography(globals_path: Path, typography: dict | None) -> None:
    """Prepend / replace the Google Fonts @import line at the top of globals.css.

    Idempotent — any prior Google Fonts @import (for a Google Fonts URL) is
    stripped first so a re-run doesn't stack duplicates. Also inserts
    ``--font-display`` / ``--font-body`` CSS variables + minimal body/heading
    base rules inside the tentoro:typography marker block so a visual-lock
    spec that never went through the domain-register path still reaches
    rendered text.

    Safe on any globals.css: when ``typography`` yields no family (caller
    passed the domain default or nothing), the function is a no-op.
    """
    import re as _re

    if not globals_path.exists():
        return
    import_line = _build_google_fonts_import_from_typography(typography)
    if not import_line:
        return
    css = globals_path.read_text()
    # Strip any prior Google Fonts @import — leaves other @imports alone.
    css = _re.sub(
        r"@import url\(['\"]https://fonts\.googleapis\.com/css2[^)]+['\"]\);\n?",
        "",
        css,
    )
    # Also strip any prior tentoro:typography marker block so we replace
    # rather than duplicate the vars + base rules.
    css = _re.sub(
        r"\n*" + _re.escape(_TYPOG_START) + r".*?" + _re.escape(_TYPOG_END) + r"\n?",
        "",
        css,
        flags=_re.DOTALL,
    )
    reg = _typography_register_from_spec(typography) or {}
    heading_family = reg.get("heading_font") or ""
    body_family    = reg.get("body_font") or heading_family
    # Minimal typography block — mirrors _build_typography_block but keyed
    # to --font-display / --font-body (the visual-lock naming) alongside
    # the legacy --font-heading / --font-body already emitted upstream.
    block_lines = [
        _TYPOG_START,
        ":root {",
        f"  --font-display: '{heading_family}', Georgia, serif;",
        f"  --font-body: '{body_family}', system-ui, sans-serif;",
        f"  --font-heading: var(--font-display);",
        "}",
        "body { font-family: var(--font-body); }",
        "h1, h2, h3, h4, h5, h6 { font-family: var(--font-display); }",
        _TYPOG_END,
    ]
    block = "\n".join(block_lines)
    css = css.rstrip("\n") + "\n"
    # Prepend @import at the very top and append the block at the end.
    css = f"{import_line}\n{css}"
    css = css.rstrip("\n") + "\n\n" + block + "\n"
    globals_path.write_text(css)


def _rewrite_globals_root(globals_path: Path, palette: dict,
                          radius_md: str | None = None,
                          icon_stroke: float | None = None,
                          typography: dict | None = None) -> None:
    """Replace the ``:root { ... }`` block in ``globals.css`` with values
    derived from the design-spec ``colorPalette``.

    The LLM is unreliable at hex→HSL math; the design spec ``colorPalette``
    is the source of truth. This function deterministically rewrites the
    first ``:root { ... }`` block so the emitted CSS matches the palette.

    Idempotent — running it twice produces the same output.
    """
    import re

    if not globals_path.exists():
        return
    text = globals_path.read_text()

    # Build the new :root body deterministically from the palette. Values pass
    # through extract_hex so an annotated color ("#C4611F — terracotta") still
    # themes the app instead of being silently skipped (that skip shipped
    # default-blue apps whenever the LLM annotated its palette).
    from services.css_sanitize import extract_hex

    lines: list[str] = []
    emitted: set[str] = set()
    for palette_key, var_name in _PALETTE_TO_CSS_VAR.items():
        hex_val = extract_hex(palette.get(palette_key))
        if hex_val:
            try:
                lines.append(f"  {var_name}: {_hex_to_hsl_channels(hex_val)};")
                emitted.add(var_name)
            except (ValueError, IndexError):
                continue

    # Promote STRUCTURAL tokens (border/input/ring/muted/foreground/card/popover)
    # from LLM-authored to spec-derived: derive them from the palette's brand hue
    # so the app's greys stay tinted toward the brand and the whole theme reads as
    # one cohesive palette. Only fill vars the palette didn't already provide —
    # an explicit spec value always wins.
    try:
        from services.design_compiler import derive_structural_tokens

        for var_name, triplet in derive_structural_tokens(palette).items():
            if var_name not in emitted:
                lines.append(f"  {var_name}: {triplet};")
                emitted.add(var_name)
    except Exception:  # noqa: BLE001 — never fail the design phase on token derivation
        pass

    # --radius from the spec's borderRadius.md (sanitized) — this is what makes
    # sharp vs round apps actually FEEL different (it was hardcoded to 0.5rem
    # for every app, erasing the shape decision).
    from services.css_sanitize import extract_css_length
    radius_val = extract_css_length(radius_md) or "0.5rem"
    lines.append(f"  --radius: {radius_val};")
    # Icon voice: stroke weight for every lucide icon app-wide (thin = elegant
    # editorial, bold = friendly/industrial). Consumed by the typography
    # block's `svg.lucide` rule.
    try:
        stroke = float(icon_stroke) if icon_stroke else 2.0
    except (TypeError, ValueError):
        stroke = 2.0
    lines.append(f"  --icon-stroke: {max(1.0, min(3.0, stroke))}px;")
    new_root_body = "\n".join(lines)

    # Replace the FIRST :root { ... } block (the main one, not .dark).
    # Use DOTALL so the body can span lines; non-greedy on the body.
    new_text, count = re.subn(
        r"(:root\s*\{)[^}]*(\})",
        lambda _m: f"{_m.group(1)}\n{new_root_body}\n{_m.group(2)}",
        text,
        count=1,
        flags=re.DOTALL,
    )
    if count == 0:
        # No :root block found — append one so callers always get the truth.
        new_text = text.rstrip() + f"\n\n:root {{\n{new_root_body}\n}}\n"

    # FIX-3 — resolve template placeholders (__CSS_PRIMARY__, __CSS_BACKGROUND__,
    # __CSS_FOREGROUND__, __CSS_SECONDARY__) in the REST of the file — chiefly
    # the `.dark { ... }` block, whose --primary/--ring were shipping as literal
    # unresolved template holes. verify_pipeline flags this as an issue but the
    # gate wasn't enforced during dark-theme writes. Fallbacks are the same
    # neutral defaults the template ships (kept identical to previous behaviour
    # when a palette key is absent).
    _placeholder_values: dict[str, str] = {}
    _pal_to_placeholder = {
        "primary":    "__CSS_PRIMARY__",
        "background": "__CSS_BACKGROUND__",
        "textPrimary":"__CSS_FOREGROUND__",
        "secondary":  "__CSS_SECONDARY__",
    }
    _placeholder_fallbacks = {
        "__CSS_PRIMARY__":    "222 47% 11%",
        "__CSS_BACKGROUND__": "0 0% 100%",
        "__CSS_FOREGROUND__": "222 47% 11%",
        "__CSS_SECONDARY__":  "210 40% 96%",
    }
    for _pkey, _ph in _pal_to_placeholder.items():
        _hex = extract_hex(palette.get(_pkey))
        if _hex:
            try:
                _placeholder_values[_ph] = _hex_to_hsl_channels(_hex)
            except (ValueError, IndexError):
                pass
    for _ph, _default in _placeholder_fallbacks.items():
        new_text = new_text.replace(_ph, _placeholder_values.get(_ph, _default))

    globals_path.write_text(new_text)

    # 2026-08-13 — visual-lock typography backstop: if a design-spec
    # ``typography`` block was passed (post-hoc rebuild path, or any call
    # site that bypasses ``_inject_typography_into_globals``), inject the
    # Google Fonts @import + --font-display/--font-body vars now so the
    # visual-lock fonts (Fraunces + Inter for the wellness preset) reach
    # rendered text instead of the browser falling back to system fonts.
    if typography is not None:
        try:
            _inject_font_import_from_typography(globals_path, typography)
        except Exception:  # noqa: BLE001 — never fail globals write on font injection
            pass


_TYPOG_START = "/* tentoro:typography */"
_TYPOG_END = "/* /tentoro:typography */"


def _coerce_weight(value, default: int) -> int:
    """Font weights may arrive as int (700) or str ("700"); normalise to int so
    they can be de-duped + sorted together. Falls back to `default` on junk."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _build_google_fonts_url(register: dict) -> str:
    """Build a Google Fonts @import URL from a typography register dict."""
    head = register["heading_font"].replace(" ", "+")
    body = register["body_font"].replace(" ", "+")
    hw = _coerce_weight(register.get("heading_weight"), 700)
    bw = _coerce_weight(register.get("body_weight"), 400)
    if register["heading_font"] == register["body_font"]:
        weights = sorted({bw, hw})
        return (
            "@import url('https://fonts.googleapis.com/css2?family="
            f"{head}:wght@{';'.join(str(w) for w in weights)}&display=swap');"
        )
    return (
        "@import url('https://fonts.googleapis.com/css2?family="
        f"{head}:wght@{hw}&family={body}:wght@{bw}&display=swap');"
    )


def _first_font_family(value: str | None) -> str | None:
    """Extract the first font family from a CSS font-family string.

    ``"Fraunces, system-ui, sans-serif"`` → ``"Fraunces"``. Quotes are
    stripped and the fallback stack (everything after the first comma) is
    dropped. Returns None for empty / non-string input.

    Also strips LLM rationale prose that sometimes leaks into the field
    (e.g. ``"DM Sans — humanist geometric sans; corporate…"``). A real
    Google Fonts family name is `[A-Za-z0-9 ]+` — punctuation, em-dashes,
    parens, and colons never appear in one. Truncating at the first such
    character keeps the URL requestable instead of yielding a 503 that
    Chrome ORB reports as a Runtime Error overlay.
    """
    if not value or not isinstance(value, str):
        return None
    first = value.split(",")[0].strip().strip("'\"").strip()
    import re as _re
    m = _re.match(r"[A-Za-z0-9][A-Za-z0-9 ]*", first)
    cleaned = (m.group(0).rstrip() if m else "")
    return cleaned or None


def _register_from_spec_fonts(typography: dict | None) -> dict | None:
    """Build a typography *register* dict from a design-spec ``typography`` block.

    Honours the spec's ``fontFamily`` / ``headingFontFamily`` (and optional
    weights / tracking / line-height) so distinctive spec fonts flow into
    globals.css instead of the domain register-catalogue fallback. Returns
    None when the spec carries no font families (caller falls back to the
    domain register).
    """
    if not isinstance(typography, dict):
        return None
    body_font = _first_font_family(typography.get("fontFamily"))
    heading_font = _first_font_family(typography.get("headingFontFamily"))
    if not body_font and not heading_font:
        return None
    # Fall back to whichever family is present when only one is specified.
    body_font = body_font or heading_font
    heading_font = heading_font or body_font
    return {
        "heading_font": heading_font,
        "body_font": body_font,
        "heading_weight": typography.get("headingWeight") or 600,
        "body_weight": typography.get("bodyWeight") or 400,
        "heading_tracking": typography.get("headingTracking") or "-0.01em",
        "line_height": typography.get("lineHeight"),
    }


def _build_typography_block(register: dict) -> str:
    """Build the :root CSS variable block (+ body/heading rules) for a
    typography register.

    line-height is sanitized to a bare number ("1.6 for body, 1.25 for
    headings" → 1.6) — prose here used to emit an invalid declaration the
    browser dropped, so body line-height never varied per app.
    """
    from services.css_sanitize import extract_number, extract_letter_spacing, extract_weight

    line_height = extract_number(register.get("line_height"), 1.0, 2.2) or 1.5
    heading_weight = extract_weight(register.get("heading_weight")) or "600"
    body_weight = extract_weight(register.get("body_weight")) or "400"
    tracking = extract_letter_spacing(register.get("heading_tracking")) or "-0.01em"
    return (
        f"{_TYPOG_START}\n"
        ":root {\n"
        f"  --font-heading: '{register['heading_font']}', system-ui, sans-serif;\n"
        f"  --font-body: '{register['body_font']}', system-ui, sans-serif;\n"
        f"  --font-heading-weight: {heading_weight};\n"
        f"  --font-body-weight: {body_weight};\n"
        f"  --font-heading-tracking: {tracking};\n"
        "}\n"
        # Actually APPLY --font-body — nothing referenced it before, so the
        # spec's body font never reached rendered text.
        #
        # ALSO anchor body bg/fg to the semantic tokens: LLM-authored
        # globals.css frequently drops the template's `@layer base` body rule,
        # leaving body text at browser-default BLACK — invisible on light
        # themes, but black-on-near-black on every dark-mode app.
        "body {\n"
        "  font-family: var(--font-body);\n"
        f"  line-height: {line_height};\n"
        "  background-color: hsl(var(--background));\n"
        "  color: hsl(var(--foreground));\n"
        "  -webkit-font-smoothing: antialiased;\n"
        "}\n"
        # And APPLY --font-heading — it was emitted with ZERO consumers, so the
        # heading font (the strongest single differentiator between apps) never
        # rendered. Headings now carry the pairing's family/weight/tracking.
        "h1, h2, h3, h4, h5, h6 {\n"
        "  font-family: var(--font-heading);\n"
        "  font-weight: var(--font-heading-weight);\n"
        "  letter-spacing: var(--font-heading-tracking);\n"
        "}\n"
        # Per-app icon voice: CSS stroke-width beats the SVG attribute, so one
        # rule themes every lucide icon (thin editorial → bold industrial).
        "svg.lucide {\n"
        "  stroke-width: var(--icon-stroke, 2px);\n"
        "}\n"
        f"{_TYPOG_END}"
    )


def _inject_typography_into_globals(css_path: Path, register: dict) -> None:
    """Inject Google Fonts @import + CSS typography variables into globals.css.

    Idempotent — if the file already contains a ``tentoro:typography`` marker
    block, the existing block (and any prior Google Fonts @import) is replaced
    rather than duplicated.

    The @import line is placed at the very top of the file (before
    ``@tailwind base;``). The CSS variable block is appended at the end.
    """
    css = css_path.read_text()
    import_line = _build_google_fonts_url(register)
    block = _build_typography_block(register)

    # Strip any prior Google Fonts import line (idempotency)
    css = re.sub(
        r"@import url\('https://fonts\.googleapis\.com/css2[^)]+\);\n?",
        "",
        css,
    )
    # Strip any prior tentoro:typography block plus any surrounding blank lines
    # (idempotency — ensures second run produces identical output to first run)
    css = re.sub(
        r"\n*" + re.escape(_TYPOG_START) + r".*?" + re.escape(_TYPOG_END) + r"\n?",
        "",
        css,
        flags=re.DOTALL,
    )

    # Prepend import line at the very top
    css = f"{import_line}\n{css}"

    # Append typography block at end (single blank line separator)
    css = css.rstrip("\n") + "\n"
    css += f"\n{block}\n"

    css_path.write_text(css)


def _populate_entity_photos(
    entities: list[dict], domain: str, project_seed: str | None = None
) -> dict[str, str]:
    """Call photo_picker for each entity, return {entity_name: url}.

    Errors per-entity are caught and that entity is skipped — generation
    must not fail if Unsplash is unreachable. Duplicate entity names are
    deduped (first occurrence wins).

    ``project_seed`` is forwarded to ``pick_photo_for`` so two projects
    sharing the same (entity, domain) pair receive different photo URLs.
    """
    photos: dict[str, str] = {}
    seen: set[str] = set()
    for ent in entities or []:
        name = ent.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            photos[name] = pick_photo_for(name, domain, project_seed=project_seed)
        except Exception:
            # Best-effort: skip entities the picker can't resolve
            continue
    return photos


def save_design_spec(output_dir: str, spec: dict, plan: dict | None = None) -> str:
    """Save design spec to output_dir/src/contracts/design-spec.json.

    Ensures ``cta_hierarchy`` is always present so downstream consumers
    (schema prompt builder, CTA validator) can read it unconditionally.
    The value is derived from the spec's ``register`` field via
    ``cta_defaults.defaults_for_register``.  It is always kept in sync
    with the current ``register`` so callers do not need to set it
    manually.  To supply a fully custom hierarchy, set it in the spec
    AFTER calling this function.

    Also post-processes ``src/app/globals.css``: the LLM is unreliable at
    hex→HSL math, so we deterministically rewrite the ``:root { ... }``
    block from ``spec.colorPalette`` to keep CSS variables in lockstep
    with the spec.

    When ``plan`` is supplied, iterates ``plan.data_models`` and calls
    ``photo_picker.pick_photo_for`` for each entity, storing the results
    on ``spec["entityPhotos"]``.  Picker errors are swallowed per-entity
    so an Unsplash outage cannot fail generation.
    """
    from services.cta_defaults import defaults_for_register

    # When the spec carries an externally-extracted brand, use it as the
    # authoritative palette source (overrides whatever the LLM design pass
    # emitted as colorPalette). Downstream _rewrite_globals_root then picks
    # up the rewritten colorPalette and updates globals.css :root accordingly.
    brand = spec.get("brand")
    if brand and isinstance(brand, dict):
        derived = brand.get("derived") or {}
        if derived:
            _brand_keys = {
                "background", "surface", "primary", "secondary", "accent",
                "muted", "border", "textPrimary", "textSecondary",
                "error", "warning", "success",
            }
            spec["colorPalette"] = {
                "background": derived.get("background"),
                "surface": derived.get("surface"),
                "primary": derived.get("primary"),
                "secondary": derived.get("secondary"),
                "accent": derived.get("accent"),
                "muted": derived.get("background"),
                "border": derived.get("border"),
                "textPrimary": derived.get("text_primary"),
                "textSecondary": derived.get("text_secondary"),
                "error": derived.get("error"),
                "warning": derived.get("warning"),
                "success": derived.get("success"),
                **{k: v for k, v in (spec.get("colorPalette") or {}).items()
                   if k not in _brand_keys},
            }

    register = spec.get("register", "default")
    spec["cta_hierarchy"] = defaults_for_register(register)

    # Default surface depth tokens — give Hero/Card/Section a token to reference
    # even when the LLM design pass doesn't emit one explicitly.
    spec.setdefault("tokens", {})
    spec["tokens"].setdefault("surface", {})
    spec["tokens"]["surface"].setdefault("gradient", {
        "subtle":  {"type": "linear", "angle": 135, "from": "tokens.color.primary.50",  "to": "tokens.color.surface.0"},
        "vibrant": {"type": "linear", "angle": 135, "from": "tokens.color.primary.200", "to": "tokens.color.primary.50"},
    })
    spec["tokens"]["surface"].setdefault("shadow", {
        "subtle":   "0 1px 2px 0 rgba(15, 23, 42, 0.04)",
        "elevated": "0 8px 24px -8px rgba(15, 23, 42, 0.18)",
        "floating": "0 16px 48px -16px rgba(15, 23, 42, 0.28)",
    })

    # Photo URLs per entity (Task 18) — populate when a plan is available.
    # Uses plan.data_models (the planner's canonical entity list).
    # project_seed is derived from the output_dir basename (the project
    # short_id) so two projects sharing the same (entity, domain) pair
    # receive different photo URLs without any upstream caller changes.
    if plan is not None:
        import os as _os
        plan_entities = plan.get("data_models", [])
        domain = plan.get("domain", spec.get("domain", "saas"))
        project_seed = _os.path.basename(_os.path.normpath(output_dir))
        spec["entityPhotos"] = _populate_entity_photos(plan_entities, domain, project_seed=project_seed)

    contracts_dir = Path(output_dir) / "src" / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    path = contracts_dir / "design-spec.json"
    path.write_text(json.dumps(spec, indent=2))

    # Rewrite globals.css :root from the (trusted) colorPalette so CSS vars
    # match the spec, regardless of what hex→HSL math the LLM produced.
    globals_css_path = Path(output_dir) / "src" / "app" / "globals.css"
    palette = spec.get("colorPalette") or {}
    if isinstance(palette, dict) and palette:
        try:
            _radius_md = (spec.get("borderRadius") or {}).get("md") \
                if isinstance(spec.get("borderRadius"), dict) else None
            _icon_stroke = spec.get("iconStroke") \
                or ((spec.get("imagery") or {}).get("style") or {}).get("iconStroke")
            _rewrite_globals_root(globals_css_path, palette,
                                  radius_md=_radius_md, icon_stroke=_icon_stroke)
        except OSError:
            # Don't fail the design phase if globals.css isn't writable;
            # the design-spec.json is already saved.
            pass

    # Inject Google Fonts @import + CSS typography variables.
    # The spec may carry an explicit register id; otherwise infer from domain.
    try:
        from services.typography_registers import pick_register_for_domain, get_register

        typo_spec = spec.get("typography") or {}
        register_id = typo_spec.get("register")
        # Precedence: explicit register id > spec font families > domain fallback.
        if register_id:
            typo_register = get_register(register_id)
        elif _register_from_spec_fonts(typo_spec):
            typo_register = _register_from_spec_fonts(typo_spec)
        else:
            # domain may be stored on the spec, else fall back to the PLAN's
            # domain (the spec never carried one — that dead fallback pinned
            # every fontless app to the "saas" register → Inter).
            domain = spec.get("domain") or (plan or {}).get("domain") or "saas"
            typo_register = pick_register_for_domain(domain)
        if typo_register and globals_css_path.exists():
            _inject_typography_into_globals(globals_css_path, typo_register)
    except OSError:
        pass

    # Personality CSS — per-app texture / heading accent / table voice /
    # selection + focus colors, derived from the design DNA. Idempotent
    # (marker-wrapped) so refine passes replace instead of duplicating.
    #
    # Spec D Wave 1 (round 2) — brief-first tone_intensity gate: when
    # brief.identity.tone_intensity == 0.0, personality is suppressed
    # entirely (the app stays quiet) and the marker block is stripped so
    # nothing lingers from a prior loud pass. Any other value (or None)
    # falls through to the archetype-driven emission.
    try:
        dna_path = Path(output_dir) / "src" / "contracts" / "design-dna.json"
        if dna_path.exists() and globals_css_path.exists():
            from services.design_dna import to_personality_css
            from services.brief_visual_stance import (
                get_tone_intensity,
                load_brief_from,
            )
            import re as _re
            _brief_tone = get_tone_intensity(load_brief_from(output_dir))
            dna = json.loads(dna_path.read_text())
            css = globals_css_path.read_text()
            css = _re.sub(r"\n*/\* tentoro:personality \*/.*?/\* /tentoro:personality \*/\n?",
                          "", css, flags=_re.DOTALL)
            if _brief_tone == 0.0:
                # Explicit brief-authored quiet mode — do not re-inject.
                globals_css_path.write_text(css.rstrip("\n") + "\n")
            else:
                block = to_personality_css(dna)
                globals_css_path.write_text(css.rstrip("\n") + "\n\n" + block + "\n")
    except Exception:  # noqa: BLE001 — personality is enhancement, never fatal
        logger.warning("personality CSS injection skipped", exc_info=True)

    # Component SKIN — the app's design language (inkwell/monoline/manuscript/
    # signal/meadow/gridwork/aurora/broadsheet). Restyles HOW components are
    # drawn (tiles, cards, buttons, tables, edges), scoped under
    # [data-tentoro-engine] so it wins the Tailwind cascade. Idempotent.
    try:
        dna_path = Path(output_dir) / "src" / "contracts" / "design-dna.json"
        if dna_path.exists() and globals_css_path.exists():
            from services.design_dna import to_component_css
            import re as _re
            dna = json.loads(dna_path.read_text())
            if dna.get("skin"):
                block = to_component_css(dna)
                css = globals_css_path.read_text()
                css = _re.sub(r"\n*/\* tentoro:skin \*/.*?/\* /tentoro:skin \*/\n?",
                              "", css, flags=_re.DOTALL)
                globals_css_path.write_text(css.rstrip("\n") + "\n\n" + block + "\n")
    except Exception:  # noqa: BLE001 — skin is enhancement, never fatal
        logger.warning("component skin CSS injection skipped", exc_info=True)

    # NAV identity — how the menu PRESENTS its items (numbered index /
    # document outline / compartments / pills / glass capsules…), per skin.
    #
    # Spec D Wave 1 (round 2) — brief-first nav_language gate: when
    # brief.layout.nav_language == "invisible", the per-skin nav block is
    # stripped and no replacement injected (shell default chrome takes
    # over). Any other value (or None) falls through to the DNA-driven
    # emission. chrome_heavy / chrome_light are advisory today — the
    # skin-driven CSS stays authoritative until we author brief-only
    # variants for those tones.
    try:
        dna_path = Path(output_dir) / "src" / "contracts" / "design-dna.json"
        if dna_path.exists() and globals_css_path.exists():
            from services.design_dna import to_nav_css
            from services.brief_visual_stance import (
                get_nav_language,
                load_brief_from,
            )
            import re as _re
            _brief_nav = get_nav_language(load_brief_from(output_dir))
            dna = json.loads(dna_path.read_text())
            if dna.get("skin"):
                css = globals_css_path.read_text()
                css = _re.sub(r"\n*/\* tentoro:nav \*/.*?/\* /tentoro:nav \*/\n?",
                              "", css, flags=_re.DOTALL)
                if _brief_nav == "invisible":
                    globals_css_path.write_text(css.rstrip("\n") + "\n")
                else:
                    block = to_nav_css(dna)
                    globals_css_path.write_text(css.rstrip("\n") + "\n\n" + block + "\n")
    except Exception:  # noqa: BLE001
        logger.warning("nav identity CSS injection skipped", exc_info=True)

    # CONTRAST GUARDRAIL — the agent authors :root palette vars freely, and a
    # bad --primary-foreground ships unreadable buttons (seen live: near-black
    # label on an espresso gradient). Recompute every filled-control
    # foreground from the actual fill with the same rule the DNA uses.
    #
    # Spec D Wave 1 (round 2) — brief-first: when brief.palette.foreground_hint
    # is authored (mid-tone brand + coloured fill = ambiguous contrast), we
    # use the hint verbatim for --primary-foreground instead of computing.
    # Accent/destructive still run the computed path (the hint applies to
    # the on-brand label; secondary fills keep their own contrast calc).
    try:
        import re as _re
        import colorsys as _cs
        from services.design_dna import _fg_for
        from services.brief_visual_stance import (
            get_foreground_hint,
            load_brief_from,
        )
        if globals_css_path.exists():
            css = globals_css_path.read_text()
            _brief_for_fg = load_brief_from(output_dir)
            _fg_hint_hex = get_foreground_hint(_brief_for_fg)

            def _hex_to_hsl_triplet(hex_str: str) -> str:
                """Convert #RRGGBB to '<hue> <sat>% <lig>%' for CSS vars."""
                h = hex_str.lstrip("#")
                r, g, b = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
                hh, ll, ss = _cs.rgb_to_hls(r, g, b)
                return f"{round(hh * 360)} {round(ss * 100)}% {round(ll * 100)}%"

            _fg_hint_triplet = (
                _hex_to_hsl_triplet(_fg_hint_hex) if _fg_hint_hex else None
            )

            def _triplet_to_hex(triplet: str) -> str | None:
                m = _re.match(r"\s*([\d.]+)\s+([\d.]+)%\s+([\d.]+)%", triplet)
                if not m:
                    return None
                h, sat, lig = (float(m.group(1)) / 360.0,
                               float(m.group(2)) / 100.0,
                               float(m.group(3)) / 100.0)
                r, g, b = _cs.hls_to_rgb(h, lig, sat)
                return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))

            changed = False
            for var in ("primary", "accent", "destructive"):
                fill = _re.search(rf"--{var}:\s*([^;]+);", css)
                if not fill:
                    continue
                fill_hex = _triplet_to_hex(fill.group(1))
                if not fill_hex:
                    continue
                # Brief-first: only overrides the on-brand (primary) label.
                if var == "primary" and _fg_hint_triplet is not None:
                    want = _fg_hint_triplet
                else:
                    want = _fg_for(fill_hex)
                css, n = _re.subn(rf"(--{var}-foreground:\s*)[^;]+;",
                                  rf"\g<1>{want};", css, count=1)
                if not n:
                    # The var is MISSING entirely (agent-authored :root often
                    # omits it) — Tailwind then resolves hsl(var(--x-fg)) to an
                    # invalid color and the label inherits page ink, which is
                    # unreadable on a dark fill. Insert it after the fill.
                    css, n = _re.subn(rf"(--{var}:\s*[^;]+;)",
                                      rf"\1\n  --{var}-foreground: {want};",
                                      css, count=1)
                changed = changed or bool(n)
            if changed:
                globals_css_path.write_text(css)
    except Exception:  # noqa: BLE001
        logger.warning("foreground contrast guardrail skipped", exc_info=True)

    return str(path)


def load_design_spec(output_dir: str) -> dict | None:
    """Load a previously saved design spec."""
    path = Path(output_dir) / "src" / "contracts" / "design-spec.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

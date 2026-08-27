"""Component Agent — generates all UI components.

Produces layout components (Navbar, Sidebar), shadcn/ui components,
and feature-specific components (tables, forms, cards per entity).
Reads the design-system contract for patterns.
"""

import os
import json
from pathlib import Path
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions
from services.sdk_agent_runner import query  # reliable Anthropic-SDK transport; bundled CLI wedges under throttle
from services.agent_messages import Message
from services.registry import load_registry, registry_summary_for_agent


COMPONENT_AGENT_SYSTEM_PROMPT = r"""You are a React component specialist for Next.js 15 + Tailwind CSS 4 + shadcn/ui projects.

## MOBILE-FIRST MANDATE (NON-NEGOTIABLE)
Every single component you generate MUST be fully responsive and work on mobile screens (320px+).
Before writing any component, ask: "Does this work on a 375px wide phone screen?"

Checklist — apply to EVERY component:
- [ ] No fixed widths (no `w-[500px]`) — use `max-w-*` with `w-full`
- [ ] No `overflow-hidden` on containers without a mobile scroll alternative
- [ ] Grids: ALWAYS `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3` (never fixed cols without breakpoints)
- [ ] Tables: ALWAYS have a `block md:hidden` card-list fallback — tables that overflow on mobile are FORBIDDEN
- [ ] Sidebar: `hidden md:flex` on desktop, replaced by `MobileNav.tsx` bottom tabs on mobile
- [ ] Buttons: minimum `h-10` touch target on mobile (`min-h-[44px]` for primary actions)
- [ ] Modals/Dialogs: full-screen on mobile (`sm:max-w-lg` but `w-full` on small screens)
- [ ] Forms: single-column on mobile, optional `md:grid-cols-2` on desktop
- [ ] Font sizes: never smaller than `text-sm` on body text; avoid `text-xs` for readable content
- [ ] Padding: `p-4 md:p-6` pattern — never just `p-8` without a smaller mobile value
- [ ] Flex rows: add `flex-wrap` or convert to `flex-col sm:flex-row` to prevent overflow

## RESPONSIVE TEMPLATES — COPY THESE EXACTLY

### Page container (every page):
```tsx
<div className="px-4 py-6 md:px-8 md:py-8">
```

### Page header with action button:
```tsx
<div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
  <div>
    <h1 className="text-xl md:text-2xl font-bold">Title</h1>
    <p className="text-sm text-muted-foreground">Description</p>
  </div>
  <div className="flex gap-2">
    <input className="h-9 w-full sm:w-64 rounded-md border px-3 text-sm" />
    <a href="/new" className="w-full sm:w-auto inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm text-white whitespace-nowrap">
      + New
    </a>
  </div>
</div>
```

### Stat cards grid:
```tsx
<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
```

### Content grid:
```tsx
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
```

### Data table with mobile card fallback (MANDATORY for every entity table):
```tsx
{/* Desktop table */}
<div className="hidden md:block rounded-lg border">
  <table className="w-full text-sm">...</table>
</div>
{/* Mobile cards */}
<div className="block md:hidden space-y-3">
  {items.map(item => (
    <div key={item.id} className="rounded-lg border bg-card p-4 space-y-2">
      <div className="font-medium">{item.name}</div>
      <div className="text-xs text-muted-foreground">{item.status}</div>
    </div>
  ))}
</div>
```

### Form layout:
```tsx
<div className="max-w-2xl mx-auto">
  <div className="rounded-xl border bg-card p-6 space-y-6">
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* fields */}
    </div>
    <div className="flex flex-col sm:flex-row gap-3 pt-4 border-t">
      <button className="w-full sm:w-auto rounded-md bg-primary px-6 py-2.5 text-sm text-white">Save</button>
      <a className="w-full sm:w-auto rounded-md border px-6 py-2.5 text-sm text-center">Cancel</a>
    </div>
  </div>
</div>
```

### Sidebar + MobileNav:
```tsx
{/* Desktop sidebar */}
<aside className="hidden md:flex w-64 flex-col border-r">...</aside>
{/* Mobile bottom nav */}
<nav className="fixed bottom-0 left-0 right-0 flex md:hidden items-center justify-around border-t bg-background h-16 z-50">
  <a className="flex flex-col items-center gap-1 text-xs">
    <Icon className="h-5 w-5" />
    <span>Home</span>
  </a>
</nav>
{/* Add bottom padding to main content for mobile nav */}
<main className="flex-1 overflow-auto pb-20 md:pb-0">...</main>
```

## YOUR JOB
Generate ALL UI components. Read the design-system contract and schema to understand patterns and data shapes, then create every component.

## COMPONENTS TO GENERATE

### Layout Components
- `src/components/layout/Navbar.tsx` — Top navigation bar:
  - App name/logo
  - Links to ALL pages from the plan (not just a few — ALL of them)
  - User menu with name/email display
  - Logout button using signOut from next-auth/react
  - "use client" directive (uses useSession)

- `src/components/layout/Sidebar.tsx` — Side navigation:
  - Links to EVERY page in the plan
  - Active state highlighting
  - Icons from lucide-react
  - Collapsible on mobile
  - "use client" directive (uses usePathname)

### shadcn/ui Components
Create each as a separate file in `src/components/ui/`:
- `button.tsx` — Button component with variants (default, destructive, outline, ghost)
- `card.tsx` — Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter
- `input.tsx` — Input component with label support
- `table.tsx` — Table, TableHeader, TableBody, TableRow, TableHead, TableCell
- `dialog.tsx` — Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter
- `badge.tsx` — Badge with variants (default, secondary, destructive, outline)
- `toast.tsx` — Toast notification component
- `skeleton.tsx` — Skeleton loading component
- `select.tsx` — Select dropdown component
- `textarea.tsx` — Textarea component
- `label.tsx` — Label component

Use the shadcn/ui pattern: React.forwardRef, cn() utility, cva variants, proper TypeScript types.

### Feature Components (per entity)
For each entity in plan.components:
- `src/components/[feature]/[Entity]Table.tsx` — Data table displaying entity records
  - Columns matching entity fields
  - Row actions (view, edit, delete)
  - Uses Table components from ui/
  - Import types from @/types/

- `src/components/[feature]/[Entity]Form.tsx` — Create/edit form
  - Fields for all entity attributes
  - Validation
  - Submit handling
  - Uses Input, Button, Select, etc. from ui/

### Workflow Components (ONLY if plan has workflows)
If plan.workflows exists and is non-empty, generate:

- `src/components/workflows/WorkflowCard.tsx` — Workflow summary card:
  - Shows workflow name, description, trigger type/event
  - Node count, process variable count
  - Links to workflow detail page (`/workflows/[id]`)
  - Uses Card from ui/

- `src/components/workflows/WorkflowNodeGraph.tsx` — Visual node graph:
  - Reads workflow definition JSON (nodes + edges)
  - Renders nodes as connected cards in a vertical flow
  - Each node shows: icon (by type), label, type badge
  - Edges shown as connecting lines/arrows between nodes
  - Node type colors: trigger=blue, action=green, condition=yellow, approval=orange, user_task=purple, end=gray
  - Highlight current node if workflow is paused

- `src/components/workflows/WorkflowNodeDetail.tsx` — Node detail panel:
  - Shows node label, description, type
  - **Input Parameters**: table of name, type, source (process variable)
  - **Output Parameters**: table of name, type, target (process variable)
  - **Config**: action type, expression, table/query details
  - **Form Binding** (for approval/user_task): shows form fields with labels and types
  - Expandable/collapsible

- `src/components/workflows/ProcessVariablesPanel.tsx` — Process variable viewer:
  - Table of all process variables: name, type, description, required, current value
  - During execution: shows live values flowing through
  - Color-coded by type (string=blue, number=green, boolean=purple, object=gray)

- `src/components/workflows/WorkflowExecutionLog.tsx` — Execution history:
  - Timeline of executed nodes with timestamps
  - Each entry shows: node label, status (completed/failed/paused), duration
  - Expandable to show resolvedInputs and producedOutputs per node
  - Failed nodes highlighted in red with error message

- `src/components/workflows/WorkflowTaskForm.tsx` — Dynamic form for human tasks:
  - Reads `formBinding` from the paused workflow node
  - Renders form fields dynamically based on formBinding.fields[]
  - Pre-fills values from `source` (process variables)
  - On submit: calls `/api/workflows/[id]/execute` with completed step data
  - For approval nodes: shows Approve + Reject buttons
  - For user_task nodes: shows Submit button
  - Connector lines between steps

- `src/components/workflows/TaskCard.tsx` — Task inbox card:
  - Shows task name, parent workflow name, status badge
  - Due date (if set), assigned at timestamp
  - Action buttons: "Complete Task", "View Details"
  - Uses Card, Badge, Button from ui/

### Shared Components
- `src/components/dashboard/StatsCard.tsx` — Dashboard stats card
- `src/components/shared/StatusBadge.tsx` — Status indicator badge
- Any other shared components from plan.shared_components

## CONFORMANCE
- Read `src/contracts/design-system.tsx` for page shell patterns
- Read `src/contracts/api-client.ts` for entity types to use in components
- **Read `src/contracts/design-spec.json`** for visual design decisions
- Sidebar MUST have links to EVERY page in the plan

## VISUAL DESIGN (CRITICAL — apps must NOT look like wireframes)

Read `src/contracts/design-spec.json` and apply its settings to EVERY component:

### Colors — use the design spec's colorPalette:
- **Primary color** for main CTAs, active sidebar item background, active tab, primary buttons
- **Secondary color** for secondary buttons, subtle backgrounds
- **Accent color** for hover states, links, focus rings
- Use `bg-[#hex]` and `text-[#hex]` with the EXACT hex values from design-spec

### Component Styling — based on design-spec.componentStyle:
- **Buttons (rounded|sharp|pill)**:
  - `rounded`: `rounded-lg` (default)
  - `sharp`: `rounded-none`
  - `pill`: `rounded-full`
  - Primary buttons get: `shadow-sm hover:shadow-md transition-all duration-150`
  - NEVER use flat unstyled buttons — every button should have depth

- **Cards (bordered|shadow|flat)**:
  - `bordered`: `border border-border rounded-xl`
  - `shadow`: `shadow-sm hover:shadow-md rounded-xl border-0`
  - `flat`: `bg-muted/50 rounded-xl border-0`
  - Cards MUST have `transition-shadow duration-200` for hover effects

- **Tables (striped|clean|bordered)**:
  - `striped`: alternate row backgrounds `even:bg-muted/30`
  - `clean`: no row borders, hover highlight `hover:bg-muted/50`
  - `bordered`: full borders on all cells

- **Inputs (outlined|filled|underlined)**:
  - `outlined`: default shadcn input
  - `filled`: `bg-muted/50 border-0 focus:bg-background`
  - `underlined`: `border-0 border-b rounded-none`

### Layout — based on design-spec.layout:
- **Navigation (sidebar|topbar|sidebar-dark)**:
  - `sidebar`: light sidebar with icon + label, active item uses primary color bg
  - `sidebar-dark`: dark sidebar (bg-slate-900), white text, active item uses bg-white/10
  - `topbar`: horizontal navigation bar at top
- **Density (compact|comfortable|spacious)**:
  - `compact`: tight padding (p-3, gap-2, text-sm)
  - `comfortable`: default (p-4, gap-4, text-sm)
  - `spacious`: generous (p-6, gap-6, text-base)

### MODERN UI RULES (NON-NEGOTIABLE — every component must follow these)

**Every Card:**
```
className="rounded-xl border bg-card shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5"
```

**Every Button (primary):**
```
className="rounded-lg bg-primary text-white shadow-sm transition-all duration-150 hover:bg-primary/90 hover:shadow-md active:scale-[0.98] disabled:opacity-50"
```

**Every Input/Select/Textarea:**
```
className="rounded-lg border border-input bg-background px-3 py-2 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
```

**Every Sidebar Item:**
```
className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all duration-150 hover:bg-muted"
// Active: add "bg-primary/10 text-primary font-medium"
```

**Every Table Row:**
```
className="border-b transition-colors hover:bg-muted/50"
```

**Every Badge/Status:**
```
className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium"
// Use status-dot before text: <span className="status-dot status-dot-success" />
```

**Dashboard Stat Card:**
```tsx
<div className="rounded-xl border bg-card p-5 shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5">
  <div className="flex items-center justify-between">
    <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Label</span>
    <div className="rounded-lg bg-primary/10 p-2">
      <Icon className="h-4 w-4 text-primary" />
    </div>
  </div>
  <p className="mt-3 text-2xl font-bold">{value}</p>
  <p className="mt-1 text-xs text-muted-foreground">{trend}</p>
</div>
```

**Dashboard Hero Banner:**
```tsx
<div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-primary to-primary/80 p-6 md:p-8 text-white">
  <div className="relative z-10">
    <p className="text-sm font-medium text-white/70 uppercase tracking-wide">Overview</p>
    <h1 className="mt-1 text-2xl md:text-3xl font-bold">Welcome back</h1>
    <p className="mt-1 text-white/80 text-sm">Here's what's happening today.</p>
  </div>
  <div className="absolute right-0 top-0 h-full w-1/3 bg-white/5 rounded-l-[100px]" />
</div>
```

**Loading Skeleton:**
```tsx
<div className="space-y-3 animate-pulse">
  <div className="h-4 w-3/4 rounded-md bg-muted" />
  <div className="h-4 w-full rounded-md bg-muted" />
  <div className="h-4 w-2/3 rounded-md bg-muted" />
</div>
```

**Empty State:**
```tsx
<div className="flex flex-col items-center justify-center py-16 text-center gap-4">
  <div className="rounded-full bg-muted p-4">
    <Inbox className="h-8 w-8 text-muted-foreground" />
  </div>
  <div>
    <h3 className="text-lg font-medium">No items yet</h3>
    <p className="mt-1 text-sm text-muted-foreground max-w-sm">Description text here.</p>
  </div>
  <Button>Create First Item</Button>
</div>
```

**NEVER produce:**
- Flat cards without shadow or border
- Buttons without hover/active state
- Inputs without focus ring
- Tables without row hover
- Status text without colored indicator
- Pages without proper spacing (use p-4 md:p-6 or p-6 md:p-8)

### Responsive Design (CRITICAL — ALL components must work on mobile):

- **Sidebar**:
  - Desktop (`md:` and up): full sidebar with icons + labels
  - Mobile: `hidden md:flex` for sidebar; show hamburger menu + slide drawer or bottom tabs instead
  - Generate a `MobileNav.tsx` component with bottom tab bar for mobile

- **Data Tables** — MUST have mobile view:
  - Desktop: `<table>` with all columns
  - Mobile: each row becomes a card. Use `hidden md:table` for table, `block md:hidden` for card list
  ```tsx
  {/* Desktop */}
  <div className="hidden md:block"><table>...</table></div>
  {/* Mobile */}
  <div className="block md:hidden space-y-3">
    {items.map(item => <MobileEntityCard key={item.id} item={item} />)}
  </div>
  ```

- **Grids** — always responsive:
  - `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4`
  - NEVER use fixed grid columns without breakpoints

- **Forms** — mobile-friendly:
  - `grid-cols-1 md:grid-cols-2` for wide forms
  - Full-width inputs on all breakpoints
  - Minimum touch target: `min-h-[44px]` on mobile buttons

- **Modals/Dialogs**:
  - Desktop: centered overlay with max-width
  - Mobile: full-screen sheet (`fixed inset-0` or bottom sheet)

### Imagery & Visual Assets:
Read design-spec.json `imagery` section and apply:

- **Login page background**: Use `imagery.loginBackground` as a hero image
  - Desktop: split layout with image on left, form on right
  - Mobile: image as overlay behind form with dark tint

- **Empty states**: use lucide-react icons as large centered illustrations
  - 64x64 icon, muted color, descriptive text, CTA button
  - Match `imagery.emptyStateStyle` (geometric, line-art, isometric, flat)

- **Avatars**: colored initials circles using primary/secondary
  ```tsx
  <div className="h-10 w-10 rounded-full bg-primary/10 text-primary flex items-center justify-center text-sm font-medium">
    {name?.charAt(0)?.toUpperCase()}
  </div>
  ```

- **Dashboard hero**: if `imagery.dashboardHero` is set, use as a gradient banner at top of dashboard

### Visual Richness (apps should feel premium):
- Dashboard stat cards: subtle gradient or colored left border (`border-l-4 border-primary`)
- Page headers: larger title (`text-xl md:text-2xl font-semibold`) + muted description
- Empty states: large icon + descriptive text + CTA button
- Loading states: skeleton shimmer (not spinner)
- Section dividers: subtle `border-t` with spacing
- Avatar/user displays: `rounded-full` with colored fallback background

## RULES
1. Read design-system contract, design-spec.json, AND navigation-flow.json BEFORE creating components.
   **navigation-flow.json** defines how components connect to pages and actions:
   - Sidebar groups and items must match the navigation.sidebar_groups in the flow contract
   - User menu must include the items from navigation.user_menu (Profile, Settings, Sign Out)
   - Entity tables must have action menus matching flows.entity_crud[Entity].list.actions
   - Entity forms must submit to the API endpoint specified in flows.entity_crud[Entity].create.submit
2. EVERY component listed in plan.components and plan.shared_components MUST be created
3. Sidebar MUST link to ONLY pages that exist — Glob src/app/ to check what pages are created by the page agent. Do NOT link to pages that don't exist.
4. Use Tailwind CSS for styling (not CSS modules)
5. Use "use client" directive only for interactive components (hooks, event handlers)
6. Import cn from "@/lib/utils" for className merging
7. shadcn/ui components should follow the standard pattern (forwardRef, CVA variants)
8. Feature tables must show ALL relevant columns from the entity
9. Feature forms must include ALL required fields EXCEPT system fields (id, createdAt, updatedAt)
10. Do NOT modify existing files
11. NEVER produce flat/wireframe looking components — every element needs depth (shadows, borders, or backgrounds)
12. Entity forms MUST have working onSubmit that POSTs to the API and redirects on success — NO TODO stubs
13. Entity tables MUST have action buttons: View (links to /[entity]/[id]), Edit, Delete
14. COMPILE CHECK: After creating all components, run `npx tsc --noEmit 2>&1 | grep "src/components" | head -20`.
    Fix any errors in YOUR files before finishing. A component that doesn't compile is not done.

## CRITICAL: COMPONENT IMPORT CONSISTENCY

After creating ALL components, pages will import from `@/components/ui/*` and `@/components/shared/*`.
You MUST create EVERY UI component that the design-system contract or plan references:
- avatar, badge, button, card, dialog, dropdown-menu, input, label, select, skeleton, switch, table, tabs, textarea, toast
- shared components: EmptyState, LoadingState, StatusBadge

Glob `src/components/ui/` and `src/components/shared/` when done — ensure all expected files exist.

## CRITICAL: AVATAR INITIALS — USE NAME FIELDS ONLY
When computing avatar initials, use person-name fields (firstName, lastName, name, email).
NEVER use password_hash, internal IDs, or opaque fields for display purposes.

## RULES & WORKFLOW INTEGRATION (CRITICAL)

The generated app has a runtime at `src/lib/rules` and `src/lib/workflows`. EVERY entity form
must use it for client-side validation, and forms whose submission triggers a workflow must
import `WorkflowTriggerButton` from `@/components/WorkflowTriggerButton`.

### Form pattern with rule validation
```tsx
"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { validateField, validateEntity } from "@/lib/rules";

export function EntityNameForm() {
  const [data, setData] = useState({ field1: "", field2: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleFieldChange = async (field: string, value: any) => {
    setData(prev => ({ ...prev, [field]: value }));
    // Live validation per-field
    const result = await validateField("EntityName", field, value, data);
    setErrors(prev => ({ ...prev, [field]: result.errors[0] || "" }));
  };

  const mutation = useMutation({
    mutationFn: async (values: any) => {
      const validation = await validateEntity("EntityName", values);
      if (!validation.valid) {
        throw new Error(validation.errors.join(", "));
      }
      const res = await fetch("/api/entityname", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!res.ok) throw new Error("Submit failed");
      return res.json();
    },
    onSuccess: () => {
      // Workflows will be triggered by the API route
    },
  });

  return (
    <form onSubmit={(e) => { e.preventDefault(); mutation.mutate(data); }}>
      <Input
        value={data.field1}
        onChange={(e) => handleFieldChange("field1", e.target.value)}
      />
      {errors.field1 && <p className="text-destructive text-sm">{errors.field1}</p>}
      <Button type="submit" disabled={mutation.isPending}>Save</Button>
    </form>
  );
}
```

### Workflow trigger buttons
For pages where users explicitly trigger a workflow (not via form submit), use the existing
`WorkflowTriggerButton` component:

```tsx
import { WorkflowTriggerButton } from "@/components/WorkflowTriggerButton";

<WorkflowTriggerButton
  workflowId="SurveyPublished"
  input={{ surveyId: survey.id }}
  label="Publish Survey"
  onSuccess={(result) => router.refresh()}
/>
```

DO NOT create a new WorkflowTriggerButton — it already exists at `src/components/WorkflowTriggerButton.tsx`.
Just import and use it.
"""


def _format_design_brief(spec: dict) -> str:
    """Format design spec into a concise, actionable brief for component agents."""
    from services.industry_design import generate_css_variables_from_spec

    colors = spec.get("colorPalette", {})
    style = spec.get("componentStyle", {})
    layout = spec.get("layout", {})
    typography = spec.get("typography", {})
    patterns = spec.get("entityPatterns", {})
    rationale = spec.get("designRationale", "")

    primary = colors.get("primary", "#1B2A40")
    secondary = colors.get("secondary", "#374151")
    accent = colors.get("accent", "#6172f3")
    background = colors.get("background", "#ffffff")
    surface = colors.get("surface", "#f9fafb")
    muted = colors.get("muted", "#f3f4f6")
    error = colors.get("error", "#ef4444")
    success = colors.get("success", "#22c55e")
    warning = colors.get("warning", "#f59e0b")

    # Handle buttons/cards being either a string or a dict
    btn_val = style.get("buttons", "rounded")
    if isinstance(btn_val, dict):
        btn_val = btn_val.get("radius", btn_val.get("style", "rounded"))
    btn_radius = {"rounded": "rounded-lg", "sharp": "rounded-none", "pill": "rounded-full"}.get(str(btn_val), "rounded-lg")
    card_val = style.get("cards", "shadow")
    if isinstance(card_val, dict):
        card_val = card_val.get("style", "shadow")
    card_style = {"bordered": "border border-border rounded-xl", "shadow": "shadow-sm hover:shadow-md rounded-xl border-0", "flat": "bg-muted/50 rounded-xl border-0"}.get(str(card_val), "shadow-sm rounded-xl")
    table_val = style.get("tables", "clean")
    table_style = table_val if isinstance(table_val, str) else "clean"
    input_val = style.get("inputs", "outlined")
    input_style = input_val if isinstance(input_val, str) else "outlined"
    density = layout.get("density", "comfortable")
    nav_type = layout.get("navigation", "sidebar")

    density_map = {"compact": "p-3 gap-2 text-sm", "comfortable": "p-4 gap-4 text-sm", "spacious": "p-6 gap-6 text-base"}
    density_classes = density_map.get(density, "p-4 gap-4 text-sm")

    entity_pattern_lines = "\n".join(f"  - {k}: {v}" for k, v in patterns.items()) if patterns else "  (default: table)"

    # Pre-compute globals.css so agents don't have to convert hex→HSL manually
    globals_css = generate_css_variables_from_spec(spec)

    return f"""
## ━━ DESIGN SPEC — APPLY TO EVERY COMPONENT ━━

> {rationale}

### Colors (use EXACT hex values with Tailwind's arbitrary value syntax)
| Role       | Hex       | Tailwind Usage                        |
|------------|-----------|---------------------------------------|
| Primary    | {primary} | `bg-[{primary}]` `text-[{primary}]`  |
| Secondary  | {secondary} | `bg-[{secondary}]` `text-[{secondary}]` |
| Accent     | {accent}  | `bg-[{accent}]` hover/focus rings     |
| Background | {background} | page background                    |
| Surface    | {surface} | card/panel backgrounds               |
| Muted      | {muted}   | subtle backgrounds, disabled states  |
| Error      | {error}   | `text-[{error}]` `border-[{error}]`  |
| Success    | {success} | `text-[{success}]`                   |
| Warning    | {warning} | `text-[{warning}]`                   |

### Component Styles
- **Buttons**: `{btn_radius} bg-[{primary}] text-white hover:opacity-90 transition-all shadow-sm` for primary
- **Cards**: `{card_style}` — NEVER use flat/borderless cards without a background
- **Tables**: {table_style} — {"even:bg-[" + muted + "]" if table_style == "striped" else "hover:bg-[" + surface + "]" if table_style == "clean" else "border border-border"}
- **Inputs**: {input_style}
- **Density**: `{density_classes}` — apply this spacing consistently

### Navigation: {nav_type}
- Sidebar active item: `bg-[{primary}] text-white`
- Sidebar inactive: `text-gray-600 hover:bg-[{surface}]`
- Mobile: bottom tab bar with primary color active indicator

### Entity View Patterns (use these layouts for each entity's list/detail)
{entity_pattern_lines}

### Typography
- Font: {typography.get("fontFamily", "Inter")}
- Headings: font-weight {typography.get("headingWeight", "600")}
- Body: {typography.get("bodySize", "14px")}

### Do NOT
- ❌ Use hardcoded Tailwind color names like `bg-blue-600`, `bg-slate-900` — use the hex values above
- ❌ Leave buttons unstyled or use `variant="ghost"` where a styled button is needed
- ❌ Skip hover/active states on interactive elements
- ❌ Use flat, borderless cards with no visual depth

### globals.css — PRE-COMPUTED (use this VERBATIM for src/app/globals.css)
All hex→HSL conversions are already done. Copy this exactly:
```css
{globals_css}
```
"""


async def run_component_agent(
    output_dir: str,
    plan: dict,
    domain_context: dict | None = None,
    design_spec: dict | None = None,
    ux_spec: str = "",
) -> AsyncIterator[Message]:
    """Generate all UI components.

    Yields streaming messages for SSE forwarding.
    """
    from services.domain_context import build_domain_profile

    os.environ.pop("CLAUDECODE", None)

    # Load registry for entity + route context
    registry = load_registry(output_dir)
    registry_context = registry_summary_for_agent(registry, ["entities", "api_routes"])

    # Load design spec from disk if not passed in
    if design_spec is None:
        from agents.design_agent import load_design_spec
        design_spec = load_design_spec(output_dir)

    domain_profile = build_domain_profile(domain_context, "component_builder")

    components = plan.get("components", [])
    shared_components = plan.get("shared_components", [])
    pages = plan.get("pages", [])
    models = plan.get("data_models", [])

    # Build component checklist — EVERY component the app needs
    checklist = []

    # 1. Layout components (MANDATORY)
    checklist.append("### Layout Components (MANDATORY)")
    checklist.append("- [ ] src/components/layout/Navbar.tsx — Top bar with app name, user menu, logout")
    checklist.append("- [ ] src/components/layout/Sidebar.tsx — Side navigation with links to ALL pages")
    checklist.append("- [ ] src/components/layout/MobileNav.tsx — Bottom tab bar for mobile (hidden md:flex for sidebar, flex md:hidden for mobile)")

    # 2. shadcn/ui base components (MANDATORY)
    checklist.append("### UI Components (MANDATORY — shadcn/ui pattern)")
    for ui in ["button", "card", "input", "table", "dialog", "badge", "toast", "skeleton", "select", "textarea", "label", "dropdown-menu"]:
        checklist.append(f"- [ ] src/components/ui/{ui}.tsx")

    # 3. Shared/dashboard components
    checklist.append("### Shared Components")
    checklist.append("- [ ] src/components/dashboard/StatsCard.tsx — Stat card with icon, value, label, trend")
    checklist.append("- [ ] src/components/shared/StatusBadge.tsx — Status with colored dot + text")
    checklist.append("- [ ] src/components/shared/EmptyState.tsx — Empty state with icon, title, description, CTA")
    checklist.append("- [ ] src/components/shared/LoadingState.tsx — Skeleton loading placeholder")
    checklist.append("- [ ] src/components/shared/ConfirmDialog.tsx — Confirmation dialog for delete actions")

    # 4. Per-entity components (MANDATORY — one Table + one Form per entity)
    import re as _re
    checklist.append(f"### Entity Components ({len(models)} entities × 2 = {len(models) * 2} components)")
    for m in models:
        name = m.get("name", "")
        if not name:
            continue
        slug = _re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower().replace("_", "-")
        fields = [f.get("name", "") for f in m.get("fields", []) if f.get("name") not in ("id", "createdAt", "updatedAt", "created_at", "updated_at")]
        checklist.append(f"- [ ] src/components/{slug}/{name}Table.tsx — Table with columns: {', '.join(fields[:6])}")
        checklist.append(f"- [ ] src/components/{slug}/{name}Form.tsx — Form with fields: {', '.join(fields[:6])}")

    # 5. Plan-specific components
    for comp in components:
        checklist.append(f"- [ ] {comp.get('file', comp.get('name', '?'))}: {comp.get('description', '')}")
    for comp in shared_components:
        checklist.append(f"- [ ] {comp.get('file', comp.get('name', '?'))}: {comp.get('description', '')}")

    # 6. Workflow components if plan has workflows
    if plan.get("workflows"):
        checklist.append("### Workflow Components")
        checklist.append("- [ ] src/components/workflows/WorkflowCard.tsx — summary card for list page")
        checklist.append("- [ ] src/components/workflows/WorkflowNodeGraph.tsx — visual node graph")
        checklist.append("- [ ] src/components/workflows/WorkflowNodeDetail.tsx — node I/O params + config")
        checklist.append("- [ ] src/components/workflows/ProcessVariablesPanel.tsx — process var viewer")
        checklist.append("- [ ] src/components/workflows/WorkflowExecutionLog.tsx — execution history")
        checklist.append("- [ ] src/components/workflows/WorkflowTaskForm.tsx — dynamic form for human tasks")

    # Page list for Sidebar
    page_links = "\n".join(
        f"- `{p.get('route', '/')}` → {p.get('name', p.get('component', '?'))}"
        for p in pages
    )

    design_brief = _format_design_brief(design_spec) if design_spec else ""

    user_prompt = f"""Generate ALL UI components for this project.
{design_brief}

Read `src/contracts/design-spec.json` FIRST — it contains the COMPLETE design system:
colors, typography, spacing, shadows, animations, entity patterns, component styles,
navigation groups, status colors, dashboard widgets, compliance requirements.
Follow it precisely for every component you create.
## Component Checklist ({len(checklist)} items)
{chr(10).join(checklist)}

## Pages for Sidebar Navigation (MUST link to ALL)
{page_links}

## Data Models ({len(models)} entities)
{chr(10).join(f"- {m.get('name', '?')}: {', '.join(f.get('name', '') for f in m.get('fields', []))}" for m in models)}

## Registry: Known Entities & API Routes
{registry_context}

You MUST use these exact entity field names when displaying data. You MUST call these exact API routes for data fetching. Do NOT invent field names or API endpoints.

## Steps
1. Apply the DESIGN SPEC above to every component — this is your visual guide
2. Read src/contracts/design-system.tsx for UI patterns
3. Read src/contracts/api-client.ts for entity types
4. Read src/db/schema/ for field definitions
5. Create layout components (Navbar, Sidebar) — Sidebar MUST have links to ALL {len(pages)} pages
6. Create ALL shadcn/ui components
7. Create feature components for each entity (tables, forms) using the entity patterns from the DESIGN SPEC
8. Create shared components (StatsCard, StatusBadge, etc.)
9. Verify every item in the checklist is created

## Full Plan
```json
{json.dumps(plan, indent=2)}
```

Start by reading the contract files."""

    # PHASE-2 brief injection: prepend the design brief as a contract
    # block when it exists on disk AND FORGE_BRIEF_CONSUME is on. Silent
    # no-op otherwise — old design_spec path still works.
    _brief_block = ""
    if os.getenv("FORGE_BRIEF_CONSUME", "0") == "1":
        try:
            from services.design_brief_to_prompt import (
                brief_to_prompt, load_brief_from_disk,
            )
            _b = load_brief_from_disk(output_dir)
            if _b is not None:
                _brief_block = "\n\n" + brief_to_prompt(_b)
        except Exception:  # noqa: BLE001
            pass

    options = ClaudeAgentOptions(
        system_prompt=COMPONENT_AGENT_SYSTEM_PROMPT + _brief_block + domain_profile,
        allowed_tools=["Write", "Edit", "Read", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=40,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message

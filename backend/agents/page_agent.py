"""Page Agent — generates all pages and layouts.

Reads EVERYTHING from disk (schema, types, components, API routes, services, contracts)
and produces all page files, layouts, globals.css, and error pages.
"""

import os
import json
from pathlib import Path
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions
from services.sdk_agent_runner import query  # reliable Anthropic-SDK transport; bundled CLI wedges under throttle
from services.agent_messages import Message
from services.registry import load_registry, registry_summary_for_agent


PAGE_AGENT_SYSTEM_PROMPT = r"""You are a page generation specialist for Next.js 15 App Router projects.

## YOUR JOB
Generate ALL pages and layouts. Read contracts from disk first, then create pages.

## STEP 1 (MANDATORY): Read these files before writing ANY page
1. `src/contracts/navigation-flow.json` — defines EVERY button, link, form submit, redirect
2. `src/contracts/event-bindings.json` — defines which data ops trigger workflows and what UI actions exist
3. `src/contracts/design-spec.json` — colors, typography, layout
4. `src/contracts/api-client.ts` — data fetching functions
5. `src/contracts/design-system.tsx` — page shell components

The [DOMAIN PROFILE] section in your system prompt already lists the design
patterns and form conventions common in this domain. Use those as guidance
for picking the right shape per page (table vs. cards, dense vs. spacious).

## TWO API ENGINES — use the right one per action
- **Data Engine** (`/api/data/{entity}`) — all CRUD: list, get, create, update, delete, stats
  ```tsx
  fetch("/api/data/tasks", { method: "POST", body: JSON.stringify(data) })
  ```
- **Workflow Engine** (`/api/workflows/{workflowId}/execute`) — business actions: approve, reject, escalate
  ```tsx
  fetch("/api/workflows/TaskApprovalWorkflow/execute", {
    method: "POST",
    body: JSON.stringify({ taskId: id, decision: "approved", user: session.user })
  })
  ```
- Read `navigation-flow.json` to know which engine each action uses
- Workflow action buttons should ONLY be visible when conditions are met (e.g., `status === "pending_approval"`)
- Example:
  ```tsx
  {item.status === "pending_approval" && (
    <div className="flex gap-2">
      <button onClick={() => executeWorkflow("approve")} className="bg-green-600 ...">Approve</button>
      <button onClick={() => executeWorkflow("reject")} className="border-red-500 ...">Reject</button>
    </div>
  )}
  ```

## CSS VARIABLES ONLY — NEVER hardcode colors (NON-NEGOTIABLE)
ALWAYS use CSS variable classes from globals.css. NEVER use hardcoded Tailwind colors.
- `bg-background` NOT `bg-gray-50` or `bg-white`
- `text-foreground` NOT `text-gray-900` or `text-black`
- `text-primary` NOT `text-blue-600` or `text-indigo-500`
- `bg-primary text-primary-foreground` NOT `bg-blue-600 text-white`
- `bg-card text-card-foreground` NOT `bg-white text-gray-800`
- `border-border` NOT `border-gray-200`
- `text-muted-foreground` NOT `text-gray-500`
Exception: status colors (green-600 for success, red-500 for error) are OK for contextual indicators.

## MOBILE-FIRST (apply to every page)
- Container: `px-4 py-6 md:px-8` — Tables: `hidden md:block` + mobile card fallback
- Grids: `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4` — Buttons: `w-full sm:w-auto`

## ROUTE STRUCTURE (non-negotiable)
```
src/app/
  layout.tsx           ← root: providers (QueryClient + Session + Toaster)
  providers.tsx        ← "use client" wrapper with QueryClientProvider
  page.tsx             ← redirect("/dashboard")
  login/page.tsx       ← OUTSIDE (dashboard)/ — NO sidebar
  signup/page.tsx      ← OUTSIDE (dashboard)/ — NO sidebar
  (dashboard)/
    layout.tsx         ← Navbar + Sidebar wrapper
    page.tsx           ← Dashboard with hero + stats
    [entity]/page.tsx  ← List pages
    [entity]/[id]/page.tsx ← Detail pages
    [entity]/new/page.tsx  ← Create forms
```

## NON-NEGOTIABLE RULES
1. Read ALL contracts (design-system, api-client, services, navigation-flow.json) AND design-spec.json before creating pages.
   **CRITICAL: navigation-flow.json** defines the COMPLETE user journey — every button, link, form submit,
   redirect, toast notification, and cross-entity navigation. Follow it exactly.
   - List pages: wire up search, create button, table row click, action menu (edit/delete) per the flow
   - Create pages: wire submit to the exact API endpoint, on_success redirect + toast, on_error show validation
   - Detail pages: wire all action buttons (edit, delete, view related entities) per the flow
   - Dashboard: wire stat card clicks to navigate to entity lists, quick actions to create pages
   - User menu: wire Sign Out to signOut() with redirect to /login
2. Read existing components (Navbar, Sidebar, entity tables/forms) to use them correctly
3. EVERY page from the plan MUST be created — not some, ALL
4. Pages must use the page shells from design-system contract
5. Pages must call api-client functions for data fetching (NOT raw fetch)
6. Dashboard must show stats from ALL entities
7. Use Server Components by default; "use client" only for interactive pages
8. `params` and `searchParams` are Promises in Next.js 15 — must `await` them
9. Import components from their actual file paths (verify they exist with Glob)
10. Create proper (dashboard) route group layout with Navbar + Sidebar
11. Do NOT modify existing files — only create page/layout files
12. NEVER create a wireframe-looking page. Every page must have depth (shadows), hierarchy (sizes), and interactivity (hover effects).
13. MOBILE RESPONSIVE — every page must follow the MOBILE-FIRST MANDATE above. A page that only works on desktop is INCOMPLETE.
14. FIELD NAMES MUST MATCH DRIZZLE SCHEMA: Drizzle ORM uses camelCase JS property names (firstName, dateOfBirth) NOT the snake_case DB column names (first_name, date_of_birth). When you create form state, use camelCase: `useState({ firstName: "", lastName: "" })`. When displaying data from API responses, use camelCase: `{item.firstName}`. The API's `db.insert(table).values({...data})` spread SILENTLY IGNORES snake_case keys — they don't match any Drizzle property.
15. VARIABLE NAMES MUST BE VALID JS: Use camelCase for ALL variables derived from entity names.
    - Entity slug `lab-orders` → variable `labOrders`, NOT `lab-orders`
    - Entity slug `time-entries` → variable `timeEntries`, NOT `time-entries`
    - NEVER use hyphens in variable names — JS treats them as minus operator
    - URL paths keep hyphens: `/lab-orders`, but variables are camelCase: `labOrdersData`
15. EVERY FILE MUST BE SYNTACTICALLY VALID: Before finishing, mentally trace every `{`, `(`, `<` to ensure it has a matching close. Missing brackets = broken app.

## FINAL VERIFICATION CHECKLIST
Before finishing, you MUST:

1. Run `npx tsc --noEmit 2>&1 | grep "src/app" | head -30` to check for compile errors
2. If ANY errors, READ the failing file, FIX the error, re-run the check
3. Then verify:
   - [ ] `src/app/page.tsx` exists (root redirect)
   - [ ] Every list page has a "Create New" button
   - [ ] Every create page has a working mutation (no TODOs)
   - [ ] No forms have id/createdAt/updatedAt fields
   - [ ] Every sidebar link has a matching page
   - [ ] Dashboard fetches stats from /api/[entity]/stats

DO NOT finish until `npx tsc --noEmit` has zero errors in files you created.
A developer who doesn't compile-check their code before submitting is not doing their job.
"""


async def run_page_agent(
    output_dir: str,
    plan: dict,
    domain_context: dict | None = None,
    design_spec: dict | None = None,
    fix_prompt: str | None = None,
) -> AsyncIterator[Message]:
    """Generate all pages and layouts.

    If ``fix_prompt`` is provided, this is a gate-triggered re-run — the agent
    only fixes the specific issues listed, not a full regeneration.

    Yields streaming messages for SSE forwarding.
    """
    from services.domain_context import build_domain_profile
    from agents.component_agent import _format_design_brief

    os.environ.pop("CLAUDECODE", None)

    # Load registry for full context
    registry = load_registry(output_dir)
    registry_context = registry_summary_for_agent(registry, ["entities", "api_routes", "components"])

    # Load design spec from disk if not passed in
    if design_spec is None:
        from agents.design_agent import load_design_spec
        design_spec = load_design_spec(output_dir)

    domain_profile = build_domain_profile(domain_context, "page_assembler")

    pages = plan.get("pages", [])
    layouts = plan.get("layouts", [])
    models = plan.get("data_models", [])

    # Build page checklist — ensure every entity gets list+detail+create
    checklist = []
    checklist.append("- [ ] src/app/page.tsx (root redirect to /dashboard)")
    checklist.append("- [ ] src/app/globals.css")
    checklist.append("- [ ] src/app/layout.tsx (root)")
    checklist.append("- [ ] src/app/(dashboard)/layout.tsx")
    checklist.append("- [ ] src/app/(dashboard)/page.tsx (dashboard with stats)")

    # Ensure every entity has list + detail + create pages
    import re as _re
    entity_routes_added = set()
    for m in models:
        name = m.get("name", "")
        if not name:
            continue
        slug = _re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower().replace("_", "-")
        fields = [f.get("name", "") for f in m.get("fields", [])]
        checklist.append(f"- [ ] /{slug}/page.tsx — List page for {name} (with Create New button, search, table)")
        checklist.append(f"- [ ] /{slug}/[id]/page.tsx — Detail page for {name}")
        checklist.append(f"- [ ] /{slug}/new/page.tsx — Create form for {name} (fields: {', '.join(f for f in fields if f not in ('id', 'createdAt', 'updatedAt', 'created_at', 'updated_at'))})")
        entity_routes_added.add(slug)

    # Add plan-specific pages not covered by entity CRUD
    for page in pages:
        route = page.get("route", page.get("path", "?"))
        name = page.get("name", page.get("component", "?"))
        slug = route.strip("/").split("/")[0] if route else ""
        if slug and slug not in entity_routes_added and route not in ("/", "/dashboard"):
            checklist.append(f"- [ ] {name} at `{route}`")

    for layout in layouts:
        checklist.append(f"- [ ] Layout: {layout.get('file', layout.get('route', '?'))}")
    # Add workflow pages if plan has workflows
    if plan.get("workflows"):
        checklist.append("- [ ] src/app/(dashboard)/workflows/page.tsx — Workflow list")
        checklist.append("- [ ] src/app/(dashboard)/workflows/[id]/page.tsx — Workflow detail")
    checklist.append("- [ ] src/app/login/page.tsx")
    checklist.append("- [ ] src/app/signup/page.tsx")
    checklist.append("- [ ] src/app/error.tsx")
    checklist.append("- [ ] src/app/not-found.tsx")
    checklist.append("- [ ] src/app/loading.tsx")

    design_brief = _format_design_brief(design_spec) if design_spec else ""

    user_prompt = f"""Generate ALL pages and layouts for this project.
{design_brief}

Read `src/contracts/design-spec.json` FIRST — it contains the COMPLETE design system:
colors, typography, spacing, shadows, animations, entity patterns, page layouts,
navigation groups, status colors, dashboard widgets, compliance requirements.
Follow it precisely for every page you create.
## Page Checklist ({len(checklist)} items)
{chr(10).join(checklist)}

## Pages from Plan ({len(pages)} pages)
{chr(10).join(f"- `{p.get('route', '/')}` → {p.get('name', '?')}: {p.get('description', '')}" for p in pages)}

## Layouts from Plan ({len(layouts)} layouts)
{chr(10).join(f"- {l.get('file', l.get('route', '?'))}: {l.get('description', '')}" for l in layouts)}

## Data Models ({len(models)} entities — for dashboard stats)
{chr(10).join(f"- {m.get('name', '?')}" for m in models)}

## Registry: Known Entities, Routes & Components
{registry_context}

You MUST import only components that exist in the registry above. You MUST call only API routes listed above. You MUST use exact field names from the entity definitions.

## Steps
1. Read `src/contracts/navigation-flow.json` — this defines EVERY user interaction
2. Read `src/contracts/design-spec.json` and `src/contracts/design-system.tsx`
3. Read `src/contracts/api-client.ts` for data fetching functions
4. Glob `src/components/` and `src/app/api/` to know what exists
5. DO NOT overwrite globals.css if it exists — the Design Agent created it
6. Write `src/app/providers.tsx` (Pattern 6: QueryClient + Session + Toaster)
7. Write `src/app/layout.tsx` (Pattern 5: root layout with Providers)
8. Write `src/app/(dashboard)/layout.tsx` (Navbar + Sidebar shell)
9. Write dashboard page (Pattern 1: hero + stats — wire clicks per navigation-flow.json)
10. Write list pages (Pattern 2: search + create button + table — wire ALL actions per flow)
11. Write create pages (Pattern 3: form + submit → API + redirect — per flow)
12. Write detail pages (Pattern 4: view + edit + delete — wire ALL actions per flow)
13. Write login/signup, error, not-found, loading pages
14. Verify ALL {len(pages)} pages from the plan are created

## Full Plan
```json
{json.dumps(plan, indent=2)}
```

Start by reading the contract files and listing existing components."""

    # If this is a gate-triggered fix run, use the fix prompt instead
    if fix_prompt:
        user_prompt = f"""Fix the following issues in the generated pages.
{design_brief}

{fix_prompt}

## Registry: Known Entities, Routes & Components
{registry_context}

Read the existing files, then fix ONLY the issues listed above. Do NOT regenerate pages that already work."""

    # Scale turns for large apps
    max_turns = 35
    if len(pages) > 15:
        max_turns = 50
    if fix_prompt:
        max_turns = 20  # Fix runs are smaller

    # PHASE-2 brief injection (see component_agent for the rationale).
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
        system_prompt=PAGE_AGENT_SYSTEM_PROMPT + _brief_block + domain_profile,
        allowed_tools=["Write", "Edit", "Read", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=max_turns,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message

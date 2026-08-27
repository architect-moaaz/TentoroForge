"""Completeness Checker Agent — verifies ALL planned artifacts were created and fills gaps."""

import os
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message


COMPLETENESS_CHECKER_PROMPT = r"""You are a completeness checker for generated Next.js full-stack applications.

## YOUR JOB
You receive a plan (JSON) that specifies what should exist: data models, API routes, components,
layouts, pages, and workflows. Your job is to verify they ALL exist and create any that are missing.

## VERIFICATION STEPS

### 1. Database Schema
- Read `src/db/schema.ts`
- Verify EVERY table from `plan.data_models` is defined
- Verify all relations from `plan.relations` are implemented
- If any table is missing, add it to the schema file

### 2. API Routes
- Run `find src/app/api -name "route.ts" -o -name "route.tsx"` to list all API route files
- Verify EVERY route from `plan.api_routes` has a corresponding file
- Missing route files must be created with: auth check, zod validation, proper DB queries, error handling
- Read an existing API route for patterns before creating missing ones

### 3. Components
- Run `find src/components -name "*.tsx"` to list all component files
- Verify components from `plan.components` and `plan.shared_components` exist
- Missing components must be created with real functionality (not stubs)
- Read existing components for patterns (imports, styling, prop patterns)

### 4. Layouts
- Check all layouts from `plan.layouts` exist
- Verify root layout has SessionProvider
- Verify app layout has Navbar + Sidebar
- The Sidebar MUST have navigation links to EVERY page in the app

### 5. Pages
- Run `find src/app -name "page.tsx"` to list all page files
- Verify EVERY page from `plan.pages` has a page.tsx file
- Missing pages must have REAL functionality:
  - List pages: data fetching, table, search, filters, create button
  - Detail pages: data fetching by ID, display fields, edit form, delete
  - Create pages: form with all fields, validation, submit, redirect
  - Dashboard: stats cards, recent items, summary data

### 6. Sidebar Navigation
- Read the Sidebar component
- Verify it has links to EVERY page route in the plan
- If links are missing, add them

### 7. Seed Data
- Verify `src/db/seed.ts` exists and includes:
  - Default admin user (admin@example.com / password123)
  - Sample data for EVERY table (10-20 rows)

## CREATION RULES
When creating missing artifacts:
- Read the database schema (src/db/schema.ts) to understand data models
- Read an existing similar file for patterns (styling, auth, data fetching, imports)
- Follow the same coding style and component library (shadcn/ui)
- Include proper data fetching, forms, validation, loading states
- Add "use client" directive for components/pages with interactivity
- Import and use existing shared components (Navbar, Sidebar, etc.)
- API routes must actually query the database using Drizzle ORM

## DO NOT
- Skip any planned artifact
- Create placeholder/stub code — everything must have real functionality
- Break existing files while adding new ones
- Change the database schema structure (only ADD missing tables)
- Rewrite existing files that are working correctly
"""


async def run_completeness_checker(
    output_dir: str,
    plan: dict,
) -> AsyncIterator[Message]:
    """Check that ALL planned artifacts were generated, fill any gaps.

    Verifies: data models, API routes, components, layouts, pages, seed data.
    Yields streaming messages for SSE forwarding.
    """
    os.environ.pop("CLAUDECODE", None)

    import json

    # Build detailed artifact summary
    sections = []

    models = plan.get("data_models", [])
    if models:
        lines = [f"  {i}. {m.get('name', '?')} ({len(m.get('fields', []))} fields)" for i, m in enumerate(models, 1)]
        sections.append(f"### Data Models ({len(models)} tables):\n" + "\n".join(lines))

    api_routes = plan.get("api_routes", [])
    if api_routes:
        lines = [f"  {i}. {r.get('method', 'GET')} {r.get('path', '?')}: {r.get('description', '')}" for i, r in enumerate(api_routes, 1)]
        sections.append(f"### API Routes ({len(api_routes)} endpoints):\n" + "\n".join(lines))

    components = plan.get("components", [])
    shared_components = plan.get("shared_components", [])
    all_components = components + shared_components
    if all_components:
        lines = [f"  {i}. {c.get('name', '?')} → {c.get('file', '?')}" for i, c in enumerate(all_components, 1)]
        sections.append(f"### Components ({len(all_components)} total):\n" + "\n".join(lines))

    layouts = plan.get("layouts", [])
    if layouts:
        lines = [f"  {i}. {l.get('file', l.get('route', '?'))}: {l.get('description', '')}" for i, l in enumerate(layouts, 1)]
        sections.append(f"### Layouts ({len(layouts)} layouts):\n" + "\n".join(lines))

    pages = plan.get("pages", [])
    if pages:
        lines = [f"  {i}. {p.get('route', p.get('path', '?'))}: {p.get('name', p.get('component', ''))}" for i, p in enumerate(pages, 1)]
        sections.append(f"### Pages ({len(pages)} pages):\n" + "\n".join(lines))

    workflows = plan.get("workflows", [])
    if workflows:
        lines = [f"  {i}. {w.get('name', '?')}: {', '.join(w.get('steps', []))}" for i, w in enumerate(workflows, 1)]
        sections.append(f"### Workflows ({len(workflows)}):\n" + "\n".join(lines))

    total = len(models) + len(api_routes) + len(all_components) + len(layouts) + len(pages)
    artifact_summary = "\n\n".join(sections)

    user_prompt = f"""Verify that ALL {total} planned artifacts were generated. Create any that are missing.

{artifact_summary}

## Full Plan:
```json
{json.dumps(plan, indent=2)}
```

## Verification Steps:
1. Check database schema — `cat src/db/schema.ts` — verify all {len(models)} tables exist
2. Check API routes — `find src/app/api -name "route.ts"` — verify all {len(api_routes)} endpoints exist
3. Check components — `find src/components -name "*.tsx"` — verify all {len(all_components)} components exist
4. Check layouts — verify layout files exist for each route group
5. Check pages — `find src/app -name "page.tsx"` — verify all {len(pages)} pages exist
6. Check Sidebar navigation has links to EVERY page
7. Check seed data exists with admin user + sample data for all tables
8. For EVERY missing artifact: read existing similar files for patterns, then create the missing file with real working code
9. Do NOT run npm run build — that's handled by the next step

Start by running the verification commands to see what exists vs what's missing."""

    options = ClaudeAgentOptions(
        system_prompt=COMPLETENESS_CHECKER_PROMPT,
        allowed_tools=["Write", "Edit", "Read", "Bash", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=50,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message

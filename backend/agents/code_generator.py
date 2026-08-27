"""Code Generator Agent — generates full-stack Next.js + PostgreSQL + Drizzle apps from text description."""

import os
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message


CODE_GENERATOR_SYSTEM_PROMPT = r"""You are a senior full-stack developer who builds production-ready internal business applications.

## YOUR ROLE
Given a text description (and optional plan JSON), you generate a complete full-stack application with:
- **Frontend**: Next.js 15 + React 19 + Tailwind CSS 4 + shadcn/ui components
- **Backend API**: Next.js API routes (app/api/)
- **Database**: PostgreSQL via Drizzle ORM
- **Authentication**: NextAuth.js v5 with credentials + JWT session strategy
- **Docker**: docker-compose.yml for PostgreSQL

## ARCHITECTURE — Clean Architecture Layers
1. **Auth Layer** (`src/auth.ts`, `src/app/api/auth/`) — NextAuth.js configuration, login/signup pages
2. **UI Layer** (`src/app/`) — Pages, layouts, client components
3. **Components** (`src/components/`) — Reusable UI components using shadcn/ui patterns
4. **API Layer** (`src/app/api/`) — REST API routes with proper error handling & auth middleware
5. **Data Layer** (`src/db/`) — Drizzle schema, migrations, queries
6. **Types** (`src/types/`) — Shared TypeScript types
7. **Middleware** (`src/middleware.ts`) — Route protection, auth checks

## FILES TO GENERATE (40+ files typical)

### Root config
- `package.json` — next, react, tailwindcss, drizzle-orm, drizzle-kit, postgres, dotenv, next-auth, bcryptjs, zod
- `postcss.config.mjs` — @tailwindcss/postcss
- `tsconfig.json` — standard Next.js
- `next.config.ts` — standard
- `docker-compose.yml` — PostgreSQL 16 service
- `drizzle.config.ts` — Drizzle Kit configuration
- `.env.local.example` — All environment variables with descriptions:
  ```
  DATABASE_URL=postgresql://user:pass@localhost:5432/dbname
  NEXTAUTH_SECRET=generate-a-random-secret-here
  NEXTAUTH_URL=http://localhost:3000
  ```

### Authentication (REQUIRED)
- `src/auth.ts` — NextAuth.js v5 config with CredentialsProvider, JWT strategy, bcrypt password comparison
- `src/app/api/auth/[...nextauth]/route.ts` — NextAuth API route handler
- `src/app/api/auth/signup/route.ts` — POST signup route: validate email/password with zod, hash password with bcryptjs, insert into users table, return success
- `src/app/(auth)/login/page.tsx` — Login form with email/password, error handling, redirect to dashboard
- `src/app/(auth)/signup/page.tsx` — Signup form with email/name/password, validation, redirect to login
- `src/app/(auth)/layout.tsx` — Centered auth layout
- `src/middleware.ts` — NextAuth middleware: protect all routes except /login, /signup, /api/auth/*, static assets
- `src/db/schema.ts` — MUST include a `users` table with: id, email (unique), name, passwordHash, role (default 'user'), createdAt, updatedAt
- `src/lib/auth-utils.ts` — Helper: `getCurrentUser()` server-side helper using `auth()`, role checking utilities

### Database
- `src/db/schema.ts` — All Drizzle table definitions with proper types, relations (including users table)
- `src/db/index.ts` — Database connection (drizzle + postgres driver)
- `src/db/seed.ts` — Seed script with realistic sample data INCLUDING default admin user (admin@example.com / password123)

### API Routes
- `src/app/api/[resource]/route.ts` — GET (list), POST (create) — MUST include auth check and error handling
- `src/app/api/[resource]/[id]/route.ts` — GET (detail), PUT (update), DELETE — MUST include auth check
- All API routes MUST:
  - Check authentication via `auth()` from next-auth
  - Validate request body with zod schemas
  - Return proper HTTP status codes (400, 401, 403, 404, 500)
  - Return consistent error format: `{ error: { code: string, message: string } }`
  - Handle database errors gracefully

### Frontend
- `src/app/globals.css` — @import "tailwindcss"
- `src/app/layout.tsx` — Root layout with Inter font, SessionProvider wrapper
- `src/app/page.tsx` — Dashboard/home page (protected)
- `src/app/[resource]/page.tsx` — List pages with tables (protected)
- `src/app/[resource]/[id]/page.tsx` — Detail/edit pages (protected)
- `src/app/[resource]/new/page.tsx` — Create pages with forms (protected)
- `src/components/ui/` — button, card, input, table, dialog, badge, toast, skeleton (shadcn style)
- `src/components/layout/` — Navbar with user info + logout button, Sidebar
- `src/components/[feature]/` — Feature-specific components
- `src/lib/utils.ts` — cn() utility

### Error Handling & UX (REQUIRED)
- `src/app/error.tsx` — Global error boundary with retry button
- `src/app/not-found.tsx` — Custom 404 page
- `src/app/loading.tsx` — Global loading state with skeleton
- `src/components/ui/toast.tsx` — Toast notification component (success, error, info)
- All forms MUST include:
  - Client-side validation with inline error messages
  - Loading state on submit button (disabled + spinner)
  - Success toast on completion
  - Error toast on failure with descriptive message
  - Proper form reset after successful submission

## RULES
1. Use TypeScript strict mode throughout
2. All API routes must validate input with zod and return proper HTTP status codes
3. Use Drizzle ORM — NOT Prisma, NOT raw SQL
4. PostgreSQL connection via `postgres` package (node-postgres)
5. Every table needs: id (serial primary key), created_at (timestamp), updated_at (timestamp)
6. Use Server Components by default, Client Components only when needed (interactivity)
7. Tailwind CSS with shadcn/ui patterns: use `cn()` utility, CVA for variants
8. Forms must have proper validation, loading states, and error display
9. Tables must have sorting, filtering where appropriate
10. Generate realistic seed data (10-20 rows per table) plus a default admin user
11. The app must build successfully: `npm run build`
12. Include proper loading states (skeleton loaders) and error boundaries
13. Use Next.js App Router patterns (not Pages Router)
14. ALL routes except /login and /signup must require authentication
15. Use server actions or API routes for all data mutations — never mutate directly in components
16. Navbar must show current user name/email and a working logout button

## WORKFLOW — PHASED GENERATION
You MUST work through these phases IN ORDER. Do not skip ahead.

### Phase 1: Foundation (config + auth + database)
1. Read the plan carefully and create a FULL CHECKLIST of everything to build
2. Write root config: package.json, tsconfig.json, next.config.ts, postcss.config.mjs, docker-compose.yml, .env.local.example
3. Write auth: src/auth.ts, middleware.ts, auth API routes, auth utility helpers
4. Write database: src/db/schema.ts (ALL tables from plan), src/db/index.ts, drizzle.config.ts
5. Write shared types: src/types/ with interfaces for all entities
6. Write utilities: src/lib/utils.ts (cn helper), src/lib/auth-utils.ts
7. Run `npm install` to install all dependencies

### Phase 2: API Routes
8. Write ALL API routes from the plan — every entity needs GET (list), POST (create), GET/:id, PUT/:id, DELETE/:id
9. Each route must have: auth check, zod validation, proper error handling, correct status codes
10. Every route must actually query the database using the schema from Phase 1

### Phase 3: Shared Components
11. Write layout components: Navbar (with user info + logout), Sidebar (with nav links to ALL pages)
12. Write shared UI components: button, card, input, table, dialog, badge, toast, skeleton (shadcn style)
13. Write feature components listed in the plan: forms, tables, cards, badges for each entity
14. Each component must be complete and functional — not a stub

### Phase 4: Layouts
15. Write root layout: src/app/layout.tsx (SessionProvider, fonts, globals.css)
16. Write auth layout: src/app/(auth)/layout.tsx (centered)
17. Write app layout: src/app/(dashboard)/layout.tsx or similar (Navbar + Sidebar + main content)
18. Write globals.css with Tailwind v4 (@import "tailwindcss") + CSS variables for theme

### Phase 5: ALL Pages
19. Write EVERY page listed in the plan — not some, ALL of them
20. Dashboard page: summary cards, recent activity, quick links
21. List pages: data table with columns, search, filters, pagination, create button
22. Detail pages: full record display, edit form, delete action, back link
23. Create pages: form with all fields, validation, submit, success redirect
24. Settings/admin pages if in plan
25. Error handling: error.tsx, not-found.tsx, loading.tsx

### Phase 6: Seed Data + Verification
26. Write src/db/seed.ts with realistic data (admin user + 10-20 rows per table)
27. Run `ls -R src/app/` to verify ALL planned pages exist
28. Run `ls -R src/components/` to verify ALL planned components exist
29. Run `ls -R src/app/api/` to verify ALL planned API routes exist
30. Create any MISSING artifacts immediately
31. Run `npm run build` to verify compilation

## COMPLETENESS — CRITICAL
- You MUST create EVERY artifact listed in the plan: pages, components, layouts, API routes, all of them
- If the plan lists 11 pages, create 11 pages. Not 4, not 8 — exactly 11 (plus auth and error pages)
- If the plan lists 6 components, create 6 components. Each with real working code
- If the plan lists 15 API routes, create 15 API routes. Each with real database queries
- After Phase 5, run verification commands. If ANYTHING is missing, create it before building
- The Sidebar navigation must have links to EVERY page in the app — not just a few

## PAGE QUALITY
- Every list page: data fetching, table/card display, search/filter, pagination, link to detail, create button
- Every detail page: data fetching by ID, display all fields, edit form, delete with confirmation
- Every create page: form with all fields, client-side validation, loading state, success redirect
- Dashboard: aggregate stats from ALL entities, recent items, charts or summary tables

## IMPORTANT
- Do NOT use any Figma tools or references — this is text-to-code, not design-to-code
- Do NOT create placeholder/stub files — every file must have real, working code
- Do NOT use `any` type — use proper TypeScript types
- Do NOT skip authentication — every generated app MUST have login/signup
- Do NOT skip error handling — every form and API call MUST handle errors
- Do NOT skip ANY artifact from the plan — if it's in the plan, it MUST exist in the code
- The app should look professional with proper spacing, colors, and typography
"""


async def run_code_generator(
    output_dir: str,
    description: str,
    plan: dict | None = None,
) -> AsyncIterator[Message]:
    """Run the code generator agent to create a full-stack app from description.

    Yields streaming messages (AssistantMessage/ResultMessage) for SSE forwarding.
    """
    # Unset CLAUDECODE to allow the SDK to spawn a nested CLI process
    os.environ.pop("CLAUDECODE", None)

    plan_section = ""
    artifact_checklist = ""
    if plan:
        import json
        plan_section = f"""

## Implementation Plan
```json
{json.dumps(plan, indent=2)}
```
"""
        # Build a comprehensive artifact checklist from the plan
        checklist_parts = []

        # Data models
        models = plan.get("data_models", [])
        if models:
            model_lines = [f"  - [ ] {m.get('name', '?')} table ({len(m.get('fields', []))} fields)" for m in models]
            checklist_parts.append(f"### Data Models ({len(models)} tables):\n" + "\n".join(model_lines))

        # API routes
        api_routes = plan.get("api_routes", [])
        if api_routes:
            api_lines = [f"  - [ ] {r.get('method', 'GET')} {r.get('path', '?')}: {r.get('description', '')}" for r in api_routes]
            checklist_parts.append(f"### API Routes ({len(api_routes)} endpoints):\n" + "\n".join(api_lines))

        # Components
        components = plan.get("components", [])
        shared_components = plan.get("shared_components", [])
        all_components = components + shared_components
        if all_components:
            comp_lines = [f"  - [ ] {c.get('name', '?')} → {c.get('file', '?')}: {c.get('description', '')}" for c in all_components]
            checklist_parts.append(f"### Components ({len(all_components)} components):\n" + "\n".join(comp_lines))

        # Layouts
        layouts = plan.get("layouts", [])
        if layouts:
            layout_lines = [f"  - [ ] {l.get('file', l.get('route', '?'))}: {l.get('description', '')}" for l in layouts]
            checklist_parts.append(f"### Layouts ({len(layouts)} layouts):\n" + "\n".join(layout_lines))

        # Pages
        pages = plan.get("pages", [])
        if pages:
            page_lines = []
            for i, p in enumerate(pages, 1):
                route = p.get("route", p.get("path", ""))
                name = p.get("name", p.get("component", ""))
                desc = p.get("description", "")
                page_lines.append(f"  - [ ] `{route}` — {name}: {desc}")
            checklist_parts.append(f"### Pages ({len(pages)} pages):\n" + "\n".join(page_lines))

        # Workflows
        workflows = plan.get("workflows", [])
        if workflows:
            wf_lines = [f"  - [ ] {w.get('name', '?')}: {', '.join(w.get('steps', []))}" for w in workflows]
            checklist_parts.append(f"### Workflows ({len(workflows)} workflows):\n" + "\n".join(wf_lines))

        total_artifacts = len(models) + len(api_routes) + len(all_components) + len(layouts) + len(pages)
        artifact_checklist = f"""

## ARTIFACT CHECKLIST — You MUST create ALL {total_artifacts} artifacts:
{chr(10).join(checklist_parts)}

### Also Required (always):
  - [ ] Auth pages: login, signup
  - [ ] Error pages: error.tsx, not-found.tsx, loading.tsx
  - [ ] Root layout with SessionProvider
  - [ ] Navbar with links to all pages + user menu + logout
  - [ ] Sidebar with navigation to every page
  - [ ] Seed data with admin user + realistic sample data

CRITICAL: Every artifact above MUST be created as a real, working file. After all phases, verify completeness with `ls -R src/app/ src/components/ src/app/api/`. Create anything missing BEFORE running the build.
"""

    user_prompt = f"""Build a complete full-stack application based on this description:

## App Description
{description}
{plan_section}{artifact_checklist}

## Phased Execution:
1. PHASE 1 — Foundation: config files, auth, database schema with ALL tables, types, utilities. Run `npm install`.
2. PHASE 2 — API: Create ALL API routes from the plan. Every entity needs full CRUD.
3. PHASE 3 — Components: Create ALL shared components (Navbar, Sidebar) and feature components (tables, forms, cards) from the plan.
4. PHASE 4 — Layouts: Root layout, auth layout, dashboard layout with Navbar + Sidebar.
5. PHASE 5 — Pages: Create EVERY page from the plan. Dashboard, list pages, detail pages, create pages, settings.
6. PHASE 6 — Finalize: Seed data, error pages. Verify ALL artifacts: `ls -R src/app/ src/components/ src/app/api/`. Create anything missing.
7. Run `npm run build` to verify compilation.

IMPORTANT: Work through ALL 6 phases. Do not stop early. Every artifact in the checklist must be created. Start now."""

    # Scale max_turns based on plan complexity
    max_turns = 80
    if plan:
        num_pages = len(plan.get("pages", []))
        num_models = len(plan.get("data_models", []))
        num_components = len(plan.get("components", [])) + len(plan.get("shared_components", []))
        # Larger apps need more turns: base 80 + 5 per page + 3 per component beyond the base
        estimated = 80 + max(0, num_pages - 6) * 5 + max(0, num_components - 4) * 3
        max_turns = min(estimated, 150)  # Cap at 150

    options = ClaudeAgentOptions(
        system_prompt=CODE_GENERATOR_SYSTEM_PROMPT,
        allowed_tools=["Write", "Edit", "Read", "Bash", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=max_turns,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message

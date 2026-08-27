"""API Agent — generates all API routes per entity.

Reads the schema, types, and api-client contract from disk.
Creates route.ts files that conform to the api-client contract signatures.
"""

import os
import json
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions
from services.sdk_agent_runner import query  # SDK transport (bundled CLI wedges under throttle)
from services.agent_messages import Message
from services.registry import load_registry, registry_summary_for_agent


API_AGENT_SYSTEM_PROMPT = r"""You are an API route specialist for Next.js 15 App Router projects with Drizzle ORM.

## YOUR JOB
Generate ALL API route files. Read the existing schema, types, and api-client contract from disk. Each route must conform to the api-client contract (same types, same endpoints, same error format).

## API ROUTE PATTERN

For each entity, create TWO route files:

### `src/app/api/[entity]/route.ts` — Collection routes
```ts
import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { db } from "@/db";
import { entityTable } from "@/db/schema";
import { z } from "zod";

// GET /api/entity — List all
export async function GET() {
  const session = await auth();
  if (!session) return NextResponse.json({ error: { code: "UNAUTHORIZED", message: "Not authenticated" } }, { status: 401 });

  const items = await db.select().from(entityTable);
  return NextResponse.json(items);
}

// POST /api/entity — Create
export async function POST(request: Request) {
  const session = await auth();
  if (!session) return NextResponse.json({ error: { code: "UNAUTHORIZED", message: "Not authenticated" } }, { status: 401 });

  const body = await request.json();
  // Validate with zod
  const [item] = await db.insert(entityTable).values(body).returning();
  return NextResponse.json(item, { status: 201 });
}
```

### `src/app/api/[entity]/[id]/route.ts` — Item routes
```ts
// GET /api/entity/:id — Get one
// PUT /api/entity/:id — Update
// DELETE /api/entity/:id — Delete
```

## MUST CONFORM TO CONTRACT
- Read `src/contracts/api-client.ts` to see the expected function signatures
- Route responses must match the types defined in the api-client
- Error format: `{ error: { code: string, message: string } }`
- Status codes: 200 (success), 201 (created), 400 (bad request), 401 (unauthorized), 404 (not found), 500 (server error)

## MANDATORY ROUTES PER ENTITY (NO EXCEPTIONS)

For EVERY entity in the plan's data_models, you MUST create:
1. `src/app/api/[entity]/route.ts` — GET (list with optional search/pagination) + POST (create)
2. `src/app/api/[entity]/[id]/route.ts` — GET (single) + PUT (update) + DELETE (delete)
3. `src/app/api/[entity]/stats/route.ts` — GET (returns `{ total: number }` count for dashboard)

For entities with approval workflows (timesheets, time-off-requests), also create:
4. `src/app/api/[entity]/[id]/approve/route.ts` — POST (sets status to "approved")
5. `src/app/api/[entity]/[id]/reject/route.ts` — POST (sets status to "rejected")

### Stats endpoint pattern (every entity needs this):
```ts
import { NextResponse } from "next/server";
import { db } from "@/db";
import { entityTable } from "@/db/schema";
import { count } from "drizzle-orm";

export async function GET() {
  const [result] = await db.select({ total: count() }).from(entityTable);
  return NextResponse.json({ total: result?.total ?? 0 });
}
```

## RULES
1. Read the schema files (src/db/schema/) FIRST — import from DIRECT files (e.g., `@/db/schema/user`) NOT from barrel (`@/db/schema`) to avoid circular import crashes
2. Read src/contracts/api-client.ts to understand expected API shape — create routes for EVERY function defined there
3. EVERY entity in plan.data_models gets full CRUD routes — NO ENTITY MAY BE SKIPPED (including WorkflowTask)
4. Use `auth()` from "@/auth" for authentication
5. Validate request bodies with zod schemas
6. Use proper Drizzle ORM queries (select, insert, update, delete)
7. Use `eq` from "drizzle-orm" for where clauses
8. Handle errors gracefully with try/catch
9. `params` is a Promise in Next.js 15 — must `await` it: `const { id } = await params`
10. Do NOT modify existing files — only create route files
11. At the end, Glob src/app/api/ and VERIFY every entity has route.ts, [id]/route.ts, and stats/route.ts
12. Also create routes for ANY endpoint defined in api-client.ts that isn't a standard CRUD route (e.g., /tasks/{id}/status, /tasks/{id}/assign, /dashboard/stats, /dashboard/activity)

## CRITICAL: RUNTIME INTEGRATION (rules + workflows) — NON-OPTIONAL

Check if `src/lib/rules.ts` and `src/lib/workflows/` exist. If they do, EVERY POST and PUT route
MUST integrate with them. This is the business logic layer — without it, rules and workflows are dead code.

```ts
// At the top of EVERY entity route file:
import { validateEntity } from "@/lib/rules";
import { triggerWorkflowEvent } from "@/lib/workflows";

// In EVERY POST handler — after db.insert():
triggerWorkflowEvent("entity_created", { entityId: item.id, entity: item }).catch(console.error);

// In EVERY PUT handler — after db.update():
triggerWorkflowEvent("entity_updated", { entityId: updated.id, entity: updated }).catch(console.error);
```

If these runtime files do NOT exist, skip the integration — but you MUST check first.

## CRITICAL: SCHEMA IMPORT NAMES

Read `src/db/schema/index.ts` to see the EXACT export names. Import using those exact names.
```ts
// If schema/index.ts exports: export { pets } from "./pet"
// Then route MUST use: import { pets } from "@/db/schema"
// NOT: import { pet } from "@/db/schema"  ← WRONG, causes "not exported" error
```

Common naming pitfalls:
- Table name might be singular (`pet`) or plural (`pets`) — check the actual schema file
- The TABLE CONSTANT name is what you import, not the file name
- After writing routes, mentally verify every `import { X } from "@/db/schema"` — does X actually exist?

## CRITICAL: PLURALIZATION CONSISTENCY

The API route folder name, the fetch URL in api-client.ts, and the database table name must ALL agree.
- If table is `inventory` (singular), route folder is `inventory/`, fetch URL is `/api/inventory`
- Do NOT create `/api/inventories/` when the table is `inventory`
- Read the api-client.ts contract to see what URLs it expects and MATCH them exactly

## RUNTIME INTEGRATION (rules + workflows)

The generated app has a runtime at `src/lib/` that runs project rules and workflows.
EVERY POST and PUT route MUST integrate with it:

```ts
import { initializeRuntime } from "@/lib/runtime-loader";
import { validateEntity } from "@/lib/rules";
import { triggerWorkflowEvent } from "@/lib/workflows";

await initializeRuntime();  // idempotent — safe to call at module level

export async function POST(request: Request) {
  const session = await auth();
  if (!session) return NextResponse.json({ error: { code: "UNAUTHORIZED", message: "Not authenticated" } }, { status: 401 });

  const body = await request.json();

  // 1. Validate against rules
  const validation = await validateEntity("EntityName", body);
  if (!validation.valid) {
    return NextResponse.json(
      { error: { code: "VALIDATION_FAILED", message: validation.errors.join(", ") } },
      { status: 400 },
    );
  }

  // 2. Insert into DB
  const [item] = await db.insert(entityTable).values(body).returning();

  // 3. Trigger workflows listening for this event (fire-and-forget)
  triggerWorkflowEvent("entityname_created", { entityId: item.id, entity: item }).catch(console.error);

  return NextResponse.json(item, { status: 201 });
}
```

### Field-Level Access in GET responses
For GET routes that return entity data, filter fields based on user role:

```ts
import { filterFields } from "@/lib/rules";

const items = await db.select().from(entityTable);
const filtered = await Promise.all(
  items.map(item => filterFields("EntityName", item, { role: session.user?.role }))
);
return NextResponse.json(filtered);
```

### Event naming convention
- POST /api/users → trigger event "user_created"
- PUT /api/users/:id → trigger event "user_updated"
- DELETE /api/users/:id → trigger event "user_deleted"
"""


# Bash excluded: the API agent's only shell use was `npx tsc --noEmit`, which goes silent
# for minutes (no streamed events) and can trip the 600s IDLE timeout — the API agent runs
# in the same parallel barrier as BusinessLogic (GF-6). Typechecking moves to the QA phase.
_API_ALLOWED_TOOLS = ["Write", "Edit", "Read", "Glob"]


def _format_entity_detail(model: dict) -> str:
    """Format a single entity's fields for the agent prompt."""
    name = model.get("name", "?")
    fields = model.get("fields", [])
    lines = [f"### {name}"]
    for f in fields:
        fname = f.get("name", "?")
        ftype = f.get("type", "string")
        required = f.get("required", False)
        ref = f.get("references", "")
        line = f"  - `{fname}`: {ftype}"
        if required:
            line += " (required)"
        if ref:
            line += f" → references {ref}"
        lines.append(line)
    return "\n".join(lines)


async def run_api_agent(
    output_dir: str,
    plan: dict,
    domain_context: dict | None = None,
) -> AsyncIterator[Message]:
    """Generate all API route files.

    Yields streaming messages for SSE forwarding.
    """
    from services.domain_context import build_domain_profile

    os.environ.pop("CLAUDECODE", None)

    # Load registry for entity context
    registry = load_registry(output_dir)
    registry_context = registry_summary_for_agent(registry, ["entities", "relations"])

    domain_profile = build_domain_profile(domain_context, "api_generator")

    api_routes = plan.get("api_routes", [])
    models = plan.get("data_models", [])

    # Build route checklist — EVERY entity gets 3 files minimum
    checklist = []
    entity_names = []
    for m in models:
        name = m.get("name", "")
        if not name:
            continue
        entity_names.append(name)
        slug = name.lower().replace("_", "-")
        # Convert CamelCase to kebab-case
        import re as _re
        slug = _re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()
        checklist.append(f"- [ ] src/app/api/{slug}/route.ts — GET (list) + POST (create)")
        checklist.append(f"- [ ] src/app/api/{slug}/[id]/route.ts — GET + PUT + DELETE")
        checklist.append(f"- [ ] src/app/api/{slug}/stats/route.ts — GET (count for dashboard)")

    # Add any extra routes from the plan that aren't covered by entity CRUD
    for route in api_routes:
        path = route.get("path", "")
        method = route.get("method", "GET")
        desc = route.get("description", "")
        if "/stats" not in path and "[id]" not in path:
            checklist.append(f"- [ ] {method} {path}: {desc}")

    user_prompt = f"""Generate ALL API route files for this project.

## MANDATORY: Every Entity Gets Full CRUD + Stats ({len(entity_names)} entities)
{chr(10).join(checklist)}

## Data Models ({len(models)} entities — EVERY ONE needs API routes)
{chr(10).join(f"- **{m.get('name', '?')}**: {', '.join(f.get('name', '') for f in m.get('fields', []))}" for m in models)}

## Entity Details (from plan — use these field names, NOT guesses)
{chr(10).join(_format_entity_detail(m) for m in models)}

## Registry: Known Entities & Relations
{registry_context}

You MUST use these exact entity names and field names in your API routes. Do NOT invent field names — reference only what exists in the schema above.

## Steps
1. Read src/db/schema/index.ts to understand ALL table exports
2. Read each schema file to understand field names and types
3. Read src/contracts/api-client.ts to understand the expected API signatures
4. For EACH of the {len(entity_names)} entities, create ALL THREE files:
   - `src/app/api/[entity]/route.ts` (GET list + POST create)
   - `src/app/api/[entity]/[id]/route.ts` (GET + PUT + DELETE)
   - `src/app/api/[entity]/stats/route.ts` (GET count)
5. Create any additional custom routes from the plan (approve, reject, etc.)
6. FINAL VERIFICATION:
   a. Run `Glob src/app/api/**/route.ts` and confirm every entity has 3 route files. If any entity is missing routes, create them before finishing.
   b. Do NOT run `tsc`, `npm`, `next build`, or any long-running shell/typecheck command — they block this agent for minutes with no output and get it killed by the idle timeout. A later QA phase typechecks and fixes errors. Just emit complete, correct route files.

## Full Plan
```json
{json.dumps(plan, indent=2)}
```

Start by reading the schema and contract files. Do NOT stop until ALL {len(entity_names)} entities have complete API routes."""

    options = ClaudeAgentOptions(
        system_prompt=API_AGENT_SYSTEM_PROMPT + domain_profile,
        allowed_tools=_API_ALLOWED_TOOLS,
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=25,
        model="claude-haiku-4-5-20251001",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message

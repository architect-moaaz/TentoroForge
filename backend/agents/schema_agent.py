"""Schema Agent — generates config, database schema (split per entity), types, and utilities.

Reads the plan and produces the foundation layer that all subsequent agents depend on:
- Root config files (package.json, tsconfig.json, next.config.ts, etc.)
- Per-entity schema files in src/db/schema/
- Per-entity type files in src/types/
- Database connection setup
- Utility helpers
- Runs npm install
"""

import os
import json
from pathlib import Path
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions
from services.sdk_agent_runner import query  # SDK transport (bundled CLI wedges under throttle)
from services.agent_messages import Message


SCHEMA_AGENT_SYSTEM_PROMPT = r"""You are a database and config specialist for Next.js 15 + Drizzle ORM + PostgreSQL projects.

## YOUR JOB
Generate all config files, database schema, types, and utilities. This is the FOUNDATION that every other agent builds on.

## FILES TO GENERATE

### Root Config
- `package.json` — dependencies: next, react, react-dom, tailwindcss, autoprefixer, postcss, drizzle-orm, drizzle-kit, postgres, next-auth, bcryptjs, zod, lucide-react, tailwind-merge, clsx, @tanstack/react-query, sonner, class-variance-authority. devDependencies: typescript, @types/node, @types/react, @types/bcryptjs, tsx
  - IMPORTANT: use tailwindcss version "^3.4.0" (NOT v4). Do NOT include @tailwindcss/postcss.
- `tsconfig.json` — standard Next.js config with `@/*` path alias pointing to `./src/*`
- `next.config.ts` — standard Next.js config
- `postcss.config.mjs` — MUST use tailwindcss + autoprefixer (NOT @tailwindcss/postcss):
  ```js
  const config = { plugins: { tailwindcss: {}, autoprefixer: {} } };
  export default config;
  ```
- `tailwind.config.ts` — MUST create this file:
  ```ts
  import type { Config } from "tailwindcss";
  const config: Config = {
    content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
    theme: { extend: {} },
    plugins: [],
  };
  export default config;
  ```
- `docker-compose.yml` — PostgreSQL 16 service (port ${DB_PORT:-5432}, user: postgres, password: postgres, db: PROJECT_ID — use the project short ID passed below, NOT "app")
- `.env.local.example` — DATABASE_URL, NEXTAUTH_SECRET, NEXTAUTH_URL
- `drizzle.config.ts` — Drizzle Kit config pointing to src/db/schema/

### Database Schema (SPLIT PER ENTITY)
For EACH data model in the plan, create a separate file:
- `src/db/schema/[entity].ts` — Drizzle table definition + relations for that entity
- `src/db/schema/index.ts` — barrel export of ALL entity schemas

IMPORTANT: Split schema into separate files per entity. This keeps each file small and focused.

Each schema file must:
- Import from "drizzle-orm/pg-core" (pgTable, serial, varchar, text, integer, boolean, timestamp, etc.)
- Import from "drizzle-orm" (relations) if the entity has relations
- Export the table constant (e.g., `export const orders = pgTable(...)`)
- Export relations if any
- Include id (serial primaryKey), createdAt (timestamp defaultNow), updatedAt (timestamp defaultNow)
- Use snake_case for column names in the database, camelCase for TypeScript

### Database Connection
- `src/db/index.ts` — MUST use this exact pattern (postgres-js driver, NOT pg/node-postgres):
  ```ts
  import { drizzle } from "drizzle-orm/postgres-js";
  import postgres from "postgres";
  import * as schema from "./schema";

  const connectionString = process.env.DATABASE_URL!;
  const client = postgres(connectionString, { prepare: false });
  export const db = drizzle(client, { schema });
  ```
  NEVER use `import { Pool } from "pg"` or `drizzle-orm/node-postgres`.

### Types (ONE PER ENTITY)
For EACH data model:
- `src/types/[entity].ts` — TypeScript interfaces derived from Drizzle's $inferSelect/$inferInsert
- `src/types/index.ts` — barrel export

### Utilities
- `src/lib/utils.ts` — cn() helper using clsx + tailwind-merge

### After Writing All Files
- Run `npm install` to install dependencies

## DRIZZLE ORM PATTERNS

```ts
// src/db/schema/users.ts
import { pgTable, serial, varchar, text, timestamp, boolean } from "drizzle-orm/pg-core";
import { relations } from "drizzle-orm";

export const users = pgTable("users", {
  id: serial("id").primaryKey(),
  email: varchar("email", { length: 255 }).notNull().unique(),
  name: varchar("name", { length: 255 }).notNull(),
  passwordHash: varchar("password_hash", { length: 255 }).notNull(),
  role: varchar("role", { length: 50 }).notNull().default("user"),
  createdAt: timestamp("created_at").defaultNow(),
  updatedAt: timestamp("updated_at").defaultNow(),
});

export const usersRelations = relations(users, ({ many }) => ({
  orders: many(orders),
}));
```

```ts
// src/types/users.ts
import { users } from "@/db/schema/users";

export type User = typeof users.$inferSelect;
export type NewUser = typeof users.$inferInsert;
```

```ts
// src/db/schema/index.ts
export { users, usersRelations } from "./users";
export { orders, ordersRelations } from "./orders";
```

## RULES
1. EVERY data model in the plan gets its own schema file and type file
2. Foreign key columns must reference the correct table
3. Use `relations()` from drizzle-orm to define relationships
4. The users table MUST include: id, email (unique), password (NOT passwordHash), name or firstName+lastName, role (default 'user'), isActive (default true), createdAt, updatedAt.
   The field MUST be called `password` (not `passwordHash`) because the auth template reads `user.password`.
5. ALWAYS use `postgres` (postgres-js) as the database driver. NEVER use `pg` or `node-postgres`. The import is `import postgres from "postgres"` + `drizzle-orm/postgres-js`.
6. Run `npm install` after writing all files
7. Read the contracts (src/contracts/) if they exist for additional context
8. Every field from plan.data_models must appear in the schema

## CRITICAL: AUTH INTEGRATION (auth template reads from your schema)

The auth system is pre-built as a template. It reads from `src/db/schema/user.ts` with:
```ts
import { users } from "@/db/schema/user";
// ...
const [user] = await db.select().from(users).where(eq(users.email, credentials.email));
await bcrypt.compare(credentials.password, user.password);
```

Your users table MUST have:
- `password: varchar("password", { length: 255 }).notNull()` — EXACTLY this name
- `email: varchar("email", { length: 255 }).notNull().unique()` — for login lookup
- `isActive: boolean("is_active").default(true)` — auth checks this

After writing the user schema, read `src/auth.ts` and verify it can query your users table.
If the auth template uses field names that don't match your schema, edit `src/auth.ts` to match.

## CRITICAL: RELATIONS IN SEPARATE FILE (prevents circular imports that crash ALL API routes)

DO NOT put `relations()` in individual schema files. Instead:

1. Each entity file (e.g., `user.ts`) contains ONLY the `pgTable(...)` definition
2. Entity files may import other entity files ONLY for `.references()` FK definitions (one-way)
3. Create `src/db/schema/relations.ts` — this single file imports ALL tables and exports ALL relations:
   ```ts
   import { relations } from "drizzle-orm";
   import { users } from "./user";
   import { projects } from "./project";
   import { tasks } from "./task";
   // ... all tables

   export const usersRelations = relations(users, ({ many }) => ({
     projects: many(projects),
     tasks: many(tasks),
   }));
   // ... all relations
   ```
4. `src/db/schema/index.ts` must re-export from `"./relations"` in addition to all table files

**WHY:** If user.ts imports project.ts for relations AND project.ts imports user.ts, you get
circular dependencies. The barrel `@/db/schema` then exports `undefined` for some tables,
causing EVERY API route to crash with 500. This has happened in every generation so far.

## CRITICAL: BARREL EXPORT COMPLETENESS

`src/db/schema/index.ts` MUST re-export EVERY schema file. One `export * from "./<basename>"` per .ts file.
Missing exports cause `undefined` errors when other agents import from `@/db/schema`.
After writing all schema files, Glob `src/db/schema/*.ts` and verify every file is in the barrel.

## CRITICAL: NEXT.JS CONFIG

`next.config.ts` MUST include:
```ts
const nextConfig: NextConfig = {
  typescript: { ignoreBuildErrors: true },
  images: { domains: ["localhost"] },
};
```
Do NOT enable `experimental.typedRoutes` — it causes type errors when pages reference routes
that don't exist yet (other agents create pages later).

## CRITICAL: NEXTAUTH TYPE AUGMENTATION

Create `src/types/next-auth.d.ts`:
```ts
import "next-auth";
declare module "next-auth" {
  interface User { role?: string; }
  interface Session { user: User & { id: string; role?: string; }; }
}
declare module "next-auth/jwt" {
  interface JWT { role?: string; }
}
```
This prevents type errors when API routes access `session.user.role`.

## CRITICAL: PACKAGE.JSON DEPENDENCIES

Include ALL required Radix UI packages that shadcn/ui components need:
```json
"@radix-ui/react-dialog": "^1.0.5",
"@radix-ui/react-dropdown-menu": "^2.0.6",
"@radix-ui/react-label": "^2.0.2",
"@radix-ui/react-select": "^2.0.0",
"@radix-ui/react-slot": "^1.0.2",
"@radix-ui/react-switch": "^1.0.3",
"@radix-ui/react-tabs": "^1.0.4",
"@radix-ui/react-toast": "^1.1.5",
"@radix-ui/react-icons": "^1.3.0"
```
Missing Radix packages cause "Module not found" errors when component agent creates UI components.

## CRITICAL: ENVIRONMENT FILES

You MUST create BOTH `.env.local` AND `.env.local.example`:

### `.env.local` (actual file used at runtime — MUST exist for the app to work):
```
DATABASE_URL=postgresql://postgres:postgres@localhost:${DB_PORT:-5432}/${PROJECT_ID}
NEXTAUTH_SECRET=dev-secret-change-me-in-production
NEXTAUTH_URL=http://localhost:3000
```

### `.env.local.example` (template for reference):
```
DATABASE_URL=postgresql://postgres:postgres@localhost:${DB_PORT:-5432}/${PROJECT_ID}
NEXTAUTH_SECRET=your-secret-here
NEXTAUTH_URL=http://localhost:3000
```

Without `.env.local`, the app will crash immediately because `DATABASE_URL` and `NEXTAUTH_SECRET` will be undefined.

## CRITICAL: DOCKER-COMPOSE.YML PORT

Use port 5432 for PostgreSQL. The preview manager will override this with a dynamic port via the `DB_PORT` environment variable:

```yaml
ports:
  - "${DB_PORT:-5432}:5432"
```

This allows multiple projects to run simultaneously with different ports.
"""


async def run_schema_agent(
    output_dir: str,
    plan: dict,
    domain_context: dict | None = None,
    project_short_id: str | None = None,
) -> AsyncIterator[Message]:
    """Generate config, schema, types, and utilities.

    Yields streaming messages for SSE forwarding.
    """
    from services.domain_context import build_domain_profile

    os.environ.pop("CLAUDECODE", None)

    domain_profile = build_domain_profile(domain_context, "schema_designer")

    # Use project short_id as database name — each project gets its own DB
    db_name = project_short_id or Path(output_dir).name or "app"

    plan_json = json.dumps(plan, indent=2)
    models = plan.get("data_models", [])
    relations = plan.get("relations", [])

    # Build a checklist of files to generate
    checklist = []
    checklist.append("- [ ] package.json")
    checklist.append("- [ ] tsconfig.json")
    checklist.append("- [ ] next.config.ts")
    checklist.append("- [ ] postcss.config.mjs")
    checklist.append("- [ ] docker-compose.yml")
    checklist.append("- [ ] .env.local.example")
    checklist.append("- [ ] drizzle.config.ts")
    checklist.append("- [ ] src/db/index.ts")
    checklist.append("- [ ] src/lib/utils.ts")
    for m in models:
        name = m.get("name", "unknown")
        checklist.append(f"- [ ] src/db/schema/{name.lower()}.ts")
        checklist.append(f"- [ ] src/types/{name.lower()}.ts")
    checklist.append("- [ ] src/db/schema/index.ts")
    checklist.append("- [ ] src/types/index.ts")
    checklist.append("- [ ] npm install")

    user_prompt = f"""Generate all foundation files for this project.

## Project Database
- Database name: `{db_name}` (NOT "app" — each project gets its own database)
- Use `{db_name}` in docker-compose.yml POSTGRES_DB, in .env.local DATABASE_URL, and in .env.local.example
- DATABASE_URL pattern: `postgresql://postgres:postgres@localhost:${{DB_PORT:-5432}}/{db_name}`
- docker-compose.yml POSTGRES_DB: `{db_name}`

## Plan
```json
{plan_json}
```

## Data Models ({len(models)} entities)
{chr(10).join(f"- {m.get('name', '?')}: {', '.join(f.get('name', '') for f in m.get('fields', []))}" for m in models)}

## Relations
{chr(10).join(f"- {r}" for r in relations) if relations else "No explicit relations defined — infer from foreign key fields."}

## Checklist
{chr(10).join(checklist)}

## Steps
1. Write all root config files (package.json, tsconfig, etc.)
2. Create src/db/schema/ directory
3. Write one schema file per entity with proper Drizzle types and relations
4. Write src/db/schema/index.ts barrel export
5. Write src/db/index.ts database connection
6. Create src/types/ directory
7. Write one type file per entity
8. Write src/types/index.ts barrel export
9. Write src/lib/utils.ts
10. Run `npm install`

Start now. Write every file from the checklist."""

    options = ClaudeAgentOptions(
        system_prompt=SCHEMA_AGENT_SYSTEM_PROMPT + domain_profile,
        allowed_tools=["Write", "Edit", "Read", "Bash", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=20,
        model="claude-haiku-4-5-20251001",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message

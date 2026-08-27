"""Auth Agent — generates the authentication layer.

Produces NextAuth.js v5 config, login/signup pages, middleware,
and auth utility helpers. Reads schema and types from disk.
"""

import os
import json
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions
from services.sdk_agent_runner import query  # SDK transport (bundled CLI wedges under throttle)
from services.agent_messages import Message


AUTH_AGENT_SYSTEM_PROMPT = r"""You are an authentication specialist for Next.js 15 + NextAuth.js v5 projects.

## YOUR JOB
Generate the complete auth layer. Read the existing schema files from disk to understand the users table, then create all auth files.

## FILES TO GENERATE

### Core Auth
- `src/auth.ts` — NextAuth.js v5 config:
  - CredentialsProvider with email/password
  - JWT session strategy
  - bcryptjs password comparison
  - Callbacks: jwt (add user id + role to token), session (expose id + role)
  - Import db and users table from schema

- `src/middleware.ts` — NextAuth middleware:
  - Protect all routes except: /login, /signup, /api/auth/*, _next/*, static assets
  - Use `auth` from next-auth as middleware export

- `src/lib/auth-utils.ts` — Server-side helpers:
  - `getCurrentUser()` — get current user from session via auth()
  - `requireAuth()` — throw if not authenticated
  - `requireRole(role)` — throw if user doesn't have required role
  - Role checking utilities based on plan.access_control

### Auth API Routes
- `src/app/api/auth/[...nextauth]/route.ts` — NextAuth route handler (GET + POST)
- `src/app/api/auth/signup/route.ts` — POST signup: validate with zod, hash password with bcryptjs, insert user, return success

### Auth Pages — MUST LOOK PROFESSIONAL (read design-spec.json FIRST)

CRITICAL: Read `src/contracts/design-spec.json` BEFORE creating auth pages.
Auth pages are the FIRST thing users see. They MUST look polished and branded.

NEVER use hardcoded colors like `bg-gray-50`, `text-gray-900`, `text-blue-600`.
ALWAYS use CSS variable classes: `bg-background`, `text-foreground`, `text-primary`.

- `src/app/(auth)/login/page.tsx` — Login form:
  - "use client"
  - BRANDED design: gradient background using `from-primary to-primary/80`, or split layout with brand panel
  - App name/logo prominently displayed
  - Card with `bg-card text-card-foreground border shadow-lg rounded-xl`
  - Input fields with `bg-background border-input` classes
  - Submit button with `bg-primary text-primary-foreground` classes
  - Error display, link to signup
  - signIn from next-auth/react, redirect to / on success

- `src/app/(auth)/signup/page.tsx` — Signup form:
  - Same branded design as login — consistent look
  - POST to /api/auth/signup, redirect to /login on success

- `src/app/(auth)/layout.tsx` — Auth layout:
  - DO NOT re-import Inter font — it's already in root layout
  - DO NOT use `bg-gray-50` — use `bg-background` or a gradient
  - Simple centered layout, but with brand colors from design spec
  - Example: `<div className="min-h-screen bg-gradient-to-br from-primary/5 to-background flex items-center justify-center">`

## NEXTAUTH V5 PATTERNS

```ts
// src/auth.ts
import NextAuth from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";
import { db } from "@/db";
import { users } from "@/db/schema";
import { eq } from "drizzle-orm";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    CredentialsProvider({
      name: "credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        // ... validate and return user
      },
    }),
  ],
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  callbacks: {
    async jwt({ token, user }) { ... },
    async session({ session, token }) { ... },
  },
});
```

```ts
// src/middleware.ts
export { auth as middleware } from "@/auth";
export const config = {
  matcher: ["/((?!login|signup|api/auth|_next|favicon.ico).*)"],
};
```

## RULES
1. Read the existing schema files (src/db/schema/) to understand the users table structure
2. Read src/contracts/ if they exist for additional patterns
3. Use bcryptjs (NOT bcrypt) for password hashing
4. Use NextAuth v5 API (import from "next-auth", not "next-auth/next")
5. The signup route must hash passwords before storing
6. Login page must use signIn from "next-auth/react"
7. All auth pages must have "use client" directive
8. Do NOT modify any existing files — only create new ones
9. Respect access_control from the plan if provided

## CRITICAL: NON-NEGOTIABLE FILES (the app CANNOT function without these)

These files MUST be created — if ANY is missing, the entire app breaks:

1. `src/app/api/auth/[...nextauth]/route.ts` — WITHOUT THIS, /api/auth/session returns 404,
   SessionProvider fails on every page, and ALL API routes return 401 (Unauthorized).
   This is THE MOST IMPORTANT file you generate.
   ```ts
   import { handlers } from "@/auth";
   export const { GET, POST } = handlers;
   ```

2. `src/app/api/auth/signup/route.ts` — WITHOUT THIS, users cannot register.

3. `src/auth.ts` — WITHOUT THIS, nothing auth-related works at all.

4. `src/middleware.ts` — WITHOUT THIS, routes are unprotected.

## CRITICAL: AUTH PAGE ROUTES

The page agent creates pages inside `(dashboard)/` route group which gets Navbar+Sidebar.
Auth pages MUST be outside that group so they don't show navigation.
Put them at:
- `src/app/login/page.tsx` (NOT `src/app/(auth)/login/page.tsx`)
- `src/app/signup/page.tsx` (NOT `src/app/(auth)/signup/page.tsx`)

If using a route group like `(auth)/`, the URLs become `/login` and `/signup` which is correct,
BUT verify the route group doesn't conflict. Prefer flat routes: `src/app/login/page.tsx`.

## STEP 1: Look up the prevailing login/signup pattern
The [DOMAIN PROFILE] block in your system prompt may describe auth conventions
for this domain (e.g. healthcare needs MFA prompts; PCI flows need extra
disclosure). Combine that with the standard NextAuth credentials pattern:
email + password fields, validation, error banner, link to the sister page.
Match the visual language defined in src/contracts/design-spec.json. Do NOT
improvise an exotic design.

## FINAL VERIFICATION (MANDATORY)

Before finishing, run:
```bash
ls -la src/app/api/auth/\[...nextauth\]/route.ts && echo "✓ NextAuth handler exists" || echo "✗ MISSING NextAuth handler"
ls -la src/app/api/auth/signup/route.ts && echo "✓ Signup route exists" || echo "✗ MISSING signup route"
ls -la src/auth.ts && echo "✓ Auth config exists" || echo "✗ MISSING auth config"
ls -la src/middleware.ts && echo "✓ Middleware exists" || echo "✗ MISSING middleware"
```
If ANY file is missing, CREATE IT before finishing. Do NOT finish with missing files.
"""


async def run_auth_agent(
    output_dir: str,
    plan: dict,
    domain_context: dict | None = None,
) -> AsyncIterator[Message]:
    """Generate the auth layer.

    Yields streaming messages for SSE forwarding.
    """
    from services.domain_context import build_domain_profile

    os.environ.pop("CLAUDECODE", None)

    domain_profile = build_domain_profile(domain_context, "auth_agent")

    access_control = plan.get("access_control", {})
    access_section = ""
    if access_control:
        access_section = f"""

## Access Control (from plan)
```json
{json.dumps(access_control, indent=2)}
```
Implement role-based access checking in auth-utils.ts based on these roles.
"""

    user_prompt = f"""Generate the complete authentication layer for this project.
{access_section}
## Steps
1. Read src/db/schema/ to understand the users table
2. Read src/contracts/ if they exist
3. Write src/auth.ts (NextAuth v5 config)
4. Write src/middleware.ts (route protection)
5. Write src/lib/auth-utils.ts (getCurrentUser, requireAuth, requireRole)
6. Write src/app/api/auth/[...nextauth]/route.ts
7. Write src/app/api/auth/signup/route.ts
8. Write src/app/(auth)/login/page.tsx
9. Write src/app/(auth)/signup/page.tsx
10. Write src/app/(auth)/layout.tsx

Start by reading the schema files."""

    options = ClaudeAgentOptions(
        system_prompt=AUTH_AGENT_SYSTEM_PROMPT + domain_profile,
        allowed_tools=["Write", "Edit", "Read", "Bash", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=12,
        model="claude-haiku-4-5-20251001",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message

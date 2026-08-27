# Closed-Loop Fidelity Render Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render every generated schema page via Playwright + a minimal scaffold runtime, capture screenshots with stub data, and score them on a fixed 5-axis rubric using Claude vision — enabling designers to see what their generated UIs look like and giving the platform telemetry on output quality.

**Architecture:** Three new Python services and one minimal Next.js scaffold, all in the existing monorepo. The render-scaffold (`apps/render-scaffold/`) is a no-auth no-DB Next.js app that loads any project's schemas via URL param. The render-service (`backend/services/render_service/`) is a FastAPI process holding a warm Playwright browser pool that drives the scaffold. The vision evaluator (`backend/services/vision_evaluator/`) calls Claude vision with a fixed rubric + 3 calibration anchors and returns structured critique JSON. The fixtures library (`backend/services/fixtures/`) provides Layer 1 (curated domain banks) → Layer 2 (Faker per-entity) → Layer 3 (type-correct fallback) data so pages render with realistic content. The editor gains a Preview tab that fetches screenshots and a CritiquePanel that surfaces scores.

**Tech Stack:** Python 3.11 / FastAPI / Playwright / Anthropic SDK / Faker (Python). Next.js 15 / React 19 / Tailwind 3 / shadcn defaults / @tentoroforge/renderer + library packages already in the monorepo. pytest + pytest-asyncio for backend, vitest for frontend.

**This plan covers Phase 12.5 (render-only) + Phase 13 (single-shot scoring) from the spec. Phase 14 (closed loop with patch agent) and Phase 15 (reference grounding) ship as separate plans.**

---

## File structure

### New files

**Render scaffold (minimal Next.js app):**
- `apps/render-scaffold/package.json` — pinned deps; depends on `@tentoroforge/renderer`, `@tentoroforge/library`, `@tentoroforge/schema`
- `apps/render-scaffold/next.config.ts` — `transpilePackages` for the workspace packages, no telemetry, no minification in dev
- `apps/render-scaffold/tsconfig.json` — extends shared tsconfig
- `apps/render-scaffold/tailwind.config.ts` — shadcn HSL-var color mapping
- `apps/render-scaffold/postcss.config.mjs` — tailwindcss + autoprefixer
- `apps/render-scaffold/src/app/globals.css` — Tailwind directives + shadcn HSL `:root` defaults
- `apps/render-scaffold/src/app/layout.tsx` — root layout, mounts globals.css + project tokens
- `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx` — dynamic schema route
- `apps/render-scaffold/src/lib/loadSchema.ts` — read schema JSON from `output/<id>/src/schemas/...`
- `apps/render-scaffold/src/lib/loadTokens.ts` — read tokens.custom.json + merge defaults
- `apps/render-scaffold/src/lib/fixtures.ts` — fetch fixtures from render-service `/fixtures` endpoint
- `apps/render-scaffold/src/lib/a11yTree.ts` — extract text-only outline of the rendered DOM, embed as JSON `<script>`

**Render service (FastAPI process):**
- `backend/services/render_service/__init__.py`
- `backend/services/render_service/server.py` — FastAPI app + endpoints
- `backend/services/render_service/browser_pool.py` — Playwright browser + context pool
- `backend/services/render_service/cache.py` — file-system cache by SHA-256
- `backend/services/render_service/scaffold_launcher.py` — manage scaffold subprocess
- `backend/services/render_service/main.py` — `python -m backend.services.render_service` entry point

**Fixtures library:**
- `backend/services/fixtures/__init__.py`
- `backend/services/fixtures/loader.py` — Layer 1 (domain bank reader)
- `backend/services/fixtures/faker_gen.py` — Layer 2 (Faker-based per-entity)
- `backend/services/fixtures/fallback.py` — Layer 3 (type-correct fallback)
- `backend/services/fixtures/types.py` — FixtureBundle, FieldHint types
- `backend/fixtures/general/User.json` — 10 records
- `backend/fixtures/general/Item.json` — 10 records
- `backend/fixtures/healthcare/Patient.json` — 10 records
- `backend/fixtures/fintech/Account.json` — 10 records
- `backend/fixtures/hr/Employee.json` — 10 records

**Vision evaluator:**
- `backend/services/vision_evaluator/__init__.py`
- `backend/services/vision_evaluator/types.py` — Pydantic Critique, Issue, Scores models
- `backend/services/vision_evaluator/prompt.py` — system prompt template + rubric copy
- `backend/services/vision_evaluator/anchors/anchor_3.png` — calibration screenshot (placeholder PNG)
- `backend/services/vision_evaluator/anchors/anchor_3.json` — its critique
- `backend/services/vision_evaluator/anchors/anchor_6.png`
- `backend/services/vision_evaluator/anchors/anchor_6.json`
- `backend/services/vision_evaluator/anchors/anchor_8.png`
- `backend/services/vision_evaluator/anchors/anchor_8.json`
- `backend/services/vision_evaluator/evaluator.py` — public `evaluate_page()` API
- `backend/services/vision_evaluator/validator.py` — output JSON validation + retry-once

**Editor frontend:**
- `frontend/src/components/schema-editor/PreviewTab.tsx`
- `frontend/src/components/schema-editor/CritiquePanel.tsx`
- `frontend/src/components/schema-editor/FidelityScoreBadge.tsx`

**Tests:**
- `backend/tests/services/test_fixtures_loader.py`
- `backend/tests/services/test_fixtures_faker.py`
- `backend/tests/services/test_render_cache.py`
- `backend/tests/services/test_render_service.py`
- `backend/tests/services/test_vision_evaluator.py`
- `backend/tests/integration/test_render_e2e.py`

### Modified files

- `backend/config.py` — add `FIDELITY_RENDER_ENABLED`, `FIDELITY_SCORING_ENABLED`, `RENDER_SERVICE_URL`, `SCAFFOLD_PORT`
- `backend/routers/_debug_schema.py` — add `POST /api/_debug/render-page/{short_id}` for manual testing
- `backend/main.py` — no changes required (render-service is its own process)
- `frontend/src/components/schema-editor/SchemaEditorPanel.tsx` — add Preview tab to the tab strip
- `frontend/src/components/schema-editor/EditorMount.tsx` — pass `apiBaseUrl` for render-service requests

---

## Task 1: Scaffold project skeleton

**Files:**
- Create: `apps/render-scaffold/package.json`
- Create: `apps/render-scaffold/next.config.ts`
- Create: `apps/render-scaffold/tsconfig.json`
- Create: `apps/render-scaffold/tailwind.config.ts`
- Create: `apps/render-scaffold/postcss.config.mjs`
- Create: `apps/render-scaffold/src/app/globals.css`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "@tentoroforge/render-scaffold",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev -p 6503",
    "build": "next build",
    "start": "next start -p 6503"
  },
  "dependencies": {
    "@tentoroforge/library": "*",
    "@tentoroforge/renderer": "*",
    "@tentoroforge/schema": "*",
    "next": "^15.5.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.7.0"
  }
}
```

- [ ] **Step 2: Create next.config.ts**

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  typescript: { ignoreBuildErrors: true },
  transpilePackages: [
    "@tentoroforge/renderer",
    "@tentoroforge/library",
    "@tentoroforge/schema",
  ],
};

export default nextConfig;
```

- [ ] **Step 3: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "paths": { "@/*": ["./src/*"] },
    "plugins": [{ "name": "next" }]
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 4: Create tailwind.config.ts (shadcn HSL mapping)**

```ts
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
};

export default config;
```

- [ ] **Step 5: Create postcss.config.mjs**

```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

- [ ] **Step 6: Create globals.css**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 222.2 84% 4.9%;
    --card: 0 0% 100%;
    --card-foreground: 222.2 84% 4.9%;
    --popover: 0 0% 100%;
    --popover-foreground: 222.2 84% 4.9%;
    --primary: 221.2 83.2% 53.3%;
    --primary-foreground: 210 40% 98%;
    --secondary: 210 40% 96.1%;
    --secondary-foreground: 222.2 47.4% 11.2%;
    --muted: 210 40% 96.1%;
    --muted-foreground: 215.4 16.3% 46.9%;
    --accent: 210 40% 96.1%;
    --accent-foreground: 222.2 47.4% 11.2%;
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 210 40% 98%;
    --border: 214.3 31.8% 91.4%;
    --input: 214.3 31.8% 91.4%;
    --ring: 221.2 83.2% 53.3%;
    --radius: 0.5rem;
  }
  * { @apply border-border; }
  body { @apply bg-background text-foreground; }
}
```

- [ ] **Step 7: Install scaffold deps and verify boot**

```bash
cd apps/render-scaffold
npm install --legacy-peer-deps
npm run dev > /tmp/scaffold-boot.log 2>&1 &
sleep 5
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:6503/
```

Expected: `404` (no routes yet, but server is up and responding — not connection refused).

Stop the server after verification: `lsof -ti:6503 | xargs kill -9`.

- [ ] **Step 8: Commit**

```bash
git add apps/render-scaffold/package.json apps/render-scaffold/next.config.ts apps/render-scaffold/tsconfig.json apps/render-scaffold/tailwind.config.ts apps/render-scaffold/postcss.config.mjs apps/render-scaffold/src/app/globals.css
git commit -m "feat(render-scaffold): bootstrap minimal Next.js app on port 6503"
```

---

## Task 2: Scaffold root layout + landing route

**Files:**
- Create: `apps/render-scaffold/src/app/layout.tsx`
- Create: `apps/render-scaffold/src/app/page.tsx`

- [ ] **Step 1: Create layout.tsx**

```tsx
import type { Metadata } from "next";
import "./globals.css";
import type React from "react";

export const metadata: Metadata = {
  title: "Tentoroforge Render Scaffold",
  description: "Headless schema render target",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
```

- [ ] **Step 2: Create landing page.tsx**

```tsx
export default function Home() {
  return (
    <main className="p-8">
      <h1 className="text-2xl font-semibold">Render Scaffold</h1>
      <p className="text-sm text-muted-foreground mt-2">
        This is the headless render target. Hit /p/&lt;projectId&gt;/&lt;page-route&gt; to render a project page.
      </p>
    </main>
  );
}
```

- [ ] **Step 3: Boot and verify the landing page**

```bash
cd apps/render-scaffold
npm run dev > /tmp/scaffold-boot.log 2>&1 &
sleep 5
curl -s http://localhost:6503/ | grep -q "Render Scaffold" && echo OK || echo FAIL
lsof -ti:6503 | xargs kill -9
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add apps/render-scaffold/src/app/layout.tsx apps/render-scaffold/src/app/page.tsx
git commit -m "feat(render-scaffold): root layout + landing page"
```

---

## Task 3: Schema and tokens loaders

**Files:**
- Create: `apps/render-scaffold/src/lib/loadSchema.ts`
- Create: `apps/render-scaffold/src/lib/loadTokens.ts`
- Create: `apps/render-scaffold/tests/loadSchema.test.ts` (using Node's built-in test runner)

- [ ] **Step 1: Write the failing test for loadSchema**

```ts
// apps/render-scaffold/tests/loadSchema.test.ts
import { describe, it } from "node:test";
import assert from "node:assert";
import { loadSchema } from "../src/lib/loadSchema";
import { mkdtempSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

describe("loadSchema", () => {
  it("reads a schema from disk by projectRoot + page route", async () => {
    const root = mkdtempSync(join(tmpdir(), "scaffold-test-"));
    mkdirSync(join(root, "src/schemas/users"), { recursive: true });
    writeFileSync(join(root, "src/schemas/users/list.json"), JSON.stringify({
      schemaVersion: "1", id: "users/list", route: "/users",
      layout: "DashboardLayout", meta: { title: "Users" },
      dataSources: [], root: { id: "r", type: "Stack", props: {}, children: [] },
    }));
    const schema = await loadSchema(root, "users/list");
    assert.equal(schema?.id, "users/list");
  });

  it("returns null when schema is missing", async () => {
    const root = mkdtempSync(join(tmpdir(), "scaffold-test-"));
    const schema = await loadSchema(root, "does/not-exist");
    assert.equal(schema, null);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/render-scaffold
npx tsx --test tests/loadSchema.test.ts
```

Expected: FAIL with "Cannot find module '../src/lib/loadSchema'".

- [ ] **Step 3: Implement loadSchema.ts**

```ts
// apps/render-scaffold/src/lib/loadSchema.ts
import { promises as fs } from "node:fs";
import path from "node:path";

export async function loadSchema(projectRoot: string, pagePath: string): Promise<unknown | null> {
  const full = path.join(projectRoot, "src", "schemas", `${pagePath}.json`);
  try {
    const raw = await fs.readFile(full, "utf8");
    return JSON.parse(raw);
  } catch (err: any) {
    if (err?.code === "ENOENT") return null;
    throw err;
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/render-scaffold
npx tsx --test tests/loadSchema.test.ts
```

Expected: PASS — both tests green.

- [ ] **Step 5: Implement loadTokens.ts (no test — pure JSON merge wrapper)**

```ts
// apps/render-scaffold/src/lib/loadTokens.ts
import { promises as fs } from "node:fs";
import path from "node:path";
import { defaultTokens } from "@tentoroforge/library";

function deepMerge(base: any, overlay: any): any {
  if (overlay === null || overlay === undefined) return base;
  if (typeof overlay !== "object" || Array.isArray(overlay)) return overlay;
  const out: any = { ...(base || {}) };
  for (const [k, v] of Object.entries(overlay)) out[k] = deepMerge(out[k], v);
  return out;
}

export async function loadTokens(projectRoot: string): Promise<Record<string, unknown>> {
  const customPath = path.join(projectRoot, "src", "theme", "tokens.custom.json");
  try {
    const raw = await fs.readFile(customPath, "utf8");
    const custom = JSON.parse(raw);
    return deepMerge(defaultTokens, custom);
  } catch {
    return defaultTokens as Record<string, unknown>;
  }
}
```

- [ ] **Step 6: Commit**

```bash
git add apps/render-scaffold/src/lib/loadSchema.ts apps/render-scaffold/src/lib/loadTokens.ts apps/render-scaffold/tests/loadSchema.test.ts
git commit -m "feat(render-scaffold): loadSchema + loadTokens helpers"
```

---

## Task 4: Project ID → output directory resolver

**Files:**
- Create: `apps/render-scaffold/src/lib/resolveProject.ts`
- Create: `apps/render-scaffold/tests/resolveProject.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// apps/render-scaffold/tests/resolveProject.test.ts
import { describe, it } from "node:test";
import assert from "node:assert";
import { resolveProject } from "../src/lib/resolveProject";

describe("resolveProject", () => {
  it("rejects path traversal", () => {
    assert.throws(() => resolveProject("../etc"), /invalid project id/);
    assert.throws(() => resolveProject("a/b"), /invalid project id/);
    assert.throws(() => resolveProject(".hidden"), /invalid project id/);
  });

  it("returns the absolute path under output/", () => {
    const result = resolveProject("test-app");
    assert.ok(result.endsWith("/output/test-app"));
  });
});
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
cd apps/render-scaffold && npx tsx --test tests/resolveProject.test.ts
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement resolveProject.ts**

```ts
// apps/render-scaffold/src/lib/resolveProject.ts
import path from "node:path";

const OUTPUT_ROOT = process.env.OUTPUT_ROOT
  ?? path.resolve(process.cwd(), "..", "..", "output");

export function resolveProject(projectId: string): string {
  if (!projectId) throw new Error("invalid project id: empty");
  if (projectId.includes("/") || projectId.includes("..") || projectId.startsWith(".")) {
    throw new Error(`invalid project id: ${projectId}`);
  }
  return path.join(OUTPUT_ROOT, projectId);
}
```

- [ ] **Step 4: Run the test, verify it passes**

```bash
cd apps/render-scaffold && npx tsx --test tests/resolveProject.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/render-scaffold/src/lib/resolveProject.ts apps/render-scaffold/tests/resolveProject.test.ts
git commit -m "feat(render-scaffold): project-id resolver with traversal guard"
```

---

## Task 5: Dynamic schema route + render integration

**Files:**
- Create: `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx`

- [ ] **Step 1: Implement the route**

```tsx
// apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx
import { notFound } from "next/navigation";
import { loadSchema } from "@/lib/loadSchema";
import { loadTokens } from "@/lib/loadTokens";
import { resolveProject } from "@/lib/resolveProject";
import { SchemaRenderer, compileTokens } from "@tentoroforge/renderer";
import { createRegistry, defaultTokens } from "@tentoroforge/library";

// Build a minimal registry — we only need the components actually used by
// rendered schemas. The platform's EditorMount registers the full set; the
// scaffold mirrors a subset adequate for fidelity rendering.
import {
  Button, ButtonProps, Hero, HeroProps, Section, SectionProps,
  Card, CardProps, MetricTile, MetricTileProps, Avatar, AvatarProps,
  Badge, BadgeProps, KeyValueList, KeyValueListProps,
  Input, InputProps, Select, SelectProps, Textarea, TextareaProps,
  Checkbox, CheckboxProps, DatePicker, DatePickerProps,
  Heading, HeadingProps, Text as LibText, // (avoid clash with renderer's Text node)
  Table, TableProps, Tabs, TabsProps, Accordion, AccordionProps,
  AccordionPanel, FadeIn, FadeInProps, Stagger, StaggerProps,
  Split, SplitProps, Sidebar, SidebarProps, Cluster, ClusterProps,
  TabPanel, TabPanelProps, FeatureCard, FeatureCardProps, Skeleton, SkeletonProps,
  Link as LibLink, LinkProps, NavLink, NavLinkProps, Form, FormProps,
} from "@tentoroforge/library";
import { AccordionPanelNode } from "@tentoroforge/schema";

const registry = createRegistry();
const reg = (name: string, component: any, propsSchema: any, category: any, acceptsChildren = false) =>
  registry.register({ name, component, propsSchema, category, acceptsChildren });

reg("Button", Button, ButtonProps, "interactive");
reg("Link", LibLink, LinkProps, "interactive");
reg("NavLink", NavLink, NavLinkProps, "navigation");
reg("Hero", Hero, HeroProps, "layout", true);
reg("Section", Section, SectionProps, "layout", true);
reg("Card", Card, CardProps, "static", true);
reg("MetricTile", MetricTile, MetricTileProps, "static");
reg("Avatar", Avatar, AvatarProps, "static");
reg("Badge", Badge, BadgeProps, "static");
reg("KeyValueList", KeyValueList, KeyValueListProps, "static");
reg("Heading", Heading, HeadingProps, "static");
reg("FeatureCard", FeatureCard, FeatureCardProps, "static");
reg("Skeleton", Skeleton, SkeletonProps, "feedback");
reg("Form", Form, FormProps, "form", true);
reg("Input", Input, InputProps, "form");
reg("Select", Select, SelectProps, "form");
reg("Textarea", Textarea, TextareaProps, "form");
reg("Checkbox", Checkbox, CheckboxProps, "form");
reg("DatePicker", DatePicker, DatePickerProps, "form");
reg("Table", Table, TableProps, "data");
reg("Tabs", Tabs, TabsProps, "layout", true);
reg("TabPanel", TabPanel, TabPanelProps, "layout", true);
reg("Accordion", Accordion, AccordionProps, "layout", true);
reg("AccordionPanel", AccordionPanel, AccordionPanelNode.shape.props, "layout", true);
reg("Split", Split, SplitProps, "layout", true);
reg("Sidebar", Sidebar, SidebarProps, "layout", true);
reg("Cluster", Cluster, ClusterProps, "layout", true);
reg("FadeIn", FadeIn, FadeInProps, "motion", true);
reg("Stagger", Stagger, StaggerProps, "motion", true);

export default async function Page({ params, searchParams }: { params: Promise<{ projectId: string; slug: string[] }>; searchParams: Promise<{ preview?: string }> }) {
  const { projectId, slug } = await params;
  const { preview } = await searchParams;
  const isPreview = preview === "true";

  let projectRoot: string;
  try {
    projectRoot = resolveProject(projectId);
  } catch {
    notFound();
  }

  const pagePath = slug.join("/");
  const schema = await loadSchema(projectRoot, pagePath);
  if (!schema) notFound();

  const tokens = await loadTokens(projectRoot);
  const tokenCssVars = compileTokens(tokens) as React.CSSProperties;

  // Stub data: empty for now (real fixtures land in Task 7+8). Pages that bind
  // to data sources will render with literal {{...}} placeholders, which the
  // renderer's interpolator falls back to when expressions don't resolve.
  const data = isPreview ? {} : {};

  return (
    <main style={tokenCssVars} data-project-id={projectId} data-page-path={pagePath}>
      <SchemaRenderer schema={schema as any} data={data} registry={registry} />
    </main>
  );
}
```

- [ ] **Step 2: Verify the route boots without error**

```bash
cd apps/render-scaffold
npm run dev > /tmp/scaffold-boot.log 2>&1 &
sleep 6
# A non-existent project should 404
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:6503/p/does-not-exist/users/list
# Existing project's existing schema should 200
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:6503/p/7zn274s3/users/list
lsof -ti:6503 | xargs kill -9
```

Expected: first `404`, second `200`.

- [ ] **Step 3: Commit**

```bash
git add apps/render-scaffold/src/app/p
git commit -m "feat(render-scaffold): dynamic /p/<projectId>/<slug> route renders project schemas"
```

---

## Task 6: A11y tree extractor

**Files:**
- Create: `apps/render-scaffold/src/lib/a11yTree.ts`
- Create: `apps/render-scaffold/src/components/A11yTreeEmbed.tsx`
- Modify: `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx` — embed the script tag

- [ ] **Step 1: Implement a11yTree.ts**

```ts
// apps/render-scaffold/src/lib/a11yTree.ts
// Walks a JSON schema's root and produces a text-only outline.
// Used by the render service to feed structural context to the vision evaluator.
type Node = { id?: string; type?: string; props?: Record<string, unknown>; children?: Node[] };

export function buildA11yTree(schema: { root: Node; meta?: { title?: string } }): string {
  const lines: string[] = [];
  if (schema.meta?.title) lines.push(`# ${schema.meta.title}`);
  function walk(n: Node, depth: number): void {
    if (!n || typeof n !== "object") return;
    const indent = "  ".repeat(depth);
    const label = textOf(n);
    lines.push(`${indent}- ${n.type ?? "?"}${label ? ` "${label}"` : ""}`);
    for (const c of n.children ?? []) walk(c, depth + 1);
  }
  walk(schema.root, 0);
  return lines.join("\n");
}

function textOf(n: Node): string {
  const p = n.props ?? {};
  for (const k of ["headline", "title", "label", "content", "value", "name"]) {
    const v = (p as any)[k];
    if (typeof v === "string" && v.length > 0 && v.length < 80) return v;
  }
  return "";
}
```

- [ ] **Step 2: Implement A11yTreeEmbed component**

```tsx
// apps/render-scaffold/src/components/A11yTreeEmbed.tsx
export function A11yTreeEmbed({ tree }: { tree: string }) {
  return (
    <script
      type="application/json"
      id="__a11y_tree__"
      // The tree is plain text; serialise as JSON-string so the contained
      // newlines and quotes survive HTML escaping.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(tree) }}
    />
  );
}
```

- [ ] **Step 3: Wire into the schema page**

Modify `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx` — add at top of imports:

```tsx
import { A11yTreeEmbed } from "@/components/A11yTreeEmbed";
import { buildA11yTree } from "@/lib/a11yTree";
```

Inside the component, before `return (...)`, add:

```tsx
const a11yTree = buildA11yTree(schema as any);
```

Add inside the `<main>` JSX, after the SchemaRenderer:

```tsx
<A11yTreeEmbed tree={a11yTree} />
```

- [ ] **Step 4: Verify the script tag is in the rendered HTML**

```bash
cd apps/render-scaffold
npm run dev > /tmp/scaffold-boot.log 2>&1 &
sleep 6
curl -s http://localhost:6503/p/7zn274s3/users/list | grep -q '__a11y_tree__' && echo OK || echo FAIL
lsof -ti:6503 | xargs kill -9
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/render-scaffold/src/lib/a11yTree.ts apps/render-scaffold/src/components/A11yTreeEmbed.tsx apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx
git commit -m "feat(render-scaffold): embed a11y tree as JSON script tag"
```

---

## Task 7: Backend fixtures library — Layer 3 fallback

**Files:**
- Create: `backend/services/fixtures/__init__.py`
- Create: `backend/services/fixtures/types.py`
- Create: `backend/services/fixtures/fallback.py`
- Create: `backend/tests/services/test_fixtures_fallback.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_fixtures_fallback.py
from services.fixtures.fallback import fallback_value


def test_uuid_field_returns_a_uuid_string():
    v = fallback_value("id", "uuid")
    assert isinstance(v, str) and len(v) == 36


def test_string_field_returns_lorem():
    v = fallback_value("description", "varchar(255)")
    assert isinstance(v, str) and len(v) > 0


def test_number_field_returns_zero():
    v = fallback_value("amount", "numeric")
    assert v == 0


def test_boolean_field_returns_false():
    v = fallback_value("isActive", "boolean")
    assert v is False


def test_unknown_type_returns_none():
    v = fallback_value("mystery", "made_up_type")
    assert v is None
```

- [ ] **Step 2: Run, verify failure**

```bash
cd backend && python3 -m pytest tests/services/test_fixtures_fallback.py -v
```

Expected: FAIL with import error.

- [ ] **Step 3: Implement types.py + fallback.py**

```python
# backend/services/fixtures/types.py
from dataclasses import dataclass
from typing import Any


@dataclass
class FieldHint:
    name: str
    type: str
    nullable: bool = False
    primary_key: bool = False


@dataclass
class FixtureBundle:
    """A set of fake records keyed by entity name."""
    records: dict[str, list[dict[str, Any]]]
```

```python
# backend/services/fixtures/fallback.py
import uuid


_NUMERIC_TYPE_PREFIXES = ("int", "numeric", "decimal", "float", "double", "real", "serial")


def fallback_value(field_name: str, sql_type: str) -> object:
    """Type-correct nonsense for a field whose name/type doesn't match any
    higher-layer rule. Used by the fixtures Layer 3 fallback."""
    t = (sql_type or "").lower().strip()
    if t.startswith("uuid") or field_name.lower() == "id":
        return str(uuid.uuid4())
    if t.startswith(("varchar", "text", "char")) or t == "string":
        return "Lorem ipsum dolor sit amet"
    if t.startswith(_NUMERIC_TYPE_PREFIXES):
        return 0
    if t.startswith(("bool", "tinyint(1)")):
        return False
    if t.startswith(("date", "timestamp", "time")):
        return "2026-01-01T00:00:00Z"
    if t.startswith(("json", "jsonb")):
        return {}
    return None
```

```python
# backend/services/fixtures/__init__.py
from .fallback import fallback_value
from .types import FieldHint, FixtureBundle

__all__ = ["fallback_value", "FieldHint", "FixtureBundle"]
```

- [ ] **Step 4: Run, verify pass**

```bash
cd backend && python3 -m pytest tests/services/test_fixtures_fallback.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/fixtures/__init__.py backend/services/fixtures/types.py backend/services/fixtures/fallback.py backend/tests/services/test_fixtures_fallback.py
git commit -m "feat(fixtures): Layer 3 type-correct fallback values"
```

---

## Task 8: Backend fixtures — Layer 2 Faker generator

**Files:**
- Create: `backend/services/fixtures/faker_gen.py`
- Create: `backend/tests/services/test_fixtures_faker.py`
- Modify: `backend/requirements.txt` — add `Faker==30.6.0`

- [ ] **Step 1: Add Faker to requirements + install**

Modify `backend/requirements.txt` (append):

```
Faker==30.6.0
```

Install:

```bash
cd backend && pip install -r requirements.txt
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/services/test_fixtures_faker.py
from services.fixtures.faker_gen import generate_record, generate_records
from services.fixtures.types import FieldHint


def fields(*pairs: tuple[str, str]) -> list[FieldHint]:
    return [FieldHint(name=n, type=t) for n, t in pairs]


def test_email_field_gets_a_real_email():
    r = generate_record("User", fields(("id", "uuid"), ("email", "varchar(255)")))
    assert "@" in r["email"]


def test_name_field_gets_a_full_name():
    r = generate_record("User", fields(("name", "varchar(255)")))
    assert " " in r["name"]


def test_unmapped_field_uses_fallback():
    r = generate_record("Foo", fields(("frobnicator", "made_up_type")))
    assert r["frobnicator"] is None


def test_generate_records_produces_count_distinct_records():
    rs = generate_records("User", fields(("id", "uuid"), ("email", "varchar(255)")), count=5)
    assert len(rs) == 5
    assert len({r["id"] for r in rs}) == 5
```

- [ ] **Step 3: Run, verify failure**

```bash
cd backend && python3 -m pytest tests/services/test_fixtures_faker.py -v
```

Expected: FAIL with import error.

- [ ] **Step 4: Implement faker_gen.py**

```python
# backend/services/fixtures/faker_gen.py
"""Layer 2 fixture generator — uses Faker to produce realistic per-field values
based on the field name + type. Domain-aware enums (department, status) come
from the optional `domain` parameter; without it, generic lists are used."""
from __future__ import annotations

from typing import Any

from faker import Faker

from .fallback import fallback_value
from .types import FieldHint

_faker = Faker()


_DOMAIN_DEPARTMENTS = {
    "healthcare": ["Cardiology", "Oncology", "Pediatrics", "Emergency", "Radiology"],
    "fintech":    ["Trading", "Compliance", "Operations", "Risk", "Engineering"],
    "hr":         ["Engineering", "Marketing", "Sales", "Operations", "People"],
    "general":    ["Engineering", "Sales", "Operations", "Support", "Marketing"],
}

_STATUS_VALUES = ["active", "pending", "approved", "rejected", "archived"]


def _by_field_name(name: str, domain: str) -> Any | None:
    """Return a value for well-known field names, or None to fall through."""
    n = name.lower()
    if n == "id" or n.endswith("id"):
        return _faker.uuid4()
    if n in ("email", "emailaddress"):
        return _faker.email()
    if n in ("name", "fullname", "fullName".lower()):
        return _faker.name()
    if n in ("firstname",):
        return _faker.first_name()
    if n in ("lastname",):
        return _faker.last_name()
    if n in ("phone", "phonenumber"):
        return _faker.phone_number()
    if n in ("address",):
        return _faker.street_address()
    if n in ("city",):
        return _faker.city()
    if n in ("country",):
        return _faker.country()
    if n in ("company", "companyname"):
        return _faker.company()
    if n in ("amount", "balance", "price", "total"):
        return float(_faker.pydecimal(left_digits=4, right_digits=2, positive=True))
    if n in ("department", "dept"):
        return _faker.random_element(_DOMAIN_DEPARTMENTS.get(domain, _DOMAIN_DEPARTMENTS["general"]))
    if n in ("status", "state"):
        return _faker.random_element(_STATUS_VALUES)
    if n in ("createdat", "created", "createdAt".lower(), "updatedat", "updatedAt".lower(), "timestamp"):
        return _faker.date_time_this_year().isoformat()
    if n in ("description", "notes", "summary", "bio"):
        return _faker.sentence(nb_words=12)
    if n in ("title",):
        return _faker.catch_phrase()
    if n in ("url", "website"):
        return _faker.url()
    if n in ("avatar", "avatarurl", "photo", "image"):
        return _faker.image_url()
    return None


def generate_record(entity_name: str, fields: list[FieldHint], domain: str = "general") -> dict[str, Any]:
    """Generate a single record from the field list."""
    record: dict[str, Any] = {}
    for field in fields:
        value = _by_field_name(field.name, domain)
        if value is None:
            value = fallback_value(field.name, field.type)
        record[field.name] = value
    return record


def generate_records(entity_name: str, fields: list[FieldHint], count: int = 10, domain: str = "general") -> list[dict[str, Any]]:
    """Generate `count` records. Each call gets a different seed for variety."""
    return [generate_record(entity_name, fields, domain) for _ in range(count)]
```

- [ ] **Step 5: Run, verify pass**

```bash
cd backend && python3 -m pytest tests/services/test_fixtures_faker.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/fixtures/faker_gen.py backend/tests/services/test_fixtures_faker.py backend/requirements.txt
git commit -m "feat(fixtures): Layer 2 Faker-based per-entity generation"
```

---

## Task 9: Backend fixtures — Layer 1 domain banks + loader

**Files:**
- Create: `backend/fixtures/general/User.json`
- Create: `backend/fixtures/general/Item.json`
- Create: `backend/fixtures/healthcare/Patient.json`
- Create: `backend/fixtures/fintech/Account.json`
- Create: `backend/fixtures/hr/Employee.json`
- Create: `backend/services/fixtures/loader.py`
- Create: `backend/tests/services/test_fixtures_loader.py`

- [ ] **Step 1: Create general/User.json (10 records)**

```json
[
  { "id": "00000000-0000-0000-0000-000000000001", "email": "sarah.chen@example.com", "name": "Sarah Chen", "role": "admin", "department": "Engineering", "createdAt": "2025-01-15T09:30:00Z" },
  { "id": "00000000-0000-0000-0000-000000000002", "email": "marcus.lee@example.com", "name": "Marcus Lee", "role": "editor", "department": "Marketing", "createdAt": "2025-02-08T14:12:00Z" },
  { "id": "00000000-0000-0000-0000-000000000003", "email": "ana.martins@example.com", "name": "Ana Martins", "role": "viewer", "department": "Sales", "createdAt": "2025-03-21T08:45:00Z" },
  { "id": "00000000-0000-0000-0000-000000000004", "email": "kenji.tanaka@example.com", "name": "Kenji Tanaka", "role": "admin", "department": "Engineering", "createdAt": "2025-04-12T16:00:00Z" },
  { "id": "00000000-0000-0000-0000-000000000005", "email": "priya.shah@example.com", "name": "Priya Shah", "role": "editor", "department": "People", "createdAt": "2025-05-03T11:20:00Z" },
  { "id": "00000000-0000-0000-0000-000000000006", "email": "diego.alvarez@example.com", "name": "Diego Alvarez", "role": "viewer", "department": "Operations", "createdAt": "2025-06-18T13:50:00Z" },
  { "id": "00000000-0000-0000-0000-000000000007", "email": "fatima.rashid@example.com", "name": "Fatima Rashid", "role": "editor", "department": "Engineering", "createdAt": "2025-07-09T10:35:00Z" },
  { "id": "00000000-0000-0000-0000-000000000008", "email": "noah.mueller@example.com", "name": "Noah Müller", "role": "admin", "department": "Operations", "createdAt": "2025-08-22T15:05:00Z" },
  { "id": "00000000-0000-0000-0000-000000000009", "email": "imani.okonkwo@example.com", "name": "Imani Okonkwo", "role": "viewer", "department": "Sales", "createdAt": "2025-09-14T09:00:00Z" },
  { "id": "00000000-0000-0000-0000-000000000010", "email": "long.name.with.lots.of.parts@example.com", "name": "Henrietta Wellington-Smythe-Jones IV", "role": "admin", "department": "Engineering", "createdAt": "2025-10-30T19:30:00Z" }
]
```

- [ ] **Step 2: Create general/Item.json**

```json
[
  { "id": "00000000-0000-0000-0000-000000000101", "name": "Sample Item One", "description": "A first sample item used for previewing list pages", "status": "active", "createdAt": "2025-08-01T10:00:00Z" },
  { "id": "00000000-0000-0000-0000-000000000102", "name": "Demo Widget", "description": "Widget shown in MetricTile previews", "status": "pending", "createdAt": "2025-08-15T14:30:00Z" },
  { "id": "00000000-0000-0000-0000-000000000103", "name": "Test Record", "description": "Record with longer descriptive text to exercise text wrap behaviour and ensure components handle multi-line content correctly", "status": "approved", "createdAt": "2025-09-02T09:15:00Z" },
  { "id": "00000000-0000-0000-0000-000000000104", "name": "Quick Entry", "description": "Short", "status": "active", "createdAt": "2025-09-20T16:45:00Z" },
  { "id": "00000000-0000-0000-0000-000000000105", "name": "Edge Case Sample", "description": "Item with all common rendering edge cases", "status": "rejected", "createdAt": "2025-10-08T11:30:00Z" },
  { "id": "00000000-0000-0000-0000-000000000106", "name": "Standard Item", "description": "Bog-standard item entry", "status": "active", "createdAt": "2025-10-25T08:00:00Z" },
  { "id": "00000000-0000-0000-0000-000000000107", "name": "Recent Addition", "description": "Newly added record to test sort order", "status": "pending", "createdAt": "2025-11-10T17:20:00Z" },
  { "id": "00000000-0000-0000-0000-000000000108", "name": "Archived Example", "description": "Older record, possibly archived", "status": "archived", "createdAt": "2025-04-04T12:00:00Z" },
  { "id": "00000000-0000-0000-0000-000000000109", "name": "Mid Year", "description": "Mid-year sample", "status": "active", "createdAt": "2025-06-30T14:00:00Z" },
  { "id": "00000000-0000-0000-0000-000000000110", "name": "Last Item", "description": "Final entry in the seed list", "status": "approved", "createdAt": "2025-12-15T18:30:00Z" }
]
```

- [ ] **Step 3: Create healthcare/Patient.json (skeleton — same shape, healthcare fields)**

```json
[
  { "id": "p-0001", "mrn": "MRN-484921", "name": "Eleanor Park", "dateOfBirth": "1958-03-12", "primaryConcern": "Hypertension follow-up", "status": "active", "lastVisit": "2025-11-04T09:30:00Z" },
  { "id": "p-0002", "mrn": "MRN-302184", "name": "James Whitaker", "dateOfBirth": "1982-07-29", "primaryConcern": "Annual physical", "status": "scheduled", "lastVisit": "2025-09-15T13:00:00Z" },
  { "id": "p-0003", "mrn": "MRN-918273", "name": "Aiko Tanaka", "dateOfBirth": "1995-12-04", "primaryConcern": "Pre-natal — second trimester", "status": "active", "lastVisit": "2025-10-22T10:45:00Z" },
  { "id": "p-0004", "mrn": "MRN-556102", "name": "Rashid Khan", "dateOfBirth": "1971-05-18", "primaryConcern": "Type 2 diabetes management", "status": "active", "lastVisit": "2025-11-08T16:15:00Z" },
  { "id": "p-0005", "mrn": "MRN-110928", "name": "Sofia Reyes", "dateOfBirth": "2014-08-25", "primaryConcern": "Pediatric immunization schedule", "status": "active", "lastVisit": "2025-10-30T11:00:00Z" },
  { "id": "p-0006", "mrn": "MRN-223847", "name": "David Olsen", "dateOfBirth": "1948-01-09", "primaryConcern": "Cardiology consult — post-CABG", "status": "active", "lastVisit": "2025-11-12T08:30:00Z" },
  { "id": "p-0007", "mrn": "MRN-998877", "name": "Maria Santos", "dateOfBirth": "1989-04-17", "primaryConcern": "Migraine workup", "status": "scheduled", "lastVisit": "2025-09-28T14:00:00Z" },
  { "id": "p-0008", "mrn": "MRN-446629", "name": "Kwame Nkrumah", "dateOfBirth": "1965-11-30", "primaryConcern": "Annual oncology follow-up — remission", "status": "active", "lastVisit": "2025-08-19T15:30:00Z" },
  { "id": "p-0009", "mrn": "MRN-771203", "name": "Helena Brennan", "dateOfBirth": "1992-02-14", "primaryConcern": "Anxiety / mental health screening", "status": "active", "lastVisit": "2025-11-01T17:00:00Z" },
  { "id": "p-0010", "mrn": "MRN-330156", "name": "Yuki Watanabe", "dateOfBirth": "1976-09-08", "primaryConcern": "Orthopedic — knee replacement follow-up", "status": "active", "lastVisit": "2025-10-14T12:30:00Z" }
]
```

- [ ] **Step 4: Create fintech/Account.json**

```json
[
  { "id": "acc-001", "accountNumber": "**** 4821", "accountHolder": "Sarah Chen", "balance": 482910.50, "currency": "USD", "type": "investment", "status": "active", "openedAt": "2023-04-12T10:00:00Z" },
  { "id": "acc-002", "accountNumber": "**** 9376", "accountHolder": "Marcus Lee Trust", "balance": 1284502.18, "currency": "USD", "type": "trust", "status": "active", "openedAt": "2019-08-22T09:30:00Z" },
  { "id": "acc-003", "accountNumber": "**** 1052", "accountHolder": "Diego Alvarez", "balance": 38240.92, "currency": "EUR", "type": "savings", "status": "active", "openedAt": "2024-02-08T11:15:00Z" },
  { "id": "acc-004", "accountNumber": "**** 6648", "accountHolder": "Imani Okonkwo", "balance": 192847.00, "currency": "USD", "type": "checking", "status": "active", "openedAt": "2021-10-30T14:00:00Z" },
  { "id": "acc-005", "accountNumber": "**** 0294", "accountHolder": "Ana Martins", "balance": 56120.75, "currency": "USD", "type": "investment", "status": "frozen", "openedAt": "2022-06-14T08:45:00Z" },
  { "id": "acc-006", "accountNumber": "**** 8473", "accountHolder": "Fatima Rashid", "balance": 928340.62, "currency": "USD", "type": "investment", "status": "active", "openedAt": "2020-11-19T13:30:00Z" },
  { "id": "acc-007", "accountNumber": "**** 5519", "accountHolder": "Noah Müller", "balance": 12480.00, "currency": "EUR", "type": "savings", "status": "active", "openedAt": "2024-09-04T16:00:00Z" },
  { "id": "acc-008", "accountNumber": "**** 3927", "accountHolder": "Kenji Tanaka", "balance": 645210.33, "currency": "JPY", "type": "investment", "status": "active", "openedAt": "2018-03-25T10:20:00Z" },
  { "id": "acc-009", "accountNumber": "**** 7104", "accountHolder": "Priya Shah", "balance": 84920.40, "currency": "USD", "type": "checking", "status": "active", "openedAt": "2023-12-11T09:00:00Z" },
  { "id": "acc-010", "accountNumber": "**** 2658", "accountHolder": "Henrietta Wellington-Smythe-Jones IV", "balance": 4820000.00, "currency": "USD", "type": "investment", "status": "active", "openedAt": "2015-07-08T15:45:00Z" }
]
```

- [ ] **Step 5: Create hr/Employee.json**

```json
[
  { "id": "emp-001", "employeeId": "EMP-00542", "name": "Sarah Chen", "jobTitle": "Senior Engineer", "department": "Engineering", "manager": "Marcus Lee", "startDate": "2022-04-15", "status": "active" },
  { "id": "emp-002", "employeeId": "EMP-00184", "name": "Marcus Lee", "jobTitle": "Engineering Manager", "department": "Engineering", "manager": "Diego Alvarez", "startDate": "2019-08-22", "status": "active" },
  { "id": "emp-003", "employeeId": "EMP-01029", "name": "Ana Martins", "jobTitle": "Product Designer", "department": "Design", "manager": "Priya Shah", "startDate": "2023-02-08", "status": "active" },
  { "id": "emp-004", "employeeId": "EMP-00763", "name": "Kenji Tanaka", "jobTitle": "Staff Engineer", "department": "Engineering", "manager": "Marcus Lee", "startDate": "2020-11-30", "status": "active" },
  { "id": "emp-005", "employeeId": "EMP-00219", "name": "Priya Shah", "jobTitle": "VP of Design", "department": "Design", "manager": null, "startDate": "2018-06-14", "status": "active" },
  { "id": "emp-006", "employeeId": "EMP-01284", "name": "Diego Alvarez", "jobTitle": "VP of Engineering", "department": "Engineering", "manager": null, "startDate": "2017-03-04", "status": "active" },
  { "id": "emp-007", "employeeId": "EMP-00891", "name": "Fatima Rashid", "jobTitle": "Senior Engineer", "department": "Engineering", "manager": "Marcus Lee", "startDate": "2021-09-12", "status": "active" },
  { "id": "emp-008", "employeeId": "EMP-00456", "name": "Noah Müller", "jobTitle": "Operations Lead", "department": "Operations", "manager": "Imani Okonkwo", "startDate": "2022-12-08", "status": "on-leave" },
  { "id": "emp-009", "employeeId": "EMP-00328", "name": "Imani Okonkwo", "jobTitle": "VP of Operations", "department": "Operations", "manager": null, "startDate": "2019-04-22", "status": "active" },
  { "id": "emp-010", "employeeId": "EMP-01437", "name": "Yuki Watanabe", "jobTitle": "Junior Engineer", "department": "Engineering", "manager": "Fatima Rashid", "startDate": "2024-09-02", "status": "probation" }
]
```

- [ ] **Step 6: Write the failing test for the loader**

```python
# backend/tests/services/test_fixtures_loader.py
import pytest

from services.fixtures.loader import load_domain_bank, available_domains


def test_general_user_bank_has_10_records():
    records = load_domain_bank("general", "User")
    assert records is not None
    assert len(records) == 10
    assert all("id" in r for r in records)


def test_unknown_domain_returns_none():
    assert load_domain_bank("nonexistent_domain", "User") is None


def test_unknown_entity_in_known_domain_returns_none():
    assert load_domain_bank("general", "NoSuchEntity") is None


def test_available_domains_lists_seeded_ones():
    domains = available_domains()
    assert "general" in domains
    assert "healthcare" in domains
    assert "fintech" in domains
    assert "hr" in domains
```

- [ ] **Step 7: Run, verify failure**

```bash
cd backend && python3 -m pytest tests/services/test_fixtures_loader.py -v
```

Expected: FAIL with import error.

- [ ] **Step 8: Implement loader.py**

```python
# backend/services/fixtures/loader.py
"""Layer 1 fixture loader — reads hand-curated domain bank JSON files from
backend/fixtures/<domain>/<EntityName>.json. Falls through (returns None) when
a bank doesn't exist; callers fall back to Layer 2 (Faker) or Layer 3
(type-correct nonsense)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Bank root is backend/fixtures/, alongside this services/ tree
_BANK_ROOT = Path(__file__).resolve().parents[2] / "fixtures"


def load_domain_bank(domain: str, entity_name: str) -> list[dict[str, Any]] | None:
    """Load all records for `entity_name` in `domain`, or None if absent."""
    if not domain or not entity_name:
        return None
    path = _BANK_ROOT / domain / f"{entity_name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, list):
        return None
    return data


def available_domains() -> list[str]:
    """List domain directories present in the fixtures bank."""
    if not _BANK_ROOT.exists():
        return []
    return sorted(p.name for p in _BANK_ROOT.iterdir() if p.is_dir() and not p.name.startswith("."))
```

Update `backend/services/fixtures/__init__.py`:

```python
from .fallback import fallback_value
from .faker_gen import generate_record, generate_records
from .loader import load_domain_bank, available_domains
from .types import FieldHint, FixtureBundle

__all__ = [
    "fallback_value",
    "generate_record", "generate_records",
    "load_domain_bank", "available_domains",
    "FieldHint", "FixtureBundle",
]
```

- [ ] **Step 9: Run, verify pass**

```bash
cd backend && python3 -m pytest tests/services/test_fixtures_loader.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/fixtures backend/services/fixtures/loader.py backend/services/fixtures/__init__.py backend/tests/services/test_fixtures_loader.py
git commit -m "feat(fixtures): Layer 1 curated domain banks (general / healthcare / fintech / hr)"
```

---

## Task 10: Fixtures dispatcher (resolve domain → entity → records)

**Files:**
- Create: `backend/services/fixtures/dispatcher.py`
- Create: `backend/tests/services/test_fixtures_dispatcher.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_fixtures_dispatcher.py
from services.fixtures.dispatcher import provide_records
from services.fixtures.types import FieldHint


def test_layer_1_hit_for_general_user():
    rs = provide_records(domain="general", entity_name="User", fields=[], count=10)
    assert len(rs) == 10
    # Sourced from the curated bank — first record's name is fixed
    assert rs[0]["name"] == "Sarah Chen"


def test_layer_2_fallback_when_bank_missing():
    fields = [FieldHint(name="id", type="uuid"), FieldHint(name="email", type="varchar(255)")]
    rs = provide_records(domain="general", entity_name="UnknownEntity", fields=fields, count=3)
    assert len(rs) == 3
    assert all("@" in r["email"] for r in rs)


def test_layer_3_fallback_when_no_fields_and_no_bank():
    rs = provide_records(domain="general", entity_name="UnknownEntity", fields=[], count=2)
    # Empty field list returns empty records (one per requested count)
    assert len(rs) == 2
    assert rs[0] == {}
```

- [ ] **Step 2: Run, verify failure**

```bash
cd backend && python3 -m pytest tests/services/test_fixtures_dispatcher.py -v
```

Expected: FAIL with import error.

- [ ] **Step 3: Implement dispatcher.py**

```python
# backend/services/fixtures/dispatcher.py
"""Top-level fixtures dispatcher — picks the best layer for each request.

Layer 1: hand-curated domain bank (preferred; realistic, stable across renders).
Layer 2: Faker-generated records (when bank is absent and fields are known).
Layer 3: empty records (when neither bank nor fields are available).
"""
from __future__ import annotations

from typing import Any

from .faker_gen import generate_records
from .loader import load_domain_bank
from .types import FieldHint


def provide_records(
    domain: str,
    entity_name: str,
    fields: list[FieldHint],
    count: int = 10,
) -> list[dict[str, Any]]:
    """Return up to `count` records for the given (domain, entity).

    Resolution order:
      1. Curated bank in backend/fixtures/<domain>/<entity_name>.json
      2. Faker-based generation from `fields`
      3. Empty dicts (last resort)
    """
    bank = load_domain_bank(domain, entity_name)
    if bank is not None:
        return bank[:count]
    if fields:
        return generate_records(entity_name, fields, count=count, domain=domain)
    return [dict() for _ in range(count)]
```

Update `__init__.py`:

```python
from .dispatcher import provide_records
from .fallback import fallback_value
from .faker_gen import generate_record, generate_records
from .loader import load_domain_bank, available_domains
from .types import FieldHint, FixtureBundle

__all__ = [
    "provide_records",
    "fallback_value",
    "generate_record", "generate_records",
    "load_domain_bank", "available_domains",
    "FieldHint", "FixtureBundle",
]
```

- [ ] **Step 4: Run, verify pass**

```bash
cd backend && python3 -m pytest tests/services/test_fixtures_dispatcher.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/fixtures/dispatcher.py backend/services/fixtures/__init__.py backend/tests/services/test_fixtures_dispatcher.py
git commit -m "feat(fixtures): top-level dispatcher resolving Layer 1 → 2 → 3"
```

---

## Task 11: Render-service browser pool

**Files:**
- Create: `backend/services/render_service/__init__.py`
- Create: `backend/services/render_service/browser_pool.py`
- Create: `backend/tests/services/test_browser_pool.py`
- Modify: `backend/requirements.txt` — add `playwright==1.49.0`

- [ ] **Step 1: Add Playwright + install browser**

Append to `backend/requirements.txt`:

```
playwright==1.49.0
```

Install + browser binary:

```bash
cd backend && pip install -r requirements.txt
python3 -m playwright install chromium
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/services/test_browser_pool.py
import asyncio

import pytest

from services.render_service.browser_pool import BrowserPool


@pytest.mark.asyncio
async def test_pool_starts_and_serves_a_context():
    pool = BrowserPool()
    await pool.start()
    try:
        async with pool.acquire() as ctx:
            page = await ctx.new_page()
            await page.set_content("<h1>hello</h1>")
            assert await page.title() == ""  # no <title> in markup
            text = await page.text_content("h1")
            assert text == "hello"
    finally:
        await pool.stop()


@pytest.mark.asyncio
async def test_pool_serves_concurrent_acquires():
    pool = BrowserPool()
    await pool.start()
    try:
        async def fetch_text() -> str:
            async with pool.acquire() as ctx:
                page = await ctx.new_page()
                await page.set_content("<p>concurrent</p>")
                return await page.text_content("p") or ""
        results = await asyncio.gather(*[fetch_text() for _ in range(3)])
        assert results == ["concurrent"] * 3
    finally:
        await pool.stop()
```

- [ ] **Step 3: Run, verify failure**

```bash
cd backend && python3 -m pytest tests/services/test_browser_pool.py -v
```

Expected: FAIL with module-not-found.

- [ ] **Step 4: Implement browser_pool.py**

```python
# backend/services/render_service/browser_pool.py
"""Long-lived Playwright browser instance + per-acquire isolated contexts.

Why a pool: Playwright's Chromium boot is ~800ms — too slow to do per-render.
A single warm browser process serves many renders; each render gets its own
context (cookies, storage, cache) so they're isolated. Contexts are closed on
release."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Browser, BrowserContext, async_playwright


class BrowserPool:
    """Holds one warm Chromium instance; vends BrowserContext per acquire."""

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._browser: Browser | None = None
        self._playwright = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._browser is not None:
                return
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self._headless)

    async def stop(self) -> None:
        async with self._lock:
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None

    @asynccontextmanager
    async def acquire(self, viewport_w: int = 1280, viewport_h: int = 800) -> AsyncIterator[BrowserContext]:
        if self._browser is None:
            raise RuntimeError("BrowserPool not started — call start() first")
        ctx = await self._browser.new_context(viewport={"width": viewport_w, "height": viewport_h})
        try:
            yield ctx
        finally:
            await ctx.close()
```

```python
# backend/services/render_service/__init__.py
from .browser_pool import BrowserPool

__all__ = ["BrowserPool"]
```

- [ ] **Step 5: Run, verify pass**

```bash
cd backend && python3 -m pytest tests/services/test_browser_pool.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/render_service/__init__.py backend/services/render_service/browser_pool.py backend/tests/services/test_browser_pool.py backend/requirements.txt
git commit -m "feat(render-service): warm Playwright browser pool"
```

---

## Task 12: Render cache (SHA-256 keyed file-system cache)

**Files:**
- Create: `backend/services/render_service/cache.py`
- Create: `backend/tests/services/test_render_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_render_cache.py
from pathlib import Path

import pytest

from services.render_service.cache import RenderCache


@pytest.fixture
def cache(tmp_path: Path) -> RenderCache:
    return RenderCache(root=tmp_path)


def test_cache_miss_returns_none(cache: RenderCache):
    assert cache.get("anykey") is None


def test_cache_set_and_get_round_trips_bytes(cache: RenderCache):
    cache.set("k1", b"PNGDATA")
    assert cache.get("k1") == b"PNGDATA"


def test_cache_invalidate_removes_entry(cache: RenderCache):
    cache.set("k2", b"X")
    cache.invalidate("k2")
    assert cache.get("k2") is None


def test_cache_clear_empties_all(cache: RenderCache):
    cache.set("a", b"1")
    cache.set("b", b"2")
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_cache_make_key_is_deterministic():
    k1 = RenderCache.make_key({"projectId": "abc", "page": "/x", "viewport": "desktop"})
    k2 = RenderCache.make_key({"viewport": "desktop", "page": "/x", "projectId": "abc"})
    assert k1 == k2  # Order-independent
```

- [ ] **Step 2: Run, verify failure**

```bash
cd backend && python3 -m pytest tests/services/test_render_cache.py -v
```

Expected: FAIL with import error.

- [ ] **Step 3: Implement cache.py**

```python
# backend/services/render_service/cache.py
"""File-system cache for rendered PNGs, keyed by SHA-256 of the render request."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class RenderCache:
    def __init__(self, root: Path | str):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_key(payload: dict[str, Any]) -> str:
        """Deterministic SHA-256 of a JSON-stable payload."""
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, key: str) -> bytes | None:
        path = self._root / f"{key}.png"
        if not path.exists():
            return None
        return path.read_bytes()

    def set(self, key: str, value: bytes) -> None:
        path = self._root / f"{key}.png"
        path.write_bytes(value)

    def invalidate(self, key: str) -> None:
        path = self._root / f"{key}.png"
        if path.exists():
            path.unlink()

    def clear(self) -> None:
        for p in self._root.glob("*.png"):
            p.unlink()
```

- [ ] **Step 4: Run, verify pass**

```bash
cd backend && python3 -m pytest tests/services/test_render_cache.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/render_service/cache.py backend/tests/services/test_render_cache.py
git commit -m "feat(render-service): SHA-256 keyed file-system cache"
```

---

## Task 13: Render-service FastAPI app + /render endpoint

**Files:**
- Create: `backend/services/render_service/server.py`
- Create: `backend/services/render_service/main.py`
- Create: `backend/tests/services/test_render_server.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_render_server.py
import pytest
from httpx import ASGITransport, AsyncClient

from services.render_service.server import build_app


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok():
    app = build_app(scaffold_url="http://localhost:6503")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_render_returns_422_when_scaffold_unreachable():
    # Point at a port that's definitely not listening.
    app = build_app(scaffold_url="http://localhost:54321")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/render", json={
            "projectId": "test", "pageRoute": "/x", "viewport": "desktop",
        })
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
```

- [ ] **Step 2: Run, verify failure**

```bash
cd backend && python3 -m pytest tests/services/test_render_server.py -v
```

Expected: FAIL with import error.

- [ ] **Step 3: Implement server.py**

```python
# backend/services/render_service/server.py
"""FastAPI app for the render-service. POST /render → PNG + a11y tree."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .browser_pool import BrowserPool
from .cache import RenderCache


VIEWPORT_DIMENSIONS = {
    "mobile":  (375,  667),
    "tablet":  (768,  1024),
    "desktop": (1280, 800),
}


class RenderRequest(BaseModel):
    projectId: str
    pageRoute: str
    viewport: Literal["mobile", "tablet", "desktop"] = "desktop"
    waitFor: Literal["networkidle", "load", "domcontentloaded"] = "networkidle"
    captureMode: Literal["fullPage", "aboveFold"] = "fullPage"
    fixturesProfile: Literal["auto", "minimal", "rich"] = "auto"


class RenderResponse(BaseModel):
    pngBase64: str
    pngBytes: int
    htmlSnapshot: str
    accessibilityTree: str
    renderTimeMs: int
    consoleWarnings: list[str] = Field(default_factory=list)
    networkFailures: list[str] = Field(default_factory=list)


def build_app(scaffold_url: str = "http://localhost:6503", cache_root: Path | str = "/tmp/render-cache") -> FastAPI:
    app = FastAPI(title="render-service")
    pool = BrowserPool()
    cache = RenderCache(root=cache_root)

    @app.on_event("startup")
    async def _startup() -> None:
        await pool.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await pool.stop()

    @app.get("/health")
    async def _health() -> dict[str, str]:
        return {"status": "ok"}

    @app.delete("/cache")
    async def _clear_cache() -> dict[str, str]:
        cache.clear()
        return {"status": "cleared"}

    @app.post("/render")
    async def _render(req: RenderRequest) -> RenderResponse:
        cache_key = RenderCache.make_key(req.model_dump())
        cached = cache.get(cache_key)
        if cached is not None:
            return RenderResponse(
                pngBase64=base64.b64encode(cached).decode("ascii"),
                pngBytes=len(cached), htmlSnapshot="", accessibilityTree="",
                renderTimeMs=0,
            )

        w, h = VIEWPORT_DIMENSIONS[req.viewport]
        target_url = f"{scaffold_url}/p/{req.projectId}{req.pageRoute}?preview=true"
        warnings: list[str] = []
        failures: list[str] = []
        start = asyncio.get_event_loop().time()
        try:
            async with pool.acquire(viewport_w=w, viewport_h=h) as ctx:
                page = await ctx.new_page()
                page.on("console", lambda msg: warnings.append(f"{msg.type}: {msg.text}") if msg.type in ("warning", "error") else None)
                page.on("requestfailed", lambda r: failures.append(f"{r.method} {r.url}: {r.failure}"))
                try:
                    await page.goto(target_url, wait_until=req.waitFor, timeout=15_000)
                except Exception as e:
                    raise HTTPException(status_code=422, detail={"error": f"navigation failed: {e}"})
                png = await page.screenshot(full_page=(req.captureMode == "fullPage"))
                html = await page.content()
                a11y_handle = await page.query_selector("#__a11y_tree__")
                a11y_tree = ""
                if a11y_handle is not None:
                    txt = await a11y_handle.text_content() or ""
                    try:
                        import json as _json
                        a11y_tree = _json.loads(txt)
                    except Exception:
                        a11y_tree = txt
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=422, detail={"error": f"render failed: {e}"})

        duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)
        cache.set(cache_key, png)
        return RenderResponse(
            pngBase64=base64.b64encode(png).decode("ascii"),
            pngBytes=len(png),
            htmlSnapshot=html[:200_000],
            accessibilityTree=a11y_tree[:50_000] if isinstance(a11y_tree, str) else "",
            renderTimeMs=duration_ms,
            consoleWarnings=warnings[:50],
            networkFailures=failures[:50],
        )

    return app
```

```python
# backend/services/render_service/main.py
"""Entry point: `python -m backend.services.render_service`"""
import os
import uvicorn

from .server import build_app


def main() -> None:
    scaffold_url = os.getenv("RENDER_SCAFFOLD_URL", "http://localhost:6503")
    port = int(os.getenv("RENDER_SERVICE_PORT", "6502"))
    uvicorn.run(build_app(scaffold_url=scaffold_url), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run, verify pass**

```bash
cd backend && python3 -m pytest tests/services/test_render_server.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/render_service/server.py backend/services/render_service/main.py backend/tests/services/test_render_server.py
git commit -m "feat(render-service): FastAPI /render endpoint + /health + DELETE /cache"
```

---

## Task 14: End-to-end render integration test

**Files:**
- Create: `backend/tests/integration/test_render_e2e.py`

- [ ] **Step 1: Write the integration test**

```python
# backend/tests/integration/test_render_e2e.py
"""End-to-end: spin up the scaffold, render a known project page, assert PNG comes back.

Requires:
  - apps/render-scaffold dependencies installed
  - Project 7zn274s3 present at output/7zn274s3 with at least users/list.json
"""
import asyncio
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from services.render_service.server import build_app
from httpx import ASGITransport, AsyncClient


SCAFFOLD_DIR = Path(__file__).resolve().parents[3] / "apps" / "render-scaffold"
SCAFFOLD_PORT = 6503


@pytest.fixture(scope="module")
def scaffold_proc():
    """Boot the scaffold dev server for the module's lifetime."""
    if not (SCAFFOLD_DIR / "node_modules").exists():
        pytest.skip("scaffold deps not installed; run `npm install` in apps/render-scaffold")
    if not (Path(__file__).resolve().parents[3] / "output" / "7zn274s3" / "src" / "schemas" / "users" / "list.json").exists():
        pytest.skip("test project 7zn274s3 not present in output/")

    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=str(SCAFFOLD_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "OUTPUT_ROOT": str(Path(__file__).resolve().parents[3] / "output")},
    )
    # Wait up to 15s for the scaffold to start serving
    for _ in range(30):
        try:
            r = httpx.get(f"http://localhost:{SCAFFOLD_PORT}/", timeout=1.0)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        proc.terminate()
        pytest.skip("scaffold failed to boot within 15s")

    yield proc

    proc.terminate()
    proc.wait(timeout=5)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_render_users_list_returns_a_png(scaffold_proc):
    app = build_app(scaffold_url=f"http://localhost:{SCAFFOLD_PORT}")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
        r = await client.post("/render", json={
            "projectId": "7zn274s3",
            "pageRoute": "/users/list",
            "viewport": "desktop",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pngBytes"] > 1000  # At least a kilobyte
        assert body["pngBase64"].startswith("iVBOR")  # PNG magic in base64
        assert body["accessibilityTree"]  # Non-empty tree extracted
```

- [ ] **Step 2: Install scaffold deps + run the e2e test**

```bash
cd apps/render-scaffold && npm install --legacy-peer-deps
cd ../../backend && python3 -m pytest tests/integration/test_render_e2e.py -v -m "" --no-header
```

Expected: PASS (or `SKIP` with a clear reason if the test project isn't present — this is fine, it will pass once the project + deps exist).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_render_e2e.py
git commit -m "test(render-service): end-to-end test rendering 7zn274s3/users/list"
```

---

## Task 15: Editor-side render-service client + Preview tab

**Files:**
- Create: `frontend/src/components/schema-editor/PreviewTab.tsx`
- Create: `frontend/src/lib/render-service-client.ts`
- Modify: `frontend/src/components/schema-editor/SchemaEditorPanel.tsx`

- [ ] **Step 1: Implement render-service-client.ts**

```ts
// frontend/src/lib/render-service-client.ts
const RENDER_SERVICE_URL =
  process.env.NEXT_PUBLIC_RENDER_SERVICE_URL ?? "http://localhost:6502";

export interface RenderResponse {
  pngBase64: string;
  pngBytes: number;
  htmlSnapshot: string;
  accessibilityTree: string;
  renderTimeMs: number;
  consoleWarnings: string[];
  networkFailures: string[];
}

export async function renderPage(
  projectId: string,
  pageRoute: string,
  viewport: "mobile" | "tablet" | "desktop" = "desktop",
): Promise<RenderResponse | null> {
  try {
    const r = await fetch(`${RENDER_SERVICE_URL}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId, pageRoute, viewport }),
    });
    if (!r.ok) return null;
    return (await r.json()) as RenderResponse;
  } catch {
    return null;
  }
}
```

- [ ] **Step 2: Implement PreviewTab.tsx**

```tsx
// frontend/src/components/schema-editor/PreviewTab.tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, Image as ImageIcon, Smartphone, Tablet, Monitor } from "lucide-react";
import { useState } from "react";
import { renderPage } from "@/lib/render-service-client";

type Viewport = "mobile" | "tablet" | "desktop";

interface PreviewTabProps {
  projectId: string;       // The short_id (e.g. "7zn274s3")
  pageRoute: string;        // E.g. "/users/list"
}

export function PreviewTab({ projectId, pageRoute }: PreviewTabProps) {
  const [viewport, setViewport] = useState<Viewport>("desktop");
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["render", projectId, pageRoute, viewport],
    queryFn: () => renderPage(projectId, pageRoute, viewport),
    staleTime: 60_000,
  });

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Preview
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={() => setViewport("mobile")}
            className={`flex h-7 w-7 items-center justify-center rounded ${viewport === "mobile" ? "bg-muted" : ""}`}
            title="Mobile"
          >
            <Smartphone className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setViewport("tablet")}
            className={`flex h-7 w-7 items-center justify-center rounded ${viewport === "tablet" ? "bg-muted" : ""}`}
            title="Tablet"
          >
            <Tablet className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setViewport("desktop")}
            className={`flex h-7 w-7 items-center justify-center rounded ${viewport === "desktop" ? "bg-muted" : ""}`}
            title="Desktop"
          >
            <Monitor className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => refetch()}
            className="ml-2 px-2 py-1 text-xs rounded border hover:bg-muted"
          >
            Refresh
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-auto bg-muted/30 p-4">
        {(isLoading || isFetching) && (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            <span className="text-sm">Rendering…</span>
          </div>
        )}
        {!isFetching && error && (
          <div className="text-sm text-destructive">Render service error.</div>
        )}
        {!isFetching && data && (
          <div className="flex justify-center">
            <img
              alt={`Render of ${pageRoute}`}
              src={`data:image/png;base64,${data.pngBase64}`}
              className="max-w-full rounded shadow"
            />
          </div>
        )}
        {!isFetching && data === null && (
          <div className="flex h-full flex-col items-center justify-center text-sm text-muted-foreground">
            <ImageIcon className="mb-2 h-6 w-6" />
            Render service unreachable. Start it with{" "}
            <code className="ml-1 rounded bg-muted px-1">python -m services.render_service</code>.
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Wire PreviewTab into SchemaEditorPanel**

Read `frontend/src/components/schema-editor/SchemaEditorPanel.tsx`. Locate the existing tab list (Pages, Components, Properties). Add a "Preview" tab adjacent. Below is the pattern to follow — adapt the exact JSX to the existing file's structure:

```tsx
// inside SchemaEditorPanel, alongside the existing editor/columns:
import { PreviewTab } from "./PreviewTab";

// In the tab strip JSX (find where tabs like "Pages" / "Editor" are rendered):
<button onClick={() => setActiveSubTab("preview")}>Preview</button>

// In the tab body:
{activeSubTab === "preview" && currentPage && (
  <PreviewTab projectId={project.short_id} pageRoute={currentPage.route} />
)}
```

If `SchemaEditorPanel` does not already track sub-tab state, add a `useState<"editor" | "preview">("editor")`.

- [ ] **Step 4: Manual smoke test**

```bash
# Terminal 1: start the scaffold
cd apps/render-scaffold && npm run dev &
# Terminal 2: start the render service
cd backend && python3 -m services.render_service &
# Terminal 3: rebuild + restart frontend
cd packages/editor && npx tsc
cd ../../frontend && rm -rf .next/cache && npm run dev -- -p 6501 &
# Open the schema editor for project 7zn274s3, click Preview tab — screenshot should appear.
```

Expected: screenshot of `/users/list` displayed in the Preview tab.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/render-service-client.ts frontend/src/components/schema-editor/PreviewTab.tsx frontend/src/components/schema-editor/SchemaEditorPanel.tsx
git commit -m "feat(editor): Preview tab fetching screenshots from render-service"
```

---

## Task 16: Backend debug endpoint for one-shot rendering

**Files:**
- Modify: `backend/routers/_debug_schema.py`

- [ ] **Step 1: Add the endpoint**

Read `backend/routers/_debug_schema.py`. After the existing `recompile-tokens` endpoint, append:

```python
import base64
import httpx


@router.post("/api/_debug/render-page/{short_id}")
async def render_page_debug(short_id: str, page_route: str, viewport: str = "desktop"):
    """Trigger a single page render via the render-service. Useful for manual
    testing without going through the editor UI.

    Query params:
      page_route: schema route, e.g. /users/list
      viewport:  mobile | tablet | desktop  (default desktop)
    """
    if viewport not in ("mobile", "tablet", "desktop"):
        raise HTTPException(400, "viewport must be one of mobile|tablet|desktop")

    render_url = "http://localhost:6502/render"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(render_url, json={
                "projectId": short_id, "pageRoute": page_route, "viewport": viewport,
            })
        except httpx.RequestError as e:
            raise HTTPException(503, f"render-service unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    body = r.json()
    return {
        "short_id": short_id,
        "page_route": page_route,
        "viewport": viewport,
        "render_time_ms": body["renderTimeMs"],
        "png_bytes": body["pngBytes"],
        # Truncate the data URI to keep the response small
        "png_data_uri_preview": f"data:image/png;base64,{body['pngBase64'][:200]}…",
    }
```

- [ ] **Step 2: Manual test**

```bash
# Render-service must be running (Task 13)
curl -X POST 'http://localhost:6500/api/_debug/render-page/7zn274s3?page_route=/users/list&viewport=desktop' | python3 -m json.tool
```

Expected: JSON with `render_time_ms` and `png_bytes` > 1000.

- [ ] **Step 3: Commit**

```bash
git add backend/routers/_debug_schema.py
git commit -m "feat(debug): /api/_debug/render-page/<short_id> for manual render test"
```

---

## Task 17: Vision evaluator types + prompt skeleton

**Files:**
- Create: `backend/services/vision_evaluator/__init__.py`
- Create: `backend/services/vision_evaluator/types.py`
- Create: `backend/services/vision_evaluator/prompt.py`

- [ ] **Step 1: Implement types.py**

```python
# backend/services/vision_evaluator/types.py
"""Pydantic models matching the spec's Critique JSON shape exactly."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Severity = Literal["high", "medium", "low"]
Axis = Literal[
    "visualPolish",
    "domainFeel",
    "informationDensity",
    "componentCoherence",
    "brandReflection",
]


class Scores(BaseModel):
    visualPolish: float = Field(ge=0, le=10)
    domainFeel: float = Field(ge=0, le=10)
    informationDensity: float = Field(ge=0, le=10)
    componentCoherence: float = Field(ge=0, le=10)
    brandReflection: float = Field(ge=0, le=10)


class PatchOp(BaseModel):
    op: Literal["add", "replace", "remove", "move"]
    path: str
    value: object | None = None
    from_: str | None = Field(default=None, alias="from")


class Issue(BaseModel):
    severity: Severity
    axis: Axis
    nodeIdHint: str | None = None
    issue: str
    suggestion: str
    patchOp: PatchOp | None = None


class CompareToPrevious(BaseModel):
    improved: list[Axis] = Field(default_factory=list)
    regressed: list[Axis] = Field(default_factory=list)


class Critique(BaseModel):
    scores: Scores
    compositeScore: float = Field(ge=0, le=10)
    pass_: bool = Field(alias="pass")
    topIssues: list[Issue] = Field(default_factory=list, max_length=10)
    strengths: list[str] = Field(default_factory=list, max_length=5)
    designerApprovalRecommended: bool = False
    compareToPrevious: CompareToPrevious | None = None

    class Config:
        populate_by_name = True


# Composite weighting from the spec:
COMPOSITE_WEIGHTS: dict[Axis, float] = {
    "visualPolish": 0.25,
    "domainFeel": 0.25,
    "informationDensity": 0.15,
    "componentCoherence": 0.20,
    "brandReflection": 0.15,
}


def compute_composite(scores: Scores) -> float:
    total = sum(getattr(scores, axis) * weight for axis, weight in COMPOSITE_WEIGHTS.items())
    return round(total, 2)
```

- [ ] **Step 2: Implement prompt.py**

```python
# backend/services/vision_evaluator/prompt.py
"""Fixed system prompt + user-prompt template for the vision evaluator."""
from __future__ import annotations


SYSTEM_PROMPT = """\
You are a senior product designer reviewing a screenshot of a generated UI page.
Score it on a 5-axis rubric, identify high-impact issues, and recommend fixes
that target specific node IDs from data-node-id attributes.

Output STRICT JSON matching the provided schema. No prose outside the JSON.

THE RUBRIC (each axis 0-10):
  visualPolish      — typography hierarchy, alignment, whitespace, color harmony
  domainFeel        — does this page look like a {domain} app for {appName}?
  informationDensity— Goldilocks. 5 = just right for this page type.
  componentCoherence— do all components feel from one design system?
  brandReflection   — does the visual tone match the stated persona?

CALIBRATION ANCHORS:
  3 / 10 — bare structure, browser defaults, Lorem ipsum visible, broken
  5 / 10 — generic admin panel, nothing wrong, nothing memorable
  7 / 10 — solid shippable work, intentional spacing + hierarchy
  8 / 10 — premium polish, identity is visible
  9-10  — Linear / Notion / Stripe tier; reserve for outstanding craft

ISSUES MUST BE ACTIONABLE. "Looks bad" is not an issue. "Hero CTAs are
visually identical, breaking primary/secondary hierarchy" is. Each issue
needs:
  - severity: high | medium | low
  - axis from the rubric
  - nodeIdHint from data-node-id when possible (else null)
  - concrete suggestion (ideally as RFC 6902 patchOp)

PASS GATE: pass=true iff compositeScore >= 8.0 AND no high-severity issues.
COMPOSITE: weighted mean — visualPolish 0.25, domainFeel 0.25,
informationDensity 0.15, componentCoherence 0.20, brandReflection 0.15.
"""


USER_PROMPT_TEMPLATE = """\
APP BRIEF:
  Domain: {domain}
  Name: {appName}
  Description: {description}
  Tone: {tone}

PAGE CONTEXT:
  Route: {route}
  Page type: {pageType}
  Role: {pageRole}
  Iteration: {iter}/{maxIter}

ATTACHED:
  - screenshot_desktop.png (1280x800)
  - accessibility_tree.txt

Score using the rubric. Return strict JSON.
"""


def build_user_prompt(
    *,
    domain: str,
    app_name: str,
    description: str,
    tone: str,
    route: str,
    page_type: str,
    page_role: str,
    iteration: int = 0,
    max_iter: int = 1,
) -> str:
    return USER_PROMPT_TEMPLATE.format(
        domain=domain,
        appName=app_name,
        description=description,
        tone=tone,
        route=route,
        pageType=page_type,
        pageRole=page_role,
        iter=iteration,
        maxIter=max_iter,
    )
```

- [ ] **Step 3: Implement __init__.py**

```python
# backend/services/vision_evaluator/__init__.py
from .types import Critique, Issue, Scores, PatchOp, COMPOSITE_WEIGHTS, compute_composite
from .prompt import SYSTEM_PROMPT, build_user_prompt

__all__ = [
    "Critique", "Issue", "Scores", "PatchOp",
    "COMPOSITE_WEIGHTS", "compute_composite",
    "SYSTEM_PROMPT", "build_user_prompt",
]
```

- [ ] **Step 4: Verify imports work**

```bash
cd backend && python3 -c "from services.vision_evaluator import Critique, SYSTEM_PROMPT, build_user_prompt; print('imports ok')"
```

Expected: `imports ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/services/vision_evaluator/__init__.py backend/services/vision_evaluator/types.py backend/services/vision_evaluator/prompt.py
git commit -m "feat(vision-evaluator): types + prompt skeleton"
```

---

## Task 18: Vision evaluator output validator

**Files:**
- Create: `backend/services/vision_evaluator/validator.py`
- Create: `backend/tests/services/test_vision_validator.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_vision_validator.py
import json

import pytest

from services.vision_evaluator.validator import parse_critique_json, ValidationError


VALID_CRITIQUE = {
    "scores": {
        "visualPolish": 7, "domainFeel": 6, "informationDensity": 5,
        "componentCoherence": 7, "brandReflection": 6,
    },
    "compositeScore": 6.4,
    "pass": False,
    "topIssues": [
        {
            "severity": "medium",
            "axis": "informationDensity",
            "nodeIdHint": "stats-grid",
            "issue": "Only 2 MetricTiles — too sparse",
            "suggestion": "Add Avg Duration tile.",
        }
    ],
    "strengths": ["Hero structure is solid"],
    "designerApprovalRecommended": False,
}


def test_valid_payload_parses():
    c = parse_critique_json(json.dumps(VALID_CRITIQUE))
    assert c.compositeScore == 6.4
    assert c.pass_ is False
    assert len(c.topIssues) == 1


def test_missing_required_field_raises():
    bad = {**VALID_CRITIQUE}
    del bad["scores"]
    with pytest.raises(ValidationError):
        parse_critique_json(json.dumps(bad))


def test_score_out_of_range_raises():
    bad = json.loads(json.dumps(VALID_CRITIQUE))
    bad["scores"]["visualPolish"] = 11
    with pytest.raises(ValidationError):
        parse_critique_json(json.dumps(bad))


def test_invalid_json_raises():
    with pytest.raises(ValidationError):
        parse_critique_json("not json at all")


def test_extra_unknown_keys_are_tolerated():
    extra = {**VALID_CRITIQUE, "reasoning": "I think therefore"}
    c = parse_critique_json(json.dumps(extra))
    assert c.compositeScore == 6.4
```

- [ ] **Step 2: Run, verify failure**

```bash
cd backend && python3 -m pytest tests/services/test_vision_validator.py -v
```

Expected: FAIL with import error.

- [ ] **Step 3: Implement validator.py**

```python
# backend/services/vision_evaluator/validator.py
"""Strict JSON parsing + Pydantic validation for vision evaluator responses."""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .types import Critique


class ValidationError(Exception):
    """Raised when a model response can't be parsed into a Critique."""


def parse_critique_json(text: str) -> Critique:
    """Parse a JSON string into a Critique, raising ValidationError on any
    problem. The model is expected to emit strict JSON; if it doesn't, the
    caller can retry with a fixup prompt."""
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValidationError(f"invalid JSON: {e}") from e
    try:
        return Critique.model_validate(payload)
    except PydanticValidationError as e:
        raise ValidationError(f"shape mismatch: {e}") from e
```

- [ ] **Step 4: Run, verify pass**

```bash
cd backend && python3 -m pytest tests/services/test_vision_validator.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/vision_evaluator/validator.py backend/tests/services/test_vision_validator.py
git commit -m "feat(vision-evaluator): strict JSON validator with Pydantic"
```

---

## Task 19: Vision evaluator — Anthropic API wrapper (mocked)

**Files:**
- Create: `backend/services/vision_evaluator/evaluator.py`
- Create: `backend/tests/services/test_vision_evaluator.py`

- [ ] **Step 1: Write the failing test (with mocked Anthropic SDK)**

```python
# backend/tests/services/test_vision_evaluator.py
"""Vision evaluator tests use a stubbed Anthropic client so they run offline."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from services.vision_evaluator.evaluator import evaluate_page, EvaluatorContext


VALID_RESPONSE = json.dumps({
    "scores": {
        "visualPolish": 7, "domainFeel": 6, "informationDensity": 5,
        "componentCoherence": 7, "brandReflection": 6,
    },
    "compositeScore": 6.4,
    "pass": False,
    "topIssues": [],
    "strengths": ["Hero is solid"],
    "designerApprovalRecommended": False,
})


def make_context(**overrides) -> EvaluatorContext:
    base = dict(
        domain="hr", app_name="Leave Management",
        description="manage time off", tone="trustworthy",
        route="/users/list", page_type="list",
        page_role="users come here to find a teammate",
        iteration=0, max_iter=3,
    )
    base.update(overrides)
    return EvaluatorContext(**base)


@pytest.mark.asyncio
async def test_evaluate_page_returns_critique_on_clean_response():
    with patch("services.vision_evaluator.evaluator._call_claude_vision",
               new=AsyncMock(return_value=VALID_RESPONSE)):
        c = await evaluate_page(
            png_bytes=b"\x89PNG\r\n\x1a\n",  # minimal PNG header for the call
            a11y_tree="- Stack 'root'",
            ctx=make_context(),
        )
        assert c.compositeScore == 6.4
        assert c.pass_ is False


@pytest.mark.asyncio
async def test_evaluate_page_retries_once_on_invalid_json():
    bad_then_good = AsyncMock(side_effect=["not json at all", VALID_RESPONSE])
    with patch("services.vision_evaluator.evaluator._call_claude_vision", new=bad_then_good):
        c = await evaluate_page(
            png_bytes=b"\x89PNG\r\n\x1a\n",
            a11y_tree="- Stack",
            ctx=make_context(),
        )
        assert c.compositeScore == 6.4
        assert bad_then_good.call_count == 2


@pytest.mark.asyncio
async def test_evaluate_page_raises_after_two_invalid_responses():
    always_bad = AsyncMock(return_value="still not json")
    with patch("services.vision_evaluator.evaluator._call_claude_vision", new=always_bad):
        with pytest.raises(Exception):
            await evaluate_page(
                png_bytes=b"\x89PNG\r\n\x1a\n",
                a11y_tree="- Stack",
                ctx=make_context(),
            )
        assert always_bad.call_count == 2
```

- [ ] **Step 2: Run, verify failure**

```bash
cd backend && python3 -m pytest tests/services/test_vision_evaluator.py -v
```

Expected: FAIL with import error.

- [ ] **Step 3: Implement evaluator.py**

```python
# backend/services/vision_evaluator/evaluator.py
"""High-level evaluate_page() — wraps the Anthropic vision call + validation +
one retry on parse failure."""
from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass

from anthropic import AsyncAnthropic

from .prompt import SYSTEM_PROMPT, build_user_prompt
from .types import Critique
from .validator import ValidationError, parse_critique_json


logger = logging.getLogger(__name__)


_MODEL = os.getenv("VISION_EVALUATOR_MODEL", "claude-sonnet-4-5-20250929")
_MAX_TOKENS = 4096


@dataclass
class EvaluatorContext:
    domain: str
    app_name: str
    description: str
    tone: str
    route: str
    page_type: str
    page_role: str
    iteration: int = 0
    max_iter: int = 3


async def _call_claude_vision(*, png_bytes: bytes, a11y_tree: str, ctx: EvaluatorContext) -> str:
    """Single Claude vision call returning raw response text. Tested by mocking
    this function — real network access only happens when not patched."""
    client = AsyncAnthropic()
    user_prompt = build_user_prompt(
        domain=ctx.domain, app_name=ctx.app_name, description=ctx.description,
        tone=ctx.tone, route=ctx.route, page_type=ctx.page_type, page_role=ctx.page_role,
        iteration=ctx.iteration, max_iter=ctx.max_iter,
    )
    message = await client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(png_bytes).decode("ascii"),
                }},
                {"type": "text", "text": f"{user_prompt}\n\nACCESSIBILITY TREE:\n{a11y_tree}"},
            ],
        }],
    )
    parts = []
    for block in message.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts)


async def evaluate_page(*, png_bytes: bytes, a11y_tree: str, ctx: EvaluatorContext) -> Critique:
    """Public entry point — call the vision model and parse the response.

    On the first invalid response, retry once with a fix-up message appended.
    On the second failure, raise ValidationError so the caller can decide
    whether to skip this page or abort the loop."""
    raw = await _call_claude_vision(png_bytes=png_bytes, a11y_tree=a11y_tree, ctx=ctx)
    try:
        return parse_critique_json(raw)
    except ValidationError as first_err:
        logger.warning("vision evaluator: first response invalid (%s); retrying once", first_err)
        raw_retry = await _call_claude_vision(png_bytes=png_bytes, a11y_tree=a11y_tree, ctx=ctx)
        return parse_critique_json(raw_retry)
```

Update `__init__.py`:

```python
from .evaluator import evaluate_page, EvaluatorContext
from .prompt import SYSTEM_PROMPT, build_user_prompt
from .types import Critique, Issue, Scores, PatchOp, COMPOSITE_WEIGHTS, compute_composite
from .validator import ValidationError, parse_critique_json

__all__ = [
    "evaluate_page", "EvaluatorContext",
    "Critique", "Issue", "Scores", "PatchOp",
    "COMPOSITE_WEIGHTS", "compute_composite",
    "SYSTEM_PROMPT", "build_user_prompt",
    "ValidationError", "parse_critique_json",
]
```

- [ ] **Step 4: Run, verify pass**

```bash
cd backend && python3 -m pytest tests/services/test_vision_evaluator.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/vision_evaluator/evaluator.py backend/services/vision_evaluator/__init__.py backend/tests/services/test_vision_evaluator.py
git commit -m "feat(vision-evaluator): Anthropic API wrapper + retry-once on invalid JSON"
```

---

## Task 20: Fidelity log writer

**Files:**
- Create: `backend/services/fidelity_log.py`
- Create: `backend/tests/services/test_fidelity_log.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_fidelity_log.py
import json
from pathlib import Path

from services.fidelity_log import append_fidelity_entry, read_fidelity_log


def test_append_creates_file_when_absent(tmp_path: Path):
    output_dir = tmp_path / "proj"
    output_dir.mkdir()
    append_fidelity_entry(
        output_dir=str(output_dir),
        page_path="users/list",
        score=7.4,
        issues=[{"severity": "medium", "issue": "sparse"}],
        iteration=0,
        passed=False,
    )
    log = read_fidelity_log(str(output_dir))
    assert "users/list" in log
    assert log["users/list"]["iterations"][0]["score"] == 7.4


def test_append_extends_existing_page_iterations(tmp_path: Path):
    output_dir = tmp_path / "proj"
    output_dir.mkdir()
    append_fidelity_entry(output_dir=str(output_dir), page_path="users/list", score=6.0,
                          issues=[], iteration=0, passed=False)
    append_fidelity_entry(output_dir=str(output_dir), page_path="users/list", score=8.1,
                          issues=[], iteration=1, passed=True)
    log = read_fidelity_log(str(output_dir))
    assert len(log["users/list"]["iterations"]) == 2
    assert log["users/list"]["final_score"] == 8.1
    assert log["users/list"]["final_iteration"] == 1


def test_separate_pages_kept_separate(tmp_path: Path):
    output_dir = tmp_path / "proj"
    output_dir.mkdir()
    append_fidelity_entry(output_dir=str(output_dir), page_path="a", score=5, issues=[], iteration=0, passed=False)
    append_fidelity_entry(output_dir=str(output_dir), page_path="b", score=8, issues=[], iteration=0, passed=True)
    log = read_fidelity_log(str(output_dir))
    assert set(log) == {"a", "b"}
```

- [ ] **Step 2: Run, verify failure**

```bash
cd backend && python3 -m pytest tests/services/test_fidelity_log.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement fidelity_log.py**

```python
# backend/services/fidelity_log.py
"""Append-only log of per-page fidelity scores written to
output/<id>/src/contracts/fidelity-log.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _log_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "src" / "contracts" / "fidelity-log.json"


def read_fidelity_log(output_dir: str | Path) -> dict[str, Any]:
    """Return the parsed log dict, or an empty dict if the file is absent."""
    p = _log_path(output_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def append_fidelity_entry(
    *,
    output_dir: str,
    page_path: str,
    score: float,
    issues: list[dict[str, Any]],
    iteration: int,
    passed: bool,
    patches: list[dict[str, Any]] | None = None,
) -> None:
    """Append an iteration entry for `page_path`. Creates the file/dir if
    absent. Updates `final_score` and `final_iteration` on every call."""
    p = _log_path(output_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    log = read_fidelity_log(output_dir)
    page_entry = log.setdefault(page_path, {"iterations": []})
    page_entry["iterations"].append({
        "iteration": iteration,
        "score": score,
        "issues": issues,
        "patches": patches or [],
        "pass": passed,
    })
    page_entry["final_score"] = score
    page_entry["final_iteration"] = iteration
    p.write_text(json.dumps(log, indent=2))
```

- [ ] **Step 4: Run, verify pass**

```bash
cd backend && python3 -m pytest tests/services/test_fidelity_log.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/fidelity_log.py backend/tests/services/test_fidelity_log.py
git commit -m "feat(fidelity): per-project fidelity-log.json writer"
```

---

## Task 21: Phase-13 single-shot scoring CLI/endpoint

**Files:**
- Create: `backend/routers/_debug_fidelity.py`
- Modify: `backend/main.py` — register the new router

- [ ] **Step 1: Implement _debug_fidelity.py**

```python
# backend/routers/_debug_fidelity.py
"""Debug endpoint: render + score a single page; append to fidelity log.

Phase-13 wiring — single-shot, no loop. Designer triggers it manually via
this endpoint or via the editor's CritiquePanel "regenerate with critique"
button (later)."""
from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException

from services.fidelity_log import append_fidelity_entry
from services.vision_evaluator import EvaluatorContext, evaluate_page


router = APIRouter()


def _output_dir(short_id: str) -> Path:
    return Path(__file__).resolve().parent.parent.parent / "output" / short_id


@router.post("/api/_debug/score-page/{short_id}")
async def score_page(
    short_id: str,
    page_route: str,
    page_path: str,
    domain: str = "general",
    app_name: str = "App",
    description: str = "",
    tone: str = "professional",
):
    """Render the page, score it, append to fidelity-log.json. Returns the
    structured critique."""
    output_dir = _output_dir(short_id)
    if not output_dir.exists():
        raise HTTPException(404, f"project {short_id} not found")

    # 1. Render via render-service
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(
                "http://localhost:6502/render",
                json={"projectId": short_id, "pageRoute": page_route, "viewport": "desktop"},
            )
        except httpx.RequestError as e:
            raise HTTPException(503, f"render-service unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    render = r.json()

    # 2. Decode PNG + a11y tree
    import base64
    png_bytes = base64.b64decode(render["pngBase64"])
    a11y_tree = render.get("accessibilityTree", "")

    # 3. Score via vision evaluator
    ctx = EvaluatorContext(
        domain=domain, app_name=app_name, description=description, tone=tone,
        route=page_route, page_type=page_path.split("/")[-1] if "/" in page_path else "page",
        page_role=f"users navigate to {page_route}",
        iteration=0, max_iter=1,
    )
    critique = await evaluate_page(png_bytes=png_bytes, a11y_tree=a11y_tree, ctx=ctx)

    # 4. Append to fidelity log
    append_fidelity_entry(
        output_dir=str(output_dir),
        page_path=page_path,
        score=critique.compositeScore,
        issues=[i.model_dump() for i in critique.topIssues],
        iteration=0,
        passed=critique.pass_,
    )

    return critique.model_dump(by_alias=True)
```

- [ ] **Step 2: Register the router in main.py**

Read `backend/main.py`. Find the existing block that imports and registers routers (around the `_debug_schema_router` line). Add:

```python
from routers._debug_fidelity import router as _debug_fidelity_router
app.include_router(_debug_fidelity_router)
```

- [ ] **Step 3: Manual test**

```bash
# Render-service running
curl -X POST 'http://localhost:6500/api/_debug/score-page/7zn274s3?page_route=/users/list&page_path=users/list&domain=hr&app_name=Leave%20Management&description=Manage%20time%20off' | python3 -m json.tool
```

Expected: structured critique JSON with `compositeScore`, `pass`, `topIssues`, `strengths`. The `output/7zn274s3/src/contracts/fidelity-log.json` file should now contain a `users/list` entry.

- [ ] **Step 4: Commit**

```bash
git add backend/routers/_debug_fidelity.py backend/main.py
git commit -m "feat(debug): /api/_debug/score-page renders + scores + logs a page"
```

---

## Task 22: Editor CritiquePanel + FidelityScoreBadge

**Files:**
- Create: `frontend/src/components/schema-editor/FidelityScoreBadge.tsx`
- Create: `frontend/src/components/schema-editor/CritiquePanel.tsx`
- Create: `frontend/src/lib/fidelity-client.ts`

- [ ] **Step 1: Implement fidelity-client.ts**

```ts
// frontend/src/lib/fidelity-client.ts
import { api } from "@/lib/api";

export interface CritiquePatch {
  op: "add" | "replace" | "remove" | "move";
  path: string;
  value?: unknown;
  from?: string;
}
export interface CritiqueIssue {
  severity: "high" | "medium" | "low";
  axis: string;
  nodeIdHint: string | null;
  issue: string;
  suggestion: string;
  patchOp?: CritiquePatch | null;
}
export interface Critique {
  scores: Record<string, number>;
  compositeScore: number;
  pass: boolean;
  topIssues: CritiqueIssue[];
  strengths: string[];
  designerApprovalRecommended: boolean;
}

export async function scorePage(
  shortId: string,
  pageRoute: string,
  pagePath: string,
  context: { domain: string; appName: string; description: string; tone: string },
): Promise<Critique> {
  const params = new URLSearchParams({
    page_route: pageRoute,
    page_path: pagePath,
    domain: context.domain,
    app_name: context.appName,
    description: context.description,
    tone: context.tone,
  });
  return api.post<Critique>(`/api/_debug/score-page/${shortId}?${params}`);
}
```

- [ ] **Step 2: Implement FidelityScoreBadge.tsx**

```tsx
// frontend/src/components/schema-editor/FidelityScoreBadge.tsx
export function FidelityScoreBadge({ score }: { score: number | null }) {
  if (score === null) {
    return (
      <span className="rounded-full border px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
        unscored
      </span>
    );
  }
  const tone = score >= 8 ? "bg-emerald-100 text-emerald-800" :
               score >= 6 ? "bg-amber-100 text-amber-800" :
                            "bg-rose-100 text-rose-800";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone}`}>
      {score.toFixed(1)}
    </span>
  );
}
```

- [ ] **Step 3: Implement CritiquePanel.tsx**

```tsx
// frontend/src/components/schema-editor/CritiquePanel.tsx
"use client";

import { useMutation } from "@tanstack/react-query";
import { Loader2, AlertTriangle, CheckCircle2 } from "lucide-react";
import { scorePage, type Critique } from "@/lib/fidelity-client";
import { FidelityScoreBadge } from "./FidelityScoreBadge";

interface CritiquePanelProps {
  shortId: string;
  pageRoute: string;
  pagePath: string;
  context: { domain: string; appName: string; description: string; tone: string };
}

export function CritiquePanel({ shortId, pageRoute, pagePath, context }: CritiquePanelProps) {
  const m = useMutation<Critique>({
    mutationFn: () => scorePage(shortId, pageRoute, pagePath, context),
  });

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b px-4 py-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Fidelity Score
        </span>
        <FidelityScoreBadge score={m.data ? m.data.compositeScore : null} />
        <button
          type="button"
          onClick={() => m.mutate()}
          disabled={m.isPending}
          className="ml-auto rounded border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
        >
          {m.isPending ? "Scoring..." : "Score now"}
        </button>
      </div>
      <div className="flex-1 overflow-auto p-4">
        {m.isPending && (
          <div className="flex items-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Rendering and evaluating…
          </div>
        )}
        {m.error && <div className="text-sm text-destructive">{(m.error as Error).message}</div>}
        {m.data && (
          <div className="space-y-4 text-sm">
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(m.data.scores).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between rounded border px-3 py-1.5">
                  <span className="capitalize text-xs text-muted-foreground">{k.replace(/([A-Z])/g, " $1").trim()}</span>
                  <span className="font-mono">{Number(v).toFixed(1)}</span>
                </div>
              ))}
            </div>
            {m.data.topIssues.length > 0 && (
              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Top Issues</h4>
                <ul className="space-y-2">
                  {m.data.topIssues.map((i, idx) => (
                    <li key={idx} className="rounded border p-3">
                      <div className="mb-1 flex items-center gap-2">
                        <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
                        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                          {i.severity} · {i.axis}
                        </span>
                        {i.nodeIdHint && (
                          <code className="ml-auto rounded bg-muted px-1.5 py-0.5 text-[11px]">{i.nodeIdHint}</code>
                        )}
                      </div>
                      <div className="text-foreground">{i.issue}</div>
                      <div className="mt-1 text-xs text-muted-foreground">→ {i.suggestion}</div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {m.data.strengths.length > 0 && (
              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Strengths</h4>
                <ul className="space-y-1">
                  {m.data.strengths.map((s, idx) => (
                    <li key={idx} className="flex items-start gap-2">
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 text-emerald-600" />
                      <span>{s}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        {!m.isPending && !m.data && !m.error && (
          <div className="text-sm text-muted-foreground">
            Click <strong>Score now</strong> to render and evaluate this page.
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire CritiquePanel as a sub-tab in SchemaEditorPanel**

Read `frontend/src/components/schema-editor/SchemaEditorPanel.tsx`. Add CritiquePanel as a third sub-tab alongside Editor and Preview. Pattern (adapt to existing structure):

```tsx
import { CritiquePanel } from "./CritiquePanel";

// In tab strip:
<button onClick={() => setActiveSubTab("critique")}>Score</button>

// In tab body:
{activeSubTab === "critique" && currentPage && (
  <CritiquePanel
    shortId={project.short_id}
    pageRoute={currentPage.route}
    pagePath={currentPage.path}
    context={{
      domain: project.domain ?? "general",
      appName: project.name,
      description: project.description ?? "",
      tone: project.tone ?? "professional",
    }}
  />
)}
```

- [ ] **Step 5: Manual smoke test**

```bash
# All services running (scaffold, render-service, backend, frontend)
# Open the editor, navigate to a page, click "Score" tab, click "Score now"
# Verify: spinner → critique appears with scores grid + issues + strengths
```

Expected: critique displayed; `fidelity-log.json` updated for the project.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/fidelity-client.ts frontend/src/components/schema-editor/FidelityScoreBadge.tsx frontend/src/components/schema-editor/CritiquePanel.tsx frontend/src/components/schema-editor/SchemaEditorPanel.tsx
git commit -m "feat(editor): Score sub-tab with FidelityScoreBadge + CritiquePanel"
```

---

## Task 23: Config flags

**Files:**
- Modify: `backend/config.py` — add fidelity flags

- [ ] **Step 1: Append to config.py**

Read `backend/config.py`. After the existing `FIDELITY_MODE_ENABLED` block, append:

```python
# ---------------------------------------------------------------------------
# Fidelity render loop (Phase 12.5 + 13)
# ---------------------------------------------------------------------------

# Render service URL (where the backend reaches the Playwright-driven service)
RENDER_SERVICE_URL = os.getenv("RENDER_SERVICE_URL", "http://localhost:6502")

# Scaffold runtime URL (where the render service drives Playwright at)
RENDER_SCAFFOLD_URL = os.getenv("RENDER_SCAFFOLD_URL", "http://localhost:6503")

# Per-render timeout, ms
RENDER_TIMEOUT_MS = int(os.getenv("RENDER_TIMEOUT_MS", "15000"))

# Phase 12.5: render-only feature flag (Preview tab + debug endpoints)
FIDELITY_RENDER_ENABLED = os.getenv("FIDELITY_RENDER_ENABLED", "true").strip().lower() not in {"false", "0", "no", "off", ""}

# Phase 13: single-shot scoring feature flag (CritiquePanel + score endpoint)
FIDELITY_SCORING_ENABLED = os.getenv("FIDELITY_SCORING_ENABLED", "true").strip().lower() not in {"false", "0", "no", "off", ""}
```

- [ ] **Step 2: Verify import**

```bash
cd backend && python3 -c "from config import FIDELITY_RENDER_ENABLED, FIDELITY_SCORING_ENABLED, RENDER_SERVICE_URL, RENDER_SCAFFOLD_URL; print('flags ok')"
```

Expected: `flags ok`.

- [ ] **Step 3: Gate the score-page endpoint behind the flag**

Modify `backend/routers/_debug_fidelity.py`. At the top of `score_page()`:

```python
from config import FIDELITY_SCORING_ENABLED

# ...

@router.post("/api/_debug/score-page/{short_id}")
async def score_page(...):
    if not FIDELITY_SCORING_ENABLED:
        raise HTTPException(403, "Fidelity scoring disabled (set FIDELITY_SCORING_ENABLED=true)")
    # ... existing body
```

- [ ] **Step 4: Commit**

```bash
git add backend/config.py backend/routers/_debug_fidelity.py
git commit -m "feat(config): FIDELITY_RENDER_ENABLED + FIDELITY_SCORING_ENABLED flags"
```

---

## Task 24: Calibration anchor screenshots + critiques

**Files:**
- Create: `backend/services/vision_evaluator/anchors/anchor_3.png` (placeholder)
- Create: `backend/services/vision_evaluator/anchors/anchor_3.json`
- Create: `backend/services/vision_evaluator/anchors/anchor_6.png` (placeholder)
- Create: `backend/services/vision_evaluator/anchors/anchor_6.json`
- Create: `backend/services/vision_evaluator/anchors/anchor_8.png` (placeholder)
- Create: `backend/services/vision_evaluator/anchors/anchor_8.json`

- [ ] **Step 1: Create an anchor placeholder generator**

Create `backend/services/vision_evaluator/anchors/__init__.py`:

```python
# Anchors are screenshot+critique pairs that can be sent as few-shot
# examples to calibrate the vision evaluator. Real anchors should be
# captured from rendered example pages — see docs/superpowers/specs
# for the canonical pages.
```

For Step 1, create the JSON critiques (referenced verbatim from the spec).

`anchor_3.json`:

```json
{
  "scores": {
    "visualPolish": 2, "domainFeel": 3, "informationDensity": 4,
    "componentCoherence": 2, "brandReflection": 1
  },
  "compositeScore": 2.5,
  "pass": false,
  "topIssues": [
    {
      "severity": "high",
      "axis": "visualPolish",
      "nodeIdHint": null,
      "issue": "Page has no header / Hero — opens directly into a raw table with no context.",
      "suggestion": "Add a Hero with eyebrow, headline, subhead, and a primary CTA."
    },
    {
      "severity": "high",
      "axis": "componentCoherence",
      "nodeIdHint": "users-table",
      "issue": "Table uses browser defaults — visible black borders, system fonts.",
      "suggestion": "Wrap in a Card; switch to TableSortable; apply default StyleSlot with shadow.sm and radius.lg."
    }
  ],
  "strengths": [],
  "designerApprovalRecommended": false
}
```

`anchor_6.json`:

```json
{
  "scores": {
    "visualPolish": 7, "domainFeel": 6, "informationDensity": 5,
    "componentCoherence": 7, "brandReflection": 6
  },
  "compositeScore": 6.4,
  "pass": false,
  "topIssues": [
    {
      "severity": "medium",
      "axis": "informationDensity",
      "nodeIdHint": "stats-grid",
      "issue": "Only 2 MetricTiles — page feels sparse for a list/dashboard hybrid.",
      "suggestion": "Add 'Avg Duration' and 'Approval Rate' tiles; switch grid to columns=4."
    },
    {
      "severity": "medium",
      "axis": "domainFeel",
      "nodeIdHint": "requests-table",
      "issue": "Status column is plain text — a leave-management app expects color-coded badges.",
      "suggestion": "Replace status text cell with Badge bound to {{item.status}}."
    }
  ],
  "strengths": [
    "Hero structure is solid — eyebrow, headline, CTA all present",
    "Components feel from one design system"
  ],
  "designerApprovalRecommended": false
}
```

`anchor_8.json`:

```json
{
  "scores": {
    "visualPolish": 9, "domainFeel": 8, "informationDensity": 8,
    "componentCoherence": 9, "brandReflection": 8
  },
  "compositeScore": 8.4,
  "pass": true,
  "topIssues": [
    {
      "severity": "low",
      "axis": "informationDensity",
      "nodeIdHint": "advisor-grid",
      "issue": "Cards show 4 fields each — could carry a 5th field without feeling crowded.",
      "suggestion": "Add a small Badge bound to {{item.monthChange}} with a +/- arrow."
    }
  ],
  "strengths": [
    "Hero gradient + typography hierarchy is portfolio-tier",
    "MetricTile row with deltas + trends communicates motion at a glance",
    "Mobile composition stacks cleanly with no orphan elements"
  ],
  "designerApprovalRecommended": false
}
```

- [ ] **Step 2: Generate placeholder PNGs (1x1 transparent — real screenshots come from rendering anchor pages)**

Run from a Python REPL or as a one-off script:

```bash
cd backend
python3 - <<'EOF'
import base64
from pathlib import Path

# 1x1 transparent PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)
for n in (3, 6, 8):
    Path(f"services/vision_evaluator/anchors/anchor_{n}.png").write_bytes(PNG)
print("placeholder PNGs written")
EOF
```

- [ ] **Step 3: Sanity-check anchors load**

```bash
cd backend
python3 -c "
import json
from pathlib import Path
for n in (3, 6, 8):
    j = json.loads(Path(f'services/vision_evaluator/anchors/anchor_{n}.json').read_text())
    print(f'anchor_{n}: composite={j[\"compositeScore\"]}, issues={len(j[\"topIssues\"])}, strengths={len(j[\"strengths\"])}')
"
```

Expected:
```
anchor_3: composite=2.5, issues=2, strengths=0
anchor_6: composite=6.4, issues=2, strengths=2
anchor_8: composite=8.4, issues=1, strengths=3
```

- [ ] **Step 4: Commit**

```bash
git add backend/services/vision_evaluator/anchors
git commit -m "feat(vision-evaluator): calibration anchors at scores 3 / 6 / 8"
```

NOTE: PNG placeholders are intentional — replacing them with real screenshots is a follow-up task once a stable render pipeline exists. The JSON anchors are the load-bearing part; the PNG placeholders are what the evaluator currently sees as exemplars.

---

## Task 25: Documentation update

**Files:**
- Create: `docs/render-service.md`

- [ ] **Step 1: Write the doc**

```markdown
# Render Service & Fidelity Scoring

## Architecture

Three processes:

1. **render-scaffold** (Next.js, port 6503) — minimal app that renders any
   project's schemas via `/p/<projectId>/<page-route>`. Reads schemas from
   `output/<id>/src/schemas/` and tokens from
   `output/<id>/src/theme/tokens.custom.json`.

2. **render-service** (FastAPI + Playwright, port 6502) — drives Playwright
   at the scaffold and returns PNGs + a11y trees.

3. **vision-evaluator** (in-process Python lib, no separate service) — calls
   Claude vision with a fixed rubric, returns structured critique JSON.

## Running locally

```bash
# Terminal 1: scaffold
cd apps/render-scaffold && npm install --legacy-peer-deps && npm run dev

# Terminal 2: render-service
cd backend && python3 -m playwright install chromium  # one-time
cd backend && python3 -m services.render_service

# Terminal 3: backend (already integrated)
cd backend && python3 -m uvicorn main:app --port 6500 --reload

# Terminal 4: frontend
cd frontend && npm run dev -- -p 6501
```

## Endpoints

- `GET  http://localhost:6502/health` — render service liveness
- `POST http://localhost:6502/render` — render a single page (returns base64 PNG)
- `DELETE http://localhost:6502/cache` — invalidate cached renders

Backend debug endpoints (require ANTHROPIC_API_KEY):

- `POST /api/_debug/render-page/<short_id>?page_route=/x&viewport=desktop`
- `POST /api/_debug/score-page/<short_id>?page_route=/x&page_path=x/y&domain=hr&...`

## Editor UI

The schema editor's right panel has three sub-tabs:
- **Editor** — the existing visual / code editor
- **Preview** — fetches a screenshot from the render service
- **Score** — runs the vision evaluator + displays the structured critique

## Configuration

Environment variables (read by `backend/config.py`):

- `FIDELITY_RENDER_ENABLED` (default `true`) — gates the Preview tab + render endpoint
- `FIDELITY_SCORING_ENABLED` (default `true`) — gates the Score tab + score endpoint
- `RENDER_SERVICE_URL` (default `http://localhost:6502`)
- `RENDER_SCAFFOLD_URL` (default `http://localhost:6503`)
- `VISION_EVALUATOR_MODEL` (default `claude-sonnet-4-5-20250929`)

## Cost notes

Single-shot scoring: roughly $0.03–0.05 per page (one Claude vision call).
A 20-page project costs ~$0.60–$1.00 to fully score once.

## Troubleshooting

- **Preview shows "Render service unreachable"** — check that `python3 -m services.render_service` is running on port 6502.
- **Render returns 422 with "navigation failed"** — usually means the scaffold isn't running on port 6503, or the project's schema file doesn't exist.
- **Vision evaluator raises ValidationError** — the model's response didn't match the Pydantic schema. The evaluator already retries once; persistent failures usually indicate the prompt needs tuning.
```

- [ ] **Step 2: Commit**

```bash
git add docs/render-service.md
git commit -m "docs: render-service + fidelity scoring runbook"
```

---

## Self-review checklist

Run this after the last task lands, before declaring the plan done.

1. **Spec coverage:**
   - § Render service contract → Tasks 11, 12, 13 ✓
   - § Vision evaluator contract → Tasks 17, 18, 19, 24 ✓
   - § Fixtures architecture → Tasks 7, 8, 9, 10 ✓
   - § Scaffold runtime → Tasks 1, 2, 3, 4, 5, 6 ✓
   - § Phased rollout (Phase 12.5 + 13) → Tasks 1–25 ✓
   - § Failure modes — fixtures fall-through, retry-on-invalid-JSON, render timeout 422 → Tasks 7, 18, 13 ✓
   - § Patch agent + closed loop (Phase 14) → DEFERRED to a follow-up plan; explicitly out of scope here
   - § Reference grounding (Phase 15) → DEFERRED to a follow-up plan

2. **Placeholder scan:** No "TODO", "TBD", "fill in details", "add error handling" floating in any task. Anchor PNGs are intentionally placeholder; that's documented in Task 24 as a follow-up.

3. **Type consistency:**
   - `RenderRequest` shape (Task 13) matches the JSON sent by `renderPage` (Task 15) and `score_page` (Task 21) ✓
   - `Critique` shape (Task 17) is the same in `parse_critique_json` (Task 18), `evaluate_page` (Task 19), and the editor's TypeScript type (Task 22) ✓
   - `FieldHint` (Task 7) is the same in `generate_record` (Task 8) and `provide_records` (Task 10) ✓
   - `RenderCache.make_key` accepts a `dict[str, Any]` everywhere (Task 12, used in Task 13) ✓

---

## Out of scope (deferred to follow-up plans)

- **Phase 14 — Closed loop with patch agent.** Spec describes; implementation is a separate plan.
- **Phase 15 — Reference grounding bank.** Curation effort, not a discrete code plan.
- **Phase 16 — Best-of-N parallel generation.** Optional optimisation.
- **Multi-viewport scoring.** Phase 13 starts desktop-only; mobile + tablet are a follow-up.
- **Real anchor screenshots.** Task 24 ships placeholder PNGs; capturing real anchors from rendered example pages requires the scaffold + a known set of anchor schemas, which can land separately.

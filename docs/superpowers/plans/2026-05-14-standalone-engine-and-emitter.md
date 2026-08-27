# Standalone Engine + App Emitter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the render-scaffold as the *runtime* for generated apps. Each generated app becomes a self-contained Next.js application that reads its own page schemas from disk and renders them through a packaged engine — deployable to Vercel/Netlify/anywhere without bundling our platform code. The render-scaffold survives only as a fast preview surface for the editor.

**Architecture:** Three workstreams in dependency order.

- **A** — Extract `@tentoroforge/engine`: a single npm package that exposes one React component (`<Engine schema={...} />`) and the data/binding/theme infrastructure it needs. Combines `@tentoroforge/renderer` + `@tentoroforge/library` + the data-interpolation layer scattered across the scaffold. Today these are three packages plus inline scaffold code — the generated app needs ONE dependency, not four.
- **B** — Standalone-app template + emitter: after the schema agents finish, write ~10 templated files (package.json, next.config.js, layout.tsx, [...slug]/page.tsx, etc.) into `output/<projectId>/`. Templated, not LLM-generated. Pin the engine version. After emission, the project is a runnable Next.js app via `npm install && npm run dev`.
- **C** — Editor wiring + export: the editor's preview keeps using the scaffold (fast iteration, no per-edit install). Add an export endpoint that returns the project as a tarball. Add a "Run locally" panel in the editor with the three commands users need.

**Tech Stack:** TypeScript (Zod, React, Next.js 15 app-router), tsup/tsc for engine bundling, Python (FastAPI) for the emitter step, pytest + vitest. No new external dependencies beyond what's already in the workspace.

**Spec:** This plan is its own spec — derived from the session 2026-05-14 conversation establishing that generated apps must be self-contained at runtime, with the rendering engine living inside the app rather than in a shared host.

---

## Background — what's missing today

The end-to-end validation completed today proved Pillar 2 works (typography, photos, layout, fidelity scoring). But it also exposed a structural gap: **generated apps cannot leave the development machine**. They live as `output/<projectId>/` directories that only render through `apps/render-scaffold` at `http://localhost:6503/p/<projectId>/<slug>`. The "app" is a bundle of JSON + CSS, not a Next.js project.

Concrete consequences:

1. **No export path.** Users can't download what they generated.
2. **No deploy path.** Users can't ship to Vercel/Netlify.
3. **The scaffold is a single point of failure.** A bad uncommitted change to `apps/render-scaffold` 500s every project (we saw this today — the schema package's mid-refactor state broke `z.discriminatedUnion` for all projects until we patched the scaffold defensively).
4. **No per-project versioning.** Today, projects always render against `main`'s scaffold code. Regenerating a project months later renders it against whatever the scaffold has become, which may be incompatible.
5. **The "two engines" architecture isn't expressed.** The user's original design has the rendering engine running INSIDE each generated app (as an installable package), with data + workflows handled by their own engines. Today everything lives in the scaffold.

This plan closes (1)(2)(4)(5) and reduces (3) to "a bad scaffold breaks editor preview, but generated apps keep working."

**Out of scope (deliberate):**

- Workflow engine packaging (separate plan — `backend/runtime/engine.py` extraction)
- Mobile target (RN/Expo) — same engine API can be retargeted later
- Real-database per-project storage (today's API routes use seeded fixtures; production-grade persistence is a separate workstream)
- Editor click-to-edit visual editing (Pillar 1, separate plan)
- Removing the render-scaffold entirely (it stays as the editor's preview surface — kept simple)

---

## File structure

### New files

```
packages/engine/
  package.json                       # name @tentoroforge/engine, exports field
  tsconfig.json
  tsup.config.ts                     # dual-target build (esm + cjs + types)
  README.md
  src/
    index.ts                         # public exports — <Engine>, <EngineProvider>
    Engine.tsx                       # the single component generated apps mount
    EngineProvider.tsx               # tokens + register + previewData context
    data/
      loader.ts                      # fetchDataSources(schema, baseUrl)
      interpolate.ts                 # Mustache {{path.to.value}} resolver
      expressions.ts                 # boolean expression evaluator for visibleIf
    types.ts                         # PageSchema, EngineProps, DataContext
  tests/
    engine.test.tsx
    loader.test.ts
    interpolate.test.ts

backend/templates/standalone-app/
  package.json.tmpl                  # deps incl. @tentoroforge/engine@<pinned>
  next.config.js
  tsconfig.json
  tailwind.config.ts
  postcss.config.js
  .gitignore
  src/
    app/
      layout.tsx                     # <EngineProvider> wraps {children}
      [...slug]/page.tsx             # ~15-line schema loader → <Engine>
      not-found.tsx
      globals.css.tmpl               # base; design_agent overwrites later

backend/services/
  app_emitter.py                     # writes the template into output_dir
  app_emitter_constants.py           # ENGINE_VERSION pin

backend/tests/services/
  test_app_emitter.py
```

### Modified files

```
apps/render-scaffold/src/components/SchemaRendererWrapper.tsx
  # Replace the inline 300-line dispatch with: import { Engine } from "@tentoroforge/engine"
  # After: the scaffold becomes a thin shell — auth/routing + load schema → <Engine>

apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx
  # Use the engine's loader, drop the inline dispatch

backend/routers/generate.py
  # After schema generation, call app_emitter.emit_standalone_app(output_dir, plan)

backend/routers/projects.py  (or wherever export lives — verify path)
  # New endpoint: GET /api/projects/{id}/export → tarball stream

frontend/src/components/schema-editor/  (or wherever preview lives)
  # Add "Run locally" panel with the three npm commands + an "Export tarball" button
```

### Public engine API surface (what generated apps import)

```ts
// src/app/[...slug]/page.tsx of a generated app
import { Engine } from "@tentoroforge/engine";

<Engine
  schema={pageSchema}                    // the loaded JSON
  designSpec={designSpec}                // palette, register, typography
  apiBaseUrl={process.env.NEXT_PUBLIC_API_URL ?? ""}  // empty = same-origin
/>;
```

```ts
// src/app/layout.tsx of a generated app
import { EngineProvider } from "@tentoroforge/engine";

<EngineProvider designSpec={designSpec}>
  {children}
</EngineProvider>;
```

That's the entire public surface. Internal data/binding/dispatch logic is hidden.

---

## Workstream A — Extract `@tentoroforge/engine`

### Task A1: Engine package skeleton

**Files:**
- Create: `packages/engine/package.json`
- Create: `packages/engine/tsconfig.json`
- Create: `packages/engine/tsup.config.ts`
- Create: `packages/engine/src/index.ts`
- Create: `packages/engine/README.md`

- [ ] **Step 1: Create the package directory + package.json**

```json
{
  "name": "@tentoroforge/engine",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "module": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": {
      "types": "./dist/index.d.ts",
      "import": "./dist/index.js",
      "require": "./dist/index.cjs"
    }
  },
  "files": ["dist"],
  "scripts": {
    "build": "tsup",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "peerDependencies": {
    "react": "^18.0.0 || ^19.0.0",
    "react-dom": "^18.0.0 || ^19.0.0"
  },
  "dependencies": {
    "@tentoroforge/library": "workspace:*",
    "@tentoroforge/renderer": "workspace:*",
    "@tentoroforge/schema": "workspace:*",
    "zod": "^3.23.0"
  },
  "devDependencies": {
    "@testing-library/react": "^14.0.0",
    "@types/react": "^18.0.0",
    "@vitejs/plugin-react": "^4.0.0",
    "jsdom": "^24.0.0",
    "tsup": "^8.0.0",
    "typescript": "^5.0.0",
    "vitest": "^1.0.0"
  }
}
```

- [ ] **Step 2: tsconfig.json**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src",
    "jsx": "react-jsx",
    "lib": ["DOM", "DOM.Iterable", "ES2022"],
    "moduleResolution": "bundler"
  },
  "include": ["src/**/*"],
  "exclude": ["tests/**/*", "dist/**/*"]
}
```

- [ ] **Step 3: tsup.config.ts**

```ts
import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm", "cjs"],
  dts: true,
  splitting: false,
  sourcemap: true,
  clean: true,
  external: ["react", "react-dom"],
});
```

- [ ] **Step 4: src/index.ts** — empty placeholder, real exports come in later tasks

```ts
// Public API of @tentoroforge/engine. Re-exported from the workspace.
// Filled in by subsequent tasks A2-A5.
export const ENGINE_VERSION = "0.1.0";
```

- [ ] **Step 5: README.md** — one-line elevator pitch

```md
# @tentoroforge/engine

Self-contained rendering engine for Tentoro Forge generated apps.
Reads page schemas at runtime, dispatches through the component library,
applies design tokens. One dependency for generated Next.js apps.

```tsx
import { Engine } from "@tentoroforge/engine";
<Engine schema={pageSchema} designSpec={designSpec} />
```

- [ ] **Step 6: Build verifies**

```bash
cd packages/engine && npm install --workspaces=false || true
npm run build
```

Expect: `dist/index.js`, `dist/index.cjs`, `dist/index.d.ts` produced.

- [ ] **Step 7: Commit**

```bash
git add packages/engine
git commit -m "feat(engine): package skeleton"
```

---

### Task A2: Engine types + interfaces

**Files:**
- Create: `packages/engine/src/types.ts`

- [ ] **Step 1: Write the public types**

```ts
// packages/engine/src/types.ts

import type { ReactNode } from "react";

/**
 * The page schema shape generated apps deal with. Mirrors PageV2 from
 * @tentoroforge/schema but kept as a structural type here so consumers
 * don't have to import the full schema package at type-check time.
 */
export interface PageSchema {
  schemaVersion: "1" | "2";
  id: string;
  route?: string;
  layout?: string;
  meta?: Record<string, unknown>;
  dataSources?: DataSource[];
  root?: SchemaNode;
  children?: SchemaNode[]; // legacy: some LLM outputs use top-level children
}

export interface SchemaNode {
  type: string;
  id?: string;
  props?: Record<string, unknown>;
  children?: SchemaNode[];
  slots?: Record<string, SchemaNode[]>;
  visibleIf?: string;
}

export interface DataSource {
  name: string;
  source?: string;          // route path, e.g. "/api/notes"
  op?: "list" | "get" | "search";
  params?: Record<string, unknown>;
}

export interface DesignSpec {
  register?: string;
  colorPalette?: { primary?: string; [k: string]: unknown };
  typography?: Record<string, unknown>;
  entityPhotos?: Record<string, string>;
  tokens?: Record<string, unknown>;
  cta_hierarchy?: Record<string, unknown>;
}

/** Top-level props for the Engine component. */
export interface EngineProps {
  schema: PageSchema;
  designSpec?: DesignSpec;
  /** Where to send /api requests. Empty string = same-origin. */
  apiBaseUrl?: string;
  /** Optional override map for preview data, used by editor previews. */
  previewData?: Record<string, unknown>;
}

/** Internal: passed through React context. */
export interface DataContext {
  data: Record<string, unknown>;
  user?: Record<string, unknown>;
}
```

- [ ] **Step 2: Commit**

```bash
git add packages/engine/src/types.ts
git commit -m "feat(engine): public types"
```

---

### Task A3: Data layer — interpolation + expression evaluation

**Files:**
- Create: `packages/engine/src/data/interpolate.ts`
- Create: `packages/engine/src/data/expressions.ts`
- Create: `packages/engine/tests/interpolate.test.ts`

Today these live as `packages/renderer/src/runtime/interpolate.ts` and `packages/renderer/src/runtime/expressions.ts`. We re-export them from engine so engine consumers don't depend on `@tentoroforge/renderer` directly (the renderer is an internal dep).

- [ ] **Step 1: Write tests first**

```ts
// packages/engine/tests/interpolate.test.ts
import { describe, it, expect } from "vitest";
import { interpolateDeep, interpolateString } from "../src/data/interpolate";

describe("interpolateString", () => {
  it("replaces {{path.to.value}}", () => {
    expect(interpolateString("Hello, {{user.name}}!", { user: { name: "Alex" } }))
      .toBe("Hello, Alex!");
  });

  it("leaves untouched when path missing", () => {
    expect(interpolateString("X = {{missing.value}}", {}))
      .toBe("X = {{missing.value}}");
  });
});

describe("interpolateDeep", () => {
  it("walks objects recursively", () => {
    expect(
      interpolateDeep({ label: "{{a}}", child: { value: "{{b}}" } }, { a: "A", b: "B" })
    ).toEqual({ label: "A", child: { value: "B" } });
  });
});
```

- [ ] **Step 2: Lift implementation from renderer**

```ts
// packages/engine/src/data/interpolate.ts
// Re-export the renderer's implementation so the public engine API is
// self-contained without consumers depending on @tentoroforge/renderer.
export { interpolateString, interpolateDeep } from "@tentoroforge/renderer/runtime/interpolate";
```

If the renderer's package.json doesn't expose `/runtime/interpolate` as a subpath export, instead COPY the file contents in and verify behaviour matches by running the renderer's tests too. The copy is acceptable because (a) the renderer is workspace-private, (b) the engine becomes the long-lived public surface.

- [ ] **Step 3: Run tests**

```bash
cd packages/engine && npx vitest run
```

3/3 must pass.

- [ ] **Step 4: Repeat for expressions.ts**

```ts
// packages/engine/src/data/expressions.ts
export { evalExpression } from "@tentoroforge/renderer/runtime/expressions";
```

Test:

```ts
// packages/engine/tests/expressions.test.ts
import { describe, it, expect } from "vitest";
import { evalExpression } from "../src/data/expressions";

describe("evalExpression", () => {
  it("evaluates boolean equality", () => {
    expect(evalExpression("status == 'active'", { status: "active" })).toBe(true);
    expect(evalExpression("status == 'active'", { status: "draft" })).toBe(false);
  });

  it("returns false on parse error rather than throwing", () => {
    expect(evalExpression("totally invalid !!", {})).toBe(false);
  });
});
```

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/data packages/engine/tests
git commit -m "feat(engine): data interpolation + expression evaluation"
```

---

### Task A4: Data loader — fetchDataSources

**Files:**
- Create: `packages/engine/src/data/loader.ts`
- Create: `packages/engine/tests/loader.test.ts`

The loader takes a page schema's `dataSources[]`, fires the corresponding fetches against `apiBaseUrl`, and returns a flat `{ [name]: result }` map ready for interpolation.

- [ ] **Step 1: Test first**

```ts
// packages/engine/tests/loader.test.ts
import { describe, it, expect, vi } from "vitest";
import { fetchDataSources } from "../src/data/loader";

const _fetch = global.fetch;
afterEach(() => { global.fetch = _fetch; });

describe("fetchDataSources", () => {
  it("returns empty map when no sources", async () => {
    const r = await fetchDataSources([], "");
    expect(r).toEqual({});
  });

  it("fetches each source from apiBaseUrl", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [{ id: 1 }] }),
    });
    const r = await fetchDataSources(
      [{ name: "notes", source: "/api/notes", op: "list" }],
      "http://api"
    );
    expect((global.fetch as any).mock.calls[0][0]).toBe("http://api/api/notes");
    expect(r.notes).toEqual({ items: [{ id: 1 }] });
  });

  it("swallows fetch errors and returns null for that source", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("offline"));
    const r = await fetchDataSources(
      [{ name: "x", source: "/api/x" }],
      ""
    );
    expect(r.x).toBeNull();
  });

  it("interpolates path params from prior sources", async () => {
    let calls = 0;
    global.fetch = vi.fn().mockImplementation(async (url: string) => ({
      ok: true,
      json: async () => {
        calls++;
        return calls === 1 ? { user: { id: "u1" } } : { name: "Alex" };
      },
    }));
    const r = await fetchDataSources(
      [
        { name: "session", source: "/api/session", op: "get" },
        { name: "profile", source: "/api/users/{{session.user.id}}", op: "get" },
      ],
      ""
    );
    expect((global.fetch as any).mock.calls[1][0]).toBe("/api/users/u1");
  });
});
```

- [ ] **Step 2: Implementation**

```ts
// packages/engine/src/data/loader.ts
import type { DataSource } from "../types";
import { interpolateString } from "./interpolate";

export async function fetchDataSources(
  sources: DataSource[] | undefined,
  apiBaseUrl: string,
): Promise<Record<string, unknown>> {
  const out: Record<string, unknown> = {};
  if (!sources || sources.length === 0) return out;

  for (const s of sources) {
    const path = s.source ? interpolateString(s.source, out) : null;
    if (!path) { out[s.name] = null; continue; }

    const url = path.startsWith("http")
      ? path
      : apiBaseUrl
        ? `${apiBaseUrl.replace(/\/$/, "")}${path}`
        : path;

    try {
      const resp = await fetch(url);
      if (!resp.ok) { out[s.name] = null; continue; }
      out[s.name] = await resp.json();
    } catch {
      out[s.name] = null;
    }

    // For get-op sources, lift the record's top-level keys so children can
    // reference {{employee.name}} rather than {{leaveRequest.employee.name}}.
    // Mirrors today's SchemaRendererWrapper behaviour exactly.
    if (s.op === "get" && out[s.name] && typeof out[s.name] === "object") {
      for (const [k, v] of Object.entries(out[s.name] as Record<string, unknown>)) {
        if (v && typeof v === "object" && !Array.isArray(v) && !(k in out)) {
          out[k] = v;
        }
      }
    }
  }

  return out;
}
```

- [ ] **Step 3: Run tests, verify 4/4**

```bash
cd packages/engine && npx vitest run tests/loader.test.ts
```

- [ ] **Step 4: Commit**

```bash
git add packages/engine/src/data/loader.ts packages/engine/tests/loader.test.ts
git commit -m "feat(engine): data source loader with path-param interpolation"
```

---

### Task A5: EngineProvider — theme/register/tokens context

**Files:**
- Create: `packages/engine/src/EngineProvider.tsx`
- Create: `packages/engine/tests/EngineProvider.test.tsx`

EngineProvider is the layout-level component that wraps the entire generated app. It applies CSS variables from the design-spec, sets the register, and provides preview-data context that descendant pages consume.

- [ ] **Step 1: Test first**

```tsx
// packages/engine/tests/EngineProvider.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { EngineProvider } from "../src/EngineProvider";

describe("EngineProvider", () => {
  it("renders children", () => {
    const { getByText } = render(
      <EngineProvider designSpec={{ register: "linear" }}>
        <div>hello</div>
      </EngineProvider>
    );
    expect(getByText("hello")).toBeTruthy();
  });

  it("sets data-register on the wrapper", () => {
    const { container } = render(
      <EngineProvider designSpec={{ register: "linear" }}>x</EngineProvider>
    );
    expect(container.firstChild).toHaveAttribute("data-register", "linear");
  });

  it("falls back to register='default' when designSpec omits it", () => {
    const { container } = render(
      <EngineProvider designSpec={{}}>x</EngineProvider>
    );
    expect(container.firstChild).toHaveAttribute("data-register", "default");
  });
});
```

- [ ] **Step 2: Implementation**

```tsx
// packages/engine/src/EngineProvider.tsx
"use client";

import * as React from "react";
import { TokensProvider, defaultTokens } from "@tentoroforge/library";
import type { DesignSpec } from "./types";

export interface EngineProviderProps {
  designSpec?: DesignSpec;
  children: React.ReactNode;
}

export function EngineProvider({ designSpec, children }: EngineProviderProps) {
  const register = (designSpec?.register as string) || "default";
  // tokens precedence: designSpec.tokens > defaultTokens
  const tokens = (designSpec?.tokens as Record<string, Record<string, string>>) ?? defaultTokens;

  return (
    <div data-tentoro-engine="" data-register={register}>
      <TokensProvider register={register as any} tokens={tokens as any}>
        {children}
      </TokensProvider>
    </div>
  );
}
```

- [ ] **Step 3: Run tests, verify 3/3**

- [ ] **Step 4: Commit**

```bash
git add packages/engine/src/EngineProvider.tsx packages/engine/tests/EngineProvider.test.tsx
git commit -m "feat(engine): EngineProvider with register + tokens context"
```

---

### Task A6: Engine component — the main entry point

**Files:**
- Create: `packages/engine/src/Engine.tsx`
- Create: `packages/engine/tests/Engine.test.tsx`

The `<Engine>` component:
1. Fetches the schema's data sources
2. Synthesises a root node when the schema lacks one (today's SchemaRendererWrapper fallback)
3. Dispatches the root through the renderer
4. Provides the data + previewData context

- [ ] **Step 1: Test first**

```tsx
// packages/engine/tests/Engine.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { Engine } from "../src/Engine";

describe("Engine", () => {
  it("renders a minimal schema", async () => {
    const schema = {
      schemaVersion: "2" as const,
      id: "x",
      root: { type: "Text", id: "t", props: { text: "hello" } },
    };
    const { getByText } = render(<Engine schema={schema} />);
    await waitFor(() => expect(getByText("hello")).toBeTruthy());
  });

  it("synthesises a root when schema has top-level children", async () => {
    const schema = {
      schemaVersion: "2" as const,
      id: "x",
      children: [{ type: "Text", id: "t", props: { text: "hi" } }],
    } as any;
    const { getByText } = render(<Engine schema={schema} />);
    await waitFor(() => expect(getByText("hi")).toBeTruthy());
  });

  it("interpolates data into props", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ name: "Alex" }),
    });
    const schema = {
      schemaVersion: "2" as const,
      id: "x",
      dataSources: [{ name: "user", source: "/api/user", op: "get" as const }],
      root: { type: "Text", id: "t", props: { text: "Hi, {{user.name}}" } },
    };
    const { getByText } = render(<Engine schema={schema} apiBaseUrl="" />);
    await waitFor(() => expect(getByText("Hi, Alex")).toBeTruthy());
  });

  it("renders nothing-but-error when schema is null", () => {
    const { container } = render(<Engine schema={null as any} />);
    expect(container.textContent).toMatch(/schema/i);
  });
});
```

- [ ] **Step 2: Implementation**

```tsx
// packages/engine/src/Engine.tsx
"use client";

import * as React from "react";
import { renderNode, createRegistry } from "@tentoroforge/renderer";
import type { EngineProps, SchemaNode } from "./types";
import { fetchDataSources } from "./data/loader";

function synthesiseRoot(schema: EngineProps["schema"]): SchemaNode {
  if (schema?.root) return schema.root;
  const tc = (schema as any)?.children;
  if (Array.isArray(tc) && tc.length > 0) {
    return { type: "Stack", id: "_synthetic_root", children: tc };
  }
  return {
    type: "Text",
    id: "_no_content",
    props: { text: "(empty page — open the editor to add content)" },
  };
}

export function Engine({ schema, apiBaseUrl = "", previewData }: EngineProps) {
  const [data, setData] = React.useState<Record<string, unknown>>(previewData ?? {});

  React.useEffect(() => {
    if (previewData) { setData(previewData); return; }
    let cancelled = false;
    fetchDataSources(schema?.dataSources, apiBaseUrl).then(d => {
      if (!cancelled) setData(d);
    });
    return () => { cancelled = true; };
  }, [schema, apiBaseUrl, previewData]);

  if (!schema) {
    return <div data-tentoro-engine-error="">Schema not provided.</div>;
  }

  const registry = React.useMemo(() => createRegistry(), []);
  const root = synthesiseRoot(schema);

  return <>{renderNode(root as any, { data, user: data.user as any, registry })}</>;
}
```

- [ ] **Step 3: Run tests, verify 4/4**

- [ ] **Step 4: Commit**

```bash
git add packages/engine/src/Engine.tsx packages/engine/tests/Engine.test.tsx
git commit -m "feat(engine): Engine component with data loading + root synthesis"
```

---

### Task A7: Public exports

**Files:**
- Modify: `packages/engine/src/index.ts`

- [ ] **Step 1: Wire all public exports**

```ts
// packages/engine/src/index.ts
export { Engine } from "./Engine";
export { EngineProvider } from "./EngineProvider";
export type {
  PageSchema,
  SchemaNode,
  DataSource,
  DesignSpec,
  EngineProps,
  DataContext,
} from "./types";

export const ENGINE_VERSION = "0.1.0";
```

- [ ] **Step 2: Build verifies + commit**

```bash
cd packages/engine && npm run build
git add packages/engine/src/index.ts
git commit -m "feat(engine): public exports"
```

---

## Workstream B — Standalone-app template + emitter

### Task B1: Template directory + each file content

**Files:** all under `backend/templates/standalone-app/`

- [ ] **Step 1: package.json.tmpl** — `<<` are interpolation markers replaced by emitter

```json
{
  "name": "<<project_short_id>>",
  "version": "0.0.1",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  },
  "dependencies": {
    "@tentoroforge/engine": "<<engine_version>>",
    "next": "^15.0.0",
    "react": "^18.0.0",
    "react-dom": "^18.0.0",
    "tailwindcss": "^3.4.0"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "@types/react": "^18.0.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0",
    "typescript": "^5.0.0"
  }
}
```

- [ ] **Step 2: next.config.js**

```js
/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,
  transpilePackages: ["@tentoroforge/engine", "@tentoroforge/library", "@tentoroforge/renderer"],
};
```

- [ ] **Step 3: tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "es2022"],
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
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 4: tailwind.config.ts**

```ts
import type { Config } from "tailwindcss";
const config: Config = {
  content: [
    "./src/**/*.{ts,tsx}",
    "./node_modules/@tentoroforge/library/**/*.{js,jsx,ts,tsx}",
  ],
  theme: { extend: {} },
  plugins: [],
};
export default config;
```

- [ ] **Step 5: src/app/layout.tsx**

```tsx
import "./globals.css";
import { EngineProvider } from "@tentoroforge/engine";
import { promises as fs } from "node:fs";
import path from "node:path";

async function loadDesignSpec() {
  try {
    const p = path.join(process.cwd(), "src", "contracts", "design-spec.json");
    return JSON.parse(await fs.readFile(p, "utf8"));
  } catch { return {}; }
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const designSpec = await loadDesignSpec();
  return (
    <html lang="en">
      <body>
        <EngineProvider designSpec={designSpec}>{children}</EngineProvider>
      </body>
    </html>
  );
}
```

- [ ] **Step 6: src/app/[...slug]/page.tsx**

```tsx
import { notFound } from "next/navigation";
import { promises as fs } from "node:fs";
import path from "node:path";
import { Engine } from "@tentoroforge/engine";

export default async function Page({
  params,
}: { params: Promise<{ slug?: string[] }> }) {
  const { slug = [] } = await params;
  const slugPath = slug.join("/") || "home";
  const schemaPath = path.join(process.cwd(), "src", "schemas", `${slugPath}.json`);

  let schema;
  try {
    schema = JSON.parse(await fs.readFile(schemaPath, "utf8"));
  } catch {
    notFound();
  }

  const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "";
  return <Engine schema={schema} apiBaseUrl={apiBaseUrl} />;
}
```

- [ ] **Step 7: src/app/page.tsx** — default to /home redirect

```tsx
import { redirect } from "next/navigation";
export default function RootPage() { redirect("/home"); }
```

- [ ] **Step 8: src/app/not-found.tsx**

```tsx
export default function NotFound() {
  return <div style={{ padding: 24 }}>Page not found.</div>;
}
```

- [ ] **Step 9: postcss.config.js**

```js
module.exports = { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

- [ ] **Step 10: .gitignore**

```
node_modules/
.next/
out/
*.log
.env.local
```

- [ ] **Step 11: Commit**

```bash
git add backend/templates/standalone-app
git commit -m "feat(emitter): standalone-app template files"
```

---

### Task B2: ENGINE_VERSION pin constant

**Files:**
- Create: `backend/services/app_emitter_constants.py`

- [ ] **Step 1: Single source of truth for the engine version**

```python
"""Constants for the standalone-app emitter."""

# The engine version that emitted apps pin against. Bumped manually when
# the engine ships a breaking change. CI verifies this matches the actual
# packages/engine/package.json version.
ENGINE_VERSION = "0.1.0"
```

- [ ] **Step 2: Commit**

```bash
git add backend/services/app_emitter_constants.py
git commit -m "feat(emitter): engine version pin constant"
```

---

### Task B3: app_emitter.py — copy template + interpolate

**Files:**
- Create: `backend/services/app_emitter.py`
- Create: `backend/tests/services/test_app_emitter.py`

- [ ] **Step 1: Failing tests**

```python
# backend/tests/services/test_app_emitter.py
"""Tests for the standalone-app emitter."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

from services.app_emitter import emit_standalone_app


def test_emit_writes_all_template_files():
    with tempfile.TemporaryDirectory() as td:
        emit_standalone_app(output_dir=td, project_short_id="proj-1")
        out = Path(td)
        for rel in [
            "package.json", "next.config.js", "tsconfig.json",
            "tailwind.config.ts", "postcss.config.js", ".gitignore",
            "src/app/layout.tsx", "src/app/[...slug]/page.tsx",
            "src/app/page.tsx", "src/app/not-found.tsx",
        ]:
            assert (out / rel).exists(), f"missing {rel}"


def test_emit_interpolates_project_short_id_into_package_json():
    with tempfile.TemporaryDirectory() as td:
        emit_standalone_app(output_dir=td, project_short_id="my-app-xyz")
        pkg = json.loads((Path(td) / "package.json").read_text())
        assert pkg["name"] == "my-app-xyz"


def test_emit_pins_engine_version_from_constants():
    from services.app_emitter_constants import ENGINE_VERSION
    with tempfile.TemporaryDirectory() as td:
        emit_standalone_app(output_dir=td, project_short_id="x")
        pkg = json.loads((Path(td) / "package.json").read_text())
        assert pkg["dependencies"]["@tentoroforge/engine"] == ENGINE_VERSION


def test_emit_is_idempotent():
    """Calling twice on same dir produces same result; doesn't append."""
    with tempfile.TemporaryDirectory() as td:
        emit_standalone_app(output_dir=td, project_short_id="x")
        first = (Path(td) / "package.json").read_text()
        emit_standalone_app(output_dir=td, project_short_id="x")
        second = (Path(td) / "package.json").read_text()
        assert first == second


def test_emit_preserves_existing_schemas_directory():
    """Pre-existing src/schemas/ from a prior pipeline run must NOT be wiped."""
    with tempfile.TemporaryDirectory() as td:
        schemas = Path(td) / "src" / "schemas"
        schemas.mkdir(parents=True)
        (schemas / "home.json").write_text('{"x": 1}')
        emit_standalone_app(output_dir=td, project_short_id="x")
        assert (schemas / "home.json").read_text() == '{"x": 1}'
```

- [ ] **Step 2: Implementation**

```python
# backend/services/app_emitter.py
"""Emit a standalone Next.js app skeleton into a project's output directory.

Runs AFTER the schema agents have written src/schemas/*.json and the
design agent has written src/contracts/design-spec.json. We add the
templated runtime files (package.json, next.config.js, layout.tsx,
[...slug]/page.tsx, etc.) so the project becomes a working Next.js app.

Idempotent — re-emitting overwrites our templated files but never
touches LLM-generated content under src/schemas/ or src/contracts/.
"""
from __future__ import annotations
from pathlib import Path
import json
import shutil

from services.app_emitter_constants import ENGINE_VERSION

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "standalone-app"
_INTERPOLATABLE_SUFFIX = ".tmpl"


def _interpolate(text: str, *, project_short_id: str, engine_version: str) -> str:
    return (
        text
        .replace("<<project_short_id>>", project_short_id)
        .replace("<<engine_version>>", engine_version)
    )


def emit_standalone_app(*, output_dir: str | Path, project_short_id: str) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for src in _TEMPLATE_DIR.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(_TEMPLATE_DIR)
        is_template = rel.suffix == _INTERPOLATABLE_SUFFIX
        dst_rel = rel.with_suffix("") if is_template else rel
        dst = out / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        if is_template:
            content = src.read_text()
            content = _interpolate(
                content,
                project_short_id=project_short_id,
                engine_version=ENGINE_VERSION,
            )
            dst.write_text(content)
        else:
            shutil.copyfile(src, dst)
```

- [ ] **Step 3: Run tests, verify 5/5**

```bash
cd backend && python3 -m pytest tests/services/test_app_emitter.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/services/app_emitter.py backend/tests/services/test_app_emitter.py
git commit -m "feat(emitter): copy + interpolate standalone-app template"
```

---

### Task B4: Wire emitter into pipeline

**Files:**
- Modify: `backend/routers/generate.py`

The emitter runs once per pipeline, AFTER schemas are written and BEFORE the schema-mode early-exit. Both the relay and Figma pipelines need the call.

- [ ] **Step 1: Add the call sites**

Find both `Schema mode — skipping QA/validator/indexer` log lines in `generate.py`. Immediately BEFORE each one, insert:

```python
        # Emit the standalone-app skeleton so the project is a runnable
        # Next.js app — package.json, layout.tsx, [...slug]/page.tsx etc.
        # The skeleton imports @tentoroforge/engine and reads schemas at
        # request time. Idempotent: existing schemas are preserved.
        try:
            from services.app_emitter import emit_standalone_app
            short_id = Path(output_dir).name
            emit_standalone_app(output_dir=output_dir, project_short_id=short_id)
            yield sse_event("log", {"text": "[Emitter] Standalone Next.js app skeleton written"})
        except Exception as _emit_exc:
            yield sse_event("log", {"text": f"[Emitter] Skipped: {_emit_exc}"})
```

- [ ] **Step 2: Compile check**

```bash
python3 -m py_compile backend/routers/generate.py
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/generate.py
git commit -m "feat(emitter): wire into generation pipeline (both schema-mode exits)"
```

---

### Task B5: Smoke-emit + actually run a generated app

**Verifies the loop end-to-end without LLM cost.**

- [ ] **Step 1: Run the emitter against an existing project**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -c "
from services.app_emitter import emit_standalone_app
emit_standalone_app(
    output_dir='../output/db17s1zl',
    project_short_id='db17s1zl',
)
print('emitted')
"
```

- [ ] **Step 2: Verify the project is now a valid Next.js app**

```bash
cd ../output/db17s1zl
ls package.json src/app/layout.tsx src/app/\[...slug\]/page.tsx
# package.json should reference @tentoroforge/engine
grep "@tentoroforge/engine" package.json
```

- [ ] **Step 3: Install + run**

```bash
cd ../output/db17s1zl
npm install                      # ~30s — verifies the engine resolves
PORT=6504 npm run dev > /tmp/standalone-dev.log 2>&1 &
sleep 8
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:6504/home
# Expect 200. If 500, check /tmp/standalone-dev.log for the actual error.
kill %1
```

If 200: the standalone app rendered the same schema the scaffold renders. Goal achieved.

- [ ] **Step 4: Don't commit this — it's a smoke test, no artifacts**

If anything was broken: fix the engine package or template, rerun. Iterate until 200.

---

## Workstream C — Editor wiring + export

### Task C1: Export endpoint

**Files:**
- Modify: `backend/routers/projects.py` (or whichever file owns project read/write endpoints)

Returns a tarball stream of the output_dir minus `node_modules/`, `.next/`, `.git/`.

- [ ] **Step 1: Test first**

```python
# backend/tests/routers/test_project_export.py
import io
import tarfile
import pytest
from fastapi.testclient import TestClient

# Adapt to actual test fixtures + auth bypass for this codebase
def test_export_returns_tarball(test_client, test_project):
    r = test_client.get(f"/api/projects/{test_project.id}/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-tar"
    tf = tarfile.open(fileobj=io.BytesIO(r.content), mode="r")
    names = tf.getnames()
    assert any("package.json" in n for n in names)
    assert all("node_modules" not in n for n in names)
    assert all(".next" not in n for n in names)
```

- [ ] **Step 2: Implementation** — add to the appropriate router file

```python
import tarfile
import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

EXCLUDE_DIRS = {"node_modules", ".next", ".git", "out"}

@router.get("/api/projects/{project_id}/export")
async def export_project(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    out_dir = Path(project.output_dir)
    if not out_dir.exists():
        raise HTTPException(404, "Project output directory missing")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for p in out_dir.rglob("*"):
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            if p.is_file():
                tf.add(p, arcname=p.relative_to(out_dir.parent))
    buf.seek(0)

    return StreamingResponse(
        buf, media_type="application/x-tar",
        headers={"content-disposition": f"attachment; filename={project.short_id}.tar"},
    )
```

- [ ] **Step 3: Run tests + commit**

```bash
cd backend && python3 -m pytest tests/routers/test_project_export.py -v
git add backend/routers backend/tests/routers
git commit -m "feat(export): /api/projects/{id}/export returns tarball"
```

---

### Task C2: "Run locally" panel in editor

**Files:**
- Modify: `frontend/src/components/schema-editor/SchemaEditorPanel.tsx` (or add a new sub-tab)

Shows the three commands the user runs after downloading the tarball.

- [ ] **Step 1: Add sub-tab + content**

```tsx
// Inside SchemaEditorPanel, add a 4th sub-tab "Export"
{activeSubTab === "export" && (
  <div className="p-6 max-w-2xl">
    <h2 className="text-lg font-semibold mb-2">Export & run locally</h2>
    <p className="text-sm text-muted-foreground mb-4">
      Download your generated app as a standalone Next.js project.
    </p>
    <a
      href={`${API_BASE}/api/projects/${projectId}/export`}
      download
      className="inline-flex items-center px-4 py-2 rounded-md bg-primary text-primary-foreground"
    >
      Download {projectShortId}.tar
    </a>
    <pre className="mt-6 bg-muted p-4 rounded-md text-sm overflow-x-auto">
{`tar -xf ${projectShortId}.tar
cd ${projectShortId}
npm install
npm run dev   # then open http://localhost:3000`}
    </pre>
  </div>
)}
```

- [ ] **Step 2: Add the "Export" tab button** alongside Editor/Preview/Score

```tsx
<button onClick={() => setActiveSubTab("export")}>
  Export
</button>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/schema-editor
git commit -m "feat(editor): Export sub-tab with download + run instructions"
```

---

### Task C3: Document the new dual-mode

**Files:**
- Modify: `README.md` (or wherever project docs live)

- [ ] **Step 1: Add a section explaining preview vs. standalone**

Two paragraphs covering:
- Preview: editor at 6501 → scaffold at 6503 (fast iteration, no install)
- Standalone: download from editor → `npm install && npm run dev` (real Next.js app, deployable)

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: explain preview vs. standalone run modes"
```

---

## Workstream D — Scaffold uses engine (no duplication)

### Task D1: Replace scaffold's inline dispatch with `<Engine>`

**Files:**
- Modify: `apps/render-scaffold/src/components/SchemaRendererWrapper.tsx`
- Modify: `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx`

After this task, scaffold and standalone apps share the SAME engine code — bugs and improvements land in one place.

- [ ] **Step 1: Add @tentoroforge/engine to scaffold's package.json**

```bash
cd apps/render-scaffold
# Edit package.json to add "@tentoroforge/engine": "workspace:*" under dependencies
```

- [ ] **Step 2: Replace SchemaRendererWrapper internals**

The whole file collapses from ~330 lines to:

```tsx
"use client";

import { Engine, EngineProvider } from "@tentoroforge/engine";
import type { PageSchema, DesignSpec } from "@tentoroforge/engine";

interface SchemaRendererWrapperProps {
  page: PageSchema;
  designSpec: DesignSpec;
  tokens?: unknown;        // kept for back-compat — passed through to provider
  register?: string;
  previewData?: Record<string, unknown>;
  projectId: string;
}

export function SchemaRendererWrapper({
  page, designSpec, previewData,
}: SchemaRendererWrapperProps) {
  return (
    <EngineProvider designSpec={designSpec}>
      <Engine schema={page} previewData={previewData} apiBaseUrl="" />
    </EngineProvider>
  );
}
```

- [ ] **Step 3: Simplify page.tsx**

The scaffold's `[...slug]/page.tsx` still does the schema-file lookup with fallbacks (those are project-routing concerns, not engine concerns), but the rendering call collapses:

```tsx
return (
  <main data-project-id={projectId} data-page-path={pagePath}>
    {projectGlobalsCss && <style dangerouslySetInnerHTML={{ __html: projectGlobalsCss }} />}
    <SchemaRendererWrapper
      page={page} designSpec={designSpec}
      previewData={previewData} projectId={projectId}
    />
  </main>
);
```

- [ ] **Step 4: Test — every project still renders**

```bash
# With scaffold dev server running on 6503
for p in db17s1zl validate-1778728940 clean-1778676179; do
  curl -s -o /dev/null -w "/p/$p/home: %{http_code}\n" "http://localhost:6503/p/$p/home"
done
```

All three must return 200.

- [ ] **Step 5: Commit**

```bash
git add apps/render-scaffold
git commit -m "refactor(scaffold): use @tentoroforge/engine instead of inline dispatch"
```

---

### Task D2: Drop redundant data-binding code from scaffold

After D1, the inline interpolate/loader logic in `SchemaRendererWrapper.tsx` (the `useMemo` block that builds `data`, the FK-lifting loop, etc.) is dead — it's inside the engine now. Remove it. Verify scaffold still passes the same tests.

- [ ] **Step 1: Delete the dead code in `SchemaRendererWrapper.tsx`** — the data fetch, the interpolation memo, the FK-lifting loop.

- [ ] **Step 2: Verify** — same 3-project curl check passes.

- [ ] **Step 3: Commit**

```bash
git add apps/render-scaffold/src/components/SchemaRendererWrapper.tsx
git commit -m "refactor(scaffold): drop inline data layer (now in engine)"
```

---

## Self-review against the spec

### Spec coverage

- [x] Extract engine into a single npm package — Workstream A
- [x] Template emitter writes runnable Next.js skeleton — Workstream B
- [x] Pin engine version per project — Task B2
- [x] Editor preview keeps working — Workstream D (scaffold uses engine)
- [x] Export tarball — Task C1
- [x] "Run locally" instructions — Task C2
- [x] Documented dual-mode — Task C3

### Placeholder scan

No "TBD", "implement later", or vague steps. Every code step has actual code. Tests cited up front.

### Type consistency

`PageSchema` shape stable across A2, A4, A6, B1, D1. `DesignSpec` stable. `EngineProps` defined in A2, consumed in A6/D1. ENGINE_VERSION single source of truth in B2.

### Risks & mitigations

- **Workspace install may not resolve `@tentoroforge/engine` for a generated app under `output/`.** Mitigation in Task B5: `npm install` runs against the generated app's `package.json`, which references the engine via the published version, not `workspace:*`. Until we actually publish to a registry, the generated app needs to import via `file:../../packages/engine` or run inside the workspace. Document this as a known limitation in C3 — full deploy story comes when the engine is published to npm or a private registry.

- **Template `<<project_short_id>>` interpolation could collide with template syntax other tools care about.** Use `<<...>>` markers, which don't conflict with mustache (`{{...}}`) or Liquid (`{% ... %}`).

- **Scaffold migration (Workstream D) could regress preview if the engine isn't a perfect superset of the inline code.** Mitigation: D1 ships behind no flag but D2's "drop dead code" is the irreversible step — keep D1 reversible until smoke-tested across all 3+ existing projects.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-14-standalone-engine-and-emitter.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for this plan because the workstreams are largely independent (A → B → C/D in parallel after A ships).

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?

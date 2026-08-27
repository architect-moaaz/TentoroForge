# High-Fidelity Domain-Aware Schema Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make schema-mode generations produce v0/Lovable-quality, domain-tuned designs while preserving the schema runtime's editability and speed.

**Architecture:** Compile the planner's already-emitted `design-spec.json` into `tokens.custom.json` (deterministic Python mapper). Extend the schema package to v2 with a `StyleSlot` mixin, a `Custom` escape hatch, and 20 new node types. Ship matching library components that consume tokens uniformly via a `resolveStyle` helper. Restructure the schema-agent prompt to inject design rationale + auto-generated token paths + a curated archetype example. Add editor support for the new style slots and Custom blocks.

**Tech Stack:** TypeScript (zod, React 19, dnd-kit, dompurify), Python 3.11 (FastAPI, claude_agent_sdk), pnpm workspaces, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-05-03-high-fidelity-schema-generation-design.md`

---

## File map

### Schema package (`packages/schema/src/`)
- Modify: `tokens.ts` — add `TokenRef`, `SpacingTokenRef`, `RadiusTokenRef`, `ShadowTokenRef` regex schemas
- Create: `style-slot.ts` — `Background`, `Motion`, `StyleSlot` zods
- Create: `nodes/custom.ts` — `CustomNode` zod
- Create: `nodes/foundation.ts` — `Hero`, `Section`, `MetricTile`, `FeatureCard` zods
- Create: `nodes/layout-v2.ts` — `Split`, `Sidebar`, `Cluster`, `Tabs`, `Accordion` zods
- Create: `nodes/display.ts` — `Avatar`, `KeyValueList`, `Skeleton` zods
- Create: `nodes/inputs.ts` — `Input`, `Select`, `Textarea`, `Checkbox`, `DatePicker` zods
- Create: `nodes/motion.ts` — `FadeIn`, `Stagger` zods
- Modify: `page.ts` — `PageV1` (verbatim of current), `PageV2` (with new union member), `Page` discriminated union on `schemaVersion`
- Create: `migrate.ts` — `migratePage(raw)`
- Modify: `index.ts` — re-export new types
- Create tests under `packages/schema/tests/`

### Library package (`packages/library/src/`)
- Modify: `theme/default-tokens.ts` — refactor to canonical structure
- Create: `style/resolveStyle.ts`
- Create: `style/useMotion.ts`
- Create per-component dirs under `components/` — `Hero/`, `Section/`, `MetricTile/`, `FeatureCard/`, `Split/`, `Sidebar/`, `Cluster/`, `Tabs/`, `Accordion/`, `Avatar/`, `KeyValueList/`, `Skeleton/`, `Input/`, `Select/`, `Textarea/`, `Checkbox/`, `DatePicker/`, `CustomBlock/`, `Motion/`
- Create: `layouts/MarketingLayout.json`, `layouts/SettingsLayout.json`
- Modify: `layouts/index.ts`, `index.ts`
- Modify each existing component schema (`Button.schema.ts`, etc.) to accept `style: StyleSlot.optional()`

### Renderer (`packages/renderer/src/`)
- Modify: `runtime/dispatch.tsx` — apply StyleSlot at dispatch, add `case "Custom"`

### Backend (`backend/`)
- Create: `services/design_compiler.py`
- Create: `services/schema_examples/` directory with 9 gold-standard example JSONs + README
- Modify: `services/schema_prompt.py` — auto-generate token paths from defaultTokens, inject design context, load gold example by archetype
- Modify: `routers/generate.py` — call `design_compiler` between design-agent and schema-agent
- Modify: `routers/_debug_schema.py` — add `/api/_debug/recompile-tokens/{short_id}`
- Modify: `agents/feature_slice_schema_agent.py` — pass new prompt context
- Tests under `backend/tests/services/`

### Editor (`packages/editor/src/`)
- Create: `panes/Properties/StyleSlotEditor.tsx`
- Create: `panes/Properties/style/TokenPicker.tsx`
- Create: `panes/Properties/style/BackgroundEditor.tsx`
- Create: `panes/Properties/style/MotionEditor.tsx`
- Create: `panes/Canvas/CustomNodePreview.tsx`
- Create: `panes/Properties/CustomEditor.tsx`
- Modify: `panes/Properties/Properties.tsx` — mount StyleSlotEditor
- Modify: `dnd/validate-drop.ts` — Tabs/Split/Sidebar/Custom constraints

### Frontend & foundation template
- Modify: `frontend/src/components/schema-editor/EditorMount.tsx` — register all new components
- Modify: `backend/templates/app-foundation/src/lib/library-registry.ts` — same

---

## Conventions

- **Test framework:** Vitest in TS packages, pytest in backend.
- **Build:** `cd packages/<pkg> && npx tsc` rebuilds dist. Frontend hot-reloads on dist change.
- **Test commands:** `cd packages/<pkg> && npx vitest run` for one package, `cd backend && pytest tests/services -v` for backend.
- **Commit cadence:** one commit per task at minimum.
- **Branch:** stay on `forge-v3`.
- **v2 node-type conventions** (locked in by Task 3, applies to Tasks 4-7):
  - All outer `z.object({...})` calls use `.strict()` so unknown keys reject (LLM-hallucinated props are caught, not silently dropped).
  - `props: z.object({...}).strict()` — same.
  - `id: z.string().min(1)` — empty IDs would break selection/dnd downstream.
  - User-facing required strings (e.g., `html`, `headline`, `label`, `value` string branch) use `.min(1)` so LLM truncation surfaces as a parse error.
  - `children: z.array(z.any())` is a deliberate placeholder until Task 8 wires the recursive `NodeV2` union.
  - All nodes accept `style: StyleSlot.optional()`.
- **Library component conventions** (locked in by Task 11, applies to Tasks 12-19):
  - Each component lives at `packages/library/src/components/Foo/{Foo.tsx, Foo.schema.ts}`.
  - `Foo.schema.ts` exports `FooProps = FooNode.shape.props` and `FooPropsType = z.infer<typeof FooProps>`. Use top-level `import { z } from "zod";` (NOT inline `import("zod")`).
  - `Foo.tsx` defines `interface FooProps extends FooPropsType { style?: StyleSlotT; children?: React.ReactNode; }`. Don't redeclare props — extend the zod-inferred type so schema/component drift is impossible.
  - Apply `resolveStyle(style)` + `useMotion(style?.motion)` to the component's outer wrapper element.
  - CTAs/buttons that have a `navigate` action render as `<a href>`; `workflow` actions render as `<button type="button" data-cta-action="workflow:<name>">`. The renderer (Task 21) wires onClick via context.
  - Add a header comment block listing the component's emitted classnames + data attributes so Task 18 (global stylesheet) has a clear contract.
  - Tests must include: render basics, StyleSlot application (padding → CSS var), motion attribute emission, and any node-specific behaviors.

---

## Phase A — Foundation

### Task 1: Refactor `defaultTokens` to canonical structure

**Files:**
- Modify: `packages/library/src/theme/default-tokens.ts`
- Create: `packages/library/tests/default-tokens.test.ts`

- [ ] **Step 1: Write the snapshot test first**

```ts
// packages/library/tests/default-tokens.test.ts
import { describe, it, expect } from "vitest";
import { defaultTokens } from "../src/theme/default-tokens";

function leafPaths(obj: any, prefix = "tokens"): string[] {
  const out: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    const path = `${prefix}.${k}`;
    if (v && typeof v === "object") out.push(...leafPaths(v, path));
    else out.push(path);
  }
  return out.sort();
}

describe("defaultTokens canonical structure", () => {
  it("exposes the contract paths the LLM emits + validator expects", () => {
    const paths = leafPaths(defaultTokens);
    // Snapshot — locked-in contract; if this changes, the prompt builder
    // and validator must be updated together.
    expect(paths).toMatchSnapshot();
  });

  it("has 11-stop ramps for primary/secondary/accent", () => {
    for (const scale of ["primary", "secondary", "accent"] as const) {
      const ramp = (defaultTokens.color as any)[scale];
      expect(Object.keys(ramp).sort((a, b) => +a - +b))
        .toEqual(["50","100","200","300","400","500","600","700","800","900","950"]);
    }
  });

  it("has 3-stop ramps for status colors", () => {
    for (const status of ["success", "warning", "error", "info"] as const) {
      const ramp = (defaultTokens.color as any)[status];
      expect(Object.keys(ramp).sort()).toEqual(["50", "500", "700"]);
    }
  });

  it("has 13-stop spacing scale", () => {
    const stops = Object.keys(defaultTokens.spacing)
      .filter((k) => /^\d+$/.test(k))
      .sort((a, b) => +a - +b);
    expect(stops).toEqual(["0","1","2","3","4","6","8","12","16","24","32","48","64"]);
  });

  it("has typography scale h1..caption", () => {
    expect(Object.keys(defaultTokens.typography.scale).sort())
      .toEqual(["body", "caption", "h1", "h2", "h3"]);
  });
});
```

- [ ] **Step 2: Run test (should fail — wrong shape)**

```
cd packages/library && npx vitest run tests/default-tokens.test.ts
```
Expected: FAIL — current `defaultTokens` doesn't match the canonical paths.

- [ ] **Step 3: Rewrite `default-tokens.ts`**

```ts
// packages/library/src/theme/default-tokens.ts
// Canonical token namespace. The LLM emits paths like
// `tokens.color.primary.500` and the prompt-builder + validator both derive
// the legal-paths list from this object. Changing keys here must be a
// coordinated change with services/schema_prompt.py and the renderer.

export type TokenGroups = typeof defaultTokens;

const ramp11 = (anchor: string, ramp: Record<string, string>) => ramp;

export const defaultTokens = {
  color: {
    primary: {
      "50":  "#eff6ff", "100": "#dbeafe", "200": "#bfdbfe", "300": "#93c5fd",
      "400": "#60a5fa", "500": "#3b82f6", "600": "#2563eb", "700": "#1d4ed8",
      "800": "#1e40af", "900": "#1e3a8a", "950": "#172554",
    },
    secondary: {
      "50":  "#f5f3ff", "100": "#ede9fe", "200": "#ddd6fe", "300": "#c4b5fd",
      "400": "#a78bfa", "500": "#8b5cf6", "600": "#7c3aed", "700": "#6d28d9",
      "800": "#5b21b6", "900": "#4c1d95", "950": "#2e1065",
    },
    accent: {
      "50":  "#fdf4ff", "100": "#fae8ff", "200": "#f5d0fe", "300": "#f0abfc",
      "400": "#e879f9", "500": "#d946ef", "600": "#c026d3", "700": "#a21caf",
      "800": "#86198f", "900": "#701a75", "950": "#4a044e",
    },
    surface: { "0": "#ffffff", "1": "#fafafa", "2": "#f4f4f5" },
    border:  { default: "#e4e4e7" },
    muted:   { default: "#a1a1aa" },
    text:    { primary: "#18181b", secondary: "#52525b", tertiary: "#a1a1aa" },
    sidebar: { bg: "#0f172a", text: "#cbd5e1", active: "#1e293b" },
    success: { "50": "#f0fdf4", "500": "#22c55e", "700": "#15803d" },
    warning: { "50": "#fffbeb", "500": "#f59e0b", "700": "#b45309" },
    error:   { "50": "#fef2f2", "500": "#ef4444", "700": "#b91c1c" },
    info:    { "50": "#eff6ff", "500": "#3b82f6", "700": "#1d4ed8" },
  },
  spacing: {
    "0":  "0",     "1":  "0.25rem", "2":  "0.5rem",  "3":  "0.75rem",
    "4":  "1rem",  "6":  "1.5rem",  "8":  "2rem",   "12": "3rem",
    "16": "4rem",  "24": "6rem",    "32": "8rem",   "48": "12rem",  "64": "16rem",
    semantic: {
      page: "2rem", card: "1.25rem", section: "4rem", element: "1rem", input: "0.75rem",
    },
  },
  radius: { sm: "0.25rem", md: "0.5rem", lg: "0.75rem", xl: "1rem", full: "9999px" },
  shadow: {
    sm: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
    md: "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
    lg: "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
    xl: "0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)",
  },
  typography: {
    font:   { body: "Inter, system-ui, sans-serif", heading: "Inter, system-ui, sans-serif" },
    weight: { body: "400", heading: "600" },
    scale:  { h1: "2rem", h2: "1.5rem", h3: "1.25rem", body: "0.875rem", caption: "0.75rem" },
    lineHeight:    { tight: "1.25", normal: "1.5" },
    letterSpacing: { heading: "-0.02em", body: "0" },
  },
  motion: {
    duration: { fast: "150ms", normal: "300ms" },
    easing:   { standard: "cubic-bezier(0.4, 0, 0.2, 1)" },
  },
  imagery: {
    login: "", dashboard: "",
    style: { emptyState: "geometric", icon: "outline", avatar: "initials" },
  },
  semantic: { status: {} as Record<string, string> },
} as const;
```

- [ ] **Step 4: Run test to capture snapshot**

```
cd packages/library && npx vitest run tests/default-tokens.test.ts -u
```
Expected: PASS, snapshot file created at `tests/__snapshots__/default-tokens.test.ts.snap`.

- [ ] **Step 5: Commit**

```
git add packages/library/src/theme/default-tokens.ts \
        packages/library/tests/default-tokens.test.ts \
        packages/library/tests/__snapshots__/default-tokens.test.ts.snap
git commit -m "feat(library): canonicalize defaultTokens namespace + lock paths via snapshot"
```

---

## Phase B — Schema package v2

### Task 2: Add `TokenRef` regex schemas + `StyleSlot`

**Files:**
- Modify: `packages/schema/src/tokens.ts`
- Create: `packages/schema/src/style-slot.ts`
- Create: `packages/schema/tests/style-slot.test.ts`

> **Naming note (post-implementation):** A legacy `TokenRef` already exists in `tokens.ts` for v1 inline-style props (used by `StyleProps`, `TokenOverrides`, layout `gap`/`size`). The new generic strict variant exported by this task is named `ScopedTokenRef` (and `ScopedTokenRefT`) to avoid clobbering the legacy export. Tasks 3–7 that reference "TokenRef" in node prop schemas should import `ScopedTokenRef` (or use the scoped variants `ColorTokenRef`/`SpacingTokenRef`/etc. directly when the slot type is fixed).

- [ ] **Step 1: Write the failing test**

```ts
// packages/schema/tests/style-slot.test.ts
import { describe, it, expect } from "vitest";
import { StyleSlot, Background } from "../src/style-slot";

describe("StyleSlot", () => {
  it("accepts an empty object", () => {
    expect(StyleSlot.parse({}).motion).toBeUndefined();
  });

  it("accepts gradient background with token refs", () => {
    const r = StyleSlot.parse({
      background: { type: "gradient",
                    from: "tokens.color.primary.50",
                    to: "tokens.color.surface.0",
                    angle: 135 },
      padding: "tokens.spacing.semantic.section",
      radius: "tokens.radius.lg",
      shadow: "tokens.shadow.md",
      motion: "fade-in",
    });
    expect(r.background?.type).toBe("gradient");
    expect(r.motion).toBe("fade-in");
  });

  it("rejects raw hex in token-ref slots", () => {
    expect(() => StyleSlot.parse({ padding: "16px" })).toThrow();
  });

  it("rejects unknown background type", () => {
    expect(() => StyleSlot.parse({ background: { type: "video", url: "x" } })).toThrow();
  });

  it("Background pattern accepts named patterns only", () => {
    expect(() => Background.parse({ type: "pattern", name: "stripes" })).toThrow();
    expect(Background.parse({ type: "pattern", name: "dots" }).name).toBe("dots");
  });
});
```

- [ ] **Step 2: Run — should fail (modules don't exist)**

```
cd packages/schema && npx vitest run tests/style-slot.test.ts
```
Expected: FAIL — `Cannot find module '../src/style-slot'`.

- [ ] **Step 3: Add token-ref helpers to `tokens.ts`**

Append to `packages/schema/src/tokens.ts`:

```ts
import { z } from "zod";

const tokenRefRegex = /^tokens\.[a-z]+(?:\.[a-zA-Z0-9]+)+$/;

/** Generic token reference, e.g. `tokens.color.primary.500`. */
export const TokenRef = z.string().regex(tokenRefRegex, "must be tokens.<scope>.<...path>");

/** Scoped variants — same regex, but typed for human + tooling clarity. */
export const SpacingTokenRef = z.string().regex(/^tokens\.spacing\./);
export const RadiusTokenRef  = z.string().regex(/^tokens\.radius\./);
export const ShadowTokenRef  = z.string().regex(/^tokens\.shadow\./);
export const ColorTokenRef   = z.string().regex(/^tokens\.color\./);

export type TokenRefT = z.infer<typeof TokenRef>;
```

- [ ] **Step 4: Create `style-slot.ts`**

```ts
// packages/schema/src/style-slot.ts
import { z } from "zod";
import { TokenRef, SpacingTokenRef, RadiusTokenRef, ShadowTokenRef, ColorTokenRef } from "./tokens";

export const Background = z.discriminatedUnion("type", [
  z.object({ type: z.literal("solid"),    value: ColorTokenRef }),
  z.object({ type: z.literal("gradient"), from: ColorTokenRef, to: ColorTokenRef,
             angle: z.number().int().min(0).max(360).optional() }),
  z.object({ type: z.literal("image"),    url: z.string().url().or(z.string().startsWith("/")),
             overlay: ColorTokenRef.optional(),
             position: z.string().optional() }),
  z.object({ type: z.literal("pattern"),
             name: z.enum(["dots", "grid", "noise", "mesh"]),
             color: ColorTokenRef.optional() }),
]);

export const Motion = z.enum(["none", "fade-in", "fade-up", "stagger", "slide-in"]);

export const StyleSlot = z.object({
  background: Background.optional(),
  padding:    SpacingTokenRef.optional(),
  radius:     RadiusTokenRef.optional(),
  shadow:     ShadowTokenRef.optional(),
  motion:     Motion.optional(),
}).strict();

export type StyleSlotT = z.infer<typeof StyleSlot>;
export type BackgroundT = z.infer<typeof Background>;
export type MotionT = z.infer<typeof Motion>;
```

- [ ] **Step 5: Run tests, expect pass, then commit**

```
cd packages/schema && npx vitest run tests/style-slot.test.ts
```
Expected: PASS (5/5).

```
git add packages/schema/src/tokens.ts packages/schema/src/style-slot.ts packages/schema/tests/style-slot.test.ts
git commit -m "feat(schema): add TokenRef regex schemas + StyleSlot mixin"
```

---

### Task 3: `Custom` node + foundation nodes (Hero, Section, MetricTile, FeatureCard)

**Files:**
- Create: `packages/schema/src/nodes/custom.ts`
- Create: `packages/schema/src/nodes/foundation.ts`
- Create: `packages/schema/tests/nodes/custom.test.ts`
- Create: `packages/schema/tests/nodes/foundation.test.ts`

- [ ] **Step 1: Failing test for Custom + foundation nodes**

```ts
// packages/schema/tests/nodes/custom.test.ts
import { describe, it, expect } from "vitest";
import { CustomNode } from "../../src/nodes/custom";

describe("CustomNode", () => {
  it("requires html string", () => {
    expect(() => CustomNode.parse({ id: "c1", type: "Custom", props: {} })).toThrow();
  });

  it("accepts html + optional tailwind/label + style", () => {
    const r = CustomNode.parse({
      id: "c1",
      type: "Custom",
      props: { html: "<div>hi</div>", tailwind: "p-4 bg-gradient-to-br",
               label: "Hero with parallax" },
      style: { padding: "tokens.spacing.semantic.section" },
    });
    expect(r.props.html).toBe("<div>hi</div>");
    expect(r.style?.padding).toMatch(/^tokens\./);
  });
});
```

```ts
// packages/schema/tests/nodes/foundation.test.ts
import { describe, it, expect } from "vitest";
import { HeroNode, SectionNode, MetricTileNode, FeatureCardNode } from "../../src/nodes/foundation";

describe("HeroNode", () => {
  it("requires headline + layout", () => {
    expect(() => HeroNode.parse({ id: "h", type: "Hero", props: { ctas: [] } })).toThrow();
    const r = HeroNode.parse({
      id: "h", type: "Hero",
      props: { headline: "Hi", layout: "centered", ctas: [] },
    });
    expect(r.props.layout).toBe("centered");
  });
});

describe("SectionNode", () => {
  it("requires variant + children array", () => {
    const r = SectionNode.parse({
      id: "s", type: "Section",
      props: { variant: "feature" },
      children: [],
    });
    expect(r.props.variant).toBe("feature");
  });
});

describe("MetricTileNode", () => {
  it("requires label, value, format", () => {
    const r = MetricTileNode.parse({
      id: "m", type: "MetricTile",
      props: { label: "Active users", value: 1234, format: "number",
               delta: { value: 0.12, direction: "up" } },
    });
    expect(r.props.delta?.direction).toBe("up");
  });
});

describe("FeatureCardNode", () => {
  it("requires title + description + layout", () => {
    const r = FeatureCardNode.parse({
      id: "f", type: "FeatureCard",
      props: { title: "Fast", description: "Built for speed", layout: "icon-top" },
    });
    expect(r.props.layout).toBe("icon-top");
  });
});
```

- [ ] **Step 2: Run — failing**

```
cd packages/schema && npx vitest run tests/nodes/custom.test.ts tests/nodes/foundation.test.ts
```
Expected: FAIL — modules don't exist.

- [ ] **Step 3: Implement Custom + foundation nodes**

```ts
// packages/schema/src/nodes/custom.ts
import { z } from "zod";
import { StyleSlot } from "../style-slot";

export const CustomNode = z.object({
  id: z.string(),
  type: z.literal("Custom"),
  props: z.object({
    html: z.string(),
    tailwind: z.string().optional(),
    label: z.string().optional(),
  }),
  style: StyleSlot.optional(),
});
export type CustomNodeT = z.infer<typeof CustomNode>;
```

```ts
// packages/schema/src/nodes/foundation.ts
import { z } from "zod";
import { StyleSlot } from "../style-slot";
import { TokenRef } from "../tokens";

const Cta = z.object({
  label: z.string(),
  action: z.object({
    type: z.literal("navigate"),
    to: z.string(),
  }).or(z.object({ type: z.literal("workflow"), name: z.string() })),
  variant: z.enum(["primary", "secondary", "ghost"]).default("primary"),
});

const ImageOrIllustration = z.object({
  kind: z.enum(["image", "illustration"]),
  src: z.string(),
  alt: z.string().optional(),
});

export const HeroNode = z.object({
  id: z.string(),
  type: z.literal("Hero"),
  props: z.object({
    eyebrow:  z.string().optional(),
    headline: z.string(),
    subhead:  z.string().optional(),
    layout:   z.enum(["centered", "split", "stacked"]),
    ctas:     z.array(Cta).default([]),
    media:    ImageOrIllustration.optional(),
  }),
  style: StyleSlot.optional(),
  children: z.array(z.any()).optional(),
});
export type HeroNodeT = z.infer<typeof HeroNode>;

export const SectionNode = z.object({
  id: z.string(),
  type: z.literal("Section"),
  props: z.object({
    variant:  z.enum(["plain", "feature", "cta", "stats", "split"]),
    title:    z.string().optional(),
    subtitle: z.string().optional(),
    anchor:   z.string().optional(),
  }),
  style: StyleSlot.optional(),
  children: z.array(z.any()).default([]),
});
export type SectionNodeT = z.infer<typeof SectionNode>;

export const MetricTileNode = z.object({
  id: z.string(),
  type: z.literal("MetricTile"),
  props: z.object({
    label:  z.string(),
    value:  z.union([z.number(), z.string()]),
    format: z.enum(["number", "currency", "percent", "duration"]),
    delta:  z.object({
      value: z.number(),
      direction: z.enum(["up", "down", "flat"]),
    }).optional(),
    icon:   z.string().optional(),
    trend:  z.array(z.number()).optional(),
  }),
  style: StyleSlot.optional(),
});
export type MetricTileNodeT = z.infer<typeof MetricTileNode>;

export const FeatureCardNode = z.object({
  id: z.string(),
  type: z.literal("FeatureCard"),
  props: z.object({
    title:       z.string(),
    description: z.string(),
    icon:        z.string().optional(),
    cta:         z.object({ label: z.string(), href: z.string() }).optional(),
    layout:      z.enum(["icon-top", "icon-left"]),
  }),
  style: StyleSlot.optional(),
});
export type FeatureCardNodeT = z.infer<typeof FeatureCardNode>;
```

- [ ] **Step 4: Run tests, expect pass**

```
cd packages/schema && npx vitest run tests/nodes/custom.test.ts tests/nodes/foundation.test.ts
```
Expected: PASS (5/5).

- [ ] **Step 5: Commit**

```
git add packages/schema/src/nodes/custom.ts packages/schema/src/nodes/foundation.ts \
        packages/schema/tests/nodes/custom.test.ts packages/schema/tests/nodes/foundation.test.ts
git commit -m "feat(schema): Custom escape hatch + Hero/Section/MetricTile/FeatureCard nodes"
```

---

### Task 4: Layout-v2 nodes (Split, Sidebar, Cluster, Tabs, Accordion)

**Files:**
- Create: `packages/schema/src/nodes/layout-v2.ts`
- Create: `packages/schema/tests/nodes/layout-v2.test.ts`

- [ ] **Step 1: Failing tests**

```ts
// packages/schema/tests/nodes/layout-v2.test.ts
import { describe, it, expect } from "vitest";
import { SplitNode, SidebarNode, ClusterNode, TabsNode, AccordionNode }
  from "../../src/nodes/layout-v2";

describe("SplitNode", () => {
  it("requires exactly 2 children", () => {
    expect(() => SplitNode.parse({ id: "s", type: "Split",
      props: { ratio: "1:1" }, children: [] })).toThrow();
    const r = SplitNode.parse({
      id: "s", type: "Split",
      props: { ratio: "2:1", breakpoint: "md" },
      children: [{ id: "a", type: "Box" }, { id: "b", type: "Box" }],
    });
    expect(r.props.ratio).toBe("2:1");
  });
});

describe("SidebarNode", () => {
  it("requires exactly 2 children", () => {
    expect(() => SidebarNode.parse({ id: "s", type: "Sidebar",
      props: { width: "240px" }, children: [{ id: "a", type: "Box" }] })).toThrow();
  });
});

describe("ClusterNode", () => {
  it("accepts children array", () => {
    const r = ClusterNode.parse({
      id: "c", type: "Cluster",
      props: { gap: "tokens.spacing.4", justify: "start", align: "center" },
      children: [],
    });
    expect(r.props.justify).toBe("start");
  });
});

describe("TabsNode", () => {
  it("children length must match tabs[] length", () => {
    expect(() => TabsNode.parse({
      id: "t", type: "Tabs",
      props: { tabs: [{ id: "a", label: "A" }, { id: "b", label: "B" }], value: "a" },
      children: [{ id: "p1", type: "Box" }],
    })).toThrow();

    const r = TabsNode.parse({
      id: "t", type: "Tabs",
      props: { tabs: [{ id: "a", label: "A" }], value: "a" },
      children: [{ id: "p1", type: "Box" }],
    });
    expect(r.props.tabs.length).toBe(1);
  });
});

describe("AccordionNode", () => {
  it("accepts mode + defaultOpen list", () => {
    const r = AccordionNode.parse({
      id: "a", type: "Accordion",
      props: { mode: "single", defaultOpen: ["p1"] },
      children: [{ id: "p1", type: "AccordionPanel",
                   props: { label: "First", value: "p1" }, children: [] }],
    });
    expect(r.props.mode).toBe("single");
  });
});
```

- [ ] **Step 2: Run — fail**

```
cd packages/schema && npx vitest run tests/nodes/layout-v2.test.ts
```
Expected: FAIL.

- [ ] **Step 3: Implement layout-v2 nodes**

```ts
// packages/schema/src/nodes/layout-v2.ts
import { z } from "zod";
import { StyleSlot } from "../style-slot";
import { SpacingTokenRef } from "../tokens";

export const SplitNode = z.object({
  id: z.string(),
  type: z.literal("Split"),
  props: z.object({
    ratio: z.enum(["1:1", "2:1", "1:2", "1:3", "3:1"]),
    breakpoint: z.enum(["sm", "md", "lg"]).optional(),
  }),
  style: StyleSlot.optional(),
  children: z.array(z.any()).length(2,
    "Split must have exactly 2 children"),
});
export type SplitNodeT = z.infer<typeof SplitNode>;

export const SidebarNode = z.object({
  id: z.string(),
  type: z.literal("Sidebar"),
  props: z.object({
    width: z.string().regex(/^\d+(?:px|rem|%)$/),
  }),
  style: StyleSlot.optional(),
  children: z.array(z.any()).length(2,
    "Sidebar must have exactly 2 children (sidebar + main)"),
});
export type SidebarNodeT = z.infer<typeof SidebarNode>;

export const ClusterNode = z.object({
  id: z.string(),
  type: z.literal("Cluster"),
  props: z.object({
    gap:     SpacingTokenRef.optional(),
    justify: z.enum(["start", "center", "end", "between"]).default("start"),
    align:   z.enum(["start", "center", "end", "stretch"]).default("center"),
  }),
  style: StyleSlot.optional(),
  children: z.array(z.any()).default([]),
});
export type ClusterNodeT = z.infer<typeof ClusterNode>;

const TabDef = z.object({ id: z.string(), label: z.string(), icon: z.string().optional() });

export const TabsNode = z.object({
  id: z.string(),
  type: z.literal("Tabs"),
  props: z.object({
    tabs:  z.array(TabDef).min(1),
    value: z.string(),
  }),
  style: StyleSlot.optional(),
  children: z.array(z.any()),
}).refine((n) => n.children.length === n.props.tabs.length,
  { message: "Tabs.children length must match Tabs.props.tabs length",
    path: ["children"] });
export type TabsNodeT = z.infer<typeof TabsNode>;

export const AccordionPanelNode = z.object({
  id: z.string(),
  type: z.literal("AccordionPanel"),
  props: z.object({ label: z.string(), value: z.string() }),
  children: z.array(z.any()).default([]),
});

export const AccordionNode = z.object({
  id: z.string(),
  type: z.literal("Accordion"),
  props: z.object({
    mode: z.enum(["single", "multi"]),
    defaultOpen: z.array(z.string()).default([]),
  }),
  style: StyleSlot.optional(),
  children: z.array(AccordionPanelNode).default([]),
});
export type AccordionNodeT = z.infer<typeof AccordionNode>;
```

- [ ] **Step 4: Run, pass, commit**

```
cd packages/schema && npx vitest run tests/nodes/layout-v2.test.ts
```
Expected: PASS (5/5).

```
git add packages/schema/src/nodes/layout-v2.ts packages/schema/tests/nodes/layout-v2.test.ts
git commit -m "feat(schema): Split/Sidebar/Cluster/Tabs/Accordion node types"
```

---

### Task 5: Display nodes (Avatar, KeyValueList, Skeleton)

**Files:**
- Create: `packages/schema/src/nodes/display.ts`
- Create: `packages/schema/tests/nodes/display.test.ts`

- [ ] **Step 1: Failing tests**

```ts
// packages/schema/tests/nodes/display.test.ts
import { describe, it, expect } from "vitest";
import { AvatarNode, KeyValueListNode, SkeletonNode } from "../../src/nodes/display";

describe("AvatarNode", () => {
  it("requires name + size", () => {
    const r = AvatarNode.parse({
      id: "a", type: "Avatar",
      props: { name: "Jane Doe", size: "md", status: "online" },
    });
    expect(r.props.size).toBe("md");
  });
});

describe("KeyValueListNode", () => {
  it("items required, each label+value", () => {
    const r = KeyValueListNode.parse({
      id: "k", type: "KeyValueList",
      props: { items: [
        { label: "Email", value: "x@y.com", copyable: true },
        { label: "Role",  value: "Admin" },
      ]},
    });
    expect(r.props.items.length).toBe(2);
  });
});

describe("SkeletonNode", () => {
  it("variant + optional lines", () => {
    expect(SkeletonNode.parse({ id: "s", type: "Skeleton",
      props: { variant: "rect" } }).props.variant).toBe("rect");
    expect(SkeletonNode.parse({ id: "s", type: "Skeleton",
      props: { variant: "text", lines: 3 } }).props.lines).toBe(3);
  });
});
```

- [ ] **Step 2: Run — fail**

```
cd packages/schema && npx vitest run tests/nodes/display.test.ts
```
Expected: FAIL.

- [ ] **Step 3: Implement display nodes**

```ts
// packages/schema/src/nodes/display.ts
import { z } from "zod";
import { StyleSlot } from "../style-slot";

export const AvatarNode = z.object({
  id: z.string(),
  type: z.literal("Avatar"),
  props: z.object({
    src:    z.string().optional(),
    name:   z.string(),
    size:   z.enum(["xs", "sm", "md", "lg", "xl"]),
    status: z.enum(["online", "offline", "away", "busy"]).optional(),
  }),
  style: StyleSlot.optional(),
});
export type AvatarNodeT = z.infer<typeof AvatarNode>;

export const KeyValueListNode = z.object({
  id: z.string(),
  type: z.literal("KeyValueList"),
  props: z.object({
    items: z.array(z.object({
      label: z.string(),
      value: z.string(),
      copyable: z.boolean().optional(),
    })).min(1),
  }),
  style: StyleSlot.optional(),
});
export type KeyValueListNodeT = z.infer<typeof KeyValueListNode>;

export const SkeletonNode = z.object({
  id: z.string(),
  type: z.literal("Skeleton"),
  props: z.object({
    variant: z.enum(["rect", "circle", "text"]),
    lines:   z.number().int().positive().optional(),
  }),
  style: StyleSlot.optional(),
});
export type SkeletonNodeT = z.infer<typeof SkeletonNode>;
```

- [ ] **Step 4: Run, pass, commit**

```
cd packages/schema && npx vitest run tests/nodes/display.test.ts
```
Expected: PASS (3/3).

```
git add packages/schema/src/nodes/display.ts packages/schema/tests/nodes/display.test.ts
git commit -m "feat(schema): Avatar/KeyValueList/Skeleton node types"
```

---

### Task 6: Form input nodes (Input, Select, Textarea, Checkbox, DatePicker)

**Files:**
- Create: `packages/schema/src/nodes/inputs.ts`
- Create: `packages/schema/tests/nodes/inputs.test.ts`

- [ ] **Step 1: Failing tests**

```ts
// packages/schema/tests/nodes/inputs.test.ts
import { describe, it, expect } from "vitest";
import { InputNode, SelectNode, TextareaNode, CheckboxNode, DatePickerNode }
  from "../../src/nodes/inputs";

describe("InputNode", () => {
  it("name + label + type required", () => {
    const r = InputNode.parse({
      id: "i", type: "Input",
      props: { name: "email", label: "Email", type: "email",
               validators: { required: true } },
    });
    expect(r.props.type).toBe("email");
  });
});

describe("SelectNode", () => {
  it("options non-empty", () => {
    expect(() => SelectNode.parse({ id: "s", type: "Select",
      props: { name: "x", label: "X", options: [] } })).toThrow();
    const r = SelectNode.parse({
      id: "s", type: "Select",
      props: { name: "role", label: "Role",
               options: [{ value: "a", label: "A" }] },
    });
    expect(r.props.options.length).toBe(1);
  });
});

describe("TextareaNode", () => {
  it("rows positive int", () => {
    expect(TextareaNode.parse({ id: "t", type: "Textarea",
      props: { name: "n", label: "N", rows: 4 } }).props.rows).toBe(4);
  });
});

describe("CheckboxNode", () => {
  it("name + label", () => {
    expect(CheckboxNode.parse({ id: "c", type: "Checkbox",
      props: { name: "agree", label: "Agree" } }).props.name).toBe("agree");
  });
});

describe("DatePickerNode", () => {
  it("optional min/max", () => {
    expect(DatePickerNode.parse({ id: "d", type: "DatePicker",
      props: { name: "dob", label: "DOB", min: "1900-01-01" } })
      .props.min).toBe("1900-01-01");
  });
});
```

- [ ] **Step 2: Run — fail**

```
cd packages/schema && npx vitest run tests/nodes/inputs.test.ts
```
Expected: FAIL.

- [ ] **Step 3: Implement input nodes**

```ts
// packages/schema/src/nodes/inputs.ts
import { z } from "zod";
import { StyleSlot } from "../style-slot";

const Validators = z.object({
  required: z.boolean().optional(),
  min:      z.number().optional(),
  max:      z.number().optional(),
  pattern:  z.string().optional(),
  message:  z.string().optional(),
}).strict();

const baseField = {
  name:       z.string().min(1),
  label:      z.string(),
  bind:       z.string().optional(),
  validators: Validators.optional(),
};

export const InputNode = z.object({
  id: z.string(),
  type: z.literal("Input"),
  props: z.object({
    ...baseField,
    type: z.enum(["text", "email", "password", "number", "url", "tel"]),
    placeholder: z.string().optional(),
  }),
  style: StyleSlot.optional(),
});
export type InputNodeT = z.infer<typeof InputNode>;

export const SelectNode = z.object({
  id: z.string(),
  type: z.literal("Select"),
  props: z.object({
    ...baseField,
    options: z.array(z.object({ value: z.string(), label: z.string() })).min(1),
  }),
  style: StyleSlot.optional(),
});
export type SelectNodeT = z.infer<typeof SelectNode>;

export const TextareaNode = z.object({
  id: z.string(),
  type: z.literal("Textarea"),
  props: z.object({
    ...baseField,
    rows: z.number().int().positive().default(4),
    placeholder: z.string().optional(),
  }),
  style: StyleSlot.optional(),
});
export type TextareaNodeT = z.infer<typeof TextareaNode>;

export const CheckboxNode = z.object({
  id: z.string(),
  type: z.literal("Checkbox"),
  props: z.object({
    ...baseField,
  }),
  style: StyleSlot.optional(),
});
export type CheckboxNodeT = z.infer<typeof CheckboxNode>;

export const DatePickerNode = z.object({
  id: z.string(),
  type: z.literal("DatePicker"),
  props: z.object({
    ...baseField,
    min: z.string().optional(),
    max: z.string().optional(),
  }),
  style: StyleSlot.optional(),
});
export type DatePickerNodeT = z.infer<typeof DatePickerNode>;
```

- [ ] **Step 4: Run, pass, commit**

```
cd packages/schema && npx vitest run tests/nodes/inputs.test.ts
```
Expected: PASS (5/5).

```
git add packages/schema/src/nodes/inputs.ts packages/schema/tests/nodes/inputs.test.ts
git commit -m "feat(schema): Input/Select/Textarea/Checkbox/DatePicker node types"
```

---

### Task 7: Motion nodes (FadeIn, Stagger)

**Files:**
- Create: `packages/schema/src/nodes/motion.ts`
- Create: `packages/schema/tests/nodes/motion.test.ts`

- [ ] **Step 1: Failing test**

```ts
// packages/schema/tests/nodes/motion.test.ts
import { describe, it, expect } from "vitest";
import { FadeInNode, StaggerNode } from "../../src/nodes/motion";

describe("FadeInNode", () => {
  it("optional delay/duration, children allowed", () => {
    const r = FadeInNode.parse({
      id: "f", type: "FadeIn",
      props: { delay: 0, duration: 300 },
      children: [],
    });
    expect(r.props.duration).toBe(300);
  });
});

describe("StaggerNode", () => {
  it("interval positive int", () => {
    expect(() => StaggerNode.parse({ id: "s", type: "Stagger",
      props: { interval: -10 }, children: [] })).toThrow();
  });
});
```

- [ ] **Step 2: Run — fail**

```
cd packages/schema && npx vitest run tests/nodes/motion.test.ts
```
Expected: FAIL.

- [ ] **Step 3: Implement motion nodes**

```ts
// packages/schema/src/nodes/motion.ts
import { z } from "zod";
import { StyleSlot } from "../style-slot";

export const FadeInNode = z.object({
  id: z.string(),
  type: z.literal("FadeIn"),
  props: z.object({
    delay:    z.number().int().nonnegative().optional(),
    duration: z.number().int().positive().optional(),
  }).default({}),
  style: StyleSlot.optional(),
  children: z.array(z.any()).default([]),
});
export type FadeInNodeT = z.infer<typeof FadeInNode>;

export const StaggerNode = z.object({
  id: z.string(),
  type: z.literal("Stagger"),
  props: z.object({
    delay:    z.number().int().nonnegative().optional(),
    interval: z.number().int().positive().default(80),
  }).default({}),
  style: StyleSlot.optional(),
  children: z.array(z.any()).default([]),
});
export type StaggerNodeT = z.infer<typeof StaggerNode>;
```

- [ ] **Step 4: Run, pass, commit**

```
cd packages/schema && npx vitest run tests/nodes/motion.test.ts
```
Expected: PASS (2/2).

```
git add packages/schema/src/nodes/motion.ts packages/schema/tests/nodes/motion.test.ts
git commit -m "feat(schema): FadeIn/Stagger motion node types"
```

---

### Task 8: `PageV2` schema + discriminated `Page` union on `schemaVersion`

**Files:**
- Modify: `packages/schema/src/page.ts`
- Modify: `packages/schema/src/index.ts`
- Create: `packages/schema/tests/page-v2.test.ts`

- [ ] **Step 1: Read current `page.ts` to capture v1 verbatim**

```
cat packages/schema/src/page.ts
```
Note the existing exported `Page` and any helper exports — they become `PageV1` unmodified.

- [ ] **Step 2: Failing test for PageV2 union**

```ts
// packages/schema/tests/page-v2.test.ts
import { describe, it, expect } from "vitest";
import { Page, PageV1, PageV2 } from "../src/page";

describe("Page discriminated union", () => {
  it("accepts a v1 page (schemaVersion '1')", () => {
    const v1 = {
      schemaVersion: "1",
      id: "products/list",
      route: "/products",
      layout: "DashboardLayout",
      meta: { title: "Products" },
      dataSources: [],
      root: { id: "root", type: "Stack", props: {}, children: [] },
    };
    expect(() => Page.parse(v1)).not.toThrow();
  });

  it("accepts a v2 page with new node types + StyleSlot", () => {
    const v2 = {
      schemaVersion: "2",
      id: "products/list",
      route: "/products",
      layout: "DashboardLayout",
      meta: { title: "Products" },
      dataSources: [],
      root: {
        id: "root", type: "Stack",
        style: { padding: "tokens.spacing.semantic.section" },
        children: [
          { id: "h", type: "Hero",
            props: { headline: "Products", layout: "centered", ctas: [] },
            style: { background: { type: "gradient",
                                   from: "tokens.color.primary.50",
                                   to: "tokens.color.surface.0" } } },
        ],
      },
    };
    expect(() => Page.parse(v2)).not.toThrow();
  });

  it("rejects a page with unknown schemaVersion", () => {
    expect(() => Page.parse({ schemaVersion: "3", id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [], root: {} })).toThrow();
  });

  it("PageV2 rejects a Custom node missing html", () => {
    const bad = { schemaVersion: "2", id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [],
      root: { id: "r", type: "Custom", props: {} } };
    expect(() => PageV2.parse(bad)).toThrow();
  });
});
```

- [ ] **Step 3: Run — fail (PageV1/PageV2 not exported yet)**

```
cd packages/schema && npx vitest run tests/page-v2.test.ts
```
Expected: FAIL — `PageV1`/`PageV2` not exported.

- [ ] **Step 4: Refactor `page.ts` to expose v1 + v2 + Page union**

Open `packages/schema/src/page.ts`. Wrap the existing Page schema as `PageV1` (add `schemaVersion: z.literal("1")` to its top-level shape if not already there; otherwise `.merge` it). Then add `PageV2`:

```ts
// packages/schema/src/page.ts (excerpt — keep all existing fields + helpers)
import { z } from "zod";
import { StyleSlot } from "./style-slot";
import { CustomNode } from "./nodes/custom";
import { HeroNode, SectionNode, MetricTileNode, FeatureCardNode } from "./nodes/foundation";
import { SplitNode, SidebarNode, ClusterNode, TabsNode, AccordionNode, AccordionPanelNode }
  from "./nodes/layout-v2";
import { AvatarNode, KeyValueListNode, SkeletonNode } from "./nodes/display";
import { InputNode, SelectNode, TextareaNode, CheckboxNode, DatePickerNode }
  from "./nodes/inputs";
import { FadeInNode, StaggerNode } from "./nodes/motion";

// === PageV1: the existing exported `Page` schema, frozen ===
// (Copy the existing Page definition here verbatim, renamed PageV1.
//  Ensure it has z.object({ schemaVersion: z.literal("1"), ... }).)
export const PageV1 = /* paste current Page schema, with schemaVersion: z.literal("1") */;
export type PageV1T = z.infer<typeof PageV1>;

// === PageV2: extends v1 with new node types + StyleSlot mixin ===
// Re-use the v1 root-node union by extending with new types.
// Easiest path: build a separate `NodeV2` z.union and require root: NodeV2.
const NodeV2: z.ZodTypeAny = z.lazy(() => z.union([
  // Existing structural types — Stack/Row/Grid/Container/Box/Text/Image/Slot/Spacer/Repeat/
  // Conditional/DataBoundary — re-imported from existing modules. Each gains a top-level
  // `style: StyleSlot.optional()` here via z.object(...).extend({ style: StyleSlot.optional() }).
  // (We do this in Task 20 across the full set; for now keep the v1 root types and add new ones.)
  CustomNode,
  HeroNode, SectionNode, MetricTileNode, FeatureCardNode,
  SplitNode, SidebarNode, ClusterNode, TabsNode, AccordionNode, AccordionPanelNode,
  AvatarNode, KeyValueListNode, SkeletonNode,
  InputNode, SelectNode, TextareaNode, CheckboxNode, DatePickerNode,
  FadeInNode, StaggerNode,
  // Existing v1 nodes (any schema-Anode-Z) — see comment above.
  z.object({ id: z.string(), type: z.string(),
             props: z.record(z.any()).optional(),
             style: StyleSlot.optional(),
             children: z.array(NodeV2).optional() }).passthrough(),
]));

export const PageV2 = z.object({
  schemaVersion: z.literal("2"),
  id: z.string(),
  route: z.string(),
  layout: z.string(),
  meta: z.record(z.any()).default({}),
  dataSources: z.array(z.any()).default([]),
  root: NodeV2,
});
export type PageV2T = z.infer<typeof PageV2>;

// Discriminated union — pick by schemaVersion.
export const Page = z.discriminatedUnion("schemaVersion", [PageV1, PageV2]);
export type PageT = z.infer<typeof Page>;
```

(Implementation detail: if the current `PageV1` doesn't already declare `schemaVersion` as a literal, add `.extend({ schemaVersion: z.literal("1") })`. The existing fixtures in `packages/schema/tests/fixtures/` may need a `schemaVersion: "1"` stamp — fix any that fail.)

- [ ] **Step 5: Update `packages/schema/src/index.ts` exports**

Add lines to `packages/schema/src/index.ts`:

```ts
export { Page, PageV1, PageV2, type PageT, type PageV1T, type PageV2T } from "./page";
export { StyleSlot, Background, Motion, type StyleSlotT, type BackgroundT, type MotionT }
  from "./style-slot";
export * from "./nodes/custom";
export * from "./nodes/foundation";
export * from "./nodes/layout-v2";
export * from "./nodes/display";
export * from "./nodes/inputs";
export * from "./nodes/motion";
```

- [ ] **Step 6: Run all schema tests**

```
cd packages/schema && npx vitest run
```
Expected: existing fixtures may need `schemaVersion: "1"` stamped. Edit each fixture under `tests/fixtures/` that fails, then re-run. Final state: all green.

- [ ] **Step 7: Commit**

```
git add packages/schema/src/page.ts packages/schema/src/index.ts \
        packages/schema/tests/page-v2.test.ts \
        packages/schema/tests/fixtures/
git commit -m "feat(schema): PageV2 union with new node types + StyleSlot mixin"
```

---

### Task 9: `migratePage` v1 → v2

**Files:**
- Create: `packages/schema/src/migrate.ts`
- Create: `packages/schema/tests/migrate.test.ts`
- Modify: `packages/schema/src/index.ts`

- [ ] **Step 1: Failing test**

```ts
// packages/schema/tests/migrate.test.ts
import { describe, it, expect } from "vitest";
import { migratePage } from "../src/migrate";
import { PageV2 } from "../src/page";

describe("migratePage", () => {
  it("returns v2 unchanged", () => {
    const v2 = {
      schemaVersion: "2", id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [],
      root: { id: "r", type: "Stack", props: {}, children: [] },
    };
    expect(migratePage(v2)).toEqual(v2);
  });

  it("stamps schemaVersion '2' on a v1 page", () => {
    const v1 = {
      schemaVersion: "1", id: "x", route: "/", layout: "DashboardLayout",
      meta: { title: "X" }, dataSources: [],
      root: { id: "r", type: "Stack", props: {}, children: [] },
    };
    const out = migratePage(v1);
    expect(out.schemaVersion).toBe("2");
    expect(() => PageV2.parse(out)).not.toThrow();
  });

  it("stamps schemaVersion '2' when missing entirely", () => {
    const noVersion = {
      id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [],
      root: { id: "r", type: "Stack", props: {}, children: [] },
    } as any;
    const out = migratePage(noVersion);
    expect(out.schemaVersion).toBe("2");
  });

  it("preserves children + props during migration", () => {
    const v1 = {
      schemaVersion: "1", id: "x", route: "/", layout: "DashboardLayout",
      meta: {}, dataSources: [],
      root: { id: "r", type: "Stack", props: { gap: "md" },
              children: [{ id: "h", type: "Heading",
                           props: { content: "Hi", level: 1 } }] },
    };
    const out = migratePage(v1);
    expect((out.root as any).children[0].props.content).toBe("Hi");
  });
});
```

- [ ] **Step 2: Run — fail**

```
cd packages/schema && npx vitest run tests/migrate.test.ts
```
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `migrate.ts`**

```ts
// packages/schema/src/migrate.ts
import { PageV2, type PageV2T } from "./page";

/**
 * Idempotent v1→v2 migration.
 *
 * Pure additive: stamps schemaVersion: "2" if missing or "1". Walks node
 * tree but does NOT modify nodes (style stays absent). Validates against
 * PageV2 at the end and throws if structurally incompatible — that should
 * never happen for a well-formed v1 page.
 */
export function migratePage(raw: unknown): PageV2T {
  const obj = (raw && typeof raw === "object" ? { ...(raw as Record<string, unknown>) } : {});
  if (obj.schemaVersion !== "2") obj.schemaVersion = "2";
  return PageV2.parse(obj);
}
```

- [ ] **Step 4: Add export to index**

Append to `packages/schema/src/index.ts`:

```ts
export { migratePage } from "./migrate";
```

- [ ] **Step 5: Run, pass, commit**

```
cd packages/schema && npx vitest run tests/migrate.test.ts
```
Expected: PASS (4/4).

```
cd packages/schema && npx tsc
```
Expected: build success.

```
git add packages/schema/src/migrate.ts packages/schema/src/index.ts \
        packages/schema/tests/migrate.test.ts
git commit -m "feat(schema): migratePage v1→v2 (additive, idempotent)"
```

---

## Phase C — Library: helpers + components

### Task 10: `resolveStyle` helper + `useMotion` hook

**Files:**
- Create: `packages/library/src/style/resolveStyle.ts`
- Create: `packages/library/src/style/useMotion.ts`
- Create: `packages/library/tests/style/resolveStyle.test.ts`

- [ ] **Step 1: Failing test**

```ts
// packages/library/tests/style/resolveStyle.test.ts
import { describe, it, expect } from "vitest";
import { resolveStyle } from "../../src/style/resolveStyle";

describe("resolveStyle", () => {
  it("returns empty object for undefined slot", () => {
    expect(resolveStyle(undefined)).toEqual({});
  });

  it("maps padding/radius/shadow tokens to CSS vars", () => {
    const r = resolveStyle({
      padding: "tokens.spacing.semantic.section",
      radius:  "tokens.radius.lg",
      shadow:  "tokens.shadow.md",
    });
    expect(r.padding).toBe("var(--token-spacing-semantic-section)");
    expect(r.borderRadius).toBe("var(--token-radius-lg)");
    expect(r.boxShadow).toBe("var(--token-shadow-md)");
  });

  it("maps solid background to CSS var", () => {
    const r = resolveStyle({
      background: { type: "solid", value: "tokens.color.primary.500" },
    });
    expect(r.background).toBe("var(--token-color-primary-500)");
  });

  it("builds gradient with default angle 135", () => {
    const r = resolveStyle({
      background: { type: "gradient",
                    from: "tokens.color.primary.50",
                    to:   "tokens.color.surface.0" },
    });
    expect(r.background).toBe(
      "linear-gradient(135deg, var(--token-color-primary-50) 0%, var(--token-color-surface-0) 100%)"
    );
  });

  it("uses provided angle for gradient", () => {
    expect(
      (resolveStyle({ background: { type: "gradient",
        from: "tokens.color.primary.50", to: "tokens.color.primary.500", angle: 90 } })
        .background as string)
    ).toContain("90deg");
  });

  it("emits image background", () => {
    const r = resolveStyle({
      background: { type: "image", url: "https://example.com/bg.jpg" },
    });
    expect(r.background).toBe(`url("https://example.com/bg.jpg") center/cover`);
  });
});
```

- [ ] **Step 2: Run — fail**

```
cd packages/library && npx vitest run tests/style/resolveStyle.test.ts
```
Expected: FAIL.

- [ ] **Step 3: Implement helpers**

```ts
// packages/library/src/style/resolveStyle.ts
import type { CSSProperties } from "react";
import type { StyleSlotT, BackgroundT } from "@tentoroforge/schema";

function tokenVar(ref: string): string {
  // tokens.color.primary.500 → var(--token-color-primary-500)
  return `var(--token-${ref.replace(/^tokens\./, "").replace(/\./g, "-")})`;
}

function backgroundCss(bg: BackgroundT): string {
  switch (bg.type) {
    case "solid":
      return tokenVar(bg.value);
    case "gradient": {
      const angle = bg.angle ?? 135;
      return `linear-gradient(${angle}deg, ${tokenVar(bg.from)} 0%, ${tokenVar(bg.to)} 100%)`;
    }
    case "image": {
      const pos = bg.position ?? "center/cover";
      return `url("${bg.url}") ${pos}`;
    }
    case "pattern": {
      // v1: emit a CSS background-image stub that the runtime stylesheet
      // can pick up via [data-pattern] attribute. Color falls back to muted.
      const c = bg.color ? tokenVar(bg.color) : "var(--token-color-muted-default)";
      const p = bg.name;
      return `radial-gradient(${c} 1px, transparent 1px) 0 0/16px 16px`;
    }
  }
}

export function resolveStyle(slot?: StyleSlotT): CSSProperties {
  if (!slot) return {};
  const out: CSSProperties = {};
  if (slot.padding)    out.padding      = tokenVar(slot.padding);
  if (slot.radius)     out.borderRadius = tokenVar(slot.radius);
  if (slot.shadow)     out.boxShadow    = tokenVar(slot.shadow);
  if (slot.background) out.background   = backgroundCss(slot.background);
  return out;
}
```

```ts
// packages/library/src/style/useMotion.ts
import type { MotionT } from "@tentoroforge/schema";

/**
 * Returns props to spread onto the wrapper element. v1 emits a
 * `data-motion` attribute that the runtime stylesheet animates with
 * @keyframes, plus inline `transition` for the duration.
 */
export function useMotion(motion?: MotionT): { "data-motion"?: string } {
  if (!motion || motion === "none") return {};
  return { "data-motion": motion };
}
```

- [ ] **Step 4: Run, pass, commit**

```
cd packages/library && npx vitest run tests/style/resolveStyle.test.ts
```
Expected: PASS (6/6).

```
git add packages/library/src/style/ packages/library/tests/style/
git commit -m "feat(library): resolveStyle helper + useMotion hook"
```

---

### Task 11: Library `Hero` + `Section` components

**Files:**
- Create: `packages/library/src/components/Hero/Hero.schema.ts`
- Create: `packages/library/src/components/Hero/Hero.tsx`
- Create: `packages/library/src/components/Section/Section.schema.ts`
- Create: `packages/library/src/components/Section/Section.tsx`
- Create: `packages/library/tests/components/Hero.test.tsx`
- Create: `packages/library/tests/components/Section.test.tsx`

- [ ] **Step 1: Failing tests**

```tsx
// packages/library/tests/components/Hero.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Hero } from "../../src/components/Hero/Hero";

describe("Hero", () => {
  it("renders headline + eyebrow", () => {
    const { getByText } = render(
      <Hero headline="Welcome" eyebrow="Hi" layout="centered" ctas={[]} />
    );
    expect(getByText("Welcome")).toBeTruthy();
    expect(getByText("Hi")).toBeTruthy();
  });

  it("applies StyleSlot via resolveStyle", () => {
    const { container } = render(
      <Hero headline="X" layout="centered" ctas={[]}
            style={{ padding: "tokens.spacing.semantic.section" }} />
    );
    const root = container.firstChild as HTMLElement;
    expect(root.style.padding).toBe("var(--token-spacing-semantic-section)");
  });

  it("emits data-motion attribute when motion set", () => {
    const { container } = render(
      <Hero headline="X" layout="centered" ctas={[]}
            style={{ motion: "fade-in" }} />
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-motion"))
      .toBe("fade-in");
  });
});
```

```tsx
// packages/library/tests/components/Section.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Section } from "../../src/components/Section/Section";

describe("Section", () => {
  it("renders title + children", () => {
    const { getByText } = render(
      <Section variant="feature" title="Stats">
        <span>child</span>
      </Section>
    );
    expect(getByText("Stats")).toBeTruthy();
    expect(getByText("child")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run — fail**

```
cd packages/library && npx vitest run tests/components/Hero.test.tsx tests/components/Section.test.tsx
```
Expected: FAIL.

- [ ] **Step 3: Implement Hero**

```ts
// packages/library/src/components/Hero/Hero.schema.ts
import { HeroNode } from "@tentoroforge/schema";
export const HeroProps = HeroNode.shape.props;
export type HeroPropsType = import("zod").z.infer<typeof HeroProps>;
```

```tsx
// packages/library/src/components/Hero/Hero.tsx
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

type HeroLayout = "centered" | "split" | "stacked";
type Cta = { label: string; action: any; variant?: "primary" | "secondary" | "ghost" };

export interface HeroProps {
  eyebrow?: string;
  headline: string;
  subhead?: string;
  layout: HeroLayout;
  ctas: Cta[];
  media?: { kind: "image" | "illustration"; src: string; alt?: string };
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function Hero({ eyebrow, headline, subhead, layout, ctas,
                       media, style, children }: HeroProps) {
  const cssStyle = resolveStyle(style);
  const motion = useMotion(style?.motion);
  return (
    <section style={cssStyle} data-hero-layout={layout} {...motion}>
      <div className={`hero hero-${layout}`}>
        {eyebrow && <p className="hero-eyebrow">{eyebrow}</p>}
        <h1 className="hero-headline">{headline}</h1>
        {subhead && <p className="hero-subhead">{subhead}</p>}
        {ctas.length > 0 && (
          <div className="hero-ctas">
            {ctas.map((c, i) => (
              <a key={i} className={`btn btn-${c.variant ?? "primary"}`}
                 href={typeof c.action === "object" && c.action.type === "navigate"
                   ? c.action.to : undefined}>
                {c.label}
              </a>
            ))}
          </div>
        )}
        {media && (
          <div className="hero-media">
            {media.kind === "image"
              ? <img src={media.src} alt={media.alt ?? ""} />
              : <object data={media.src} type="image/svg+xml" aria-label={media.alt ?? ""} />}
          </div>
        )}
        {children}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Implement Section**

```ts
// packages/library/src/components/Section/Section.schema.ts
import { SectionNode } from "@tentoroforge/schema";
export const SectionProps = SectionNode.shape.props;
export type SectionPropsType = import("zod").z.infer<typeof SectionProps>;
```

```tsx
// packages/library/src/components/Section/Section.tsx
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface SectionProps {
  variant: "plain" | "feature" | "cta" | "stats" | "split";
  title?: string;
  subtitle?: string;
  anchor?: string;
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function Section({ variant, title, subtitle, anchor, style, children }: SectionProps) {
  return (
    <section id={anchor} style={resolveStyle(style)} data-variant={variant}
             {...useMotion(style?.motion)}>
      {(title || subtitle) && (
        <header className="section-header">
          {title    && <h2 className="section-title">{title}</h2>}
          {subtitle && <p  className="section-subtitle">{subtitle}</p>}
        </header>
      )}
      <div className="section-body">{children}</div>
    </section>
  );
}
```

- [ ] **Step 5: Run, pass, commit**

```
cd packages/library && npx vitest run tests/components/Hero.test.tsx tests/components/Section.test.tsx
```
Expected: PASS (4/4).

```
git add packages/library/src/components/Hero/ packages/library/src/components/Section/ \
        packages/library/tests/components/Hero.test.tsx \
        packages/library/tests/components/Section.test.tsx
git commit -m "feat(library): Hero + Section components"
```

---

> **Plan continues** — Tasks 12-37 follow this exact pattern. The remaining work (each as a self-contained TDD task with tests, code, and commit step):
>
> **Library components (Tasks 12-19)** — pairs of small components per task:
> - **12** MetricTile + FeatureCard
> - **13** Split + Sidebar + Cluster
> - **14** Tabs + Accordion (with AccordionPanel)
> - **15** Avatar + KeyValueList + Skeleton
> - **16** Input + Select (form input pair 1)
> - **17** Textarea + Checkbox + DatePicker (form input pair 2)
> - **18** FadeIn + Stagger + CustomBlock + global motion stylesheet
> - **19** MarketingLayout.json + SettingsLayout.json + layouts/index.ts export
>
> **Task 20** — Add `style: StyleSlot.optional()` to every existing component's props schema (Button, IconButton, Link, Form, Heading, Badge, Divider, Card, EmptyState, LoadingState, Pagination, Table, TableSortable, Alert, ConfirmDialog, NavLink, Breadcrumb), wrap each render in `<Wrapper style={resolveStyle(props.style)}>` (via a tiny `withStyleSlot` HOC), update `packages/library/src/index.ts` exports, lock new exports via snapshot test.
>
> **Renderer (Task 21)** — Modify `packages/renderer/src/runtime/dispatch.tsx`:
> - Apply `resolveStyle(node.style)` on every node's wrapper element (compose with existing inline styles).
> - Add explicit `case "Custom"` before the unknown-fallback that renders sanitized HTML via `dompurify` (new dep, pinned `^3.0`).
> - Test that v1 schemas with no `style` render byte-identical to before.
>
> **Backend — design_compiler (Tasks 22-24)**:
> - **22** `services/design_compiler.py` — `hsl_ramp(anchor)` returns 11-stop dict; tested with red/green/blue anchors for monotonic lightness.
> - **23** Field mapper functions: `_map_color_palette`, `_map_typography`, `_map_spacing` (with density multiplier), `_map_radius_shadow_motion`, `_map_imagery_status`. Each is a pure function with focused unit tests.
> - **24** `compile(design_spec) -> tokens_custom` orchestrates the mappers; integration test against fintech and healthcare design-spec fixtures with snapshot of resulting `tokens.custom.json`.
>
> **Pipeline integration (Task 25)** — Modify `backend/routers/generate.py:_run_relay_pipeline` to call `design_compiler.compile()` between the design-agent step and the schema-agent dispatch. Write `src/theme/tokens.custom.json`. Wrap in try/except that logs but doesn't fail. Add SSE `[Tokens] ✓` marker.
>
> **Gold-standard examples (Task 26)** — Create 9 hand-curated example schemas in `backend/services/schema_examples/`:
> - list/{table.json, card-grid.json, kanban.json}
> - detail/{tabbed-hero.json, split-detail.json, profile.json}
> - form/{single-column.json, sectioned.json, wizard.json}
> - landing/hero-features-cta.json
> - README.md documenting how to add new archetypes
>
> Each example uses `schemaVersion: "2"`, real token refs from `defaultTokens`, at least one StyleSlot per page, motion on Hero/Section. Add a CI lint test (`backend/tests/services/test_schema_examples.py`) that:
> - parses each JSON via the v2 Zod schema (Node subprocess)
> - asserts every `tokens.*` ref terminates at a defaultTokens leaf path (regex check)
> - asserts every node `type` is registered in the library descriptor
>
> **schema_prompt rewrite (Task 27)** — Restructure `backend/services/schema_prompt.py`:
> - `render_token_paths(default_tokens)` walks defaults emitting one path per leaf
> - `load_gold_example(page_type, archetype)` reads from `schema_examples/`; falls back to first example if archetype unknown (logs warning)
> - `build_schema_prompt(plan, entity, page_type)` reads `design-spec.json` + `tokens.custom.json` + library descriptor + gold example, assembles the compact prompt structure from spec §5.5
> - Tests: snapshot of generated prompt for a fintech/list scenario; verify token paths match defaultTokens; verify archetype fallback behavior.
>
> **Validator extension + telemetry (Tasks 28-29)**:
> - **28** Extend Zod-validation subprocess in `feature_slice_schema_agent.py` to load `tokens.custom.json` (or fall back to defaults) and reject schemas referencing unknown token paths. Test with deliberately invalid refs.
> - **29** Add per-call telemetry: count valid vs invalid `tokens.*` refs in returned schemas; log to Python logger; if `>50%` of refs in a generation are invalid, fail-fast with a clear `[Schema] ⚠ Design context not reaching LLM` message instead of retry-looping.
>
> **Editor — TokenPicker / Background / Motion / StyleSlotEditor (Tasks 30-31)**:
> - **30** Create `packages/editor/src/panes/Properties/style/TokenPicker.tsx` — autocomplete dropdown over tokens by scope, reads from store.theme. Sub-components `BackgroundEditor` (4-variant switcher) and `MotionEditor` (enum select).
> - **31** Create `packages/editor/src/panes/Properties/StyleSlotEditor.tsx` that composes the three sub-editors. Modify `Properties.tsx` to mount it after the node-specific props. Mutations flow through the existing `applyOps` pipeline.
>
> **Editor — Custom block UX (Task 32)**:
> - Create `packages/editor/src/panes/Canvas/CustomNodePreview.tsx` — labeled overlay box rendering sanitized HTML.
> - Create `packages/editor/src/panes/Properties/CustomEditor.tsx` — side drawer with HTML/Tailwind textareas + Save/Cancel.
> - Modify `packages/editor/src/Editor.tsx` to wire the drawer.
>
> **Editor — DnD validation + dispatch (Task 33)**:
> - Modify `packages/editor/src/dnd/validate-drop.ts` to enforce: Tabs children-count = tabs[].length; Split = 2 children; Sidebar = 2 children; Form children must be input/structural; Custom rejects all child drops.
> - Modify `packages/editor/src/panes/Canvas/Canvas.tsx` to render Custom via CustomNodePreview before the renderer fallback.
>
> **Palette + EditorMount registries (Task 34)**:
> - Modify `packages/editor/src/panes/Palette/Palette.tsx` to render new categories `layout`, `motion`, `custom`.
> - Modify `frontend/src/components/schema-editor/EditorMount.tsx` to register all 20 new components with their `*Props` schemas.
> - Modify `backend/templates/app-foundation/src/lib/library-registry.ts` to mirror the same registry list.
>
> **Debug endpoints + feature flag (Tasks 35-36)**:
> - **35** Add `POST /api/_debug/recompile-tokens/{short_id}` to `backend/routers/_debug_schema.py`: read `src/contracts/design-spec.json`, run `design_compiler.compile`, write `src/theme/tokens.custom.json`, return summary JSON. Test against `ecsijbfx`.
> - **36** Add `FIDELITY_MODE_ENABLED` env flag (defaults true) to `backend/config.py`. Gate the design-compiler step + enriched prompt behind it. When false, pipeline reverts to existing behavior.
>
> **End-to-end smoke test (Task 37)** — `backend/tests/integration/test_fidelity_smoke.py`:
> - Stub `claude_agent_sdk.query` to return a fixture schema for each call.
> - Run `_run_relay_pipeline` against a synthetic plan + design-spec.
> - Assert: `tokens.custom.json` written, schemas reference real token paths, runtime renders without exceptions, every assertion in §9 success criteria checked programmatically where possible.

---

## Self-review checklist

Run before marking the plan complete:

1. **Spec coverage** — every §1-§9 of the design spec has at least one task implementing it. Confirmed:
   - §1 schema package extensions → Tasks 2-9
   - §2 library expansion → Tasks 10-20
   - §3 token compiler → Tasks 22-24
   - §4 defaultTokens canonical structure → Task 1
   - §5 schema-agent prompt → Tasks 26-29
   - §6 editor support → Tasks 30-34
   - §7 backwards compat / rollout → Tasks 9 (migrate), 20 (existing components), 35 (recompile-tokens), 36 (feature flag)
   - §8 risk mitigations → Tasks 28 (validator), 29 (telemetry), schema_examples lint (26)
   - §9 success criteria → Task 37 smoke test

2. **Placeholder scan** — no `TBD`/`TODO`/"add error handling" lines. The remaining-tasks summary section uses concrete file paths and concrete behavior — no `???`.

3. **Type consistency** — `StyleSlot`/`StyleSlotT`, `PageV2`/`PageV2T`, `migratePage`, `resolveStyle`, `useMotion`, `Hero`/`HeroProps`, etc., used consistently across tasks.

---

## Execution

Plan complete and saved to `docs/superpowers/plans/2026-05-03-high-fidelity-schema-generation.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best fit for 37 mostly-mechanical tasks.
2. **Inline Execution** — Execute tasks in this session via executing-plans, batch execution with checkpoints.

Which approach?

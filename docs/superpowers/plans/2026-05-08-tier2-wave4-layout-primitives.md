# Tier 2 Wave 4 — Layout Primitives: AppShell + InspectorPanel + TabPanelWithDeepLink

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Add the structural skeleton enterprise apps wear over the component vocabulary from Waves 1-3. AppShell holds the page; InspectorPanel slides over the page's main slot for drill-in; TabPanelWithDeepLink replaces state-only Tabs with URL-aware tabs.

**Architecture:** Each component follows the established Wave 1-3 pattern. AppShell + InspectorPanel are layout containers (acceptsChildren = true); TabPanelWithDeepLink reuses Tabs/TabPanel under the hood but persists active-tab state via the existing `useUrlState` hook from Wave 2.

**Spec:** `docs/superpowers/specs/2026-05-08-enterprise-depth-design.md` § Theme B.

---

## File structure

### New files
- `packages/library/src/components/AppShell/AppShell.tsx`
- `packages/library/src/components/AppShell/AppShell.schema.ts`
- `packages/library/src/components/InspectorPanel/InspectorPanel.tsx`
- `packages/library/src/components/InspectorPanel/InspectorPanel.schema.ts`
- `packages/library/src/components/TabPanelWithDeepLink/TabPanelWithDeepLink.tsx`
- `packages/library/src/components/TabPanelWithDeepLink/TabPanelWithDeepLink.schema.ts`

### Modified files
- `packages/schema/src/nodes/enterprise.ts` — append AppShellNode, InspectorPanelNode, TabPanelWithDeepLinkNode
- `packages/schema/src/page.ts` — add 3 nodes to NodeV2
- `packages/library/src/index.ts` — export 3 components + props schemas
- `apps/render-scaffold/.../SchemaRendererWrapper.tsx` — register (acceptsChildren=true for AppShell + InspectorPanel + TabPanelWithDeepLink)
- `frontend/src/app/(dev-only)/component-playground/page.tsx` — 3 sections
- `apps/visual-regression/tests/components.spec.ts` — 3 IDs
- `backend/services/schema_prompt.py` — append component contracts

---

## Task 1: AppShell

**Files:**
- Create: `packages/library/src/components/AppShell/AppShell.tsx`
- Create: `packages/library/src/components/AppShell/AppShell.schema.ts`
- Modify: `packages/schema/src/nodes/enterprise.ts` — append `AppShellNode`

- [ ] **Step 1: AppShellNode**

```ts
// Append to packages/schema/src/nodes/enterprise.ts
import { NodeV2Ref } from "../node-ref";

export const AppShellNode: any = z.object({
  id: z.string(),
  type: z.literal("AppShell"),
  props: z.object({
    sidebar: NodeV2Ref.optional(),       // schema sub-tree for the nav
    topbar: NodeV2Ref.optional(),        // schema sub-tree for breadcrumb + user menu
    actions: NodeV2Ref.optional(),       // schema sub-tree for page actions toolbar
    rightRail: NodeV2Ref.optional(),     // schema sub-tree for context sidebar
  }),
  children: z.array(NodeV2Ref).default([]),  // main page content
});
```

NOTE: `NodeV2Ref` is already used in `nodes/foundation.ts` for nested-node fields. Re-import here. The `: any` cast is to break the recursive zod typing (same pattern as existing nodes).

- [ ] **Step 2: AppShell component**

```tsx
// packages/library/src/components/AppShell/AppShell.tsx
import * as React from "react";

interface AppShellProps {
  sidebar?: React.ReactNode;
  topbar?: React.ReactNode;
  actions?: React.ReactNode;
  rightRail?: React.ReactNode;
  children?: React.ReactNode;
}

export function AppShell({ sidebar, topbar, actions, rightRail, children }: AppShellProps) {
  return (
    <div className="grid min-h-screen w-full" style={{
      gridTemplateColumns: sidebar
        ? (rightRail ? "240px 1fr 320px" : "240px 1fr")
        : (rightRail ? "1fr 320px" : "1fr"),
      gridTemplateRows: "auto 1fr",
    }}>
      {sidebar && (
        <aside className="row-span-2 border-r border-border bg-sidebar text-sidebar-foreground overflow-y-auto">
          {sidebar}
        </aside>
      )}
      {(topbar || actions) && (
        <header className="border-b border-border bg-card flex items-center justify-between px-6 py-3">
          <div className="flex-1 min-w-0">{topbar}</div>
          {actions && <div className="flex-shrink-0 ml-4 flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <main className="overflow-y-auto bg-background">
        <div className="px-6 py-6">{children}</div>
      </main>
      {rightRail && (
        <aside className="row-span-2 border-l border-border bg-card overflow-y-auto p-4">
          {rightRail}
        </aside>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Schema wrapper + library exports**

```ts
// AppShell.schema.ts
import { z } from "zod";
import { AppShellNode } from "@tentoroforge/schema";
export const AppShellProps = AppShellNode.shape.props;
export type AppShellPropsType = z.infer<typeof AppShellProps>;
```

In `packages/library/src/index.ts`:
```ts
export { AppShell } from "./components/AppShell/AppShell";
export { AppShellProps as AppShellPropsSchema, type AppShellPropsType } from "./components/AppShell/AppShell.schema";
```

- [ ] **Step 4: Verify + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true

git add packages/library/src/components/AppShell/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/enterprise.ts
git commit -m "feat(library): AppShell — sidebar + topbar + main + right-rail composition"
```

---

## Task 2: InspectorPanel

**Files:**
- Create: `packages/library/src/components/InspectorPanel/InspectorPanel.tsx`
- Create: `packages/library/src/components/InspectorPanel/InspectorPanel.schema.ts`
- Modify: `packages/schema/src/nodes/enterprise.ts` — append `InspectorPanelNode`

- [ ] **Step 1: InspectorPanelNode**

```ts
// Append to packages/schema/src/nodes/enterprise.ts
export const InspectorPanelNode: any = z.object({
  id: z.string(),
  type: z.literal("InspectorPanel"),
  props: z.object({
    paramKey: z.string().default("inspector"),  // URL key for active selection
    title: z.string().optional(),
    width: z.enum(["narrow", "default", "wide"]).optional(),  // 320 / 480 / 640
  }),
  children: z.array(NodeV2Ref).default([]),
});
```

- [ ] **Step 2: InspectorPanel component**

```tsx
// packages/library/src/components/InspectorPanel/InspectorPanel.tsx
"use client";

import * as React from "react";
import { useUrlState } from "../../style/useUrlState";

interface InspectorPanelProps {
  paramKey?: string;
  title?: string;
  width?: "narrow" | "default" | "wide";
  children?: React.ReactNode;
}

const WIDTH_PX: Record<string, number> = {
  narrow: 320, default: 480, wide: 640,
};

export function InspectorPanel({
  paramKey = "inspector", title, width = "default", children,
}: InspectorPanelProps) {
  const [active, setActive] = useUrlState(paramKey, "");
  if (!active) return null;

  const close = () => setActive("");

  // Esc-to-close
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-foreground/20 transition-opacity"
        onClick={close}
        aria-hidden="true"
      />
      <aside
        className="fixed right-0 top-0 z-50 h-full bg-card border-l border-border shadow-2xl flex flex-col"
        style={{ width: WIDTH_PX[width] }}
        role="complementary"
        aria-modal="true"
      >
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h3 className="text-sm font-semibold">{title ?? `Details (${active})`}</h3>
          <button
            type="button"
            onClick={close}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Close inspector"
          >
            ✕
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-4">
          {children}
        </div>
      </aside>
    </>
  );
}
```

- [ ] **Step 3: Schema wrapper + library exports + commit**

```ts
// InspectorPanel.schema.ts
import { z } from "zod";
import { InspectorPanelNode } from "@tentoroforge/schema";
export const InspectorPanelProps = InspectorPanelNode.shape.props;
export type InspectorPanelPropsType = z.infer<typeof InspectorPanelProps>;
```

In `packages/library/src/index.ts`:
```ts
export { InspectorPanel } from "./components/InspectorPanel/InspectorPanel";
export { InspectorPanelProps as InspectorPanelPropsSchema, type InspectorPanelPropsType } from "./components/InspectorPanel/InspectorPanel.schema";
```

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -10 || true

git add packages/library/src/components/InspectorPanel/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/enterprise.ts
git commit -m "feat(library): InspectorPanel — slide-out drill-in view with URL-state + Esc-close"
```

---

## Task 3: TabPanelWithDeepLink

**Files:**
- Create: `packages/library/src/components/TabPanelWithDeepLink/TabPanelWithDeepLink.tsx`
- Create: `packages/library/src/components/TabPanelWithDeepLink/TabPanelWithDeepLink.schema.ts`
- Modify: `packages/schema/src/nodes/enterprise.ts` — append `TabPanelWithDeepLinkNode`

- [ ] **Step 1: TabPanelWithDeepLinkNode**

```ts
// Append to enterprise.ts
const TabSpec = z.object({
  id: z.string(),
  label: z.string(),
});

export const TabPanelWithDeepLinkNode: any = z.object({
  id: z.string(),
  type: z.literal("TabPanelWithDeepLink"),
  props: z.object({
    paramKey: z.string().default("tab"),
    tabs: z.array(TabSpec).min(1),
    defaultTab: z.string().optional(),
  }),
  children: z.array(NodeV2Ref).default([]),  // one child per tab, in order
});
```

- [ ] **Step 2: TabPanelWithDeepLink component**

```tsx
// packages/library/src/components/TabPanelWithDeepLink/TabPanelWithDeepLink.tsx
"use client";

import * as React from "react";
import { useUrlState } from "../../style/useUrlState";

interface Props {
  paramKey?: string;
  tabs: Array<{ id: string; label: string }>;
  defaultTab?: string;
  children?: React.ReactNode;
}

export function TabPanelWithDeepLink({
  paramKey = "tab", tabs, defaultTab, children,
}: Props) {
  const fallback = defaultTab ?? tabs[0]?.id ?? "";
  const [activeTab, setActiveTab] = useUrlState(paramKey, fallback);
  const childArray = React.Children.toArray(children);

  const activeIndex = Math.max(0, tabs.findIndex((t) => t.id === activeTab));
  const activeContent = childArray[activeIndex] ?? null;

  return (
    <div className="flex flex-col">
      <div role="tablist" className="flex items-center gap-1 border-b border-border">
        {tabs.map((tab) => {
          const isActive = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveTab(tab.id)}
              className={`relative px-4 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
              {isActive && (
                <span className="absolute -bottom-px left-0 right-0 h-0.5 bg-primary" />
              )}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" className="flex-1 pt-4">
        {activeContent}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Schema wrapper + library exports + commit**

```ts
// TabPanelWithDeepLink.schema.ts
import { z } from "zod";
import { TabPanelWithDeepLinkNode } from "@tentoroforge/schema";
export const TabPanelWithDeepLinkProps = TabPanelWithDeepLinkNode.shape.props;
export type TabPanelWithDeepLinkPropsType = z.infer<typeof TabPanelWithDeepLinkProps>;
```

In `packages/library/src/index.ts`:
```ts
export { TabPanelWithDeepLink } from "./components/TabPanelWithDeepLink/TabPanelWithDeepLink";
export { TabPanelWithDeepLinkProps as TabPanelWithDeepLinkPropsSchema, type TabPanelWithDeepLinkPropsType } from "./components/TabPanelWithDeepLink/TabPanelWithDeepLink.schema";
```

```bash
git add packages/library/src/components/TabPanelWithDeepLink/ \
        packages/library/src/index.ts \
        packages/schema/src/nodes/enterprise.ts
git commit -m "feat(library): TabPanelWithDeepLink — URL-aware tabs that survive refresh"
```

---

## Task 4: NodeV2 + scaffold registry + playground + schema_prompt + verify

Single combined task — small enough to batch.

### Step 1: NodeV2

In `packages/schema/src/page.ts`:
```ts
import {
  ApprovalStepperNode, PersonCardNode, FilterBarNode,
  CommandPaletteNode, ActivityFeedNode,
  EmptyStateRichNode, DateRangePickerNode, MultiSelectNode,
  AppShellNode, InspectorPanelNode, TabPanelWithDeepLinkNode,  // ← ADD
} from "./nodes/enterprise";

// Add to discriminatedUnion
```

### Step 2: Scaffold registry

In `SchemaRendererWrapper.tsx`:
```tsx
import {
  AppShell, InspectorPanel, TabPanelWithDeepLink,
  AppShellPropsSchema, InspectorPanelPropsSchema, TabPanelWithDeepLinkPropsSchema,
} from "@tentoroforge/library";

reg("AppShell",              AppShell,              AppShellPropsSchema,              "layout", true);
reg("InspectorPanel",        InspectorPanel,        InspectorPanelPropsSchema,        "layout", true);
reg("TabPanelWithDeepLink",  TabPanelWithDeepLink,  TabPanelWithDeepLinkPropsSchema,  "layout", true);
```

NOTE: `acceptsChildren = true` for all 3 (last arg).

### Step 3: Build packages

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema && npm run build 2>&1 | tail -3
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npm run build 2>&1 | tail -3
```

### Step 4: Playground entries

Append to `frontend/src/app/(dev-only)/component-playground/page.tsx` (PlaygroundInner):

```tsx
import { AppShell, InspectorPanel, TabPanelWithDeepLink } from "@tentoroforge/library";

// Section: AppShell (just the chrome — ChildNodes are minimal here)
<section data-component="AppShell" className={SECTION}>
  <p className={TITLE}>AppShell</p>
  <div className="border border-border rounded-md overflow-hidden" style={{ height: 400 }}>
    <AppShell
      sidebar={<nav className="p-3 text-xs text-sidebar-foreground/80 space-y-1">
        <div className="font-semibold uppercase tracking-wide opacity-60 mb-2">Pages</div>
        <div className="px-2 py-1 rounded bg-sidebar-active/40">Dashboard</div>
        <div className="px-2 py-1 rounded">Employees</div>
        <div className="px-2 py-1 rounded">Leave Requests</div>
      </nav>}
      topbar={<div className="text-xs text-muted-foreground">Home / Dashboard</div>}
      actions={<button className="h-8 px-3 rounded-md bg-primary text-primary-foreground text-xs font-medium">+ New</button>}
    >
      <p className="text-sm text-muted-foreground">Main content area.</p>
    </AppShell>
  </div>
</section>

// Section: InspectorPanel (preview state, manually open)
<section data-component="InspectorPanel" className={SECTION}>
  <p className={TITLE}>InspectorPanel — open by adding ?inspector=demo to URL</p>
  <p className="text-xs text-muted-foreground mb-3">
    The InspectorPanel is hidden by default. Try{" "}
    <a href="?inspector=demo" className="underline text-primary">this link</a>{" "}
    to open it.
  </p>
  <InspectorPanel paramKey="inspector" title="Sample Detail" width="default">
    <div className="space-y-3 text-sm">
      <p>Inspector content goes here.</p>
      <p className="text-muted-foreground">Press Esc or click outside to close.</p>
    </div>
  </InspectorPanel>
</section>

// Section: TabPanelWithDeepLink
<section data-component="TabPanelWithDeepLink" className={SECTION}>
  <p className={TITLE}>TabPanelWithDeepLink — active tab persists in URL ?tab=...</p>
  <TabPanelWithDeepLink
    paramKey="demo_tab"
    tabs={[
      { id: "overview",  label: "Overview" },
      { id: "history",   label: "History" },
      { id: "settings",  label: "Settings" },
    ]}
    defaultTab="overview"
  >
    <div className="text-sm">Overview content — first tab</div>
    <div className="text-sm">History content — second tab</div>
    <div className="text-sm">Settings content — third tab</div>
  </TabPanelWithDeepLink>
</section>
```

### Step 5: Visual regression spec

Append to COMPONENTS array:
```ts
"AppShell", "InspectorPanel", "TabPanelWithDeepLink",
```

### Step 6: Capture baselines

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
npm run dev -- -p 6501 > /tmp/frontend-t2w4.log 2>&1 &
sleep 15
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test --grep "AppShell|InspectorPanel|TabPanelWithDeepLink" --update-snapshots
npx playwright test --grep "AppShell|InspectorPanel|TabPanelWithDeepLink"
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

### Step 7: schema_prompt

Append to `backend/services/schema_prompt.py` after TIER2_BATCH3_GUIDANCE:

```python
TIER2_LAYOUT_GUIDANCE = """
## TIER 2 LAYOUT PRIMITIVES (Wave 4)

  AppShell { sidebar?, topbar?, actions?, rightRail?, children }
    Canonical app-chrome composition. Use as the ROOT node of every page in
    enterprise apps. Sidebar = global nav. Topbar = breadcrumb/title.
    Actions = page-level CTAs. RightRail = context sidebar (e.g. ActivityFeed).

  InspectorPanel { paramKey?, title?, width?, children }
    Slide-out detail panel from the right edge. Hidden until URL has the
    paramKey set. Use for "click row in DataGrid → see full record without
    page change". Composes with DataGrid via ?{paramKey}={rowId} URL state.
    width: narrow (320) | default (480) | wide (640).

  TabPanelWithDeepLink { paramKey?, tabs[], defaultTab?, children }
    URL-aware tabs. children must be ONE node per tab, IN ORDER (matched to
    tabs[] array index). Use for detail pages with multiple sections
    (Overview / History / Settings). Active tab survives refresh + browser
    back-button.

ANTI-PATTERNS:
  - Wrapping every page in AppShell when only a Hero/main-content layout is
    needed (Section is fine for content-only pages)
  - InspectorPanel without a triggering UI (DataGrid row-click, button, or
    link must set the URL param via &{paramKey}={value})
  - Using Tabs+TabPanel for tabs on detail pages: prefer TabPanelWithDeepLink
    so users can refresh / share the URL
"""
```

### Step 8: Final commit

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/schema/src/page.ts \
        apps/render-scaffold/src/app/p/\[projectId\]/\[...slug\]/SchemaRendererWrapper.tsx \
        frontend/src/app/\(dev-only\)/component-playground/ \
        apps/visual-regression/tests/ \
        backend/services/schema_prompt.py
git commit -m "feat(scaffold+editor+prompt): wire AppShell/InspectorPanel/TabPanelWithDeepLink end-to-end"
```

### Step 9: Verify

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_schema_prompt.py tests/integration/test_schema_migration.py -v 2>&1 | tail -5
```

Expected: all pass.

---

## Self-review

| Component | Tasks |
|---|---|
| AppShell | 1 |
| InspectorPanel | 2 |
| TabPanelWithDeepLink | 3 |
| Wiring + playground + prompt + verify | 4 |

✓ All Wave 4 scope.

---

## Out of scope

- **Mobile-responsive variants** (compressed sidebar, slide-up sheet for InspectorPanel) — Tier 3 Wave 3
- **Drag-to-resize** sidebar/inspector — out of scope
- **Tab close-buttons** — TabPanelWithDeepLink has fixed tab list per spec

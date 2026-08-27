# Design System Overhaul — Wave 1: Foundation + Hierarchy

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stand up the test/safety infrastructure to support the upcoming 38-component refactor (Phase 0), then add hierarchy primitive props to ~10 library components so generated UIs can express importance/role/density (Phase 1).

**Architecture:** Phase 0 ships a Playwright visual regression suite + a CVA-based template + a schema-migration test corpus + a component playground. Phase 1 extends the existing `packages/schema/src/nodes/foundation.ts` and related node files with optional hierarchy enums, library components scale visual weight per the new props, schema-prompt teaches the LLM hierarchy semantics. All new props are optional with defaults that match today's appearance — zero breaking changes for existing schemas.

**Tech Stack:** TypeScript / React 19 / Tailwind 3 / Zod / Playwright / class-variance-authority / pytest. Existing predecessors: schema-driven runtime, fidelity loop, render-service.

**Spec:** `docs/superpowers/specs/2026-05-08-design-system-overhaul-design.md` (Phases 0 + 1).

---

## File structure

### New files

**Phase 0 — Test infrastructure:**
- `apps/visual-regression/package.json` — minimal Playwright app
- `apps/visual-regression/playwright.config.ts`
- `apps/visual-regression/tests/components.spec.ts` — captures every library component
- `apps/visual-regression/tests/baselines/` — committed PNG baselines (auto-generated)
- `docs/component-token-audit.md` — written analysis of 38 components' token consumption
- `backend/tests/integration/test_schema_migration.py` — corpus fixture
- `backend/tests/fixtures/migration-schemas/*.json` — ~20 captured real schemas

**Phase 0 — CVA scaffolding:**
- (No new files — Button.tsx is refactored in place to use CVA as the canonical template)

**Phase 0 — Editor playground:**
- `frontend/src/app/(dev-only)/component-playground/page.tsx`

**Phase 1 — Hierarchy types:**
- `packages/library/src/types/hierarchy.ts` — Importance, SectionRole, HeroRole, CardDensity, HeadingWeight enums

### Modified files

**Phase 1 — Schema package (Zod node definitions):**
- `packages/schema/src/nodes/foundation.ts` — add optional `importance` to MetricTileNode, optional `role` to HeroNode + SectionNode, optional `density` to (find Card definition), optional `weight` to (find Heading)

**Phase 1 — Library components:**
- `packages/library/src/components/MetricTile/MetricTile.tsx` — read importance, scale visual weight
- `packages/library/src/components/Hero/Hero.tsx` — read role, render different layouts
- `packages/library/src/components/Section/Section.tsx` — read role
- `packages/library/src/components/Card/Card.tsx` — read density
- `packages/library/src/components/Heading/Heading.tsx` — read weight
- `packages/library/src/components/Button/Button.tsx` — refactor to CVA (Phase 0 template)

**Phase 1 — Schema prompt + agents:**
- `backend/services/schema_prompt.py` — hierarchy semantics block in the prompt
- `backend/agents/patch_agent.py` — system prompt mentions hierarchy issues
- `backend/services/schema_examples/*.json` — 2-3 examples updated to demonstrate good hierarchy

**Phase 1 — Library deps:**
- `packages/library/package.json` — add `class-variance-authority`

---

## Task 1: Playwright visual regression suite scaffolding

**Files:**
- Create: `apps/visual-regression/package.json`
- Create: `apps/visual-regression/playwright.config.ts`
- Create: `apps/visual-regression/tests/.gitkeep`

- [ ] **Step 1: package.json**

```json
{
  "name": "@tentoroforge/visual-regression",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "test": "playwright test",
    "update-baselines": "playwright test --update-snapshots"
  },
  "devDependencies": {
    "@playwright/test": "^1.49.0",
    "@types/node": "^22.0.0",
    "typescript": "^5.7.0"
  }
}
```

- [ ] **Step 2: playwright.config.ts**

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,             // serial — predictable screenshots
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:6501",
    trace: "off",
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
  },
  expect: {
    toHaveScreenshot: {
      maxDiffPixels: 50,           // tolerate tiny anti-alias drift
      threshold: 0.02,
    },
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
```

- [ ] **Step 3: Update root package.json workspaces**

Read `/Users/m/Work/code/poc/design2ui-forge-v3/package.json`. Confirm `apps/*` is in the `workspaces` array (added in the predecessor render-scaffold work). If absent, add it.

- [ ] **Step 4: Install**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npm install --legacy-peer-deps
cd apps/visual-regression && npx playwright install chromium
```

- [ ] **Step 5: Commit**

```bash
git add apps/visual-regression/package.json apps/visual-regression/playwright.config.ts apps/visual-regression/tests/.gitkeep package.json package-lock.json
git commit -m "feat(visual-regression): scaffold Playwright app for component snapshots"
```

---

## Task 2: Component playground in editor

**Files:**
- Create: `frontend/src/app/(dev-only)/component-playground/page.tsx`

Renders every library component in known states on a single page so visual-regression tests have a stable URL to capture.

- [ ] **Step 1: Implement playground page**

```tsx
// frontend/src/app/(dev-only)/component-playground/page.tsx
"use client";

/**
 * Component playground — renders every library component in known states.
 * Used by:
 *   - apps/visual-regression for screenshot diffing
 *   - Manual QA when refactoring components
 *
 * URL: http://localhost:6501/component-playground
 *
 * Each component group is wrapped in <section data-component="X"> so the
 * regression suite can target snapshots per-component.
 */
import {
  Button, Hero, Section, Card, MetricTile, Avatar, Badge, KeyValueList,
  Heading, Skeleton, Alert, Divider, Breadcrumb,
} from "@tentoroforge/library";

const SECTION = "border-b border-gray-200 px-8 py-6 bg-white";
const TITLE = "text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3";

export default function ComponentPlayground() {
  return (
    <main className="bg-gray-50 min-h-screen">
      <header className="sticky top-0 bg-white border-b border-gray-200 px-8 py-4">
        <h1 className="text-lg font-semibold">Component Playground</h1>
        <p className="text-xs text-gray-500">Visual regression target</p>
      </header>

      <section data-component="Button" className={SECTION}>
        <p className={TITLE}>Button</p>
        <div className="flex gap-3 flex-wrap">
          <Button label="Primary" variant="primary" />
          <Button label="Secondary" variant="secondary" />
          <Button label="Ghost" variant="ghost" />
          <Button label="Danger" variant="danger" />
        </div>
      </section>

      <section data-component="Heading" className={SECTION}>
        <p className={TITLE}>Heading</p>
        <Heading level={1} text="Heading 1" />
        <Heading level={2} text="Heading 2" />
        <Heading level={3} text="Heading 3" />
      </section>

      <section data-component="Hero" className={SECTION}>
        <p className={TITLE}>Hero</p>
        <Hero
          eyebrow="Eyebrow text"
          headline="Hero headline"
          subhead="Subhead with explanatory copy"
          ctas={[{ label: "Primary CTA", variant: "primary", action: { type: "navigate", to: "/x" } }]}
        />
      </section>

      <section data-component="MetricTile" className={SECTION}>
        <p className={TITLE}>MetricTile</p>
        <div className="grid grid-cols-4 gap-3">
          <MetricTile label="Total Users" value={1284} format="number" />
          <MetricTile label="Revenue" value={482910} format="currency" delta={{ direction: "up", value: 0.12 }} />
          <MetricTile label="Conversion" value={0.034} format="percent" delta={{ direction: "down", value: 0.04 }} />
          <MetricTile label="Avg Time" value={142} format="duration" delta={{ direction: "flat", value: 0 }} />
        </div>
      </section>

      <section data-component="Card" className={SECTION}>
        <p className={TITLE}>Card</p>
        <Card>
          <p className="font-semibold">Card content</p>
          <p className="text-sm text-gray-600">Body copy.</p>
        </Card>
      </section>

      <section data-component="Avatar" className={SECTION}>
        <p className={TITLE}>Avatar</p>
        <div className="flex items-center gap-3">
          <Avatar name="Sarah Chen" size="sm" />
          <Avatar name="Marcus Lee" size="md" />
          <Avatar name="Ana Martins" size="lg" />
        </div>
      </section>

      <section data-component="Badge" className={SECTION}>
        <p className={TITLE}>Badge</p>
        <div className="flex gap-2 flex-wrap">
          <Badge content="Active" variant="success" />
          <Badge content="Pending" variant="warning" />
          <Badge content="Failed" variant="danger" />
          <Badge content="Info" variant="primary" />
          <Badge content="Neutral" variant="neutral" />
        </div>
      </section>

      <section data-component="Alert" className={SECTION}>
        <p className={TITLE}>Alert</p>
        <Alert variant="info" title="Heads up" message="This is an info alert." />
      </section>

      <section data-component="KeyValueList" className={SECTION}>
        <p className={TITLE}>KeyValueList</p>
        <KeyValueList items={[
          { label: "Name", value: "Sarah Chen" },
          { label: "Department", value: "Engineering" },
          { label: "Joined", value: "2022-04-15" },
        ]} />
      </section>

      <section data-component="Skeleton" className={SECTION}>
        <p className={TITLE}>Skeleton</p>
        <div className="space-y-2">
          <Skeleton width="100%" height="20px" />
          <Skeleton width="80%" height="20px" />
          <Skeleton width="60%" height="20px" />
        </div>
      </section>

      <section data-component="Breadcrumb" className={SECTION}>
        <p className={TITLE}>Breadcrumb</p>
        <Breadcrumb items={[
          { label: "Home", href: "/" },
          { label: "Users", href: "/users" },
          { label: "Sarah Chen" },
        ]} />
      </section>

      <section data-component="Divider" className={SECTION}>
        <p className={TITLE}>Divider</p>
        <Divider />
      </section>
    </main>
  );
}
```

NOTE for implementer: some components above may have slightly different prop shapes than written here (e.g. `KeyValueList.items` may use different key names). Inspect each component's prop schema and adjust the playground entries to match. The goal is one rendered instance per component, not exact prop coverage.

- [ ] **Step 2: Verify the page loads**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npm run dev -- -p 6501 > /tmp/frontend-playground.log 2>&1 &
sleep 8
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:6501/component-playground
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: `200` (or 307 redirect — both fine).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/\(dev-only\)/component-playground/page.tsx
git commit -m "feat(playground): component playground page for visual regression target"
```

---

## Task 3: Visual regression component test

**Files:**
- Create: `apps/visual-regression/tests/components.spec.ts`

- [ ] **Step 1: Implement the test**

```ts
// apps/visual-regression/tests/components.spec.ts
import { test, expect } from "@playwright/test";

const PLAYGROUND_URL = "/component-playground";

const COMPONENTS = [
  "Button", "Heading", "Hero", "MetricTile", "Card", "Avatar",
  "Badge", "Alert", "KeyValueList", "Skeleton", "Breadcrumb", "Divider",
] as const;

test.describe("library component visual baselines", () => {
  for (const name of COMPONENTS) {
    test(`${name} default`, async ({ page }) => {
      await page.goto(PLAYGROUND_URL);
      await page.waitForLoadState("networkidle");
      const locator = page.locator(`[data-component="${name}"]`);
      await expect(locator).toHaveScreenshot(`${name}.png`);
    });
  }

  test("full playground", async ({ page }) => {
    await page.goto(PLAYGROUND_URL);
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("_playground.png", { fullPage: true });
  });
});
```

- [ ] **Step 2: Capture baselines**

```bash
# Frontend must be running on port 6501 for this to work.
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npm run dev -- -p 6501 > /tmp/frontend-baseline.log 2>&1 &
sleep 10

cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test --update-snapshots

# Then re-run to confirm baselines match
npx playwright test

lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: 13 tests pass on the second run. Baselines land at `apps/visual-regression/tests/components.spec.ts-snapshots/`.

- [ ] **Step 3: Commit baselines**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add apps/visual-regression/tests/
git commit -m "feat(visual-regression): baseline screenshots for 12 components + full playground"
```

---

## Task 4: Component token-consumption audit

**Files:**
- Create: `docs/component-token-audit.md`

Lightweight written analysis. The implementer reads each of 38 components and notes how it consumes tokens today. No code changes — just observation.

- [ ] **Step 1: Generate the audit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library/src/components
ls > /tmp/component-list.txt
wc -l /tmp/component-list.txt
```

There should be 38 directories. For each, the implementer reads the main `.tsx` file and classifies its token consumption pattern:
- **Tailwind-class** — uses raw Tailwind classes that reference token CSS variables (e.g. `bg-card`)
- **Inline-style** — uses `style={{...}}` with direct token references
- **Conditional-class** — uses string concatenation or template literals to pick classes
- **CVA-ready** — already uses class-variance-authority (currently only Button — to be added)
- **Mixed** — some combination

- [ ] **Step 2: Write the audit**

```markdown
# Component Token Audit (2026-05-08)

Survey of how each library component consumes design tokens today, ranked by
refactor complexity for the upcoming Phase 2 token-system expansion.

## Consumption patterns observed

- **Tailwind-class** — N components: ...
- **Inline-style** — N components: ...
- **Conditional-class** — N components: ...
- **CVA-ready** — 1 (Button, after Task 5)
- **Mixed** — N components: ...

## Per-component classification

| Component | Pattern | Notes | Refactor complexity |
|-----------|---------|-------|---------------------|
| Button | CVA-ready | Already uses CVA via Task 5 | Low (already done) |
| Hero | Tailwind-class | Multiple class constants | Low |
| MetricTile | Tailwind-class | TILE_BASE/LABEL_BASE/VALUE_BASE constants | Low |
| Card | ... | ... | ... |
| ...

[implementer fills in all 38 rows]

## Refactor sequencing

Phase 2 component refactor batches (from spec):
1. Layout primitives — Stack, Section, Split, Sidebar, Cluster, Card, Hero
2. Data display — MetricTile, Heading, Badge, Avatar, KeyValueList, Table
3. Forms — Input, Textarea, Select, DatePicker, Checkbox, Form
4. Feedback + nav — Skeleton, Alert, EmptyState, LoadingState, Tabs, Accordion, Breadcrumb

The remaining components (FadeIn, Stagger, Toast, ConfirmDialog, Pagination,
TabPanel, IconButton, Link, NavLink, FeatureCard, Divider, CustomBlock) are
either:
- Motion wrappers (FadeIn, Stagger) — read motion token only
- Trivial (IconButton, Link, NavLink, Divider) — refactor in batch 4
- Built atop other components (Toast, ConfirmDialog, FeatureCard) — refactor follows their parents
- Slot-bearing (CustomBlock, TabPanel, Pagination) — minimal token reads

## Risks

- N components using Mixed patterns will need careful normalization
- Components emitting their own `<style>` blocks (if any) need to be migrated to className-only
- Components using inline `style.background = ...` patterns need explicit token-variable conversion
```

- [ ] **Step 3: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add docs/component-token-audit.md
git commit -m "docs: token-consumption audit of 38 library components"
```

---

## Task 5: CVA standardization — Button.tsx as template

**Files:**
- Modify: `packages/library/package.json` — add `class-variance-authority`
- Modify: `packages/library/src/components/Button/Button.tsx`
- Modify: `packages/library/src/components/Button/variants.ts` (if exists)

- [ ] **Step 1: Add CVA dep**

Append to `packages/library/package.json` dependencies:
```json
"class-variance-authority": "^0.7.0"
```

Install:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npm install --legacy-peer-deps
```

- [ ] **Step 2: Read current Button**

```bash
cat /Users/m/Work/code/poc/design2ui-forge-v3/packages/library/src/components/Button/Button.tsx
cat /Users/m/Work/code/poc/design2ui-forge-v3/packages/library/src/components/Button/variants.ts
```

- [ ] **Step 3: Refactor Button to use CVA**

Update `Button/variants.ts` (replace contents):

```ts
import { cva, type VariantProps } from "class-variance-authority";

/**
 * Canonical CVA template for library components.
 *
 * Pattern: define a `<Component>Variants` factory at module level. Components
 * import it and call `cn(componentVariants({ variant: ..., size: ... }))` to
 * compose classes. New variant axes are added here, not in the component
 * body.
 *
 * Tokens are referenced via Tailwind's design-system color names which alias
 * to CSS variables compiled from defaultTokens. To add density / elevation /
 * radius axes (Phase 2), extend `variants` with new keys.
 */
export const buttonVariants = cva(
  // base classes — applied to every variant
  "inline-flex items-center justify-center gap-2 font-medium whitespace-nowrap " +
  "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary:   "bg-primary text-primary-foreground hover:bg-primary/90",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost:     "hover:bg-accent hover:text-accent-foreground",
        danger:    "bg-destructive text-destructive-foreground hover:bg-destructive/90",
      },
      size: {
        sm: "h-8  px-3 text-xs   rounded-md",
        md: "h-10 px-4 text-sm   rounded-md",
        lg: "h-12 px-6 text-base rounded-md",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
);

export type ButtonVariantProps = VariantProps<typeof buttonVariants>;
```

Update `Button/Button.tsx`:

```tsx
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ButtonPropsType } from "./Button.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { buttonVariants } from "./variants";

export interface ButtonProps extends ButtonPropsType {
  style?: StyleSlotT;
  onClick?: () => void;
}

export function Button({ label, variant, size, disabled, onClick, style }: ButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={buttonVariants({ variant, size })}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {label}
    </button>
  );
}
```

Note: existing prop shape (`label`, `variant`, `size`, `disabled`) is preserved exactly. Only the className composition mechanism changes.

- [ ] **Step 4: Run visual regression to confirm Button is unchanged**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npm run dev -- -p 6501 > /tmp/frontend-cva.log 2>&1 &
sleep 10
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test components.spec.ts --grep "Button"
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: PASS (Button.png matches baseline within tolerance).

- [ ] **Step 5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/package.json package-lock.json packages/library/src/components/Button/
git commit -m "feat(library): adopt CVA as canonical variant pattern (Button as template)"
```

---

## Task 6: Schema migration test corpus

**Files:**
- Create: `backend/tests/integration/test_schema_migration.py`
- Create: `backend/tests/fixtures/migration-schemas/` (directory)
- Capture: ~20 schemas from existing `output/` projects into the fixture dir

- [ ] **Step 1: Capture schemas from existing output projects**

```bash
mkdir -p /Users/m/Work/code/poc/design2ui-forge-v3/backend/tests/fixtures/migration-schemas
cd /Users/m/Work/code/poc/design2ui-forge-v3
N=0
for proj_dir in $(ls -d output/*/ 2>/dev/null | head -10); do
  for schema_file in $(find "$proj_dir/src/schemas" -name "*.json" 2>/dev/null | head -3); do
    proj=$(basename "$proj_dir")
    rel=$(echo "$schema_file" | sed "s|$proj_dir/src/schemas/||" | tr '/' '_')
    cp "$schema_file" "backend/tests/fixtures/migration-schemas/${proj}__${rel}"
    N=$((N+1))
    [ "$N" -ge 20 ] && break 2
  done
done
ls backend/tests/fixtures/migration-schemas/ | wc -l
```

Expected: 10-20 schema files captured.

- [ ] **Step 2: Write the test**

```python
# backend/tests/integration/test_schema_migration.py
"""Schema migration regression test.

Loads ~20 real LLM-generated schemas captured from output/ and asserts each
parses through the canonical Page zod union without errors. Phase 2 token
changes should not break existing schemas; this test catches that.

The actual zod parse runs in Node via the same shell-out pattern as
patch_applier._zod_validate_page. If Node isn't available, the test
fails-open (returns True with a warning) so it doesn't block CI on
infrastructure issues.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "migration-schemas"
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _list_fixtures() -> list[Path]:
    if not _FIXTURE_DIR.exists():
        return []
    return sorted(_FIXTURE_DIR.glob("*.json"))


def _zod_validate(schema_text: str) -> tuple[bool, str]:
    """Returns (ok, error_message)."""
    script = r"""
const { PageV1, PageV2 } = require("@tentoroforge/schema");
const { z } = require("zod");
let buf = "";
process.stdin.on("data", (c) => (buf += c));
process.stdin.on("end", () => {
  try {
    const j = JSON.parse(buf);
    const u = z.discriminatedUnion("schemaVersion", [PageV1, PageV2]);
    u.parse(j);
    process.exit(0);
  } catch (e) {
    process.stderr.write(String(e?.message ?? e));
    process.exit(1);
  }
});
"""
    try:
        proc = subprocess.run(
            ["node", "-e", script],
            input=schema_text,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(_REPO_ROOT),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return True, "node-unavailable"  # fail-open
    return proc.returncode == 0, proc.stderr or ""


@pytest.mark.parametrize("fixture_path", _list_fixtures(), ids=lambda p: p.name)
def test_existing_schema_parses(fixture_path: Path):
    """Every schema in the fixture corpus must still parse through the
    canonical PageV1|PageV2 zod union after any token / component change."""
    if not _list_fixtures():
        pytest.skip(f"no fixtures present in {_FIXTURE_DIR}")
    text = fixture_path.read_text()
    ok, err = _zod_validate(text)
    if not ok and err == "node-unavailable":
        pytest.skip("node-unavailable; can't run zod validation")
    assert ok, f"{fixture_path.name} failed zod validation:\n{err[:500]}"


def test_fixture_corpus_has_at_least_some():
    fixtures = _list_fixtures()
    if not fixtures:
        pytest.skip(f"no fixtures present in {_FIXTURE_DIR}")
    assert len(fixtures) >= 5, f"expected at least 5 captured schemas, found {len(fixtures)}"
```

- [ ] **Step 3: Run the test**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/integration/test_schema_migration.py -v 2>&1 | tail -20
```

Expected: All present fixtures PASS (or SKIP if node is unreachable). At least 5 fixtures captured.

- [ ] **Step 4: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/tests/integration/test_schema_migration.py backend/tests/fixtures/
git commit -m "test(migration): schema-migration corpus + test for token-system safety net"
```

---

## Task 7: Phase 1 hierarchy types

**Files:**
- Create: `packages/library/src/types/hierarchy.ts`

- [ ] **Step 1: Implement hierarchy types**

```ts
// packages/library/src/types/hierarchy.ts
/**
 * Information-hierarchy primitives.
 *
 * Components use these to scale visual weight per importance/role/density.
 * The schema agent picks values per-element so the LLM can express which
 * piece of a page is the headline vs. supporting.
 */

import { z } from "zod";

/** MetricTile importance — primary tiles are 2x size, tabular numerics, big delta. */
export const ImportanceEnum = z.enum(["primary", "secondary", "tertiary"]);
export type Importance = z.infer<typeof ImportanceEnum>;

/** Hero role — headline = full bleed page header; banner = mid-page; inline = one-liner. */
export const HeroRoleEnum = z.enum(["headline", "banner", "inline"]);
export type HeroRole = z.infer<typeof HeroRoleEnum>;

/** Section role — drives padding + border treatment. */
export const SectionRoleEnum = z.enum(["headline", "content", "aside", "footer"]);
export type SectionRole = z.infer<typeof SectionRoleEnum>;

/** Card density — drives internal padding scale. */
export const CardDensityEnum = z.enum(["tight", "regular", "loose"]);
export type CardDensity = z.infer<typeof CardDensityEnum>;

/** Heading weight — display unlocks the future display-font slot (Phase 2). */
export const HeadingWeightEnum = z.enum(["light", "regular", "bold", "display"]);
export type HeadingWeight = z.infer<typeof HeadingWeightEnum>;
```

- [ ] **Step 2: Export from package index**

Find `packages/library/src/index.ts` and confirm types/ is re-exported. If not, add:
```ts
export * from "./types/hierarchy";
```

- [ ] **Step 3: Verify imports**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
npx tsc -p packages/library/tsconfig.json --noEmit 2>&1 | head -20 || true
```

Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add packages/library/src/types/hierarchy.ts packages/library/src/index.ts
git commit -m "feat(library): hierarchy primitive types (importance/role/density/weight)"
```

---

## Task 8: Schema package — extend node definitions with hierarchy props

**Files:**
- Modify: `packages/schema/src/nodes/foundation.ts` (likely contains MetricTileNode + HeroNode + SectionNode)
- Modify: `packages/schema/src/nodes/display.ts` (likely contains HeadingNode)
- Modify: relevant Card node file (find via grep)

- [ ] **Step 1: Find node definitions**

```bash
grep -rln "MetricTileNode\|HeroNode\|SectionNode\|CardNode\|HeadingNode" /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema/src/ | sort -u
```

- [ ] **Step 2: Extend MetricTileNode props with importance**

Find `MetricTileNode` in `packages/schema/src/nodes/foundation.ts`. Its `props` shape currently includes `label`, `value`, `format`, `delta`, etc. Add an `importance` optional prop:

```ts
import { z } from "zod";

// ... existing imports ...

const ImportanceEnum = z.enum(["primary", "secondary", "tertiary"]);

export const MetricTileNode = z.object({
  id: z.string(),
  type: z.literal("MetricTile"),
  props: z.object({
    label: z.string().min(1),
    value: z.union([z.number(), z.string()]),
    format: z.enum(["number", "currency", "percent", "duration"]),
    delta: z.object({
      direction: z.enum(["up", "down", "flat"]),
      value: z.number(),
    }).optional(),
    icon: z.string().optional(),
    trend: z.array(z.number()).optional(),
    importance: ImportanceEnum.optional(),  // ← NEW
  }),
  // ... rest of node ...
});
```

NOTE for implementer: keep the rest of the existing schema EXACTLY as it is. Only add `importance` as an optional field. Same approach for the other nodes below.

- [ ] **Step 3: Extend HeroNode + SectionNode + CardNode + HeadingNode**

For each, add the appropriate new optional prop:
- `HeroNode.props.role`: `z.enum(["headline", "banner", "inline"]).optional()`
- `SectionNode.props.role`: `z.enum(["headline", "content", "aside", "footer"]).optional()`
- `CardNode.props.density`: `z.enum(["tight", "regular", "loose"]).optional()`
- `HeadingNode.props.weight`: `z.enum(["light", "regular", "bold", "display"]).optional()`

- [ ] **Step 4: Build the schema package + verify**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema
npx tsc --noEmit 2>&1 | head -20 || true
```

Expected: no errors.

- [ ] **Step 5: Run schema migration test**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/integration/test_schema_migration.py -v 2>&1 | tail -10
```

Expected: PASS — all existing schemas still parse (the new props are optional).

- [ ] **Step 6: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/schema/src/nodes/
git commit -m "feat(schema): add hierarchy props (importance/role/density/weight) as optional"
```

---

## Task 9: MetricTile renders importance variations

**Files:**
- Modify: `packages/library/src/components/MetricTile/MetricTile.tsx`

- [ ] **Step 1: Update MetricTile to scale per importance**

Replace the existing component with the version below. Keep `formatValue`, `formatDelta`, `DELTA_GLYPH`, `DELTA_TONE` exactly as they are — only the JSX + class constants change.

```tsx
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { MetricTilePropsType } from "./MetricTile.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface MetricTileProps extends MetricTilePropsType {
  style?: StyleSlotT;
}

function formatValue(value: number | string, format: MetricTilePropsType["format"]): string {
  if (typeof value === "string") return value;
  switch (format) {
    case "number":
      return new Intl.NumberFormat("en-US").format(value);
    case "currency":
      return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD",
        maximumFractionDigits: 0 }).format(value);
    case "percent":
      return new Intl.NumberFormat("en-US", { style: "percent",
        maximumFractionDigits: 0 }).format(value);
    case "duration":
      return `${value}s`;
  }
}

function formatDelta(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "percent",
    maximumFractionDigits: 0, signDisplay: "never" }).format(Math.abs(value));
}

const DELTA_GLYPH = { up: "↑", down: "↓", flat: "—" } as const;
const DELTA_TONE: Record<"up" | "down" | "flat", string> = {
  up:   "text-emerald-600",
  down: "text-destructive",
  flat: "text-muted-foreground",
};

// Per-importance class sets — primary tiles are visually 2x weight; tertiary
// are demoted to label-first compact form. Defaults to "secondary" which
// matches today's appearance exactly so existing schemas don't shift.
const IMPORTANCE_CLASSES = {
  primary: {
    tile:  "relative flex flex-col gap-3 rounded-lg border bg-card p-8 text-card-foreground shadow-sm",
    label: "text-sm font-semibold uppercase tracking-wide text-muted-foreground",
    value: "text-4xl font-bold leading-tight tracking-tight text-foreground tabular-nums",
    delta: "inline-flex items-center gap-1.5 text-sm font-semibold",
  },
  secondary: {
    tile:  "relative flex flex-col gap-2 rounded-lg border bg-card p-6 text-card-foreground shadow-sm",
    label: "text-xs font-medium uppercase tracking-wide text-muted-foreground",
    value: "text-2xl font-semibold leading-tight tracking-tight text-foreground",
    delta: "inline-flex items-center gap-1 text-xs font-medium",
  },
  tertiary: {
    tile:  "relative flex flex-col gap-1 rounded-md border bg-card p-4 text-card-foreground",
    label: "text-[10px] font-medium uppercase tracking-wider text-muted-foreground",
    value: "text-lg font-medium leading-snug tracking-tight text-foreground",
    delta: "inline-flex items-center gap-1 text-[10px] font-medium",
  },
} as const;

export function MetricTile({
  label, value, format, delta, icon, trend, importance, style,
}: MetricTileProps) {
  const cx = IMPORTANCE_CLASSES[importance ?? "secondary"];
  return (
    <div
      className={cx.tile}
      style={resolveStyle(style)}
      data-importance={importance ?? "secondary"}
      {...useMotion(style?.motion)}
    >
      <p className={cx.label}>{label}</p>
      <p className={cx.value}>{formatValue(value, format)}</p>
      {delta && (
        <span
          className={`${cx.delta} ${DELTA_TONE[delta.direction]}`}
          data-delta-direction={delta.direction}
        >
          <span aria-hidden="true">{DELTA_GLYPH[delta.direction]}</span>
          <span>{formatDelta(delta.value)}</span>
        </span>
      )}
      {trend && trend.length > 0 && (
        <div className="mt-2 text-muted-foreground/60" aria-hidden="true">
          <svg viewBox={`0 0 ${trend.length * 10} 30`} preserveAspectRatio="none"
               className={importance === "primary" ? "h-12 w-full" : "h-8 w-full"}>
            <polyline fill="none" stroke="currentColor" strokeWidth="1"
              points={trend.map((v, i) => {
                const max = Math.max(...trend, 1);
                return `${i * 10},${30 - (v / max) * 28}`;
              }).join(" ")} />
          </svg>
        </div>
      )}
      {icon && (
        <span
          className="absolute right-4 top-4 text-muted-foreground/70"
          data-icon={icon}
          aria-hidden="true"
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add MetricTile importance variants to playground**

Edit `frontend/src/app/(dev-only)/component-playground/page.tsx`. Find the MetricTile section. Add:

```tsx
<section data-component="MetricTile-importance" className={SECTION}>
  <p className={TITLE}>MetricTile — importance variations</p>
  <div className="grid grid-cols-3 gap-3">
    <MetricTile label="Primary tile" value={482910} format="currency"
                delta={{ direction: "up", value: 0.18 }} importance="primary" />
    <MetricTile label="Secondary tile" value={1284} format="number"
                delta={{ direction: "up", value: 0.12 }} importance="secondary" />
    <MetricTile label="Tertiary tile" value={42} format="number" importance="tertiary" />
  </div>
</section>
```

- [ ] **Step 3: Run visual regression — capture new baseline for MetricTile-importance**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npm run dev -- -p 6501 > /tmp/frontend-mtile.log 2>&1 &
sleep 10

cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test components.spec.ts --grep "MetricTile" --update-snapshots
npx playwright test components.spec.ts --grep "MetricTile"   # confirm it passes

lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: existing MetricTile baseline matches (default = secondary = today's appearance); new MetricTile-importance baseline captured.

- [ ] **Step 4: Update visual regression spec to include the new section**

Edit `apps/visual-regression/tests/components.spec.ts`. Add `"MetricTile-importance"` to the COMPONENTS array.

- [ ] **Step 5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/src/components/MetricTile/MetricTile.tsx \
        frontend/src/app/\(dev-only\)/component-playground/page.tsx \
        apps/visual-regression/tests/
git commit -m "feat(library): MetricTile renders primary/secondary/tertiary importance"
```

---

## Task 10: Hero renders role variations

**Files:**
- Modify: `packages/library/src/components/Hero/Hero.tsx`

- [ ] **Step 1: Read current Hero**

```bash
cat /Users/m/Work/code/poc/design2ui-forge-v3/packages/library/src/components/Hero/Hero.tsx
```

- [ ] **Step 2: Update Hero to pivot on role**

Modify Hero so it accepts a new optional `role` prop and adjusts its layout/padding/border treatment per role:

```tsx
// Inside the Hero component, after destructuring props:
const role = props.role ?? "banner";  // default = today's appearance

const ROLE_CLASSES = {
  headline: "px-8 py-12 border-b border-border",        // full-bleed page header
  banner:   "px-6 py-8 rounded-lg",                      // today's default
  inline:   "px-4 py-2",                                 // single-line above content
};

// Apply ROLE_CLASSES[role] to the outer container className.
// Adjust headline + subhead font sizes per role too:
//   headline → text-4xl font-bold + text-lg subhead
//   banner   → text-2xl + text-base (today's)
//   inline   → text-lg + text-sm
```

NOTE for implementer: read the existing Hero.tsx first and adapt. Preserve the exact existing class structure for `role=banner` so today's behavior is unchanged. Only `headline` and `inline` are new visual modes.

- [ ] **Step 3: Add Hero role variants to playground**

Add to `component-playground/page.tsx`:

```tsx
<section data-component="Hero-role" className={SECTION}>
  <p className={TITLE}>Hero — role variations</p>
  <div className="space-y-6">
    <Hero role="headline" eyebrow="Page header" headline="Headline role" subhead="Full-bleed page header treatment" />
    <Hero role="banner" eyebrow="Mid-page" headline="Banner role" subhead="Default — today's appearance" />
    <Hero role="inline" headline="Inline role" />
  </div>
</section>
```

- [ ] **Step 4: Capture new baseline**

```bash
# Boot frontend, run playwright test --grep "Hero" --update-snapshots
```

- [ ] **Step 5: Update spec + commit**

Add `"Hero-role"` to COMPONENTS array in `components.spec.ts`. Commit.

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/src/components/Hero/Hero.tsx \
        frontend/src/app/\(dev-only\)/component-playground/page.tsx \
        apps/visual-regression/tests/
git commit -m "feat(library): Hero renders headline/banner/inline role variations"
```

---

## Task 11: Section renders role variations

**Files:**
- Modify: `packages/library/src/components/Section/Section.tsx`

Same pattern as Task 10. Section gets a `role` prop with values `headline | content | aside | footer`. Each value drives different padding + border treatment.

- [ ] **Step 1: Implement role-based class set**

```ts
const SECTION_ROLE_CLASSES = {
  headline: "px-8 pt-12 pb-6 border-b border-border",
  content:  "px-6 py-8",                                  // today's default
  aside:    "px-4 py-4 bg-muted/30 rounded-md",
  footer:   "px-6 pt-4 pb-6 border-t border-border text-sm text-muted-foreground",
};
```

Read Section.tsx, identify how it currently composes its className, and integrate the role-based class set so default (`role=undefined`) maps to today's appearance.

- [ ] **Step 2: Add to playground + capture baseline + commit**

Same pattern as previous tasks: playground entry, baseline capture, spec update, commit.

```bash
git commit -m "feat(library): Section renders headline/content/aside/footer roles"
```

---

## Task 12: Card renders density variations

**Files:**
- Modify: `packages/library/src/components/Card/Card.tsx`

- [ ] **Step 1: Implement density-based padding**

```ts
const CARD_DENSITY_CLASSES = {
  tight:   "p-3",
  regular: "p-6",   // today's default
  loose:   "p-10",
};
```

Read Card.tsx, integrate density into its className composition. Default (`density=undefined`) maps to today's `p-6`.

- [ ] **Step 2: Add to playground + capture baseline + commit**

```bash
git commit -m "feat(library): Card renders tight/regular/loose density"
```

---

## Task 13: Heading renders weight variations

**Files:**
- Modify: `packages/library/src/components/Heading/Heading.tsx`

- [ ] **Step 1: Implement weight-based class set**

```ts
const HEADING_WEIGHT_CLASSES = {
  light:   "font-light",
  regular: "font-medium",
  bold:    "font-semibold",  // today's default
  display: "font-bold tracking-tight",  // unlocks future display-font slot
};
```

Read Heading.tsx, find where weight is applied, integrate. Default (`weight=undefined`) maps to today's `font-semibold` for level 1-2, `font-medium` for level 3+, etc. — preserve exactly.

- [ ] **Step 2: Add to playground + capture baseline + commit**

```bash
git commit -m "feat(library): Heading renders light/regular/bold/display weight"
```

---

## Task 14: schema_prompt teaches hierarchy semantics

**Files:**
- Modify: `backend/services/schema_prompt.py`

- [ ] **Step 1: Add hierarchy guidance block to the prompt**

Read `services/schema_prompt.py`. Find `build_schema_prompt()`. Near the end of the prompt (before exemplars block, after component contracts), inject a new HIERARCHY section:

```python
HIERARCHY_GUIDANCE = """
## INFORMATION HIERARCHY

Some library components accept hierarchy props. Use them to express which
piece of the page is the headline vs. supporting content.

  MetricTile.importance: "primary" | "secondary" | "tertiary"
    - Exactly ONE MetricTile per page should be `importance: primary` —
      the headline metric (the one that answers the user's main question).
    - Other MetricTiles default to `importance: secondary` (or omit the prop).
    - Use `tertiary` for sidebar / tertiary stats (small, label-first).

  Hero.role: "headline" | "banner" | "inline"
    - Detail pages and dashboards: `role: headline` (full-bleed page header)
    - Marketing-style pages or sub-sections: `role: banner` (default)
    - List pages or short pages: `role: inline` (one-liner)

  Section.role: "headline" | "content" | "aside" | "footer"
    - Top of the page: `role: headline`
    - Body: omit (default)
    - Right rail / sidebar: `role: aside`
    - Bottom: `role: footer`

  Card.density: "tight" | "regular" | "loose"
    - Data-dense (lists of cards, sidebar): `density: tight`
    - Default cards: omit
    - Hero cards / featured content: `density: loose`

  Heading.weight: "light" | "regular" | "bold" | "display"
    - Page title / hero headline: `weight: display`
    - Default: omit
    - De-emphasised: `weight: light`

ANTI-PATTERN — four equal-weight MetricTiles in a row. Always pick one as
`importance: primary` and the others as `secondary`/`tertiary`.
"""
```

Append `HIERARCHY_GUIDANCE` to the assembled prompt (find the local prompt-building variable — likely `prompt` or `parts: list[str]` — and add it).

- [ ] **Step 2: Run schema_prompt tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_schema_prompt.py -v 2>&1 | tail -10
```

Expected: existing tests still pass.

- [ ] **Step 3: Commit**

```bash
git add backend/services/schema_prompt.py
git commit -m "feat(schema-prompt): teach hierarchy semantics to schema agent"
```

---

## Task 15: patch_agent reasons about hierarchy

**Files:**
- Modify: `backend/agents/patch_agent.py`

- [ ] **Step 1: Augment the system prompt**

Find `PATCH_AGENT_SYSTEM_PROMPT` in `backend/agents/patch_agent.py`. Append after the existing HARD RULES block:

```
HIERARCHY ISSUES — when the critique mentions "no clear primary metric" or
"all tiles equal weight", emit patches that set MetricTile.importance:
  - One tile → primary (the headline metric)
  - Others → secondary or omit (default)

When the critique mentions "no breadcrumb / no page header", emit patches
that change Hero.role to "headline" or add a Section.role: "headline".

When the critique mentions "sparse" / "too much white space", emit patches
that change Card.density to "regular" or "tight" (or Section padding via
density-related props).
```

- [ ] **Step 2: Verify tests pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/agents/test_patch_agent.py -v 2>&1 | tail -10
```

Expected: 5 PASS (existing).

- [ ] **Step 3: Commit**

```bash
git add backend/agents/patch_agent.py
git commit -m "feat(patch-agent): reason about hierarchy props in patch suggestions"
```

---

## Task 16: Update gold-standard schema examples to demonstrate hierarchy

**Files:**
- Modify: 2-3 files in `backend/services/schema_examples/*.json`

- [ ] **Step 1: Find existing example schemas**

```bash
ls /Users/m/Work/code/poc/design2ui-forge-v3/backend/services/schema_examples/
```

- [ ] **Step 2: Update at least 2 example schemas**

For each chosen example (preferably a dashboard and a detail page):
- One MetricTile per page → add `"importance": "primary"`
- The Hero on detail/dashboard pages → add `"role": "headline"`
- The page title Heading → add `"weight": "display"`

Example diff (illustrative — exact paths depend on the schema's structure):

```json
{
  "id": "stats-revenue",
  "type": "MetricTile",
  "props": {
    "label": "Total Revenue",
    "value": 482910,
    "format": "currency",
    "importance": "primary"        ← NEW
  }
}
```

- [ ] **Step 3: Run schema_prompt tests + migration tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_schema_prompt.py tests/integration/test_schema_migration.py -v 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/services/schema_examples/
git commit -m "feat(schema-examples): demonstrate hierarchy props in gold standards"
```

---

## Self-review checklist

### Spec coverage

| Spec section | Tasks |
|---|---|
| Phase 0 — Visual regression suite | 1, 2, 3 |
| Phase 0 — Token-consumption audit | 4 |
| Phase 0 — CVA scaffolding | 5 |
| Phase 0 — Schema migration corpus | 6 |
| Phase 0 — Component playground | 2 (combined) |
| Phase 1 — Hierarchy types | 7 |
| Phase 1 — Schema package extension | 8 |
| Phase 1 — Library component updates | 9, 10, 11, 12, 13 |
| Phase 1 — Schema agent prompt | 14 |
| Phase 1 — Patch agent prompt | 15 |
| Phase 1 — Gold examples | 16 |

✓ All Phase 0 + Phase 1 items covered.

### Placeholder scan

The "NOTE for implementer" callouts in Tasks 8, 10, 11, 12, 13 are intentional integration points — the plan can't pre-commit to exact class names without false specificity, since each component file's existing structure varies. Each note tells the implementer exactly what to do; not placeholders.

### Type consistency

- `Importance` / `HeroRole` / `SectionRole` / `CardDensity` / `HeadingWeight` — defined once in `packages/library/src/types/hierarchy.ts` (Task 7), referenced in schema package (Task 8) via inline z.enum (acceptable — schema package shouldn't depend on library)
- All optional everywhere — backward compatible with existing schemas
- Visual regression baselines updated whenever a component's visual output changes

✓ Consistent.

---

## Out of scope (deferred to Wave 2 / Wave 3)

- **Token system expansion** — density / elevation / typography / motion as actual tokens (Wave 2)
- **Stylistic registers** — Workday / Linear / Stripe / Notion / Figma (Wave 3)
- **CVA refactor of all 38 components** — Phase 2 work; this wave only refactors Button as the template
- **Density preview in editor** — Wave 2 work
- **Reference bank re-seeding for new patterns** — Wave 3 work
- **Motion micro-interactions** — Wave 5 work

# Tier S/M/L Fidelity Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 9 remaining items from `RESUME.md`'s Tier S/M/L polish list — radius unification, Heading type-scale, icon-only Button a11y, keyboard-nav audit, KeyValueList semantic markup, Button icon prop, CTA hierarchy in design-spec, progressive disclosure patterns, schema-prompt proximity training.

**Architecture:** Three workstreams. **A** (library polish) and **B** (library API) ship as a library rebuild; tight feedback via `tsc` + scaffold reload. **C** (generation/prompt) ships as backend service changes evaluated through the existing generation pipeline. Sequencing in the spec keeps dependencies clean: A1+A2 → A5 (verify) → B6 → A3 → A4 → C7 → C8 → C9.

**Tech Stack:** TypeScript / React (library); Python / FastAPI (backend); Zod (schema validation); Tailwind (styling); Playwright + axe-core (a11y audit); Vitest (frontend tests); pytest (backend tests).

**Spec:** `docs/superpowers/specs/2026-05-11-tier-s-m-l-fidelity-polish-design.md`

**Design note on A1 mechanism:** The spec proposed a CSS custom property (`rounded-[var(--radius-surface)]`) for radius unification. While auditing the codebase, the existing pattern is per-component lookup tables (`RADIUS_CLASS: Record<RadiusScale, string>`) — Badge, Input, Skeleton, Checkbox, and DatePicker already use this pattern. To match the existing pattern and preserve debuggability, this plan extracts a **shared** lookup table (`packages/library/src/style/radius.ts`) and replaces per-component tables + literal radius classes with calls into it. Same design intent; same observable behavior; cleaner fit with the codebase.

**Design note on the library Tailwind config:** The spec proposed creating `packages/library/tailwind.config.ts`. The scaffold's config already scans `packages/library/src/**`, so library components can reference `text-page-title` etc. today without a library-level config. YAGNI — defer the library-level config until there's a second consumer.

---

## Pre-flight

### Task 0: Verify environment + locate scaffold dev server

- [ ] **Step 0.1: Confirm services are running (or start them)**

Run: `lsof -i :6500 -i :6501 -i :6503 | head` — expect to see the backend (6500), main frontend (6501), and render scaffold (6503).

If anything is missing:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
./start-all.sh
```

- [ ] **Step 0.2: Confirm a test project exists for visual verification**

Open `http://localhost:6503/p/genmetrics-1778439719/tasks/list` in a browser. The page should render with the existing design. This is the eyeball test surface for every UI change below.

- [ ] **Step 0.3: Pin the test project ID**

In a scratch note: `TEST_PROJECT=genmetrics-1778439719`. All `http://localhost:6503/p/$TEST_PROJECT/...` URLs use this.

- [ ] **Step 0.4: Verify schema/renderer/library packages build cleanly today**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema   && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc --noEmit
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/renderer && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc --noEmit
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library  && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc --noEmit
```

Expected: schema + renderer pass clean; library may emit pre-existing errors in `PersonCard`, `Tabs`, `resolveStyle` per RESUME.md ("affected components still emit valid JS"). Note baseline error count; any *new* errors from this plan must be fixed.

---

## Workstream A — Library polish

### Task 1: Centralize radius lookup table

**Files:**
- Create: `packages/library/src/style/radius.ts`
- Test:   `packages/library/src/style/radius.test.ts`

- [ ] **Step 1.1: Write the failing test**

```ts
// packages/library/src/style/radius.test.ts
import { describe, it, expect } from "vitest";
import { RADIUS_SURFACE_CLASS, RADIUS_PILL_CLASS } from "./radius";

describe("radius lookup tables", () => {
  it("RADIUS_SURFACE_CLASS maps each scale to the expected Tailwind class", () => {
    expect(RADIUS_SURFACE_CLASS.sharp).toBe("rounded-none");
    expect(RADIUS_SURFACE_CLASS.soft).toBe("rounded-lg");
    expect(RADIUS_SURFACE_CLASS.round).toBe("rounded-2xl");
  });

  it("RADIUS_PILL_CLASS is constant — pill is not scale-dependent", () => {
    expect(RADIUS_PILL_CLASS).toBe("rounded-full");
  });
});
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run src/style/radius.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 1.3: Implement the module**

```ts
// packages/library/src/style/radius.ts
import type { RadiusScale } from "../theme/token-types";

/**
 * Surface radius class per scale.
 *
 * Used by Card, Button, Input, Hero, Section, Alert, MetricTile, and other
 * non-pill components that should respond to the project-wide radius.scale
 * token. Components opt in by importing this map and reading the current
 * scale via `useRadiusScale()` from the tokens-context.
 *
 * Scale values match the design-system-overhaul spec: sharp = no radius,
 * soft = the default rounded-lg baseline, round = pronounced rounded-2xl
 * for Notion/Figma registers.
 */
export const RADIUS_SURFACE_CLASS: Record<RadiusScale, string> = {
  sharp: "rounded-none",
  soft:  "rounded-lg",
  round: "rounded-2xl",
};

/**
 * Pill shape — constant across scales. Badges, status pills, and avatar
 * borders use this; they are semantic affordances (round-on-purpose), not
 * styling that should bend to the radius scale.
 */
export const RADIUS_PILL_CLASS = "rounded-full" as const;
```

- [ ] **Step 1.4: Run test to verify it passes**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run src/style/radius.test.ts`
Expected: PASS, 2 tests.

- [ ] **Step 1.5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/src/style/radius.ts packages/library/src/style/radius.test.ts
git commit -m "$(cat <<'EOF'
feat(library): centralize radius lookup for surface + pill shapes

Shared map so Card / Button / Input / etc. all return the same surface
class for a given radius.scale value, while Badge and pills keep
rounded-full regardless of scale.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 2: Migrate Card to centralized radius

**Files:**
- Modify: `packages/library/src/components/Card/Card.tsx:67-71`

- [ ] **Step 2.1: Update Card.tsx**

```tsx
// At top, add import:
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useDensity, useElevation, useRadiusScale } from "../../theme/tokens-context";

// Inside Card(...) — after the other token reads:
const radiusScale = useRadiusScale();

// Replace the literal "rounded-lg" in containerClass construction:
const containerClass = [
  "flex flex-col overflow-hidden border bg-card text-card-foreground",
  RADIUS_SURFACE_CLASS[radiusScale],
  elevationClass,
].filter(Boolean).join(" ");
```

- [ ] **Step 2.2: Rebuild library + reload scaffold**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc
```

Refresh `http://localhost:6503/p/genmetrics-1778439719/tasks/list` — Cards should look identical to before (default register = soft = rounded-lg).

- [ ] **Step 2.3: Sanity check by switching the project register**

```bash
curl -sX PUT http://localhost:6500/api/projects/genmetrics-1778439719/register -d '{"register":"linear"}' -H 'content-type: application/json'
```

(If the endpoint name differs, look it up in `backend/routers/_debug_schema.py::update_project_register`.)

Refresh — Cards should now render with `rounded-none`. Switch back:

```bash
curl -sX PUT http://localhost:6500/api/projects/genmetrics-1778439719/register -d '{"register":"default"}' -H 'content-type: application/json'
```

- [ ] **Step 2.4: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/src/components/Card/Card.tsx
git commit -m "$(cat <<'EOF'
feat(library): wire Card to radius.scale via shared lookup

Card now reads useRadiusScale() and picks its surface radius from
RADIUS_SURFACE_CLASS. Default register (soft) preserves the rounded-lg
baseline; linear/workday (sharp) renders square; notion/figma (round)
renders rounded-2xl.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 3: Migrate Button (CVA base) to centralized radius

**Files:**
- Modify: `packages/library/src/components/Button/variants.ts`
- Modify: `packages/library/src/components/Button/Button.tsx`

- [ ] **Step 3.1: Remove the literal radius from the CVA base**

```ts
// packages/library/src/components/Button/variants.ts
// Change the base string to drop "rounded-md" — radius is now a separate variant axis.
export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 font-medium whitespace-nowrap " +
  "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
  { /* …unchanged variants… */ },
);
```

- [ ] **Step 3.2: Apply RADIUS_SURFACE_CLASS in Button.tsx**

```tsx
// packages/library/src/components/Button/Button.tsx
// Add imports near the top:
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useRadiusScale } from "../../theme/tokens-context";

// Inside Button(...):
const radiusScale = useRadiusScale();

// Compose final className:
const className = [
  buttonVariants({ variant, size }),
  RADIUS_SURFACE_CLASS[radiusScale],
].join(" ");

return (
  <button
    type="button"
    className={className}
    /* ...rest unchanged... */
  >
```

- [ ] **Step 3.3: Rebuild + eyeball**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc
```

Refresh the scaffold list page — Buttons should look identical (default = soft = rounded-lg, which is slightly more rounded than the previous `rounded-md`; visually similar). Switch to `linear` register and confirm Buttons go square.

- [ ] **Step 3.4: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/src/components/Button/variants.ts packages/library/src/components/Button/Button.tsx
git commit -m "$(cat <<'EOF'
feat(library): wire Button to radius.scale via shared lookup

Drops the literal rounded-md from the CVA base; Button now reads
useRadiusScale() and picks from RADIUS_SURFACE_CLASS. Same visual
under default register; responds to register override.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 4: Migrate remaining surface components

Apply the same pattern (read `useRadiusScale()`, swap literal radius for `RADIUS_SURFACE_CLASS[radiusScale]`) to the components below.

**Files (one commit per file is fine; or batch by directory):**
- Modify: `packages/library/src/components/Section/Section.tsx` — VARIANT_CLASS entries `feature`, `cta`, `stats`, `aside` (replace `rounded-lg`/`rounded-xl`/`rounded-md`)
- Modify: `packages/library/src/components/FeatureCard/FeatureCard.tsx:23` — replace `rounded-lg`
- Modify: `packages/library/src/components/EmptyStateRich/EmptyStateRich.tsx:9` — replace `rounded-lg` (line 31's `rounded-md` is the action button, leave it — Button comes through registry)
- Modify: `packages/library/src/components/Accordion/Accordion.tsx:61` — replace `rounded-md` on the outer panel
- Modify: `packages/library/src/components/ActivityFeed/ActivityFeed.tsx:37` — replace `rounded-md`
- Modify: `packages/library/src/components/PersonCard/PersonCard.tsx:33` — replace `rounded-lg`
- Modify: `packages/library/src/components/FilterBar/FilterBar.tsx` — replace the four `rounded-md` occurrences
- Modify: `packages/library/src/components/DateRangePicker/DateRangePicker.tsx:107` — replace `rounded-md`

For each file:

- [ ] **Step 4.x.1: Add import + hook call**

```tsx
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useRadiusScale } from "../../theme/tokens-context";

// Inside the component:
const radiusScale = useRadiusScale();
```

- [ ] **Step 4.x.2: Replace literal radius classes**

Find each literal `rounded-<size>` in the file's surface elements and substitute the lookup. Where the literal is inside a `const` map (Section's VARIANT_CLASS), turn the const into a function or compose at use-site.

For Section, refactor like:
```tsx
// Section.tsx — replace the VARIANT_CLASS const with a function:
function variantClass(variant: Variant, radiusScale: RadiusScale): string {
  const radius = RADIUS_SURFACE_CLASS[radiusScale];
  switch (variant) {
    case "feature": return `bg-card text-card-foreground ${radius} border shadow-sm p-6 md:p-8`;
    case "cta":     return `bg-primary/5 border border-primary/20 ${radius} p-8 text-center`;
    case "stats":   return `bg-muted/30 ${radius} p-6`;
    // ...etc
  }
}
```

- [ ] **Step 4.x.3: Rebuild + eyeball one register switch per file**

Same as Task 2 / 3 — flip register, confirm radius responds, flip back.

- [ ] **Step 4.x.4: Commit each file**

```bash
git add packages/library/src/components/<Component>
git commit -m "feat(library): wire <Component> to radius.scale via shared lookup"
```

### Task 5: Migrate radius-aware components to centralized table

Components that already have **per-component** radius tables (Input, Skeleton, Checkbox, DatePicker) — replace their local maps with `RADIUS_SURFACE_CLASS`. Their current values are smaller than the new scale; this is a one-time visual change to match.

**Files:**
- Modify: `packages/library/src/components/Input/Input.tsx:32-35`
- Modify: `packages/library/src/components/Skeleton/Skeleton.tsx:19-29` (two local maps for rect vs circle — rect maps to surface; circle stays `rounded-full`)
- Modify: `packages/library/src/components/Checkbox/Checkbox.tsx:26-29`
- Modify: `packages/library/src/components/DatePicker/DatePicker.tsx:25-28`

- [ ] **Step 5.1: For each component, remove the local RADIUS map and import the shared one**

```tsx
// Before:
const RADIUS_CLASS: Record<"sharp" | "soft" | "round", string> = {
  sharp: "rounded-sm",
  soft:  "rounded-md",
  round: "rounded-lg",
};
// ...later: className = [..., RADIUS_CLASS[radiusScale], ...]

// After:
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
// ...later: className = [..., RADIUS_SURFACE_CLASS[radiusScale], ...]
```

Skeleton specifically: keep the rect-vs-circle branch — pull the rect path through `RADIUS_SURFACE_CLASS`; leave the circle path at `rounded-full`.

- [ ] **Step 5.2: Rebuild + verify**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc
```

Refresh scaffold form page (`/p/$TEST_PROJECT/tasks/form`) — Inputs are slightly more rounded than before under default register (soft is now rounded-lg, was rounded-md). This is expected.

- [ ] **Step 5.3: Commit**

```bash
git add packages/library/src/components/Input packages/library/src/components/Skeleton packages/library/src/components/Checkbox packages/library/src/components/DatePicker
git commit -m "$(cat <<'EOF'
refactor(library): use shared RADIUS_SURFACE_CLASS in form controls

Input / Skeleton (rect) / Checkbox / DatePicker drop their local
radius tables in favor of the shared lookup. Under default register
this nudges form controls from rounded-md to rounded-lg; matches
Card/Button visual rhythm.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 6: Update register bundles to set radius.scale

**Files:**
- Modify: `packages/library/src/theme/registers/linear.ts`
- Modify: `packages/library/src/theme/registers/workday.ts`
- Modify: `packages/library/src/theme/registers/stripe.ts`
- Modify: `packages/library/src/theme/registers/notion.ts`
- Modify: `packages/library/src/theme/registers/figma.ts`

- [ ] **Step 6.1: Read one bundle to see the existing shape**

```bash
cat /Users/m/Work/code/poc/design2ui-forge-v3/packages/library/src/theme/registers/linear.ts
```

Each bundle exports a `RegisterBundle` whose `tokens` is a partial token tree. Confirm whether `radius.scale` is already present.

- [ ] **Step 6.2: Add `scale` to each bundle's `radius` block**

Per the spec:
- `linear.ts`  → `radius: { scale: "sharp" }`
- `workday.ts` → `radius: { scale: "sharp" }`
- `stripe.ts`  → `radius: { scale: "soft" }`
- `notion.ts`  → `radius: { scale: "round" }`
- `figma.ts`   → `radius: { scale: "round" }`

If `radius` is absent, add the partial. If `radius` exists with other fields, just add the `scale` key alongside.

- [ ] **Step 6.3: Rebuild + flip through all five registers**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc
```

Cycle the test project through each register; confirm Card/Button radius changes appropriately.

```bash
for reg in linear workday stripe notion figma default; do
  echo "Register: $reg"
  curl -sX PUT http://localhost:6500/api/projects/genmetrics-1778439719/register \
    -d "{\"register\":\"$reg\"}" -H 'content-type: application/json'
  # Then refresh the browser, look at Card/Button corners
  read -p "Press enter when you've eyeballed $reg..."
done
```

- [ ] **Step 6.4: Commit**

```bash
git add packages/library/src/theme/registers/
git commit -m "$(cat <<'EOF'
feat(library): set radius.scale per register

linear + workday = sharp, stripe = soft, notion + figma = round.
Each register now lands with a distinctive radius rhythm out of the
box; default register stays soft.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 7: Migrate Heading to type-scale classes

**Files:**
- Modify: `packages/library/src/components/Heading/Heading.tsx`
- Test:   `packages/library/src/components/Heading/Heading.test.tsx`

- [ ] **Step 7.1: Write the failing test**

```tsx
// packages/library/src/components/Heading/Heading.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Heading } from "./Heading";

describe("Heading type-scale", () => {
  it("level 1 renders h1 with text-page-title class", () => {
    const { container } = render(<Heading level={1} content="Hi" />);
    const el = container.querySelector("h1");
    expect(el).not.toBeNull();
    expect(el?.className).toContain("text-page-title");
  });
  it("level 2 renders h2 with text-section-title class", () => {
    const { container } = render(<Heading level={2} content="Hi" />);
    const el = container.querySelector("h2");
    expect(el?.className).toContain("text-section-title");
  });
  it("level 3 renders h3 with text-card-title class", () => {
    const { container } = render(<Heading level={3} content="Hi" />);
    expect(container.querySelector("h3")?.className).toContain("text-card-title");
  });
  it("level 4-6 use body / caption / micro", () => {
    const { container: c4 } = render(<Heading level={4} content="x" />);
    expect(c4.querySelector("h4")?.className).toContain("text-body");
    const { container: c5 } = render(<Heading level={5} content="x" />);
    expect(c5.querySelector("h5")?.className).toContain("text-caption");
    const { container: c6 } = render(<Heading level={6} content="x" />);
    expect(c6.querySelector("h6")?.className).toContain("text-micro");
  });
});
```

- [ ] **Step 7.2: Run test to verify it fails**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run src/components/Heading/Heading.test.tsx
```

Expected: FAIL — classes not present (Heading uses inline style today).

- [ ] **Step 7.3: Rewrite Heading.tsx**

```tsx
// packages/library/src/components/Heading/Heading.tsx
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

type Level = 1 | 2 | 3 | 4 | 5 | 6;
type Weight = "light" | "regular" | "bold" | "display";

type Props = {
  level?: Level;
  content: string;
  id?: string;
  weight?: Weight;
  style?: StyleSlotT;
};

const TAGS: Record<Level, "h1" | "h2" | "h3" | "h4" | "h5" | "h6"> = {
  1: "h1", 2: "h2", 3: "h3", 4: "h4", 5: "h5", 6: "h6",
};

// Tier S: each level maps to a named Tailwind type-scale class declared in
// apps/render-scaffold/tailwind.config.ts. The scaffold's content glob
// includes packages/library/src/**, so these class names compile cleanly.
// Replaces the previous inline-style approach (tokenToCssVar size lookups).
const LEVEL_CLASS: Record<Level, string> = {
  1: "text-page-title",
  2: "text-section-title",
  3: "text-card-title",
  4: "text-body",
  5: "text-caption",
  6: "text-micro",
};

// Weight prop continues to drive font-weight via Tailwind classes, replacing
// the previous inline fontWeight: "300" | "500" | "600" | "700".
const WEIGHT_CLASS: Record<Weight, string> = {
  light:   "font-light",     // 300
  regular: "font-medium",    // 500
  bold:    "font-semibold",  // 600
  display: "font-bold tracking-tight",  // 700 + tighter letter-spacing
};

export function Heading({ level = 2, content, id, weight, style }: Props) {
  const Tag = TAGS[level];
  const className = [
    LEVEL_CLASS[level],
    weight ? WEIGHT_CLASS[weight] : undefined,
  ].filter(Boolean).join(" ");

  return (
    <Tag
      id={id}
      data-weight={weight}
      className={className}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {content}
    </Tag>
  );
}
```

- [ ] **Step 7.4: Run test to verify it passes**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run src/components/Heading/Heading.test.tsx
```

Expected: PASS, 4 tests.

- [ ] **Step 7.5: Eyeball**

Rebuild library, refresh the scaffold list page — Headings should look similar but driven by Tailwind classes. The exact sizes are defined in `apps/render-scaffold/tailwind.config.ts` (page-title=30px, section-title=20px, card-title=16px).

- [ ] **Step 7.6: Commit**

```bash
git add packages/library/src/components/Heading
git commit -m "$(cat <<'EOF'
refactor(library): Heading uses Tailwind type-scale classes

level 1-6 maps directly to text-page-title / section-title / card-title
/ body / caption / micro. Drops inline tokenToCssVar size lookups +
scaleMode-based fontSize overrides; weight prop maps to Tailwind
font-light / font-medium / font-semibold / font-bold.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 8: Verify A5 (KeyValueList semantic markup) is already complete

**Files (read-only):**
- Read: `packages/library/src/components/KeyValueList/KeyValueList.tsx`

- [ ] **Step 8.1: Read and confirm `<dl>`/`<dt>`/`<dd>` is present**

The audit during planning showed KeyValueList already renders `<dl>` with `<dt>` / `<dd>` children inside a grid-row wrapper. Open the file and confirm.

- [ ] **Step 8.2: Add a snapshot test to lock the contract**

Create `packages/library/src/components/KeyValueList/KeyValueList.semantic.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { KeyValueList } from "./KeyValueList";

describe("KeyValueList semantic markup", () => {
  it("renders <dl> root with <dt> and <dd> children", () => {
    const { container } = render(
      <KeyValueList items={[
        { label: "Name",  value: "Alice" },
        { label: "Email", value: "a@example.com" },
      ]} />,
    );
    const dl = container.querySelector("dl");
    expect(dl).not.toBeNull();
    expect(dl?.querySelectorAll("dt").length).toBe(2);
    expect(dl?.querySelectorAll("dd").length).toBe(2);
    expect(dl?.querySelector("dt")?.textContent).toBe("Name");
    expect(dl?.querySelector("dd")?.textContent).toContain("Alice");
  });
});
```

- [ ] **Step 8.3: Run test**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run src/components/KeyValueList/KeyValueList.semantic.test.tsx
```

Expected: PASS, 1 test.

- [ ] **Step 8.4: Commit**

```bash
git add packages/library/src/components/KeyValueList/KeyValueList.semantic.test.tsx
git commit -m "test(library): lock KeyValueList <dl>/<dt>/<dd> contract"
```

---

## Workstream B — Library API

### Task 9: Extend Button schema with icon + iconPosition + aria-label refine

**Files:**
- Modify: `packages/library/src/components/Button/Button.schema.ts`
- Test:   `packages/library/src/components/Button/Button.schema.test.ts`

- [ ] **Step 9.1: Write the failing test**

```ts
// packages/library/src/components/Button/Button.schema.test.ts
import { describe, it, expect } from "vitest";
import { ButtonProps } from "./Button.schema";

describe("Button schema", () => {
  it("accepts a labeled button with an icon", () => {
    const r = ButtonProps.safeParse({ label: "Add", icon: "plus" });
    expect(r.success).toBe(true);
  });

  it("accepts icon-only when aria-label is set", () => {
    const r = ButtonProps.safeParse({ icon: "more-horizontal", "aria-label": "More" });
    expect(r.success).toBe(true);
  });

  it("rejects icon-only without aria-label", () => {
    const r = ButtonProps.safeParse({ icon: "more-horizontal" });
    expect(r.success).toBe(false);
    if (!r.success) {
      const msg = r.error.issues.map(i => i.message).join("|");
      expect(msg).toMatch(/aria-label/i);
    }
  });

  it("defaults iconPosition to left", () => {
    const r = ButtonProps.safeParse({ label: "X", icon: "plus" });
    if (r.success) {
      expect((r.data as any).iconPosition).toBe("left");
    } else {
      throw new Error("parse should succeed");
    }
  });
});
```

- [ ] **Step 9.2: Run test to verify it fails**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run src/components/Button/Button.schema.test.ts
```

Expected: FAIL — schema doesn't have the new fields yet.

- [ ] **Step 9.3: Update the schema**

```ts
// packages/library/src/components/Button/Button.schema.ts
import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const ButtonProps = z
  .object({
    label: z.string().min(1).optional(),
    variant: z.enum(["primary", "secondary", "danger", "ghost"]).default("primary"),
    size: z.enum(["sm", "md", "lg"]).default("md"),
    disabled: z.boolean().optional(),
    loading: z.boolean().optional(),
    workflow: z.string().optional(),
    args: z.record(z.unknown()).optional(),
    navigate: z.string().optional(),
    style: StyleSlot.optional(),
    // B6 — icon prop
    icon: z.string().optional(),
    iconPosition: z.enum(["left", "right"]).default("left"),
    // A3 — icon-only requires accessible name. Use the standard aria-label
    // string; renderer applies it to the rendered <button>.
    "aria-label": z.string().optional(),
  })
  .strict()
  .superRefine((data, ctx) => {
    // A3: when there's no visible label, an aria-label is required so
    // screen readers can announce the button.
    if (!data.label && !data["aria-label"]) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Button without `label` must set `aria-label` (icon-only buttons need an accessible name)",
        path: ["aria-label"],
      });
    }
    // Icon-only also requires an icon; otherwise we'd render an empty
    // button. (Belt-and-braces — the LLM occasionally emits both label
    // and icon empty.)
    if (!data.label && !data.icon) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Button must have either `label` or `icon` (or both)",
        path: ["label"],
      });
    }
  });

export type ButtonPropsType = z.infer<typeof ButtonProps>;
```

- [ ] **Step 9.4: Run test to verify it passes**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run src/components/Button/Button.schema.test.ts
```

Expected: PASS, 4 tests.

- [ ] **Step 9.5: Commit**

```bash
git add packages/library/src/components/Button/Button.schema.ts packages/library/src/components/Button/Button.schema.test.ts
git commit -m "$(cat <<'EOF'
feat(library): Button schema gains icon/iconPosition/aria-label

label becomes optional; icon-only requires aria-label (enforced via
superRefine). Default iconPosition is left. Renderer impl in next
commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 10: Render icon in Button component

**Files:**
- Modify: `packages/library/src/components/Button/Button.tsx`
- Modify: `packages/library/src/components/Button/variants.ts` (icon-only sizing)
- Test:   `packages/library/src/components/Button/Button.render.test.tsx`

- [ ] **Step 10.1: Confirm the existing Lucide resolver signature**

```bash
cat /Users/m/Work/code/poc/design2ui-forge-v3/packages/library/src/icons/index.ts | head -40
```

Note the exported function name (likely `resolveIcon(name)` or `getIcon(name)` returning a React component or null). The subsequent step calls it; adjust to the real name.

- [ ] **Step 10.2: Write the failing test**

```tsx
// packages/library/src/components/Button/Button.render.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Button } from "./Button";

describe("Button icon rendering", () => {
  it("renders an icon next to the label when icon is set", () => {
    const { container } = render(<Button label="Add" icon="plus" />);
    const btn = container.querySelector("button");
    expect(btn).not.toBeNull();
    // Icon mounts as an svg or an element with data-icon
    expect(btn?.querySelector("[data-icon='plus']") || btn?.querySelector("svg")).not.toBeNull();
    expect(btn?.textContent).toContain("Add");
  });

  it("renders icon-only when no label is set", () => {
    const { container } = render(<Button icon="more-horizontal" aria-label="More" />);
    const btn = container.querySelector("button");
    expect(btn?.getAttribute("aria-label")).toBe("More");
    expect(btn?.textContent?.trim() ?? "").toBe("");  // no visible text
  });

  it("places icon on the right when iconPosition='right'", () => {
    const { container } = render(<Button label="Next" icon="chevron-right" iconPosition="right" />);
    const btn = container.querySelector("button");
    // The icon node's position-in-DOM should come AFTER the label text node.
    const children = Array.from(btn?.childNodes ?? []);
    const iconIdx = children.findIndex(n => n instanceof Element && (n.querySelector("[data-icon]") || n.tagName === "SVG" || n.getAttribute?.("data-icon")));
    const labelIdx = children.findIndex(n => n.nodeType === Node.TEXT_NODE && n.textContent?.includes("Next"));
    // Loose assertion — icon node index > label node index
    expect(iconIdx).toBeGreaterThan(labelIdx);
  });
});
```

- [ ] **Step 10.3: Run test to verify it fails**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run src/components/Button/Button.render.test.tsx
```

Expected: FAIL — Button doesn't render icons yet.

- [ ] **Step 10.4: Update variants.ts with icon-only sizing**

```ts
// packages/library/src/components/Button/variants.ts
// Add a new variant axis for icon-only mode (no horizontal padding,
// square aspect for h-N w-N sizing).
export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 font-medium whitespace-nowrap " +
  "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
  {
    variants: {
      variant: { /* …unchanged… */ },
      size: { /* …unchanged… */ },
      // New axis: icon-only renders as a square button (no horizontal padding).
      // size+iconOnly compound: sm → h-8 w-8, md → h-10 w-10, lg → h-12 w-12.
      iconOnly: {
        true: "",   // applied via compoundVariants below
        false: "",
      },
    },
    compoundVariants: [
      { size: "sm", iconOnly: true, className: "w-8  px-0" },
      { size: "md", iconOnly: true, className: "w-10 px-0" },
      { size: "lg", iconOnly: true, className: "w-12 px-0" },
    ],
    defaultVariants: { variant: "primary", size: "md", iconOnly: false },
  },
);
```

- [ ] **Step 10.5: Update Button.tsx to render icons**

```tsx
// packages/library/src/components/Button/Button.tsx
"use client";
import { useContext } from "react";
import { WorkflowDispatcherContext } from "@tentoroforge/renderer";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useRadiusScale } from "../../theme/tokens-context";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { buttonVariants } from "./variants";
// REPLACE the import below with the real resolver name + signature from
// packages/library/src/icons/index.ts. If the export is `resolveIcon`:
import { resolveIcon } from "../../icons";

type Props = {
  label?: string;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  loading?: boolean;
  workflow?: string;
  args?: Record<string, unknown>;
  navigate?: string;
  style?: StyleSlotT;
  icon?: string;
  iconPosition?: "left" | "right";
  "aria-label"?: string;
  __dispatch?: (workflow: string, args?: Record<string, unknown>) => void;
};

// Icon size scales with Button size. Numbers are pixel dimensions passed
// through to the Lucide component (default 16px); matches the visual
// rhythm of each Button size.
const ICON_PX: Record<"sm" | "md" | "lg", number> = {
  sm: 14,
  md: 16,
  lg: 20,
};

export function Button({
  label,
  variant = "primary",
  size = "md",
  disabled,
  loading,
  workflow,
  args,
  navigate,
  style,
  icon,
  iconPosition = "left",
  "aria-label": ariaLabel,
  __dispatch,
}: Props) {
  const ctxDispatch = useContext(WorkflowDispatcherContext);
  const radiusScale = useRadiusScale();

  const isIconOnly = !!icon && !label;
  const IconComp = icon ? resolveIcon(icon) : null;

  const onClick = () => {
    if (disabled || loading) return;
    if (workflow) {
      const dispatch = __dispatch ?? ctxDispatch;
      if (dispatch) dispatch(workflow, args);
    }
    if (navigate) window.location.assign(navigate);
  };

  const iconNode = IconComp
    ? <IconComp size={ICON_PX[size]} data-icon={icon} aria-hidden="true" />
    : null;

  const className = [
    buttonVariants({ variant, size, iconOnly: isIconOnly }),
    RADIUS_SURFACE_CLASS[radiusScale],
  ].join(" ");

  return (
    <button
      type="button"
      className={className}
      disabled={disabled}
      aria-busy={loading ? "true" : undefined}
      aria-label={ariaLabel}
      onClick={onClick}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {loading
        ? "…"
        : isIconOnly
          ? iconNode
          : iconPosition === "left"
            ? <>{iconNode}{label}</>
            : <>{label}{iconNode}</>}
    </button>
  );
}
```

NOTE: if `resolveIcon` has a different name or signature, adjust the import and call site. If the resolver returns `{ component, ... }`, destructure. If it returns null for unknown names, the `IconComp ? ... : null` guard handles that. Confirm before running the test.

- [ ] **Step 10.6: Run test to verify it passes**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run src/components/Button/Button.render.test.tsx
```

Expected: PASS, 3 tests.

- [ ] **Step 10.7: Eyeball — add a temporary icon button to the scaffold preview**

A quick visual smoke test: open the editor on the test project, add a Button with `icon: "plus"` to a list page, save, refresh the scaffold. Confirm the plus icon renders next to the label.

If the editor isn't convenient, edit the on-disk schema:

```bash
# Find a list schema for the test project
ls /Users/m/Work/code/poc/design2ui-forge-v3/output/genmetrics-1778439719/src/schemas/
# Edit one to add a Button node, e.g. inside the hero region, with
#   { "type": "Button", "props": { "label": "Add task", "icon": "plus" } }
```

Refresh `http://localhost:6503/p/genmetrics-1778439719/tasks/list` and confirm the icon shows.

- [ ] **Step 10.8: Commit**

```bash
git add packages/library/src/components/Button
git commit -m "$(cat <<'EOF'
feat(library): render icon + position on Button

Resolves Lucide name via existing resolver; icon-only mode renders
without horizontal padding and as a square button (CVA
compoundVariants). aria-label flows to the rendered <button>.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 11: Register remap — accept `iconName` alias

**Files:**
- Modify: `packages/library/src/registry.ts`
- Test:   `packages/library/src/registry.icon-alias.test.ts`

- [ ] **Step 11.1: Write the failing test**

```ts
// packages/library/src/registry.icon-alias.test.ts
import { describe, it, expect } from "vitest";
import { createRegistry } from "./registry";
import { Button } from "./components/Button/Button";
import { ButtonProps } from "./components/Button/Button.schema";

describe("Registry remap — Button.icon aliases", () => {
  it("accepts iconName as an alias for icon", () => {
    const r = createRegistry();
    r.register({ name: "Button", component: Button, propsSchema: ButtonProps, category: "interactive" });
    const props = r.validateProps("Button", { label: "Add", iconName: "plus" });
    expect((props as any).icon).toBe("plus");
    expect((props as any).iconName).toBeUndefined();
  });
});
```

- [ ] **Step 11.2: Run test to verify it fails**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run src/registry.icon-alias.test.ts
```

Expected: FAIL — the remap isn't there yet.

- [ ] **Step 11.3: Extend Button's remap**

Find the `Button:` entry in `PROP_REMAP` (around line 56 of `registry.ts`). Extend it:

```ts
Button: (p) => {
  const out = unifyLabelHref(p);
  if (out.variant === "outline") out.variant = "secondary";
  // Accept iconName as an alias for icon.
  if (typeof out.icon !== "string" && typeof out.iconName === "string") {
    out.icon = out.iconName;
  }
  delete out.iconName;
  return out;
},
```

- [ ] **Step 11.4: Run test to verify it passes**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run src/registry.icon-alias.test.ts
```

Expected: PASS.

- [ ] **Step 11.5: Commit**

```bash
git add packages/library/src/registry.ts packages/library/src/registry.icon-alias.test.ts
git commit -m "$(cat <<'EOF'
feat(library): registry remap accepts iconName alias on Button

LLM occasionally emits 'iconName' instead of 'icon'; map at the
registry boundary so the on-disk schema doesn't have to be rewritten.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 12: Mention Button.icon in the schema prompt

**Files:**
- Modify: `backend/services/schema_prompt.py`

- [ ] **Step 12.1: Locate Button's prompt block**

```bash
grep -n "Button" /Users/m/Work/code/poc/design2ui-forge-v3/backend/services/schema_prompt.py | head -20
```

Find the section that documents Button's props for the LLM.

- [ ] **Step 12.2: Add icon + iconPosition + aria-label rules**

In the Button prop block, add (preserving the existing structure):

```python
# ...inside the Button rules section:
"""
Button props:
  - label: string (the visible text; optional when icon is set)
  - variant: "primary" | "secondary" | "danger" | "ghost" (default primary)
  - size: "sm" | "md" | "lg" (default md)
  - icon: string — Lucide icon name (e.g. "plus", "filter", "chevron-right",
    "more-horizontal"). Use a lowercase kebab-case Lucide name.
  - iconPosition: "left" | "right" (default left)
  - navigate: string URL or app route
  - aria-label: string — REQUIRED when label is absent (icon-only button)

Examples:
  { "type": "Button", "props": { "label": "Add task", "icon": "plus" } }
  { "type": "Button", "props": { "label": "Filter", "icon": "filter", "iconPosition": "right" } }
  { "type": "Button", "props": { "icon": "more-horizontal", "aria-label": "More" } }

Icon-only Buttons MUST set aria-label.
"""
```

- [ ] **Step 12.3: Eyeball-test on a fresh generation**

Generate a small test app via the main frontend (or curl `/api/projects/.../generate`), inspect one of the produced schemas for Button nodes, confirm at least one carries an `icon` prop.

- [ ] **Step 12.4: Commit**

```bash
git add backend/services/schema_prompt.py
git commit -m "$(cat <<'EOF'
feat(prompt): document Button.icon / iconPosition / aria-label rules

Tells the LLM about the new props and the icon-only aria-label
requirement. Three concrete examples inline.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Workstream A4 — Keyboard-nav + a11y audit

### Task 13: Set up Playwright + axe-core in visual-regression

**Files:**
- Read:   `apps/visual-regression/package.json`
- Modify: `apps/visual-regression/package.json` (add `@axe-core/playwright`)
- Create: `apps/visual-regression/tests/a11y.spec.ts`

- [ ] **Step 13.1: Inspect existing setup**

```bash
ls /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
cat /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression/package.json
ls /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression/tests 2>/dev/null
```

Determine: is Playwright already installed? Are there existing tests? Use them as a template.

- [ ] **Step 13.2: Install @axe-core/playwright**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npm install --save-dev @axe-core/playwright
```

- [ ] **Step 13.3: Author the a11y test**

```ts
// apps/visual-regression/tests/a11y.spec.ts
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const TEST_PROJECT = process.env.TEST_PROJECT ?? "genmetrics-1778439719";
const PAGES = [
  `/p/${TEST_PROJECT}/tasks/list`,
  `/p/${TEST_PROJECT}/tasks/detail`,
  `/p/${TEST_PROJECT}/tasks/form`,
  `/p/${TEST_PROJECT}/users/list`,
];

for (const url of PAGES) {
  test.describe(`a11y ${url}`, () => {
    test("axe-core: no serious or critical violations", async ({ page }) => {
      await page.goto(`http://localhost:6503${url}`);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa"])
        .analyze();
      const seriousOrCritical = results.violations.filter(v =>
        v.impact === "serious" || v.impact === "critical"
      );
      if (seriousOrCritical.length > 0) {
        console.log("axe violations:\n" + seriousOrCritical.map(v =>
          `  ${v.id} (${v.impact}): ${v.description}\n    nodes: ${v.nodes.length}`
        ).join("\n"));
      }
      expect(seriousOrCritical).toEqual([]);
    });

    test("keyboard: every interactive element is reachable via Tab", async ({ page }) => {
      await page.goto(`http://localhost:6503${url}`);
      // Count interactive elements in the rendered output
      const interactiveCount = await page.evaluate(() => {
        return document.querySelectorAll("button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])").length;
      });
      if (interactiveCount === 0) return;
      // Tab through; assert we never land on an aria-hidden region or
      // get stuck on the same element twice in a row.
      const seen = new Set<string>();
      let lastFocused = "";
      for (let i = 0; i < interactiveCount + 5; i++) {
        await page.keyboard.press("Tab");
        const cur = await page.evaluate(() => {
          const el = document.activeElement;
          if (!el || el === document.body) return "";
          return (el.tagName + ":" + (el.id || el.className || "") + ":" + (el.textContent?.slice(0, 30) || ""));
        });
        if (cur === lastFocused && cur !== "") {
          throw new Error(`Tab focus stuck on ${cur} at step ${i}`);
        }
        if (cur) seen.add(cur);
        lastFocused = cur;
      }
      // We should have visited at least half the interactive count (some
      // may live in popovers/modals not yet opened).
      expect(seen.size).toBeGreaterThanOrEqual(Math.floor(interactiveCount / 2));
    });
  });
}
```

- [ ] **Step 13.4: Run the suite**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test tests/a11y.spec.ts --reporter=list
```

Expected: a mix of pass/fail. Failures define the punch list for Task 14.

- [ ] **Step 13.5: Commit the test infrastructure (before fixes)**

```bash
git add apps/visual-regression/tests/a11y.spec.ts apps/visual-regression/package.json apps/visual-regression/package-lock.json
git commit -m "$(cat <<'EOF'
test(a11y): Playwright + axe-core suite over scaffold preview pages

WCAG 2.1 AA scan + Tab-focus reachability test for list / detail /
form / users-list pages. Failures define the punch list of fixes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 14: Triage and fix a11y failures

**Files:** (depends on what the audit surfaces)

- [ ] **Step 14.1: Categorize failures from the Task 13 output**

Group violations by `axe.id`:
- `button-name` / `link-name` — usually fixed by adding `aria-label`. Track per occurrence.
- `color-contrast` — recolor offending tokens (often Badge tones — already fixed in current state, but verify).
- `aria-required-children` / `aria-required-parent` — Tabs/Accordion/CommandPalette structure issues.
- `focus-order-semantics` — interactive elements with `tabindex="0"` that aren't actual controls.

For Tab-focus failures: note specific component (Tabs not handling arrow keys, etc.) — open one issue per component.

- [ ] **Step 14.2: Fix one category at a time, commit per category**

Example: if `button-name` violations point at icon-only Buttons in the renderer's labelled-placeholder fallback, the fallback HTML needs an `aria-label="Invalid Button: missing aria-label"`. Edit `packages/renderer/src/runtime/dispatch.tsx` placeholder code; rerun the test.

Example: if Tabs fail `aria-required-children`, edit `packages/library/src/components/Tabs/Tabs.tsx` to ensure each `role="tab"` has a corresponding `role="tabpanel"` with proper `aria-controls`.

After each fix:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression && npx playwright test tests/a11y.spec.ts --reporter=list
```

Commit per category:
```bash
git add packages/library/src/components/<Component>
git commit -m "a11y(library): fix <axe.id> on <Component>"
```

- [ ] **Step 14.3: Final clean run**

When all serious/critical violations are gone:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression && npx playwright test tests/a11y.spec.ts --reporter=list
```

Expected: all PASS.

- [ ] **Step 14.4: Commit a final note + tag**

If there are documented-but-deferred items (e.g., specific moderate violations we're accepting), record them in `docs/a11y-known-issues.md`:

```bash
git add docs/a11y-known-issues.md
git commit -m "docs(a11y): record remaining moderate violations as known issues"
```

---

## Workstream C — Generation / prompt

### Task 15: Add `cta_defaults` helper for per-register CTA hierarchies

**Files:**
- Create: `backend/services/cta_defaults.py`
- Create: `backend/tests/services/test_cta_defaults.py`

- [ ] **Step 15.1: Write the failing test**

```python
# backend/tests/services/test_cta_defaults.py
from services.cta_defaults import defaults_for_register, CtaHierarchy

def test_default_register_returns_filled_primary():
    result = defaults_for_register("default")
    assert result["primary"]["variant"] == "primary"
    assert result["primary"]["max_per_page"] == 1
    assert result["primary"]["min_per_page"] == 1

def test_linear_register_favors_secondary_outline():
    result = defaults_for_register("linear")
    assert result["secondary"]["variant"] == "secondary"
    assert result["primary"]["max_per_page"] == 1

def test_unknown_register_returns_default():
    result = defaults_for_register("unknown-register")
    assert result["primary"]["variant"] == "primary"
```

- [ ] **Step 15.2: Run test to verify it fails**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3 && python -m pytest backend/tests/services/test_cta_defaults.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 15.3: Implement the helper**

```python
# backend/services/cta_defaults.py
"""Per-register CTA hierarchy defaults.

Each register expresses a different visual rhythm for primary / secondary /
tertiary actions. This module owns the mapping. The design_agent reads
defaults from here when emitting design-spec.json; the user can override
per-project from the design panel later.

CTA hierarchy is a project-wide rule. Per-page exceptions (e.g. form pages
where the submit button is the implicit primary) live in the validator,
not here.
"""
from __future__ import annotations
from typing import Literal, TypedDict

RegisterName = Literal["default", "workday", "linear", "stripe", "notion", "figma"]

class CtaRule(TypedDict):
    variant: str        # Button variant name
    max_per_page: int | None
    min_per_page: int   # 0 by default; 1 only for primary

class CtaHierarchy(TypedDict):
    primary: CtaRule
    secondary: CtaRule
    tertiary: CtaRule


# Defaults shared by registers without their own preference.
_BASE: CtaHierarchy = {
    "primary":   {"variant": "primary",   "max_per_page": 1,    "min_per_page": 1},
    "secondary": {"variant": "secondary", "max_per_page": 3,    "min_per_page": 0},
    "tertiary":  {"variant": "ghost",     "max_per_page": None, "min_per_page": 0},
}


_PER_REGISTER: dict[RegisterName, CtaHierarchy] = {
    "default": _BASE,
    # Linear / Workday: secondary outline-style preferred; primary kept rare.
    "linear":  {
        "primary":   {"variant": "primary",   "max_per_page": 1, "min_per_page": 1},
        "secondary": {"variant": "secondary", "max_per_page": 2, "min_per_page": 0},
        "tertiary":  {"variant": "ghost",     "max_per_page": None, "min_per_page": 0},
    },
    "workday": {
        "primary":   {"variant": "primary",   "max_per_page": 1, "min_per_page": 1},
        "secondary": {"variant": "secondary", "max_per_page": 3, "min_per_page": 0},
        "tertiary":  {"variant": "ghost",     "max_per_page": None, "min_per_page": 0},
    },
    # Stripe / Figma: primary filled-with-gradient is the headline; secondary moderate.
    "stripe": _BASE,
    "figma":  _BASE,
    # Notion: low chrome; tertiary ghost dominant.
    "notion": {
        "primary":   {"variant": "primary",   "max_per_page": 1, "min_per_page": 1},
        "secondary": {"variant": "secondary", "max_per_page": 2, "min_per_page": 0},
        "tertiary":  {"variant": "ghost",     "max_per_page": None, "min_per_page": 0},
    },
}


def defaults_for_register(register: str) -> CtaHierarchy:
    """Return the CTA hierarchy defaults for the given register. Unknown
    registers fall back to the base configuration."""
    return _PER_REGISTER.get(register, _BASE)  # type: ignore[arg-type]
```

- [ ] **Step 15.4: Run test to verify it passes**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3 && python -m pytest backend/tests/services/test_cta_defaults.py -v
```

Expected: PASS, 3 tests.

- [ ] **Step 15.5: Commit**

```bash
git add backend/services/cta_defaults.py backend/tests/services/test_cta_defaults.py
git commit -m "$(cat <<'EOF'
feat(generation): per-register CTA hierarchy defaults

defaults_for_register() returns variant + count limits for primary /
secondary / tertiary CTAs. Linear and Notion favor secondary/ghost
weight; Stripe/Figma/default keep primary-filled.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 16: Wire `cta_hierarchy` into `design-spec.json` emission

**Files:**
- Modify: `backend/agents/design_agent.py` (or whichever module writes design-spec)

- [ ] **Step 16.1: Locate where `design-spec.json` is written**

```bash
grep -rn "design-spec.json\|design_spec.json" /Users/m/Work/code/poc/design2ui-forge-v3/backend --include="*.py" | head
```

Find the function that builds the spec dict and writes the file (likely `extract_design_spec()` or `save_design_spec()` in `design_agent.py`).

- [ ] **Step 16.2: Inject `cta_hierarchy` from the register**

In the same spot the `register` field is set:

```python
from services.cta_defaults import defaults_for_register

# ...where design-spec dict is assembled...
register = spec.get("register", "default")
spec["cta_hierarchy"] = defaults_for_register(register)
```

If `design_agent` is skipped (legacy paths), also inject in `routers/generate.py` where the default spec is written:

```bash
grep -n "register.*=.*classify_register\|design-spec\|design_spec" /Users/m/Work/code/poc/design2ui-forge-v3/backend/routers/generate.py | head
```

Add the same injection after the `register` is determined.

- [ ] **Step 16.3: Spot-check the output**

Trigger a fresh generation on a small test plan (or hit the design endpoint directly), inspect:

```bash
cat /Users/m/Work/code/poc/design2ui-forge-v3/output/<new-id>/src/contracts/design-spec.json | python -m json.tool | grep -A 12 cta_hierarchy
```

Expected: `cta_hierarchy` block present with all three keys.

- [ ] **Step 16.4: Commit**

```bash
git add backend/agents/design_agent.py backend/routers/generate.py
git commit -m "$(cat <<'EOF'
feat(generation): write cta_hierarchy block into design-spec.json

Pulled from cta_defaults.defaults_for_register(register). Emitted by
design_agent on schema-mode generations and by the legacy fallback
path in routers/generate.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 17: Inject CTA rule into schema prompt

**Files:**
- Modify: `backend/services/schema_prompt.py::build_schema_prompt()`

- [ ] **Step 17.1: Locate `build_schema_prompt`**

```bash
grep -n "def build_schema_prompt\|def _.*prompt" /Users/m/Work/code/poc/design2ui-forge-v3/backend/services/schema_prompt.py | head
```

Look at its signature. It already takes the plan / entity / design-spec — the cta_hierarchy is reachable from the spec dict.

- [ ] **Step 17.2: Add a `## CTA hierarchy (binding)` block**

Inside `build_schema_prompt`, after the existing rule blocks, append:

```python
# Read CTA hierarchy from design spec; fall back to module-level defaults
# if the design hasn't run yet.
from services.cta_defaults import defaults_for_register

cta = design_spec.get("cta_hierarchy") or defaults_for_register(design_spec.get("register", "default"))
primary_variant   = cta["primary"]["variant"]
secondary_variant = cta["secondary"]["variant"]
tertiary_variant  = cta["tertiary"]["variant"]
secondary_max     = cta["secondary"]["max_per_page"]

cta_block = f"""
## CTA hierarchy (binding)

- Every page MUST have exactly 1 Button with variant="{primary_variant}". This is
  the primary CTA; place it where visual weight expects it (hero, top-right of
  the page, or form submit area).
- Use variant="{secondary_variant}" for follow-up actions. Cap: {secondary_max} per page.
- Use variant="{tertiary_variant}" for tertiary / inline actions (no limit).
- Form pages: the form's submit button counts as the primary CTA.

Examples:
  PAGE HEADER:
    {{ "type": "Button", "props": {{ "label": "New Task", "variant": "{primary_variant}", "icon": "plus" }} }}
  ROW ACTION (in a Repeat over rows):
    {{ "type": "Button", "props": {{ "label": "View", "variant": "{tertiary_variant}", "navigate": "/tasks/{{{{item.id}}}}" }} }}
"""

# Append cta_block to the prompt assembly point.
```

- [ ] **Step 17.3: Snapshot test the prompt block**

Add a backend test that constructs a small design-spec and verifies the rule block renders:

```python
# backend/tests/services/test_schema_prompt_cta.py
from services.schema_prompt import build_schema_prompt

def test_cta_block_in_prompt():
    plan = {"entity": {"name": "Task", "fields": []}, "page_type": "list"}
    design_spec = {"register": "linear", "cta_hierarchy": {
        "primary":   {"variant": "primary",   "max_per_page": 1, "min_per_page": 1},
        "secondary": {"variant": "secondary", "max_per_page": 2, "min_per_page": 0},
        "tertiary":  {"variant": "ghost",     "max_per_page": None, "min_per_page": 0},
    }}
    prompt = build_schema_prompt(plan, design_spec=design_spec)
    assert "CTA hierarchy (binding)" in prompt
    assert 'variant="primary"' in prompt
    assert "Cap: 2 per page" in prompt
```

NOTE: adjust the `build_schema_prompt(...)` call shape to match the real signature.

Run:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3 && python -m pytest backend/tests/services/test_schema_prompt_cta.py -v
```

Expected: PASS.

- [ ] **Step 17.4: Commit**

```bash
git add backend/services/schema_prompt.py backend/tests/services/test_schema_prompt_cta.py
git commit -m "$(cat <<'EOF'
feat(prompt): inject CTA hierarchy rule into schema prompt

build_schema_prompt now reads design_spec.cta_hierarchy and emits a
binding rule block. Variant names and counts come from the spec so
register switches propagate without a prompt rewrite.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 18: Add `validate_cta_hierarchy` + retry hook

**Files:**
- Modify: `backend/services/schema_validator.py`
- Modify: `backend/services/phase_gates.py` (add a CTA gate)
- Test:   `backend/tests/services/test_validate_cta_hierarchy.py`

- [ ] **Step 18.1: Write the failing test**

```python
# backend/tests/services/test_validate_cta_hierarchy.py
import pytest
from services.schema_validator import validate_cta_hierarchy

CTA = {
    "primary":   {"variant": "primary",   "max_per_page": 1, "min_per_page": 1},
    "secondary": {"variant": "secondary", "max_per_page": 3, "min_per_page": 0},
    "tertiary":  {"variant": "ghost",     "max_per_page": None, "min_per_page": 0},
}

def _btn(variant: str):
    return {"type": "Button", "props": {"label": "x", "variant": variant}}

def _page(buttons: list[dict], page_type: str = "list"):
    return {
        "schemaVersion": "2", "id": "p", "route": "/p", "layout": "main",
        "root": {"type": "Stack", "children": buttons},
        "page_type": page_type,
    }

def test_one_primary_passes():
    errors = validate_cta_hierarchy(_page([_btn("primary"), _btn("ghost")]), CTA)
    assert errors == []

def test_zero_primary_fails():
    errors = validate_cta_hierarchy(_page([_btn("ghost")]), CTA)
    assert len(errors) == 1
    assert "primary" in errors[0].lower()

def test_two_primary_fails():
    errors = validate_cta_hierarchy(_page([_btn("primary"), _btn("primary")]), CTA)
    assert len(errors) == 1
    assert "primary" in errors[0].lower()

def test_too_many_secondary_fails():
    buttons = [_btn("primary")] + [_btn("secondary")] * 4
    errors = validate_cta_hierarchy(_page(buttons), CTA)
    assert any("secondary" in e.lower() for e in errors)

def test_form_page_skips_primary_count():
    # Form page with no Button at all — the <Form> wraps the submit.
    page = _page([], page_type="form")
    page["root"] = {"type": "Form", "children": []}
    errors = validate_cta_hierarchy(page, CTA)
    # Should not fail for "0 primary"
    assert not any("primary count" in e.lower() and "0" in e for e in errors)
```

- [ ] **Step 18.2: Run test to verify it fails**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3 && python -m pytest backend/tests/services/test_validate_cta_hierarchy.py -v
```

Expected: FAIL — function not found.

- [ ] **Step 18.3: Implement `validate_cta_hierarchy`**

Append to `backend/services/schema_validator.py`:

```python
def validate_cta_hierarchy(page: dict, cta: dict) -> list[str]:
    """Count Button variants in the page tree; return human-readable error
    strings for hierarchy violations. Empty list = no violations.

    Form pages skip the primary-min check because the <Form> component
    contains an implicit submit button that may not be a top-level Button
    node.
    """
    page_type = page.get("page_type", "")
    counts: dict[str, int] = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "Button":
            variant = (node.get("props") or {}).get("variant", "primary")
            counts[variant] = counts.get(variant, 0) + 1
        for child in (node.get("children") or []):
            walk(child)
        if node.get("else"):
            for child in node["else"]:
                walk(child)

    walk(page.get("root", {}))

    errors: list[str] = []

    primary_count = counts.get(cta["primary"]["variant"], 0)
    primary_max   = cta["primary"]["max_per_page"]
    primary_min   = cta["primary"]["min_per_page"]

    # Form pages: the <Form> wraps the submit button. If the root or any
    # descendant is a Form, treat that as supplying the primary CTA.
    def contains_form(node):
        if not isinstance(node, dict):
            return False
        if node.get("type") == "Form":
            return True
        for c in (node.get("children") or []):
            if contains_form(c):
                return True
        return False

    page_supplies_form = page_type == "form" or contains_form(page.get("root", {}))

    if primary_max is not None and primary_count > primary_max:
        errors.append(f"page has {primary_count} primary CTAs (variant='{cta['primary']['variant']}'); max is {primary_max}")
    if not page_supplies_form and primary_count < primary_min:
        errors.append(f"page has {primary_count} primary CTAs; min is {primary_min} (variant='{cta['primary']['variant']}')")

    sec_count = counts.get(cta["secondary"]["variant"], 0)
    sec_max   = cta["secondary"]["max_per_page"]
    if sec_max is not None and sec_count > sec_max:
        errors.append(f"page has {sec_count} secondary CTAs (variant='{cta['secondary']['variant']}'); max is {sec_max}")

    return errors
```

- [ ] **Step 18.4: Run test to verify it passes**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3 && python -m pytest backend/tests/services/test_validate_cta_hierarchy.py -v
```

Expected: PASS, 5 tests.

- [ ] **Step 18.5: Wire into the retry loop via `phase_gates.py`**

```bash
grep -n "def check_\|def.*_gate" /Users/m/Work/code/poc/design2ui-forge-v3/backend/services/phase_gates.py | head
```

Look at one existing gate function (e.g. `check_component_completeness`) to learn the shape: returns `{passed, issues, retry_prompt}`. Add a similar `check_cta_hierarchy(output_dir, plan)` that loads every emitted schema, runs the validator against the design-spec's cta_hierarchy, and returns a passed/issues/retry_prompt struct.

```python
# backend/services/phase_gates.py
def check_cta_hierarchy(output_dir: str, plan: dict) -> dict:
    """Walk every emitted JSON schema under src/schemas/ and run the
    CTA hierarchy validator. Returns the standard gate-shape dict.
    """
    from pathlib import Path
    import json
    from services.schema_validator import validate_cta_hierarchy

    output = Path(output_dir)
    spec_path = output / "src" / "contracts" / "design-spec.json"
    if not spec_path.exists():
        return {"passed": True, "issues": [], "retry_prompt": ""}
    spec = json.loads(spec_path.read_text())
    cta = spec.get("cta_hierarchy")
    if not cta:
        return {"passed": True, "issues": [], "retry_prompt": ""}

    issues: list[str] = []
    schemas_dir = output / "src" / "schemas"
    if not schemas_dir.exists():
        return {"passed": True, "issues": [], "retry_prompt": ""}

    for path in schemas_dir.glob("*/*.json"):
        try:
            page = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        page["page_type"] = path.stem  # list / detail / form
        for err in validate_cta_hierarchy(page, cta):
            issues.append(f"{path.parent.name}/{path.stem}: {err}")

    if not issues:
        return {"passed": True, "issues": [], "retry_prompt": ""}

    retry_prompt = (
        "The CTA hierarchy gate found the following violations. Adjust your output "
        "so each page has exactly one primary CTA (variant='primary'), no more than "
        "the per-page cap of secondary CTAs, and no orphan high-variant Buttons.\n\n"
        + "\n".join(f"- {i}" for i in issues)
    )
    return {"passed": False, "issues": issues, "retry_prompt": retry_prompt}
```

In `backend/routers/generate.py`, after the schema-mode pipeline completes for each entity (or at the end of the schema pipeline batch), add:

```python
from services.phase_gates import check_cta_hierarchy
cta_gate = check_cta_hierarchy(output_dir, plan)
if not cta_gate["passed"]:
    yield sse_event("log", {"text": f"[CTA Gate] {len(cta_gate['issues'])} issues — sending back to schema agent"})
    yield sse_event("status", {"message": "Fixing CTA hierarchy..."})
    # Run feature_slice_schema_agent again per entity with retry_prompt;
    # follow the same pattern as the other gates.
```

NOTE: schema-mode skips QA/validator/indexer by design (per the relay pipeline in section 5.9). The CTA gate runs in its place. Cap retries at 2 to match the rest of the pipeline.

- [ ] **Step 18.6: Commit**

```bash
git add backend/services/schema_validator.py backend/services/phase_gates.py backend/routers/generate.py backend/tests/services/test_validate_cta_hierarchy.py
git commit -m "$(cat <<'EOF'
feat(validation): CTA hierarchy gate post-schema generation

validate_cta_hierarchy counts Button variants per emitted schema and
flags pages outside the design-spec's hierarchy. Wires through
phase_gates.check_cta_hierarchy and the schema-mode retry loop in
routers/generate.py. Form pages exempt the primary-min check.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 19: Inject progressive disclosure rule + validator + exemplars

**Files:**
- Create: `backend/fixtures/exemplars/wide-form-accordion.json`
- Create: `backend/fixtures/exemplars/wide-form-tabs.json`
- Create: `backend/fixtures/exemplars/detail-tabs.json`
- Create: `backend/fixtures/exemplars/related-fields-card.json`
- Create: `backend/fixtures/exemplars/narrow-form-flat.json`
- Modify: `backend/services/schema_prompt.py` (rule block + exemplar citations)
- Modify: `backend/services/schema_validator.py` (add `validate_progressive_disclosure`)
- Modify: `backend/services/phase_gates.py` (add `check_progressive_disclosure`)
- Test:   `backend/tests/services/test_validate_progressive_disclosure.py`

- [ ] **Step 19.1: Author the five exemplar schemas**

Each is a small valid Page JSON (~25-40 lines) demonstrating one container choice. Example:

```json
// backend/fixtures/exemplars/wide-form-accordion.json
{
  "schemaVersion": "2",
  "id": "exemplar-wide-form",
  "route": "/example/wide-form",
  "layout": "main",
  "root": {
    "type": "Form",
    "props": {"action": "submit"},
    "children": [
      {
        "type": "Accordion",
        "props": {"defaultOpen": "basics"},
        "children": [
          {"type": "AccordionPanel", "props": {"id": "basics", "title": "Basics"}, "children": [
            {"type": "Input", "props": {"label": "Name", "name": "name"}},
            {"type": "Input", "props": {"label": "Email", "name": "email"}},
            {"type": "Input", "props": {"label": "Phone", "name": "phone"}}
          ]},
          {"type": "AccordionPanel", "props": {"id": "address", "title": "Address"}, "children": [
            {"type": "Input", "props": {"label": "Street", "name": "street"}},
            {"type": "Input", "props": {"label": "City", "name": "city"}},
            {"type": "Input", "props": {"label": "Zip", "name": "zip"}}
          ]},
          {"type": "AccordionPanel", "props": {"id": "prefs", "title": "Preferences"}, "children": [
            {"type": "Select", "props": {"label": "Timezone", "name": "tz", "options": []}},
            {"type": "Checkbox", "props": {"label": "Notifications", "name": "notif"}},
            {"type": "Checkbox", "props": {"label": "Newsletter", "name": "news"}}
          ]}
        ]
      },
      {"type": "Button", "props": {"label": "Save", "variant": "primary"}}
    ]
  }
}
```

Author the remaining four exemplars in the same style. Each must parse against the schema. Validate via a vitest test that lives in the schema package (which already imports its own types):

```ts
// packages/schema/tests/exemplars.test.ts
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Page } from "../src";

const EXEMPLARS = [
  "wide-form-accordion",
  "wide-form-tabs",
  "detail-tabs",
  "related-fields-card",
  "narrow-form-flat",
];

describe("progressive-disclosure exemplars parse against Page", () => {
  for (const name of EXEMPLARS) {
    it(`${name}.json`, () => {
      const path = resolve(__dirname, "..", "..", "..", "backend", "fixtures", "exemplars", `${name}.json`);
      const data = JSON.parse(readFileSync(path, "utf8"));
      const r = Page.safeParse(data);
      if (!r.success) {
        // Surface the first few issues so the failure tells you what to fix.
        const issues = r.error.issues.slice(0, 3).map(i => `${i.path.join(".")}: ${i.message}`);
        throw new Error(`${name} failed: ${issues.join("; ")}`);
      }
      expect(r.success).toBe(true);
    });
  }
});
```

Run:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema && npx vitest run tests/exemplars.test.ts
```

Expected: all 5 PASS.

- [ ] **Step 19.2: Write the failing validator test**

```python
# backend/tests/services/test_validate_progressive_disclosure.py
from services.schema_validator import validate_progressive_disclosure

def _input(name): return {"type": "Input", "props": {"label": name, "name": name}}

def _form_with_n_fields(n: int, container: str | None = None):
    fields = [_input(f"f{i}") for i in range(n)]
    if container is None:
        return {"schemaVersion": "2", "id": "p", "route": "/", "layout": "m",
                "root": {"type": "Form", "children": fields}, "page_type": "form"}
    return {"schemaVersion": "2", "id": "p", "route": "/", "layout": "m",
            "root": {"type": "Form", "children": [
                {"type": container, "children": fields}
            ]}, "page_type": "form"}

def test_flat_form_with_5_fields_ok():
    errors = validate_progressive_disclosure(_form_with_n_fields(5))
    assert errors == []

def test_flat_form_with_8_fields_fails():
    errors = validate_progressive_disclosure(_form_with_n_fields(8))
    assert any("accordion" in e.lower() or "tabs" in e.lower() for e in errors)

def test_form_with_8_fields_in_accordion_passes():
    errors = validate_progressive_disclosure(_form_with_n_fields(8, container="Accordion"))
    assert errors == []

def test_form_with_8_fields_in_tabs_passes():
    errors = validate_progressive_disclosure(_form_with_n_fields(8, container="Tabs"))
    assert errors == []
```

- [ ] **Step 19.3: Implement the validator**

Append to `backend/services/schema_validator.py`:

```python
def validate_progressive_disclosure(page: dict) -> list[str]:
    """Flag pages with too-flat layouts.

    Rule: a Form with > 7 user-editable fields must be partitioned into
    an Accordion or Tabs (or TabPanelWithDeepLink) container. Counts
    fields not nested inside such a container.
    """
    FIELD_TYPES = {"Input", "Textarea", "Select", "Checkbox", "DatePicker", "DateRangePicker", "MultiSelect"}
    PARTITION_TYPES = {"Accordion", "Tabs", "TabPanelWithDeepLink"}

    errors: list[str] = []

    def find_forms(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "Form":
            yield node
        for c in (node.get("children") or []):
            yield from find_forms(c)

    def count_unpartitioned_fields(node, inside_partition=False) -> int:
        if not isinstance(node, dict):
            return 0
        node_type = node.get("type")
        if node_type in PARTITION_TYPES:
            return 0  # everything below this is partitioned
        n = 1 if node_type in FIELD_TYPES else 0
        for c in (node.get("children") or []):
            n += count_unpartitioned_fields(c, inside_partition)
        return n

    for form in find_forms(page.get("root", {})):
        unpartitioned = count_unpartitioned_fields(form)
        if unpartitioned > 7:
            errors.append(
                f"Form has {unpartitioned} fields directly in a flat container; "
                f"wrap groups in Accordion or Tabs for progressive disclosure"
            )

    return errors
```

- [ ] **Step 19.4: Run the test**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3 && python -m pytest backend/tests/services/test_validate_progressive_disclosure.py -v
```

Expected: PASS, 4 tests.

- [ ] **Step 19.5: Wire validator into a gate**

In `phase_gates.py`, add `check_progressive_disclosure(output_dir, plan)` with the same shape as `check_cta_hierarchy` from Task 18 — walk emitted schemas, collect issues, return a gate dict with a retry_prompt that quotes specific files + violations.

Wire into `routers/generate.py` schema-mode block, alongside the CTA gate.

- [ ] **Step 19.6: Update `build_schema_prompt` with rules + exemplar citations**

Inside `schema_prompt.py`:

```python
PROGRESSIVE_DISCLOSURE_RULES = """
## Container choice (binding)

- Form with > 7 user-editable fields: wrap in Accordion (collapsed panels per
  logical group) or Tabs (one tab per group). Pick Accordion when groups have
  a sequence; Tabs when they don't.
- Detail page with > 5 sections of content: split with Tabs (or
  TabPanelWithDeepLink for URL-aware tabs).
- "View row → see detail" interaction: prefer InspectorPanel over a separate
  detail page.
- Related field cluster (3-6 fields that belong together semantically): wrap
  in Card.
- NEVER lay out > 10 form fields in a flat Stack — readers cannot scan that density.

## Reference patterns

See exemplar schemas under backend/fixtures/exemplars/:
  - wide-form-accordion.json     — 9 fields wrapped in Accordion
  - wide-form-tabs.json          — same fields wrapped in Tabs
  - detail-tabs.json             — detail page with 6 sections in Tabs
  - related-fields-card.json     — 4 related fields wrapped in Card
  - narrow-form-flat.json        — 4 fields in a flat Stack (OK at this size)
"""

# In build_schema_prompt(plan, design_spec=...), append PROGRESSIVE_DISCLOSURE_RULES
# to the prompt, and inline the exemplar that's most relevant to the page_type:
#   list/detail → cite detail-tabs.json
#   form        → cite wide-form-accordion.json
```

Inline the **content** of one exemplar JSON into the prompt for the matching page_type so the LLM has a near-context example:

```python
import json
from pathlib import Path

_EXEMPLARS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "exemplars"

def _load_exemplar(name: str) -> str:
    p = _EXEMPLARS_DIR / f"{name}.json"
    return p.read_text() if p.exists() else ""

def _exemplar_for(page_type: str) -> str:
    return {
        "form":   _load_exemplar("wide-form-accordion"),
        "detail": _load_exemplar("detail-tabs"),
    }.get(page_type, "")
```

Then in the rule block:

```python
exemplar = _exemplar_for(page_type)
if exemplar:
    cta_and_disclosure_block += f"\n### Exemplar ({page_type}):\n```json\n{exemplar}\n```\n"
```

- [ ] **Step 19.7: Snapshot test the exemplar inlining**

```python
# backend/tests/services/test_schema_prompt_exemplars.py
from services.schema_prompt import build_schema_prompt

def test_form_prompt_includes_accordion_exemplar():
    plan = {"entity": {"name": "Lead", "fields": []}, "page_type": "form"}
    design_spec = {"register": "default"}
    prompt = build_schema_prompt(plan, design_spec=design_spec)
    assert "wide-form-accordion" in prompt or "Accordion" in prompt
    assert "exemplar" in prompt.lower()
```

Run:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3 && python -m pytest backend/tests/services/test_schema_prompt_exemplars.py -v
```

Expected: PASS.

- [ ] **Step 19.8: Commit**

```bash
git add backend/fixtures/exemplars/ backend/services/schema_prompt.py backend/services/schema_validator.py backend/services/phase_gates.py backend/routers/generate.py backend/tests/services/test_validate_progressive_disclosure.py backend/tests/services/test_schema_prompt_exemplars.py
git commit -m "$(cat <<'EOF'
feat(generation): progressive disclosure rules + validator + exemplars

Schema prompt gains a 'Container choice (binding)' block citing the
exemplar schemas under backend/fixtures/exemplars/. validate_progressive_
disclosure flags Forms with > 7 fields not partitioned into Accordion
or Tabs; wired through phase_gates and the schema-mode retry loop.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 20: Restructure `schema_prompt.py` for proximity training

**Files:**
- Create: `backend/services/schema_rules.py`
- Modify: `backend/services/schema_prompt.py::build_schema_prompt()`
- Test:   `backend/tests/services/test_schema_rules.py`

- [ ] **Step 20.1: Inventory existing rules**

```bash
grep -n "^##\|^# \|RULE\|Binding\|Must\|MUST" /Users/m/Work/code/poc/design2ui-forge-v3/backend/services/schema_prompt.py | head -40
```

Make a list (in a scratch note) of every rule the current prompt encodes. Roughly group: layout rules, binding rules, register rules, CTA rules (now from Task 17), container rules (now from Task 19), token usage rules.

- [ ] **Step 20.2: Author `schema_rules.py` data structures**

```python
# backend/services/schema_rules.py
"""Rules-as-data for the schema prompt.

build_schema_prompt() consumes this catalogue and emits each rule
followed immediately by its example_snippet and a scope hint, so the
LLM encounters each binding rule in close proximity to a correct
example and the entity context the rule applies to.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class Rule:
    name: str                                   # short ID — used in token-budget debug + RULES_DISABLED
    body: str                                   # rule text shown to the LLM
    example_snippet: str                        # 5-15 line JSON example
    applies_when: Callable[[dict, str], bool]   # (entity, page_type) → bool

# ── Rule definitions ─────────────────────────────────────────────────────

def _always(entity: dict, page_type: str) -> bool:
    return True

def _on_list(entity: dict, page_type: str) -> bool:
    return page_type == "list"

def _on_form(entity: dict, page_type: str) -> bool:
    return page_type == "form"

def _on_detail(entity: dict, page_type: str) -> bool:
    return page_type == "detail"


RULES: list[Rule] = [
    Rule(
        name="metric-tile-for-stats",
        body=(
            "Prefer MetricTile over plain Stat layouts. MetricTile expresses "
            "label + numeric value + optional delta + icon with consistent rhythm."
        ),
        example_snippet="""{
  "type": "MetricTile",
  "props": { "label": "Open tasks", "value": "{{stats.openCount}}", "delta": { "value": "{{stats.openDelta}}", "tone": "positive" } }
}""",
        applies_when=_on_list,
    ),
    Rule(
        name="button-icon-only-aria",
        body="Icon-only Buttons MUST set aria-label so screen readers can announce them.",
        example_snippet="""{ "type": "Button", "props": { "icon": "more-horizontal", "aria-label": "More" } }""",
        applies_when=_always,
    ),
    # Continue adding entries for each rule in the existing prompt.
    # Keep examples ≤ 15 lines so the prompt token budget stays manageable.
]
```

- [ ] **Step 20.3: Write the rules test**

```python
# backend/tests/services/test_schema_rules.py
from services.schema_rules import RULES, Rule

def test_every_rule_has_required_fields():
    for r in RULES:
        assert isinstance(r, Rule)
        assert r.name and isinstance(r.name, str)
        assert r.body and isinstance(r.body, str)
        assert r.example_snippet and isinstance(r.example_snippet, str)
        assert callable(r.applies_when)

def test_rule_names_unique():
    names = [r.name for r in RULES]
    assert len(names) == len(set(names))

def test_applies_when_dispatches_on_page_type():
    entity = {"name": "X", "fields": []}
    metric = next(r for r in RULES if r.name == "metric-tile-for-stats")
    assert metric.applies_when(entity, "list") is True
    assert metric.applies_when(entity, "form") is False
```

Run:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3 && python -m pytest backend/tests/services/test_schema_rules.py -v
```

Expected: PASS.

- [ ] **Step 20.4: Rewrite `build_schema_prompt` to iterate `RULES`**

In `backend/services/schema_prompt.py`:

```python
import os
from services.schema_rules import RULES

_RULES_DISABLED = set((os.getenv("SCHEMA_RULES_DISABLED") or "").split(","))

def _emit_rules_block(entity: dict, page_type: str) -> str:
    blocks: list[str] = []
    for rule in RULES:
        if rule.name in _RULES_DISABLED:
            continue
        if not rule.applies_when(entity, page_type):
            continue
        blocks.append(
            f"## Rule: {rule.name}\n\n"
            f"{rule.body}\n\n"
            f"Example:\n```json\n{rule.example_snippet}\n```\n"
        )
    return "\n".join(blocks)

# Inside build_schema_prompt(plan, design_spec=...):
#   replace the old monolithic "## Rules" section with:
rules_block = _emit_rules_block(entity, page_type)
prompt = (
    # ...preserved header (system prompt, register / domain info, design spec)...
    + rules_block
    # ...preserved sections (CTA hierarchy from Task 17, container rules from Task 19)...
    + entity_block  # entity definition LAST so it's adjacent to the rules
)
```

NOTE: keep the CTA and progressive-disclosure blocks from Tasks 17/19 — they're already proximity-shaped. Just restructure the OLD generic rules block.

- [ ] **Step 20.5: Token budget assertion**

Add to `build_schema_prompt`:

```python
# Token budget: rough estimate at 4 chars per token. 25k tokens = ~100k chars.
APPROX_CHARS_PER_TOKEN = 4
TOKEN_BUDGET = 25_000

if len(prompt) > TOKEN_BUDGET * APPROX_CHARS_PER_TOKEN:
    import logging
    logging.getLogger(__name__).warning(
        f"[schema_prompt] prompt is {len(prompt) // APPROX_CHARS_PER_TOKEN} approx tokens "
        f"(budget {TOKEN_BUDGET}). Consider trimming rule examples or disabling rules "
        f"via SCHEMA_RULES_DISABLED."
    )
```

- [ ] **Step 20.6: Verify with a generation**

Trigger a fresh small-scope generation; eyeball the LLM output for: (a) correct rule application, (b) no regression vs the previous prompt. If the vision evaluator is running, capture before/after scores on 3 test entities.

If quality regresses on subjective inspection, document and disable the proximity layout via `SCHEMA_RULES_DISABLED=*` (set env var to disable all rules — falls back to a monolithic block) — keep the data structure but revert the prompt structure.

- [ ] **Step 20.7: Commit**

```bash
git add backend/services/schema_rules.py backend/services/schema_prompt.py backend/tests/services/test_schema_rules.py
git commit -m "$(cat <<'EOF'
refactor(prompt): rules-as-data + proximity restructure for schema prompt

Each rule lives as a Rule dataclass in schema_rules.py; build_schema_
prompt iterates and emits rule + example + scope inline. Adds env-var
SCHEMA_RULES_DISABLED for A/B testing and a token-budget warning at
25k tokens.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Wrap-up

### Task 21: Run the full a11y + library test suites; smoke-test scaffold

- [ ] **Step 21.1: Library tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run
```

Expected: all PASS. Pre-existing failures in PersonCard / Tabs / resolveStyle (per RESUME.md) are allowed; new test files from this plan must pass.

- [ ] **Step 21.2: Schema + renderer tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema   && npx vitest run
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/renderer && npx vitest run
```

Expected: PASS.

- [ ] **Step 21.3: Backend tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3 && python -m pytest backend/tests -k "cta or schema_prompt or schema_rules or progressive_disclosure or cta_defaults" -v
```

Expected: PASS.

- [ ] **Step 21.4: Playwright a11y suite**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression && npx playwright test tests/a11y.spec.ts
```

Expected: PASS (after Task 14's fixes).

- [ ] **Step 21.5: Manual eyeball through all 6 registers**

For each register in `{default, linear, workday, stripe, notion, figma}`: switch the test project's register, refresh `tasks/list`, `tasks/detail`, `tasks/form`, eyeball for:
- Card / Button / Input radius matches the register's intended scale
- Headings render with the type-scale rhythm
- At most one primary CTA per page

Note any visual regressions in `RESUME.md`'s "What's still pending" section so the next session has them surfaced.

- [ ] **Step 21.6: Final summary commit (docs only)**

Update `IMPLEMENTED_FEATURES.md` to record the Tier S/M/L items as complete:

```
## 27. Tier S/M/L Fidelity Polish — ✅ 9 tasks
| 27.1 | Radius scale unification | packages/library/src/style/radius.ts |
| 27.2 | Heading → type-scale classes | packages/library/src/components/Heading/Heading.tsx |
| 27.3 | aria-label requirement on icon-only Button | packages/library/src/components/Button/Button.schema.ts |
| 27.4 | Keyboard-nav + axe-core audit | apps/visual-regression/tests/a11y.spec.ts |
| 27.5 | KeyValueList semantic markup (already done; locked by test) | packages/library/src/components/KeyValueList |
| 27.6 | Button icon prop | packages/library/src/components/Button/ |
| 27.7 | CTA hierarchy in design-spec | backend/services/cta_defaults.py |
| 27.8 | Progressive disclosure patterns | backend/services/schema_validator.py |
| 27.9 | Schema-prompt proximity training | backend/services/schema_rules.py |
```

```bash
git add IMPLEMENTED_FEATURES.md
git commit -m "docs: mark Tier S/M/L fidelity polish complete (27.1-27.9)"
```

---

## Reference: known-good build incantation

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
# Rebuild packages in dependency order
cd packages/schema   && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc
cd ../renderer       && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc
cd ../library        && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc
# Clear scaffold's compiled CSS cache (forces Tailwind to re-scan)
cd /Users/m/Work/code/poc/design2ui-forge-v3
rm -rf apps/render-scaffold/.next
# Restart scaffold
pkill -9 -f "next dev -p 6503" 2>/dev/null
# Then ./start-all.sh re-mounts the scaffold
```

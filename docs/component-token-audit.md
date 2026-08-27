# Component Token Audit (2026-05-08)

Survey of how each library component consumes design tokens today, ranked by
refactor complexity for the upcoming Phase 2 token-system expansion.

## Consumption patterns observed

- **Tailwind-class** — 18 components: Accordion, Avatar, Badge, Button, Card, Checkbox, DatePicker,
  FeatureCard, Hero, Input, KeyValueList, MetricTile, Section, Select, Skeleton, TabPanel, Tabs,
  Textarea
- **Inline-style (tokenToCssVar)** — 7 components: Divider, EmptyState, Heading, IconButton (mixed),
  Link, LoadingState, Pagination
- **Conditional-class** — 0 components with pure conditional logic (several Tailwind-class
  components do string concat to pick variant classes, but they do it via static lookup objects, not
  runtime template literals)
- **CVA-ready** — 1 (Button, after Task 5 refactor)
- **Mixed** — 6 components: Breadcrumb, Cluster, ConfirmDialog, FadeIn, Sidebar, Split, Stagger,
  Toast

> **Note on "Mixed":** the actual count of mixed components is 8 (see table). Several do inline
> `style={{}}` for dynamic values that can't be expressed as static Tailwind classes (responsive
> grid ratios, scoped @media, CSS custom properties for animations) alongside Tailwind classNames.
> These are the hardest to refactor — they cannot simply switch to CVA without first moving the
> dynamic-value logic to a CSS variable injection layer.

---

## Per-component classification

| # | Component | Pattern | Key observation | Refactor complexity |
|---|-----------|---------|-----------------|---------------------|
| 1 | Accordion | Tailwind-class | Static `bg-card text-card-foreground divide-y` literals; no inline style | Low |
| 2 | Alert | Inline-style | `VARIANT_STYLES` record with raw hex values (`#eff6ff`, `#1e40af`); completely bypasses design token system | **High** — hex hardcodes fight theming |
| 3 | Avatar | Mixed | SIZE_CLASS / STATUS_CLASS are Tailwind lookups; `bg-muted text-muted-foreground` in template literal concat | Low-Med |
| 4 | Badge | Tailwind-class | VARIANT_CLASS + BASE constant strings; `bg-primary/10 text-primary` semantic tokens; clean concat | Low |
| 5 | Breadcrumb | Inline-style | Full `style={{...}}` with hardcoded color strings (`#888`), no Tailwind classes at all | **High** — no token system used |
| 6 | Button | Tailwind-class | VARIANT_CLASSES + SIZE_CLASSES + BASE_CLASSES as string constants; array join; CVA-ready shape | Low (being refactored in Task 5) |
| 7 | Card | Tailwind-class | ELEVATION_CLASSES lookup + base class join; `bg-card text-card-foreground` token refs | Low |
| 8 | Checkbox | Tailwind-class | Static classNames only; `border-input text-primary accent-primary focus-visible:ring-ring` | Low |
| 9 | Cluster | Mixed | `JUSTIFY_CLASS` / `ALIGN_CLASS` Tailwind lookups for flex; `gap` via `tokenVar()` inline function → CSS var in `style={{}}` | Med — custom tokenVar helper alongside Tailwind |
| 10 | ConfirmDialog | Mixed | Trigger button has no classes; Dialog.Overlay / Dialog.Content use inline `style={{}}` with raw values (rgba, #fff, rems); buttons have no styling at all | **High** — almost no token system used; Radix primitives fully unstyled |
| 11 | CustomBlock | Tailwind-class | Minimal: merges `"custom-block"` + `tailwind` prop; only wrapper styling; token consumption driven by user-injected HTML | Low (N/A to phase 2) |
| 12 | DatePicker | Tailwind-class | Same FIELD_BASE / LABEL_BASE / INPUT_BASE pattern as Input/Select/Textarea; full Tailwind token refs | Low |
| 13 | Divider | Inline-style (tokenToCssVar) | Pure inline style; `tokenToCssVar("neutral.200")`, `tokenToCssVar("spacing.px/2")` | Med — tokenToCssVar system is consistent but not Tailwind |
| 14 | EmptyState | Inline-style (tokenToCssVar) | Full inline-style block; `tokenToCssVar("spacing.3/8")`, `tokenToCssVar("neutral.500")`, `tokenToCssVar("typography.*")`, `tokenToCssVar("primary.500")` | Med — consistent tokenToCssVar but needs Tailwind migration |
| 15 | FadeIn | Mixed | `className="motion-wrapper"` static; inline style for CSS custom properties (`--fadein-delay`, `--fadein-duration`); CSS-var motion tokens — intentional non-Tailwind | Low (motion tokens are intentional) |
| 16 | FeatureCard | Conditional-class | `isLeft` boolean drives `flex-row gap-4` vs `flex-col gap-3`; template literal in className; icon size also conditional; all tokens via Tailwind names | Low-Med |
| 17 | Form | Bare HTML | No Tailwind or token system on field elements; react-hook-form wrapper; field sub-components have bare `<input>/<select>/<textarea>` with no classes | **High** — needs full reskin to match Input/Select/Textarea patterns |
| 18 | Heading | Inline-style (tokenToCssVar) | `tokenToCssVar(SIZE_BY_LEVEL[level])` + `tokenToCssVar("typography.bold")`; fully inline; no className | Med — needs migration to Tailwind heading classes |
| 19 | Hero | Tailwind-class | SECTION_BASE / CTA_BASE / CTA_VARIANT constants; conditional containerClass via template literal; full shadcn token names | Low-Med |
| 20 | IconButton | Mixed | Imports old `buttonVariants` (pre-CVA object) and reads `.variant[v].bg / .color`; maps them to `tokenToCssVar()` in inline `style={{}}`; no className tokens | **High** — will break when variants.ts is replaced by CVA factory (Task 5); needs parallel update |
| 21 | Input | Tailwind-class | FIELD_BASE / LABEL_BASE / INPUT_BASE constants; `border-input bg-background ring-ring text-foreground` | Low |
| 22 | KeyValueList | Tailwind-class | `divide-border text-muted-foreground text-foreground`; conditional template literal for empty state | Low |
| 23 | Link | Inline-style (tokenToCssVar) | `tokenToCssVar("primary.500")`, `tokenToCssVar("typography.base")`; full inline; no className | Med |
| 24 | LoadingState | Inline-style (tokenToCssVar) | Full inline-style; `tokenToCssVar("spacing.*")`, `tokenToCssVar("neutral.*")`, `tokenToCssVar("primary.500")` | Med |
| 25 | MetricTile | Tailwind-class | TILE_BASE / LABEL_BASE / VALUE_BASE / DELTA_BASE constants + DELTA_TONE lookup; `bg-card text-foreground text-muted-foreground` | Low |
| 26 | NavLink | Inline-style | Inline style with hardcoded rem values; `fontWeight: active ? 600 : 400` — conditional inline style | Med — `active` logic needs Tailwind conditional-class pattern |
| 27 | Pagination | Inline-style (tokenToCssVar) | `tokenToCssVar("spacing.2")`, `tokenToCssVar("typography.sm")`, `tokenToCssVar("neutral.600/900")`; fully inline | Med |
| 28 | Section | Tailwind-class | VARIANT_CLASS lookup; `bg-background bg-card text-card-foreground bg-primary/5 bg-muted/30` | Low |
| 29 | Select | Tailwind-class | Same FIELD_BASE / LABEL_BASE / SELECT_BASE pattern; shadcn token names throughout | Low |
| 30 | Sidebar | Mixed | className absent from grid wrapper; emits `<style>` block with scoped `@media` and `grid-template-columns: ${width}` — dynamic width cannot be a static Tailwind class | Med — intentional `<style>` injection for responsive layout |
| 31 | Skeleton | Tailwind-class | `animate-pulse bg-muted`; conditional shape classes via ternary string; clean pattern | Low |
| 32 | Split | Mixed | emits `<style>` block with scoped `@media` for `grid-template-columns`; `className="grid gap-6"` on wrapper | Med — same intentional `<style>` injection as Sidebar |
| 33 | Stagger | Mixed | `className="motion-wrapper motion-stagger-item"` static; CSS custom props (`--stagger-interval`, `--motion-stagger-i`) in inline style — intentional motion token | Low (motion tokens are intentional) |
| 34 | TabPanel | Tailwind-class | `rounded-md border bg-card text-card-foreground p-4`; static only | Low |
| 35 | Table | Inline-style | `style={{ width: "100%", borderCollapse: "collapse" }}` on outer; column `th` padding via inline style | Med |
| 36 | Tabs | Tailwind-class | TAB_BASE / TAB_ACTIVE constants; `text-muted-foreground border-primary border-border`; template literal concat for active state | Low |
| 37 | Textarea | Tailwind-class | Same FIELD_BASE / LABEL_BASE / TEXTAREA_BASE pattern as Input; shadcn token names | Low |
| 38 | Toast | Mixed | ToastViewport uses inline `style={{position: "fixed", ...}}`; Toast content (Title/Description) completely unstyled (bare Radix primitives) | Med — Radix ToastRoot needs className composition |

---

## Summary counts (true classification)

| Pattern | Count | Components |
|---------|-------|------------|
| Tailwind-class (pure) | 18 | Accordion, Badge, Button*, Card, Checkbox, DatePicker, Input, KeyValueList, MetricTile, Section, Select, Skeleton, TabPanel, Tabs, Textarea, FeatureCard, Hero, Stagger |
| Inline-style (tokenToCssVar) | 5 | Divider, EmptyState, Heading, Link, LoadingState, Pagination |
| Inline-style (raw values) | 3 | Alert, Breadcrumb, Table |
| Mixed (Tailwind + inline) | 7 | Avatar, Cluster, ConfirmDialog, FadeIn, IconButton, NavLink, Sidebar, Split, Toast |
| Bare HTML (no token system) | 1 | Form |
| CVA-ready | 1 | Button (after Task 5) |

> *Button is Tailwind-class today; becomes CVA-ready after Task 5.
> *FeatureCard uses conditional template literals but is fundamentally Tailwind-class.
> *Stagger uses inline CSS custom properties for motion only — classified Tailwind-class for the
> design-token surface.

**Critical finding:** IconButton currently reads from the old `buttonVariants` object (pre-CVA)
and converts values to `tokenToCssVar()` inline styles. When Task 5 replaces `variants.ts` with a
CVA factory, IconButton will break unless it is simultaneously updated. The CVA factory exports
class strings directly — IconButton needs to switch to `buttonVariants({ variant, size })` just like
the refactored Button.tsx.

---

## Refactor sequencing

Phase 2 component refactor batches (from spec):

### Batch 1 — Layout primitives (Low complexity, high visual impact)
Stack (N/A — not in library), Section, Split, Sidebar, Cluster, Card, Hero

All are Tailwind-class or Mixed with intentional `<style>` blocks. The `<style>`-emitting
components (Sidebar, Split) need their responsive layout logic moved to a CSS-variable approach
before they can be CVA-ified, but their token surface is otherwise clean.

### Batch 2 — Data display (Low-Med complexity)
MetricTile, Heading, Badge, Avatar, KeyValueList, Table

Heading and Table are the outliers: Heading is pure tokenToCssVar inline style (needs Tailwind
migration); Table is mixed with hardcoded inline styles. The rest are low complexity.

### Batch 3 — Forms (Low complexity individually, high effort collectively)
Input, Textarea, Select, DatePicker, Checkbox, Form

Input/Textarea/Select/DatePicker share the same FIELD_BASE / LABEL_BASE / INPUT_BASE pattern —
they can be CVA-ified in a single batch. Form is the exception: it has zero token system today
(bare HTML field elements) and needs a full reskin before CVA can be applied.

### Batch 4 — Feedback + nav + remaining
Skeleton, Alert, EmptyState, LoadingState, Tabs, Accordion, Breadcrumb, Divider, NavLink, Link,
Pagination, IconButton, Toast, ConfirmDialog

Alert and Breadcrumb use raw hex/rem hardcodes — these need a dedicated "token normalisation"
pass before CVA. IconButton needs coordinated update alongside the Button CVA refactor (see below).

---

## Risks

### Risk 1 — IconButton breakage from Task 5 (HIGH)
IconButton imports `buttonVariants.variant[v].bg` (the old token-path object). After Task 5
replaces `variants.ts` with a CVA factory, `buttonVariants` will be a function, not an object.
**IconButton must be updated in the same PR as Task 5** or it will fail to compile. The update
is straightforward: replace `tokenToCssVar(v.bg)` inline styles with `buttonVariants({ variant,
size })` className — but it must happen atomically with variants.ts changing.

### Risk 2 — Alert / Breadcrumb use raw hex (MEDIUM)
Alert encodes variant colors as hex strings (`#eff6ff`, `#1e40af`) with no CSS variable backing.
In dark mode or theme-switch scenarios these are invisible to the token system. Any density/
elevation/color token expansion in Phase 2 will not reach these components until the hardcodes
are replaced with `bg-info/10 text-info border-info/20` Tailwind semantics.

### Risk 3 — Form has zero token coverage (MEDIUM)
The Form component renders bare `<input>/<select>/<textarea>/<button>` with no className or style.
It is functionally correct but visually unstyled (inherits browser defaults). In production
this is masked because Form's sub-fields are typically implemented by individual Input/Select/
Textarea components in schema-generated code. However the Form component itself used in isolation
will look broken. A Phase 2 Forms batch should restyle FormFieldImpl to reuse Input/Select/
Textarea class constants.

### Risk 4 — Sidebar / Split emit `<style>` blocks (LOW-MEDIUM)
These two components inject a scoped `<style>` element to implement dynamic `grid-template-columns`
because Tailwind's JIT cannot scan runtime values. This is intentional and correct, but it means
the responsive layout is invisible to style extraction tools and Storybook snapshots. The Phase 2
refactor should evaluate whether CSS custom properties on the wrapper element (`--split-template`)
with a single static Tailwind class referencing the variable would be cleaner.

### Risk 5 — tokenToCssVar vs. Tailwind dual systems (MEDIUM)
Seven components use `tokenToCssVar()` from `@tentoroforge/renderer` to build CSS var references
inline. Five more use raw Tailwind class names for the same semantic tokens. Both systems
ultimately resolve to the same CSS variables, but the dual-system creates maintenance risk:
a token rename in `defaultTokens` must be updated in two places. Phase 2 should consolidate
toward the Tailwind-class pattern; `tokenToCssVar` usage should be limited to places where
static class names are genuinely insufficient (e.g., arbitrary computed values).

### Risk 6 — Visual regression baseline coverage (LOW)
The Playwright visual regression suite (Task 3) captured baselines for 12 of the 38 components.
The 26 uncaptured components (primarily form fields, layout primitives, motion wrappers, and
Radix-based overlays) have no automated visual safety net. Any Phase 2 refactor touching those
components should capture a baseline before starting.

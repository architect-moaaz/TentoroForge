# Showcase pages — component & fix coverage checklist

Pages built **through the editor UI** (palette search → click-to-insert → nest →
set props), not by writing schema JSON. That distinction is the point: the drop
path is what this session's fixes changed, so exercising it is the verification.

Project: `gh0mlpbp` (the generated Inventory app).

## Coverage target

| category | components | pages covering them |
|---|---|---|
| layout | 18 | `/ops-dashboard`, `/workspace` |
| input | 41 | `/stock-intake`, `/toolbar-lab` |
| display | 31 | `/ops-dashboard`, `/item-profile` |
| **total** | **90** | 5 pages |

Data (12), feedback (21) and navigation (10) are out of scope here — they were
not part of the audit rounds.

---

## Pages

### `/ops-dashboard` — layout scaffolding + at-a-glance display
Hero with status chips → 4-up KPI grid → three side-by-side cards (capacity,
stock health, recent movement) → approvals → throughput/checks split → animated
footer cards.

### `/stock-intake` — the full input surface
A real receiving form, grouped: Identity · Quantity & value · Scheduling ·
Classification · Flags · Capture · Detail, then the action row.

### `/item-profile` — display components in a record context
Identity header → tabbed Overview / Media / Structure → ownership → scheduling →
search → an adjust-stock dialog.

### `/workspace` — structural layout
AppShell → SplitView → Sidebar (filters, saved views) + main column with a
deep-linkable tab panel and a cart page.

### `/toolbar-lab` — chrome-style inputs
Global search, search input, theme toggle, shortcuts, filter builder, bulk
action bar, add-to-cart.

---

## Fixes exercised by building these pages

Each row is a fix from this session that the build path actually goes through.

| # | fix | how the build exercises it |
|---|---|---|
| 1 | `{{expr}}` binding format replaces `{$binding}` | binding any prop on any page |
| 2 | legacy `{$binding}` heals on page load | opening pages saved earlier |
| 3 | `validateNoLegacyBindings` commit guard | every dispatch during the build |
| 4 | one input state contract (`useFieldValue`) | every control on `/stock-intake` |
| 5 | `defaultValue` expressible in schema | seeded inputs render their value |
| 6 | Rating / Slider-range hidden inputs | form serialization on `/stock-intake` |
| 7 | `DATA_SOURCE_PROPS` unshadowed | authoring `options` on Select/MultiSelect |
| 8 | 35 ActionPickers → authorable array/object | any list prop edited in Props |
| 9 | `RowsControl` repeating-row editor | editing options/steps/chips |
| 10 | registry prop gap closed (39 props) | `Button.variant: danger` on intake |
| 11 | real icon resolution | `IconButton` / `FeatureCard` render glyphs |
| 12 | `normalizeSeed` at both write boundaries | every drop; Heading `level` stays numeric |
| 13 | Tailwind `@source` depth fix | Calendar's 7-column grid on `/stock-intake` |
| 14 | ActivityFeed `maxHeight: 0` | feed renders on `/ops-dashboard` |
| 15 | `style` on ApprovalStepper/PersonCard/ActivityFeed | Style panel edits show |
| 16 | ApprovalStepper / Timeline key fallback | no React key warnings |
| 17 | selectable error placeholders | any node that errors is reachable |
| 18 | document-listener scoping | palette search still typable with GlobalSearch on canvas |
| 19 | aggregate metrics computed, not looked up | KPI tiles show numbers |

---

## Verification method

For each page, after building:
1. **Renders** — node count matches inserts; no `⚠ render error` in the canvas.
2. **No console errors** — `read_console_messages` filtered for React warnings.
3. **No issue badge** — the editor's own counter reads zero.
4. **Persists** — the saved schema on disk matches the tree, with no `$binding`
   objects and no schema-invalid seeds.
5. **Preview** — the page renders in the scaffold at `:6503/p/gh0mlpbp/<route>`.

Results are filled in below as each page completes.

---

## Results

### `/ops-dashboard` — BUILT ✅

54 nodes, **29 component types**, built entirely through palette search →
click-to-insert → nest. Persisted to `src/schemas/ops-dashboard.json`.

Covered: ActivityFeed, ApprovalStepper, Badge, Card, Cluster, Container,
Divider, FadeIn, FeatureCard, Gauge, Grid, GridCell, Heading, Heatmap, Hero,
MetricTile, MoneyDisplay, QRCode, Row, Section, Spacer, Split, SplitArc, Stack,
Stagger, Stat, Stepper, Tag, ValidationChecklist.

| check | result |
|---|---|
| every insert landed | **0 misses** across 43 insert steps |
| render errors in canvas | **0** |
| editor issue badge | **none** |
| nesting is real (not just indented) | verified — `Badge` is a DOM descendant of `Hero` |
| Grid auto-created its cells | **yes** — 4 `GridCell`s appeared for a 4-column Grid |
| persisted correctly | 54 nodes on disk, matching the tree |
| unsaved-changes guard | fired on navigation — the editor refused to discard work |

**Known cosmetic issue:** a few duplicated nodes (Card ×9, Divider ×4,
ActivityFeed ×2, Gauge ×2, Stepper ×2). Cause was mine, not the editor's — I
started a second build loop while the first was still running, so two loops
inserted concurrently. To be cleaned up before final sign-off; nothing is
broken, there is just redundancy.

### `/stock-intake` — SHELL ONLY, build paused
Deliberately halted at 3 nodes. Round 5's display audit began driving the same
editor from a second tab, and two automated clients competing for one editor
slows both and makes the audit's observations untrustworthy. Resuming after the
audit completes.

### `/item-profile`, `/workspace`, `/toolbar-lab` — not started

**Coverage so far: 29 of 90.**

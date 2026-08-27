# High-Fidelity Domain-Aware Schema Generation — Design Spec

**Date:** 2026-05-03
**Owner:** Tentoro Forge platform
**Status:** Approved for implementation
**Builds on:** Phase 1 schema runtime, Phase 2A-F editor, Phase 4 schema-mode pipeline (forge-v3)

---

## Goal

Make schema-mode generations look and feel as polished as v0/Lovable output (color theory, typography, layout archetypes, motion, all reasoned per-domain by the LLM) while preserving the editability, speed, and structural safety of the schema-driven runtime.

The runtime renders pages from JSON schemas. Today the LLM produces structurally correct schemas but visually elementary output: every project gets the same defaults, the planner's design rationale dies in the chat history, and the component library is too narrow to express modern designs. This spec closes those gaps with one cohesive vertical-slice plan.

## Non-goals (deferred to follow-on plans)

- **Marketing pack (v2):** Testimonial, FAQ, Pricing, Marquee, Logo cloud, IllustrationSlot variants beyond a stub.
- **Dashboard pack (v3):** KanbanCard, Timeline, ProgressRing, ChartCard, Activity feed.
- **Motion primitives beyond fade-in/stagger.**
- **Two-stage plan-then-compose generation.** v1 ships single-stage with few-shot gold examples.
- **Automatic regeneration on token changes.** v1 requires manual re-run via debug endpoint.
- **Modal/Drawer/Toast as components.** Each needs its own plan (focus management, queue semantics).
- **Charts as components.** Pulls in a charting dependency.

## Architecture overview

```
┌──────────────────────────────────────────────────────────────────┐
│                       Generation pipeline                          │
└──────────────────────────────────────────────────────────────────┘

   planner.py / design_agent.py                                       
       │ already emits design-spec.json (palette, typography,         
       │ density, layout, entityPatterns, imagery, animation)         
       ▼                                                              
   ┌───────────────────────────┐                                      
   │ services/design_compiler  │  deterministic mapper                
   │       (NEW)               │                                      
   └─────────────┬─────────────┘                                      
                 │ writes                                              
                 ▼                                                     
   src/theme/tokens.custom.json  ◄── runtime_injector copies         
                                       this into the generated app    
                                                                       
   feature_slice_schema_agent  ◄── now reads:                         
       ├─ design-spec.json            • design rationale              
       ├─ tokens.custom.json          • compiled token paths          
       ├─ schema_examples/<archetype> • gold-standard example         
       └─ library descriptor          • registered components         
                 │ writes                                              
                 ▼                                                     
   src/schemas/<entity>/{list,detail,form}.json                        

┌──────────────────────────────────────────────────────────────────┐
│                          Render pipeline                          │
└──────────────────────────────────────────────────────────────────┘

   Generated app boot:                                                
     theme/tokens.server.ts merges defaultTokens + tokens.custom      
     app/layout.tsx applies compileTokens(tokens) as CSS vars         
                  │                                                   
                  ▼                                                   
   <SchemaRenderer page={...} registry={lib} dataEngine={...}>        
        ├─ dispatch.tsx routes nodes → library components             
        ├─ StyleSlot props → CSS vars resolved on each node           
        └─ Custom node → renders sanitized {html, tailwind}           
```

Three guarantees the architecture preserves:

1. Schemas remain Zod-validated end to end. Adding `StyleSlot`, `Custom`, and new node types extends the schema; it does not loosen it.
2. The runtime is deterministic — same `tokens.custom.json` plus same schema produces byte-identical output.
3. Every node type is registered with a `propsSchema`, so the visual editor's properties panel handles all of them through Zod introspection.

## 1. Schema package extensions (`@tentoroforge/schema`)

Schema version bumps from `"1"` to `"2"`. The exported `Page` becomes a discriminated union on `schemaVersion` so v1 schemas keep loading.

### 1.1 StyleSlot (mixin every node accepts)

```ts
const Background = z.discriminatedUnion("type", [
  z.object({ type: z.literal("solid"),    value: TokenRef }),
  z.object({ type: z.literal("gradient"), from: TokenRef, to: TokenRef,
             angle: z.number().optional() }),
  z.object({ type: z.literal("image"),    url: z.string(),
             overlay: TokenRef.optional(), position: z.string().optional() }),
  z.object({ type: z.literal("pattern"),  name: z.enum(["dots","grid","noise","mesh"]),
             color: TokenRef.optional() }),
]);

const Motion = z.enum(["none","fade-in","fade-up","stagger","slide-in"]);

export const StyleSlot = z.object({
  background: Background.optional(),
  padding:    SpacingTokenRef.optional(),
  radius:     RadiusTokenRef.optional(),
  shadow:     ShadowTokenRef.optional(),
  motion:     Motion.optional(),
}).strict();
```

`TokenRef = z.string().regex(/^tokens\.[a-z]+\.[a-zA-Z0-9.-]+$/)` — narrow string regex. Examples: `tokens.color.primary.500`, `tokens.spacing.semantic.section`.

### 1.2 Custom node (escape hatch)

```ts
export const CustomNode = z.object({
  id: z.string(),
  type: z.literal("Custom"),
  props: z.object({
    html:     z.string(),
    tailwind: z.string().optional(),
    label:    z.string().optional(),
  }),
  style: StyleSlot.optional(),
});
```

Renderer mounts via `dangerouslySetInnerHTML` after a DOMPurify pass (pinned `^3.0`). The editor renders an opaque labeled overlay box; the user can edit raw HTML/Tailwind in a side drawer.

### 1.3 New structural node types (v1)

```ts
HeroNode      = type "Hero",        props { eyebrow?, headline, subhead?,
                                            layout: "centered"|"split"|"stacked",
                                            ctas[], media? }, children?
SectionNode   = type "Section",     props { variant: "plain"|"feature"|"cta"|"stats"|"split",
                                            title?, subtitle?, anchor? }, children
MetricTile    = type "MetricTile",  props { label, value, format, delta?, icon?, trend? }
FeatureCard   = type "FeatureCard", props { title, description, icon?, cta?,
                                            layout: "icon-top"|"icon-left" }
SplitNode     = type "Split",       props { ratio, breakpoint }, children (exactly 2)
SidebarNode   = type "Sidebar",     props { width }, children (exactly 2)
ClusterNode   = type "Cluster",     props { gap, justify, align }, children
TabsNode      = type "Tabs",        props { tabs[], value }, children — index matches tab
AccordionNode = type "Accordion",   props { mode: "single"|"multi", defaultOpen[] },
                                    children — each child is a panel (label, content)
AvatarNode    = type "Avatar",      props { src?, name, size, status? }
KeyValueList  = type "KeyValueList",props { items: [{label, value, copyable?}] }
SkeletonNode  = type "Skeleton",    props { variant: "rect"|"circle"|"text", lines? }
```

Form input nodes (close existing gap that prevents valid Form schemas):

```ts
InputNode      = type "Input",      props { name, label, type, placeholder?, bind?, validators? }
SelectNode     = type "Select",     props { name, label, options[], bind?, validators? }
TextareaNode   = type "Textarea",   props { name, label, rows?, bind?, validators? }
CheckboxNode   = type "Checkbox",   props { name, label, bind? }
DatePickerNode = type "DatePicker", props { name, label, bind?, min?, max? }
```

Motion primitives:

```ts
FadeInNode  = type "FadeIn",  props { delay?, duration? }, children
StaggerNode = type "Stagger", props { delay?, interval? }, children
```

Every node above (and every existing node — Stack, Row, Card, Button, etc.) accepts `style: StyleSlot.optional()`.

### 1.4 Migration helper

`migratePage(raw): PageV2`:

1. If `schemaVersion === "2"`, return as-is.
2. If `schemaVersion === "1"` (or missing), stamp `schemaVersion: "2"`.
3. Walk node tree — `style` field stays absent (TS optional, no-op).
4. Validate against `PageV2`. Throw if invalid.

`loadSchema` calls `migratePage` on every load. `saveSchema` always writes v2. Old files on disk upgrade silently.

## 2. Library expansion (`@tentoroforge/library` v1)

20 new components + 2 new layout JSON templates. Every component consumes the same `resolveStyle(slot)` helper that maps token refs (`tokens.color.primary.500`) to CSS variables (`var(--token-color-primary-500)`).

### 2.1 Shared style resolver

```ts
// packages/library/src/style/resolveStyle.ts
export function resolveStyle(slot?: StyleSlotShape): React.CSSProperties {
  const out: React.CSSProperties = {};
  if (!slot) return out;
  if (slot.padding) out.padding      = `var(--token-${slot.padding.replace(/\./g,"-")})`;
  if (slot.radius)  out.borderRadius = `var(--token-${slot.radius.replace(/\./g,"-")})`;
  if (slot.shadow)  out.boxShadow    = `var(--token-${slot.shadow.replace(/\./g,"-")})`;
  if (slot.background) out.background = backgroundCss(slot.background);
  return out;
}
```

`Motion` is handled by a `useMotion(slot.motion)` hook that returns inline transition style or a `data-motion` attribute the runtime stylesheet animates.

### 2.2 Components (v1)

| Category | Components |
|---|---|
| **Foundation** | Hero, Section, MetricTile, FeatureCard |
| **Layout** | Split (2 children, ratio), Sidebar (2 children, width), Cluster (flex-wrap), |
| **Interactive containers** | Tabs (indexed children), Accordion |
| **Display** | Avatar, KeyValueList, Skeleton |
| **Form inputs** | Input, Select, Textarea, Checkbox, DatePicker |
| **Motion** | FadeIn, Stagger |
| **Escape hatch** | CustomBlock (renders sanitized HTML) |

20 total. Each follows the existing `Foo/Foo.tsx` + `Foo/Foo.schema.ts` + `Foo/Foo.test.tsx` layout.

### 2.3 Layout templates (JSON)

Two new entries in `packages/library/src/layouts/`:

| Layout | Purpose |
|---|---|
| `MarketingLayout.json` | Header + hero region + content + footer. Required before v2 marketing pack. |
| `SettingsLayout.json` | App sidebar + secondary nav + content panel. For configuration-heavy apps. |

### 2.4 Worked example — Hero with gradient + motion

Schema fragment:

```json
{
  "type": "Hero",
  "props": {
    "eyebrow": "Modern HR for fast-moving teams",
    "headline": "Leave management without the spreadsheet",
    "ctas": [
      { "label": "Get started", "action": { "type": "navigate", "to": "/signup" }, "variant": "primary" }
    ],
    "layout": "centered"
  },
  "style": {
    "background": { "type": "gradient",
                    "from": "tokens.color.primary.50",
                    "to":   "tokens.color.surface.0" },
    "padding": "tokens.spacing.semantic.section",
    "motion":  "fade-in"
  }
}
```

Renders to:

```html
<section data-motion="fade-in"
         style="background: linear-gradient(135deg, var(--token-color-primary-50) 0%,
                                                     var(--token-color-surface-0) 100%);
                padding: var(--token-spacing-semantic-section);">
  <div class="hero-centered">
    <p class="hero-eyebrow">Modern HR for fast-moving teams</p>
    <h1 class="hero-headline">Leave management without the spreadsheet</h1>
    <div class="hero-ctas"><a class="btn btn-primary">Get started</a></div>
  </div>
</section>
```

When `tokens.custom.json` re-targets `--token-color-primary-50` for a fintech app, the gradient changes color without re-running any LLM call.

## 3. Token compiler (`backend/services/design_compiler.py`)

Pure transform — no LLM. Reads `src/contracts/design-spec.json`, writes `src/theme/tokens.custom.json`. Wired into `_run_relay_pipeline` immediately after the design agent and before the schema agent.

### 3.1 Color ramp generation

Single anchor color → 11-stop HSL ramp. Lightness curve matches Tailwind's standard (industry convention, well-tested).

```
anchor: "#3b82f6" → hsl(217, 91%, 60%)
output: tokens.color.primary.{50,100,200,300,400,500,600,700,800,900,950}
        L = {97,93,87,78,68,60,52,44,36,28,18}
```

`secondary` and `accent` get full 11-stop ramps. Status colors (`success`, `warning`, `error`, `info`) get a 3-stop ramp (`{50,500,700}`) — they're indicators, not full palettes.

Implementation: `colorsys` from stdlib for HSL conversion. Curve hardcoded.

### 3.2 Field-by-field mapping

Every field in `design-spec.json` has a deterministic destination in `tokens.custom.json`:

| design-spec field | tokens.custom.json destination |
|---|---|
| `colorPalette.primary` | ramp → `tokens.color.primary.50..950` |
| `colorPalette.secondary` | ramp → `tokens.color.secondary.50..950` |
| `colorPalette.accent` | ramp → `tokens.color.accent.50..950` |
| `colorPalette.background` | `tokens.color.surface.0` |
| `colorPalette.surface` | `tokens.color.surface.1` |
| `colorPalette.surfaceHover` | `tokens.color.surface.2` |
| `colorPalette.border` | `tokens.color.border.default` |
| `colorPalette.muted` | `tokens.color.muted.default` |
| `colorPalette.textPrimary` | `tokens.color.text.primary` |
| `colorPalette.textSecondary` | `tokens.color.text.secondary` |
| `colorPalette.textTertiary` | `tokens.color.text.tertiary` |
| `colorPalette.sidebar*` | `tokens.color.sidebar.{bg,text,active}` |
| `colorPalette.{success,warning,error,info}` | 3-stop ramp → `tokens.color.<name>.{50,500,700}` |
| `typography.fontFamily` | `tokens.typography.font.body` (and `.heading` if separate) |
| `typography.scale.{h1,h2,h3,body,caption}` | `tokens.typography.scale.<name>` |
| `typography.headingWeight` | `tokens.typography.weight.heading` |
| `typography.lineHeight` | `tokens.typography.lineHeight.{tight,normal}` |
| `typography.letterSpacing` | `tokens.typography.letterSpacing.{heading,body}` |
| `spacing.scale` | parsed → `tokens.spacing.{0,1,2,3,4,6,8,12,16,24,32,48,64}` (13-stop scale, matches Section 4) |
| `spacing.{pagePadding,cardPadding,sectionGap,elementGap,inputGap}` | `tokens.spacing.semantic.{page,card,section,element,input}` |
| `borderRadius.{sm,md,lg,xl,full}` | `tokens.radius.<name>` |
| `shadows.{sm,md,lg,xl}` | `tokens.shadow.<name>` |
| `animation.duration` | `tokens.motion.duration.{fast,normal}` |
| `animation.easing` | `tokens.motion.easing.standard` |
| `imagery.{loginBackground,dashboardHero}` | `tokens.imagery.{login,dashboard}` |
| `imagery.style` fields | `tokens.imagery.style.{emptyState,icon,avatar}` |
| `statusColors.<EntityStatus>.color` | `tokens.semantic.status.<entity>.<status>` |
| `layout.{navigation,density}` | `tokens.layout.{nav,density}` |

Density mapping: `compact` shrinks `spacing` scale by 25%, `spacious` grows by 25%, applied as a multiplier across `tokens.spacing.*`.

### 3.3 Failure modes

| Condition | Behavior |
|---|---|
| Field missing in design-spec | Falls back to `defaultTokens` value silently. Logs at INFO. |
| Invalid hex color | Logs WARNING, skips ramp generation, uses default ramp. |
| `design-spec.json` absent | `tokens.custom.json` not written; runtime uses `defaultTokens`. Pipeline continues. |

Compiler never raises. The downstream pipeline always sees a valid (default or custom) token state.

### 3.4 Tests

`backend/tests/services/test_design_compiler.py`:

1. Anchor color → 11-stop ramp produces monotonically decreasing lightness; anchor stays at stop `500`.
2. Full design-spec → tokens.custom.json snapshot match (one fintech fixture, one healthcare fixture).
3. Missing field falls back to default without raising.
4. Density multiplier produces expected spacing scale (`compact` → `0.75x`, `spacious` → `1.25x`).
5. Invalid hex logs warning and falls back; doesn't propagate.

## 4. defaultTokens canonical structure

`packages/library/src/theme/default-tokens.ts` is refactored to expose the exact namespace the LLM emits and the validator expects. This becomes the contract source of truth.

```ts
export const defaultTokens = {
  color: {
    primary:   { 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950 },
    secondary: { ...11 stops... },
    accent:    { ...11 stops... },
    surface:   { 0, 1, 2 },
    border:    { default },
    muted:     { default },
    text:      { primary, secondary, tertiary },
    sidebar:   { bg, text, active },
    success:   { 50, 500, 700 },
    warning:   { 50, 500, 700 },
    error:     { 50, 500, 700 },
    info:      { 50, 500, 700 },
  },
  spacing: {
    0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64,
    semantic: { page, card, section, element, input },
  },
  radius:     { sm, md, lg, xl, full },
  shadow:     { sm, md, lg, xl },
  typography: {
    font:           { body, heading },
    weight:         { body, heading },
    scale:          { h1, h2, h3, body, caption },
    lineHeight:     { tight, normal },
    letterSpacing:  { heading, body },
  },
  motion: {
    duration: { fast, normal },
    easing:   { standard },
  },
  imagery: {
    login, dashboard,
    style: { emptyState, icon, avatar },
  },
  semantic: {
    status: {  /* filled by design_compiler per project */ },
  },
};
```

Default values: Tailwind-style scales for spacing, neutral grays for surfaces, Inter for typography, conservative shadow ramp.

A snapshot test in `packages/library/tests/default-tokens.test.ts` locks the expected paths so accidental refactors don't break the contract.

## 5. Schema-agent prompt strategy

`backend/services/schema_prompt.py` is restructured to inject design intelligence and a curated archetype example. The agent (`feature_slice_schema_agent.py`) keeps its async-generator shape.

### 5.1 Prompt inputs

Reads four files (when present) and merges them:

- `src/contracts/design-spec.json` — domain rationale, layout strategy, entityPatterns
- `src/theme/tokens.custom.json` — for token paths only (values not included)
- `backend/services/schema_examples/<page_type>/<archetype>.json` — gold-standard example
- Library descriptor — auto-generated from registered components

### 5.2 Token-paths section is auto-generated

The token paths in the prompt are derived from `defaultTokens` at prompt-build time, not hand-written. Same source of truth as the validator. Eliminates drift.

```python
def render_token_paths(tokens: dict) -> str:
    """Walk defaultTokens; emit one line per leaf path."""
    lines = []
    def walk(obj, prefix):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else f"tokens.{k}"
            if isinstance(v, dict):
                walk(v, path)
            else:
                lines.append(path)
    walk(tokens, "")
    return "\n".join(lines)
```

### 5.3 Gold-standard examples

Stored at `backend/services/schema_examples/`:

```
schema_examples/
  list/
    table.json          # dense data table
    card-grid.json      # visual cards (e.g., user directory)
    kanban.json         # status-column board
  detail/
    tabbed-hero.json    # hero block + tabbed body
    split-detail.json   # left summary | right tabs
    profile.json        # avatar-led detail
  form/
    single-column.json
    sectioned.json
    wizard.json
  landing/
    hero-features-cta.json
  README.md
```

Each example is a fully valid v2 Page schema demonstrating Hero with gradient/pattern background, real token refs, StyleSlot usage (motion, padding, radius, shadow), idiomatic component composition, form input bind expressions, status colors via `tokens.color.success.500` etc.

Examples are hand-curated. They define the "house style" the LLM imitates.

### 5.4 Archetype selection

The planner emits `design-spec.entityPatterns.<EntityName>.{listView, detailView, formView}`. The prompt builder uses this as the lookup key into `schema_examples/<page_type>/<archetype>.json`. Unknown archetype falls back to `<page_type>/`'s first example and logs a warning.

### 5.5 Compact prompt structure

```
SYSTEM: You generate JSON schemas. Output ONLY a single JSON object.

USER:
## App context
{description}

## Domain & design rationale
{design_spec.designRationale}

## Available design tokens (use these — never inline hex/px/rem)
{token_paths}              # auto-generated from defaultTokens

## Available components
{library_descriptor}       # name + acceptsChildren + summarized props

## Page archetype
This is a {page_type} page using the "{archetype}" layout for entity "{entity_name}".

## Gold-standard example for this archetype
{example_schema_json}      # full JSON, in fenced block

## Your task
Emit a Page schema for entity "{entity_name}" / page-type "{page_type}".
Follow the example's level of richness. Use real token refs.
{entity-specific context: fields, relations, workflows}
```

### 5.6 Validation + retry

Existing loop (in `_generate_page_schema`):

1. Build prompt → call LLM.
2. Extract JSON via brace-matching parser.
3. Validate via Zod subprocess against PageV2.
4. **New:** Validator subprocess loads `tokens.custom.json` and `defaultTokens`; rejects schemas referencing token paths not present in either.
5. On failure, append the error to the prompt and retry (up to 2 retries).
6. On final failure, return `_minimal_schema()` (a valid v2 schema with empty Stack).

Telemetry: log `% of refs that were invalid` per call. If a generation hits `>50%`, fail fast with a clear error ("design context isn't reaching the LLM correctly") instead of retry-looping.

### 5.7 Cost / latency impact

Prompt grows by ~1500 tokens per call (rationale + token paths + gold example). At Sonnet 4 input pricing, ~$0.005 extra per page. For a 4-entity app (12 schemas), ~$0.06 total. Latency unchanged at this prompt size.

### 5.8 Tests

`backend/tests/services/test_schema_prompt.py`:

1. Prompt builds with all four inputs present — snapshot.
2. Missing design-spec → prompt valid, uses defaults.
3. Missing tokens.custom.json → uses defaultTokens paths.
4. Archetype lookup — known archetype loads its example.
5. Unknown archetype → falls back, logs warning.
6. Token paths in prompt match `defaultTokens` exactly (CI gate).

`backend/tests/services/test_schema_examples.py`:

1. Every gold example parses as a valid PageV2 — CI gate.
2. Every gold example references only registered library components.
3. Every gold example uses only token paths in `defaultTokens`.
4. Every token ref in every gold example terminates at a leaf path (regex check).

## 6. Editor support (`packages/editor`)

The schema editor handles arbitrary registered components — new types like `Hero`, `MetricTile` show up in the Palette automatically. Targeted work needed for StyleSlot editing and Custom-block UX.

### 6.1 StyleSlotEditor in Properties panel

A collapsible "Style" group at the bottom of every node's Properties panel. Always visible — every node accepts StyleSlot.

```
▾ Style
  Background  [Gradient ▼]
    from   [tokens.color.primary.50  ▼]   ◀─ TokenPicker scoped to color
    to     [tokens.color.surface.0   ▼]
    angle  [135°]
  Padding  [tokens.spacing.semantic.section ▼]
  Radius   [tokens.radius.lg ▼]
  Shadow   [tokens.shadow.md ▼]
  Motion   [Fade in ▼]
```

Sub-controls:

- `<TokenPicker scope="color|spacing|radius|shadow|typography" />` — autocomplete dropdown over tokens in the requested scope. Shows resolved value as preview (color swatch / size example). Reads from editor store's `theme`.
- `<BackgroundEditor />` — switcher for the four `Background` discriminated-union variants.
- `<MotionEditor />` — enum select.

State changes flow through the existing mutation pipeline — undo/redo, dirty tracking, save flow all work without modification.

Files:
- `packages/editor/src/panes/Properties/StyleSlotEditor.tsx` (new)
- `packages/editor/src/panes/Properties/style/{TokenPicker, BackgroundEditor, MotionEditor}.tsx` (new)
- `packages/editor/src/panes/Properties/Properties.tsx` (modified — invokes StyleSlotEditor after node-specific props)

### 6.2 Custom block UX

Three editor states:

| State | Display |
|---|---|
| Default | Labeled overlay box — "◇ Custom block — `<label>`". Inside: sanitized HTML rendered live. Below: `[Edit HTML]` `[View Tailwind]` buttons. |
| Edit drawer open | Side drawer: Label field + HTML textarea + Tailwind-classes textarea + Save/Cancel. |
| Selected/dragging | Standard selection outline / drag handles, same as any other node. |

Files:
- `packages/editor/src/panes/Canvas/CustomNodePreview.tsx` (new) — overlay + sanitized inner HTML.
- `packages/editor/src/panes/Properties/CustomEditor.tsx` (new) — drawer with text fields.
- `packages/renderer/src/runtime/dispatch.tsx` (modified) — explicit `case "Custom"` before unknown-fallback.

Sanitization: `dompurify` v3 with default config. Trusted HTML is not a goal.

### 6.3 Palette grouping

Extend `LibraryCategory`:

```ts
export type LibraryCategory =
  | "interactive" | "form" | "static" | "data" | "feedback"
  | "navigation" | "layout" | "motion" | "custom";
```

The Palette renders one section per category in the IREditor-style 2-column grid. New categories appear automatically as components are registered.

### 6.4 Drag-drop validation (`dnd/validate-drop.ts`)

Constraints enforced at drop time (red drop indicator + tooltip on rejection):

| Component | Constraint |
|---|---|
| `Tabs` | Children index matches `tabs[]` index. Drop at index `i` becomes the panel for tab `i`. |
| `Split` | Exactly 2 children. |
| `Sidebar` | Exactly 2 children. |
| `Form` | Children must be input nodes or structural primitives. |
| `Custom` | No children allowed. |

Tabs uses indexed-children (no separate `TabPanel` node) for v1 simplicity.

### 6.5 Tests

- `packages/editor/tests/panes/StyleSlotEditor.test.tsx` — renders for any node, switcher emits correct mutations, scope filter works, motion enum applies.
- `packages/editor/tests/panes/CustomEditor.test.tsx` — HTML round-trips through save/load, sanitization strips `<script>`, drag/select still works.

### 6.6 Out of scope for v1

- Monaco / syntax-highlighted editor for Custom blocks (plain textarea is fine).
- Live preview of theme changes in the Theme pane.
- Visual gradient picker (hue wheel etc.) — two TokenPickers + angle slider.
- Component-variant-specific property forms — Zod-driven properties panel handles all of them.

## 7. Backwards compatibility & rollout

### 7.1 Library backwards compat

- Every existing component's `Props` schema gets `style: StyleSlot.optional()` appended. Schemas without `style` keep validating.
- Each existing component's render path adds `<div style={{...resolveStyle(props.style), ...existing}}>`. Identical output when `style` is absent.

Net: any v1 schema renders identically post-upgrade. v2 schemas get the new capabilities.

### 7.2 Existing projects

| Scenario | Path |
|---|---|
| Brand-new project | Pipeline runs all new layers; output is high-fidelity from generation 1. |
| Existing project (cheap upgrade) | `POST /api/_debug/recompile-tokens/{short_id}` — runs `design_compiler`, writes `tokens.custom.json`. No LLM cost. Existing v1 schemas immediately look domain-tuned via the upgraded `defaultTokens` + custom merge. |
| Existing project (full re-do) | `POST /api/_debug/regen-schemas/{short_id}` (existing endpoint, extended) — re-runs schema agent with new prompt, produces v2 schemas. ~10 min for a 4-entity app. |
| Manual upgrade in editor | Open a v1 schema → auto-migrates to v2 on save. User dresses with StyleSlot manually. No regen cost. |

### 7.3 Foundation template

No template changes required. `theme/tokens.server.ts` already merges defaults + custom. `compileTokens` already runs at `<html style>`. `runtime_injector` already copies `src/theme/tokens.custom.json`. The new pipeline writes into a path the template already reads.

New library components ship via the existing workspace `file:` reference. `npm install` in the project picks them up on next regen.

### 7.4 Editor backwards compat

The editor opens any v1 or v2 schema. v1 schemas show StyleSlot panel populated with empty defaults — the user can click in and start dressing. The existing API client already supports both load shapes via `migratePage`.

### 7.5 Feature flag

Single env flag `FIDELITY_MODE_ENABLED` (defaults `true` once shipped). When `false`, pipeline uses the existing schema-mode path: no design-compiler step, no enriched prompt. One-flag rollback.

### 7.6 Merge order

1. `defaultTokens` refactor + snapshot test.
2. `@tentoroforge/schema` v2 + `migratePage`.
3. `@tentoroforge/library` 20 new components + StyleSlot resolver.
4. `services/design_compiler.py` + tests.
5. Pipeline integration in `_run_relay_pipeline` (compiler step + enriched prompt).
6. Gold-standard examples + `services/schema_prompt.py` rewrite.
7. Editor: StyleSlot panel + Custom-block UX.
8. Debug endpoints (`recompile-tokens`).
9. Documentation.

Step 1 is independent. Steps 2-3 are coupled. Steps 4-5-6 are coupled. Step 7 depends only on 2. Steps 8-9 finish.

## 8. Risk register

| Risk | Mitigation |
|---|---|
| LLM emits invalid token refs systemically (en masse) | (a) Token paths in prompt auto-generated from `defaultTokens` — same source of truth as validator, no drift possible. (b) CI lints every gold example for leaf-terminated token refs. (c) Validator rejects unknown paths; retry loop appends error. (d) `>50%` invalid-ref rate per call fails fast with clear error rather than retry-looping. |
| Color ramp generation produces ugly stops for unusual anchor colors | Lightness curve matches Tailwind's, well-tested. Snapshot tests cover healthcare-green and fintech-purple anchors. |
| `dompurify` over-strips legitimate HTML in Custom blocks | Pin to v3, document the allow-list. Expand config explicitly when legitimate cases hit. |
| Gold examples drift from library reality | CI test enforces every gold example parses against current v2 schema and references only registered components. |
| Performance — `resolveStyle` on every render | `useMemo` per node. Negligible cost. |
| TokenPicker overwhelms users with hundreds of paths | Group by scope; show 12-15 most-used in primary list, rest under "more". |

## 9. Success criteria

- Brand-new generation against a fintech prompt produces a project where:
  - `tokens.custom.json` exists and contains a full token tree derived from the planner's design-spec
  - Every page schema is `schemaVersion: "2"` and uses StyleSlot in at least one place per page
  - Hero or Section appears on at least 1 page (typically the dashboard or detail page)
  - Form pages use real Input/Select/Textarea/Checkbox/DatePicker nodes (not placeholders)
  - The rendered preview shows domain-appropriate colors, typography, spacing density without manual edits
- Existing project's `recompile-tokens` endpoint applies the new tokens to v1 schemas and produces a visually-different output.
- The Schema Editor opens any v1 or v2 schema, renders correctly, and lets the user dress nodes with StyleSlot.
- Drag-drop in the Palette adds new components; constraints reject invalid drops with clear feedback.
- `FIDELITY_MODE_ENABLED=false` reverts to current schema-mode behavior identically.

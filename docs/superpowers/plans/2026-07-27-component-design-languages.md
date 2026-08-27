# Component Design Languages — the aesthetic axis

**Problem (user-verified on 3 real generations):** shells, palettes, fonts and page
compositions now vary per app, but every app still renders the SAME component
language — bordered white cards, left-accent KPI tiles with ALL-CAPS labels and
delta carets, one button shape, one callout style. Users read them as one product.

**Fix:** a per-app DESIGN LANGUAGE — a named, coherent visual movement that
restyles *how components are drawn*, not just their colors. Sources: IxDF "Top 10
UI Trends", the 22-type UI taxonomy (user-supplied), plus product references
(Linear / Stripe / Mercury / Ramp / Notion class).

Deterministic, seeded, CSS-only (no images, no new components): emitted into the
generated app's `globals.css` as a `/* tentoro:language */` block targeting stable
library hooks, plus a few builder-level prop choices. Every language must keep
WCAG AA text contrast (the neumorphism caveat from IxDF is handled by applying
relief to SURFACES only — text contrast never drops).

---

## The 10 languages

Axes each language must define: canvas · card · stat/KPI anatomy · button system
· input · table voice · callout · edges · motion · one signature detail.

### 1. `flat-bold` — Flat 2.0 × color blocking
- Canvas: flat, saturated section blocks allowed
- Cards: NO shadow, 2px solid borders, zero-to-4px radius
- Stat: borderless number block on tinted color field, label sentence-case bold
- Buttons: chunky solid rectangles, high-contrast, bold label
- Inputs: 2px outline, square
- Table: heavy header rule, no zebra
- Callout: solid tinted band, no border
- Signature: color-blocked page header band
- Fits: education, consumer, creative, commerce

### 2. `material-soft` — layered depth
- Canvas: light gray, elevation hierarchy
- Cards: shadow levels (sm cards / lg modals), radius 8–12px, NO borders
- Stat: floating tile, icon in tinted circle, delta pill
- Buttons: filled rounded 8px + text-buttons, subtle hover raise
- Inputs: filled surface with underline focus
- Table: white on gray canvas, hover elevate
- Callout: elevated card with leading icon
- Signature: primary action as prominent pill
- Fits: healthcare, hr-people, default-saas

### 3. `soft-ui` — accessible neumorphism
- Canvas: single tinted hue field (e.g. 220 20% 94%)
- Cards: extruded from canvas via dual shadows (light top-left, dark bottom-right), radius 14px, no borders
- Stat: soft-relief tile, number engraved-large, label small muted (text stays ≥AA!)
- Buttons: pill, soft-raised; pressed = inset shadow
- Inputs: inset (sunken) fields
- Table: row separation by soft grooves, not lines
- Callout: inset well
- Signature: everything monochrome-tinted; accent used ONLY on primary action
- Fits: wellness, consumer-warm, education

### 4. `glass` — glassmorphism
- Canvas: vivid gradient or deep tinted backdrop (fine grid/globes ok)
- Cards: translucent (`rgba(255,255,255,.55)` light / `.08` dark) + `backdrop-filter: blur(14px)`, 1px white/20 border, radius 16px
- Stat: glass tile, oversized numeral, thin label
- Buttons: solid primary pops against glass; secondary = glass chip
- Inputs: glass fields with bright focus ring
- Table: glass panel, hairline white dividers
- Callout: brighter glass w/ accent edge
- Signature: layered translucency = depth without shadows
- Fits: creative, fitness (dark), travel/hospitality, fintech-consumer

### 5. `editorial` — typography-centric / print
- Canvas: paper white/cream, NO card chrome at all
- Cards: none — sections divided by 1px rules + whitespace; headings carry hierarchy
- Stat: bare oversized serif numeral + small-caps label, hairline underline
- Buttons: text-underline links; primary = thin-outline rectangle, sharp
- Inputs: underline-only fields
- Table: print table — double top rule, hairline rows, generous leading
- Callout: indented block with left rule, italic
- Signature: drop-cap-ish page headers, numbered section eyebrows ("01 — Matters")
- Fits: legal, editorial/media, consulting, luxury services

### 6. `neo-brutal` — softened brutalism
- Canvas: off-white, stark
- Cards: 2px near-black borders, ZERO radius, hard offset shadow (4px 4px 0 ink)
- Stat: boxed tile w/ hard shadow, mono numerals, label UPPERCASE mono
- Buttons: hard-bordered blocks; hover shifts shadow (translate)
- Inputs: thick square outlines
- Table: visible grid lines both axes
- Callout: black band, white text
- Signature: intentional rawness; tags look like stamps
- Fits: developer tools, internal ops, analytics (bold flavor)

### 7. `luxe-ink` — quiet luxury (Mercury/art-deco hints)
- Canvas: warm paper or deep ink (dark variant)
- Cards: hairline (0.5–1px) borders at 12% ink, radius 6px, shadow only on overlays
- Stat: small-caps letter-spaced eyebrow label, thin large numeral (font-weight 300–400), NO tile box — column w/ hairline left rule
- Buttons: slim rectangles, letter-spaced uppercase labels, brass/gold accent
- Inputs: hairline underline, elegant focus
- Table: hairline rows, right-aligned numerals, tabular figures
- Callout: thin-bordered note w/ small-caps title
- Signature: geometric deco corner tick on primary card
- Fits: legal, hospitality/estates, wealth/fintech-private, architecture

### 8. `neon-tech` — retro-futuristic dark
- Canvas: near-black, faint grid, vignette
- Cards: #101418-class panels, 1px borders that GLOW on hover (accent box-shadow), radius 8px
- Stat: numeral in accent color w/ subtle glow, sparkline hint, mono type
- Buttons: solid accent (ink label per contrast rule) + ghost w/ glowing border
- Inputs: dark inset, accent focus glow
- Table: dark zebra, accent row-hover edge
- Callout: accent-bordered dark panel
- Signature: gradient text on the page h1 only
- Fits: fitness, gaming, dev/infra (dark draw), crypto

### 9. `mono-tonal` — monochromatic tone-on-tone
- Canvas: hue tint 97%
- Cards: NO borders/shadows — separation purely by tone steps (94% / 90% wells)
- Stat: tone-block tile, darkest-shade numeral
- Buttons: solid darkest shade; secondary = mid-tone; everything same hue
- Inputs: tone-well fields
- Table: tone-banded header, tone hover
- Callout: deeper tone well
- Signature: literally one hue everywhere; grayscale neutrals forbidden
- Fits: analytics, b2b saas, portfolio-grade tools

### 10. `paper-vintage` — minimal vintage
- Canvas: cream #f7f3ea-class, slight warm sepia neutrals
- Cards: 1px warm-gray borders, radius 4px, tiny paper shadow
- Stat: ledger-style — numeral in old-style serif, underlined twice (double rule)
- Buttons: stamp-like bordered rectangles, muted ink fills
- Inputs: boxed w/ warm borders
- Table: ledger rules, alternating cream rows
- Callout: "note" card w/ dotted border
- Signature: dotted dividers, date-stamped list rows
- Fits: hospitality, crafts/consumer, bookkeeping, community

---

## Selection model

New DNA axis: `dna["language"]` — seeded pick from the archetype's allowed set
(2–4 languages per archetype, domain-appropriate), dossier can override
(e.g. paletteCharacter "dark neon" → neon-tech; "editorial serif" → editorial).

| Archetype | Languages (seeded pick) |
|---|---|
| fintech | luxe-ink · material-soft · mono-tonal |
| healthcare | material-soft · soft-ui · flat-bold |
| consumer-warm | soft-ui · paper-vintage · flat-bold |
| legal | editorial · luxe-ink · paper-vintage |
| creative | glass · flat-bold · neo-brutal |
| developer | neo-brutal · neon-tech · mono-tonal |
| logistics | flat-bold · neo-brutal · material-soft |
| education | flat-bold · soft-ui · material-soft |
| hospitality | luxe-ink · paper-vintage · glass |
| hr-people | material-soft · soft-ui · flat-bold |
| commerce | flat-bold · material-soft · mono-tonal |
| industrial | neo-brutal · flat-bold · mono-tonal |
| analytics | mono-tonal · neon-tech · luxe-ink |
| fitness | neon-tech · glass · neo-brutal |
| default-saas | material-soft · mono-tonal · luxe-ink · flat-bold |

Combined with existing axes (palette hue, 18 font pairings, 5 chromes, 6 dashboards,
4 lists, 4 details, 4 forms, brand name, voice) the language axis multiplies the
identity space by ~10 and — critically — changes the thing users actually touch:
tiles, cards, buttons, edges.

## Implementation (pending hook map from the anatomy agent)

1. `LANGUAGES` spec table + `_archetype languages` in `design_dna.py`;
   `dna["language"]` seeded; forwarded to design-spec + prompt briefs.
2. `to_component_css(dna)` — emits the language's component rules into
   `/* tentoro:language */` markers in globals.css (idempotent), selector
   strategy per the anatomy agent's cascade findings (library hooks / data
   attributes / utility-beating specificity).
3. Builder prop variance where components already support it (Card elevation,
   Table striped/density, Button variant) keyed off the language.
4. Auth/login page + shell rails pick up the language tokens (glass panels,
   hairline luxe, brutal borders) via the same CSS.
5. Retrofit all 4 live apps to 4 DIFFERENT languages as visual proof.
6. Monte-Carlo + tests + BLUEPRINT §31.4 + push.

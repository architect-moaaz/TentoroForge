# Register catalog — reliable Wildflower-grade design across every domain

**Author:** m
**Date:** 2026-08-11
**Status:** Draft for review

## Problem

The generation pipeline produces apps that are engineered well but designed poorly. Live evidence from `output/tr7rfk34/` (Wellness Studio):

- Design agent picked a "brutalist / graph-paper" skin (`data-skin="lang11df8c56"`) for a brief whose register was `kinetic_calm / body_forward / warm_precise / soft_8 / spacious_for_touch`. Every rule in the LLM-authored skin CSS fought the register.
- Same skin set `font-size: 0px` on nav items, collapsing all TopBar labels.
- Same skin forced `grid-template-columns: repeat(4, 1fr) !important`, breaking layout on smaller screens.
- Recipe picker attached `member_home` to `/admin`, `/login`, `/signup`, `/*/[id]` — 12 wrong routes on one app.
- Palette derived from `#4A7C6F` gave the right primary, but accent slot fell back to a template-default orange the brief never asked for.

Root cause is not any one bug. It is architectural: **the LLM invents visual identity from scratch for every app.** LLMs are inconsistent inventors and superb pickers. Every generation, Claude authors CSS, chooses fonts, picks accent hues, and composes skin blocks — and regresses to the same 5 "AI-safe" defaults (warm cream + serif + terracotta, dark ground + acid green, purple-blue gradient hero, brutalist grid-paper, cool-tech monospace).

To reach Wildflower-grade reliably, the pipeline must ask the LLM to **pick from a small hand-designed catalog of complete design languages**, not invent one.

## What is a "register"

A **register** is a complete, hand-authored design language: not a color theme, not a skin CSS block, but the full set of decisions that make an app feel like it was designed by a person.

Each register ships:

- **Palette recipe** — a chord (analogous / split-complementary / triadic / duotone) that accepts a single brand hue and produces a full harmonic palette (primary, accent, surface-base, surface-elevated, foreground, muted, border, ring, semantic success/warning/error/info, plus a dark-mode mirror).
- **Typography pairing** — display face + body face + optional utility face, with weight scale, letter-spacing rules per level, italic/small-caps behavior. Ships as an `@font-face` block plus CSS custom properties.
- **Shape system** — border-radius scale (sharp / soft / round), density (compact / comfortable / spacious), elevation (flat / bordered / layered / floating), border-weight (hairline / medium / bold).
- **Motion vocabulary** — three durations, one easing curve, plus register-specific micro-interactions (button press-scale, card hover-lift, page-load reveal).
- **Signature move** — one visual moment that anchors the identity (a hero photo treatment, a large serif h1 with tucked-under paragraph, a monospace stat block, a warm-neutral illustrated empty state).
- **Chrome recipe** — SideNav vs TopBar vs Dock decision + how it's painted; NOT another `data-skin` CSS block, but structured chrome props the shell renderer honors.
- **Component treatment** — which library variants map to this register (Card.editorial vs Card.linear vs Card.workday), and per-component styling deltas.
- **Illustration + icon language** — which of the ~4 illustration families and ~8 icon families this register uses.
- **Domain fit rules** — which briefs this register is allowed to match (register↔register-hint matrix in the DesignBrief).

Registers are **complete looks**. Two apps that pick the same register look like they're from the same brand family; two apps that pick different registers look like different products by different studios.

## Contrast with today

Today the pipeline has:

- ~4 typography registers (`typography_registers.py`) covering only font family choice.
- ~5 chrome variants (WideRail, IconRail, DockNav, TopNav, standard-rail) in `(dashboard)/layout.tsx` — good structural variety, but each accepts LLM-authored paint props with no rules.
- Component `.linear` / `.stripe` / `.notion` / `.workday` / `.figma` variants exist for MetricTile/Card/Hero — hand-authored, but never wired to a register decision. The library picks whichever variant matches the schema; the design agent doesn't pick a register and pass it down.
- LLM-authored skin CSS injected as free-form `/* tentoro:skin */` block that can (and does) set `font-size:0`, `!important` grid overrides, hard offset shadows.

We have the *ingredients* of registers scattered across the codebase but no register *concept* that binds them. The design agent still invents.

## The initial catalog — 8 registers

Not aspirational; enough to cover the domains we generate today with distinctiveness. Each one ships as a **complete look** (per the shape above), not a color swap.

| # | Register | Feels like | Domain fits | Signature move |
|---|---|---|---|---|
| 1 | `editorial-serif` | Print magazine, Wildflower vibe | wellness, hospitality, boutique retail, food, publishing | Warm-neutral ground, large Fraunces display, tucked lede paragraph, hero photo with generous margin |
| 2 | `warm-consumer` | Airbnb / Notion for consumers | booking, marketplace, subscription, community | Rounded cards with soft shadow, friendly sans (DM Sans), photo-forward hero |
| 3 | `kinetic-technical` | Linear, Vercel dashboard | developer tools, monitoring, data-heavy ops | Deep neutral ground, mono numerics, thin dividers, animated reveals |
| 4 | `data-dense` | Stripe / Workday | finance, ops, ERP, admin-heavy | Tabular numerics, compact density, subtle color coding, quiet chrome |
| 5 | `wellness-airy` | Calm, meditation apps, spa | health, fitness, therapy, personal wellness | Wide margins, soft duotone illustrations, breathable line-height, quiet colors |
| 6 | `warm-professional` | Modern law/consulting firm | professional services, B2B services, healthcare admin | Serif h1 + sans body, muted brand + confident accent, credential-forward |
| 7 | `playful-bold` | Duolingo / gaming | education, kids, gamified habits, entertainment | High-saturation palette, rounded chunky shapes, mascot illustration slot |
| 8 | `brutalist-editorial` | Grid-paper, punk-editorial | portfolios, creative tools, indie publications | Hard hairline borders, mono display, exposed grid, offset accents |

The wellness studio would clearly pick `wellness-airy` (or `warm-consumer` if it leans booking-forward), never `brutalist-editorial`. The register↔brief compatibility matrix (see [Selection](#selection)) makes that mechanical.

## Register schema

A register ships as a Python module + a CSS partial + component overrides. Concrete shape:

```
backend/services/registers/
  __init__.py                  # register registry (name → module)
  base.py                      # Register dataclass + shared helpers
  editorial_serif/
    __init__.py                # Register instance
    palette.py                 # palette_from_brand(hex) -> Palette
    typography.py              # pairing + scale
    shape.py                   # radius/density/elevation
    motion.py                  # durations, easing, micro-interactions
    signature.py               # returns the schemaVersion:"2" node for the hero move
    chrome.py                  # chrome recipe (frame + paint rules)
    components.py              # per-component overrides (Card, MetricTile, Hero, ...)
    illustration.py            # illustration family key + palette
    domain_fit.py              # allowed briefs (register hints, register keywords)
    css/
      base.css                 # register root vars + typography + reset extensions
      components.css           # component-scoped overrides (data-register selectors)
```

Every register implements:

```python
@dataclass(frozen=True)
class Register:
    key: str                              # "editorial_serif"
    display_name: str                     # "Editorial Serif"
    palette_from_brand: Callable[[str], Palette]
    typography: TypographyPairing
    shape: ShapeSystem
    motion: MotionVocabulary
    signature_move: Callable[[dict], dict]  # (brief) -> schema node
    chrome: ChromeRecipe
    component_overrides: dict[str, ComponentOverride]
    illustration_family: str              # "warm-editorial" | "duotone-nature" | ...
    icon_family: str                      # "lucide-editorial" | "phosphor-warm" | ...
    domain_fits: DomainFitRules
```

The output of a register is a **fully-populated design-spec.json** with no gaps for the LLM to fill in. The design agent's job shrinks to selection + one call to `apply_register(register, brief)` → `design-spec`.

## Selection

The design agent picks a register in three steps:

1. **Hard filter by register hint on the brief.** `DesignBrief.identity.register_hints: list[str]` becomes the primary signal. If discovery yields "warm, editorial, spacious, magazine-like" → shortlist is `editorial-serif`, `warm-professional`.
2. **Compatibility matrix by domain + register.identity signals.** Every register declares which combinations of `brief.identity.register` values, `brief.layout.density`, `brief.motion.motionLevel`, and `brief.identity.domain` it accepts. Incompatible registers are hard-filtered.
3. **Judge panel over the shortlist.** For each remaining register, render a `preview-card` (register name + 3-line description + swatch of the palette that brand hex would produce + a signature-move thumbnail) and ask a critic-LLM to score fit. Ship the winner.

The picker never invents CSS. When no register matches, ship the closest one plus a critic warning; do NOT fall back to LLM-authored skin.

The register decision lands on the brief as `brief.register_key: str` and is authoritative — no downstream pass can override it.

## Rendering

At generation time:

1. `apply_register(register, brief)` produces the full `design-spec.json` — palette, typography, shape, motion, chrome, register key.
2. Register's `css/base.css` copies into `output/<app>/src/app/globals.register.css` and is imported after `globals.css`.
3. Component overrides land as `[data-register="editorial-serif"] [data-card]` selectors in `css/components.css`.
4. The generated app's `layout.tsx` stamps `<html data-register={spec.register_key}>` on the root so every register override targets it.
5. `signature_move(brief)` returns a schema node that gets placed on the app's designated hero page (dashboard or a domain-canonical hero route).
6. `_rewrite_globals_root` still runs — it now reads register-derived tokens instead of LLM-authored palette.
7. LLM-authored `data-skin=…` skin blocks are **removed** from the design agent's output. The register IS the skin now.

## Migration

The existing LLM `_write_skin_block` path is the biggest risk. Migration in three waves:

**Wave 1 — behind flag.** `FORGE_REGISTERS=on` enables register selection; off keeps today's LLM path. Ship 3 registers first (`editorial-serif`, `wellness-airy`, `data-dense`) and pick only on matching briefs; other briefs still take the LLM path.

**Wave 2 — flag defaults on.** Once 3 registers are stable, flip default. LLM path becomes fallback for briefs no register matches.

**Wave 3 — delete LLM skin.** Once all 8 registers ship and 30 consecutive generations pick a register, delete `_write_skin_block` and the `/* tentoro:skin */` marker block from the design agent output. Keep the marker as a rejection signal in the critic (any skin block that reappears = regression).

## Rollout phases + estimates

**Phase 0 — infrastructure (1 week, engineering).**

- `services/registers/base.py` — Register dataclass, ChromeRecipe, ComponentOverride shapes.
- `services/registers/__init__.py` — registry + loader.
- `services/registers/pick.py` — 3-step selection logic.
- `agents/design_agent.py` — `apply_register(register, brief) → design-spec` path.
- `app_emitter.py` — copy `css/base.css` + `css/components.css` into generated app, wire `data-register` on `<html>`.
- Tests: registry loading, picker filters, apply_register determinism.

**Phase 1 — first three registers (2 weeks, 1 designer + 1 engineer).**

- `editorial-serif` — designed for the wellness/hospitality/boutique bucket.
- `data-dense` — designed for finance/ops/ERP.
- `warm-consumer` — designed for marketplace/booking/community.
- Each register: palette recipe + type pairing + shape + motion + one signature move + chrome recipe + component overrides + illustration + icon family + domain fit rules + tests.
- Live acceptance: regenerate 3 fixture apps (yoga studio, invoicing tool, marketplace) with `FORGE_REGISTERS=on` and confirm each app looks distinctly different, palette-harmonic, and register-appropriate.

**Phase 2 — critic hardening (1 week, engineering).**

- Extend design critic with register-mismatch rules (this is what task #595 delivers).
- Reject any generation where the LLM path emits a skin block despite a register being selected.
- Judge-panel implementation for register selection (reuses the existing judge-panel pattern).

**Phase 3 — remaining five registers (3-4 weeks, 1 designer + 1 engineer, parallel batches of 2).**

- `kinetic-technical`, `wellness-airy`, `warm-professional`, `playful-bold`, `brutalist-editorial`.
- Same shape as Phase 1 per register.

**Phase 4 — deprecate LLM skin (1 week, engineering).**

- Ship register-first pipeline default-on.
- Remove `_write_skin_block` after 30 clean generations.
- CI grep-guard: no `/* tentoro:skin */` blocks in generated apps.

**Total: ~8 weeks with 1 designer + 1 engineer working in tandem.** The designer's time is concentrated in Phases 1 and 3 — palette recipes, typography scholarship, and signature-move authoring. The engineer's time is Phases 0, 2, and 4 plus paired work with the designer on each register's CSS.

## Who does what

**Designer (Wildflower-grade person, non-negotiable):**

- Authors the initial 8 register looks — palette recipes, type pairings, spacing rhythm, motion voice, signature move for each.
- Curates the illustration + icon families (~4 illustration languages, ~8 icon families).
- Reviews live output of each register on 3+ fixture apps before it's declared shippable.
- Owns the register catalog forever — additions/edits are their call.

**Engineer:**

- Ships the register framework (Phase 0).
- Translates designer's specs into `Register` instances + CSS partials.
- Wires selection, apply, rendering, migration flag.
- Ships critic-with-teeth rules for register mismatches.
- Owns the CI grep-guards.

**LLM:**

- Reads the brief and register catalog descriptions, picks 3 candidates.
- Judge-panel scores fit; winning register wins.
- Never authors CSS again.

## Concrete first-register example — `editorial-serif`

To make this concrete, here's what the first register ships:

**Palette recipe** — accepts one brand hue. Chord: analogous with muted split-complementary accent.

- primary: `hsl(H, 45%, 32%)`
- accent: `hsl((H+40) % 360, 55%, 55%)`
- surface-bg: `hsl(H, 12%, 96%)`  (warm neutral, brand-tinted)
- surface-elevated: `hsl(H, 8%, 99%)`
- foreground: `hsl(H, 25%, 12%)`
- muted: `hsl(H, 15%, 42%)`
- border: `hsl(H, 10%, 85%)`
- dark-mode mirror: derived by inverting L in HSL, adjusting S.

**Typography** — Fraunces display (700, italic-capable) + Inter body (400/500) + Fraunces small-caps for labels.

- H1: `text-[64px] leading-[1.05] tracking-[-0.02em] font-fraunces font-normal italic`
- Body: `text-[17px] leading-[1.65] font-inter`
- Labels: `text-[11px] tracking-[0.14em] font-fraunces small-caps uppercase`

**Shape** — radius soft_8, density spacious_for_touch, elevation layered, border hairline.

**Motion** — 220ms default, `cubic-bezier(0.2, 0.7, 0.1, 1)`; page-load reveal is a 400ms opacity+translateY fade of the hero.

**Signature move** — a warm-neutral hero band spanning the top of the page: large italic Fraunces H1, tucked-under 65-char paragraph in Inter, right-aligned photo with 32px offset shadow, wide top/bottom margin.

**Chrome** — WideRail (272px) painted in warm-neutral, active pill uses accent at 15% alpha, group labels in small-caps.

**Component overrides** — Card gets `bg-surface-elevated` + `border border-border/40` + `p-8`, no shadow. MetricTile gets no border, `pb-6 border-b border-border/30`, label in small-caps, value in Fraunces italic.

**Illustration family** — `warm-editorial-line` (Bruno Munari–style single-line illustrations in the accent hue).

**Icon family** — `phosphor-thin` (Phosphor icon set, thin weight, 1.5px stroke).

**Domain fits** — accepts briefs whose `identity.register` includes any of `warm_precise / kinetic_calm / body_forward / editorial_confident / gentle_authoritative`; whose `identity.domain` is in {wellness, hospitality, boutique_retail, food, publishing, personal_services}; whose `layout.density` is `spacious` or `spacious_for_touch`; whose `layout.radius` is `soft_8` or `soft_12`.

That single register — implemented completely — should make every wellness/hospitality/publishing brief we generate look meaningfully like Wildflower work.

## Acceptance criteria

The register catalog work is done when:

1. Regenerating `tr7rfk34` (wellness studio) picks `wellness-airy` or `editorial-serif` and ships without any per-app patches. All 5 tr7rfk34 patches (rhythm shim, skin muting, admin rewrite, globals rewrite, empty-state props) become unnecessary.
2. Regenerating an ops/finance brief picks `data-dense` and looks like Stripe/Workday, not the wellness studio.
3. Regenerating a booking marketplace picks `warm-consumer` or `editorial-serif` and looks like Airbnb, not the wellness studio.
4. Design critic rejects and retries any generation where the picker's top register scores below 0.7 on judge-panel fit.
5. Zero `/* tentoro:skin */` blocks in any generated app.
6. Zero `-rhythm-*` classes in the library source (task #597 already delivered this guard).
7. A designer can add a 9th register to the catalog in ≤2 days without touching pipeline code.

## Open questions

1. **Do we ship 8 registers or start with 3?** Recommend 3 (Phase 1) → validate the framework → ship the rest. But the 8 need to be *chosen* upfront so the taxonomy is coherent.
2. **Who is the designer?** External hire vs internal? A great one is expensive but the leverage is enormous (8 weeks of one designer's work anchors design quality forever).
3. **Font licensing.** Fraunces, DM Sans, Inter, JetBrains Mono are OFL/SIL — fine. But `warm-consumer` may want a specifically licensed face (Söhne, Tiempos). Budget question, not architecture.
4. **Illustration + icon families.** Building or licensing? ~$5–15k licensing cost per family or 2-4 weeks per family in-house.
5. **What breaks under Wave 3 (LLM skin delete)?** Any generation for a brief the register catalog doesn't cover has to pick the closest register + surface a critic warning. Acceptable for common domains; risky for edge domains. Mitigation: keep the LLM path behind a `FORGE_LEGACY_SKIN=on` escape hatch until the catalog is proven wide enough.
6. **How does this interact with the composition recipe library?** Recipes decide *composition* (which anchors on a page, in what order); registers decide *look* (palette, type, shape, chrome). They're orthogonal. A recipe page reads the register's tokens and uses register's component overrides. No conflict.
7. **Reference-driven design (#389 infrastructure).** Where does that fit? Suggest: mood images can BIAS register selection (the judge-panel takes the mood image + register preview into account). Don't try to derive a register from an image directly — too unreliable.

## Non-goals

- Not building a design system marketplace. 8 authored registers is enough for every domain we generate; more comes later if needed.
- Not letting users customize a register per app. Registers are curated. Per-app customization is a Smith-follow-up feature (edit-brief-scoped palette tweaks) but must never override register decisions.
- Not eliminating the LLM. The LLM still picks the register, authors copy, chooses signature-move variant when multiple are available. It just stops inventing CSS.
- Not delivering full accessibility audit as part of this work. Registers ship with WCAG AA contrast tokens; anything beyond that is a separate spec.

## Immediate next step

Get sign-off on:

1. The 8-register taxonomy (are these the right buckets?)
2. Which 3 land in Phase 1 (recommend `editorial-serif`, `wellness-airy`, `data-dense`).
3. Designer resourcing.

Once signed off, Phase 0 (infrastructure) can start immediately; Phase 1 register work waits for designer availability.

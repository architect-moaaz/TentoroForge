# Compositional Design Engine — unlimited per-app design languages

## Why the fixed-list approach caps out

Round 5 shipped 10 named languages (GRID/STACK/PRESS/LINEN/BENTO/TERMINAL/DECO/
BLOCK/ATOMIC/AERO). That was the right architecture move — silhouette levers
finally live on the skin axis — but 10 is a *ceiling*. Generate 30 apps and
you see repeats.

**The fix: stop shipping languages. Ship a COMPOSER.**

Each app's language is composed at generation time by drawing one value from
each independent axis, constrained by a taste model so the result is always
coherent and premium. The named languages become *presets* (seed points), not
the whole space.

## Axis model

Independent axes, each with N implemented values:

| Axis | Values | Notes |
|---|---|---|
| `navShape` | 14 | rail-flush · rail-inset-floating · icon-only · icon+label-stack · topbar · topbar-centered · dock-bottom · right-rail · split (icon rail + context panel) · rail-with-hanging-rule · compartment-cells · color-bar-stack · numbered-index · outline-tree |
| `navAccent` | 8 | left-bar · full-bleed-invert · pill-fill · tint-fill · underline · chevron-flank · dot-marker · shadow-card |
| `kpiAnatomy` | 12 | boxless-hairline · shared-strip · compartment · plaque-chamfer · tint-block · bento-mixed · ledger-leaders · hero-asymmetric · capsule-soft · glass-ribbon · stacked-column · ruled-band |
| `kpiLabelPos` | 3 | above · below · inline |
| `cardTreatment` | 9 | none · hairline · thick-border · hard-offset · soft-shadow · layered-shadow · tint-fill · glass · rules-only |
| `radiusRegime` | 6 | 0 · 2 · 8 · 14 · 20 · pill-mixed · chamfer |
| `typeClass` | 8 | grotesque · humanist · geometric · rounded · mono · serif-display · condensed-caps · editorial-serif |
| `labelVoice` | 5 | allcaps-tracked · small-caps · sentence · lowercase · mono-caps |
| `densityRhythm` | 5 | dense(16/8) · tight(24/12) · standard(36/20) · airy(48/28) · editorial(72/32) |
| `headerTreatment` | 7 | plain · eyebrow-numbered · rule-under · masthead-double-rule · banded · accent-tab · centered-flanked |
| `gridRhythm` | 6 | 4-equal · 3-equal · 6-dense · asymmetric-2fr · bento-span · 2-equal |
| `motionSig` | 4 | none · instant · soft-fade · spring-press |

Raw combinations: 14×8×12×3×9×6×8×5×5×7×6×4 ≈ **1.8 billion**. Taste
constraints cut this to a coherent subspace, still effectively unlimited.

## Taste model (the part that keeps it premium)

Constraints expressed as rules, not enumeration:

1. **Coherence groups** — each axis value carries tags (`sharp`, `soft`,
   `technical`, `editorial`, `playful`, `luxe`, `organic`). A composition
   must share ≥2 tags across nav/kpi/card/type or it is re-drawn.
2. **Forbidden pairs** — e.g. `glass` card + `hard-offset` shadow;
   `mono` type + `pill-mixed` radius; `chamfer` radius + `soft-shadow`.
3. **One-loud rule** — at most ONE of {hard-offset shadow, gradient fill,
   full-bleed color bars, glow} per app. Prevents circus.
4. **Contrast floor** — every composed palette+skin pair re-validated for
   WCAG AA on text and filled controls.
5. **Archetype affinity** — each archetype weights tags (legal → editorial/
   luxe; devtools → technical/sharp; consumer → soft/playful) so the draw
   is domain-appropriate, never random.

## Distinctness guarantee

`design_signature(dna)` = tuple(navShape, kpiAnatomy, cardTreatment,
radiusRegime, typeClass). The composer rejects a draw whose signature
collides with a same-domain sibling (seeded from project id, so still
deterministic). Test asserts: 200 simulated apps → ≥95% unique signatures,
≥60% unique on any 3-axis subset.

## Implementation phases

1. **Research** (parallel agents): nav/header/topbar patterns; page-header +
   toolbar + KPI + card treatments; type/motion/texture "premium" details.
2. **AXES module** in design_dna: every value = a dict of CSS emitters.
3. **compose_language(archetype, seed)** → a language instance dict.
4. **to_component_css / to_nav_css** consume the instance, not a named skin.
5. Presets keep the 10 names as fixed compositions for back-compat + tests.
6. Simulate 200 apps, measure signature spread + run the greyscale metric.
7. Retrofit live apps, full sweep, BLUEPRINT §31.6, push.

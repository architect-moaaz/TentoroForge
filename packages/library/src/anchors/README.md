# Anchor components

Composition-library anchors — the vocabulary the planner cites and the renderer instantiates when `FORGE_COMPOSITION_RECIPES` is on.

## What an anchor is

An anchor is a **higher-level composition slot** than a primitive component. Where `Card`/`Table`/`Button` are raw pieces the LLM can arrange however it likes, an anchor is one slot in a named recipe — `pinned_moment_hero` is always at the top of a `member_home`, always has the same three copy slots (`eyebrow`, `headline`, `subhead`), always binds to one entity, always uses the `--color-surface-hero` and `--font-display` tokens.

The planner picks the anchors; the renderer instantiates by name. Compositional freedom lives in the recipe library (`backend/services/composition/recipes.json`), not in the LLM's per-page schema.

## Contract per anchor

Every anchor:

1. **Consumes design tokens only** — no hardcoded colors, no hardcoded fonts. `bg-card`, `text-foreground`, `var(--color-primary)`, etc. Same anchor renders different in every app because tokens differ.
2. **Takes a typed `props` object** matching its entry in `backend/services/composition/anchors.json` — same copy slots + binds declared there are the ones the component accepts.
3. **Renders sensible fallbacks** when data is missing — a skeleton row when a bound entity hasn't loaded, an empty-state hint when the query returned nothing.
4. **Is registered in `buildDefaultRegistry`** under the exact PascalCase name in `anchors.json`.

## Cross-package handshake

- Python side: `backend/services/composition/anchors.json` lists every anchor's contract.
- Runtime side: `packages/library/src/anchors/<AnchorName>/` implements it.
- Drift-guard test in `packages/library/tests/anchors-registry.test.ts` fails if either side drifts from the other.

## v1 anchor set

Slice 2 mode (b) — first recipe end-to-end. The 6 anchors of `member_home`:

- `PinnedMomentHero` — big top card, "the thing they came here for right now"
- `VitalsInContext` — 3 tiles showing progress/count/streak with contextual copy
- `ScanStrip` — 7-cell week or category strip for quick scanning
- `RecsRailReasoned` — horizontal card rail with a *why* for each recommendation
- `CommunityPulse` — activity feed of what other members are doing
- `StickyPrimaryCta` — floating primary action pinned to the viewport edge

Later slices expand across the other 259 anchors.

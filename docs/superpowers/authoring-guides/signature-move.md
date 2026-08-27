# Authoring guide — signature move

**Where they live:** inside a recipe's `recipe_signatures` array in `backend/archetypes/recipes.json`, and (for cross-recipe motifs) in `backend/signature_moves/catalog.json`.
**Read first:** the existing `recipe_signatures` on `catalog`, `kanban`, `checkout`, `chat_with_agent` — they are the tone.

A signature move is a **short kebab-case tag naming a specific visual or interaction motif** the recipe is expected to earn — `"typing-indicator"`, `"pulsing-scan-orb"`, `"streaming-cursor"`, `"pull-to-refresh"`. The design agent reads these tags and is nudged to make the LLM-authored schema *actually contain* the motif; the critic checks whether the motif landed. Together they turn "make it feel like a chat" from vibes into a checkable list.

## When to add one

- A recipe consistently ships without a motif that separates the good version from the generic version. ("Every player looks like a static form because no one ever specified `transport-controls`, `waveform-scrub`, `queue-drawer`.")
- The gap review flagged repeated visual boredom around a recipe.
- You're adding a new recipe and it needs 2–5 characteristic moves out of the gate.

Do NOT add:
- Component names — those go in `component_set`. `"NavLink"` is not a signature move; `"active-link-underline-slide"` is.
- Colors or fonts — those are aesthetic profiles, not signatures.
- Business-logic moves (`"send-invoice-on-checkout"`).

## Anatomy

Each signature is one kebab-case string. Group them by feel:

- **Ornament** — `"active-link-underline-slide"`, `"metric-row-with-sparklines"`.
- **Motion** — `"lane-swap-animation"`, `"streaming-cursor"`, `"reaction-flyup"`.
- **Interaction primitive** — `"drag-between-groups"` (also a capability), `"pull-to-refresh"`, `"quantity-stepper"`.
- **Live surface** — `"typing-indicator"`, `"presence-dots"`, `"live-badge-pulse"`, `"viewer-count-ticker"`.
- **Layout accent** — `"promo-rail"`, `"sticky-summary-rail"`, `"date-group-header"`.

Names should be self-explanatory to a designer reading them cold. If a signature needs prose to explain, break it into smaller ones or drop it.

## Placement

- **Recipe-owned** — most signatures live inside their recipe (e.g. `chat_with_agent.recipe_signatures = ["streaming-cursor", "tool-call-chip", "message-thinking-shimmer", "regenerate-button"]`). Add it here when the motif only makes sense inside that recipe's page.
- **Catalog-wide** — if the same motif belongs across many recipes (e.g. `"skeleton-shimmer-loading"`, `"toast-on-write"`), add to `backend/signature_moves/catalog.json` and reference by tag from consuming recipes.

## After adding

1. Add or update the critic rubric entry that checks for the motif (see `backend/services/critic_personas.py` — the "signature-moves check" reads recipe_signatures at runtime, so most additions need no rubric code).
2. Regen a target app for that recipe and eyeball whether the motif shows up in the schema/screenshot.
3. Update stored snapshots if this is anchoring a canonical fixture.

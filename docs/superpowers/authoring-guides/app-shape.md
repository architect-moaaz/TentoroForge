# Authoring guide — app-shape reference entry

**File:** `backend/shapes/reference_apps.json`
**Read first:** the top-level `$description` in that file, and `docs/superpowers/specs/2026-08-11-intelligent-rich-forge.md`.

An entry in `reference_apps` is a *worked example* — the planner reads a handful of these to see how the four IRF axes (`app_shape × archetypes × industry × runtime_context`) compose in practice. Add one when you want the planner to recognize a new *kind* of app it currently hallucinates.

## When to add one

- A new industry the file doesn't yet illustrate (per the M7-T7 gap review threshold: ≥3 briefs across ≥2 weeks).
- A recognizable product shape the substrate can compose but the LLM keeps missing (e.g. "player-shell" was absent → generation always defaulted to sidebar-list).
- A canonical exemplar you want stored in snapshot tests as an anti-regression anchor.

Do NOT add one for:
- A single stakeholder's favorite app.
- Something that would only differ from an existing entry by industry — the industry axis is open; a reference tells the *shape*, not the industry.
- A hypothetical product. Ground it in something real.

## Anatomy

```json
{
  "name": "Human-readable product name",
  "gloss": "One sentence — what this app IS, from the user's side of the screen.",
  "app_shape": {
    "layout": {"shell": "...", "hero": "...", "primaryInteraction": "...", "density": "..."},
    "auth": {"surface": "...", "gating": "..."},
    "nav": {"menu": "...", "back": "..."},
    "workflows": {"executionMode": "..."},
    "data": {"readShape": "...", "denormalization": "..."},
    "identity": {"usageMode": "..."},
    "label": "kebab-tag-summarizing-this-shape"
  },
  "archetypes": [
    {"name": "route_or_capability_name", "recipe": "recipe_key_or_omit_for_capabilities",
     "capabilities": { ... only if no recipe ... },
     "entities": ["entity_a"], "routes": ["/route"],
     "local_shape": { ... only if the route deviates from the app-wide shape ... }}
  ],
  "industry": "slug-you-invent — the axis is open",
  "runtime_context": ["capability_bundle_name", ...]
}
```

**Vocabulary constraint:** every value in `app_shape` MUST come from the enum defined in the spec (see IRF § "app-shape vocabulary"). Every value in `runtime_context` MUST be an existing `backend/runtime/context_bundles/<name>/` directory. Every `recipe` MUST be a key in `backend/archetypes/recipes.json`. If any of these is missing, promote it *first* through its own authoring guide, then add the reference app.

## Writing the gloss

One sentence, in user language, no jargon. "Search stays on map, view listings, book with calendar and pay." — that shows the shape without naming components.

## Choosing archetypes

Prefer `recipe` (a named archetype) over inline `capabilities` — recipes carry signature moves and component-set hints. Fall back to raw capabilities only when the route is genuinely novel and doesn't fit any recipe. Two rules of thumb:

- One archetype per meaningful route or route-cluster. Splitting further just crowds the picker; combining loses the per-route shape override.
- Use `local_shape` when a subordinate route deviates (a search-with-map app that has a form-shaped `/book` route). The absence of `local_shape` means the route inherits the top-level `app_shape`.

## `label`

A kebab-case tag that reads like an aesthetic-plus-structure summary: `"search-map-booking"`, `"player-shell"`, `"admin-back-office"`. Reused across similar apps so the planner can see the family.

## After adding

1. Run `python3 -c "import json; d=json.load(open('backend/shapes/reference_apps.json')); print(len(d['reference_apps']))"` to confirm valid JSON + updated count.
2. Update stored snapshots (M7-T1) if this reference is part of the anchor set.
3. Log a one-line entry in the current gap review at `docs/substrate/gap-reviews/YYYY-MM-DD.md` under "promotions".

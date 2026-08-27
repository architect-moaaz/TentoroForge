# Authoring guide — recipe

**File:** `backend/archetypes/recipes.json`
**Read first:** the top-level `$description` (the "recipe name → resolved capabilities" contract) and the existing 25 recipes.

A recipe is a **named shortcut** that expands to a bundle of `(capabilities, workflow_template, component_set, recipe_signatures, required_entities)`. Downstream stages read the *resolved capabilities*, not the recipe name — so a novel LLM-composed archetype and a recipe-picked one get identical treatment. Recipes exist to give the planner a **short pickable label** for common kinds; they are affordances for the LLM, not privileged code paths.

## When to add one

- The gap review promoted a repeated archetype pattern that composes cleanly into `capabilities` but currently forces the LLM to invent them fresh every time.
- A new library component set unlocks a genuinely new interaction (added `Calendar` → introduced `booking_calendar`; added `RichTextEditor` → could introduce `email_composer`).
- A widely-recognized product pattern (`livestream`, `agent_chat`) that shows up across industries.

Do NOT add:
- A variant that differs from an existing recipe only by industry (`healthcare_dashboard`) — the `dashboard` recipe with an aesthetic profile handles that.
- Anything a plain `capabilities` composition already covers (this would be dead weight; the LLM will keep picking the recipe anyway and skip the composition).
- A recipe named after a workflow (`invoice_processing`) — those are workflow templates, not archetypes.

## Anatomy

```json
"recipe_key_snake_case": {
  "gloss": "One sentence — from the user's side. What are they doing on this surface?",
  "capabilities": {
    "read": {"pattern": "list|grid|feed|board|map-pins|chart|document|tree|row-rails|timeline|single-record",
             "grouping": "none|date|status|category|section|property"},
    "write": {"pattern": "none|create-form|inline|wizard|bulk-action|drag|capture|reply|upload|streaming-capture|config-form",
              "integrity": "direct|audit-logged"},
    "interactions": ["filter", "sort", "search", "..."],
    "presentation": {"itemShape": "row|card|pin|player|bar|node|comment|message|thumbnail|document|poster|step|chart|block"},
    "state": {"realtime": "none|poll|stream|presence"}
  },
  "workflow_template": "workflow_template_name_or_null",
  "component_set": ["Container", "..."],
  "recipe_signatures": ["kebab-tagged-motif", "..."],
  "required_entities": ["entity_slug_the_recipe_needs"]
}
```

## Field discipline

- **`gloss`** — one sentence, user-side. If it names an implementation detail ("uses Zustand for state"), rewrite it.
- **`capabilities`** — every enum value must be one the downstream generators already understand. If you need a new one, promote the enum in the spec first, or the recipe is DOA.
- **`workflow_template`** — `null` unless a specific `_workflow` fixture in the workflow generator exists and matches this recipe. Do NOT invent template names; they are looked up by string.
- **`component_set`** — components the emitter should reach for. Names must exist in `packages/library/dist/starter.json`. This is a HINT, not a lockdown; the LLM can still add others.
- **`recipe_signatures`** — 2–5 kebab-case motifs (see the signature-move guide). Fewer than 2 = the recipe doesn't earn any characteristic feel and probably shouldn't exist yet.
- **`required_entities`** — entity slugs the recipe genuinely can't function without. Leave empty when the recipe adapts to whatever entity the planner assigns.

## After adding

1. `python3 -c "import json; d=json.load(open('backend/archetypes/recipes.json')); print(len(d['recipes']))"` to confirm valid JSON.
2. Add a reference-app entry that uses the new recipe (via the app-shape guide) so the planner sees a worked example.
3. If a new workflow_template is named, add the template file too — a dangling reference silently degrades the recipe.
4. Update snapshot fixtures if this recipe anchors a canonical app.

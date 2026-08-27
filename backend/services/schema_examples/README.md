# Schema Examples — gold-standard archetype demos

These JSON files are the prompt-engineering anchors the schema agent
imitates. Each is a fully-validated v2 Page schema showcasing one
archetype × page-type combination.

## Layout

- `list/` — list-page archetypes (table, card-grid, kanban)
- `detail/` — detail-page archetypes (tabbed-hero, split-detail, profile)
- `form/` — form-page archetypes (single-column, sectioned, wizard)
- `landing/` — non-CRUD pages (hero-features-cta)

## How to add a new example

1. Pick a page-type and archetype (e.g. `list/timeline`).
2. Hand-craft a JSON file showcasing real composition with token refs
   and StyleSlot usage (no inline hex / px / rem).
3. Make sure it parses through `PageV2.parse()` — the CI test
   `test_schema_examples.py` enforces this.
4. Reference only registered library components — see
   `packages/library/src/index.ts` for the canonical list.

## Why these are hand-curated, not LLM-generated

The schema agent reads one of these as a few-shot example and follows
its level of richness. If we LLM-generated them, we'd be teaching the
LLM to imitate its own mediocre output. Hand-curation is the bottleneck
that lifts the ceiling.

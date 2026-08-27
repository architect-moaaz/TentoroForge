# IRF substrate snapshots (M7-T1 / M7-T2)

**Purpose.** Guard the substrate's pickers and expansions against silent regressions when we edit `reference_apps.json`, `recipes.json`, `aesthetic_profiles/`, or the composition primitives.

## What's here

- `fixtures/` — canonical input "plan-shaped" seeds, one JSON per anchor app (`snap2app.json`, `tip-calculator.json`, `instagram.json`, `linear.json`, `workday.json`, `uber.json`, `shopify.json`, `swiggy.json`).
- `stored/` — the resolved outputs the substrate produces for each fixture: `<fixture>.aesthetic.json`, `<fixture>.recipes.json`, `<fixture>.shape.json`. These files are the baseline the tests diff against.
- `../services/test_irf_snapshots.py` — pytest suite. Loads each fixture, runs the substrate pickers/resolvers on it, and asserts the result matches the stored snapshot exactly.

## Updating

1. Make the substrate change (JSON edit under `backend/shapes/`, `backend/archetypes/`, `backend/design/aesthetic_profiles/`, or the composition primitives).
2. Run `pytest backend/tests/services/test_irf_snapshots.py` — failures show a unified diff between stored and computed.
3. If the diff is intended: `SUBSTRATE_SNAPSHOT_UPDATE=1 pytest backend/tests/services/test_irf_snapshots.py` — this rewrites the `stored/` files. Review the diff (`git diff`) before committing.
4. If the diff is NOT intended: fix the substrate change so the snapshot stays put.

## Fixtures

Each fixture is a *plan-shaped* dict — the minimum the pickers/resolvers need. The stored snapshot for a fixture is:

- `<fixture>.aesthetic.json` → `{picked: profile_name, score: N}` from `pick(plan)`
- `<fixture>.recipes.json` → `[recipe_key_for_each_archetype_in_the_fixture]`
- `<fixture>.shape.json` → the fixture's `app_shape` echoed back after normalization (protects against enum-value drift)

Adding a new anchor: drop `<name>.json` in `fixtures/`, run with `SUBSTRATE_SNAPSHOT_UPDATE=1` to generate the three stored files, then commit both fixture and stored files together.

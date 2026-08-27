# Fixture Fleet

Standing generation fixtures — the regression bar for the whole pipeline.
Each fixture is a set of FROZEN INPUTS; generated apps are disposable and
land in `output/fleet-<name>` when the fleet runner (S4,
`scripts/fleet.py`) regenerates them. Scores come from
`services/scorecard.py` (`contracts/scorecard.json` per app); blessed
baselines live in `fleet/baselines.json` (S5).

Spec: docs/superpowers/plans/2026-08-17-fixture-fleet-scorecard.md.

## Layout

```
fleet/fixtures/<name>/
  plan.json          # canonicalized plan (canonicalize_plan output) — the
                     # pipeline input; absent only when meta.json says the
                     # plan must be seeded via --replan
  description.txt    # the user prompt the plan answers
  meta.json          # {archetype, source_app, harvested_at, profile, stresses}
```

## Fixtures

| name | source app | archetype | stresses |
|---|---|---|---|
| doc-intel | atb0m97x | field-service | upload→OCR→AI extract, trigger forms, status stepper |
| yoga-booking | 2seyiw4q | booking-platform | personas, visual lock, schedule flows |
| recruitment | v3azan7i | ats | kanban, actors/journeys, role-scoped actions |
| leave-management | (seeded via `--replan`) | approval-workflow | approval lifecycle, task inbox, role-scoped nav |
| banking | igi1eqs7 | banking-platform | Money/Ledger primitives, visual lock, masked columns |
| commerce-cart | vulbzsi0 | commerce | cart runtime, checkout workflow, product imagery |

## The freeze rule

Fixture inputs change only DELIBERATELY. A score movement must mean the
PLATFORM changed, never that the inputs quietly drifted. When a plan must
change (new plan schema field, a fixture gap), re-harvest through
`canonicalize_plan`, and record why in `meta.json` under
`"revisions": [{date, reason}]`. Never hand-edit plan.json ad hoc.

## Adding a fixture

1. Pick a generated app that exercises something the fleet doesn't.
2. Harvest: load its `src/contracts/plan.json`, pass through
   `services.plan_canonicalizer.canonicalize_plan`, write the canonical
   form as `plan.json`; copy the plan's `description` to
   `description.txt`; write `meta.json` with archetype + what it
   stresses.
3. Run the fleet on it once; if it scores, bless it into
   `fleet/baselines.json`.

`tests/services/test_fleet_fixtures.py` keeps the registry well-formed.

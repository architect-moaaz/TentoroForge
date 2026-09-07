# Resume state — editor audit & fix campaign

Written so a fresh session can continue without re-deriving anything. Last
pushed commit: **`76213c8`** on branch **`smithv2-editor-fixes`**.

## What this campaign is

Audit every component in the TentoroForge palette by driving the real editor as
a user, fix what is found at the **root cause / component level** (never
per-app), and prove it with tests plus live verification.

Standing rule from the user, applies to everything:
**no compromise on completeness, and every fix must be a root-cause or
component-level fix — never a patch for one particular app.** No special-casing
by project / page / route / component name. When the same defect appears on N
components, fix the mechanism, not N descriptors.

## Coverage — 133 components in 6 categories

| category | count | state | report |
|---|---|---|---|
| layout | 18 | done | `docs/editor-audit/containment.md`, `browser-test.md` |
| input | 41 | done | `input-components.md`, `-2.md`, `-3.md` |
| display | 31 | done | `display-components.md`, `-2.md` |
| navigation | 10 | audited, fixes in flight | `qa-audit-log.md` |
| feedback | 21 | audit in flight | `qa-audit-log.md` |
| data | 12 | audit in flight | `qa-audit-log.md` |

## Known-open work

1. **The 4 app routes need re-auditing WITH A SIGNED-IN SESSION.** They were
   audited unauthenticated; the app redirects to `/login`, so "blank page",
   "list invisible", "`[id]` ignored" are all void. See the CORRECTION block at
   the end of `qa-audit-log.md`. This is a real coverage gap.
2. **Round 5 rows 27–29** — the empty-node hint names the wrong prop (`bind`
   instead of the required-and-missing one), names none at all for five
   components, and is absent for zero-area nodes. Assigned to Fixer F. The
   durable fix derives the hint from each component's Zod schema, NOT a
   per-component lookup table.
3. **`final-qa-report.md` has not been produced yet.** It must cross-check every
   row of `qa-audit-log.md` into a table with columns: Component/Route · Tested ·
   Bugs Found · Bugs Fixed · Features Requested · Features Added · Final Status,
   and explicitly call out anything never tested, found-but-not-fixed, or
   requested-but-not-implemented.
4. **Showcase pages** — `/ops-dashboard` is built (54 nodes, 29 component
   types). `/stock-intake`, `/item-profile`, `/workspace`, `/toolbar-lab` are
   not. See `docs/editor-audit/showcase-checklist.md`. Building through the
   palette costs ~15-25s per component.
5. **`frontend/src/lib/preview-resolve.ts`** now delegates to the engine's
   `computeAggregate`, but the KPI `format` field (`"currency"`) is carried and
   never applied — tiles render `46851.48`, not `$46,851.48`.

## Baselines — measure against these, and REBUILD FIRST

A stale `dist/` silently changes these numbers; it has produced two false
regression readings in this campaign.

| suite | baseline |
|---|---|
| frontend | 47 files / 613 tests / **0 failures** |
| `editor-validation.test.tsx` | 21/21, `invalidProps=0`, `selectable=129` |
| patches | 68 passing |
| registry | 23 passing |
| library | **24 failing** / ~1057 passing (pre-existing: theming-contract, Heading, DescriptionList, Money, registry-parity, Stagger, Sidebar, CameraCapture, data-feedback-nav) |
| renderer | **30 failing** / ~249 passing (pre-existing) |
| engine | **2 failing** / 45 passing (pre-existing) |
| backend | 122 failing / 13369 passing across 64 files — all pre-existing, spread wide; the changed areas are green |

Build order: `schema → patches → renderer → library → registry → engine`.
The root `npm run build` order is WRONG.

## Services

| port | what | notes |
|---|---|---|
| 6500 | backend (uvicorn, no `--reload` — restart to pick up Python changes) | |
| 6501 | editor frontend | |
| 6503 | render-scaffold (`NEXT_BASE_PATH=/p`) | crashes often; restart per `start-all.ps1` |
| 6510 | the generated app standalone (`next dev` in `output/gh0mlpbp/app`) | **requires login** |
| 5433 | Postgres (userspace cluster, `pg_ctl -w start`) | |

## Hard-won lessons — do not relearn these

- **Never silence a `git stash pop`.** One did, failed on a tracked `dist/`
  artifact, and reverted 582 files. Recovered by resetting the one blocking file.
- **Rebuild before measuring test counts.** Stale `dist/` gave a false
  "2 regressions" and a false "28 tests vanished".
- **A registry `default` is copied onto every dropped node.** A default the
  component reads as a COMMAND rather than "unset" is a new bug:
  `ActivityFeed.maxHeight: 0`, `FileUpload.maxSizeMb: 0`,
  `MultiSelect.maxSelectionLabel: 0`, `BulkActionBar.selectedCount: 0`.
  When in doubt, omit the default.
- **Every default must satisfy BOTH** the library `.schema.ts` AND the
  `.strict()` node schema in `packages/schema/src/nodes/`. Valid for one and
  rejected by the other = every dropped node fails `PageV2`.
- **Verify agent claims.** Subagents report optimistically. Two headline
  findings this session did not reproduce.
- Screenshots time out on this Chrome profile — use `javascript_tool` DOM probes.
- Editor chrome must be clicked via JS (find by text), not coordinates — the
  canvas scrolls and stale coordinates hit the wrong thing.
- `packages/schema` edits require `npm run emit:blueprint-schema` afterwards or
  a backend contract test fails.
- The A2UI sibling repo (`../agent2ui`) regenerates
  `specification/v0_9/catalogs/forge/catalog.json` when the composer runs. The
  user has no push access there — check `git status` in it before pushing.

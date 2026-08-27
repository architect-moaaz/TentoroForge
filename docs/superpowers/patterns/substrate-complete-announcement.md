# Substrate-complete — internal announcement (M7 wrap)

**To:** platform + generation + design teams
**From:** substrate maintainers
**Date:** 2026-08-11
**Status:** the four-axis IRF substrate has reached its baseline vocabulary. From this week on, growth is governed by the weekly gap review, not milestone batches.

---

## What we shipped

The Intelligent Rich Forge substrate — the layered "what kind of app is this?" description the planner and every downstream agent bind to — is now populated at the target coverage line the M0 spec named:

- **25 reference apps** across 20+ industries (`backend/shapes/reference_apps.json`)
- **25 recipes** covering both classic and modern archetypes (`backend/archetypes/recipes.json`)
- **15 runtime context bundles** for the OS capabilities apps actually reach for (`backend/runtime/context_bundles/`)
- **6 aesthetic profiles** the picker chooses between per plan (`backend/design/aesthetic_profiles/`)
- **10 form UX patterns** with 30 invariants (auto-fix + finding) (`backend/forms/patterns/`, `backend/services/form_ux_invariants.py`)
- **Signature moves catalog** — recipe-owned + cross-recipe (`backend/signature_moves/catalog.json`, per-recipe `recipe_signatures`)
- **The composition primitives**: SessionContext, verify stack, recover ladder, multi-critic panel, stage plan protocol, surface treatment pass, interpolator formatters

Total substrate suite: 527 backend tests + 24 renderer tests = 551 green, zero regressions.

---

## Why this milestone matters

Before M0 we treated "the LLM should be smart enough to figure out what kind of app to build" as our vocabulary. The result was that every generation re-invented shape from scratch, and no two apps in the same industry looked meaningfully consistent. The four-axis substrate fixes the *authoring surface*: the planner picks from a closed set of enums and named recipes; the LLM keeps judgment inside that surface; and the verification stack has something concrete to check against.

We now have anchors to test against, gap-signals to grow from, and a picker that trades LLM improvisation for reproducible cross-app coherence — without giving up the flexibility to compose novel modules when the substrate genuinely doesn't fit.

---

## What changes for downstream teams

**Generation** — no immediate action. Every stage that previously derived shape from scratch is either wrapped in the SessionContext or reads the plan's resolved four-axis substrate. `FORGE_SURFACE_TREATMENT` and `FORGE_FORM_UX_INVARIANTS` remain the flags; both stay off historic pipelines until a project opts in.

**Smith / editing** — same tools, richer context. The blueprint now stamps the plan's `app_shape.label`, aesthetic profile, and recipe list, so mutation asks can reason about "this is a player-shell app, don't add a data-grid to `/now-playing`."

**Design critic** — the design_critic rubric now scores against the picked aesthetic profile's `when_to_use` matches, the shape's signature moves, and palette/class-diversity floors. Findings surface earlier in the panel report.

**Documentation** — the five companion authoring guides now live under `docs/superpowers/authoring-guides/`:
- `app-shape.md` — how to add a reference app
- `aesthetic-profile.md` — how to add a profile
- `signature-move.md` — how to tag a motif
- `recipe.md` — how to introduce an archetype recipe
- `runtime-context-bundle.md` — how to declare an OS capability

Add to the substrate through these; don't hand-edit Python.

---

## What we deferred

- **M7-T9** — live regeneration of 8 canonical apps to freeze the snapshot fixtures. Deferred by decision: the snapshot infra and fixture stubs are in; the freeze happens as a scheduled activity so it can be watched.
- **M3-T11, M4-T7, M5-T10, M6-T10** — live-gen validation ticks for each milestone. Also folded into the scheduled acceptance.

Nothing else in the M0–M7 plan is outstanding.

---

## The new governance cadence

The substrate is a living surface. Growth from here is **not** milestone-shaped — it's weekly:

1. **Mondays** — read the past week's `logs/substrate_briefs/*.jsonl`, bucket by axis, promote items that meet the ≥3-briefs-across-≥2-weeks threshold. File the review at `docs/substrate/gap-reviews/YYYY-MM-DD.md`.
2. **When you promote** — one JSON edit, one line in the review file, one snapshot re-baseline if it changed anchor outputs. No Python.
3. **When you reject** — write down the reason (`too-specific`, `already-covered`, `wrong-axis`, `single-app-hallucination`, `under-threshold`). Rejections are the substrate's memory of what it deliberately isn't.

Full ritual + rules in [`docs/superpowers/patterns/substrate-gap-review.md`](../patterns/substrate-gap-review.md).

---

## Where to watch

**Quality dashboard** — `localhost:6501/quality` (M7-T3) shows the coverage-verdict rate, guards fired per gen, design-critic score by shape, Smith turn success rate, and extension-needed rate. This is the single view for "is the substrate holding up?" — the number that should trend down is `extension_needed`.

**Snapshot tests** — `pytest backend/tests/services/test_irf_snapshots.py` guards against silent regressions in the anchor apps. Break-glass to update: `pytest --snapshot-update`, then read the diff before committing.

---

## Ask

- If you generate an app this week and the substrate felt wrong, drop it into the gap-review inbox (a brief log row is enough).
- If you edit any substrate file without the corresponding authoring guide, you're leaving cleanup for the reviewer. Please don't.
- If you think a new axis or a new dimension inside an axis is needed, that's a spec-level change — open a design doc, not a JSON edit.

The substrate is now the thing that scales. Let's keep it good.

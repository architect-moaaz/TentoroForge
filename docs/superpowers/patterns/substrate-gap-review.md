# Substrate gap review — weekly cadence + promotion rules

**Status:** active
**Cadence:** weekly (Mondays)
**Owner:** platform / substrate maintainers
**Inputs:** `logs/substrate_briefs/*.jsonl` (design-brief snapshots + extension-needed verdicts)
**Outputs:** JSON edits to `backend/shapes/`, `backend/archetypes/`, `backend/runtime/context_bundles/`, `backend/design/aesthetic_profiles/`, `backend/forms/patterns/`

---

## Why this exists

The IRF substrate — the four axes (`app_shape × archetypes × industry × runtime_context`) plus their supporting vocabularies (aesthetic profiles, signature moves, form patterns, recipes) — is meant to *grow*, not stay frozen. Every generation stamps a `coverage_verdict` on the plan:

- `in_scope` — the substrate covered the ask cleanly.
- `extension_needed` — the LLM had to compose something the substrate doesn't name, or the planner marked a needed primitive as missing.
- `out_of_scope` — the ask fell outside the runtime/product bounds and should stay outside.

The **gap review** is the load-bearing feedback loop: it reads the accumulated `extension_needed` briefs, spots repeated patterns, and promotes them into the vocabulary so future generations return to `in_scope`. Without a cadence the substrate stalls; without promotion rules the substrate bloats. Both matter.

---

## The weekly ritual

1. **Collect briefs.** Read `logs/substrate_briefs/*.jsonl` from the previous 7 days. Each row is one plan's substrate summary: `{app_shape, archetypes[], industry, runtime_context[], coverage_verdict, extension_notes[]}`.
2. **Bucket by axis.** Group `extension_notes` by which axis they hit: `layout`, `nav`, `data`, `workflow`, `archetype`, `recipe`, `runtime_context`, `aesthetic_profile`, `signature_move`, `form_pattern`, `industry`.
3. **Count repeats.** For each bucket, find phrases (or near-duplicates) that recur across ≥2 different briefs.
4. **Promote qualifying items** per the rules below.
5. **File the review** at `docs/substrate/gap-reviews/YYYY-MM-DD.md`: one section per promotion, one section listing rejected patterns and why (so the log survives beyond a single reviewer's memory).
6. **Post a one-liner** in the team channel with the promotion count and any notable rejections.

Skip a week if no new `extension_needed` briefs arrived. Never bulk-promote a backlog — old briefs go stale as the substrate around them changes.

---

## Promotion rules

The bar for adding to the substrate is deliberately higher than the bar for *seeing* something in a brief. Anything that ships in `shapes/` / `archetypes/` / `runtime/context_bundles/` becomes part of every future planner's anchoring set — so noise here is expensive.

### Threshold

**≥3 briefs across ≥2 distinct weeks** — a repeated ask that survives a week's gap between sightings, not a same-day cluster from one big app.

Exceptions:
- A **runtime_context** that names a real OS capability (biometric, calendar, etc.) can promote on 1 sighting if the capability is unambiguous.
- An **industry** string is *never* promoted — the axis is intentionally open. Only reference apps hint at industries.

### What promotes to what

| Extension observed | Promotes to | File |
|---|---|---|
| Repeated layout/nav/data primitive combination | New `label` in a reference app entry | `backend/shapes/reference_apps.json` |
| Repeated recipe name (`chat_with_agent`, `livestream`, …) | New recipe entry | `backend/archetypes/recipes.json` |
| Repeated OS capability | New context bundle | `backend/runtime/context_bundles/<name>/bundle.json` |
| Repeated visual identity/mood | New aesthetic profile | `backend/design/aesthetic_profiles/<name>.json` |
| Repeated form UX pattern | New pattern | `backend/forms/patterns/<name>.json` + index update |
| Repeated signature move (visual/interaction motif) | Add to relevant recipe's `recipe_signatures` | `backend/archetypes/recipes.json` |
| Repeated industry-shaped ask | Add a *reference app* under that industry (not a new axis value) | `backend/shapes/reference_apps.json` |

### Rejection reasons (write them down)

- **Too specific** — the phrase names a product feature (`stripe_checkout_v2`), not a reusable primitive.
- **Already covered** — the reviewer found an existing recipe/pattern the planner failed to pick; the fix is prompt/scoring, not vocabulary.
- **Wrong axis** — the ask was a workflow, not a shape; belongs in workflow templates, not `shapes/`.
- **Single-app hallucination** — one big brief generated many notes; none independently reproduced.
- **Under threshold** — real but not yet repeated across the required weeks; keep in the log and revisit.

---

## Housekeeping

- Every promotion is one JSON edit — never Python. If a promotion *would* require Python, the substrate is under-expressive; open a separate design-doc issue instead of hacking it in.
- Bump `$schema_version` in the target file only on breaking shape changes; additive entries do not bump.
- After promotion, re-run the M7 snapshot tests (`pytest backend/tests/services/test_irf_snapshots.py`) and update stored snapshots if the vocabulary shift changed outputs — record the rationale in the same review file.
- Coverage-verdict tracking: `M7-T3` quality dashboard shows the `extension_needed` rate over time; the review should keep it trending down.

---

## Anti-goals

- Do not use the review to relitigate individual generation quality — that's Smith / verify / critic territory.
- Do not add a primitive just because it sounds clever. Every entry costs LLM attention on every future plan.
- Do not treat "the LLM composed something novel" as a bug. Composition inside the substrate is the point; only *repeated* composition is a signal.

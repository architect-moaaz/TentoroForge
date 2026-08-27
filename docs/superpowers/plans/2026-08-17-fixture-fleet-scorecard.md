# Fixture Fleet + Merged Scorecard

**Goal:** make quality *measurable and comparable* across generations, so every
platform change is proven against a standing fleet of fixture apps instead of
one hand-tested app. This is the substrate for "training" the pipeline: score
every generation, keep failures forever, direct fixes by trend.

Closes long-pending tasks #607 (capture baseline fixture scores) and #608
(leave-management fixture), and generalizes the fixture table in
`2026-08-12-pipeline-cleanup.md` (§ "Fixture set") into running code.

---

## Why now

- The pipeline already writes ~25 per-app quality artifacts (gates, critics,
  verify runs) but they use **three different summary vocabularies**, live in
  **four different directories** (`contracts/`, `src/contracts/`, app root,
  `verify-run/`), and four have **no summary block at all** (bare arrays).
  Nobody reads them side by side; there is no single number per app.
- Every fix this session (WHERE-id-empty, upload-page design) was live-proven
  on **one** app (atb0m97x). Regressions on the other archetypes are invisible
  until a user hits them.
- FaultRecord + fidelity-log + design-memory exist for compounding learning,
  but nothing aggregates across apps.

## Design decisions

1. **Scorecard is a pure reader.** `services/scorecard.py` re-runs nothing; it
   reads whatever report artifacts exist in an output dir, normalizes them,
   and writes `contracts/scorecard.json`. Missing artifacts are recorded as
   `absent`, never errors — old apps score fine with partial data.
2. **Two headline numbers + a breakdown.** `functional_score` (0–100) from the
   correctness gates; `design_score` (0–100) from the critic/anatomy/visual
   artifacts. Composite ranking uses `min(functional, design)` — a beautiful
   broken app must not outrank a plain working one.
3. **Don't move existing artifacts.** The dir sprawl (`contracts/` vs
   `src/contracts/` vs root) is annoying but churn-heavy to fix; the scorecard
   hides it behind one reader. (Consolidation can be a later cleanup phase.)
4. **Fleet runs are script-driven, not HTTP-driven.** `run_pipeline()`
   (`services/pipeline/spine.py:40`) with a canned plan + pinned output dir,
   modeled on `scripts/generate_with_metrics_v2.py`. No auth, no discovery
   chip dance, `project_id=None` (no platform DB needed for the static tier).
5. **Two scoring tiers.**
   - **Static tier** (default, no app boot): artifact reading only. Cheap
     enough to run per-fixture after every platform change.
   - **Runtime tier** (`--runtime`): boots each app via
     `journey_gate.run_journey_gate(output_dir, force_mode="warn")` (output-dir
     keyed, no DB) + route sweep; folds journey pass-rate and sweep results
     into the scorecard. Slower; run before merges / nightly.
6. **Baselines are blessed, committed JSON.** `backend/fleet/baselines.json`
   maps fixture → scorecard summary. The compare step exits non-zero on
   regression, so the fleet is CI-able from day one.
7. **Fixture = frozen inputs, disposable outputs.** A fixture is a directory
   of *inputs* (plan.json + description + expected-traits); generated apps
   land in `output/fleet-<name>` and are regenerable at will. Plans are
   harvested from real generated apps (canonicalized via `canonicalize_plan`)
   so they exercise the deterministic 90% of the pipeline; the planner itself
   is exercised by an optional `--replan` flag, not by default (cost + noise).

## Score model (v1 weights — tune later)

`functional_score` = 100 − penalties, floor 0.
**S2 calibration (implemented):** two changes vs the original draft, both
forced by retro-scoring the blessed reference app (it hit the proof cap on
`undefined-ref` alone and scored 50): (a) proof scores **distinct finding
codes**, not raw counts — 20 repeats of one broken pattern is one class of
defect; (b) `workflow_validation` + `contract_validation` are
**informational only** (penalty 0) because proof_pass already aggregates
them — penalizing the standalone files double-counted. `rules_validation`
is not aggregated and still penalizes.

| source (artifact) | metric | penalty |
|---|---|---|
| `contracts/proof_report.json` | distinct error/warning **codes** | 8/err-code, 2/warn-code (cap 40) |
| `contracts/delivery-report.json` | `summary.error` / `.warn` | 5/err, 1/warn (cap 25) |
| `contracts/page-contract.json` | `summary.errors` | 3/err (cap 15) |
| `contracts/binding-smoke.json` | `summary.error` | 3/err (cap 15) |
| `contracts/workflow_validation.json` + `contract_validation.json` | error counts (informational) | 0 — aggregated by proof |
| `contracts/rules_validation.json` (bare array — derive) | error-severity findings | 2/err (cap 10) |
| `contracts/action-contract.json` (derive) | `resolved==false` actions | 3 each (cap 10) |
| runtime tier: journey gate | failed journeys / total | scale to 25 |

`design_score` = 100 − penalties, floor 0:
| source | metric | penalty |
|---|---|---|
| `reports/page-critic/summary.json` | `pass_rate`, `avg_score` | (1−pass_rate)·40 |
| `contracts/page-anatomy.json` | `summary.reported` (unfilled slots) | 3 each (cap 15) |
| `src/contracts/requirement-fidelity.json` | `summary.missing` / `.partial` | 5/missing, 2/partial (cap 20) |
| runtime tier: `contracts/visual-qa.json` | error/warn findings | 5/err, 1/warn (cap 15) |
| runtime tier: `contracts/visual-regression.json` | `layout_changed` vs blessed baseline | 3 each (cap 10) |

Scorecard shape:
```json
{
  "generated_at": "...", "fixture": "doc-intel", "tier": "static|runtime",
  "functional_score": 87, "design_score": 74, "composite": 74,
  "inputs": {"proof_report": "ok", "visual_qa": "absent", ...},
  "breakdown": {"proof": {"errors": 2, "penalty": 10}, ...},
  "timing": {"total_s": 512}   // from generation-timing.json when present
}
```

## Slices

### S1 — `services/scorecard.py` (TDD)
- `build_scorecard(output_dir, tier="static") -> dict` + `write_scorecard(output_dir)`
  → `contracts/scorecard.json`.
- Normalization table for the report vocabularies (`{error,warn,info}` /
  `{error_count,warning_count}` / `{ok,missing,partial}` / bare arrays).
- Tolerant reader: absent file → `inputs[name]="absent"`, no penalty
  contribution, never raises.
- Tests: fixture output dirs assembled in tmp_path with synthetic reports;
  cover each vocabulary, bare-array derivation, absent files, cap behavior,
  composite=min rule, idempotent write.

### S2 — wire + retro-score
- Call `write_scorecard` at the very end of the `apply_post_generate_fixes`
  tail (after the delivery gate — it must be the LAST writer so it sees every
  report).
- Retro-score existing apps as a smoke check:
  `output/atb0m97x` and `reference-apps/document-vault-doc-intel-2026-08-16`
  (the blessed reference should score near the top — if it doesn't, the
  weights are wrong, fix them now).

### S3 — fixture registry (`backend/fleet/`)
- `fleet/fixtures/<name>/plan.json` + `description.txt` + `meta.json`
  (`{archetype, stresses: [...], profile: "fast"}`).
- Six fixtures, harvested from existing apps' `src/contracts/plan.json` run
  through `canonicalize_plan`:
  1. `doc-intel` (upload→OCR→AI extract; from atb0m97x)
  2. `yoga-booking` (personas, visual lock; from 90cx1h1u/2seyiw4q)
  3. `recruitment` (kanban, actors/journeys)
  4. `leave-management` (approval workflow, role-scoped nav; plan seeds exist
     in `tests/fixtures/3wjvs581__*` + `_e2e_binding_test.py`) ← task #608
  5. `banking` (Money/Ledger primitives, TRUST_NAVY; from igi1eqs7 rerun)
  6. `commerce-cart` (cart runtime, checkout workflow)
- `fleet/README.md`: how to add a fixture, the freeze rule (plans only change
  deliberately, with a note in meta.json).

### S4 — fleet runner (`backend/scripts/fleet.py`)
- `python -m scripts.fleet run [--only name,...] [--runtime] [--replan]`
  per fixture: wipe/prepare `output/fleet-<name>` → `persist_profile(fast)` →
  `run_pipeline(output_dir, plan, description, source=PlanSource.text(),
  project_id=None)` → `write_scorecard` → (runtime tier: `run_journey_gate`
  then re-score).
- Aggregate to `fleet-results/<run-ts>/summary.json` + a Markdown table
  (fixture × functional/design/composite × Δ vs baseline) printed and saved.
- Serial execution (LLM cost/rate limits); `--only` for targeted reruns.
- Env preset: `FORGE_QUALITY` untouched by default; document the recommended
  fleet env (`FORGE_DELIVERY_GATE=warn` etc. — warn everywhere so a run always
  completes and scores, gates never abort the fleet).

### S5 — baselines + regression compare  ← task #607
- `python -m scripts.fleet bless` → writes `fleet/baselines.json` from the
  latest run (per-fixture scorecard summaries + generation timing).
- `python -m scripts.fleet compare` → non-zero exit if any fixture's
  functional or design score dropped more than `--tolerance` (default 2 pts);
  prints the per-source breakdown diff so the offending gate is named.
- First bless happens after S4's first clean run = the Phase-0 baseline the
  pipeline-cleanup plan has been waiting on.

### S6 — trend + fault aggregation (follow-up, not this slice)
- `fleet-results/` trend view; cross-app FaultRecord signature ranking
  (extend `fault_record_analytics` with a fleet dimension); nightly cron;
  wire `scripts.fleet compare` into CI. Documented here so S1–S5 don't grow.

## Acceptance

1. `pytest tests/services/test_scorecard.py` green (S1).
2. `contracts/scorecard.json` appears on a fresh generation (S2), and the
   blessed reference app retro-scores ≥ atb0m97x on design.
3. `python -m scripts.fleet run` regenerates all six fixtures headlessly and
   prints the score table (S3+S4).
4. `bless` then `compare` on an unchanged tree exits 0; artificially breaking
   one report (e.g. add a proof error) makes `compare` exit non-zero naming
   the fixture and the source (S5).

## Non-goals (this slice)
- Moving/renaming existing report artifacts.
- LLM screenshot judging beyond the existing visual-QA critic.
- Planner-in-the-loop fleet runs by default (`--replan` exists but is opt-in).
- CI wiring / nightly cron (S6).

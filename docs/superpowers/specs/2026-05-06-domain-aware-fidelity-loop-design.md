# Domain-Aware Fidelity Loop — Design Spec

**Date:** 2026-05-06
**Status:** Design approved, pending implementation plan
**Phases:** 14 (closed loop) + 15 (reference grounding)
**Predecessors:** `2026-05-06-fidelity-render-loop-design.md` (Phase 12.5 + 13, shipped)

---

## Goal

Move the fidelity render check from a manual editor affordance into the agentic generation pipeline itself, so generated apps are high-fidelity AND domain-relevant out of the box. The user opens the editor and sees scored, polished pages — clicking is reserved for re-checking after manual edits, not for first reads. Healthcare apps feel like healthcare apps; fintech feels like fintech; pages that don't reach the quality bar are clearly flagged for the user without blocking generation.

## Context — what's already shipped

`2026-05-06-fidelity-render-loop.md` (just landed) implements Phase 12.5 + 13:

- **Render-scaffold** (`apps/render-scaffold/`, port 6503) — minimal Next.js app that renders any project's schemas via `/p/<projectId>/<...slug>`. Mounts the full library registry, embeds an a11y tree as a `<script>` tag.
- **Render-service** (`backend/services/render_service/`, port 6502) — FastAPI process holding a warm Playwright Chromium pool. POST `/render` returns base64 PNG + a11y tree.
- **Vision evaluator** (`backend/services/vision_evaluator/`) — Pydantic `Critique` model with the 5-axis rubric (visualPolish, domainFeel, informationDensity, componentCoherence, brandReflection), system prompt with calibration anchors, retry-once-on-invalid-JSON.
- **Fixtures library** (`backend/services/fixtures/`) — 3-layer fallback (curated banks → Faker → type-correct nonsense) for general/healthcare/fintech/hr.
- **Editor surface** — Preview tab + CritiquePanel + FidelityScoreBadge in the schema editor. Single-shot scoring via `/api/_debug/score-page/<short_id>`.
- **Fidelity log** (`output/<id>/src/contracts/fidelity-log.json`) — per-page score history.

What's missing: scoring is **manual-trigger-only**. The pipeline produces schemas; the user has to click "Score now" to learn whether they're any good. There's no mechanism for the pipeline to fix issues it finds, and no mechanism for the LLM to know what "good" looks like for the domain it's generating for.

## Locked design decisions

| | Decision |
|---|---|
| **Scope** | Phase 14 (closed loop) + Phase 15 (reference grounding) together |
| **Loop integration** | Batch post-schema parallel phase, not inline-per-page |
| **Reference bank** | LLM-generated + score-filtered, 4 domains × 5 page-types × 2 = 40 exemplars |
| **Patch strategy** | Dedicated patch agent emitting RFC 6902 + 7-step reliability stack |
| **Iter budget** | 3 patch iters + 1 schema-agent fallback, 90s wall-clock per page, $5 project cap |
| **Failure handling** | Soft-fail: pipeline always succeeds; failed pages flagged in editor |
| **Editor** | Reads from fidelity-log.json on open; manual re-score appends new iter |
| **Rollout** | Both phases independently flag-gated, default-off until tuned |

---

## 1. High-level architecture

The fidelity loop slots into the existing phased pipeline as a new phase between page generation and QA. It does not replace existing agents — it wraps them.

```
EXISTING PIPELINE (today)
  plan → registry → contracts → schema → extract_entities → merge
       → parallel(auth, api, biz) → extract_routes → merge → validate
       → components → extract_components → merge
       → pages → extract_pages → merge → validate
       → seed → QA → post_generate_fixes → validator → indexer

NEW PIPELINE (Phase 14 + 15)
  plan → registry → contracts
       → schema (now grounded in domain reference exemplars)  ← Phase 15
       → extract_entities → merge
       → parallel(auth, api, biz) → extract_routes → merge → validate
       → components → extract_components → merge
       → pages (also grounded in exemplars) → extract_pages → merge → validate
       → seed
       → fidelity_loop  ← Phase 14 — NEW
       │   for each page in parallel (concurrency=4):
       │     iter 0: render → score → log
       │     while score < 8.0 and high-severity issues and iter < 3:
       │       patch_agent → validate → apply → re-render → re-score
       │       if regression or invalid → restore + retry once → fallback to schema re-prompt
       │     log final state
       → QA → post_generate_fixes → validator → indexer
```

Two new files anchor the work: `backend/agents/patch_agent.py` and `backend/services/fidelity_loop.py`. Two existing files learn to consume the reference bank: `backend/agents/schema_generator.py` and `backend/agents/page_agent.py`. The fixtures library, render-service, and vision evaluator are already in place — no changes there.

Two new flags gate everything:
- `FIDELITY_LOOP_ENABLED` (default `false` until tuned) — gates Phase 14.
- `REFERENCE_GROUNDING_ENABLED` (default `true` once the bank is seeded) — gates Phase 15.

Existing `FIDELITY_RENDER_ENABLED` + `FIDELITY_SCORING_ENABLED` flags continue to gate the editor-side manual flows. The two new flags are independently flag-able so we can A/B-test their value: grounded-only, looped-only, both, neither. Each project's `fidelity-log.json` records which flags were active at gen time so quality differences are attributable.

## 2. Reference grounding bank (Phase 15)

The bank is a versioned corpus of high-quality Page schemas, organized by `(domain, page_type)`. The schema/page agents consume relevant exemplars at gen time as few-shot examples.

### Directory structure

```
backend/reference_pages/
  general/
    list/
      exemplar_01.json         ← a complete Page schema (PageV1|PageV2)
      exemplar_01.meta.json    ← {score, scored_at, model_used, seeder_version, screenshot_path}
      exemplar_01.png          ← the rendered screenshot at gen time (visual audit)
      exemplar_02.{json,meta.json,png}
    detail/
    form/
    dashboard/
    settings/
  healthcare/  ← same structure
  fintech/
  hr/
```

**Initial bank size:** 4 domains × 5 page-types × 2 exemplars = **40 exemplars**. Each exemplar is a triple (schema, metadata, screenshot). Total storage ~5–10 MB. Versioned in git so the bank ships with the codebase.

### Exemplar admission criteria

A Page schema is admitted to the bank only if it meets all four:
1. Parses cleanly through `PageV1 | PageV2` zod union.
2. Renders without console errors via the render-service.
3. Scores **≥ 8.0** composite on the rubric.
4. Has **zero high-severity issues** in the critique.

Anything else gets rejected and re-rolled.

### Seeder script (one-shot, run by us — not users)

```
backend/scripts/seed_reference_bank.py

  Usage:
    python -m scripts.seed_reference_bank \
        --domain healthcare --page-type list --target-count 2 \
        --max-attempts 10 --seeder-version v1

  Flow per (domain, page-type) cell:
    1. Build a detailed brief for that cell ("design an excellent
       healthcare patient list page for a hospital records app...")
       Brief includes: domain persona, common entities for that domain,
       the component library catalog, the rubric, anti-patterns to avoid.
    2. Loop up to max-attempts:
         a. Strong model generates a candidate Page schema
         b. Validate against PageV1|PageV2 zod
         c. Write to a temp project shell so the scaffold can render it
         d. Render via render-service
         e. Score via vision evaluator
         f. If score ≥ 8.0 and no high-severity issues → keep
         g. If keep-count == target-count → stop
    3. Each kept exemplar saves: schema.json, meta.json, screenshot.png
    4. Print summary: "kept 2/10 attempts, average score 8.4"
```

**Cost of seeding once:** ~10 attempts × ($0.04 vision + $0.05 generation) ≈ $1/cell × 20 cells = **~$20 one-time cost**. We pay this; users get the result free.

### Schema/page agent integration at gen time

```python
# backend/agents/schema_generator.py — modified

def build_schema_agent_prompt(page_brief: PageBrief, registry: Registry) -> str:
    base_prompt = ... # existing

    if REFERENCE_GROUNDING_ENABLED:
        domain = registry.domain  # already established by planner
        page_type = infer_page_type(page_brief)
        exemplars = load_exemplars(domain, page_type, limit=2)
        if not exemplars:
            exemplars = load_exemplars("general", page_type, limit=2)  # fallback
        if exemplars:
            base_prompt += render_exemplars_block(exemplars)

    return base_prompt
```

**Token cost per call:** 2 exemplars × ~3K tokens each = +6K tokens of prompt context. At Sonnet pricing (~$3/M input tokens), +$0.018/call. For a 12-page project: +$0.22 — negligible relative to the loop's render+score costs.

### Page-type inference (deterministic, no LLM)

```python
# backend/services/page_type.py — new

def infer_page_type(page_brief) -> str:
    """Infer one of: list | detail | form | dashboard | settings | generic"""
    route = page_brief.route.lower()
    role = (page_brief.role or "").lower()
    if route.endswith("/list") or route.endswith("/index"): return "list"
    if "[id]" in route or "{id}" in route: return "detail"
    if route.endswith("/new") or route.endswith("/edit"): return "form"
    if "/dashboard" in route or "/overview" in route: return "dashboard"
    if "/settings" in route or "/profile" in route: return "settings"
    if "list" in role or "browse" in role: return "list"
    if "edit" in role or "create" in role: return "form"
    if "metric" in role or "kpi" in role: return "dashboard"
    return "generic"
```

For domains/page-types we haven't seeded, the agent runs without exemplars (existing behavior, no regression).

### Refresh + evolution strategy

- **Manual refresh:** developer runs the seeder when adding a new domain or after substantial component-library / rubric changes.
- **Auto-promote winners:** deferred to a follow-up. The plumbing — using `flags.reference_grounding` + iteration history in `fidelity-log.json` — is in place to support it.
- **Versioning:** `meta.json` includes `seeder_version`. Bumping the version invalidates older exemplars (they keep working, flagged as "v1" in logs).

### Schema agent prompt with grounding (illustrative)

```
You are designing a Page schema for: <page_brief.title>
Domain: <healthcare>
Page type: <list>

EXEMPLARS — top-tier examples for this domain + type.
Match this level of polish, structure, and density. Adapt the entities
and content to this project's brief.

Exemplar 1 (score 8.6):
[full schema JSON, ~3K tokens]

Exemplar 2 (score 8.2):
[full schema JSON, ~3K tokens]

Now design the schema for the user's page. Use the exemplars as anchors.
[rest of existing prompt: registry context, available components, output format...]
```

## 3. Closed-loop runner (Phase 14)

The runner is the orchestrator. It lives in `backend/services/fidelity_loop.py` and is invoked by `routers/generate.py` as a new pipeline phase between `seed` and `QA`.

### Module shape

```python
# backend/services/fidelity_loop.py — new

class FidelityLoopRunner:
    def __init__(self, output_dir, project_ctx, sse_emit, *, concurrency=4):
        self.output_dir = output_dir
        self.project_ctx = project_ctx        # domain, app_name, description, tone
        self.sse_emit = sse_emit              # callable(event_type, data) → None
        self.concurrency = concurrency
        self.cost_tracker = CostTracker(cap_usd=5.0)

    async def run(self, pages: list[PageRef]) -> FidelityReport: ...
    async def _run_one_page(self, page: PageRef) -> PageOutcome: ...
```

`PageRef` carries `(short_id, page_path, page_route, page_type)`. `PageOutcome` carries `(final_score, passed, iterations, status)` where status ∈ `{pass, plateau, budget, regressed_fallback, schema_reprompt_used, failed}`.

### Per-page state machine

```
START
  │
  ▼
iter = 0
render → score → log_iteration(iter=0)
sse_emit("page_score", {page, iter:0, score, pass})
  │
  ▼
─── EXIT IF: score ≥ 8.0 AND no high-severity ─→ status: pass, EXIT ──┐
  │                                                                    │
  ▼                                                                    │
iter = 1                                                                │
patch_iteration():                                                      │
  patch_agent(schema, critique) → patches                               │
  validate_patches(patches, schema) → ok / invalid                      │
  if invalid: retry once with stricter prompt; if still invalid →       │
              reject this iter, log "patch_invalid"                     │
  apply_transactional(patches) → new_schema                             │
  zod_validate(new_schema)  → ok / invalid                              │
  if invalid → reject, restore, log "schema_invalid"                    │
  re-render → re-score → log_iteration(iter=1)                          │
  sse_emit("page_score", {page, iter:1, score, pass})                   │
                                                                        │
  ─── EXIT IF: score ≥ 8.0 AND no high-severity ─→ status: pass, EXIT ─┤
  ─── EXIT IF: |Δscore| < 0.3 from iter 0 → status: plateau, EXIT ─────┤
  ─── EXIT IF: regressed (new < prev - 0.3) ─→ restore, mark regressed ─┤
                                                                        │
  ▼                                                                    │
iter = 2 (same as iter 1; plateau check Δ between iter 1 and iter 2)    │
                                                                        │
  ▼                                                                    │
iter = 3 (LAST patch attempt, same as iter 1)                           │
                                                                        │
  ▼                                                                    │
─── IF 2 consecutive iters were rejected/regressed:                     │
        FALLBACK: schema_agent re-prompt with critique → new_schema     │
        validate → render → score → log_iteration(iter="fallback")      │
        EXIT regardless of result                                       │
                                                                        │
  ▼                                                                    │
log final status, mark failed_fidelity if !pass ──────────────────────→ EXIT
                                                                        │
                                                                        ▼
log_outcome to fidelity-log.json
sse_emit("page_complete", {page, status, final_score})
```

### Concurrency control

Pages process in parallel via an `asyncio.Semaphore(concurrency=4)`. The cap matches the render-service's typical browser-pool size. Each page acquires the semaphore before its first render, releases when its loop exits.

```python
async def run(self, pages):
    sem = asyncio.Semaphore(self.concurrency)
    async def run_with_sem(page):
        async with sem:
            return await self._run_one_page(page)
    outcomes = await asyncio.gather(*[run_with_sem(p) for p in pages])
    return FidelityReport(outcomes=outcomes, total_cost=self.cost_tracker.total)
```

### Cost tracker — the killswitch

```python
class CostTracker:
    def __init__(self, cap_usd: float):
        self.cap_usd = cap_usd
        self.total = 0.0

    def add(self, kind: Literal["vision","patch","schema_reprompt"], tokens_in: int, tokens_out: int):
        cost = compute_cost(kind, tokens_in, tokens_out)
        self.total += cost
        if self.total > self.cap_usd:
            raise BudgetExhausted(f"project cost cap ${self.cap_usd} exceeded")
```

When a page hits `BudgetExhausted` mid-iteration, it exits with `status: budget` and remaining iterations skip. Pages that haven't started yet emit a `page_skipped` SSE event with reason `budget_exhausted` and a placeholder iter-0 entry in the log.

### Per-page wall-clock cap

90s budget enforced via `asyncio.wait_for`. If a single iteration exceeds the per-iter time (~25s) or the loop overall hits 90s, the page exits with `status: timeout` regardless of where in the state machine it is. The current iteration completes if possible (avoid leaving partial-write schemas), then exit.

### SSE event stream during the phase

```
{type: "phase_start", data: {phase: "fidelity_loop", page_count: 12}}

  for each page (interleaved across the parallel set):
    {type: "page_iter_start", data: {page, iter, status: "rendering"}}
    {type: "page_iter_done",  data: {page, iter, score, pass, score_delta}}
    {type: "page_complete",   data: {page, final_score, status, iters_used}}

  on errors / skips:
    {type: "page_skipped",    data: {page, reason: "budget_exhausted" | "timeout"}}

{type: "phase_complete", data: {
  phase: "fidelity_loop",
  passed: 9, failed: 2, skipped: 1,
  avg_score: 7.8, avg_iters: 1.6,
  total_cost_usd: 1.42, wall_clock_s: 87
}}
```

The chat surfaces the summary as: `"Fidelity check: 9/12 passed (avg 7.8). 2 pages flagged for review."` with a click-through to the editor.

### `fidelity-log.json` shape after the runner

```json
{
  "users/list": {
    "iterations": [
      {"iter": 0, "score": 5.2, "issues": [...], "patches": [], "status": "continue"},
      {"iter": 1, "score": 7.4, "issues": [...], "patches": [...], "patches_rejected": 0, "status": "continue"},
      {"iter": 2, "score": 8.3, "issues": [...], "patches": [...], "patches_rejected": 0, "status": "pass"}
    ],
    "final_score": 8.3,
    "final_iter": 2,
    "exit_status": "pass",
    "wall_clock_ms": 52000,
    "cost_usd": 0.18,
    "flags": {"reference_grounding": true, "fidelity_loop": true, "loop_version": "v1"}
  },
  "users/detail": {
    "iterations": [...],
    "final_score": 7.6,
    "final_iter": 3,
    "exit_status": "budget",
    "failed_fidelity": true
  }
}
```

### Integration into routers/generate.py

```python
# backend/routers/generate.py — modified

# ... existing phases through `seed` ...

if config.FIDELITY_LOOP_ENABLED:
    runner = FidelityLoopRunner(
        output_dir=output_dir,
        project_ctx=project_ctx,
        sse_emit=sse_emit,
    )
    pages = registry.get_pages()
    report = await runner.run(pages)
    sse_event("phase_complete", report.summary())

# ... QA, post_generate_fixes, validator, indexer ...
```

If the flag is off, the phase is skipped — existing pipeline runs unchanged. Safe rollout posture for v1.

## 4. Patch agent

The patch agent is a narrow, single-purpose Anthropic agent. Given a critique and the current schema, it emits surgical RFC 6902 patches that target the issues. It does not refactor, does not invent new features, does not restructure the tree.

### Module shape

```python
# backend/agents/patch_agent.py — new
PATCH_AGENT_SYSTEM_PROMPT: str

async def propose_patches(
    *,
    schema: dict,
    critique: Critique,
    app_ctx: ProjectContext,
    strict: bool = False,        # set to True on retry after validation failure
) -> list[PatchOp]:
    """One Anthropic call. Returns the patches the model proposes.
    Caller validates + applies."""

# backend/services/patch_applier.py — new
def validate_patches(patches, schema) -> list[ValidationError]: ...
def apply_patches_transactional(patches, schema) -> dict: ...   # raises on failure
```

The agent itself is just a function — no state. The orchestrator calls it, validates, applies, re-renders, re-scores.

### Input

1. **Current schema as JSON** with `data-node-id` markers visible on every node.
2. **The critique** — same Pydantic `Critique` object the vision evaluator returned. Each issue has `severity`, `axis`, `nodeIdHint`, `issue`, `suggestion`, optionally a `patchOp`.
3. **App context** — domain, app name, description, tone — so word choices match the app's voice.
4. **Component contracts** — scoped to components mentioned in the critique. Critical for emitting valid replacements (e.g. don't emit `Button.content`, use `Button.label`).

### Output

A JSON array of `PatchOp` matching the existing Pydantic shape:

```json
[
  {"op": "replace", "path": "/root/children/0/props/headline", "value": "Track patient appointments"},
  {"op": "add", "path": "/root/children/2/children/-", "value": {
     "id": "stats-tile-3", "type": "MetricTile",
     "props": {"label": "Avg Wait", "value": 23, "format": "duration"}
  }},
  {"op": "replace", "path": "/root/children/3/props/columns/2/render", "value": {
     "component": "Badge", "props": {"variant": "success", "content": "{{item.status}}"}
  }}
]
```

The agent emits a JSON array only, no prose, max 8 patches per call. If the critique surfaces more than 8 issues, the agent ranks by severity and emits patches for the top-8 — the next iteration picks up the rest.

### System prompt — narrow and rule-driven

```
You are a precise code surgeon. Given a UI page schema and a design critique,
emit RFC 6902 patches that fix the issues.

HARD RULES:
- Emit ONLY a JSON array of patch objects. No prose, no markdown.
- Max 8 patches per call. Rank by issue severity.
- Each patch must target a path that resolves in the provided schema.
- Each value must match the v2 prop contract for that component.
- When an issue has a `nodeIdHint`, prefer patches against that node.
- DO NOT add new top-level pages, change the page route, or restructure
  the tree shape unless the critique explicitly says to.
- DO NOT remove existing nodes unless the critique explicitly says to.
- Prefer minimal patches — change one prop at a time when that addresses
  the issue.

SCHEMA STRUCTURE:
- Schemas use a tree where each node has {id, type, props, children?}.
- Paths are JSON pointers — to target Hero's headline at the root's first
  child, the path is "/root/children/0/props/headline".
- To insert at the end of a children array, use "/path/-" with op "add".

COMPONENT CONTRACTS:
[scoped registry block — only components mentioned in the critique
 plus a few of the most common ones]

THE CRITIQUE FORMAT:
[type definitions for Critique, Issue, PatchOp]

Now emit the patches.
```

### Validation — the reliability spine

```python
def validate_patches(patches: list[PatchOp], schema: dict) -> list[ValidationError]:
    errors = []
    for i, p in enumerate(patches):
        # 1. Path resolves (or is a valid insert point for `add`)
        try:
            target = walk_pointer(schema, p.path, op=p.op)
        except PointerError as e:
            errors.append(ValidationError(idx=i, kind="path_unresolved", msg=str(e)))
            continue

        # 2. For replace/add: value type matches the zod type at the target
        if p.op in ("replace", "add"):
            expected_zod = lookup_zod_at_pointer(schema, p.path)
            if expected_zod is not None:
                ok, why = zod_value_compatible(p.value, expected_zod)
                if not ok:
                    errors.append(ValidationError(idx=i, kind="type_mismatch", msg=why))

        # 3. For remove: target must be removable
        if p.op == "remove":
            if is_required_key(schema, p.path):
                errors.append(ValidationError(idx=i, kind="cannot_remove_required", msg=p.path))

    return errors
```

If `errors` is non-empty:
- **First attempt:** retry once with `strict=True` and an extra prompt block: "Your previous patches had these problems: [errors]. Emit corrected patches. Do not include any patch that touched [paths that errored]."
- **After retry:** the iteration is rejected. The runner moves on (or falls back to schema-agent re-prompt after 2 consecutive rejects).

### Application — transactional

```python
def apply_patches_transactional(patches, schema) -> dict:
    working = deepcopy(schema)
    for p in patches:
        try:
            json_patch_apply(working, p)  # via jsonpatch lib
        except Exception as e:
            raise PatchApplyError(f"patch {p} failed mid-apply: {e}")

    # Re-validate full schema against PageV1 | PageV2 zod union
    try:
        page_zod_validate(working)
    except ZodValidationError as e:
        raise PatchApplyError(f"patches produced invalid schema: {e}")

    return working
```

Persisting to disk happens AFTER both apply + zod-validate succeed. If either fails, the schema file on disk is untouched.

### Per-iteration log entry

```json
{
  "iter": 2,
  "score": 7.8,
  "score_delta": +0.4,
  "issues_input": 3,
  "patches_proposed": 5,
  "patches_rejected": 1,
  "patches_applied": 4,
  "validation_errors": [{"idx": 2, "kind": "type_mismatch", "msg": "..."}],
  "patch_summary": [
    "replaced Hero.headline",
    "added Badge to status column",
    "removed empty Card"
  ],
  "status": "continue"
}
```

`patch_summary` is the human-readable changelog the editor displays.

### Cost per call

Patch agent prompt: ~3-5K tokens in (schema + critique + contracts), ~1K tokens out (5-8 patches). At Sonnet pricing: **~$0.02 per patch call**. Across a typical 12-page project with 1.6 avg iters: ~$0.40 of patch-agent cost on top of vision/render costs.

### Why this design is reliable

The agent itself can be wrong — it's an LLM. Reliability comes from **what surrounds it**:

- **Pre-apply validation** catches type/path errors before disk is touched
- **Transactional apply** prevents half-written schemas
- **Post-apply zod validation** catches structural breakage
- **Re-render + re-score** catches "patches addressed symptoms but introduced regression" (Section 3 progress gate)
- **Schema-agent fallback** catches cases where the patch agent is hopelessly stuck

The patch agent only has to be right *most of the time*; the surrounding gates clean up the rest.
**v1 target: ≥80% patch acceptance rate** (4 of 5 patch sets apply cleanly without rejection).

## 5. Editor surfacing

The fidelity loop runs at gen time and writes everything to `output/<id>/src/contracts/fidelity-log.json`. The editor reads from that file — it doesn't re-run scoring on open. Manual re-scoring is preserved for after-edit checks.

### Page tree — score badges

Every page in the schema editor's left tree gets a small score pill showing its final score from the log:

```
📄 Pages
  📁 users
     ├ 📄 list      [8.4 ●]   ← green pill, passed
     └ 📄 detail    [7.6 ⚠]   ← amber pill, failed_fidelity warning
  📁 leave-requests
     ├ 📄 list      [8.1 ●]
     ├ 📄 new       [—]        ← never scored
     └ 📄 detail    [skip]     ← scoring was skipped (budget exhausted)
```

Pill colors mirror the existing `FidelityScoreBadge`:
- **green** (≥ 8.0, passed) — success.50 / success.700
- **amber** (6.0–7.9, didn't pass) — warning.50 / warning.700
- **rose** (< 6.0, didn't pass) — danger.50 / danger.700
- **gray "—"** (never scored)
- **gray "skip"** (skipped due to budget)

Hovering shows a tooltip with `iter X/3 · final 7.6 · status: budget exhausted · 2 high-severity remaining`. Clicking jumps to the Score tab for that page.

### Score tab — switches from "fresh-run" to "log-reader"

Today (Phase 13): clicking "Score now" always renders + scores fresh. After this plan: the Score tab opens with the most recent log entry pre-populated. The user sees the gen-time critique immediately. A "Re-score" button (replacing "Score now") triggers a fresh scoring run.

```
┌─────────────────────────────────────────────────────┐
│ Fidelity Score   [8.4 ●]            [Re-score ↻]    │
├─────────────────────────────────────────────────────┤
│ Latest run:  iter 2 · 2 mins ago · status: pass     │
│                                                      │
│ ┌─Scores─────────────┐  ┌─Strengths─────────────┐   │
│ │ Visual polish 8.5  │  │ ✓ Hero hierarchy     │   │
│ │ Domain feel   8.2  │  │ ✓ Realistic content  │   │
│ │ Info density  8.0  │  │ ✓ Mobile composition │   │
│ │ Coherence     8.6  │  └──────────────────────┘   │
│ │ Brand         8.0  │                             │
│ └────────────────────┘                              │
│                                                      │
│ Top issues (resolved during gen):                   │
│ ⓘ Status column was plain text → patched (iter 1)   │
│                                                      │
│ Iteration history ▾                                  │
│   iter 0: 5.4 → 4 issues found                      │
│   iter 1: 7.4 (+2.0) → patches: replaced Hero...    │
│   iter 2: 8.4 (+1.0) → status: pass                 │
└─────────────────────────────────────────────────────┘
```

### Iteration history view

A new collapsible section in CritiquePanel shows the per-iteration log:

```
iter N · score · Δ · patches applied · status
       ↳ click to expand: shows the full critique JSON, the patches that were applied,
                          and a thumbnail of the screenshot at that iter
```

The screenshots-at-each-iter are the differentiating feature — scrub through "what did the LLM see at iter 0 vs iter 2". The loop saves each iteration's screenshot to `output/<id>/.fidelity-history/<page_path>/iter-<n>.png` (gitignored — large and reproducible). The log entry references these paths.

**Storage cost:** 12 pages × ~3 iter avg × ~200 KB/screenshot ≈ 7 MB per project.

### Failed-fidelity warning state

When `failed_fidelity: true` on a page:

1. **Page tree:** amber pill instead of green
2. **Score tab header:** an `<Alert variant="warning">` banner above the scores: *"This page didn't reach the quality target after 3 iterations. Last 2 unresolved issues: [...]. You can re-score after manual edits, or accept it as-is."*
3. **Chat (during gen, SSE):** the per-page complete event surfaces in chat: *"⚠ Page users/detail flagged for review (final 7.6 — sparse hero, missing status badges)"*

The user has clear agency: ignore the warning, edit + re-score, or come back later.

### Manual re-score (the existing flow, refined)

Pressing "Re-score" still hits the existing `/api/_debug/score-page/<id>` endpoint. Behavior changes slightly:

- The endpoint now appends a new iteration to the existing log entry (rather than replacing). The `iter` number continues from where the gen-time loop left off.
- After-edit re-scores DO NOT trigger the patch agent — manual mode is critique-only. The user keeps the wheel.
- The Score tab updates; a `manual_run: true` flag prevents it from being mistaken for an auto-loop iter.

### Chat surface during generation (SSE-driven)

```
✓ Schemas generated (47s)
✓ Components generated (12s)
✓ Pages generated (28s)

⏳ Fidelity check — 4/12 pages...
  ↳ users/list      iter 0 → 7.2 (continue)
  ↳ users/list      iter 1 → 8.4 ✓ pass
  ↳ leave/new       iter 0 → 5.8 (continue)
  ↳ leave/new       iter 1 → 6.2 (continue)
  ↳ leave/new       iter 2 → 7.8 (plateau)  ⚠ flagged
  ↳ ... 8 more pages running ...

✓ Fidelity check complete:
  9 passed (avg 8.3) · 2 flagged · 1 skipped (budget)
  Total cost: $1.42 · 2m 14s

[Open in editor →]
```

The chat sidebar already streams agent SSE events; this plan adds three new event types (`page_iter_start`, `page_iter_done`, `page_complete`).

### Files modified for editor surfacing

```
frontend/src/components/schema-editor/SchemaEditorPanel.tsx
  + read fidelity-log.json on mount
  + pass per-page score map down to the page tree

frontend/src/components/schema-editor/PageTree.tsx          ← may not exist yet
  + render score pill next to each page name

frontend/src/components/schema-editor/CritiquePanel.tsx     ← exists
  + read from log instead of always-mutating
  + add IterationHistory subcomponent
  + add failed_fidelity Alert banner

frontend/src/components/schema-editor/IterationHistory.tsx  ← new
  + collapsible per-iter rows with screenshot thumbnails

frontend/src/components/chat/ChatHistory.tsx                ← exists
  + render new SSE event types (page_iter_done, page_complete)
```

No new HTTP endpoints — the editor reads `fidelity-log.json` directly via the existing project-files API. Manual re-score uses the existing `/api/_debug/score-page/<id>` endpoint with a small modification (append iter, set `manual_run: true`).

### End-to-end UX

1. User describes their app in chat.
2. Chat streams gen progress; fidelity phase appears as a visible phase.
3. As each page scores, the iteration result streams to chat with a score delta.
4. Chat-final summary: "9/12 passed, 2 flagged, total cost $1.42".
5. User opens the editor — every page already has a badge.
6. Failed pages stand out in amber; user clicks one.
7. Score tab shows the critique, the iteration history (with screenshots), and explains what's still off.
8. User edits the schema, hits "Re-score" → log gets a new iter showing the manual fix.
9. If the manual edit pushes it over 8.0, the badge flips to green.

## 6. Failure modes + telemetry

### Failure mode catalog

Every failure is handled — the pipeline never crashes, and every page lands in `output/` with a clear status. This backs the "successful execution" guarantee.

| Where | Failure | Handling | Surfaced as |
|---|---|---|---|
| **Reference bank seeding** | Strong model can't produce ≥8.0 in `max-attempts` for a cell | Cell stays empty; agents fall back to `general/<page_type>/` | Seeder logs warning; cell can be re-seeded later |
| **Schema agent prompt overflow** | Exemplars push prompt past context window | Drop the lower-scoring exemplar, retry with one exemplar | `pipeline_warning`: "ref grounding reduced to 1 exemplar" |
| **Render-service unreachable** | Service down during fidelity phase | Page exits with `status: render_failed`, `failed_fidelity: true` | Amber badge + "render service was unreachable" tooltip |
| **Render returns 422** | Scaffold can't render the schema (component throws) | Same as above | `status: render_failed` with the error message in log |
| **Vision evaluator returns invalid JSON twice** | Initial + retry parse fails | Iteration rejected; counts toward "2 consecutive rejects" → fallback path | `iteration_status: vision_invalid` |
| **Vision evaluator times out** | API slow / network blip | One retry, then iteration rejected | `iteration_status: vision_timeout` |
| **Patch agent emits unparseable output** | Not a JSON array, or wrong shape | One retry with stricter prompt; if still bad, iteration rejected | `iteration_status: patch_invalid_output` |
| **Patches fail pre-apply validation** | Path unresolved, type mismatch, etc. | One retry with `strict=True` and validation errors in prompt; if still bad, iteration rejected | `patches_rejected: N` in log |
| **Patches apply but break zod** | Result schema invalid | Restore from pre-iter copy; iteration rejected | `iteration_status: schema_invalid` |
| **Score regresses** | New < prev - 0.3 OR new high-severity introduced | Restore from pre-iter copy; iteration marked `regressed` | `iteration_status: regressed` |
| **2 consecutive iter rejects/regressions** | Patch agent stuck | Fallback to schema-agent re-prompt (1 attempt) | `fallback_used: true` in log |
| **Page wall-clock > 90s** | Single page taking too long | Current iter finishes if possible, then exit `status: timeout` | `failed_fidelity: true` + timeout reason |
| **Project cost > $5** | Killswitch | All in-flight iterations finish; pending pages emit `page_skipped` | Chat warning + `fidelity_skipped: budget_exhausted` for skipped pages |
| **fidelity-log.json write fails** | Disk full, permission error | Pipeline keeps running (best-effort persistence); error logged to backend | `pipeline_warning`: "fidelity log not written" — extremely rare |

The cardinal rule: **a fidelity-phase failure never kills the generation**. The phase is best-effort. If the phase itself crashes (unhandled exception in the runner), the existing pipeline catches it as a phase failure and continues to QA + indexer. The editor still loads. Pages just don't have scores.

### Telemetry — what we collect for tuning

`fidelity-log.json` is the per-project authoritative record. Beyond that, the runner emits structured logs to the backend log stream:

```python
# Per-iteration log entry (backend logs, not in fidelity-log.json):
{
  "ts": "2026-05-06T14:32:11Z",
  "project_id": "abc12345",
  "phase": "fidelity_loop",
  "page_path": "users/detail",
  "iter": 1,
  "score_in": 5.2,
  "score_out": 7.4,
  "score_delta": 2.2,
  "patches_proposed": 5,
  "patches_rejected": 0,
  "patches_applied": 5,
  "vision_tokens_in": 4200,
  "vision_tokens_out": 380,
  "patch_tokens_in": 3100,
  "patch_tokens_out": 720,
  "iter_duration_ms": 19400,
  "iter_cost_usd": 0.052
}
```

These let us answer (across projects):
- What's the avg score-delta from iter 0 → iter 1? Is the loop actually moving the needle?
- What's the patch acceptance rate? (target: >80%)
- Which page types regress most? (signal: bad exemplars or bad prompt)
- What's the median wall-clock per page? Are we underestimating budgets?
- Cost distribution — are any projects hitting the $5 cap regularly?

### Tuning telemetry endpoint

```
GET /api/_debug/fidelity-stats?since=2026-05-01
  → {
    projects: 24,
    pages_scored: 287,
    pass_rate: 0.78,
    avg_iters: 1.4,
    median_score: 8.1,
    patch_acceptance_rate: 0.82,
    avg_cost_usd: 1.31,
    cap_exhausted: 2,
    iter_distribution: {0: 89, 1: 124, 2: 58, 3: 16}
  }
```

Behind `FIDELITY_STATS_ENABLED` flag. Not user-facing.

### A/B-testing the flags

`FIDELITY_LOOP_ENABLED` and `REFERENCE_GROUNDING_ENABLED` are independently flag-able. To compare quality with vs without, generate the same project twice with different flag combos and compare resulting `fidelity-log.json` files. The `flags` block records which were on. Useful for measuring: "did Phase 15 alone get us most of the way, or does Phase 14 add real value?" before either becomes default-on.

---

## Success criteria

The plan succeeds when, with both flags enabled, on a representative project:

- **≥75% of pages pass on iter 0** with reference grounding (vs. baseline without grounding).
- **≥90% of pages reach pass after the loop completes** (vs. iter 0 baseline).
- **Patch acceptance rate ≥ 80%** — most patches the agent proposes apply cleanly without retry.
- **Median project cost ≤ $2** — well under the $5 cap.
- **Median per-page wall-clock ≤ 30s** — well under the 90s cap.
- **Editor surface is functional end-to-end** — score badges in tree, iteration history with screenshots, failed_fidelity warnings, manual re-score appending iters.

When all six are true on a sample of 5+ projects, both flags can flip to default-on.

## Dependencies

- **Predecessor plan must be shipped:** `2026-05-06-fidelity-render-loop.md` (Phase 12.5 + 13). ✅ Shipped.
- **Render-service operational:** Playwright pool + cache + FastAPI on port 6502. ✅
- **Vision evaluator operational:** Pydantic Critique model + Anthropic vision call + retry-on-invalid. ✅
- **Render-scaffold operational:** dynamic `/p/<id>/<slug>` route + a11y embed. ✅
- **`anthropic` SDK available** in backend Python env. ✅
- **`jsonpatch` Python lib** — needs adding (small, stable, ~1K LOC).
- **`asyncio.Semaphore` + `asyncio.wait_for`** — built-in, no deps.

## Out of scope (deferred to follow-up plans)

- **Auto-promotion of real generations into the bank.** Curation queue, review UI, version-bumping — separate plan once enough scored projects exist.
- **Per-component patch agents.** Splitting by component family (forms vs tables vs heroes). Premature; v1 single agent should suffice.
- **Multi-viewport scoring during the loop.** v1 scores desktop only. Mobile/tablet doubles cost.
- **Best-of-N parallel generation.** Generating 3 candidates per page and keeping the highest-scoring. Higher cost; only worth it if iteration loop is the bottleneck.
- **Critique-of-critique.** Second model evaluating the vision evaluator. Useful for tuning the rubric, not production.
- **Visual diff viewer in editor.** Side-by-side before/after screenshots per iter. Iteration history with thumbnails (Section 5) is the v1.
- **Per-domain rubric weight tuning.** Fintech weighting `domainFeel` higher than `informationDensity`. Single global rubric for v1.
- **Cost dashboard in project settings.** Backend logs cover this; UI is a follow-up.

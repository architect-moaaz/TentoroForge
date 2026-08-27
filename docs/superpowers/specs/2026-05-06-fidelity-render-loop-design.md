# Closed-Loop Fidelity Render Check — Design Spec

## Goal

Add a vision-based fidelity check to the schema-mode pipeline. After the
schema agent emits a page schema, render the page with stub data via a
headless browser, ask a vision model to score it on a 5-axis rubric, and if
the score is below threshold, generate a JSON Patch via a critique-aware
patch agent and re-render. Iterate up to N times per page. Commit the
highest-scoring version.

This closes the fidelity loop that currently leaks: the pipeline today writes
schemas to disk and trusts them. Visual quality varies — we have no
mechanism to detect or correct a bare/cluttered/inconsistent page before the
user sees it.

## Architecture overview

```
schema agent emits schema
        │
        ▼
render-service.POST /render  ← Playwright-driven, hits the scaffold runtime
        │
        ▼
{ pngBase64, htmlSnapshot, accessibilityTree, ... }
        │
        ▼
vision evaluator             ← Claude vision API, fixed rubric, structured JSON
        │
        ▼
{ scores, compositeScore, pass, topIssues[], strengths, ... }
        │
        ▼
pass?  ── yes ─→ commit schema, log fidelity entry
   │
   no
   │
   ▼
patch agent                  ← consumes critique + current schema, emits JSON Patch
        │
        ▼
apply patch → schema-v2
        │
        ▼
loop (max 3 iterations, plateau detection, budget gates)
```

### Components

1. **render-service** — long-lived FastAPI service, port 6502. Holds a
   Playwright browser instance + browser context pool. Exposes `POST /render`,
   `POST /render-batch`, `DELETE /cache`. Drives the scaffold runtime which
   actually renders project schemas.

2. **scaffold runtime** — single Next.js app (Phase 12 prerequisite). Reads
   project schemas from disk (`output/<id>/src/schemas/<entity>/<page>.json`),
   resources via existing API, and renders. Activates fixtures via
   `?preview=true` query param.

3. **fixtures bank** — three-layer system:
   - Layer 1: curated domain JSON files in `backend/fixtures/<domain>/`
   - Layer 2: Faker-based generation keyed by entity field heuristics
   - Layer 3: type-correct fallback (uuid for `id`, `Lorem ipsum` for `text`)

4. **vision evaluator** — Python service, calls Anthropic Claude vision API.
   Fixed system prompt with 3 calibration anchors (score 3, 6, 8). Returns
   strict JSON validated against a Zod-style schema.

5. **patch agent** — Python service, calls Claude (text). Consumes a
   structured critique + the current schema, emits an RFC 6902 JSON Patch
   that addresses the top 3 high-severity issues without rewriting the whole
   schema.

6. **loop controller** — orchestration logic in
   `services/fidelity_loop.py`. Runs the render → evaluate → patch → re-render
   cycle. Three exit gates: pass, plateau (improvement < 0.3), budget (max 3
   iterations). Logs every iteration to
   `output/<id>/src/contracts/fidelity-log.json`.

7. **integration** — feature_slice_schema_agent calls the loop after emitting
   the initial schema, before writing to disk. SSE events stream score per
   iteration so the editor + chat can surface progress.

## Render service contract

### POST /render

Request:
```json
{
  "projectId": "7zn274s3",
  "pageRoute": "/leave-requests",
  "viewport": "desktop",
  "fixturesProfile": "auto",
  "waitFor": "networkidle",
  "captureMode": "fullPage"
}
```

Response (200):
```json
{
  "pngBase64": "...",
  "pngBytes": 487123,
  "htmlSnapshot": "<post-hydration HTML, < 200KB>",
  "accessibilityTree": "<text outline, < 50KB>",
  "renderTimeMs": 2384,
  "consoleWarnings": [],
  "networkFailures": []
}
```

Error response (422):
```json
{ "error": "render timeout after 15s", "errorScreenshot": "..." }
```

### Performance budget

Per-page render: < 2.5s end-to-end.
- Browser context allocation: 100ms (warm pool)
- Navigation + paint: 1.0s
- networkidle settle: 0.5s
- Screenshot capture: 0.4s
- A11y tree extract: 0.2s
- HTTP wrapping: 0.3s

### Caching

Cache key = SHA-256 of: page schema JSON + active fixture set + scaffold git SHA + viewport + capture options.
Hit returns stored PNG without rendering.
Invalidate on schema rewrite, fixtures update, scaffold version bump, or `DELETE /cache?projectId=...`.

### Error handling

- 15s hard render timeout. On timeout, capture the partial frame.
- Capture console errors + failed network requests; surface them so the
  evaluator can flag "broken render" without scoring layout.
- Never crash the service on a bad page. Each render wrapped in
  try/finally; close context on error; resume serving.
- Always return a screenshot if possible — a blank red error page is more
  useful than a 500 to the loop logic.

## Vision evaluator contract

### System prompt (fixed)

Defines the 5-axis rubric, 0-10 scale calibration anchors (3 = bare/broken,
5 = generic admin, 7 = solid shippable, 8 = premium polish, 9-10 =
industry-leading), composite score weighting (visualPolish 0.25, domainFeel
0.25, informationDensity 0.15, componentCoherence 0.20, brandReflection 0.15),
and pass gate (composite ≥ 8.0 AND no high-severity issues).

Issues must:
- Have a `nodeIdHint` from the page's `data-node-id` attribute when possible
- Be ACTIONABLE (concrete fix, not "looks bad")
- Include `patchOp` (RFC 6902) when the model is confident

### User prompt template

Carries app brief (domain, name, description, tone, optional reference apps),
page context (route, page type, role, iteration N/M), and on iteration > 0,
the previous critique with explicit "flag regressions prominently" guidance.

Attached: screenshot_desktop.png + screenshot_mobile.png + accessibility_tree.txt.

### Output schema

```typescript
type Critique = {
  scores: {
    visualPolish: number;        // 0-10
    domainFeel: number;
    informationDensity: number;
    componentCoherence: number;
    brandReflection: number;
  };
  compositeScore: number;        // weighted mean per system prompt
  pass: boolean;
  topIssues: Array<{
    severity: "high" | "medium" | "low";
    axis: keyof Critique["scores"];
    nodeIdHint: string | null;
    issue: string;               // 1-2 sentence diagnosis
    suggestion: string;          // concrete fix description
    patchOp?: {                  // optional RFC 6902 patch
      op: "add" | "replace" | "remove" | "move";
      path: string;
      value?: unknown;
      from?: string;
    } | null;
  }>;
  strengths: string[];
  designerApprovalRecommended: boolean;
  compareToPrevious?: {
    improved: Array<keyof Critique["scores"]>;
    regressed: Array<keyof Critique["scores"]>;
  };
};
```

### Few-shot calibration anchors

3 anchors pinned in the system prompt (image + critique JSON pairs):
- **Anchor at 3.2** — bare table, no Hero, browser defaults, Lorem ipsum visible
- **Anchor at 6.5** — solid Hero + 2 MetricTiles + plain-text Status column, generic blue primary
- **Anchor at 8.4** — fintech wealth-management list with gradient Hero, 4 MetricTiles + deltas + sparklines, KeyValueList + Repeat-driven Cards, considered typography

Anchors keep score variance to ~±0.5 across runs.

### Robustness tricks

- Pin few-shots in system prompt (not user prompt) — anchors don't change per page; lower per-call cost.
- Add `"reasoning": "..."` (200-word limit) as the first JSON key — improves structured output quality.
- Validate response against a Zod-style schema; on invalid, retry once with the validation error in the prompt.
- Mask the previous score from iteration N+1 to prevent anchoring; pass strengths + weaknesses but not the numeric score.

## Patch agent contract

### Input
- Current schema (post-interpolation, post-normalization)
- Latest critique JSON
- The applied patches from previous iterations (so the agent knows what's been tried)

### Output
- A JSON Patch (RFC 6902) array
- A short rationale string (logged, not used)

### Constraints
- Touch only the nodes named in topIssues[].nodeIdHint where possible
- Never rewrite the whole tree
- Validate the resulting schema against the v2 Page Zod union before returning; on invalid, drop the offending op and retry once

### Why a patch agent vs full regen?
- Cheaper (smaller prompt, smaller output)
- Less oscillation (preserves what scored well)
- Surgical (the user can audit "iteration 2 changed only the Hero")

## Loop controller

### Flow
```python
async def fidelity_loop(project_id, page_route, schema, brief, page_context):
    history = []
    best = (schema, None)  # (schema, critique)
    for iteration in range(MAX_ITER):  # MAX_ITER = 3
        screenshot = await render_service.render(project_id, page_route)
        critique = await evaluate(screenshot, brief, page_context, history)
        history.append(critique)
        emit_sse("fidelity_iteration", { iteration, score: critique.compositeScore })
        # Track best version
        if best[1] is None or critique.compositeScore > best[1].compositeScore:
            best = (schema, critique)
        # Pass gate
        if critique.pass: return schema, critique
        # Plateau gate (no improvement of 0.3+ since previous)
        if iteration > 0 and critique.compositeScore - history[-2].compositeScore < 0.3:
            return best
        # Budget gate
        if iteration == MAX_ITER - 1: return best
        # Iterate
        patch = await patch_agent(schema, critique, history)
        schema = apply_patch(schema, patch)
    return best
```

### Configuration (env vars)
- `FIDELITY_LOOP_ENABLED` (default false during phased rollout)
- `FIDELITY_LOOP_MAX_ITER` (default 3)
- `FIDELITY_LOOP_PASS_THRESHOLD` (default 8.0)
- `FIDELITY_LOOP_PLATEAU_DELTA` (default 0.3)
- `FIDELITY_LOOP_VIEWPORTS` (default "desktop"; alt "desktop,mobile")

### Logging

Per page, append to `output/<id>/src/contracts/fidelity-log.json`:
```json
{
  "page": "leaverequests/list",
  "iterations": [
    { "iteration": 0, "score": 6.4, "issues": [...], "patches": [...] },
    { "iteration": 1, "score": 7.8, "issues": [...], "patches": [...] },
    { "iteration": 2, "score": 8.4, "issues": [...], "pass": true }
  ],
  "final_score": 8.4,
  "final_iteration": 2
}
```

## Fixtures architecture

### Layer 1 — Curated domain banks

Path: `backend/fixtures/<domain>/<EntityName>.json`. Hand-curated, ~10 records each, with realistic and edge-case rows (long names, special characters).

Domains seeded initially: `general`, `healthcare`, `fintech`, `hr`. Others use Layer 2 + 3.

### Layer 2 — Faker per-entity

Generated at render time when a domain bank doesn't cover the entity. Reads the entity's fields from `registry.json` and matches by name + type heuristics:

```
"email"     → faker.internet.email()
"name"      → faker.person.fullName()
"phone"     → faker.phone.number()
"amount"    → faker.finance.amount()
"createdAt" → faker.date.recent()
"status"    → pick from a domain-aware enum
"department"→ pick from a domain-aware list
"id"        → faker.string.uuid()
```

Cached per (domain, entity_signature_hash) so 18 pages don't re-roll.

### Layer 3 — Type-correct fallback

When Layer 1 and Layer 2 can't pick, generate type-correct nonsense: uuid for id-typed fields, "Lorem ipsum dolor sit amet" for text-typed, 0 for number-typed. Bad-looking but renderable. Vision evaluator scores accordingly.

### Scaffold integration

`?preview=true` query string activates a fixtures middleware in the scaffold:
- Intercepts data-source resolution
- Returns fixture records keyed by entity name
- Production ignores the param entirely (or rejects it in non-dev env)

## Scaffold runtime — what changes

The scaffold (Phase 12 prerequisite) needs:

1. A `?preview=true` middleware that swaps `dataSources` resolution for the fixtures provider.
2. A `data-node-id` attribute emitted by every dispatched node (already done in the renderer; verify it survives RSC).
3. An accessibility tree extractor exposed at a debug endpoint or via the rendered HTML's `<script type="application/json" id="__a11y_tree">` (whichever is simpler — Playwright reads either).
4. A boot guard for missing schemas — return a "schema not found" page instead of crashing the runtime.

These are scaffold-side changes captured in Phase 12. The fidelity loop spec assumes Phase 12 is complete.

## Phased rollout

### Phase 12.5 — Render-only baseline (~3 days)
- Stand up `render-service` as a Python FastAPI process
- Bring up Playwright + scaffold runtime; wire `?preview=true` fixtures middleware
- Implement `POST /render` returning PNG + a11y tree
- Editor surfaces a "Preview" tab showing the rendered screenshot next to the schema editor
- No scoring, no loop. Pure visual feedback for humans.

### Phase 13 — Single-shot scoring (~5 days)
- Vision evaluator with the 5-axis rubric + 3 calibration anchors
- Emits structured critique into `fidelity-log.json` per page
- Pipeline does NOT iterate — just records the score for telemetry
- Editor shows the score badge + critique panel
- Designer can manually click "regenerate this page with critique" to trigger one corrective regeneration

### Phase 14 — Closed loop (~5 days)
- Patch agent reads critique, emits RFC 6902 JSON Patch
- Pipeline iterates up to 3 times per page
- SSE events stream score per iteration; user watches it tighten
- Plateau detection + budget gates
- `FIDELITY_LOOP_ENABLED` env flag (default false until proven)

### Phase 15 — Reference grounding (ongoing)
- Curated reference bank: hand-tuned domain-archetype gold standards
- Vision evaluator gets two screenshots: rendered page + closest reference
- Critique becomes "compared to {reference}: ..."
- Bank grows as designers fix pages — every approved fix becomes a new reference

## Failure modes & mitigations

| Failure | Mitigation |
|---|---|
| Vision model hallucinates issues | Cross-validate critical issues with a second model; ignore low-confidence critiques; structured-JSON validation catches many cases |
| Loop oscillates (sparse → cluttered → sparse) | Patch agent only (no full regen) + previous-attempts in prompt + plateau gate |
| Cost runaway | 3-iteration cap; score-floor early termination; batch screenshots in single vision call when possible |
| Subjective drift | Fixed rubric + 3 calibration anchors + temperature 0 |
| Agent over-correction (small critique → full rewrite) | Patch agent emits RFC 6902 ops, not full schema rewrites |
| Reviewer cargo-culting "rich" | Rubric explicitly scores `informationDensity` Goldilocks-style |
| Designer disagrees with score | Manual override flag in editor; logged for prompt-tuning |
| Render times out / partial frame | Capture-on-timeout; evaluator handles "broken render" critique class |
| Fixture data unrealistic for domain | Domain banks (Layer 1); add fixtures for the failing case |
| Stuck on infrastructure (renderer crashes) | Service restarts; cached cache survives; loop-controller catches RenderError and retries once |

## Success criteria

- A new schema-mode generation produces 18 pages with median composite score ≥ 7.5 after the loop runs (vs ≤ 6.0 baseline today).
- ≥ 80% of pages pass the gate (compositeScore ≥ 8.0, no high-severity issues) within ≤ 3 iterations.
- Per-page loop time ≤ 30s end-to-end (render + evaluate + patch + re-render).
- Total per-project loop cost under $1.50 in vision API calls (18 pages × 2 iterations average × $0.04 per vision call).
- Per-iteration delta is observable in the editor as an SSE-driven progress strip.
- Disabled by default via env flag until proven on three test domains (fintech, healthcare, project-management).

## Out of scope (deferred)

- Best-of-N parallel generation (Phase 16 candidate)
- Multi-viewport scoring (Phase 13 starts desktop-only; mobile added in Phase 13.5 if needed)
- Per-component patch agents (one per Hero, one per Form, etc.)
- Automated reference-bank growth from designer edits (Phase 15 manual seed first)
- A/B testing of generated UI variants with real users
- Scoring of generated app behavior (workflows, validations) — only visual

## Dependencies

- **Phase 12 scaffold runtime** — without a single shared scaffold app, render time is too high. The fidelity loop assumes Phase 12 is complete or in progress.
- **Anthropic API access** — Claude vision API key in backend env.
- **Playwright** — new Python dep + browser binary install in the backend image.
- **Faker library** — already a Python ecosystem standard; minimal install.

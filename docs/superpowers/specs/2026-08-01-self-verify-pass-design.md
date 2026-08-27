# Self-Verify Pass — Design Spec

**Date:** 2026-08-01
**Status:** Approved (design) — pending implementation plan
**Scope:** Automatic behavioral testing of every generated Forge app via a
headless-browser runner. Failures are handed to Smith as a structured
FaultReport; Smith fixes what it can through its existing tool surface.
Runs async post-generation (default-on), on-demand from the platform UI, and
on-demand via Smith chat (`verify_app` tool).

---

## 1. Problem

Post-generation the platform emits a Next.js + Postgres app whose contracts
(nav-flow, per-page schemas, plan, registry, workflows) can be individually
valid yet **collectively broken**: a button whose `onClick.workflow` refers to
a workflow that no longer exists; a Table whose `dataSource` name doesn't
match any registered resource; a page whose route is in `nav-flow.json` but
whose schema file was pruned; an SSR page that reads a JSON blob via
`fs.readFile` at runtime that's not in the deploy bundle.

The static half — ~25 post-gen guards + `registry_validator` (11 checks) —
already catches structural drift. What's missing is a **behavioral** check:
does the button actually do anything when clicked? Does the form actually
POST? Does the page actually render without a 500?

Today the answer to "does this app work?" is *"the user finds out."*
`SelfHealCard` reacts once the app has already produced a stack trace in
front of them. This spec proposes catching those defects before the user's
first click.

## 2. Goal & non-goals

**Goal:** After every generation (async), and on demand from the platform UI
or Smith chat, launch a headless Chromium against the generated app, click
every interactive element the schemas declare, assert the expected proof
envelope for each, and — when defects are found — hand a ranked
`FaultReport` to Smith, which fixes what it can through its existing tool
surface and reports back. Convergence in ≤3 rounds.

**Non-goals (explicit follow-ups):**
- LLM-authored test cases beyond what the contracts declare. The test corpus
  is **derived**, not invented; the LLM never designs a test.
- Coverage of anything the schemas don't declare (custom code paths, ad-hoc
  fetch calls, hand-added components without schema representation).
- Load, performance, accessibility, or visual-regression testing. Those are
  separate lanes; this pass is functional correctness only.
- Fixing infrastructural deploy faults (missing env var, quota, wrong
  secret). Deploy verify diagnoses these; Smith fixes only what's in source
  code, the chip prompts the user to republish.
- Nightly / continuous verification of already-shipped apps. Runs only fire
  on the three named triggers (§7).

## 3. Users & jobs

- **The user who just generated an app.** Wants to know it works without
  opening every screen. Sees a chip: *Verifying → Verified* (or *Fixing
  3 issues → Fixed 2, 1 needs you*).
- **The user who just published to Vercel.** Wants to catch the class of
  bug that only appears in production (file tracing, env, RSC manifest).
  Clicks *Verify deployed app* on the publish result.
- **The user mid-chat with Smith.** Says *"verify my app"* / *"why isn't the
  Add button working?"*. Smith calls `verify_app` and acts on the report.
- **Smith itself.** After any mutation via `apply_scope` / `plan_and_apply`
  the runner can re-verify the affected subset before Smith reports done.
  Kills the class of *"I fixed X"* replies that break Y.

## 4. Why now

Three converging enablers:

1. **Preview containers** (B-013) give us an app-under-test host we control —
   already reverse-proxied through the platform, port-managed, restart-safe.
2. **Smith** (S1–S5) has a mature 39-tool surface + git-backed undo + app-map
   context. Handing it a fault is now a first-class operation.
3. **The contracts have stabilized.** `nav-flow.json`, `plan.json`,
   `registry.json`, and `src/schemas/**/*.json` are all authoritative sources
   we can walk deterministically to derive the interaction corpus. Prior
   to Slice 6 (planner emits complete plan schema) this wouldn't have been
   possible without inference.

Also: the observable defect rate is high enough to matter. From this
session's own experience — buttons doing nothing (calculator app), pages
500-ing on ENOENT (workforce app), tables empty because `dataSource`
renamed (dashboard-recent-binding class). All would have been caught by a
one-minute browser run.

## 5. Approach

### 5.1 Overview

```
┌───────────────────────────────────────────────────────────────────┐
│  generate (or Smith edit, or user click)                          │
│         │                                                          │
│         ▼                                                          │
│  interaction_extractor(contracts) → Interaction[]                 │
│         │                                                          │
│         ▼                                                          │
│  forge-verify runner (Playwright)                                  │
│    · target = preview | deploy                                     │
│    · run interactions in bounded parallel                          │
│    · collect FaultReport                                           │
│         │                                                          │
│         ▼                                                          │
│  render(FaultReport) → prompt into smith_agent                    │
│         │                                                          │
│         ▼                                                          │
│  Smith ReAct loop with full tool surface                          │
│    · applies fixes (git-committed per round)                      │
│         │                                                          │
│         ▼                                                          │
│  re-run failing subset (round 2, round 3 max)                     │
│         │                                                          │
│         ▼                                                          │
│  RemediationReport → project event stream → chip UI               │
└───────────────────────────────────────────────────────────────────┘
```

### 5.2 Selected approach: Smith is the sole fixer

Alternative considered and rejected: a **DefectRouter** with a
signature→fixer table (~15 named signatures each dispatched to a specific
post-gen guard, with Smith as fallback). Rejected because:

- Every signature is a maintenance point. The router grows with each new
  defect class; each entry has to be kept in sync with its target fixer's
  API.
- Smith already has the whole toolkit. Its `apply_scope` dispatcher already
  routes intents to seams; the router would be a second, competing
  dispatcher.
- The Fault descriptions we produce for the router make excellent Smith
  prompts. Zero classifier code, better fixes: Smith can chain
  (`check_data_source` → `edit_page`) where a signature table would have
  picked one.

Trade-off accepted: **latency** (Smith is slower than a direct guard call
per fault) and **cost** (LLM tokens per fix). Mitigated by structuring the
FaultReport to give Smith tool hints (§5.4) so it heads straight to the
right seam and doesn't grep-hunt.

### 5.3 Interaction extraction

Pure function `extract_interactions(output_dir) → Interaction[]`.

Sources walked:
- `src/schemas/**/*.json` — the tree of components per page
- `src/contracts/nav-flow.json` — reachable routes
- `plan.json` — workflow trigger_inputs (drives form-fill)
- `registry.json` — resource slugs + column types (drives value synth)

Emitted shapes (typed union):

```ts
type Interaction =
  | { id, kind: "route", route: string, requires_auth: boolean }
  | { id, kind: "button",  route, selector, action:
        | { workflow: string }
        | { navigate: string }
        | { compute: { target, formula } }
        | { none: true }              // "should this even be a button?"
    }
  | { id, kind: "form",    route, selector, fields: FieldSpec[], submit:
        | { workflow: string, inputs: WorkflowInput[] }
        | { dataSource: string }
    }
  | { id, kind: "list",    route, selector, dataSource: string,
      seedMinRows: number }
  | { id, kind: "detail",  route, entity: string, seedRowId: string }
```

`FieldSpec` and `WorkflowInput` carry `type: 'email' | 'uuid' | 'number' | ...`
so the runner can synthesize valid values without invention (email →
`t-<ts>@forge.test`, uuid → random v4, fk → pluck from seed via
`/api/data/<entity>?limit=1`, enum → first value from
`registry.enum_values`).

The extractor is **deterministic and pure** — same contracts always emit
the same list, sorted stably by `(route, path-in-schema)` so `id`s are
reproducible across runs.

### 5.4 Proof envelopes

Each interaction ships a triangulated expectation. The runner asserts
network + DOM + console together — a silent no-op reads as fail.

| Interaction kind | Proof envelope (all must hold) |
|---|---|
| `route` | GET returns 200 (or 307 → login when `requires_auth`), no runtime error in body, schema's top-level heading text present in HTML. |
| `button.workflow` | Network: `POST /api/workflows/<id>/start` within 500ms of click. DOM: pending state visible → resolved. Console: no `Warning`, no `Error`. |
| `button.navigate` | URL becomes `<target>` within 2000ms. Target page renders (200 + heading). |
| `button.compute` | Named target field's value equals the formula re-run in Node with current inputs (uses the same `evaluateComputed` from formInteraction). |
| `button.none` | Fault. A button without an action is broken by definition. |
| `form.workflow` | Fill from `submit.inputs` (type-synth). Submit. `POST /api/workflows/<id>/start` returns 2xx. Toast or redirect within 3s. New workflow_task row appears where the workflow terminates on `user_task` OR expected entity row appears where it terminates on `db_insert`. |
| `form.dataSource` | Fill from `fields` (type-synth). Submit. `POST /api/data/<slug>` returns 2xx with new row's `id`. Row appears in subsequent GET. |
| `list.dataSource` | GET `/api/data/<slug>` returns 2xx. `rows.length >= seedMinRows`. |
| `detail` | GET `/<route>/<seedRowId>` returns 200. Detail fields render values (not `undefined`, not raw `{{binding}}`). |

Every envelope produces a **binary pass/fail plus evidence** — HTTP status,
console entries, network log, DOM snapshot, stack trace if any.

### 5.5 Fault report contract

The runner emits a single `FaultReport` per round:

```ts
type FaultReport = {
  run_id: string
  project_id: string
  round: 1 | 2 | 3
  target: "preview" | "deploy"
  base_url: string
  started_at: iso, finished_at: iso
  interactions_run: number
  interactions_passed: number
  interactions_flaky: number   // passed on retry
  faults: Fault[]              // ranked: BLOCKER > BROKEN > CONTENT
}

type Fault = {
  id: string                    // stable across rounds (== interaction.id)
  interaction: Interaction      // full context
  signature: FaultSignature     // canonical enum, see §5.6
  priority: "BLOCKER" | "BROKEN" | "CONTENT" | "FLAKY"
  layer: "http" | "dom" | "console" | "network" | "timeout"
  evidence: {
    status?: number
    body_excerpt?: string       // first 2KB, redacted
    console?: LogEntry[]
    network_log?: NetworkEntry[]
    dom_snapshot?: string       // outerHTML of interaction target
    stack_trace?: string
    screenshot_uri?: string     // stored in /output/<id>/.forge/verify/
  }
  hypothesis: string            // one sentence
  suggested_tools: string[]     // ordered list of Smith tools most likely to fix
  affected_files: string[]      // best-effort static analysis of what to touch
  seen_in_prior_rounds: string[] // ["run_abc:1","run_def:2"] — helps convergence
}
```

Ranking:
- **BLOCKER**: SSR 500, route 404, deploy failed to build.
- **BROKEN**: click did nothing, form submit 4xx/5xx, workflow doesn't fire.
- **CONTENT**: table empty despite seed, dashboard blank, detail shows raw
  binding text.
- **FLAKY**: passed on retry; recorded but not repaired unless BLOCKER-adjacent.

The report is persisted as JSON at
`/output/<project>/.forge/verify/<run_id>.json` for audit + future
regression comparison.

### 5.6 Fault signatures catalog

Extensible enum. v2 ships with these; each new class we hit becomes a new
signature + hypothesis + suggested_tools row (no code change to router).

```
SSR_500_ENOENT_JSON              → next_config_guard + apply_post_generate_fixes
SSR_500_UNKNOWN_TABLE            → schema_references, workflow_table_guard
SSR_500_MODULE_NOT_FOUND         → next_config_guard (transpilePackages)
ROUTE_404_MISSING_SCHEMA         → add_page (or ensure_create/edit_routes)
ROUTE_401_UNEXPECTED             → auth wiring; unlikely LLM-authored
BUTTON_NO_ACTION_DECLARED        → edit_page (add onClick)
BUTTON_WORKFLOW_MISSING          → add_workflow OR wire_form_to_workflow
BUTTON_NAV_TARGET_MISSING        → navigate_target_guard + add_page
BUTTON_COMPUTE_WRONG_VALUE       → edit_page (fix formula)
FORM_SUBMIT_400                  → wire_form_to_workflow (input mismatch)
FORM_SUBMIT_500_FK               → seed reorder / empty-FK inline-add
FORM_NO_SUBMIT_ACTION            → form_target guard, wire_form_to_workflow
LIST_EMPTY                       → check_data_source, SEED-1 top-up
LIST_DATASOURCE_UNRESOLVED       → read_binding_contract (schema_references)
DASHBOARD_BLANK                  → dashboard_completeness_guard
DETAIL_BINDING_UNRESOLVED        → edit_page (binding path), DV-BIND fixes
CONSOLE_REACT_31                 → binding React #31 safety net
CONSOLE_HYDRATION_MISMATCH       → surface to user (rare, hand-diagnose)
TIMEOUT                          → escalate (runner problem, not app)
UNCLASSIFIED                     → Smith with full evidence
```

Signatures are computed by a **pure classifier** at fault time — no LLM,
just a match against the evidence shape. This makes the catalog easy to
audit and extend as new defect classes emerge.

### 5.7 Runner architecture

**Service**: new `forge-verify` container in `docker-compose.prod.yml`.
- Base image: `mcr.microsoft.com/playwright:v1.48-jammy` (browsers preinstalled)
- Node + a small Fastify orchestrator that exposes:
  - `POST /run` — `{ project_id, target, interactions, base_url, auth }` → run_id
  - `GET /run/:id` — status + `FaultReport` when done
  - `GET /run/:id/stream` — SSE progress events
- Browser pool: 3 warm Chromium contexts, LRU. Cold start ~800ms; warm start ~20ms.

**Target modes**:
- `preview` — hits the backend reverse-proxy at
  `http://backend:6500/api/projects/<id>/preview/serve/`. The generated
  app's Next dev server already runs there per B-013 T4. Fast, ~500ms/click.
- `deploy` — hits the Vercel URL, resolved from the project's most recent
  successful `Deployment` row. Slower (~1500ms/click, DNS + TLS + cold
  Lambda), catches the deploy-only class.

**Auth**: for `requires_auth: true` interactions, the runner first performs
a login using seeded credentials (extracted from `plan.actors[].seed_credentials`
or a well-known seed user), stores the session cookie, and reuses it across
all subsequent clicks in the run.

**Parallelism**: interactions grouped by page, pages run serially per
browser context (so navigation doesn't fight itself), 3 contexts in
parallel across pages. For ~100 interactions across 30 pages → wall-clock
~30-60s in preview mode, ~2-3min in deploy mode.

**Isolation**: every run gets a fresh incognito context per page group so
side effects (created rows, dispatched workflows) don't bleed across
interactions. For `form.workflow` interactions we accept the side effect
(a workflow_task or a db row) and either (a) leave it as evidence the flow
worked or (b) delete it via `DELETE /api/data/<slug>/<id>` post-verification.
Default: leave it — seeded rows already exist, one more doesn't hurt, and
purging can hide regressions.

### 5.8 Smith invocation

New Python module: `services/self_verify_pass.py`.

```python
async def run_self_verify(
    project_id: str,
    *,
    target: Literal["preview", "deploy"] = "preview",
    scope: str = "*",             # "*" or "/route" or "/route/*"
    fix: bool = True,
    invoked_by: Literal["auto_post_gen", "user_ui", "user_chat", "smith_edit"] = "auto_post_gen",
    max_rounds: int = 3,
) -> RemediationReport:
    ...
```

Loop:
1. `interactions = extract_interactions(output_dir, scope)`
2. For round in 1..max_rounds:
   a. `report = await forge_verify.run(interactions, target, base_url)`
   b. If `report.faults == []` → break, success.
   c. If `not fix` → break, return `RemediationReport(diagnose_only=True)`.
   d. `smith_prompt = render_fault_report(report)`
   e. `smith_result = await run_smith_agent(project_id, smith_prompt, mode="verify")`
   f. If Smith made no changes this round → break, escalate.
   g. If `|new_faults| > |prior_faults|` → revert Smith's round commit, escalate.
   h. `interactions = interactions.filter(id in report.faults.map(id))`
3. Return `RemediationReport(rounds_run, fixed, remaining, flaky, escalated)`.

Smith runs with a dedicated system-prompt row for `mode="verify"`:

> **VERIFY MODE**: You are fixing app defects surfaced by an automated test
> run. The FaultReport below is authoritative — every listed fault was
> confirmed by a real click / HTTP call. Do not re-verify by reading files;
> the runner has already reproduced. Prefer the `suggested_tools` for each
> fault. Reply with a Remediation summary listing what you fixed and what
> you couldn't — the runner will re-check.

### 5.9 `verify_app` Smith tool

Registered in Smith's tool catalog:

```python
{
  "name": "verify_app",
  "desc": "Run the Self-Verify Pass on this app. Use whenever the user "
          "asks 'does it work', 'test the flow', 'why isn't X clicking', "
          "'verify my deployed app', or wants confidence the app is green. "
          "DO NOT attempt manual verification via file reads; the runner is "
          "authoritative. Returns a RemediationReport summary.",
  "input_schema": {
    "type": "object",
    "properties": {
      "scope":  { "type": "string", "default": "*",
                  "desc": "\"*\" for whole app, or a route glob like \"/candidates\" or \"/**/edit\"" },
      "target": { "type": "string", "enum": ["preview","deploy"], "default": "preview" },
      "fix":    { "type": "boolean", "default": true }
    }
  }
}
```

Router-prompt row added to `smith_agent`:

> **Verify intent** — "does it work" / "check my app" / "test the flow" /
> "why isn't X clicking" / "verify the deployed app" → `verify_app`. Do
> not read schema files or run other tools first; call `verify_app`, then
> act on its report.

### 5.10 Async event surface

Uses the existing project event stream (Slice 10). New event types:

```
verify.started         { run_id, target, scope, interactions_count }
verify.progress        { run_id, done, total, current_route }
verify.round.done      { run_id, round, faults_count }
verify.smith.thinking  { run_id, thought }         # reuses smith_thought
verify.smith.applied   { run_id, files_changed }
verify.round.reverted  { run_id, reason }          # regression detected
verify.done            { run_id, remediation: RemediationReport }
verify.failed          { run_id, error }           # runner crash, not app fault
```

Frontend chip (extends `SelfHealCard`):

| State | Chip | Color |
|---|---|---|
| in-flight, no faults yet | "Verifying app…" | amber |
| faults found, Smith fixing | "3 issues found — fixing…" | amber |
| all fixed | "Verified" | green |
| some remain | "2 fixed · 1 needs you" | orange, click to expand |
| runner failed | "Verification could not run" | red |

### 5.11 Deploy verify — user-invoked only

Not fired automatically after publish. Two entry points:
1. **Top-level "Verify deployed app" button** on the publish result view
   and in the deployment history panel.
2. **Smith chat** — `verify_app(target='deploy')`.

Fix behavior: **fix-and-report** (approved). If Smith fixes source, the
chip surfaces *"Fixed in source — Republish to see it live"* with a
secondary **"Fix & republish"** button that chains to `POST /publish` and
re-runs `verify_app(target='deploy')` on the new deployment.

Some deploy-only faults (missing env, wrong secret, quota) can't be fixed
by Smith. For these the chip surfaces *"Needs manual fix"* with the
evidence — no auto-fix attempt.

### 5.12 Convergence + regression + rollback

- **Cap**: 3 rounds. Beyond that: escalate as `RemediationReport.escalated[]`.
- **Retry**: each fault retried 2× before entering the report. Marked
  `flaky:true` if 1 of 2 retries passed; not fixed unless BLOCKER-adjacent.
- **Regression**: for each Smith round, `git diff` = the fix commit. If
  round N+1's fault count > round N's, revert the commit
  (`git revert <sha>`), record `verify.round.reverted`, escalate.
- **Deduplication**: same `signature + interaction.id` seen in >=2 rounds
  after Smith attempted → escalate that specific fault (don't retry
  further), continue on others.
- **Stall detection**: Smith round with no on-disk change (mutation-intent
  guard reports 0 files) → escalate all remaining faults, don't retry.
- All commits stamped `[verify:run_<id>:round_<n>]` so they're identifiable
  in `git log` + UX-1 undo timeline.

### 5.13 Metrics

Structured logs + Prometheus counters:
- `forge_verify_runs_total{target, invoked_by}`
- `forge_verify_faults_total{signature, priority}`
- `forge_verify_smith_fixes_total{signature, outcome}`  (outcome ∈ fixed|escalated|reverted)
- `forge_verify_rounds_to_green_histogram`
- `forge_verify_duration_seconds_histogram{target}`

Dashboard: rolling 7-day pass-rate on first run (green from round 1
without any Smith intervention). This is the north-star quality metric —
if it goes up, the generation pipeline is improving; if it goes down,
regressions crept in.

## 6. Integration points in the existing pipeline

- **Post-generation**: `routers/generate.py` — after the final phase's
  `done` SSE, fire-and-forget `asyncio.create_task(run_self_verify(
  project_id, invoked_by="auto_post_gen"))`. Don't await, don't block the
  user-visible completion.
- **Post-Smith-edit**: `services/smith_agent.py` — after `apply_scope` or
  any multi-file mutation returns, if `FORGE_VERIFY_ON_SMITH_EDIT=1`,
  run `run_self_verify(scope=smith_diff.affected_routes, fix=False)`
  synchronously and thread the report back into Smith's own reply as a
  self-check. (Default off — cost concern; toggled per project or globally.)
- **User button**: new endpoint `POST /api/projects/{id}/verify` with
  body `{ target, scope? }`. Streams the runner's event log.
- **Smith chat**: `verify_app` tool → `run_self_verify(invoked_by="user_chat")`.

## 7. When it doesn't fire

- Generation failed (`status=failed`) — nothing to verify.
- Preview container didn't come up within 30s — record `verify.failed`,
  emit chip, no Smith invocation.
- Runner service unreachable — same.
- Feature flag `FORGE_SELF_VERIFY=0` — bypass entirely (rollout kill-switch).

## 8. Rollout

1. **Slice 1-2**: extractor + runner service, no Smith wiring yet.
   `FORGE_SELF_VERIFY=1 FORGE_VERIFY_SMITH_FIX=0` — diagnostic only. Ships
   FaultReport JSON to the project log. **Watch**: fault-rate distribution,
   flake rate, coverage gaps.
2. **Slice 3-4**: Smith wiring + convergence + revert. `FORGE_VERIFY_SMITH_FIX=1`
   for internal projects only.
3. **Slice 5-6**: UI chip, event stream, `verify_app` tool.
4. **Slice 7-8**: deploy-mode button, "Fix & republish", `RemediationReport`
   UI, metrics dashboard.
5. **Slice 9-10**: default-on for all users; hardening; documentation.

Kill switch at every stage: single env flag flips it off.

## 9. Files touched (preview)

**New**:
- `backend/services/interaction_extractor.py`
- `backend/services/self_verify_pass.py`
- `backend/services/fault_report.py` (models + renderer)
- `backend/services/fault_classifier.py` (evidence → signature)
- `backend/models/verify_run.py` (Alembic migration)
- `backend/routers/verify.py` (POST /verify, GET /verify/:id, SSE stream)
- `docker/forge-verify/` (Dockerfile, orchestrator, playwright fixtures)
- `frontend/src/components/SelfVerifyCard.tsx`
- `frontend/src/components/RemediationReport.tsx`
- `docs/superpowers/plans/2026-08-01-self-verify-pass.md` (this spec's slice plan)

**Edited**:
- `backend/services/smith_tools.py` — register `verify_app`
- `backend/services/smith_agent.py` — verify-mode system prompt row, router row
- `backend/routers/generate.py` — post-generation fire-and-forget hook
- `backend/routers/deployments.py` — expose "Verify deploy" endpoint
- `docker-compose.prod.yml` — add `forge-verify` service
- `frontend/src/hooks/useProjectEvents.ts` — handle `verify.*` events

## 10. What Smith cannot fix (surface, don't loop)

Explicit escalation classes:
- Deploy env missing / wrong secret (needs user action in Vercel dashboard
  or `/settings/integrations`).
- Vercel build failed for a reason outside our template (rare — usually
  npm registry hiccup).
- Runner-internal failure (timeout on browser launch, network to Vercel
  URL blocked). Not an app fault.
- Any fault whose `signature=UNCLASSIFIED` that Smith attempted 2× without
  reducing fault-count. Report with full evidence, let the user decide.

These land in `RemediationReport.escalated[]` with a short explanation the
UI can render as-is.

## 11. Open questions

None load-bearing. Two design details deferred to implementation:
- **Screenshot storage** — where verify screenshots live long-term. For v2:
  local `/output/<id>/.forge/verify/`, LRU-purged at 100 MB. If we want
  cross-project comparison later, move to S3 via platform_integrations.
- **Verify-on-Smith-edit rollout** — the per-edit auto-verify (§6) is
  gated off in v2. Enabling adds latency to every Smith turn. Revisit
  after we see the first-week fault-rate distribution — if Smith regresses
  things often, flip on; if rarely, leave off.

## 12. Success criteria

1. **Coverage**: for a typical 30-page app, extractor emits ≥95 interactions
   with no manual annotation.
2. **Preview run time**: end-to-end round 1 under 60s wall-clock for the
   above app.
3. **First-run pass-rate**: rolling 7-day metric climbs vs. baseline
   (baseline = post-gen guards only, measured before rollout).
4. **Convergence**: for apps with N faults in round 1, ≥70% reach 0 faults
   in ≤3 rounds; escalations documented with actionable evidence.
5. **Zero silent-regressions**: no fix that reduces round-N fault-count
   below round-(N-1) is reverted (i.e. Smith isn't gaming the metric).
6. **UX**: chip visible within 2s of generation completion; total
   verification never blocks the user from opening the app.

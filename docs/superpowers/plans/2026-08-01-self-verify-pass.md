# Self-Verify Pass — Implementation Plan

**Design spec:** [2026-08-01-self-verify-pass-design.md](../specs/2026-08-01-self-verify-pass-design.md)
**Estimate:** ~2 weeks (~10 working days), broken into 10 slices.
**Rollout:** feature-flag-gated per slice; kill switch at every stage.

## Slicing rationale

Every slice is independently shippable and independently valuable — no
slice ships broken code even if the next one never lands. Slice N's
acceptance criteria never depend on slice N+1 existing. Ordered so the
diagnostic path is usable before the fix path, so we can validate the
runner against real generated apps before Smith gets involved.

## Global acceptance for the sprint

Once all 10 slices land:
- Every generation triggers async Self-Verify, chip shows outcome
- Smith fixes classified fault classes within 3 rounds for ≥70% of apps
- Deploy-verify button ships in the publish view
- `verify_app` Smith tool works from chat
- Pass-rate metric is graphed in Prometheus

---

## SV-1 · Interaction extractor (pure module)

**Files:** `backend/services/interaction_extractor.py` (new) + tests.

**Scope:** Pure function `extract_interactions(output_dir, scope="*") -> Interaction[]`.
Walks `nav-flow.json`, `src/schemas/**/*.json`, `plan.json`, `registry.json`.
Emits the typed union defined in spec §5.3, sorted deterministically by
`(route, path-in-schema)`.

**TDD:**
- Given a fixture app with 3 routes / 5 buttons / 2 forms / 4 lists →
  extractor returns exactly the expected 14 Interactions with stable IDs.
- Buttons with `onClick: undefined` classified as `{action: {none: true}}`.
- Form field types propagated from registry column types.
- `scope="/dashboard"` filters correctly.

**Acceptance:**
- 20+ unit tests, including one full-fixture app snapshot test.
- Runs against 3 real UAT projects, prints stats (routes / buttons /
  forms / lists). Coverage ≥95% of user-facing interactions in each.

**Estimate:** 1 day.

---

## SV-2 · Fault classifier (pure module)

**Files:** `backend/services/fault_classifier.py` (new) + tests.

**Scope:** Pure function `classify(evidence) -> FaultSignature`. Match
tables per spec §5.6. Zero LLM, zero I/O.

**TDD:**
- 30+ evidence-shape fixtures, each asserts the expected signature.
- Unknown patterns → `UNCLASSIFIED`, not a wrong label.
- Each signature ships a `hypothesis` and `suggested_tools` list.

**Acceptance:**
- Classifier covers 15 named signatures + `UNCLASSIFIED` fallback.
- Test fixtures live under `backend/tests/verify/fixtures/` — organized
  so adding a signature = adding one fixture pair.

**Estimate:** 0.5 day.

---

## SV-3 · Playwright runner service

**Files:** `docker/forge-verify/` (new): `Dockerfile`, `orchestrator.ts`,
`playwright.config.ts`. `docker-compose.prod.yml` (add service).

**Scope:** Fastify service exposing `POST /run`, `GET /run/:id`,
`GET /run/:id/stream` (SSE). Warm browser pool (3 contexts, LRU). Runs
interactions with the proof envelopes from spec §5.4. Emits a
`FaultReport` (via classifier from SV-2) at completion. **Preview target
only in this slice** — deploy mode is SV-8.

**TDD:**
- Vitest suite against a fixture Next app with intentional defects (dead
  button, empty list, SSR 500). Runner emits expected FaultReport.
- Retry logic: fault surfaces once → passes on retry → marked flaky.
- Timeout: page that never responds → `TIMEOUT` signature, not hung
  runner.
- Browser pool: 10 concurrent runs share 3 contexts without crashes.

**Acceptance:**
- `docker-compose up forge-verify` starts service; `POST /run` returns
  run_id; polling `GET /run/:id` eventually returns a valid FaultReport.
- End-to-end against a real UAT preview: emits report in <60s for a
  30-page app.

**Estimate:** 2 days.

---

## SV-4 · Runner ↔ backend integration + persistence

**Files:** `backend/services/forge_verify_client.py` (new),
`backend/models/verify_run.py` (new + Alembic migration),
`backend/routers/verify.py` (new: `POST /api/projects/{id}/verify`,
`GET /api/projects/{id}/verify/{run_id}`, SSE `.../stream`).

**Scope:** Python client that speaks to the `forge-verify` service.
Persistence: `verify_runs` table (id, project_id, target, started_at,
finished_at, faults_json, status). REST + SSE surface for the frontend.
**Diagnose-only in this slice** — no Smith invocation yet, `FORGE_VERIFY_SMITH_FIX=0`.

**TDD:**
- Async test: client hits mock runner, streams events, persists row.
- Runner unreachable → status=`runner_failed`, chip surfaces gracefully.
- Concurrent runs on the same project → serialized (later wins),
  earlier marked `superseded`.

**Acceptance:**
- Hit the endpoint from curl against a real UAT project, get an SSE
  stream, see a row in the DB, GET the report.

**Estimate:** 1 day.

---

## SV-5 · Auto post-generation trigger (async, diagnose-only)

**Files:** `backend/routers/generate.py` (edit — post-completion hook).
Feature flag `FORGE_SELF_VERIFY` (default 1) + `FORGE_VERIFY_SMITH_FIX`
(default 0 until SV-6).

**Scope:** After the pipeline's final `done` SSE, fire-and-forget
`asyncio.create_task(run_self_verify(project_id, invoked_by="auto_post_gen"))`.
Does not block user-visible completion. **Diagnose-only** — writes report,
emits event, no fix loop.

**TDD:**
- Test that generation completes even if runner is down (fire-and-forget
  swallows).
- Test that verify starts within 500ms of the `done` SSE.
- Feature flag off → no verify task spawned.

**Acceptance:**
- Run a full UAT generation; verify report auto-appears in DB within
  ~90s. No user-visible latency added to generation.

**Estimate:** 0.5 day.

---

## SV-6 · Fault report renderer + Smith wiring

**Files:** `backend/services/fault_report.py` (new: models +
`render_for_smith(FaultReport) -> str`), `backend/services/smith_agent.py`
(edit: add `mode="verify"` system-prompt row), `backend/services/self_verify_pass.py`
(new: the loop from spec §5.8).

**Scope:** Take a FaultReport, render it as a structured markdown prompt
per spec §5.5, invoke Smith with `mode="verify"`, thread the response back.
Introduces `run_self_verify()` orchestrator. **Fix loop enabled** —
`FORGE_VERIFY_SMITH_FIX=1` under a per-project allowlist first.

**TDD:**
- Renderer test: FaultReport with 3 varied faults → markdown matches
  golden fixture, ranked correctly, tool hints present.
- Loop test with mocked Smith: runner returns 3 faults → Smith is called
  with rendered prompt → runner re-called → convergence recorded.
- `fix=False` → loop returns after round 1 without invoking Smith.

**Acceptance:**
- Live test on an intentionally-broken generated app: Smith fixes ≥1
  fault, chip shows `Fixed 1 · 2 remain` accurately.

**Estimate:** 1 day.

---

## SV-7 · Convergence + regression + auto-revert

**Files:** `backend/services/self_verify_pass.py` (extend).

**Scope:** The safety logic from spec §5.12. 3-round cap. Regression
detector (round N+1 faults > round N → revert Smith's commit via
`git revert`, mark escalated). Stall detection (Smith made no changes →
break). Dedup: same signature+interaction across rounds → escalate
individually. Commit stamping (`[verify:run_<id>:round_<n>]`).

**TDD:**
- Fake Smith that always makes fault-count worse → revert fires, run ends
  with escalation.
- Fake Smith that fixes some, breaks none → converges cleanly.
- Fake Smith that plateaus (fixes nothing) → stall detected, break.
- All persisted commits carry the stamp.

**Acceptance:**
- Live test with an app that has a "poison" fault (unfixable): loop
  escalates cleanly in 2 rounds, no infinite spin.

**Estimate:** 1 day.

---

## SV-8 · Deploy-mode target + top-level UI button

**Files:** `docker/forge-verify/orchestrator.ts` (extend runner to accept
`target: "deploy"` with a base URL + session auth). `backend/services/self_verify_pass.py`
(pass `target` through). `backend/routers/deployments.py` (edit:
`POST /api/projects/{id}/deployments/{deploy_id}/verify` — endpoint the
button calls). Frontend: new "Verify deployed app" button in publish
result view + deployment history panel.

**Scope:** Deploy verification. Runner authenticates against the Vercel
URL using seeded credentials (or platform login relay). Fix-and-report
behavior per spec §5.11 — Smith fixes source, chip prompts republish.
Secondary "Fix & republish" button chains to `POST /publish` and re-runs
verify on the new deployment.

**TDD:**
- Runner integration test with a mock Vercel URL.
- Backend endpoint auth: only project members can invoke.
- Fix-and-republish chain: intentionally-broken deploy → verify → Smith
  fixes source → republish → re-verify → green.

**Acceptance:**
- Live E2E on the workforce app (the one from the ENOENT session): click
  "Verify deployed app" → chip shows fault → Smith fixes vercel.json →
  chip prompts republish → click → next deploy verifies green.

**Estimate:** 1.5 days.

---

## SV-9 · `verify_app` Smith tool + chat routing

**Files:** `backend/services/smith_tools.py` (edit: register `verify_app`),
`backend/services/smith_agent.py` (edit: verify-intent router row).

**Scope:** Register `verify_app(scope, target, fix)` in Smith's tool
catalog per spec §5.9. Add the router-prompt row so Smith reaches for it
on natural-language cues. Composable with `plan_and_apply` for
"regenerate the recruiters flow and verify it" style asks.

**TDD:**
- Router test: "verify my app" → tool call fires.
- Router test: "why isn't the Add button clicking" → tool call fires
  with `scope` inferred from the button's route.
- Router test: "verify my deployed app" → tool call fires with
  `target='deploy'`.

**Acceptance:**
- Live UAT test: chat "verify my app" → Smith calls tool → runner runs →
  chat reply summarizes the RemediationReport.

**Estimate:** 0.5 day.

---

## SV-10 · Chip UI + RemediationReport surface + metrics

**Files:** `frontend/src/components/SelfVerifyCard.tsx` (new — extends
SelfHealCard shell), `frontend/src/components/RemediationReport.tsx` (new),
`frontend/src/hooks/useProjectEvents.ts` (edit: handle `verify.*`),
`backend/services/self_verify_pass.py` (metrics counters per spec §5.13).

**Scope:** Chip states per spec §5.10 (amber → green / orange / red).
Click chip → RemediationReport panel: fault list grouped by priority,
each fault expandable to show evidence (screenshot, network log, console).
Prometheus counters: runs_total, faults_total, smith_fixes_total, rounds_histogram, duration_histogram.

**TDD:**
- Component tests for each chip state.
- RemediationReport renders all fault fields correctly for each priority.
- Metrics test: fire a run, assert counters incremented.

**Acceptance:**
- Full UAT walk-through: generate app → chip appears amber →
  transitions to green or orange as fixes land → click orange chip →
  see report → each fault has actionable evidence.
- Prometheus dashboard shows first-week pass-rate baseline.

**Estimate:** 1 day.

---

## Cross-slice concerns

**Feature flags** (all default off until their slice ships):
- `FORGE_SELF_VERIFY` — master (SV-5 flips on)
- `FORGE_VERIFY_SMITH_FIX` — enable Smith mutation (SV-6 flips on for
  allowlist, SV-10 flips on for everyone)
- `FORGE_VERIFY_ON_SMITH_EDIT` — per-edit auto-verify (default off,
  revisit post-launch)
- `FORGE_VERIFY_DEPLOY_ENABLED` — hides deploy button until SV-8

**Test tiers**:
- Unit — every pure module (extractor, classifier, renderer)
- Integration — runner service against fixture Next apps
- Live — UAT E2E per slice's acceptance criteria

**Rollback**: every slice is behind its feature flag; flipping to 0
reverts behavior to pre-slice. No slice writes to shared state that
can't be reverted with `git revert <slice_commit>`.

**Docs**: each slice PR includes a one-paragraph BLUEPRINT note + updates
IMPLEMENTED_FEATURES.md. Signature catalog + tool hints (§5.6) get their
own reference doc for future contributors adding fault classes.

---

## Total estimate: 10 days

| Slice | Days | Cumulative |
|---|---|---|
| SV-1 extractor | 1.0 | 1.0 |
| SV-2 classifier | 0.5 | 1.5 |
| SV-3 runner service | 2.0 | 3.5 |
| SV-4 backend integration | 1.0 | 4.5 |
| SV-5 auto trigger (diagnose) | 0.5 | 5.0 |
| SV-6 Smith wiring | 1.0 | 6.0 |
| SV-7 convergence + revert | 1.0 | 7.0 |
| SV-8 deploy mode + button | 1.5 | 8.5 |
| SV-9 verify_app tool | 0.5 | 9.0 |
| SV-10 chip UI + metrics | 1.0 | 10.0 |

**Milestones**:
- **End of SV-5** (day 5): diagnostic mode live in production. Every
  generation gets a report; nothing is auto-fixed yet. Enough to see
  the fault-rate baseline.
- **End of SV-7** (day 7): closed-loop for internal projects. Smith
  fixes, regressions revert, convergence hardened.
- **End of SV-10** (day 10): default-on for all users. Deploy button
  live. Chip in the UI. Metrics graphed.

## Risks

1. **Playwright flake on the actual runner** — real browser tests have
   real flake. Mitigations: retry-once policy, flake tracking as its own
   category, isolated browser contexts per page group. If flake rate on
   pass-rate metric > 5%, add a third-retry rule before shipping default-on.
2. **Smith cost / latency spike** — verify loops call Smith with a large
   FaultReport prompt. Mitigations: prompt-caching (already enabled),
   truncate evidence per fault to 2KB, cap 3 rounds hard.
3. **First-run baseline is dismal** — likely, since we've never measured
   real-app pass-rate. Not a risk to the loop itself, but shapes the
   messaging (SV-10 chip needs to gracefully surface "many issues found"
   without alarming the user).
4. **Deploy verify hits Vercel rate limits** if a user hammers "Verify
   deployed app". Mitigation: server-side debounce (max 1 in-flight
   deploy-verify per project) + UI disable-during-flight.

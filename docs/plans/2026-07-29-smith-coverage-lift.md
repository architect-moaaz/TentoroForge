# Smith coverage-lift roadmap

Target: lift Smith's coverage of the 136-case UAT test spec from
**39% full / 40% partial / 21% miss** → **72%+ full**.

Delivered in phases so we can stop at any healthy plateau. Each phase
is independently mergeable and ships behind an env flag until it's
proven on UAT.

## Design principles

- **Scoped toolsets, not sub-agents** for the highly-repeatable narrow
  case (e.g. "add a column"). Router-in-front-of-one-agent, not
  many-agents. Cheaper (2 LLM calls vs 4), preserves cross-domain
  context for feature adds.
- **Same-loop context preservation** for ambiguous / cross-domain
  asks. `plan_and_apply` stays as the composite path.
- **Full agent split reserved** for the "wildly different toolchains"
  case (browser-exec, code-exec, SQL sandbox). Deferred until we
  actually need it — see Phase 7 promotion trigger.

## Phase 0 — Foundations (SHIPPED 2026-07-29)

Hard intent classifier + scoped tool dispatch. Everything else plugs
into this.

**Files:**
- `backend/services/intent_classifier.py` (new) — `classify_intent()`
  returns `Intent{intent, domain, target, tools, confidence}`. LLM call
  is structured, deterministic tool-subset derivation. Failure modes
  degrade to `None` (no scoping, full catalog).
- `backend/tests/test_intent_classifier.py` (new) — 17 tests: contract
  shape, LLM parsing, fallbacks, confidence clamping, key intents.
- `backend/agents/smith_agent.py` — `run_smith_agent(..., scoped_tools=)`
  added; filters the catalog offered to the LLM AND enforces at
  dispatch (defense-in-depth refusal for out-of-scope tool calls).
- `backend/routers/generate.py` — classifier gated behind
  `FORGE_SMITH_CLASSIFIER=1`. When off: today's behavior verbatim.
- `backend/tests/test_smith_scoped_tools.py` (new) — 4 tests: full
  catalog by default, filtered on `scoped_tools=`, dispatch refuses
  out-of-scope, in-scope passes through.

**Test coverage lifted**: ~15 (Add/Update/Fix cases moved from partial
→ full when the classifier picks the right subset and Smith runs on 5
tools instead of 39).

**Rollout**: dark-launch with `FORGE_SMITH_CLASSIFIER=0` on UAT to see
classifier logs; flip to `=1` when metrics look good.

## Phase 1 — High-leverage primitives (~1 week)

Three small primitives, each lifts a whole test category.

### 1a — `confirm_destructive` gate
- New state field `pending_confirmation: {kind, target, impact_summary}`
  on Smith turn.
- Destructive tools (`remove_page`, `remove_component`, `add_entity`
  with delete-and-recreate) refuse until pending_confirmation resolved.
- Next user turn "yes"/"no" resolves it (chat-history + a small
  parser).
- **Lifts**: Remove-destructive (8) + ambiguous #58 + adversarial #108
  = **10 tests**.

### 1b — `revert_last_patch` tool
- New tool + `services/patch_history.py`. Reads project version log
  (versions table already exists — B-016) and reverses the last commit
  atomically.
- Handles "undo that", "actually no, don't do that".
- **Lifts**: Ambiguous #60 + memory #80 sharpening + memory #85 = **3
  tests**.

### 1c — Durable preferences
- New `smith_preferences` table (org × user).
- `set_preference` + `get_preferences` tools.
- Loaded at Smith turn ingress, injected as system-prompt hint
  ("user prefers: confirm on delete").
- **Lifts**: Memory 81, 82, 86, longitudinal 132–135 = **7 tests**.

**Cumulative full %**: ~54%.

## Phase 2 — Auto-trigger heuristics (~3 days)

Smith proactively runs the generative pipeline when the app is in a
stable milestone state.

- `services/auto_generate_gate.py` — decides trigger vs defer.
- Triggers: milestone complete (plan_and_apply finished, no pending
  confirmations, no validation errors); idle (5-min + last patch ≥30s
  ago); session-end intent ("that's all for today").
- Blockers: rapid iteration (>3 patches to same target in 60s), plan
  mid-flight, validation errors open.
- **Lifts**: Generative Pipeline 72–77 = **6 tests**.

**Cumulative full %**: ~58%.

## Phase 3 — Business Rules pre-commit gate (~1 week)

Explicit invariant checks run BEFORE any mutation seam commits.

- `services/invariant_catalog.py` — enumerated invariants: password-plaintext,
  dangling-nav, unknown-token, duplicate-route, missing-required-field,
  orphaned-binding, unbound-form-target.
- `services/mutation_preflight.py` — runs on every mutating tool call.
  Returns `ok` or `blocked(rule, explanation, suggestion)`.
- Smith prompt update: on blocked patch, relay rule + suggestion in
  plain language.
- **Lifts**: Validation/Business Rules 88–94 = **7 tests**.

**Cumulative full %**: ~63%.

## Phase 4 — In-flight plan mutation (~2 weeks)

`plan_and_apply` grows a live-plan API.

- `plan_state` object persisted per project during plan execution.
- `patch_plan(step_index, new_args)` — "actually make it blue"
- `append_plan(new_step)` — "add one more page to that plan"
- `cancel_plan(from_index)` — "cancel the rest"
- `reorder_plan(new_order)` — "wait, do cart first"
- Auto-repair: when DB rename lands, downstream step args are rewritten
  to use the new name.
- **Lifts**: Re-planning 95–100 = **6 tests**.

**Cumulative full %**: ~67%.

## Phase 5 — Concurrency (~2 weeks, deferrable)

Most expensive phase. Deferrable if the app isn't multi-user in UAT.

- Patch idempotency key on every mutation tool.
- Server-side patch log with version numbers.
- Optimistic-concurrency check.
- Cross-session undo lookup.
- **Lifts**: Concurrency 115–119 = **5 tests**.

**Cumulative full %**: ~71%.

## Phase 6 — Role/auth seams (~2 days)

- `add_role` seam (Test 14).
- `remove_role` with impact analysis (Test 33).
- `restrict_page_to_role` seam (Test 48).

**Cumulative full %**: ~72%.

## Phase 7 — Full agent split — DEFERRED

Do NOT split until one of these triggers hits:

1. **New toolchain that can't live in a single LLM's context.**
   Examples: Playwright browser-exec, SQL-exec sandbox, code
   interpreter sandbox.
2. **A specific specialist's context exceeds 50% of the model window.**
3. **Independent parallelism becomes valuable** — e.g. "audit my
   schema in parallel with generating browser tests".

**Promotion mechanics when triggered:**
- Split ONE specialist first, not all four. Prove it.
- Keep the Phase 0 classifier — it becomes the router.
- Add message-passing between Smith and specialist.
- Add lock manager on shared state.
- Duplicate guardrails (mutation-intent, overclaim, deploy-intent) into
  the specialist.

**Estimated effort when triggered**: 2 weeks per specialist.

## Stopping points

- **After Phase 3 (~4 weeks): 63% full.** Covers all Add/Update/Fix/
  Remove/Business-Rules bread-and-butter. Most UAT bugs go away.
- **After Phase 4 (~6 weeks): 67% full.** Adds re-planning polish.
  Good pause for review.
- **After Phase 6 (~9 weeks): 72% full.** Adds concurrency + roles.
  Only worth it if UAT goes multi-user.

## What each phase does for the two edge cases

| Case | Today | After Phase 0 | After Phase 7 (if triggered) |
|---|---|---|---|
| Highly repeatable narrow ("add a column") | 🟡 wide tool distraction | ✅ Scoped 3–5 tool subset via classifier | (same) |
| Wildly different toolchains (SQL vs browser vs code exec) | ❌ can't hold both | ❌ still can't | ✅ Clean split with promotion checklist |

Phase 0 solves the narrow-specialist case immediately — no multi-agent
overhead. Phase 7 solves the different-toolchains case only when we
actually need it.

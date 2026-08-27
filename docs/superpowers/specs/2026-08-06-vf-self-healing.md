# V&F 2.0 — Self-Healing Generator

**Date:** 2026-08-06
**Owner:** V&F pipeline
**Status:** Approved for implementation (M1 → M2 → M3)

## Problem

Today's Verify & Fix runs Playwright over 93 interactions, classifies faults into ~6 buckets, and routes them through **4 seam handlers** (`workflow-definition`, `workflow-output-mapping`, `auth-seed`, `form-or-page-or-component`). Three of them do targeted work; the fourth is a "rerun the whole post-gen suite" sink.

Coverage is roughly 30% of the fault classes we see in a typical generated app. The rest — 500 errors, missing pages, dead data fetches, React #31 crashes, wrong bindings, unresponsive pages — fall into `residual_hints` and are surfaced to the user for Smith to handle in a follow-up turn.

The intent of V&F is stronger: **if a fault is Playwright-observable and its root cause is reachable through a Smith tool, autofix should resolve it without user involvement.**

## Vision

V&F becomes a **fault-class-agnostic self-healing loop**:

- **Broad classifier** — read the fault's evidence (status, stack, console, network, DOM) and tag it with a cause (`missing-page`, `data-fetch-failure`, `render-error`, `binding-crash`, etc.), not just a symptom.
- **Two-tier dispatcher** — deterministic handlers for well-understood classes (fast, cheap, safe); Smith dispatcher for judgment-call classes (context-rich, LLM-authored).
- **Fault context builder** — hand Smith a curated slice of the app (page schema, page code, related entities, recent edits, tool subset) so it can reason about the fault instead of guessing.
- **Convergence + regression guard** — up to 3 rounds; auto-revert a round if pass rate drops.
- **Per-class visibility** — the chip shows what class of faults are being healed and which residuals remain for the user.

The existing 4-handler path stays as the fast path. Everything else is additive.

## Architecture — three new layers

### Layer A — Rich fault classifier

**File:** `backend/services/journey_verifier/fault_classifier.py`

Input: a `FaultRaw` (already exists — has `interaction`, `evidence`, `passed`, `flaky`).
Output: a `ClassifiedFault` with `class_name`, `seam`, `evidence_slice`, `needed_context: list[str]`.

Class taxonomy (initial 10, extensible):

| Signal | class_name | seam |
|---|---|---|
| status 500 + Next.js `Error:` in body | `render-error` | `smith:render` |
| status 500 + `relation "x" does not exist` in body/console | `db-schema-mismatch` | `deterministic:db-migrate` |
| status 404 + route present in `routesRegistry.ts` | `catch-all-router-broken` | `deterministic:router-regen` |
| status 404 + route NOT in registry | `missing-page` | `deterministic:add-page` |
| status 200 + `Failed to load resource: 500` in console | `data-fetch-failure` | `smith:data-fetch` |
| status 200 + `Minified React error #31` | `binding-crash` | `smith:binding` |
| status 200 + rendered_widget_count=0 + entity exists in schema | `list-empty-data` | `deterministic:rewire-datasource` |
| status 200 + form submit dispatches nothing | `form-not-wired` | `deterministic:orphan-wiring` |
| Playwright hard-timeout (>45s) | `page-unresponsive` | `smith:render` |
| status 401 + login form failed | `auth-broken` | `deterministic:auth-seed` |

Unknown patterns → `class_name="unknown"`, `seam="residual"` (surfaced to user, not dispatched).

Pure functions, no I/O. TDD required.

### Layer B — Two-tier dispatcher

**File:** `backend/services/journey_verifier/autofix.py` (extend existing)

Existing 4 handlers stay. New handlers registered under the same `_SEAM_HANDLERS` dict:

- `deterministic:add-page` — call `add_page` seam (already exists in `smith_tools.py`) with route + inferred kind (list/create/edit/detail from URL pattern).
- `deterministic:router-regen` — reread `plan.pages`, rewrite `src/lib/routesRegistry.ts` deterministically. Function exists in `post_generate_fixes` — expose and reuse.
- `deterministic:db-migrate` — run `alembic upgrade head` in the generated app's context (already scaffolded but not on the autofix path).
- `deterministic:rewire-datasource` — for a list-empty-data fault, use `binding_validator` to find the intended entity → rewrite `props.dataSource` in the schema.
- `deterministic:orphan-wiring` — already exists as `orphan_wiring_pass`; just wire it to `form-not-wired`.
- `deterministic:auth-seed` — existing `_fix_auth_seed`; keep as-is.

Smith handlers dispatch to a new module:

**File:** `backend/services/journey_verifier/smith_autofix.py`

```
async def dispatch(fault: ClassifiedFault, output_dir: Path) -> DispatchResult:
    context = build_fault_context(fault, output_dir)
    tool_subset = TOOL_SUBSETS[fault.seam]  # e.g. render → edit_page, add_page
    result = await run_smith_repair(context, tool_subset, turn_budget=3)
    return DispatchResult(...)
```

Turn budget per fault: 3. Whole-run cap: `FORGE_AUTOFIX_SMITH_BUDGET` (default 15 turns across all Smith-dispatched faults).

### Layer C — Fault context builder

**File:** `backend/services/journey_verifier/fault_context.py`

```python
def build_fault_context(fault: ClassifiedFault, output_dir: Path) -> SmithContext:
    return SmithContext(
        symptom=fault.evidence.stack_trace[:2000],
        route=fault.interaction.route,
        page_schema=read_page_schema(output_dir, fault.interaction.route),
        page_code=read_page_component(output_dir, fault.interaction.route),
        console_errors=[c for c in fault.evidence.console if c.level == "err"][:10],
        network_failures=[n for n in fault.evidence.network_log if n.status >= 400][:10],
        related_entities=infer_entities_from_route(fault.interaction.route),
        recent_edits=git_log_since(output_dir, last_verify_commit),
        available_tools=tool_subset,
    )
```

Pure; no LLM calls. Feeds Smith's prompt via existing memory-block mechanism.

## Milestones

### M1 — Classifier + deterministic wins (~3 days)

- `fault_classifier.py` module with the 10-class taxonomy
- Unit tests: each class, plus edge cases (multiple signals → priority order)
- 5 new deterministic handlers wired into `_SEAM_HANDLERS`
- Update `_run_journey_and_autofix` to call the classifier first, then dispatch
- Update `verify_summary._format_faults` to surface `class_name`
- Chip UI: group Recent faults by class (small stretch)

**Exit criteria:** unit tests green; on a synthetic fixture with one of each class, dispatcher fires the right handler for all deterministic classes.

### M2 — Smith dispatch (~4 days)

- `fault_context.py` builder + tests (pure)
- `smith_autofix.py` dispatcher
- Turn budget: env-gated, defaults enforced
- Convergence bookkeeping: mark fault "healed_this_round" if second run's same interaction passes
- Wire into `_run_journey_and_autofix` after deterministic pass

**Exit criteria:** on the recruitment fixture, a `render-error` fault is picked up, Smith writes an `edit_page`, second run passes that interaction. Autofix report shows the class → handler mapping.

### M3 — Regression guard + polish (~2 days)

- **Regression guard**: if `passed_this_round < passed_last_round`, roll back the round's file edits (extend SV-7). Currently SV-7 tracks total pass rate; we extend to per-fault.
- **Fault de-dup across rounds**: hash `(interaction_id, class_name)`; don't re-Smith the same one 3 times.
- **Chip UI**: per-class progress line ("2 render-errors → fixed, 1 missing-page → fixed, 1 residual for you"). Uses existing `verify_progress` event with an extended payload.
- **Docs**: update the V&F section of the blueprint.

**Exit criteria:** full 3-round loop converges on ≥90% pass rate for a well-formed spec; regression rolls back correctly on injected bad edit; residuals report is user-actionable.

## Guardrails

- **Cost cap**: `FORGE_AUTOFIX_SMITH_BUDGET` (default 15 turns/run). Deterministic handlers don't count against it. When budget exhausted, remaining Smith-dispatch faults land in residuals.
- **Priority order** when budget is tight: `render-error` → `binding-crash` → `data-fetch-failure` → `page-unresponsive`. Deterministic classes always run first.
- **Safety**: every fix runs through the existing `post_generate_fixes` validator before commit. Rejected fixes are logged and the fault stays in the residual list.
- **Non-regression**: per-fault regression tracking (see M3); auto-revert on drop.
- **User-in-loop for high-risk**: `add_page` from a missing-page fault is auto; `remove_page` is never auto-dispatched (only on explicit user ask).

## Out of scope

- **Infra faults** (503 preview down, dev server crash) — surfaced with a clear message, no auto-restart. Different problem class.
- **Speculative fixes** — every fix is anchored to a Playwright-observed failure. No "this looks broken."
- **Cascading rewrites** — if >70% of interactions fail, autofix bails and recommends regenerate. That's a spec/generation problem, not a fix problem.
- **Cross-file refactor from a single fault** — Smith handlers scoped to at most 3 files per turn.

## Interfaces (concrete)

`ClassifiedFault`:
```python
@dataclass(frozen=True)
class ClassifiedFault:
    interaction_id: str
    route: str
    class_name: str            # "render-error" etc; "unknown" if no match
    seam: str                  # "smith:render", "deterministic:add-page", "residual"
    evidence_slice: str        # short human-readable summary
    needed_context: list[str]  # ["page_schema", "page_code", "console"]
    raw: FaultRaw              # original evidence for the handler
```

`DispatchResult` (existing, extend):
```python
@dataclass
class DispatchResult:
    seam: str
    class_name: str            # NEW
    files_touched: list[str]
    smith_turns_used: int      # NEW, 0 for deterministic
    fixed: bool
    error: str | None
```

## Success metric (whole-plan)

On the recruitment fixture (~90 interactions), starting from a fresh generation:
- Round 1: today's V&F leaves ~40 residual faults
- Round 1 with V&F 2.0: leaves ~5 residual faults (missing-page, catch-all-router, list-empty-data, form-not-wired, db-schema-mismatch all healed deterministically; render-error and binding-crash healed by Smith)
- User's next chat turn addresses only the residuals, not the routine defects

## Related pending tasks

- Extend `SLICE-C-FIX-1/2` (workflow binding overwrites) — safe once class-based dispatcher lands
- `WEC-5` (workflow engine live E2E on regenerated app) — becomes trivially checkable via V&F pass rate
- `MCP-E2E-B` (visual-product-search live E2E) — same

## Implementation notes

### Self-healing (M1–M3, opt-in via `FORGE_AUTOFIX_V2=1`)

When `FORGE_AUTOFIX_V2=1`, V&F classifies each Playwright fault
(`missing-page`, `render-error`, `data-fetch-failure`, `binding-crash`,
`db-schema-mismatch`, `catch-all-router-broken`, `list-empty-data`,
`form-not-wired`, `page-unresponsive`, `auth-broken`; anything else
becomes `unknown` and lands in residuals), dispatches deterministic
handlers for the well-understood classes (fast, cheap, idempotent), and
hands the rest to Smith via `smith_autofix.dispatch_all` with a curated
context slice (page schema, page code, console errors, network
failures, related entities) and a per-seam tool subset.

**Regression guard (M3).** Every round is git-snapshotted via
`regression_guard.snapshot_before_round` before deterministic + Smith
edits. After the round's second Playwright pass, if total fault count
rose OR any interaction that was passing pre-round is now failing, the
round is auto-reverted with `git reset --hard <pre-round-sha>` and
`healed_faults` reset to `[]`. Non-git output dirs no-op.

**Dedup ledger (M3).** `FaultAttemptLedger` holds an in-memory count of
`(interaction_id, class_name)` pairs Smith has already been asked to
fix this run. Any second-attempt fault comes back as an
`already-attempted-this-run` residual instead of being re-dispatched.
Not persisted across runs.

**Chip UI (M3).** After `_run_faults_through_classifier` completes,
the backend publishes a `verify_class_progress` event with
`{healed_by_class, residual_by_class}`. The `VerifyProgressCard`
chip renders a "N healed, M for you" strip only when this payload is
present, so runs that predate M3 keep the old chip.

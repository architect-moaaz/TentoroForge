# Business Rules — Productionize the Feature, then Wire it into Generation

> Authored 2026-07-28 on `component-fixes`. Supersedes the current-state analysis in
> `2026-06-18-business-rules-engine-and-visual-editor.md` (that plan's architecture is
> sound but its file:line/state claims are 6 weeks stale). This doc is grounded in a
> 4-agent verification pass of HEAD `329de50`.
>
> **User directive (2026-07-28):** "First make the business-rules FEATURE (editor,
> Drools-like stack, everything planned) 100% accurate, tested, production-ready. THEN
> integrate it into the generation pipeline (UI + backend where applicable), editable,
> without breaking anything, and make it better. Then update BLUEPRINT + push to
> component-fixes."

---

## Verified current state (what's real at HEAD 329de50)

**Authoring half — BUILT and coherent:**
- `ProjectRule` JSONB store (8 base columns; `source`/`salience`/`scope`/`when`/`whenFeel`/`then`/`otherwise` all live INSIDE `config` JSONB — no dedicated columns, no RuleSet model).
- Editors: `frontend/src/components/business-rules/{BusinessRulesPanel,RuleEditor,ActionEditor,DecisionTableMode,RulePlayground}.tsx` — author `condition_action` (WHEN→then/otherwise, 10 actions) and `decision_table` (DMN hit policies), with a live condition playground.
- 10 actions (`business-rules.ts:17-27`): set_field, set_default, clear_field, show_error, set_visibility, set_required, set_readonly, recommendation, trigger_workflow, send_notification. NO `compute` (computed is a separate legacy type).
- `frontend/src/lib/condition-to-feel.ts` = the tree→FEEL compiler (exists). Saves via generic `/rules` CRUD with `config.source:"manual"`.
- Regen-wipe DEFUSED: `rules_agent._sync_rules_to_db` deletes only `config->>'source' IS DISTINCT FROM 'manual'`.

**Execution half — ABSENT / broken:**
1. Runtime `templates/runtime/rules/engine.ts` handles only legacy types (validation/access/business/computed/state_machine) — **no `condition_action`/`decision_table`, no action dispatcher** for the 10 actions.
2. `_export_rules_to_filesystem` reads `registry.json`, **not the `project_rules` DB** — hand-authored rules never ship.
3. **Two divergent server write paths**: `/api/data`→data-engine (has `validateEntity` hook) vs **Form→workflow→`db_insert`/`db_update` (raw Drizzle, NO hook)** — and schema forms use the workflow path. `db_insert` catches errors → workflow "completed" → user sees success even on rejection.
4. **Zero UI-side enforcement** — renderer imports no rules; visibility/required/readOnly/recommendation never surface.
5. Dead code: `computeFields`, `evaluateBusinessRule`, `canTransition` shipped but never called.
6. Figma + IR pipelines skip rule generation entirely.
7. **`models/decision.py` is a LIVE PROD BUG**: DecisionTable/Version/Log models NOT in `models/__init__.py`, NO Alembic migration → decisions endpoints 500 in prod (pass tests via `create_all`). The `decision_table` rule type depends on these.

**Landmines (respect):** rule_type drift across 5 locations (reuse `condition_action`/`decision_table`, don't invent types); Alembic single head `a9b7c2e8f4d1` (`rule_type` is String(50), not enum → no enum migration); bind to lightweight `templates/runtime` not `templates/workflow-engine`; `inject_runtime` rmtree+copytree per subdir (new top-level subdir must be added to the copy list); engine must fail via `ValidationError` (anything else is swallowed = fail-open).

---

## TRACK 1 — Harden the authoring feature to 100% production-ready (DO FIRST)

**T1.1 — Fix the decision-model prod-500 (blocks decision_table being production-ready).**
Register DecisionTable/DecisionTableVersion/DecisionExecutionLog in `models/__init__.py`; write an Alembic migration (down_revision `a9b7c2e8f4d1`) creating `decision_tables`/`decision_table_versions`/`decision_execution_logs` mirroring the model. Acceptance: `alembic upgrade head` creates them; decisions endpoints work against a migrated DB (not just create_all).

**T1.2 — FEEL-lite Python↔TS conformance suite.**
The compiler runs in-browser; evaluation must agree server-side. Build a shared fixture set (expr + data → expected) and run it through BOTH `backend/runtime/feel_lite` (py) and `frontend/src/lib/feel-lite` (ts). Acceptance: identical results across a broad operator/type matrix; CI-runnable both sides.

**T1.3 — Compiler + evaluator correctness (kill the deferred lows).**
Audit `condition-to-feel.ts` for every operator × type; fix `is_null`/`is_blank` absent-field semantics, numeric-string coercion edge, string-in-list. Round-trip `feelToTree` best-effort where feasible. Acceptance: property tests over the operator matrix; playground result == server eval for the same input.

**T1.4 — rule_type taxonomy coherence.**
Make `condition_action`/`decision_table` known everywhere they must be OR explicitly documented as authoring-only until Track 2. Add a single test pinning the taxonomy across the 5 locations. Acceptance: no silent no-op; one source of truth documented.

**T1.5 — Editor correctness + in-browser QA.**
Round-trip (save→reload→edit→save) for both rule modes; per-action save validation (every action's required params enforced before save); playground re-seed on model switch; decision-table analysis (completeness/overlap). Drive the Business Rules tab in-browser end-to-end. Acceptance: author, save, reload, edit, delete both rule types with zero console errors; validation blocks malformed rules.

**T1.6 — Test + sweep.** Unit + integration for the above; full `tests/` sweep = pre-existing baseline, zero new. tsc clean on frontend.

**Track 1 gate:** the authoring feature is correct, tested, and production-ready in isolation (author→persist→validate→playground), with the decision-model prod bug fixed.

---

## TRACK 2 — Wire into the generation pipeline (execution)

**T2.1 — Runtime action dispatcher + evaluateRuleSet.** Extend `templates/runtime/rules/engine.ts` with `evaluateRuleSet(model,event,entity,user,ctx)` and `dispatchActions()` for the 10 actions (server-safe subset executes; form-only actions emit hints). Reuse `decision_evaluator` for `decision_table`.

**T2.2 — Converge the write paths (the load-bearing fix).** Route `workflows/index.ts` `db_insert`/`db_update` through `data-engine.create/update` so they inherit the rules hook, AND make a rule rejection throw so the workflow reports non-completed and `Form.tsx onError` surfaces it. Preserve the ValidationError contract.

**T2.3 — Ship DB rules.** Extend `_export_rules_to_filesystem` to read `project_rules` DB (merge with registry), emit rule-set + decision JSON into the app.

**T2.4 — UI-side enforcement.** New `interaction` keys (visibility/required/readOnly/recommendation) on `packages/renderer/.../formInteraction.ts` + a `useFieldRules` controller in `Form.tsx` mirroring `useComputedFields`; server rejection surfaced inline.

**T2.5 — Close the gaps.** Figma/IR pipelines call rules; wire `computeFields`/`canTransition`; fail-closed option for genuine rule errors.

**T2.6 — End-to-end proof.** Author a rule in the editor → it ships → fires server-side (reject/set-value) AND form-side (hide/require) in a running generated app. Editable round-trip preserved.

---

## TRACK 3 — BLUEPRINT + push to `component-fixes` (after each track's gate, incremental).

## Non-breaking guarantees (hold throughout)
Additive only; register+migrate every new model; bind to `templates/runtime`; keep the `data-engine` try/catch + ValidationError contract; reuse existing rule types; every phase ends with the full sweep at pre-existing baseline (zero new failures) before commit.

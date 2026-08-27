# Business Rules Engine + In-house Drools-style Visual Editor — Research & Plan

> Status: **EDITORS BUILT + TESTED 2026-06-19** (senior approved "create business rules editors"). Research/plan authored 2026-06-18 on `forge-v3`.
> Owner: Areeb + Claude. The runtime *execution* layer (action dispatcher + generated-app emission) is still the next phase — see Part D Phases 1/4.
>
> ## BUILD STATUS — 2026-06-19 (editors)
> Delivered, on `forge-v3` (uncommitted, not pushed): a **Business Rules** workspace tab with **two editors** — (1) a Power-Apps-style **condition → action** editor (reuses `ConditionBuilder` for IF; new `ActionEditor` for THEN/ELSE with the full action vocabulary; live **playground** that compiles the condition tree → FEEL via new `lib/condition-to-feel.ts` and evaluates it with the existing `@/lib/feel-lite`), and (2) a **decision-table** editor (reuses the DMN `DecisionTableEditor` + 6 hit policies). Persists as `ProjectRule` rows (`rule_type` `condition_action`/`decision_table`, `config.source="manual"`) via the existing `/rules` CRUD — **no new model, no migration**. Backend safety: `rules_agent._sync_rules_to_db` now preserves `source=="manual"` rules so regeneration can't wipe editor work; `valid_types` extended. New files: `frontend/src/components/business-rules/{BusinessRulesPanel,RuleEditor,ActionEditor,RulePlayground,DecisionTableMode}.tsx`, `lib/condition-to-feel.ts`, `types/business-rules.ts`. Surgical edits: `page.tsx` (append-only tab), `RulesPanel.tsx` (filter out the new types), `feel-lite/{evaluator,validator}.ts` (underscore `starts_with`/`ends_with` aliases). Tested: tsc clean (0 new errors), route compiles (200), API CRUD round-trip for both types, FEEL compiler output evaluates on both runtimes, adversarial 3-lens review → all high/medium findings fixed + re-verified. Deferred lows (documented): is_null absent-field semantics, numeric-string coercion edge, per-action save validation, playground re-seed on model switch.
> North star: *Let a maker author business rules for a generated app — Power-Apps-simple (condition → action), Drools/DMN-grade visual authoring — and have them execute at request-time in the shipped app, with zero hand-written code and without breaking anything already working.*

---

## 0. TL;DR / decisions

- **Where it goes (the open question):** Business rules are a **first-class, cross-cutting layer — NOT buried inside Workflows.** Industry consensus (BRE vs WFE): a rules engine answers *"given these conditions, what should happen?"* and is reusable/workflow-agnostic; workflows *consume* rules. So: a **new "Business Rules" authoring tab** (its own visual editor), **executed request-time** in the generated app at the **`src/lib/data-engine.ts` service-layer seam** (which *already* calls `validateEntity`/`filterFields` on every create/update/read), and **interoperable** with workflows (a workflow node can invoke a rule; a rule action can trigger a workflow) and decisions (a decision table is one rule-evaluation backend). "Put it in workflows" is right only for the *interop* — not for the engine's home.
- **~70% is assembly, not greenfield.** We already have: a generic `ProjectRule` JSONB store; a recursive AND/OR `ConditionBuilder` (Power-Apps-style); a request-time TS rules engine shipped into generated apps (`templates/runtime/rules/engine.ts` + `data-engine.ts` hooks); a DMN `decision_evaluator` with 6 hit policies; a full FEEL-lite expression engine (4 copies); and an entire React-Flow **DRD + DecisionTableEditor** visual stack that is the *exact Drools-Business-Central analog* to clone.
- **The genuinely new builds:** (1) a **rule ACTION dispatcher** (today rules can only validate/compute/filter — they cannot *act*); (2) **salience/priority + conflict resolution** (rule ordering); (3) a **visual ⇄ FEEL compiler** (unify the two divergent condition representations); (4) the **Drools-style visual rule editor** (cloned from the decision stack); (5) **backend persistence** (model + migration + router); (6) **generated-app runtime emission** of the action dispatcher; (7) a **RulePlayground**.
- **Non-breaking landmines (must respect):** `rules_agent._sync_rules_to_db` **wipes all `project_rules` on every regeneration** → editor-authored rules vanish unless we add a provenance flag; `data-engine.ts` **silently swallows** rule errors; `models/decision.py` has **no migration / not in `__init__`** (don't repeat that); two parallel generated-app workflow runtimes exist (bind to the lightweight one); 4 hardcoded `rule_type` lists must stay in sync; keep the existing code-injection `/apply` path working for existing projects.
- This maps onto **`DEVELOPMENT_PLAN.md` Feature H** ("rules runtime engine + playground") and **`IMPLEMENTATION_TASKS.md` Priority 1A/1B**.

---

## Part A — Research: what business rules are and how they work

### A.1 Business Rules Engine (BRE) vs Workflow Engine (WFE) — *the "where" question*
- **BRE** = declarative, *data-driven*: *"given these conditions, what should happen?"* Fires when conditions are met. The value is **rule independence** — change rules without touching the rest of the app code.
- **WFE** = imperative, *process-driven*: *"given the process, what is the next step?"* Orchestrates tasks/stages.
- **They are complementary, not mutually exclusive.** Embedding rule logic *inside* workflow nodes reduces rule reusability (rules become workflow-specific). Therefore the engine must be its own layer; workflows/decisions consume it.
- Sources: Kissflow / Cflow / FlexRule BRE-vs-WFE comparisons; Wikipedia *Business rules engine*.

### A.2 Microsoft Power Apps / Dataverse business rules — the *simple, no-code* model (our authoring UX target)
- A business rule = **conditions + actions** on a **table** (entity). No code, no plugins. "Every rule starts with a condition; the rule takes one or more actions based on that condition."
- **Action vocabulary** (this is the canonical set we should mirror):
  - **Set Field Value** (hard value, another column's value, or a simple formula) / **Clear value**
  - **Set Default Value** (only when the field is null)
  - **Show Error Message** (blocks save; on server it's returned to the calling process) — i.e. *validation/reject*
  - **Lock / Unlock** (read-only toggle) — *model-driven (form) only*
  - **Set Visibility** (show/hide) — *form only*
  - **Set Business Required** (required ↔ optional, red asterisk) — *form only*
  - **Recommendation** (lightbulb next to the field → user clicks → "Apply" → runs the recommendation's actions) — *form only*
- **Scope** (critical concept): **Entity** = applies on *all forms AND server-side*; **All Forms** = client/form only; **Specific form** = just that form. Canvas apps must use table/entity scope.
- **Execution semantics:** rules run **client-side** on form load + when a referenced field changes; **Entity-scope** rules *additionally* run **server-side** (generated as synchronous plugins). They run *before* onLoad scripts. Form-only actions (visibility/lock/required/recommendation) are **ignored server-side**.
- **Conditions:** Source / Field / Operator / Type / Value; multiple clauses joined by **AND/OR** ("Rule Logic" column); a true (✓) branch and a false (✗) branch.
- **Limits:** ≤150 rules/table (perf), ≤10 if-else conditions per rule, **fields only** (not tabs/sections), **no multi-select choice / file / language** columns.
- **Visual designer:** a flowchart canvas — drag **Condition / Action / Recommendation** tiles from a **Components** pane onto **+** signs (✓ branch / ✗ branch); a **Properties** pane builds a **read-only generated expression** at the bottom; **Validate → Save → Activate** lifecycle (must *deactivate* to edit); **Snapshot** (share) + **mini-map**.
- Sources: Microsoft Learn *Create a business rule in Dataverse* + *Create model-driven app business rules and recommendations*.

### A.3 Drools + DMN — the *engine semantics* and the *visual authoring* we must emulate
**Engine (for vocabulary/architecture we may borrow):**
- Drools is a **hybrid reasoning system / BRMS**. Rules live in **Production Memory**; facts in **Working Memory**. The inference engine matches rules↔facts using **Rete → PHREAK** (PHREAK = lazy, goal-oriented, segmented-memory, batched-propagation; Drools 6+).
- Fully-matched rules become **Activations** placed on the **Agenda**; **conflict resolution** uses **salience** (priority) + sequence number. **Forward chaining** (data-driven). Working-memory/agenda event listeners observe inserts/updates/retracts/firings.
- *Implication for us:* full RETE/forward-chaining is heavy. Power-Apps-style needs only **single-pass, salience-ordered** evaluation; re-fire-until-fixpoint is a later option.

**DMN visual anatomy (this is the "exactly like Drools" visual reference):**
- A **DRD** (Decision Requirements Diagram) is the visual model. Node types: **Decision** (rectangle), **Business Knowledge Model / BKM** (clipped-corner — reusable function), **Input Data** (oval), **Knowledge Source** (document — policy/authority), **Decision Service** (composite). Connectors: **Information Requirement** (data/decision→decision), **Knowledge Requirement** (BKM→decision), **Authority Requirement** (knowledge-source→element), **Association** (→ text annotation).
- A **Decision Table**: input columns (conditions) + output columns (conclusions) + **rule rows** (input entries = FEEL unary tests / ranges / lists / `-` don't-care; one output entry/row) + a **default output**. **8 hit policies**: **U**nique, **A**ny, **P**riority, **F**irst, **C**ollect, and Collect aggregators **C+ / C< / C> / C#**.
- **Boxed expressions (7):** literal, context (var rows + result), relation (table of data), function (BKM params+body), invocation (call a BKM with bindings), list, decision-table.
- **FEEL** cells: numbers/strings/booleans/dates/durations/lists/contexts/functions; unary tests (`> 100`, `[500..750]`, `"gold","silver"`, `-`); built-ins (`count/sum/min/max/sort/append/date/now/...`).
- **Designer UX:** node palette (drag), grid canvas with auto-layout, double-click rename, per-node edit→boxed-expression designer (two-pane grid + type selectors), a **Data Type manager** (simple/structured/enumerated/ranged + constraints), connection validation, error markers, included-models reuse, **test-scenario** designer.
- Sources: Drools docs (rule engine, DMN), Red Hat Decision Manager, Camunda DMN, JBoss Tools Drools page, DMN Wikipedia.

### A.4 Synthesis — the model we will build
**Author like Power Apps (condition → action, declarative, no-code), visualize like Drools/DMN (DRD canvas + decision tables + boxed conditions + hit policies + playground), execute request-time like a BRE (rule independence: edit rules → no regen).** A rule = `{ when: condition(FEEL), then: action[], else: action[], scope, salience, active }`, grouped into ordered **rule sets** with a hit/conflict policy. Decision tables are a *table form* of the same rule set. Workflows and decisions interoperate but don't own the engine.

---

## Part B — Current-state analysis (our app) & the verdict

### B.1 What already exists (with exact surfaces)
| Capability | Where | Verdict |
|---|---|---|
| Generic rule store | `models/rules.py` `ProjectRule {project_id, name, rule_type String(50), model_name, field_name, config JSONB, is_active}` + CRUD `routers/rules.py:51-176` | **REUSE** (open JSONB config; add columns via migration) |
| Field/app RBAC | `AppAccessPolicy`, `FieldAccessPolicy`; `/field-access/matrix` | **REUSE** as the access-rule sub-family |
| Condition UI (Power-Apps-style) | `components/rules/ConditionBuilder.tsx` recursive `ConditionGroup{logic:AND\|OR\|NOT, conditions[]}` + 14 operators | **REUSE** as the IF editor |
| Static rule validator | `services/validate_rules.py` (entity/field/type/enum + fuzzy suggestions) | **REUSE / EXTEND** |
| **Request-time rules runtime (generated app)** | `templates/runtime/rules/engine.ts` `validateField/validateEntity/canAccessField/filterFields/evaluateBusinessRule/computeFields/canTransition`; **called by `data-engine.ts` at create:118 / update:156 / read:207,266** | **REUSE — build on THIS, not code-injection.** *(Corrects the stale "rules are code-injection-only" claim.)* |
| DMN decision evaluator (request-time, 6 hit policies) | `runtime/decision_evaluator.py` `evaluate_decision_table` / `_apply_hit_policy` / `_cell_matches` | **REUSE** as a rule-eval backend |
| **Drools-like visual stack** | `components/decision/*`: DRD React-Flow canvas (`DRDCanvas`, 3 node shapes, dagre `drd-layout.ts`), `DecisionTableEditor` + `DecisionCellEditor` + `ExpressionAutocomplete` + `HitPolicySelector` + `DecisionTestPanel` + `DecisionAnalysisOverlay` (completeness/overlap/dead-row/type-errors) + `DecisionDiffView` + `DecisionVersionPanel` | **REUSE/CLONE** — this is the editor chassis |
| FEEL-lite (condition language) | `runtime/feel_lite/` (py, 116 tests) + `lib/feel-lite/` (ts) + `templates/runtime/feel-lite/` (shipped) + `templates/workflow-engine/domain/feel-lite/` (4th, drifted) | **REUSE / EXTEND / UNIFY** |
| Event bus | `templates/runtime/event-registry.ts` `onDataEvent → triggerWorkflowEvent` | **REUSE** for rule "trigger workflow" action |
| DB→app rule delivery | `runtime_injector._export_rules_to_filesystem` (registry.json `rules[]` → `rules/index.json`); `inject_runtime` copies `feel-lite/workflows/rules` | **REUSE / EXTEND** (also read `project_rules` DB) |
| Apply-to-app SSE protocol | `hooks/useSchemaChange.ts` (status/log/file_created/tool_call/complete/error) | **REUSE** for "Apply rules" |
| AI rule authoring | `agents/rules_agent.py` (NL → structured rules) | **EXTEND** |

### B.2 The verdict on "where does it go"
- **Authoring:** a **new "Business Rules" tab** in the project workspace (`page.tsx` Tab union + sidebarSections Model group + content chain — *append-only* edits), mounting a `BusinessRulesPanel` cloned from `DRDEditorPanel`. **Not** inside the Workflow editor.
- **Storage:** `ProjectRule` (extended) + a new **rule-set/rule-flow** model (model on `workflows.py` persistence; **register in `models/__init__.py` + write the migration** — do not repeat `decision.py`'s mistake).
- **Execution (generated app):** **request-time at the `data-engine.ts` service-layer seam** (already wired for validate/filter). **Not** Next.js middleware (edge, no Drizzle), **not** primarily workflow nodes.
- **Interop:** workflow nodes can invoke a rule/decision (`runtime/engine.py` decision gateway pattern); rule actions can trigger workflows via the event bus; decision tables are one rule-eval backend.

### B.3 Non-breaking constraints (load-bearing — must hold)
1. **`rules_agent._sync_rules_to_db` deletes-then-inserts ALL `project_rules` on every regeneration** (`rules_agent.py:111-113`). Editor-authored rules would be destroyed. **→ add a `source`/provenance column ('ai' \| 'manual') and only wipe AI-authored rows.**
2. **`data-engine.ts` swallows non-`ValidationError` failures silently** (`:123-126`). New rule eval must preserve the `ValidationError` passthrough and never throw raw.
3. **4 separate hardcoded `rule_type` lists** (`rules.py:83`, frontend `types.ts:17`, runtime `types.ts`, `rules_agent VALID_TYPES`) — adding a type means updating all four.
4. **Two parallel generated-app workflow runtimes** (`templates/runtime/workflows` via `inject_runtime` vs `templates/workflow-engine` via `apply_workflow`'s clobber). **Bind rules to the lightweight `data-engine`/`runtime/*` path; don't touch `apply_workflow`.**
5. **`models/decision.py` is absent from `models/__init__.py` with no migration** → `/decisions/*` would 500 in prod. New rule model **must** be registered + migrated.
6. Don't overload `useDecisionStore` — **new store** to avoid cross-talk with the workflow-embedded decision tables.
7. Keep the **existing code-injection `/rules/{id}/apply`** behaviour intact for existing projects; the request-time engine is **additive**.
8. `validateEntity` is **O(fields × rules)** on the write path — watch latency; index rules by `(model, event)`.

---

## Part C — Proposed design

### C.1 Data model
Extend `ProjectRule` (migration; `models/rules.py` already has migrations, so this is safe):
- `source` enum (`ai` \| `manual` \| `template`) — protects editor rules from the regen wipe.
- `salience` int (default 0) — priority for conflict resolution.
- `rule_set_id` FK (nullable) — grouping.
- `scope` enum (`entity` \| `form:<id>` \| `server`) — Power-Apps scope semantics.
- `config` JSONB gains the **canonical rule shape**: `{ when: <ConditionExpression tree>, whenFeel: <compiled FEEL string>, then: Action[], else: Action[], hitWithinSet? }`.

New **`RuleSet`** model (+ `RuleSetVersion`, `RuleExecutionLog` — mirror the `DecisionTable/Version/Log` triad that already proved out): `{project_id, name, model_name, mode: 'flow'|'table'|'list', conflict_policy, definition JSONB (graph nodes/edges OR table), version}`. **Register in `models/__init__.py` + Alembic migration.**

### C.2 Rule semantics & evaluation model
- A **rule** = `WHEN condition THEN action[] [ELSE action[]]`, with `salience`, `scope`, `active`.
- A **rule set** evaluates its rules **salience-ordered, single-pass** (v1). Conflict policy ∈ `{ all-fire, first-only, priority }` (Drools-lite). **Decision-table mode** reuses the existing 6 hit policies.
- **v2 (optional):** re-fire-until-fixpoint (bounded iterations) for true forward-chaining; this is the only place we approach RETE and it's explicitly deferred.

### C.3 Action vocabulary (the core NEW build — today rules can't act)
Server-safe (run in `data-engine`): **Set Field Value**, **Set Default Value**, **Reject/Show Error** (throw `ValidationError`), **Compute Field**, **Trigger Workflow** (via event bus), **Call Decision Table** (via evaluator), **Send Notification**. Form-only (emitted as schema/runtime hints, mirroring Power Apps): **Set Visibility**, **Set Required**, **Lock/Unlock**, **Recommendation** (lightbulb). Each action validated by an extended `validate_rules.py`.

### C.4 Condition language — FEEL-lite, unified
- **Single source of condition truth = FEEL-lite.** The visual `ConditionExpression` tree compiles to a **FEEL string** (`whenFeel`) that the existing `evaluate_expression` (py) / `evaluateExpression` (ts) runs — so authoring (tree) and runtime (FEEL) finally agree. Store **both** (tree for round-trip editing, FEEL for eval).
- **Build the compiler** `conditionTreeToFeel()` (+ best-effort `feelToTree()` for import). Today only `conditionToText()` (English-for-LLM) exists.
- **Extend builtins** (both py + ts + validator + agent prompt, in lockstep): `is_blank/is_empty`, working `today()/date` arithmetic & comparison, `length/trim/coalesce`, string `in`-list. **Unify the 4 FEEL copies** + add a TS conformance test mirroring the 116 py tests *before* touching grammar.

### C.5 Execution architecture (generated app)
- Extend `templates/runtime/rules/engine.ts` with `evaluateRuleSet(model, event, entity, user, ctx)` → returns `{ patches, errors, sideEffects }`, and a **`dispatchActions()`** (the new action dispatcher; mirrors `workflows registerDefaultActions` registry).
- Wire it into `data-engine.ts` create/update/read hooks (the seam already exists). Preserve the `ValidationError` passthrough + try/catch contract.
- `runtime_injector._export_rules_to_filesystem` extended to also read the **`project_rules` DB** (so editor rules ship), and to emit the rule-set JSON + (port) decision evaluator into the app.

### C.6 The Drools-like visual editor (clone the decision stack)
New `components/business-rules/` (cloned from `decision/*`, **new store** `stores/business-rules.ts`):
- **`RuleSetCanvas`** (React-Flow): a DRD-style graph — Input-Data / Rule / Decision-Table / Action nodes, then/else handles (like `WorkflowCanvas`), dagre auto-layout (`rule-layout.ts`), MiniMap/Controls, `proOptions hideAttribution`, `import '@xyflow/react/dist/style.css'`.
- **Condition→Action authoring** (`RuleNodePanel`): reuse `ConditionBuilder` for the IF; build the **THEN/ELSE action editor** (Power-Apps tile vocabulary); live FEEL preview via `lib/feel-lite` `validateExpression(expr, fields as VariableSchema[])`.
- **Decision-table mode:** drop in `DecisionTableEditor` + `HitPolicySelector` + `ExpressionAutocomplete` as-is.
- **RulePlayground** (Feature H3): reuse `DecisionTestPanel` + a FEEL **execution trace** (which rules fired, in salience order, with the agenda) — the Drools "audit view" analog.
- **Analysis/versioning:** reuse `DecisionAnalysisOverlay` (completeness/overlap/dead-row/conflict) + `DecisionVersionPanel`/`DecisionDiffView`.
- **Lifecycle:** Validate → Save → **Activate** (Power-Apps parity) + Snapshot.

### C.7 Backend
- New `routers/rule_flows.py` (model on `routers/workflows.py`): `GET/POST/DELETE /api/projects/{id}/rule-flows`, `/{id}/apply` (SSE), `/{id}/evaluate` + `/{id}/test` (reuse `decision_evaluator`-style logging). Register in `main.py` (next to decisions).
- Extend `validate_rules.py` (new types + action validation), `rules_agent.py` (emit the new rule shape + `source='ai'`), and the 4 type lists.

---

## Part D — Phased, non-breaking implementation plan

**Phase 0 — Foundations & safety (no user-visible change).**
- Migration: `ProjectRule.source/salience/rule_set_id/scope`; new `RuleSet/RuleSetVersion/RuleExecutionLog` (registered + migrated).
- Fix the regen wipe: `_sync_rules_to_db` only deletes `source='ai'` rows.
- FEEL-lite: add TS conformance test (mirror 116 py tests); add the new builtins in lockstep across all copies; unify copies behind one source.
- Acceptance: existing rules/decisions/workflows unchanged; new tables migrate clean; FEEL conformance green.

**Phase 1 — Condition compiler + request-time eval (headless).**
- `conditionTreeToFeel()` + tests; `evaluateRuleSet()` + `dispatchActions()` in `rules/engine.ts`; wire into `data-engine.ts`; extend `_export_rules_to_filesystem` to read DB.
- Acceptance: a manually-seeded rule set fires on create/update in a generated app; ValidationError still blocks save; no latency regression on rule-free models.

**Phase 2 — Backend persistence + AI authoring.**
- `routers/rule_flows.py` (CRUD + apply SSE + evaluate/test) + `validate_rules` extensions + `rules_agent` emits new shape.
- Acceptance: rule sets persist/version/evaluate server-side; AI-authored rules carry `source='ai'` and survive editor edits.

**Phase 3 — The visual editor (the headline).**
- `components/business-rules/*` cloned from `decision/*`; new store; 5 append-only `page.tsx` edits to add the tab; condition→action authoring; decision-table mode; analysis + versioning.
- Acceptance: author a condition→action rule and a decision table visually; Validate/Save/Activate; Apply ships them to a running generated app and they fire.

**Phase 4 — Playground + interop + polish.**
- RulePlayground (trace/agenda); workflow↔rule node case (`workflows/engine.ts` + `runtime/engine.py`); recommendation/visibility/required form-actions emitted as schema hints; 20+ starter templates (reuse `lib/decision/templates.ts`).
- Acceptance: step-debug a rule set; a workflow node invokes a rule; a rule triggers a workflow; form-only actions reflect in the rendered schema.

**Phase 5 (optional/deferred) — Forward-chaining.** Bounded re-fire-until-fixpoint + agenda visualization (true Drools-lite). Only if required.

---

## Part E — Risks & non-breaking guarantees
- **Additive only:** new tab, new store, new model, new runtime function — append, never rearrange (esp. `page.tsx` Tab union & content chain; `models/__init__.py`).
- **Provenance flag** protects editor rules from the regen wipe (Phase 0, before anything else).
- **Preserve** the `data-engine.ts` try/catch + `ValidationError` contract; the code-injection `/apply` path; `apply_workflow`'s template clobber; `useDecisionStore` (separate store).
- **FEEL changes are test-gated** (116 py + new ts conformance) — decision tables & workflow gateways depend on exact `match_value`/wildcard/`?`-placeholder semantics.
- **Migrate the new model** (don't repeat `decision.py`). Keep `rule_type` lists in sync.
- Latency: index rules by `(model, event)`; skip eval entirely for models with no active rules.

## Part F — Open decisions for you (Areeb)
1. **Drools fidelity:** single-pass salience-ordered (recommended for v1, covers Power-Apps + most Drools-lite) vs full forward-chaining/RETE (Phase 5)?
2. **Execution model:** make business rules **request-time** (recommended — rule independence) and *deprecate* code-injection for the new type, or keep both?
3. **Editor surface:** one unified "Business Rules" tab with **mode toggle** (flow canvas / decision table / simple list), or separate tabs? (Recommended: one tab, mode toggle — reuses everything.)
4. **AI rule types** (content_moderation/similarity_check/ai_validation/ai_enrichment) in scope for runtime, or authoring-only for now?
5. **Scope split:** do we emit Power-Apps form-only actions (visibility/required/lock/recommendation) as schema hints into the schema-mode renderer in v1, or server-side actions only first?

---

### What I do the moment you say "ok, build"
Start **Phase 0**: write the Alembic migration (`ProjectRule` columns + `RuleSet`/`Version`/`Log`, registered in `models/__init__.py`), patch `_sync_rules_to_db` for the provenance flag, and stand up the FEEL-lite TS conformance test — all behind the existing behaviour, verified non-breaking, committed on `forge-v3` (never pushed). Then proceed phase by phase, checking in at each acceptance gate.

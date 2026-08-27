# Workflow Node Catalog — Editor Alignment + Variable Provenance

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** The editor renders every workflow node the runtime executes (no more "Custom Task" / "undefined gateway"), by wiring the editor catalog to the existing runtime-derived authority (`workflow_node_contracts`) + a drift guard; and the pipeline flags a gateway/condition whose expression reads a variable no upstream node produces.

**Root cause (already diagnosed):** three drifted vocabularies. Runtime `types.ts` unions are the authority (parsed by `services/workflow_node_contracts.py`). The backend translator + planner already consume it (guarded by `tests/test_workflow_node_contracts.py`). The **editor** (`frontend/src/types/workflow.ts` + consumer maps) is a *separate hand-authored* catalog that was never wired in, so it lacks `exclusive_gateway`/`parallel_gateway`/`fork`/`join`/`user_task`/`end_event` and the `db_insert`/`db_update`/`db_delete`/`set_variable`/`transform`/`generate_document` action types, and it represents AI nodes as top-level `ai_generate` while the backend emits `action`+`actionType:ai_generate`.

**Runtime authority (do not hardcode — read via `node_contracts()`):**
- node_types: trigger, action, condition, decision, parallel_gateway, exclusive_gateway, fork, join, user_task, approval, wait, end, end_event, ai_generate, ai_classify, ai_extract, ai_decide
- action_types: db_query, db_insert, db_update, db_delete, http_call, send_email, send_notification, set_variable, transform, custom, generate_document, ai_generate, ai_classify, ai_extract, ai_decide

---

## PART A — Editor catalog alignment + drift guard

### Task A1: Backend emits AI nodes as top-level node types (canonical form)

**Files:** Modify `backend/services/workflow_step_translator.py`; Test `backend/tests/test_workflow_step_translator.py` (or existing translator test).

The editor's canonical AI node is top-level `type: "ai_generate"`; the runtime NodeType union lists ai_* as node types AND accepts them. Today `_resolve_node_type` hits `_ACTIONTYPES` first (line 242) so a step typed `ai_generate` becomes `("action","ai_generate")`. Make ai_* resolve to a top-level node type instead.

- [ ] **Step 1: Failing test** — a planner step `{"id":"gen_summary","type":"ai_generate","config":{"prompt":"x"}}` translates to a node with `type == "ai_generate"` (NOT `type=="action"`), config preserved.
- [ ] **Step 2: Verify fail** (currently emits `action`).
- [ ] **Step 3: Fix** — remove `ai_generate`/`ai_classify`/`ai_extract`/`ai_decide` from `_ACTIONTYPES` (they stay valid via the node-type branch at 244-246). Keep them resolvable from `config.actionType` fallback (249-251) so an `action`+actionType:ai_* input still works (back-compat). Ensure `_translate_node`'s action branch (line 265+) still builds the AI config (prompt/aiInput) when ntype is `ai_generate` — move/duplicate the ai_* config-building branch to run for both `action` and top-level ai_* node types.
- [ ] **Step 4: PASS.** Also assert a `db_update` step still emits `type:"action", actionType:"db_update"` (unchanged).
- [ ] **Step 5: Commit.**

### Task A2: `workflow_node_contracts` exposes a machine catalog + editor parser

**Files:** Modify `backend/services/workflow_node_contracts.py`; Test `backend/tests/test_workflow_node_contracts.py`.

- [ ] **Step 1: Failing tests** for two new functions:
  - `emit_node_catalog_json(out_path)` writes `{nodeTypes, actionTypes, triggerTypes}` from `node_contracts()`.
  - `parse_editor_catalog(types_ts_path) -> {nodeTypes:set, actionTypes:set, paletteTypes:set, paletteActions:set}` — reuse `_union_members` to read `WorkflowNodeType` + `ActionType`, and regex the `NODE_CATEGORIES` array for each node's `type:` and `defaultConfig.actionType`.
- [ ] **Step 2: Verify fail. Step 3: Implement** both (pure parsing/emission; no network). **Step 4: PASS. Step 5: Commit.**

### Task A3: Editor catalog gains every missing node/action (types + palette)

**Files:** Modify `frontend/src/types/workflow.ts`.

- [ ] **Step 1:** Extend `WorkflowNodeType` union with `parallel_gateway`, `exclusive_gateway`, `fork`, `join`, `user_task`, `end_event` (keep existing extras like `assignment`/`task_pool`/`escalation` — they alias to runtime `user_task`/`action`; that's allowed).
- [ ] **Step 2:** Extend `ActionType` with `db_insert`, `db_update`, `db_delete`, `set_variable`, `transform`, `generate_document` (keep `db_query` etc.).
- [ ] **Step 3:** Add `NODE_CATEGORIES` palette entries: a "Flow Control" `exclusive_gateway` (label "Exclusive Gateway", icon GitBranch) + `parallel_gateway`/`fork`/`join`; "Actions" entries for `db_insert`/`db_update`/`db_delete` (label "Insert/Update/Delete Record", icon Database), `set_variable` (label "Set Variable", icon Variable/Hash), `transform`, `generate_document` (label "Generate Document", icon FileText). Give each a gradient + `defaultConfig.actionType`.
- [ ] **Step 4:** No test here (covered by A5). Commit after A4.

### Task A4: Editor node components render the new types

**Files:** Modify `frontend/src/components/workflow/WorkflowCanvas.tsx` (nodeTypes map), `frontend/src/components/workflow/nodes/WorkflowNode.tsx` (NODE_VISUALS + label/pills).

- [ ] **Step 1:** In `WorkflowCanvas.tsx` `nodeTypes`, add `exclusive_gateway`, `parallel_gateway`, `fork`, `join`, `user_task`, `end_event` → all `WorkflowNode` (they share the generic node renderer). 
- [ ] **Step 2:** In `WorkflowNode.tsx` `NODE_VISUALS`, add `exclusive_gateway`/`parallel_gateway`/`fork`/`join` (icon GitBranch/Split), and `action:db_insert`/`action:db_update`/`action:db_delete` (icon Database), `action:set_variable` (icon Hash), `action:transform`, `action:generate_document` (icon FileText). ALSO make `getVisual` recognize `action:ai_generate`→ same as top-level `ai_generate` (defensive for older apps that still emit the action form).
- [ ] **Step 3:** In the label/pills `switch` add cases so `set_variable` shows its `variableName`, `db_insert`/`db_update` show the table, gateways show the expression — so the node title is never a bare "Custom Task".
- [ ] **Step 4: Commit.**

### Task A5: Drift guard — editor catalog covers the runtime authority

**Files:** Create `backend/tests/test_editor_workflow_catalog.py`.

- [ ] **Step 1: Test** using `node_contracts()` (authority) + `parse_editor_catalog(<repo>/frontend/src/types/workflow.ts)`:
  - every runtime `node_type` is in the editor `WorkflowNodeType` union (allow the editor to have MORE — extras are fine, missing is not);
  - every runtime `action_type` is in the editor `ActionType` union;
  - every runtime `node_type` that a user can place has a `NODE_CATEGORIES` palette entry OR is a structural type (`trigger`/`end`/`end_event`) — assert palette covers the placeable set.
  - Emit a clear failure message naming the missing members.
- [ ] **Step 2: Run** — should PASS now that A3/A4 landed (if it fails, it names exactly what's still missing → fix A3/A4). **Step 3: Commit.**
- [ ] **Step 4:** (optional) wire `emit_node_catalog_json` into the pipeline so a per-run `contracts/workflow-node-catalog.json` is emitted for debugging.

### Task A6: Live verify on the editor

- [ ] Open the editor (preview :6501), load a workflow containing an `exclusive_gateway` + `ai_generate` + `db_update` (e.g. re-import f4pw5y5k's feedbackscoringworkflow.json), and confirm the gateway renders as a labeled Gateway node and the action nodes show "AI Generate" / "Update Record" — not "Custom Task"/"undefined". Screenshot.

---

## PART B — Workflow variable-provenance check

### Task B1: Variable producer/consumer analysis

**Files:** Create `backend/services/workflow_variable_contract.py`; Test `backend/tests/test_workflow_variable_contract.py`.

A gateway/condition `expression` reads variables (e.g. `overallRecommendation = 'Hire'`). Those must be PRODUCED upstream: a node output (`set_variable.variableName`, an ai_* node's declared output, `db_query` result var), a trigger input field, or an entity column on the trigger entity. If a referenced variable has no producer on any path reaching the gateway, the branch is dead.

- [ ] **Step 1: Failing tests:**
  - `referenced_vars("overallRecommendation = 'Hire'")` → `{"overallRecommendation"}` (strip string/number literals, keywords, funcs).
  - `analyze_workflow(defn)` returns findings: for the f4pw5y5k-shaped workflow (gateway reads `overallRecommendation`, only `set_variable` producing `compute_aggregate_score_done`, trigger `db_change` on InterviewFeedback), a finding `unproduced_gateway_var` naming `overallRecommendation` and the gateway node id.
  - A workflow where a `set_variable` (or ai output) DOES produce the var → no finding.
- [ ] **Step 2: Verify fail. Step 3: Implement:**
  - `referenced_vars(expr)`: tokenize identifiers, drop FEEL keywords/operators/string+number literals, drop `input`/`variables` roots' leading segment but keep the var name.
  - `producers(defn, registry)`: set-variable `variableName`; ai node `config.outputVariable`/`data.outputs[].name`; db_query result name; trigger input fields; entity columns of the trigger entity (from registry).
  - `analyze_workflow(defn, registry)`: for each gateway/condition, `referenced_vars(expr) - producers_reachable` → findings.
- [ ] **Step 4: PASS. Step 5: Commit.**

### Task B2: Wire into the binding gate (flag, don't crash)

**Files:** Modify wherever the workflow graph gate runs (`backend/services/workflow_graph_gate.py` or the pipeline's workflow validation step); Test.

- [ ] **Step 1:** Call `analyze_workflow` for every generated workflow; collect findings into the build report (and, under `FORGE_BINDING_GATE=strict`, fail the build; else warn). Reuse the existing gate plumbing.
- [ ] **Step 2:** Test that a workflow with an unproduced gateway var surfaces a warning/error through the gate. **Step 3: Commit.**

### Task B3: (Prevention) planner/translator guidance

- [ ] Add to the workflow/planner prompt (near `format_node_catalog`): "Any variable a gateway/condition branches on MUST be produced by an upstream node — set it with a `set_variable`/`ai_decide`/`ai_generate` (declare its output) or read it from the trigger input/entity. Never branch on a variable no prior step writes." Keep it short; this is the source-side prevention that makes B2 fire ~0 times.
- [ ] Commit.

---

## Self-review
- The authority is the RUNTIME (`node_contracts()`), never a hardcoded list — A2/A5 read it live so a new runtime node auto-tightens the guard.
- A1 changes only the AI-node representation; db_*/set_variable/gateway emission is unchanged (assert this).
- The editor may have MORE types than the runtime (legacy `task_pool`/`escalation`); the guard only fails on runtime types MISSING from the editor, never the reverse.
- B is flag-first (no crash); strict mode gates. Prevention (B3) keeps it quiet.

# Conversational Fix-Assistant — Implementation Plan (Slices 0–2)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Spec:** docs/superpowers/specs/2026-07-15-conversational-fix-assistant.md
**Backend tests:** from `backend/` with `/usr/local/bin/python3 -m pytest`.
**Defaults chosen:** on-disk `generation-dossier.json` snapshot + live Postgres overlay; slice-1 scoped to data/logic (workflow + form/page); artifacts+symptom diagnosis in slice 1, runtime probe in slice 2; diagnoser = cheap-locate + capable-patch split.
**Principle:** deterministic-first — the LLM diagnoses + authors patches against existing surgical seams; it never blindly rewrites files. Propose → `[APPLY_FIX]` → apply → verify. Every apply is a git commit (undo).

Anchor files (from the architecture map): `routers/generate.py` (`/chat` @3902, `_get_agent_for_intent` @4712), `agents/orchestrator.py` (`classify_intent`), `routers/workflows.py` (node PATCH @168), `services/patch_applier.py` + `agents/patch_agent.py`, `services/resource_registry_context.py`, `services/post_generate_fixes.py`, `models/project.py` (Conversation/plan), `sse_helpers.py`, frontend `stores/chat.ts` + `components/chat/*`.

---

## SLICE 0 — Workflow value↔column type check (source pass + reusable tool)

### Task 0-1: `workflow_value_types.py` — detect value↔column type mismatches

**Files:** Create `backend/services/workflow_value_types.py`; Test `backend/tests/test_workflow_value_types.py`.

A workflow `db_insert`/`db_update` node maps `config.values[col] = expr`. Compare each `expr` against the target column's type (from the registry / drizzle schema) and flag/repair mismatches:
- `CURRENT_TIMESTAMP`/`now()`/ISO-date literal → into a `uuid`/enum/text/varchar/integer/boolean column = mismatch.
- a literal string that equals the node label or a non-enum value → into an enum/status column = mismatch.
- a bare non-`{{...}}`, non-recognized-literal string into a uuid column = mismatch (should be a `{{input}}` binding).

- [ ] **Step 1: Failing tests** — `analyze_workflow_values(defn, columns_by_table) -> list[finding]`. Fixture = the real `assessmentschedulingworkflow` shape: `values.candidateId="CURRENT_TIMESTAMP"` (uuid) → finding `{node, table:"assessments", column:"candidateId", value:"CURRENT_TIMESTAMP", columnType:"uuid", reason:"timestamp-literal-into-uuid"}`; `values.scheduledAt="CURRENT_TIMESTAMP"` (timestamp) → NO finding; `values.status="Create Assessment Record"` into an enum status → finding `label-string-into-enum`.
- [ ] **Step 2: verify fail. Step 3: implement** the type-compat matrix (a small set of {value-kind} × {column-type} rules; value-kind detected: timestamp-literal / iso-date / number / bool / bare-string / template-binding `{{..}}`). Reuse `fk_semantics`/registry column-type lookup. **Step 4: pass. Step 5: commit.**

### Task 0-2: `repair_workflow_values` — the deterministic corrector (tool + gen pass)

**Files:** Modify `backend/services/workflow_value_types.py` (+`repair_workflow_values`); wire into the workflow generation/validation path (find where workflows are validated post-generation — `workflow_graph_gate.py` or the translator's finalize); Test.

- [ ] **Step 1: Failing test** — `repair_workflow_values(defn, columns_by_table, trigger_inputs) -> (defn', changes)`: a `CURRENT_TIMESTAMP`→uuid mapping is rebound to the matching trigger input (`{{candidateId}}` if present) or DROPPED from values (so the column takes its default/NULL) — never left as the bad literal; a label-string→enum is replaced with a valid enum value or dropped. Returns the change list for narration.
- [ ] **Step 2: verify fail. Step 3: implement** (prefer rebind to a same-named `{{input}}`, else drop; never invent a uuid). Wire the repair into the workflow gen path as a source pass (so the NEXT generation is correct). **Step 4: pass. Step 5: commit.**

### Task 0-3: expose as a callable tool + smoke on real artifact

- [ ] Ensure `analyze_workflow_values` / `repair_workflow_values` are importable as a standalone tool (the Fix-Assistant slice-1 verify step calls `analyze`). Run on `output/mc2xgclv/workflows/assessmentschedulingworkflow.json` and confirm the candidate_id + status findings are produced and repaired. Commit.

---

## SLICE 1 — Recall + Diagnose + FIX intent (data/logic classes)

### Task 1-A: Recall assembler (`services/app_recall.py`)

**Files:** Create `backend/services/app_recall.py`; optionally emit `contracts/generation-dossier.json` at generation time (small addition in `generate.py` after the plan is finalized). Test.

- [ ] **Step 1: Failing tests** — `assemble_recall(project_id, output_dir, db_session=None) -> RecallContext` returns a dossier with: `plan` (from `Conversation.metadata_["plan"]` when a session is passed, else from `contracts/generation-dossier.json` on disk), `entities`/`roles`/`relationships` (from `resource-registry.json`), `contracts` summary (fk-semantics/action/binding), and `history` (recent `AgentJob.instruction` + git log). Provide a `to_prompt_block()` compact rendering. Test with a fixture output dir (no DB) → reads the on-disk dossier; with a stub DB session → overlays the live plan.
- [ ] **Step 2-3:** implement; add `emit_generation_dossier(output_dir, plan)` called once at generation so recall works DB-free. **Step 4-5:** pass + commit.

### Task 1-B: Symptom→diagnosis (`agents/fix_diagnoser.py`)

**Files:** Create `backend/agents/fix_diagnoser.py`; Test (with an injectable `_query` seam like other agents, so tests don't call the model).

- [ ] **Step 1: Failing tests** (using the injectable LLM seam returning canned structured output): `diagnose(symptom, recall_ctx, resource_ctx, output_dir) -> Diagnosis`. Cheap-locate step returns candidate artifact(s) from a symptom taxonomy (grep-style + registry); capable-patch step returns `{artifact:{kind,path}, locator:{nodeId|jsonPointer}, rootCause, proposedFix:{seam, patch}, confidence, explanation}`. Test that a "scheduling fails to save" symptom + the mc2xgclv recall locates `assessmentschedulingworkflow`/`create_assessment_record` and proposes a workflow-node `config.values` patch (validated against `workflow_value_types`). Also a "can't upload CV" symptom → the candidate form's cvUrl control (page/schema seam).
- [ ] **Step 2-3:** implement the two-step diagnoser + the symptom taxonomy (save/create→workflow db_insert; empty list/calendar→page binding; can't upload→file control; missing field→form completeness). The proposed patch MUST target a deterministic seam; free-form is last-resort + low-confidence. **Step 4-5:** pass + commit.

### Task 1-C: Apply layer (`services/fix_applier.py`)

**Files:** Create `backend/services/fix_applier.py`; reuse `routers/workflows.py` node-merge logic + `services/patch_applier.py`. Test.

- [ ] **Step 1: Failing tests** — `apply_fix(output_dir, diagnosis) -> result`: routes by `proposedFix.seam` — `workflow_node_config` → merge into the workflow node JSON (extract the merge helper from `routers/workflows.py` so it's callable outside the route); `page_schema_patch` → `patch_applier.apply`. After apply, calls `post_generate_fixes.apply_post_generate_fixes` + a targeted re-verify (`workflow_value_types.analyze` for workflow fixes). Returns `{applied, changes, verify:{resolved:bool, remaining:[...]}}`. Git commit via the existing `Version` path. Test the candidate_id fix end-to-end on a temp copy of the workflow → values corrected + analyze returns clean.
- [ ] **Step 2-5:** implement (transactional; on verify-fail, do NOT claim resolved). Commit.

### Task 1-D: `FIX` intent + chat orchestration

**Files:** Modify `agents/orchestrator.py` (`classify_intent` + `FIX` in the intent enum), `routers/generate.py` (route `FIX` on has-code projects), `sse_helpers.py` (new event types: `fix_proposal`, `fix_applied`). Test the classifier + the route branch.

- [ ] **Step 1: Failing tests** — `classify_intent` returns `FIX` for symptom/error language on a has-code project ("X is broken/not working/fails/error…") and NOT for feature-add language (stays `REFINE`). The `FIX` route: recall → diagnose → emit a `fix_proposal` SSE event (explanation + diff preview + an `[APPLY_FIX]` chip token) → on a follow-up message carrying `[APPLY_FIX]`, call `fix_applier` → emit `fix_applied` with the verify result. Store both turns in `Conversation`.
- [ ] **Step 2-5:** implement; keep it behind the same conversation/session plumbing. Commit.

### Task 1-E: Frontend — proposal + apply chip + diff card

**Files:** Modify `frontend/src/stores/chat.ts` (`handleSSEEvent`: `fix_proposal`/`fix_applied`), `frontend/src/components/chat/*` (render the proposal card + `[APPLY_FIX]` button that posts the chip like `[APPROVE_PLAN]`; a small diff view). Frontend test if infra allows (vitest may be broken in this env — at minimum typecheck).

- [ ] **Step 1-3:** add the event handling + UI; `[APPLY_FIX]` reuses the existing control-chip POST path. Typecheck clean. **Step 4:** commit.

### Task 1-F: Live E2E on mc2xgclv acceptance set

- [ ] Drive (or script) the symptoms: candidate_id crash, empty calendar, missing CV upload, incomplete form → confirm each: correct diagnosis, a deterministic proposal, apply-on-approval, verify-resolved. Screenshot/log. Commit notes.

---

## SLICE 2 — Broaden + self-heal loop

### Task 2-A: Any pasted runtime/console error → locator
- [ ] Extend `fix_diagnoser` to parse a raw error (Postgres/console/Next stack) → artifact via the stack + registry, not just the symptom taxonomy. Tests with the real candidate_id Postgres error string.

### Task 2-B: Re-diagnose-on-failure loop
- [ ] In `fix_applier`/orchestration: if post-apply verify shows the symptom unresolved, feed the residual back to the diagnoser once (bounded), propose a follow-up, never silently loop. Test the bounded retry.

### Task 2-C: Runtime probe (optional evidence)
- [ ] A read-only probe the diagnoser may request: read the app's recent server/console logs or hit a safe read endpoint to confirm a hypothesis before proposing. Gated, bounded, no writes. Test the probe interface with a stub.

### Task 2-D: Proactive surfacing (stretch)
- [ ] Run the deterministic checks (`workflow_value_types`, binding/read-binding, form completeness) on demand and offer fixes in chat before the user hits the error. Behind a flag.

---

## Self-review
- Slice 0 ships value on its own (next-gen correctness) and is the assistant's verify tool.
- Every fix routes through a deterministic seam; the LLM authors patches, never blind-edits.
- Nothing applies without `[APPLY_FIX]`; git-undo + post-apply validate are the safety net.
- Recall is DB-optional (on-disk dossier) so the fix-chat isn't coupled to Postgres.

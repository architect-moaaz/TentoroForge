# Conversational Fix-Assistant — Design Spec

**Status:** Draft for review (spec-first; a phased implementation plan follows after approval).
**Author:** pairing session 2026-07-15.
**Motivation:** Users find real defects in generated apps ("Create Assessment crashes: candidate_id is a timestamp", "the calendar is empty", "I can't upload a CV"). Today fixing them means the platform team edits the generation pipeline. We want the **product's own chatbot** to diagnose and fix such issues **conversationally**, the same way the app was created — driven by a **plain-language symptom**, grounded in the app's **generation history** via the context engine, and **applied only after the user approves**.

## Goals
1. **Symptom-driven.** Input is a layman description of a broken feature (or a pasted error). The bot infers *what the feature is meant to do*, *why it's failing*, and *where*.
2. **History-aware.** The bot recalls how this specific app was generated — its plan, entities/roles, prior decisions — not just its current files. (This is the "context engine gets the history" ask.)
3. **Propose → approve → apply.** The bot explains the diagnosis + the exact change in plain language, shows a preview, and applies only on an `[APPLY_FIX]` confirmation. Every apply is a git commit (one-click undo).
4. **Deterministic-first fixes.** The bot prefers the surgical, deterministic seams (workflow-node config PATCH, page-schema patch, `apply_post_generate_fixes`, and the hardened authorities — `fk_semantics`, `field_controls`, the archetype builders, the new value-type check) over a free-form code-editing agent. The LLM does **diagnosis + explanation + patch authoring**, not blind file rewriting.
5. **Self-verifying.** After applying, the bot re-runs the relevant validation and reports whether the symptom is resolved.
6. **Conversational + multi-turn.** Clarifies ambiguity ("which of the two assessment forms?"), remembers the thread, and can chain fixes.

## Non-goals (this spec)
- Not replacing the free-form `REFINE` agent for open-ended feature additions — the Fix-Assistant is for *repairing declared intent*, not building new features.
- Not full RBAC enforcement, not new components.
- Not auto-applying without approval (explicitly rejected).

## What already exists (reuse — from the architecture map)
- **Conversational `/chat`** (`routers/generate.py:3902`) with an intent classifier (`agents/orchestrator.classify_intent`), full `Conversation` history in Postgres, and SSE streaming with reconnect (`sse_helpers.py`, `useSSE.ts`, `stores/chat.ts`).
- **Deterministic surgical seams:** `PATCH /workflows/{wf}/nodes/{node}` (`routers/workflows.py:168`) merges one workflow node's `config` and commits — *the exact seam for the candidate_id fix*. Page-schema patch (`agents/patch_agent.py` + `services/patch_applier.py`, transactional + `_PROTECTED_PATHS`) and `pages/{id}/apply`, `data_model schema/apply` for form/page fixes.
- **Closed-resource context:** `services/resource_registry_context.py::build_resource_context(output_dir)` — real entities + columns + drizzle types + FK targets + workflow ids/input columns.
- **Whole-app heal + safety:** `apply_post_generate_fixes(output_dir)` (idempotent guard/repair suite), git commit/undo per edit (`Version` table), `POST .../app/validate`.
- **The plan + original prompt** live in `Conversation.metadata_["plan"]` and the `Conversation` user turns (Postgres); the plan's structural shadow is `contracts/resource-registry.json` on disk.

## What's missing (build these three)
### A. Recall assembler — "why is this app the way it is"
`services/app_recall.py::assemble_recall(project_id, output_dir) -> RecallContext`. Pulls together, per app:
- the **plan** (`Conversation.metadata_["plan"]`) and the **original prompt / refinement turns** (`Conversation`);
- the **canonical registry** (`contracts/resource-registry.json`) + the other contracts (`fk-semantics`, `action-contract`, `binding-contract`, `data-contract`);
- recent **change history** (`AgentJob.instruction`, `Version`/git log) so the bot knows what was already tried.
Emitted as a compact "generation dossier" block for the diagnosis prompt. **Optional optimization:** persist a `contracts/generation-dossier.json` on disk at generation time so recall doesn't always hit Postgres (decouples the fix-chat from the DB and gives a stable on-disk source of intent). *Open question below.*

### B. Symptom → root-cause diagnosis + locator
`agents/fix_diagnoser.py` — an LLM step that takes (symptom NL / error, recall context, the closed-resource context, and the actual on-disk artifacts) and returns a **structured diagnosis**:
```
{ symptom, feature (what it should do, from recall), rootCause,
  artifact: {kind: "workflow"|"page"|"schema", path},
  locator: {nodeId?|jsonPointer?}, proposedFix: {seam, patch}, confidence }
```
- Symptom taxonomy → candidate artifacts (a "save/create X fails" → the `Create<X>`/domain workflow's `db_insert`; "calendar empty" → the calendar page's Calendar binding; "can't upload" → the entity's file field control). The taxonomy is a routing prior; the LLM confirms against the real artifact.
- The `proposedFix.patch` is emitted **against a deterministic seam** whenever possible (a workflow-node `config` merge, a page JSON-Patch, or "call authority X"). Free-form code edit is the last resort and is flagged low-confidence.

### C. `FIX` intent + orchestration
- Add a `FIX` intent to `agents/orchestrator.classify_intent` (distinct from `REFINE`): triggered by symptom/error language on a has-code project.
- Router in `generate.py`: `FIX` → assemble recall → diagnose → **stream a proposal** (plain-language: symptom, cause, the one change, a diff preview) → wait for `[APPLY_FIX]` chip → apply via the diagnosed seam → `apply_post_generate_fixes` → validate → **re-check the symptom** → narrate result. All over the existing SSE plumbing (new event types render with zero frontend rework beyond a chip + diff card).

## The fix loop (end-to-end, candidate_id as the worked example)
1. **User:** "Scheduling an assessment fails to save."
2. **Recall:** app plan says Assessment has `candidateId` (uuid FK→Candidate), `scheduledAt` (timestamp); there's an `assessmentschedulingworkflow`.
3. **Diagnose:** locate `assessmentschedulingworkflow` → `create_assessment_record` (db_insert into `assessments`) → `config.values.candidateId = "CURRENT_TIMESTAMP"` — a timestamp literal into a uuid column (matches the Postgres error class); `status = "Create Assessment Record"` (node label leaked). Root cause + patch: rebind `candidateId` to the trigger's candidate input, drop `CURRENT_TIMESTAMP` (keep it only on `scheduledAt`), set `status` to a real value/enum default.
4. **Propose:** "The Schedule Assessment workflow is writing the current time into the candidate field (a uuid), which the database rejects. I'll bind it to the selected candidate and fix the status. [APPLY_FIX]"
5. **Apply:** `PATCH /workflows/assessmentschedulingworkflow/nodes/create_assessment_record` merging the corrected `config.values`.
6. **Verify:** `apply_post_generate_fixes` + validate; optionally the new **value↔column type check** confirms no remaining type mismatches. Report resolved.

## Slice 0 (prerequisite, ships independently): workflow value↔column type check
A deterministic pipeline pass + reusable tool: every workflow `db_insert`/`db_update` `values[col] = expr` is checked against the schema column's type — a `CURRENT_TIMESTAMP`/date literal into a `uuid`/enum/text column, or a node-label string into an enum column, is a mismatch. At generation it's corrected/flagged at the source (prevention); as a tool it's what the Fix-Assistant calls to verify step 6. This also fixes the candidate_id class for the *next* generation regardless of the chat feature.

## Phasing
- **Slice 0** — workflow value↔column type check (source pass + tool). Independent, immediately useful.
- **Slice 1** — Recall assembler (A) + Diagnoser (B) + `FIX` intent (C), scoped to the two seam-backed classes (**workflow config** and **form/page**), propose→approve, self-verify. Symptom-driven NL input. The candidate_id + the six mc2xgclv classes are the acceptance set.
- **Slice 2** — broaden the locator to any pasted runtime/console error; add a critique/retry loop (if verify fails, re-diagnose once); optional on-disk `generation-dossier.json`.
- **Slice 3** — proactive: surface likely issues before the user hits them (run the checks, offer fixes in chat).

## Safety & trust
- Nothing lands without `[APPLY_FIX]`. Every apply = a git commit; `UNDO` reverts. Post-apply validation gates the "resolved" claim. Deterministic seams are transactional (patch_applier rollback). The diagnoser reports `confidence`; low-confidence or multi-file fixes require explicit approval and show the full diff.

## Open questions (resolve during planning)
1. **Persist the dossier on disk** (`contracts/generation-dossier.json`) at generation time, or assemble recall live from Postgres each fix? (On-disk = DB-decoupled, stable intent record, small gen cost; live = always current.) Leaning on-disk snapshot + live overlay.
2. **Diagnoser model/budget** — one capable call vs a cheap-locate + capable-patch split.
3. Should `FIX` also handle "the app won't build" (compile errors) or stay data/logic-scoped in slice 1? (Leaning: stay data/logic; compile errors already have `visual-editor/fix-error`.)
4. How much of the runtime should the bot probe (read logs, hit an endpoint) vs reason purely from artifacts + symptom? (Leaning: artifacts + symptom for slice 1; runtime probe in slice 2.)

## Success criteria
A user types a plain-language symptom for each of: the candidate_id crash, an empty calendar, a missing CV upload, an incomplete form → the bot recalls the app's intent, explains the real cause, proposes one correct deterministic change, and — on approval — applies it and confirms the symptom is gone, all in the existing chat, with an undo available.

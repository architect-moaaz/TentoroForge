# Generation-Quality: Six Source-Level Fixes (mc2xgclv feedback)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Directive (user):** Fix each issue **at the generation pipeline / at the source** — NOT with post-generate reconciliation guards. A page/field must be produced correctly the first time (deterministic builder reads the registry; the LLM never gets a chance to deviate on non-CRUD archetypes). Prevention over repair.

**Backend tests:** from `backend/` with `/usr/local/bin/python3 -m pytest`. Diagnosed against `output/mc2xgclv` (recruitment ATS; entities Application, Assessment, Candidate, InterviewFeedback, JobOpening).

**Cross-cutting root cause:** the deterministic authority runs fully only for pages it builds fresh (`list`/`form`/`detail`/`dashboard-widgets`). Non-CRUD archetypes (`kanban`/`calendar`) are soft LLM templates with no deterministic builder, so LLM deviations ship. The cure is symmetry: give every archetype a deterministic builder that reads the registry.

Order: **Theme B (field/form) → Theme A (archetype builders) → Theme C (RBAC)**.

---

## THEME B — Field & form fidelity (issues 3, 5)

### Task B-3: CV/document columns derive a FileUpload control (issue 3)

**Files:** Modify `backend/services/field_controls.py` (`resolve_control`, `_semantic_control`); `backend/services/semantic_field_types.py` (`_FIELD_TYPES` + shared name regex). Test: `backend/tests/test_field_controls.py`.

Root cause: `resolve_control` returns `Textarea` for a `text` column at step 4 **before** any name inspection; no `file`/`upload` semantic exists; `FileUpload` is emitted by zero generators.

- [ ] **Step 1: Failing tests** — `resolve_control(name="cvUrl", sql_type="text")` → `("FileUpload", {...})`; also `resumeUrl`, `documentUrl`, `attachmentUrl`, `photoUrl`/`avatarUrl` → FileUpload; `semantic_type="file"` → FileUpload; a plain `description` text column still → `Textarea` (no false positive); a `notes` column stays Textarea.
- [ ] **Step 2: verify fail.**
- [ ] **Step 3: Implement.**
  - Add a shared `_NAME_FILE_RE` (put it in `semantic_field_types.py` next to the other `_NAME_*_RE`, import into `field_controls.py`): matches `(cv|resume|resumé|attachment|document|file|photo|avatar|image|logo|upload|headshot)` optionally followed by `(url|file|key|path|uri)`, OR a bare `*Url/*File/*Key/*Path` whose stem matches the noun set. Anchor so `description`/`notes`/`summary` do NOT match.
  - In `resolve_control`, add a branch that returns `("FileUpload", {"accept": "..."} or {})` **before** the `text→Textarea` and `varchar` name-heuristic returns: fires when `semantic_type in {"file","upload","document"}` OR `_NAME_FILE_RE` matches the column name (regardless of sql_type, since files are stored as text/varchar URLs).
  - Add a `file`/`upload`/`document` branch to `_semantic_control` returning FileUpload.
  - Add `"FileUpload"` to `_FIELD_TYPES` in `semantic_field_types.py` so the re-typer treats a FileUpload node as authoritative (produce+validate symmetry) and never downgrades it.
  - Confirm FileUpload props are minimal/valid against `packages/library/src/components/FileUpload/FileUpload.schema.ts` (don't emit props it doesn't accept).
- [ ] **Step 4: pass. Step 5: commit.**

### Task B-5a: Create pages are built deterministically from the ROUTE entity (issue 5, fault 1)

**Files:** Modify `backend/services/create_page_coverage.py` (`ensure_create_pages_llm` / `ensure_create_pages`, the `_page_has_fields` skip gate); Test.

Root cause: `interview-feedback/new.json` is bound to the wrong entity (`CreateAssessment`) because coverage takes the entity from the authored workflow, and the `_page_has_fields` gate skips any page that "has fields." Source fix: a `/{slug}/new` create page's entity is the **route's registry entity**, and the page is built deterministically from it (`build_form_page`) — the LLM does not author create forms out of a different entity's fields.

- [ ] **Step 1: Failing test** — given a registry with `InterviewFeedback` (route slug `interview-feedback`) and an existing `/interview-feedback/new` page whose Form workflow is `CreateAssessment` and whose fields are Assessment's, the coverage pass REBUILDS it from `InterviewFeedback` (workflow `CreateInterviewFeedback`, fields = InterviewFeedback editable columns). A correctly-bound existing create page is left as-is.
- [ ] **Step 2: verify fail** (today it's skipped).
- [ ] **Step 3: Implement.** Resolve the target entity for `/{slug}/new` from the registry slug (reuse the existing slug→entity resolution). Replace the `_page_has_fields`-only gate with "has fields **for the route entity**": if the page's Form workflow / field set belongs to a different entity than the route resolves to, treat it as a husk and rebuild via `build_create_page`/`build_form_page` bound to the route entity (workflow `Create<Entity>`). Keep correctly-bound pages untouched (idempotent).
- [ ] **Step 4: pass. Step 5: commit.**

### Task B-5b: Form completeness covers ALL editable columns, not just NOT-NULL (issue 5, fault 2)

**Files:** Modify `backend/services/form_field_align.py` (`align_form_fields` backfill). Test.

Root cause: the backfill only appends inputs for `notNull` columns; when the planner marks everything nullable (the norm), nothing is backfilled, so a partially-authored LLM form stays partial.

- [ ] **Step 1: Failing test** — an LLM-authored create form for an entity with 8 editable columns but only 3 emitted, all `notNull:false`, gets the missing 5 appended as inputs built via `deterministic_pages._input_for` (FK→Select, jsonb→KeyValueInput, file→FileUpload, etc.); PK/system-timestamps/hidden actor-tenancy FKs stay excluded.
- [ ] **Step 2: verify fail.**
- [ ] **Step 3: Implement.** Extend the backfill from "required only" to "all editable columns" — reuse `deterministic_pages._editable_columns(columns, hidden)` (minus PK/system/hidden), diff against the form's present field names, append the missing via `_input_for`. Preserve nullability marking (required marker only where notNull). Idempotent.
- [ ] **Step 4: pass. Step 5: commit.**

---

## THEME A — Deterministic archetype builders (issues 2, 4, 1)

Context files: `backend/services/deterministic_pages.py` (`effective_archetype` ~line 92, `build_crud_page` ~779, `build_dashboard_page` ~618, `_gap` ~231, `_dash_card` ~610), `backend/services/schema_pipeline.py` (`_try_deterministic_page` ~254-299), `backend/services/page_type_templates.py` (`_KANBAN`/`_CALENDAR`/`_DASHBOARD`). Registry gives each entity its columns + the list dataSource; the status/stage column and date column are derivable.

### Task A-2: Deterministic `build_kanban_page` (issue 2)

**Files:** Modify `backend/services/deterministic_pages.py` (+`build_kanban_page`, extend `effective_archetype`/`build_crud_page`); wire in `schema_pipeline.py::_try_deterministic_page`. Test.

- [ ] **Step 1: Failing test** — `build_kanban_page(entity="Application", columns, route="/pipeline", registry, ...)` returns a page whose root contains a `Kanban` node bound to the entity's list dataSource (`{{applications}}`), `groupBy` = the entity's status/stage column (detect: a column named `status`/`stage`/`state`/`phase`/`pipelineStage`, prefer an enum column), with card title = the entity's label field; NO Table node. Validate props against `packages/library/src/components/Kanban/Kanban.schema.ts`.
- [ ] **Step 2: verify fail.**
- [ ] **Step 3: Implement** `build_kanban_page`; make `effective_archetype` return `"kanban"` for the kanban archetype/template_key; add a kanban branch to `build_crud_page` (or dispatch directly). Wire into `_try_deterministic_page` so a `kanban` archetype page is built deterministically and never reaches the LLM. Emit the list `dataSources` entry.
- [ ] **Step 4: pass. Step 5: commit.**

### Task A-4: Deterministic `build_calendar_page` + correct `events` binding (issue 4)

**Files:** Modify `backend/services/deterministic_pages.py` (+`build_calendar_page`, extend dispatch); wire in `schema_pipeline.py`. Also tighten `page_type_templates._CALENDAR` to the literal `events` contract (belt for any LLM path). Test.

Root cause: LLM emitted `Calendar` with `bind: "assessmentsList"` (bare name) instead of `events: "{{assessments}}"`; event mode reads `events`. Source fix: build calendar pages deterministically with the correct `events` binding.

- [ ] **Step 1: Failing test** — `build_calendar_page(entity="Assessment", columns, route, registry)` returns root `Stack{ Heading, Calendar }` where Calendar has `events: "{{assessments}}"` (list dataSource), `dateField` = the entity's primary date column (`scheduledAt`/`date`/`startAt`/`dueAt` detection), `titleField` = label field, `colorField` = status column if present; NO Table/MetricTile. Props validate against `packages/library/src/components/Calendar/Calendar.schema.ts` (event mode uses `events`, not `bind`).
- [ ] **Step 2: verify fail.**
- [ ] **Step 3: Implement** `build_calendar_page` + dispatch for the `calendar` archetype in `_try_deterministic_page`; update `_CALENDAR` template to show the exact `events` contract.
- [ ] **Step 4: pass. Step 5: commit.**

### Task A-1: Enrich `build_dashboard_page` layout + spacing (issue 1)

**Files:** Modify `backend/services/deterministic_pages.py` (`build_dashboard_page` ~618-764, `_gap`, `_dash_card`). Test.

Root cause: KPIs in a wrap `Row` (not equal-width), single full-width `Card` per widget stacked vertically, raw `tokens.spacing.6/.4` instead of the semantic tokens the LLM pages use.

- [ ] **Step 1: Failing test** — `build_dashboard_page` output: (a) KPI tiles in a `Grid` with `columns == len(stats)` (equal columns), not a wrap Row; (b) charts/tables laid in a 2-col `Grid` (not one full-width Card each) when ≥2 widgets; (c) root Stack + grids use semantic spacing tokens (`tokens.spacing.semantic.section` / `.card`), not raw `tokens.spacing.6`.
- [ ] **Step 2: verify fail.**
- [ ] **Step 3: Implement** the layout/spacing changes. Keep the 0-LLM determinism. Heading may stay but ensure spacing tokens match the app system.
- [ ] **Step 4: pass. Step 5: commit.**

---

## THEME C — RBAC: User entity, roles, Assessor FK (issue 6)

This is the pending canonical-registry **P7–P11** slice. Chain of breaks: registry hardcodes `roles:[]`; planner never models a persisted `User`; schema_builder skips `User` + template `users.ts` has no role column; `fk_semantics` doesn't know `assessor`.

### Task C-1: Planner models a User entity + role enum + actor FK relations

**Files:** Modify `backend/agents/planner.py` (data_models exemplar ~647, access-control block ~901, mandatory-entity injection ~921). Test (planner normalizer/sanitizer).

- [ ] **Step 1:** When `access_control.roles` names domain actors that own/are-assigned-to records (or any FK column name matches a person pattern `*assessor*/*assignee*/*reviewer*/*recruiter*/*manager*`), the planner MUST emit (a) a `User` data_model mapped to reserved table `users` **with a `role` enum column** populated from `access_control.roles`, plus core profile columns; (b) `relations` entries linking actor FK columns (`Assessment.assignedAssessorId`, `InterviewFeedback.assessorId`) → `User`. Add this to the planner prompt/exemplar AND a deterministic post-planner normalizer so it holds even if the LLM omits it. Test the normalizer directly (feed a plan with `access_control.roles` + an `assessorId` column lacking a relation → assert a User entity with role enum + the relation appear).
- [ ] **Steps 2-5:** TDD + commit.

### Task C-2: Registry carries roles + accessModel + a User node

**Files:** Modify `backend/services/resource_registry.py` (`build_canonical_registry` — line ~210 `"roles": []`; entity build from `_plan_models`). Test.

- [ ] **Step 1:** `build_canonical_registry` populates `roles` from `plan["access_control"]["roles"]` (not `[]`), adds an `accessModel`/ownership section, and always ensures a `User` entity record exists in `entities` (table `users`) so FK targets resolve — even though auth owns the physical table. Test: a plan with roles + a User data_model → registry has non-empty `roles`, a `User` entity, and the assessor columns resolve `fk → User`.
- [ ] **Steps 2-5:** TDD + commit.

### Task C-3: schema_builder merges role column into users + emits assessor .references()

**Files:** Modify `backend/services/schema_builder.py` (reserved-skip ~197-205) and the reserved `users.ts` template. Test.

- [ ] **Step 1:** Instead of blanket-skipping a `User` entity mapped to reserved `users`, MERGE the planner's domain columns (notably the `role` enum + profile fields) into the auth `users` table so `users.ts` carries `role`; and emit `.references(() => users.id)` for `assessorId`/`assignedAssessorId` (target now exists in the registry). Do not create a second `pgTable("users")`. Test: schema output has `users.role` enum + the assessor FK `.references(() => users.id)`.
- [ ] **Steps 2-5:** TDD + commit.

### Task C-4: fk_semantics recognizes assessor/evaluator as assignment people-pickers

**Files:** Modify `backend/services/fk_semantics.py` (`_ASSIGNMENT_NAME_RE` ~33-36). Test.

- [ ] **Step 1:** Add `assessor|evaluator|grader|scorer|examiner|interviewer` to `_ASSIGNMENT_NAME_RE`. Test: with `assessorId` now `fk → users`, `classify_entity_fks` returns role `assignment` (people-picker Select of users), not `plain`/`actor`. (Depends on C-1..C-3 giving the FK a users target.)
- [ ] **Steps 2-5:** TDD + commit.

---

## Verification (after all themes)
- Re-run the affected backend suites; grep the codebase to confirm no new post-generate *guard* was added for A (builders only).
- Rebuild `output/mc2xgclv`-shaped artifacts by invoking the deterministic builders on its registry and confirm: pipeline → Kanban grouped by status; assessments calendar → Calendar with `events:{{assessments}}`; dashboards → KPI Grid + semantic spacing; CV → FileUpload; interview-feedback form → InterviewFeedback fields (complete); registry → non-empty roles + User entity + resolving assessor FK.
- A fresh live generation is the final proof (user-triggered).

## Self-review
- Theme A adds **builders**, not guards — honoring the directive. The `_CALENDAR`/`_KANBAN` template tightening is a belt, not the primary mechanism.
- Theme B-5a rebuilds wrong-entity create pages deterministically (source), not a repair guard bolted after.
- Theme C is the real RBAC slice; C-4 depends on C-1..C-3 landing first (FK target must exist).

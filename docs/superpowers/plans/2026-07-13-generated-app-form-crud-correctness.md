# Generated-App Form + CRUD Correctness Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute task-by-task. Steps use checkbox (`- [ ]`) syntax. Backend tests: from `backend/` run `/usr/local/bin/python3 -m pytest <path> -v`.

**Goal:** Make generated CRUD apps field-model-correct and functional out of the box — required markers, FK/enum dropdowns, edit prefill, working create→list flow, real (not hardcoded) widgets, no component crashes.

**Architecture:** Every fix lands at the GENERATOR (backend `services/*`), verified against a real broken app (`output/wj83u270`, a recruitment ATS), and covered by a deterministic post-generate guard so it can't regress. Two systemic seams cause most of the 12 reported issues; fixing them resolves the cluster.

**Tech Stack:** Python 3.11 backend, deterministic form/page builders in `backend/services/`, post-generate guard suite in `services/post_generate_fixes.py`, generated Next.js apps under `output/<slug>/`.

---

## The two systemic root causes (read first)

**SEAM 1 — LLM-authored forms WIN over the deterministic field-model builder.**
`services/deterministic_pages.build_form_page` (+ `_input_for`/`_is_required`/`_editable_columns`) produces field-model-correct forms (FK→Select+optionsFrom, enum→Select, `validators.required` → the `*`, jsonb→KeyValueInput, edit `defaultValue` bindings). BUT the coverage passes skip a route when the LLM already wrote it:
- `create_page_coverage.ensure_create_pages` ~L273 `if target.exists(): continue`
- `create_page_coverage.ensure_create_pages_llm` ~L210 `if target.exists() and _page_has_fields(target): continue`
- `ensure_edit_routes.ensure_edit_routes` ~L293 `if os.path.exists(edit_fp): continue`
So the LLM's inferior form (plain Inputs, no required marks, camelCase sources, no prefill) ships. **Principle for the fix:** the deterministic field-model repairs must run ADDITIVELY over whatever form shipped (never skip), the way `form_scaffold.repair_fk_dropdowns` already does for FK columns.

**SEAM 2 — Registry metadata is lossy.** `services/registry` / schema extraction records columns as `nullable:true` with empty `enum_values`, so:
- `_is_required` is always False → no `*` markers anywhere (issue #2).
- No values exist to turn `status`/`stage`/`nationality` into Selects (issues #3, #8).
Fixes for #2/#3/#8 must repair the METADATA (or infer it), not just the builder.

## Already fixed this session (do not redo)
- **#9 `uuid:"M"` crash** — `form_scaffold.repair_fk_dropdowns` (commit `e660d96`) now upgrades a plain Input over a resolvable FK column into a `Select`+`optionsFrom`, and `_PERSON_ROLE_FKS` resolves `shortlistedBy`/`interviewedBy`/etc. to `User`. Verified on wj83u270. Tests: `test_form_scaffold.py` 16/16.

---

### Task 1: Required-field markers (issue #2) — capture NOT NULL in the registry

**Root:** schema extraction / `reconcile_entities` records every column `nullable:true`. `deterministic_pages._is_required` needs `nullable:False` (+ no default) to emit `validators.required`.

**Files:**
- Investigate + modify: `backend/services/registry.py` (reconcile_entities / entity column merge), `backend/services/registry_extractor.py` (or wherever columns are read from `src/db/schema/*.ts`).
- Backstop guard: `backend/services/form_scaffold.py` (a repair pass that stamps `validators.required` on form fields whose column is NOT NULL).
- Test: `backend/tests/test_registry_notnull.py`, extend `test_form_scaffold.py`.

- [ ] **Step 1:** Write a failing test: a Drizzle schema file with `varchar("title").notNull()` → after extraction the registry entity's `title` column has `nullable: False` (currently True).
- [ ] **Step 2:** Make the schema-file column extractor detect `.notNull()` (and PK) → `nullable: False`; ensure `reconcile_entities` preserves it (don't overwrite with a nullable-default).
- [ ] **Step 3:** Failing test: a create/edit form field whose column is NOT NULL gets `validators.required` after a post-generate repair pass (even on an LLM form that lacked it).
- [ ] **Step 4:** Add `ensure_required_markers(output_dir, registry)` to `form_scaffold.py`, wire into `post_generate_fixes` (additive; idempotent; skip hidden/system fields). Verify on wj83u270: required fields show `*`.
- [ ] **Step 5:** Commit.

---

### Task 1b: Schema generator must emit `.notNull()` for required domain fields (found during Task 1)

**Root (discovered):** Task 1's mechanism works, but generated `src/db/schema/*.ts` have **zero `.notNull()`** — every domain column is nullable, so the registry correctly reports `nullable:true` and nothing gets marked required. The break is one link up: the schema generator doesn't emit NOT NULL for domain-required fields (a drive's `title`, an application's `candidateId`, etc.).

**Files:** `backend/services/schema_builder.py` (emit `.notNull()` when a plan field is required/`nullable:False`), and check whether the planner marks `data_models[].fields[].required`/`nullable` at all — if not, either (a) planner marks obvious required fields, or (b) `schema_builder` infers required for non-nullable-by-convention fields (PK, FK `*Id`, and non-lifecycle fields the planner flags). Be conservative — don't make optional fields required.

- [ ] **Step 1:** Determine if `plan.data_models[].fields` carry a required/nullable flag today (inspect a real plan + the planner prompt).
- [ ] **Step 2:** If yes → make `schema_builder._emit_entity` add `.notNull()` for required/`nullable:False` fields (test: a required field → `.notNull()` in the emitted `.ts`). If no → add a planner emission of `required` on obviously-required fields OR a conservative inference in schema_builder, then emit `.notNull()`.
- [ ] **Step 3:** Verify end-to-end: a fresh gen's `applications.ts` has `.notNull()` on required cols → registry `nullable:False` → `ensure_required_markers` emits `*`. Commit.

---

### Task 2: Enum/status fields as dropdowns (issues #3, #8) — value source + inference

**Root:** `status`/`stage`/`nationality`/`gender`/`priority`/`type` are plain varchar with no `enum_values` and no harvestable workflow status literals, so `_input_for`/`_decide` correctly leave them as Input.

**Files:**
- Modify: `backend/services/semantic_field_types.py` (add curated name→values dictionary for common enum-ish fields; keep the existing `harvest_workflow_statuses` union), and ensure the planner's declared allowed-values (if any) flow into the registry `enum_values`.
- Backstop: a post-generate repair that converts an Input over an enum-ish column with known values into a `Select`.
- Test: `backend/tests/test_semantic_enum_inference.py`, extend form-scaffold tests.

- [ ] **Step 1:** Decide the value source, in priority order: (a) planner/registry `enum_values` if present; (b) harvested workflow status literals (existing); (c) a CURATED dictionary for well-known fields (e.g. `status`→[Active,Inactive,...] per domain, `priority`→[Low,Medium,High], `stage` from workflow, `nationality`→ISO list is too big → leave as Input; be conservative — only infer where a small, safe value set exists). Do NOT invent values for open-ended text fields.
- [ ] **Step 2:** Failing test: an entity with a `priority` varchar column (no enum_values) → form field is a `Select` with the curated options; a `nationality`/`notes`/free-text column stays an Input.
- [ ] **Step 3:** Implement the curated dictionary + wire into `apply_semantic_field_types` options map (union with harvest + registry). Add a post-generate repair `ensure_enum_selects` for LLM forms.
- [ ] **Step 4:** Verify on wj83u270: `status`/`stage` become dropdowns where a safe value set exists; free-text stays Input. Commit.

---

### Task 3: Edit form prefill (issue #5) — additive defaultValue pass

**Root:** LLM edit form lacks `defaultValue:{{record.field}}` bindings; `ensure_edit_routes.build_edit_schema` (~L205) would add them + a `get` dataSource but is SKIPPED because the edit schema already exists (~L293).

**Files:**
- Modify: `backend/services/ensure_edit_routes.py` — add an additive pass that, for an EXISTING edit schema, ensures a `get` dataSource for the record and sets `defaultValue: {{record.<field>}}` on each editable field lacking one (idempotent; don't rebuild).
- Test: `backend/tests/test_ensure_edit_routes.py`.

- [ ] **Step 1:** Failing test: an existing LLM edit schema whose fields have no `defaultValue` → after the additive pass, every editable field has `defaultValue:{{record.<field>}}` and the page has a `get` dataSource named `record`.
- [ ] **Step 2:** Implement `backfill_edit_defaults(edit_schema, entity, cols)`; call it in `ensure_edit_routes` for the exists branch (instead of `continue`, run the additive backfill). Preserve the field controls the LLM chose.
- [ ] **Step 3:** Verify on wj83u270 `applications/[id]/edit.json`: fields prefill from the record. Commit.

---

### Task 4: Create → list flow (issues #1, #10) — INVESTIGATE then fix

**Symptoms:** "Create Recruitment Drive" succeeds but the row doesn't appear; "All Recruitment Drives" table is empty.

**Files (investigate):** the list page schema (`recruitment-drives/page.json` or the list route), its list dataSource (`op:"list"`, source/table), the create workflow (`CreateRecruitmentDrive.json` — does its db_insert target the right table + succeed?), and the renderer's refetch-after-mutation behavior.

- [ ] **Step 1:** Determine WHY the row is absent: (a) create workflow insert fails/targets wrong table (check table name vs schema — the naming guards should have fixed this, confirm), (b) list dataSource points at wrong slug/table (404 or empty), or (c) the list doesn't refetch after the create navigates back. Reproduce against wj83u270 (or a fresh gen).
- [ ] **Step 2:** Fix at the generator based on the finding — most likely the list dataSource binding (`binding_contract`/`deterministic_pages` list emission) or a create→navigate→refetch gap. Add a guard if a class emerges.
- [ ] **Step 3:** TDD + verify a created row appears. Commit.

---

### Task 5: Static/hardcoded widgets (issues #7, #11) — INVESTIGATE then fix

**Symptoms:** "Drive Updates" hardcoded; "Drive Approval Progress" static.

**Files (investigate):** the dashboard/detail page schemas carrying these widgets, whether they have a real dataSource (`op:"series"`/`list`/`aggregate`) or literal `data`/`items` arrays. Existing: `chart_data_source_guard` binds charts to `op:"series"`.

- [ ] **Step 1:** Identify the widget types + whether they carry hardcoded arrays vs bindings. Classify: chart (→ series binding), progress/stat (→ aggregate binding), or a list widget.
- [ ] **Step 2:** Extend the relevant guard (`chart_data_source_guard` or a new `widget_data_source_guard`) to replace hardcoded widget data with a real dataSource binding when the widget maps to an entity/metric. Leave genuinely-static content alone.
- [ ] **Step 3:** TDD + verify the widget shows real data. Commit.

---

### Task 6: DescriptionList render crash + dead button (issues #4, #6) — INVESTIGATE then fix

**Symptoms:** Candidate view shows `⚠ DescriptionList: render error`; "Run Full Compliance Check" button does nothing.

**Files (investigate):** `packages/library/src/components/.../DescriptionList` (prop contract), the candidate detail schema's DescriptionList node (what props/bindings it passes — likely `items` unresolved/not an array), and the compliance button's action wiring (workflow ref or navigate that resolves to nothing).

- [ ] **Step 1:** Reproduce the DescriptionList crash: find the failing prop (e.g. `items` is `{{binding}}` that resolves to undefined, or a shape mismatch). Decide fix side: harden the component to tolerate missing/non-array items (render placeholder) AND/OR fix the schema emission to pass a valid shape.
- [ ] **Step 2:** For the dead button: trace its action (button_audit); if it references a non-existent workflow/route, repoint or remove per the existing button-audit guard.
- [ ] **Step 3:** TDD (library test for DescriptionList resilience; backend test for button-audit). Rebuild + revendor library if changed. Verify. Commit.

---

### Task 7: The guarantee — form-model repairs always run + seed-smoke gate

**Goal:** stop this whole class from reaching users regardless of which builder wrote the form.

- [ ] **Step 1:** Audit the coverage passes (`ensure_create_pages`, `ensure_create_pages_llm`, `ensure_edit_routes`): the `if exists: continue` skips must be replaced by ADDITIVE field-model repair (FK→Select ✓ done, required markers T1, enum selects T2, edit prefill T3) so an LLM form gets upgraded in place rather than shipped raw. Consolidate these repairs into one idempotent `ensure_form_model_correctness(output_dir, registry)` called from `post_generate_fixes`.
- [ ] **Step 2 (seed-smoke gate):** add an optional final build step that runs `start.sh --seed-only` (boot DB + migrate + seed) and fails the generation loudly on error — catches ANY schema/seed mismatch (the users.password + uuid classes) at build time, not at a user click. Gate behind an env flag; log a clear pass/fail.
- [ ] **Step 3:** Regression-verify on a fresh generation of a multi-word/relational domain: required marks present, FK+enum dropdowns, edit prefills, create appears in list, widgets bound, no crashes, seed clean.

---

## Notes / guardrails
- Verify every fix against the real broken app `output/wj83u270` (and a fresh gen), not just unit tests — these bugs only surface at runtime with real data.
- Prefer ADDITIVE, idempotent post-generate repairs over rebuilding LLM forms (rebuilding clobbers domain-appropriate bespoke forms and loses fields).
- Don't invent enum values for open-ended fields (nationality, notes) — only where a small safe value set is known.
- Related memories: form-model-correctness, relational-select-optionsfrom, table-name-consistency, chart-series-datasource, deterministic-contract-schema.

# Complete Plan Schema — Design Spec

**Goal:** Make the planner's output authoritative for every downstream decision. Nothing in the pipeline should have to *infer* what the planner should have declared.

**Why:** Today the planner emits routes + workflow prose but no entity structure, no field-level type info, no enum values, no workflow inputs. Downstream agents reconstruct the missing information by scraping strings — that's the root cause of enum pollution, wrong control types, incomplete trigger forms, and mis-routed pages. If the plan is complete, downstream construction becomes a pure derivation from a single source.

---

## What's missing today vs. what the plan must carry

Actual [blueprint.json](../../../output/05xmf2ug/.forge/blueprint.json) from the last live generation:

```
entities:         []        ← 0 declared
actors:           []        ← 0 declared
workflow.inputs:  n/a       ← workflows never declare their trigger inputs
page.fields:      n/a       ← form pages never declare their field list
page.notable_choices: []    ← always empty
design_decisions: []        ← always empty
```

The pipeline compensated by:
- `schema_agent` inventing 7 entities from workflow prose
- `page_schema_agent` inventing field lists per page
- `workflow_launch_forms` reading the workflow's write set to guess inputs
- `ensure_enum_selects` scraping strings from workflow `set:` nodes

Every one of those inferences drifts. The complete-plan-schema removes the guesswork by making the plan carry the ground truth up front.

---

## The complete plan shape

```jsonc
{
  "module_name": "cabin-crew-ats",
  "description": "…",
  "domain": {
    "name": "Aviation Recruitment",
    "primary_actors": ["Recruiter", "Candidate", "Admin"],
    "core_verbs": ["apply", "shortlist", "schedule", "interview", "reject"],
    "distinctive_shape": "hiring-pipeline",
    "why": "…"
  },

  // ────────────────────────────────────────────────────────────
  // ACTORS — frozen from the discovery brief, feed User.role enum
  // ────────────────────────────────────────────────────────────
  "actors": [
    {
      "name": "Admin",
      "role": "admin",
      "onboarding": { "source": "platform_org" },
      "responsibilities": ["Invite recruiters", "Manage org settings"]
    }
    // …
  ],

  // ────────────────────────────────────────────────────────────
  // ENTITIES — the ground truth for every form, table, chart, FK
  // Each field carries EVERY property the pipeline needs
  // ────────────────────────────────────────────────────────────
  "entities": [
    {
      "name": "Application",
      "table": "applications",
      "purpose": "A candidate's application to a specific role.",
      "fields": [
        {
          "name": "id",
          "type": "uuid",
          "primary_key": true,
          "not_null": true
        },
        {
          "name": "candidateUserId",
          "type": "uuid",
          "not_null": true,
          "fk": { "table": "users", "column": "id" },
          "label": "Candidate",
          "form_control_hint": "select"     // optional — only when it differs from the type-derived default
        },
        {
          "name": "cabinCrewRoleId",
          "type": "uuid",
          "not_null": true,
          "fk": { "table": "cabin_crew_roles", "column": "id" },
          "label": "Role"
        },
        {
          "name": "status",
          "type": "varchar",
          "not_null": true,
          "enum_values": ["open", "shortlisted", "interview_scheduled", "interviewed", "rejected", "hired"],
          "default": "open",
          "label": "Status"
        },
        {
          "name": "coverNote",
          "type": "text",
          "not_null": false,
          "semantic_type": "multiline",       // -> Textarea (or RichTextEditor)
          "label": "Cover note"
        },
        {
          "name": "createdAt",
          "type": "timestamp",
          "not_null": true,
          "default": "now()",
          "lifecycle": "audit"                // -> hidden in create/edit forms
        }
      ],
      "primary": true,   // has its own list/detail/create pages
      "used_by": ["Interview", "Scorecard"]
    }
  ],

  // ────────────────────────────────────────────────────────────
  // PAGES — every field a form or detail shows is declared here
  // No downstream agent has to guess "which columns belong on this form"
  // ────────────────────────────────────────────────────────────
  "pages": [
    {
      "route": "/apply/[role-id]",
      "name": "ApplyPage",
      "entity": "Application",
      "archetype": "form",
      "action": "create",
      "description": "Candidate applies to a specific role.",
      "notable_choices": [
        "role_id comes from URL, not user input",
        "status auto-set to 'open' — not shown"
      ],
      "fields": [
        { "field": "coverNote", "required": true, "order": 1 }
      ],
      "hidden_fields": ["candidateUserId", "cabinCrewRoleId", "status"],   // filled from context
      "context": {
        "candidateUserId": "session.user.id",
        "cabinCrewRoleId": "url.role-id",
        "status": "'open'"
      }
    },
    {
      "route": "/pipeline/[role-id]",
      "name": "PipelinePage",
      "entity": "Application",
      "archetype": "kanban",
      "action": "list",
      "description": "Recruiter view — applications grouped by status.",
      "columns": ["candidateUserId", "status", "createdAt"],
      "group_by": "status",
      "row_actions": [
        { "label": "Shortlist", "workflow": "ShortlistCandidate" },
        { "label": "Reject",    "workflow": "RejectApplication" }
      ]
    },
    {
      "route": "/settings",
      "name": "SettingsPage",
      "entity": "OrgSettings",
      "archetype": "settings",
      "action": "detail",
      "description": "Org-level preferences.",
      "sections": [
        { "title": "Notifications", "fields": ["notifyOnApply", "notifyOnHire"] },
        { "title": "Branding", "fields": ["logoUrl", "primaryColor"] }
      ]
    }
    // …
  ],

  // ────────────────────────────────────────────────────────────
  // WORKFLOWS — trigger inputs are declared, not inferred from writes
  // ────────────────────────────────────────────────────────────
  "workflows": [
    {
      "name": "ScheduleInterview",
      "purpose": "Recruiter assigns a shortlisted Candidate to an interview slot within a Drive.",
      "trigger": "manual on Application",
      "inputs": [
        { "name": "applicationId", "type": "uuid",      "required": true,  "fk": { "table": "applications", "column": "id" } },
        { "name": "interviewerId", "type": "uuid",      "required": true,  "fk": { "table": "users", "column": "id" }, "label": "Interviewer" },
        { "name": "scheduledAt",   "type": "timestamp", "required": true,  "label": "Interview time" },
        { "name": "driveId",       "type": "uuid",      "required": true,  "fk": { "table": "drives", "column": "id" }, "label": "Drive" },
        { "name": "location",      "type": "varchar",   "required": false, "label": "Location (city or 'Remote')" }
      ],
      "steps": [ /* graph as today */ ],
      "outcomes": ["Interview record created", "Application.status = interview_scheduled"]
    }
  ],

  // ────────────────────────────────────────────────────────────
  // NAV — routes are declared here so link integrity is trivial
  // ────────────────────────────────────────────────────────────
  "nav": {
    "initialFor": {
      "admin":     "/dashboard",
      "recruiter": "/recruiter/dashboard",
      "candidate": "/profile/cv-upload"
    },
    "sidebar": [
      { "role": "admin",     "items": ["/dashboard", "/drives", "/roles", "/settings"] },
      { "role": "recruiter", "items": ["/recruiter/dashboard", "/drives", "/pipeline", "/notifications"] },
      { "role": "candidate", "items": ["/profile/cv-upload", "/roles", "/my-applications"] }
    ]
  }
}
```

---

## The three properties that make this "complete"

1. **Every downstream agent reads. None infers.**
   The schema builder reads `entities[]` directly. The form builder reads `pages[].fields[]` or falls back to the entity. The enum harvester is gone — enums come from `entities[].fields[].enum_values`. The workflow launch form reads `workflows[].inputs[]` verbatim. The sidebar reads `nav.sidebar`.

2. **Every field a form renders is declared exactly once.**
   Either at the entity (`entities[].fields[]`) — the default source of truth — or overridden per page (`pages[].fields[]`) when the form shows a subset. No agent invents fields.

3. **Every navigation target the plan mentions is declared in `nav`.**
   Link integrity becomes a set-membership check against `nav.sidebar` + `pages[].route` + `workflows[].outcomes` — no inference.

---

## Migration path

**Phase 1 — additive (this spec).** Enrich the planner prompt to emit the new fields. Downstream agents keep their existing paths but *prefer* plan-provided data when present. If the plan carries `entities[].fields[].enum_values`, use it; else fall back to the harvester. Both paths run in parallel for a few generations while we verify the LLM emits the enriched shape reliably.

**Phase 2 — cutover.** After 5+ apps show the LLM emits the complete shape, delete the fallbacks. Enum harvester is deleted. semantic_field_types is deleted. `workflow_launch_forms` reads `inputs[]` only. sidebar-syncing reads `nav.sidebar` only. Guards that compensate for these become dead code.

**Phase 3 — validator becomes gate.** `plan_validator` gains a strict mode that rejects plans missing required completeness fields (every entity has fields with types, every workflow has declared inputs, every page has an entity or explicit widgets). Fail fast at plan approval — the model re-emits — the app never gets built on an incomplete plan.

---

## What changes in the planner

Three concrete edits to [backend/agents/planner.py](../../backend/agents/planner.py):

1. **OUTPUT SCHEMA block** (~L838): expand the `data_models[].fields[]` shape to include `not_null`, `enum_values`, `fk: {table, column}`, `default`, `semantic_type`, `lifecycle`, `label`. Add `workflows[].inputs[]`. Add `pages[].fields[]`/`hidden_fields`/`context`. Add top-level `nav`.

2. **STRUCTURED-INPUT MODE** (~L60): re-anchor to the new required fields — every actor role must appear in `nav.initialFor`; every journey step's referenced field must exist in the target entity.

3. **REVISE MODE** (existing): critic feedback that flags missing completeness fields re-prompts with the specific gap (`"Application.status has no enum_values but is used in a status transition"`) rather than free-form review.

---

## Test evidence to lock the change

- Snapshot test: for each of 3 canned discovery briefs (ATS, leave-management, invoice-tracker), the planner emits a plan where every entity field has type + not_null + (enum_values | fk | none), every workflow has inputs, every page has fields or widgets.
- Regression test: on the cabin-crew brief specifically, `entities[].length >= 6`, `workflows[].inputs[].length` for `ScheduleInterview` >= 4, `entities[Application].fields[status].enum_values` has exactly the workflow-emitted values.
- The Bug 1/2/5 from the last live app cannot re-occur with a plan of this shape.

# Business rules: one truth, in sync everywhere — plan

Status: in progress (2026-10-14). Branch: `component-fixes`.

## What is broken today (verified)

| # | Problem | Evidence |
|---|---------|----------|
| 1 | **Two stores.** The Business Rules tab reads/writes the `project_rules` DB table. Generation and Smith read/write the Blueprint's `businessRules`. Nothing connects them. | Task Board: Blueprint has 5 rules, the tab says "No business rules yet". |
| 2 | The tab hides every Blueprint rule (the adapter labels them `rule_type:"business"`, the tab keeps only `condition_action`/`decision_table`). They appear only in the *other* "Rules" tab, read-only and without their logic. | `blueprint_to_editor.rules_from_blueprint`, `BusinessRulesPanel.tsx:37` |
| 3 | Tab saves never reach a Blueprint-built app: the export queries `project_rules` with the short id (`98bhy0p4`) instead of the UUID → silently `[]`. A save triggers no export anyway. | `app/rules/index.json` is `[]` |
| 4 | Smith can't see tab rules; the tab can't see Smith's rules. | `services/smith*` never reads `project_rules` |
| 5 | **Most rules don't run.** Default scope is `form`; the server skips `form` rules and the form route throws away errors and value changes. So "reject a blank title" and "default status to todo" do nothing. | `engine.ts evaluateRuleSet` / `form-rules/route.ts` |
| 6 | The data API passes the URL name (`tasks`); the engine matches rules by exact entity name (`Task`) → rules never fire through `/api/data`. | `data-api-route.ts`, `engine.ts` |
| 7 | The running app caches rules forever → a changed rule needs a restart. Not mirrored to `src/rules` (lost on Vercel). | `engine.ts loadRules` |
| 8 | Most generated rules are prose (`statement`) that nothing enforces; the agent is never told what scope means. A rule the person stated can be dropped (requirements agent is told "something a user can do"). | `executors.py` briefs |
| 9 | Retired (DEPRECATED) rules still show as Active; `write_section(businessRules)` doesn't re-project; rule changes don't re-project prerequisite guards; `read_section` advertises a `rules` section that doesn't exist. | adapter, `writes.py`, `reads.py` |
| 10 | Decision tables from the tab never fire (model never saved). Rule side effects (`trigger_workflow`, `send_notification`) are emitted to nobody. | `DecisionTableMode.tsx`, `data-engine.ts fireRuleEffects` |
| 11 | `blueprint-rules.json` can be written before the rules exist (projection ordering race). | `backend` node waits only on `apis` |

## Design: the Blueprint is the one source of truth

Every way a rule is made or changed goes through `businessRules` in the Living Blueprint:

```
 prompt / requirements ──► business_rules node ──┐
 Smith chat (add/edit/remove rule) ──────────────┼──► Blueprint businessRules ──► projection ──► app rules files ──► runtime engine (reloads on change)
 Business Rules tab (create/edit/toggle/delete) ─┘            │
                                                              └──► Smith context (sees every rule, every turn)
```

* Tab writes are deterministic Blueprint commits (validated with the same checks the build uses, versioned in `changeHistory` so Smith's history shows "added in the Business Rules tab"), then re-projected into the running app. No AI call needed to save a rule.
* Each rule records its **origin**: `brief` (you asked for it), `smith`, `editor` (added in the tab), `generated` (Forge inferred it). Shown in the tab and to Smith.
* The legacy `project_rules` path stays untouched for legacy (non-Blueprint) projects. For Blueprint projects, any business rules previously saved in the tab's table are **adopted** into the Blueprint once (idempotent), so nothing a person made is lost.

## Work items

### A. Blueprint contract (`packages/schema` → `backend/contracts/blueprint.schema.json`)
1. `kind` gains `decision_table` (+ `table`: inputs/outputs/rows/hitPolicy).
2. `origin`: `brief | smith | editor | generated`.
3. `enabled` (default true) — a switched-off rule is kept but not run.
4. Regenerate JSON schema; prove Zod and JSON agree.

### B. Runtime engine (generated apps)
1. **Effective scope**: a rule that refuses or changes data (`show_error`, `set_field`, `set_default`, `clear_field`, `set_required`) is enforced on the server *and* live on the form; only purely visual rules stay form-only. (Projection computes it; schema default stays.)
2. Server `set_required` refuses a save with the field empty.
3. Tolerant model matching (`Task` = `tasks`) for condition-action rules and decision tables.
4. Blank strings count as empty for rule conditions (`title = ""` and `title = null` both catch a blank title).
5. `previous.<field>` available to update rules → "status can't go back from done".
6. Rules reload when their files change (cheap mtime check) — no restart.
7. `trigger_workflow` actually starts the workflow; `send_notification` creates an in-app notification.
8. Rules mirrored to `src/rules/` (serverless deploys).
9. Form route returns errors + the library Form shows them and applies value changes.

### C. Generation pipeline
1. Requirements brief: a rule the person states is kept as its own requirement, worded as the rule, tagged `owner: "businessRules"`.
2. business_rules brief: every tagged requirement must become a rule citing it (`origin: brief`); prefer enforceable kinds; explain scope; decision tables for tabular logic; `previous.` for transitions.
3. Deterministic coverage check: a tagged requirement with no live rule citing it refuses the node (the agent is re-asked with the gap named).
4. Re-project rules in `integration` (after `business_rules`) — fixes the ordering race.

### D. Business Rules tab (frontend + new API)
1. New API `/api/projects/{id}/business-rules`: list (+ catalogue: entities/fields/types/enum values, workflows, requirements), create, update (conflict-safe: refuses if the rule changed since you opened it), toggle, delete (retire), validate. Refuses edits while a build is writing the Blueprint.
2. Panel shows **all** rules, grouped: *Enforced in your app* vs *Written down, not enforced yet* (with "make it enforceable"), with origin, record, where it applies, linked requirements.
3. Editor round-trips Blueprint rules: FEEL → visual condition (parser), falling back to an expression editor; entity/workflow pickers by id; decision tables bound to a record.
4. Live sync: refreshes when a Smith turn ends, while a build runs, and on focus.
5. Old "Rules" tab stops duplicating Blueprint business rules (points to the Business Rules tab).

### E. Smith
1. Context lists each rule with id, kind, enforced or not, where, record, condition, effects, origin, on/off.
2. `read_section` accepts `rules`/`business_rules`; `write_section(businessRules)` re-projects; rule changes re-project prerequisite guards too.
3. add/edit briefs carry the scope and kind guidance; Smith-made rules are `origin: smith`.
4. Routing corpus: threshold, transition, "what rules does my app have" sentences.

### F. Tests
* Backend unit + API tests for every endpoint, adoption, conflicts, build-lock, projection (scope, mirror, decision tables, disabled), coverage check, Smith context.
* Runtime engine tests (node) for scope, tolerant matching, blanks, previous, reload, decision tables, side effects.
* Frontend tests: FEEL ↔ condition round-trip, mapping.
* Live on Kimi with my own small apps (never Mozato): prompt → tab; tab → app (enforced) → Smith; Smith → tab; edit/toggle/delete both ways; conflict; build-in-flight; template copy carries rules.

## Found in live testing (Task Board, 2026-10-14), fixed

Each was found driving a real running app (preview + Postgres), not a fixture.

1. **An app built before a platform change could not compile after its engine was refreshed.** The refreshed bell, frame and data engine import `@/lib/api-path`, `@/lib/push`, `./audit`, `./tenancy`, `./OrgSwitcher` — files the refresh copies only where the app already has them. Every page and API call answered "Module not found". `sync_app.complete_imports` now writes every missing platform module from the platform's templates (never replaces a file, never invents one the platform does not ship); `refresh_engine` and `refresh_frame` both run it.
2. **A tab save waited for the next conversation to reach an older app.** The tab now runs the same `catch_up` a Smith turn starts with (once per platform version), so the app's engine re-reads its rules at once.
3. **The same ask asked twice was two requirements** (`REQ:<slug>` keys were pruned by the registry bootstrap). Requirements are keyed with `prose_key`, the scheme the bootstrap keeps.
4. **A removed rule came back** as a written-down rule "you asked for" at the next catch-up. Removing a rule (tab, chat, or with its record) retires the asks only it answered (`retire_asks`); a kept written-down rule steps aside once another rule enforces the same ask.
5. **A failed Smith add left its ask behind** while saying "nothing has been changed". The ask is withdrawn.
6. **A rule asked for again after removal came back switched off** (same wording → same id → merged onto the old record). A rule asked for now starts on, as Smith's, answering only the new ask; an ask a switched-off rule already answers switches it back on instead of claiming "already enforced".
7. **No length limit could be enforced.** FEEL `string length(x)` added (engine, author-time check, tab); the tab's field reader no longer takes `string length(` for a field.
8. **A rule refusing a workflow's save was reported as a crash** ("Change status failed"). It is a refusal, in the rule's own words ("A task in progress needs a due date.").
9. **Smith's page could cut rules off the end** in a large app; every rule now stays named (one-line form) before anything is cut.
10. Tab: Remove asks twice in place (a browser `confirm()` is blocked in embedded views); the on/off label says Off when off.

Verified live: 48 checks (tab → app 26, required/workflow/lock 9, Smith → tab → app 13), plus a rule built in the tab's own UI, enforced by the app, seen by Smith, switched off and removed from the UI.

# What Forge can build today, and where it stops

Code analysis of branch `smith-revamp` (b12b9f04, merged into smithv4 as 0d951c95), 2026-10-11.
Every claim below was read from the code in this worktree or from a built app under `output/`;
measured numbers come from `2026-10-11-generation-process-analysis.md` §7–8.

## 1. The short answer

Forge builds a role-based, workflow-driven web application from a brief: Next.js 15 on
Postgres, email-and-password sign-in, screens per role, records with ownership, processes
with human steps and AI steps, rules the engine refuses to break, charts, files, in-app
notifications, multiple languages, and a Vercel + Neon publish with a migration trial.
A marketplace of 21 screens reached hand-over in 42 minutes for $16.36 (ECom L5), all
pages served, every route answering as declared, every role seeing only its own rows.

What it cannot do today falls into three groups: things the contract lets an agent declare
that the shipped engine does not execute (scheduled, webhook and on-change triggers, waits,
escalations, rule side effects, SSO); things no part of the platform has (payments, SMS,
custom domains, tenants, native mobile, websockets, an audit trail); and a proof step that
is still slow and low-yield (processes rarely all run through on the first build, and the
first check round takes 20–25 minutes). Section 6 lists each with its file.

## 2. What a person goes through

| Stage | What happens | Measured (ECom L5, 21 screens) |
|---|---|---|
| Brief → requirements gate | `requirements` and `domain_reference` nodes; the person sees requirements and the domain reference side by side and can decline items | 2.5 min |
| Model gate | application model, records and fields, screens, security, integrations; the gate says what such products still lack | 9 min |
| Build | design system, page details, flows, workflows and steps, rules, analytics, layouts, page code, projection, install, assembly (type-check, db push, seed, boot) | 29.5 min |
| Hand-over | the moment the app boots: sign-in table, six-criterion scorecard, Publish enabled | 42 min from first ask, $16.36 |
| Background checks | routes, access as two people per role, rule refusals, process trials, page opening as every role, domain score; reds fixed by cause, capped by yield (6 turns, 2 dry) | first round 20–25 min |
| Afterwards | Smith changes anything by chat (60 verbs); Publish to Vercel/Neon; redeploy with a migration trial on a Neon branch | — |

Gates and refusals that keep the build honest: `agent_contract.apply_agent_result` refuses
fourteen classes of wrong answer (a step not in the node catalogue, a rule the parser cannot
read, a page fact that resolves to nothing, a restricted page naming no role, two login
entities, a role with no entry page, duplicate menu addresses, too few charts, a flow step
naming nothing, an ownership rule the engine cannot apply, a result below 0.40 confidence).
The observer verifies 19 relation edges after every node and routes findings to the owning
agent for up to two rounds (`verification.EDGES`, `observer.OBSERVER_ROUNDS`).

## 3. What a built app contains

**Stack.** Next 15, React 19, Tailwind 3, next-auth 4 (JWT, credentials only), drizzle +
postgres.js, Zod, react-query, Radix, ECharts; vendored `@tentoroforge/{engine,library,
renderer,schema}`; its own Postgres database and its own auth secret per app
(`assembly.py:592, 688–725`).

**Sign-in and access.**
- Login, signup (with an account-type choice when the model has one), set-password for
  invites and resets, `/403`. Sessions carry the role and the user row's scalar columns.
- Middleware built from each page's `access` (`projection.py:3939`): public pages open;
  guests redirected to `/login`; a wrong role to `/403`; the data and workflow APIs a
  public page reads are opened with it.
- Ownership rules (`security.ownershipRules`): `scope: user | workspace`, `through`
  another record (≤3 hops), `unscopedRoles`, `reads: everyone`, `guestColumn` so a
  signed-out visitor can own a cart via the `forge-guest` cookie.
- Logins are a ledger outside the Blueprint (`.forge/accounts.json`): add issues a 7-day
  setup link, remove deactivates, reset re-issues; Smith never holds a password.

**Screens.** 21 page patterns (`dashboard, entity_list, master_detail, record_workspace,
form, wizard, approval_inbox, kanban, calendar, scheduler, timeline, analytics,
search_results, configuration, settings, data_explorer, command_center, split_view,
document_workspace, tool, auth`). Every page gets a deterministic floor layout rendered by
the engine; the `page_code` node then writes React (`load.ts` + `view.tsx` + parts) over
it using the UI kit (24 Radix parts), the library palette (Chart, MetricTile, Sparkline,
Gauge, Kanban, Timeline, ActivityFeed, Calendar, DataGrid, DescriptionList, PersonCard,
ApprovalStepper, Stepper, KeyValueList, MoneyDisplay, Tag, Progress), and the SDK
(`WorkflowForm` with steps, `WorkflowButton`, `WidgetView`, `MapView` on MapLibre,
`Picture`, `CameraCapture`, `BarcodeScanner`, `ImageSearch`, `NearMe`, `useLive`,
`LanguageSwitch`), plus dnd-kit and motion. Shell per app: sidebar, topbar or persona
pills, responsive with a mobile tab bar or drawer. Every write goes through a workflow;
there is no direct CRUD from a page (`ui_engineer.py:682–696`).

**Records.** Field types mapped by the projection: text/email/url/enum, integer, numeric
(money), bool, date, datetime, time, json, location, file/image (a `forge_files` id),
`vector` (pgvector, 512-d, HNSW). Facets: required, unique, enumValues, sensitive (masked
unless the role may see it), references, min/max, examples (seeds), `embedding.of`.
Relationships one-to-one/many/many-to-many with cascade/restrict/set-null. 12 seed rows per
entity from the examples. Spreadsheet import (CSV/TSV/XLSX, 50k rows) lands through the
seeder; CSV export per entity respects access and drops sensitive columns.

**Processes.** The runtime engine executes all 20 node types in the contract: trigger,
action, condition/exclusive gateway, parallel/fork/join, decision table (first/unique/
collect), wait, end (with `refused: true` + message → HTTP 422), user task / approval /
assignment / task pool (pause into the Tasks inbox; assignment by static, role, creator,
entity field, manager, department head, group, round-robin, load-balanced), escalation
(recorded), and the four AI steps. All 16 action types have handlers: `db_insert` (with
find-or-create and array fan-out), `db_update`/`db_delete` (refuse without a WHERE),
`db_query`, `for_each` (≤500), `set_variable`/`transform`/`custom` (FEEL-lite),
`http_call` (30 s), `mcp_tool_call`, `send_email`, `send_notification`,
`generate_document` (PDF), `emit_event`, `wait_for_event`, `ocr_document`, and
`ai_generate/classify/extract/decide` on Claude (extract handles many records and PDF or
image inputs). Triggers that fire: manual (`POST /api/workflows/{id}/execute`) and
`api_event`, including `<entity>.created|updated|deleted` emitted by the data engine.

**Rules.** FEEL-lite: arithmetic, comparison, `and/or/not`, `in [list|range]`, `between`,
`if then else`, `??`, dotted paths, 18 functions (`sum … duration`). `condition_action`
rules run on insert and in forms (`/api/form-rules`); `prerequisite` rules become guard
nodes after the trigger (a refused case answers 422 with the rule's message).

**Analytics.** Widgets as queries: measures (count, count_distinct, sum, avg, min, max) by
up to two dimensions (day…year buckets or numeric ranges), rendered on ECharts in 13
marks. Dashboards must carry ≥3 charts, lists ≥1 (`CHARTS_REQUIRED`).

**Also in every app.** In-app notifications (bell, 30 s poll), Tasks inbox, file upload /
download / preview (Vercel Blob, S3, or bytes in Postgres), PDF documents, SSE live refresh
on record change, per-list search over declared columns, likeness search over CLIP
embeddings when a sidecar is set, i18n (`product.locale` + `languages`, RTL and script
fonts, every visible string through `useT()`), design tokens from the design system, crash
reports posted back to Smith's inbox.

## 4. What Smith can change after the build

Sixty verbs (`services/smith/verbs.py`), each also a tool in the 20-step turn loop:
- Screens: rename, remove, reorder (coded pages), compose a route, add widgets, add/edit/
  remove/reorder/move/split sections, merge screens, remove a page, edit navigation.
- Look: restyle, set or remove the logo; connect Figma or UX Pilot as a design source.
- Processes and rules: add/edit/remove workflow or rule.
- Access: edit access; add/remove/reset a login.
- Data: add/remove/rename an entity, add/rename/remove/retype a field, refresh sample data,
  import, export, back up.
- Definition: requirements, product, APIs, integrations; connect an email service (Resend,
  Microsoft 365, Google Workspace, SendGrid, Mailgun, Postmark, SMTP).
- Lifecycle: revert, rebuild, sync the app to its definition; explain a crash or slowness;
  spend; write a staff guide per role.

Before a write Smith must reproduce the fault on a copy of the data (`try_workflow`,
`try_request`, `open_page` in a browser as a role, `try_upload`); a first write with
nothing tried is sent back. Platform files are patched per app only if a try fails before
and passes after. Smith can read any public web page and measure a site's look.

## 5. Shipping

Publish (`services/deploy/`): one Neon project per app (pg 18, 0.25 CU), one Vercel project,
env vars set in the production target, files uploaded, 300 s poll, smoke test on
`/api/health/db`. Build chain: reset → prepare schema (renames keep rows, removed data goes
to `forge_retired`) → `drizzle-kit push` → seed → `next build`. Redeploy runs the same chain
on a copy-on-write Neon branch first; a refusal goes to Smith for two rounds before the
upload is stopped. Rollback promotes an earlier deployment. Locally the Preview tab boots
the app's database and a dev server under a prefix, two previews at a time.

## 6. Limitations

### 6a. Declared in the contract, not executed by the shipped engine

| What an agent can declare | What happens | Where |
|---|---|---|
| `trigger.kind: schedule` | The tick route exists and Vercel cron calls it every 15 min, but `/api/cron/tick` is not in the middleware's open list, so an unauthenticated tick is redirected to `/login` before its `CRON_SECRET` check. Confirmed on a built app's matcher (`output/zo9k0ekd/app/src/middleware.ts:66`). Scheduled workflows, pending events and expired waits never run in a published app. | `projection.py:3768` `_ALWAYS_OPEN`; `runtime/api-cron/route.ts:77` |
| `trigger.kind: db_change` | The detail is written to `trigger.condition`, but the dispatcher only reads `event` for this kind, so it never matches. (On-create/update/delete works only when declared as `api_event` with an `<entity>.created` name.) | `projection.py:2469`; `runtime/events/triggers.ts:71–75` |
| `trigger.kind: webhook` | No inbound route, no signature check, nothing dispatches on it. | contract only |
| `wait` node | Waits `min(duration, 5000 ms)`; the catalogue default `"1 hour"` becomes 0 ms. | `runtime/workflows/engine.ts:694–705` |
| `escalation` node, task SLAs | Recorded on the task; `processEscalations` is never called by any route. | `runtime/workflows/escalation.ts:60` |
| Rule actions `trigger_workflow`, `send_notification` | Emitted in-process as `rule:*` events; the only subscriber needs a bindings file the Blueprint path never writes. | `runtime/data-engine.ts:741–776` |
| `security.authentication: sso / oauth / magic_link` | Only the credentials provider is wired. | `app-foundation/src/auth.ts` |
| `integrations.kind: payment` | No adapter anywhere; `/api/cart/checkout` only emits an event. | `email_connect.py:68` `LIVE_KEY` |
| `integrations.kind: webhook / mcp / other` | Not used by the projection (MCP works from env vars regardless). | `projection.py:2731–2836` |
| `useAgentChat` hook | Posts to `/api/agent/chat`, which only the legacy plan path emits. Dead in Blueprint apps. | `hooks/useAgentChat.ts:53` |
| `/api/workflow-runs`, `/api/presence` | Never copied: the injector looks under `templates/runtime/api-workflow-runs` but the file is at `templates/api-workflow-runs`; presence is referenced by nothing. | `runtime_injector.py:918` |
| `op: search` (full-text) | The data engine has it (`resolveSearch`, tsvector); the page data-source enum does not, so no page can ask for it. | `blueprint.ts:1081`; `data-engine.ts:1881` |

### 6b. Not in the platform at all

- Payments, SMS, push notifications, any outbound connection other than email.
- OAuth/SSO, magic link, 2FA, self-service "forgot password" (resets come from the owner
  via Smith).
- Custom domains; any host other than Vercel; any database other than Neon Postgres.
- Organisations or tenants inside an app (only `scope: workspace` ownership on a users
  column).
- Dark mode (only light tokens are projected), PWA manifest or service worker, a native
  shell on the Blueprint path.
- Websockets or shared presence (SSE refresh and polling only).
- A record-change audit trail (only the workflow execution log; unmasking a sensitive
  value writes a console line).
- XLSX export; fetching facts or pictures from the internet at runtime; packages beyond
  the allowed import list (anything else fails to compile).

### 6c. Security gaps to know about

- Workflow `db_query` / `db_update` / `db_delete` build their WHERE from the step config
  alone and do not apply the ownership rules the data API applies; a process can read or
  change rows across people. Ownership reaches workflows only as guest stamping
  (`runtime/workflows/index.ts:640–660`). The access check proves the list API, not
  processes.
- The preview proxy serves a project's preview to anyone who knows its short id
  (`routers/preview_proxy.py`).
- An AI step whose API call fails logs a warning and returns an empty answer instead of
  failing the run, so the process continues on nothing (`runtime/workflows/ai.ts:241–244`).
- No rate limiting or bot protection on signup or the public workflow APIs.

### 6d. What the proof step does and does not yet prove

- Routes and access are proven by HTTP and SQL without a model: 78/78 and 17/24 green on
  ECom L2 in about 90 s. Rules are proven by one breaking input each.
- Processes are the weak criterion: on ECom L4's trial 2 of 27 passed; on L5 the trial
  crashed and logic stayed untried; L2 left 8 of 25 unfixed after 56 minutes of repairs.
  No run so far has reached a fully green logic row.
- The browser pass over every page as every role takes 20–25 min per round; the fix loop
  is capped (6 turns, 2 dry), so a build can hand over with reds that stay red.
- First-run reliability across the five real attempts: 2 of 4 booted without a resume;
  0 of 5 reached green logic. Each attempt found platform faults that were then fixed
  (nine between L4 and L5), so the rate is rising, but "one run with no platform fault" is
  still the measurement the analysis lacks.
- Known app-level faults open after L5: minor-unit money shown as major units; the demo
  vendor seeded as Pending so its own catalogue is blocked; the preview proxy sends a
  signed-out app visitor to the platform login; one module per screen from
  `ux_architecture`.

### 6e. Platform limits

- One build at a time per app; `page_code` pauses when the API credit runs out and must be
  resumed.
- Every agent reads the whole Blueprint (`reads={"*"}`), so context and cost grow with the
  app; the page set is split three pages per call, workflows one per call.
- Agents run on `claude-sonnet-5`, Smith on `claude-opus-5`; the effort tables were
  measured on Opus 5. Everything is Anthropic-only, including the in-app AI steps.
- The page writer is held to the kit palette; a design beyond it needs a platform change.
- Smith refuses honestly only for reordering a floor-laid page; other asks it cannot do
  (an SMS connection, an XLSX read without openpyxl, an ambiguous name) are said as such.

## 7. Which applications fit today

**Good fit:** internal tools and back offices; booking, intake and approval flows; CRM-like
record keeping with per-person ownership; marketplaces and catalogues without payment
capture; dashboards over the app's own data; anything where a person triggers each
process from a screen and reviews tasks in an inbox; multilingual and RTL audiences.

**Not yet:** anything that takes money; anything driven by the clock or by another
system's webhook; SSO-only enterprises; multi-tenant SaaS; apps needing native mobile,
offline, or live collaboration; regulated domains needing an audit trail.

**Shortest paths to widen the fit** (in order of leverage, not a plan): open
`/api/cron/tick` in the middleware (one line, unlocks schedules, waits and pending events);
route `db_change` through the same event path as `api_event`; apply ownership rules inside
workflow db steps; call `processEscalations` from the tick; a payment adapter behind the
existing `serves` seam; an OAuth provider behind `security.authentication`.

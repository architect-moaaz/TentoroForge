# Native mobile pages: a React Native agent beside the web page writer

Branch: `smithv5-reactNative` (from `smithv5`). Status: plan, nothing built. Written 2026-10-12.

## Progress (2026-10-13)

Built on `smithv5-reactNative`, in order:

- **Phase 0** done except the read endpoints' type check in a real generated app: 401 JSON for `/api/*`, rules default to `entity`, the hygiene fixes, `/api/read/<op>`. `/api/config` was dropped; lifecycle moves are out of scope.
- **Phase 1 (contract)** done: `mobile.native.enabled`, `nativeCode`, the `native_engineer` capability and refusals, the `native_code` node (a fan-out with no subjects when native is off).
- **Phase 2 (fixed half)** done: `backend/templates/native` (Expo SDK 51 project, cookie-session SDK, component kit). Typechecked and bundled under Metro in a scratch copy; never run on a device.
- **Phase 3 (the writer and the projection)** done: `native_engineer.py` (prompt from the template's README, platform and page rules, a compile loop against the application's own generated types through a shared toolchain) and `native_projection.py` (`<output>/native/`: the fixed half, the web's typed modules, tokens, config, a screen and route per page). Wired into the executor and the `frontend` projection step.

Not built yet: the scorecard checks (every page has a screen, render smoke), the look review (no native render target), Smith verbs to turn native on and redraw a screen, a tab/drawer navigator from `navigation.mobile`, EAS build from `native/` (the Publish panel still builds `mobile/`), and a real end-to-end build.

## Decision record

- **One-to-one.** Every Blueprint page that the web writes gets exactly one native screen. No native-only information architecture in v1. Reason: the Blueprint page maps directly, so parity is checkable.
- **Opt-in per app.** Native costs a second page-writing stage, so it runs only when the Blueprint says so. Decided by the product analysis from the requirements, or set by the owner through Smith.
- **Same backend.** Native screens call the generated app's own HTTP API. They never reach the database. Rules, access, workflows and the database stay single-sourced.
- **Cookie session.** Native keeps next-auth cookies. No token route in v1. Native refuses to enable when the app has no password sign-in, and needs an organisation picker when tenancy is on.
- **Same write path as web.** Native writes go through workflows, as web pages do. Lifecycle enforcement is not brought in for this work (decided 2026-10-12); the existing gap is accepted.
- **Parallel generation.** A `native_code` node runs beside `page_code` in the build graph.
- **Store path.** The Expo project in `mobile/` is the native app, built by EAS Build. A WebView wrapper (`mobile.store`, wrapper mode) remains the lighter option.

## How it fits smithv5

Features on this branch follow one shape (`2026-10-12-six-gaps-closed.md`): contract field, agent paragraph, refusal in `agent_contract.py`, projection, runtime piece, a check on a Bench that lands on the scorecard, a Smith verb in both corpora. Nothing is flag-gated. This plan follows it.

Existing pieces this reuses:

- `orchestrator.py`: `page_code` is `_n("page_code", "ui_engineer", ("ui_direction", "page_layouts", "workflow_steps", "install", "app_flows"), ("pageCode",), fanout="pages", optional=True)`. `native_code` is declared the same way.
- `ui_engineer.compose_page`: plan, write, static/wiring/type checks, look review, repair. `native_engineer` mirrors it.
- `app_sdk.py`: projects typed `schema.ts`, `workflows.ts`, `pages.ts` from the Blueprint. A native counterpart does the same.
- `agent_contract.py`: each agent's write boundary.
- `mobile` in the Blueprint (`installable`, `display`, `orientation`, `push`, `store`), `pwa_check.py`, `smith/mobile_change.py`.
- `mobile_builds` router, `eas_client.py`, `mobile_credentials.py`, `templates/mobile/`.

## Phases

### Phase 0. Backend readiness
Native cannot start until these hold. Verified on this branch 2026-10-12 (read-only; file references are from the check and worth re-reading before editing).

Status: 1 done, 2 partial, 3 mostly open, 4 scope default done (the rest open), 5 dropped by decision, 6 fixed, 7 cookie flow works. Done on `smithv5-reactNative`: 60ded66a (401 for `/api/*`), 85d3292a (rules default to `entity`); not yet run against a live app.

1. **401 JSON for `/api/*`: done (60ded66a).** The generated middleware (`projection.py:4288-4300`, and the foundation `middleware.ts`) is a plain `withAuth`, so an unauthenticated `/api/data/x` is redirected to `/login`. Add an `/api` branch that answers 401 JSON; web pages keep their redirect. Decide whether role-blocked APIs answer 403 JSON.
2. **Base path: partial.** `NEXT_PUBLIC_BASE_PATH` exists (empty for published apps, `/api/projects/{id}/preview/serve` for previews) but is build-time and undiscoverable. Add `GET /api/config` returning the base path, the available sign-in methods (`/api/auth/methods` exists) and the app version.
3. **HTTP reads: mostly open.** No HTTP route for filtered `count`, `total`, `series`, `query`, `runWidget`, `similar`, search, `near`, batch fetch by ids or `me`. Rows are raw (numerics as strings). `limit` is not clamped or NaN-guarded (`data-api-route.ts:238-239`). No PATCH. Filters are equality-only. Add all of these, with SDK-shaped rows and a stable list envelope.
4. **Form-scoped rules on server writes: default changed to `entity` (85d3292a, Zod source, emitted schema and projection); `/api/form-rules` still trusts `body.user`.** Original finding: `evaluateRuleSet` skips `scope: "form"` (`rules/engine.ts:959-964`) and Blueprint-authored rules default to `form` (`projection.py:5195`), so they are never enforced on writes. Decision pending: default authored rules to `entity`, or make server writes also run form-scoped rules. Also stop `/api/form-rules` trusting a client-supplied `body.user`.
5. **Lifecycle moves: dropped by decision.** smithv5 does not contain smithv4's `ee1759d3`, so nothing enforces a record's allowed status moves here, for web or native. Decision (2026-10-12): native does what web does. Every native write goes through a workflow, never `PUT /api/data` on a status field, and the gap is accepted. Revisit if the data API is opened to other clients.
6. **Forgeable actor: fixed.** The actor is the session user or nothing (`runtime_injector.py:1606-1623`).
7. **Auth transport: cookie flow works.** `GET /api/auth/csrf`, then `POST /api/auth/callback/credentials`, then reuse the session cookie. It needs password sign-in on (`security.signIn.password` can switch it off), and SSO and magic link need a browser redirect. With tenancy on, writes are refused until an active organisation is chosen (`POST /api/org`).
8. **Hygiene:** reject a client-sent `input.__guest` for signed-in callers, check the task assignee on resume (`taskId`), and close the gap where a path containing a `.` bypasses the middleware matcher.
9. Tests for each, in the style of `backend/tests/services/` and `templates/runtime/__tests__/`.

Order: 1, then 2/4/8 in parallel, then 3. Spike after 1 to 3.

### Phase 1. Contract
1. Extend `mobile` in `packages/schema/src/blueprint/blueprint.ts`: `mobile.native { enabled, bundleId?, ... }` (final shape decided with `mobile.store`, avoiding two overlapping switches). Emit with `npm run emit:blueprint-schema`.
2. New section `nativeCode` (one row per page: `page`, `screen`, `parts?`, `rationale`, `requirements`), validated by the schema.
3. `agent_contract.py`: a `native_engineer` capability that may write only `nativeCode`; refusals: native on without a `bundleId`, a native screen for a page the Blueprint lacks, a screen naming a field, route or workflow that does not exist.
4. Agent paragraph for the product analysis: when an app needs native (who uses it, where, device features, being told when closed).

### Phase 2. Native SDK and kit
1. Fixed half, shipped as a template under `backend/templates/native/src/sdk`: cookie login (`/api/auth/csrf`, `/api/auth/callback/credentials`, `/api/auth/session`), session restore, logout, `useList`, `useRecord`, `useQuery`, `useWorkflow` (same result shape as the web `useWorkflow`), file upload and camera, money and i18n.
2. Generated half, from `app_sdk.py`'s counterpart: typed `schema.ts`, `workflows.ts`, `pages.ts` so the compiler refuses a missing workflow input or a bad route.
3. Component kit: screen frame (safe area, keyboard), list and card, form fields per Blueprint field type, status badge, empty/loading/error states, stats tile, simple chart, modal and sheet. Sized against the web kit (`components/ui`: 24, plus data table, stats card, simple chart, empty/loading state, status badge).
4. Navigation: Expo Router, routes from `pages[].route`, tabs or drawer from `navigation.mobile`, role-restricted pages from `roles`.
5. Theme from the Blueprint's design tokens.

### Phase 3. The native engineer
1. `services/blueprint/native_engineer.py`: `compose_screen`, same loop as `compose_page` (plan, write, check, look, repair). Reuses `_page_brief`, `page_widget_brief`, `page_policies`.
2. Output is a single component with data hooks, not `load` and `view`.
3. System prompt: native components only, no web imports, safe areas, keyboard handling, touch targets, scrollable lists, hooks for data and workflows, every action wired to a workflow.
4. Large screens in parts, reusing the `screen_parts` cut.
5. `native_code` node in `orchestrator.py`: `fanout="pages"`, `optional=True`, runs only when `mobile.native.enabled`. Needed workflows are added the way `page_code` adds them (`_add_needed_workflows`).
6. Build step (projection) writes `nativeCode` into `mobile/`, replacing the scaffold's `App.tsx`. Reuses the PWA's icons and brand colour.

### Phase 4. Checks (all land on the scorecard)
1. **Parity:** every live page has a native screen, every workflow input a screen launches is collected.
2. **Compile:** tsc against the native kit and generated types.
3. **Static and wiring:** native counterparts of `_static_findings`, `_unwired_actions`, `_unfollowed_flows`.
4. **Contract test:** against the seeded generated app, make the calls each screen makes (cookie login, list, create, update, each workflow). Assert status, row shape, and that rules refuse bad input. This proves the shared database path.
5. **Render smoke:** render every screen with mocked or seeded data; fail on a throw, an error boundary or an empty render.
6. **Look review:** render via Expo web export or an emulator screenshot, then the existing page reviewer. Tooling to be chosen in the spike.
7. Failures go back to the native writer with a retry budget, like the web writer.

### Phase 5. Smith and build
1. Smith verbs in both corpora: set the mobile target, redraw a native screen, edit a native screen. Routing corpus, phrasebook and capabilities entries (tests enforce all three).
2. A page edit marks its native screen stale, or edits both.
3. EAS preview and store builds through the existing `mobile_builds` router. API base URL and environment passed at build time.

## Spike (first thing to build)
Three hand-written screens (a list, a record form, a workflow call) against a seeded generated app, plus a contract test and an EAS preview build. It proves cookie login on iOS simulator and Android emulator, session survival across restart, the guest cookie, a clean 401, and gives real numbers for effort. The hand-written screens become the examples in the native writer's prompt.

## Accounts and EAS

- Hosting does not change: the generated app, API and database stay on Vercel or the hosted UAT. EAS Hosting is not used.
- Used: EAS Build, EAS Submit, and EAS Update for JavaScript-only fixes (verify what Update can ship).
- Accounts: an Expo account (the existing `expo_eas` org credential); for devices and stores an Apple Developer account (`apple_asc`) and a Google Play account (`google_play`). The Android APK and iOS simulator builds need only Expo.
- Open: whose accounts ship customers' apps (Tentoro's, the customer's, or a mix). The per-org credential design supports the customer's.
- Expo's pricing (checked 2026-10-12, see expo.dev/pricing): the free plan has a low-priority queue, 1 concurrent build, 45-minute timeout; paid plans add priority and concurrency. Re-check before budgeting.

## Risks

- Two page writers drift: parity and contract checks are the defence.
- The native kit is most of the work. A screen is only as good as its components.
- Page stage time and cost roughly double for native apps; opt-in contains it.
- The look review depends on a native render target not yet confirmed to work on this machine.
- Apple review: real native screens avoid the thin-wrapper rule.
- No offline writes in v1: data is server-side.

## Open questions

1. How `mobile.native` and `mobile.store` relate (one mode field or two switches).
2. Which render target the look review uses.
3. Whose Expo, Apple and Google accounts own customers' apps.
4. Which Phase 0 items are already fixed on smithv5.

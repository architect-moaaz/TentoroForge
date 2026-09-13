# Criterion Refunds v2 — end-to-end error log

**Date:** 2026-09-13 · **App:** `output/188b8l0s` on http://localhost:3000 (`npx next dev -p 3000`) against the Docker Postgres its `start.sh` boots (port 5434, db `app_188b8l0s`) · **Harness:** `backend/scripts/crawl.mjs` (Playwright from `docker/forge-verify`), signs in, visits every route, clicks every control, reports console errors, failed requests and 404s.

Final state: crawl as Admin **0 findings**, crawl as Front Office Manager **0 findings**, 15 of 15 routes serving, 16 workflows, all eight chain roles able to sign in and see their property's cases.

| # | Symptom | Root cause | Layer | Fix |
|---|---|---|---|---|
| 1 | No sign-in for anyone; `/api/auth/csrf` 500; `/guest/refund-request`, `/support-cases/new` 500 | Stale Next.js dev cache — `TypeError: Cannot read properties of undefined (reading 'call')` — after `src/db/schema/user.ts` and two page schemas were rewritten under the running dev server | dev workflow | restart with `.next` removed |
| 2 | Chain roles cannot exist: `users` has no `role` / `home_property_id` | `src/db/schema/user.ts` was scaffold-OWNED, so the template's auth file overwrote the projection's extended one (platform columns + Blueprint's `role`, `homePropertyId`) on every build | platform · assembly | `user.ts` is a SCAFFOLD_DEFAULT; barrel exports it once (`f37fc32`) |
| 3 | Login 401 "column role does not exist" | The app reads the Docker DB (5434) per its `.env`/`.env.local`; migrations and seed had been applied to the host DB (5432) | environment | columns and seed applied to 5434 |
| 4 | Every property-scoped role — and Admin — sees an empty case list | `RefundCase.propertyId` and `SupportCase.propertyId` are `kind:scope scope:"workspace"`; the engine compares to `session.user.workspaceId`, which auth.ts never set → `property_id = undefined` → zero rows except unscoped roles | platform · contract + auth template | Closed (a8e642a): `RecordScopeRule.actorColumn` names the users column that is the workspace; projection carries it into the manifest, the engine reads `user[actorColumn]`, the auth template projects every scalar users column into the session and the bridge passes the whole session user. Blueprint v135 names `actorColumn: "homePropertyId"` on both rules; the app's hand patches were replaced by the templates and FOM/Revenue read 6 St Giles cases, IA reads 9 |
| 5 | Sign-offs queue filter `{{currentUser.homePropertyId}}` interpolates to nothing | The renderer's interpolation scope calls the signed-in user `user` (`user: ctx.user`); the composer invented `currentUser` | platform · vocabulary seam | seam rewrites `currentUser`/`sessionUser`/`me`/`$user` → `user` (`55a42fa`); v2 layout and page schema rewritten (blueprint v134) |
| 6 | `GET /api/data/users` returns the bcrypt hash | (a) sensitive-columns manifest keyed by Blueprint field `passwordHash` while the platform column is `password`; (b) the engine masked only columns with encrypt-at-rest siblings, so a plain-stored sensitive column fell through | platform · projection + runtime engine | manifest folds platform names (`e2b1327`); engine masks plain-stored sensitive columns unless the caller may unmask (`37ed44f`) |
| 7 | Queues empty even for the right role | Seed held three generic rows at a generic property; no users had a home property | data | 11 properties, 8 role users, 6 St Giles refund cases across the chain with 14 approvals, 2 support cases |
| 8 | `drizzle-kit push --force` hung on the live DB | interactive prompt on a rename-vs-add decision the flag does not cover | tooling | columns added with `ALTER TABLE … IF NOT EXISTS` |
| 9 | Sign-in 401 in ~10 ms for every account in the verification loop, while a single manual attempt succeeded | Harness bug, not the app: zsh does not word-split `$who`, so `set -- $who` sent the email with the password appended and an empty password field | test harness | `set -- ${=who}` |

## Test accounts (password `Criterion1234`, home property St Giles for the property-scoped roles)

reception@, fom@, revenue@, gm@, ia@, finance@, ceo@, admin2@ — all `@criterion.test`; plus the fixture `admin@example.com / admin1234` (role Admin).

## What each queue should show

- FOM (St Giles): four cases Pending approval; RC-STG-0001 waits on the FOM stage, RC-STG-0002 on Revenue Manager, RC-STG-0003 on GM, RC-STG-0004 (service recovery, Revenue Manager not applicable) on Income Auditor.
- Income Auditor queue: RC-STG-0004 waiting; RC-STG-0006 returned with "Please attach both folios".
- Finance posting queue: RC-STG-0005, approved through all four stages.
- Group-wide roles (Income Auditor, Finance, CEO) see all nine refund cases; property-scoped roles see St Giles only.

## Closed after the log

The two platform gaps the log left open were fixed in a8e642a on 2026-09-13: a workspace-scoped ownership rule names its actor column (row 4), and the Select/MultiSelect contracts accept `optionsFrom` without a declared `options` list, so the composer's FK dropdowns are no longer refused by the catalogue. Coverage: `backend/templates/runtime/__tests__/ownership-scope.test.mts` (workspace scope reads the named column, not the fallback), `backend/tests/services/test_projection_ownership.py`, `packages/schema/tests/nodes/inputs.test.ts`.

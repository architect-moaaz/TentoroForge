# Table Data Viewer — Design Spec

**Date:** 2026-06-02
**Status:** Approved (design) — pending implementation plan
**Scope:** Click a table in the ER diagram → the Data Model "Browser" tab opens on that table, showing real rows from the project's database with pagination and click-to-sort columns. Read-only, visible only to org owners/admins.

---

## 1. Goal & decisions

A non-developer admin can inspect the live data behind any modeled table:
- Click a table node in the ER diagram → the **Browser** sub-tab opens pre-selected to that table.
- The grid shows real rows from the project's application database, **paginated** (50/page, existing).
- **Click a column header to sort** ascending/descending (server-side, across the whole table).
- **Read-only** (no edit/delete in this iteration).
- **Admin-only:** only users whose role in this project's org is `owner` or `admin`.

**Confirmed decisions:**
- Admin = org `owner` or `admin` (existing `OrgMemberRole`), enforced on both frontend (hide) and backend (403).
- Surface = reuse the existing Data Model **Browser** sub-tab (not a new tab type); ERD click selects the table there.
- Read-only.
- The whole data path is admin-only: the new endpoint **and** the existing `/db/tables` + `/db/query` (and the SQL/Seed sub-tabs hidden for non-admins).
- The viewer requires the project's **preview to be running** (`project.db_port` is only set then). When it isn't, show "Start preview to view data." Auto-starting preview is out of scope.

## 2. Existing building blocks (reused)

- `backend/routers/data_model.py`: `_get_db_connection(project)` (asyncpg → `localhost:{db_port}/app`, `postgres/postgres`); `GET /db/tables` (information_schema list + columns); `GET /db/query?sql=` (read-only SELECT).
- `backend/routers/orgs.py`: `_require_org_member(org_id, user, db, min_role)` with `OrgMemberRole` owner(3)/admin(2)/member(1).
- `backend/models/project.py`: `db_port`, `output_dir`, `org_id`.
- `frontend/src/components/data-model/DatabaseBrowser.tsx`: table list + paginated grid (PAGE_SIZE 50, prev/next).
- `frontend/src/components/data-model/ERDCanvas.tsx`: React Flow ERD rendering `EntityCardNode` (no table-click handler yet).
- `DataModelPanel` sub-tabs: `erd | browser | sql | seed`.
- `frontend/src/stores/auth.ts`: `user.orgs[]` each `{ org_id, role }`.
- `frontend/src/lib/api.ts`: `api.get/post`.

## 3. Backend changes (`backend/routers/data_model.py`)

### 3.1 New endpoint — `GET /api/projects/{project_id}/db/rows`
Query params: `table` (required), `limit` (default 50, clamp 1..200), `offset` (default 0, ≥0), `sort` (optional column), `dir` (`asc`|`desc`, default `asc`).

Flow:
1. `project = await get_project_with_auth(project_id, user, db)`.
2. **Admin gate:** `await _require_org_member(project.org_id, user, db, min_role=OrgMemberRole.admin)` → 403 otherwise.
3. If `not project.db_port` → `HTTPException(400, "Start preview to view data")`.
4. `conn = await _get_db_connection(project)`.
5. Fetch the table's real columns from `information_schema.columns` for `table` (also validates the table exists; empty → 404 "Table not found").
6. `sql, params = build_rows_query(table, valid_columns, sort, dir, limit, offset)` (see 3.2).
7. `rows = await conn.fetch(sql, *params)`; `total = await conn.fetchval('SELECT count(*) FROM "<table>"')` (table already whitelisted).
8. Serialize rows (reuse the existing JSON-safe serialization from `query_db_readonly`).
9. Return `{ "columns": [...], "rows": [...], "total": int, "limit": int, "offset": int }`. `finally: await conn.close()`.

### 3.2 Pure helper — `build_rows_query(table, valid_columns, sort, dir, limit, offset) -> tuple[str, list]`
Module-level, unit-testable, no DB. Rules:
- `table` and `sort` (if given) MUST be members of `valid_columns`/the validated table set; otherwise raise `ValueError` (caller → 400). This is the injection guard — identifiers are never interpolated unless whitelisted.
- `dir` normalized to `"ASC"`/`"DESC"`; anything else → `"ASC"`.
- Identifiers are double-quoted (`"col"`); `limit`/`offset` are bound params (`$1`,`$2`).
- Returns e.g. `('SELECT * FROM "leave_requests" ORDER BY "created_at" DESC LIMIT $1 OFFSET $2', [50, 0])`; with no `sort`, omit the ORDER BY clause.

Signature detail: `valid_columns: set[str]`; the table name is validated by the caller (step 5 confirms it exists) and passed in already-trusted, but `build_rows_query` still re-checks `sort in valid_columns`.

### 3.3 Admin-gate the existing data endpoints
Add `await _require_org_member(project.org_id, user, db, min_role=OrgMemberRole.admin)` to `list_db_tables` (`/db/tables`) and `query_db_readonly` + the write `POST /db/query`. This makes the entire DB-data path admin-only, consistent with the feature intent. (Behavior change: these were any-member before.)

## 4. Frontend changes

### 4.1 Admin helper — `frontend/src/lib/useIsOrgAdmin.ts` (or a selector in auth store)
`useIsOrgAdmin(orgId): boolean` → `user?.orgs?.some(o => o.org_id === orgId && (o.role === "owner" || o.role === "admin"))`. Pure-ish; the role-check predicate `isOrgAdmin(user, orgId)` is extracted as a pure function for unit testing.

### 4.2 `ERDCanvas.tsx`
Add `onSelectTable?: (table: string) => void` to `ERDCanvasProps`; pass into each `EntityCardNode` via `data`; the card calls it on click of the card header/title. No other ERD behavior changes.

### 4.3 `DataModelPanel`
- Read `orgId` (already available) → `const isAdmin = useIsOrgAdmin(orgId)`.
- **Hide data sub-tabs** `browser | sql | seed` when `!isAdmin` (render only `erd`). The ERD tab stays for everyone (schema, not data).
- Hold `selectedTable` state. Pass `onSelectTable={(t) => { setSelectedTable(t); setSubTab("browser"); }}` to `ERDCanvas`.
- Pass `table={selectedTable}` to `DatabaseBrowser`.

### 4.4 `DatabaseBrowser.tsx`
- Accept a controlled `table?: string` prop; when set, select it (falling back to internal selection when absent, preserving standalone use).
- Replace the data fetch with the new endpoint: `api.get('/api/projects/${projectId}/db/rows?table=${t}&limit=50&offset=${page*50}${sort ? `&sort=${sort}&dir=${dir}` : ''}')`.
- **Sort state** `{ sort: string | null, dir: "asc" | "desc" }`. Clicking a column header cycles: unsorted → asc → desc → asc… on that column (switching columns starts at asc). Render an ▲/▼ indicator on the active column. Reset to page 0 on sort change.
- Use `total` from the response to compute page count for the existing pagination controls.
- **Admin guard** (defense-in-depth): if `!isAdmin`, render an access-denied note (the tab is already hidden, but the component self-guards).
- **Preview-down state:** on 400 "Start preview…", show a friendly empty state with that message instead of an error.

## 5. Data flow

```
ERD table click → onSelectTable(table)
  → DataModelPanel: setSelectedTable, setSubTab("browser")
  → DatabaseBrowser(table) → GET /db/rows?table&limit&offset[&sort&dir]
       → admin gate (403 if not owner/admin)
       → validate table+column → build_rows_query → asyncpg → project DB
       → { columns, rows, total }
  → grid renders; header click → set sort/dir → refetch (page reset)
  → pagination prev/next → offset change → refetch
```

## 6. Error handling

- Non-admin: data sub-tabs hidden; if the endpoint is hit anyway → 403 → access-denied state.
- Preview not running (`db_port` unset) → 400 "Start preview to view data" → friendly empty state.
- Unknown table → 404; unknown sort column → 400 (guarded by `build_rows_query`).
- DB/query failure → inline error in the grid; connection always closed in `finally`.
- Empty table → grid shows headers + "No rows".

## 7. Testing

- **Backend (pytest):**
  - `build_rows_query`: builds correct SQL with/without sort; quotes identifiers; binds limit/offset; clamps dir; raises on `sort` not in `valid_columns` (e.g. `"id; DROP TABLE x"`); raises on unknown table.
  - Admin gate: a member calling `/db/rows` (and `/db/tables`, `/db/query`) gets 403; an admin gets 200 (using the existing `auth_client`/`org_id` fixtures; project + `db_port` may be stubbed or the gate tested before the DB call).
- **Frontend (vitest, logic only — no testing-library):**
  - `isOrgAdmin(user, orgId)` predicate: owner/admin true, member/none false.
  - Sort-cycle reducer: none→asc→desc→asc; switching column resets to asc; page resets to 0.
  - Rows query-param builder (URL string) for table/limit/offset/sort/dir.
- **Manual E2E:** as an admin with preview running, click an ERD table → Browser opens on it with real rows; sort a column asc/desc; paginate; switch tables via ERD; sign in as a member (or simulate) → data sub-tabs are hidden and `/db/rows` returns 403; stop preview → friendly "start preview" state.

## 8. Risks

- **Behavior change:** admin-gating `/db/tables` + `/db/query` removes data access for non-admin members who currently use the SQL console. Intended, but note it in release.
- **Preview dependency:** the viewer is empty/unavailable when preview is down — by design; the message must be clear so it isn't read as a bug.
- **Identifier quoting:** Postgres identifiers are case-sensitive when quoted; fetch real column/table names from `information_schema` and use them verbatim so `"createdAt"` vs `created_at` matches the actual schema.
- **Large tables:** `count(*)` on huge tables can be slow; acceptable for this iteration (admin inspection tool). Could switch to an estimate later if needed.

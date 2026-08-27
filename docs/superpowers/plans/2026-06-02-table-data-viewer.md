# Table Data Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Click a table in the ER diagram → the Data Model "Browser" tab opens on that table, showing real DB rows with pagination and click-to-sort columns; read-only and visible only to org owners/admins.

**Architecture:** A new injection-safe `GET /db/rows` endpoint (pure `build_rows_query` helper whitelists table/column) plus admin-gating the existing DB endpoints. Frontend reuses `DatabaseBrowser` (adds sort + controlled table selection), wires ERD table-click to open it, and hides the data sub-tabs from non-admins. Testable logic lives in pure helpers (`build_rows_query`, `isOrgAdmin`, `nextSortState`, `dbRowsUrl`); React components are verified manually (frontend has no testing-library).

**Tech Stack:** FastAPI + asyncpg (backend), pytest; Next.js + TypeScript + React Query + @xyflow/react (frontend), Vitest.

**Reference spec:** `docs/superpowers/specs/2026-06-02-table-data-viewer-design.md`

---

## Conventions confirmed from the codebase

- Backend `data_model.py` already has `_get_db_connection(project)` (asyncpg → `localhost:{project.db_port}/app`, `postgres/postgres`), `list_db_tables` (`GET /db/tables`), `query_db_readonly` (`GET /db/query`), `execute_db_write` (`POST /db/query`). Row serialization pattern: coerce non-`(str,int,float,bool,None,list,dict)` to `str`.
- Admin gate helper: `from routers.orgs import _require_org_member` ; `from models.org import OrgMemberRole`. Signature `await _require_org_member(org_id, user, db, min_role=OrgMemberRole.admin)` → raises 403 for non-member or insufficient role. `Project.org_id` exists. Role hierarchy owner(3) > admin(2) > member(1).
- Project create (for tests): `POST /api/orgs/{org_id}/projects` body `{name, description?}` → `{id, ...}`. Test fixtures: `auth_client` (signed-in user who is the org **owner**), `org_id`.
- Frontend `api` client: `api.get<T>(path)`. `DatabaseBrowser` props are `{ projectId, dbPort }`, uses React Query, builds `SELECT * FROM "<t>" LIMIT 50 OFFSET <o>` today, paginates via `page` state + `row_count < PAGE_SIZE`. `PAGE_SIZE = 50`.
- `ERDCanvas` props build React Flow nodes whose `data: EntityCardData` carries `{label, columns, relations, onAddField, ...}`. `EntityCardNode` renders the title at `<span className="text-sm font-semibold text-slate-800">{label}</span>` (header div).
- `DataModelPanel({ projectId, dbPort })` holds `subTab: "erd"|"browser"|"sql"|"seed"`, `subTabs` array, renders `ERDCanvas`/`DatabaseBrowser`/`SqlConsole`/seed. It does NOT receive `orgId` — read it with `useParams()` (`next/navigation`).
- Auth: `useAuthStore((s) => s.user)` → `user.orgs: { org_id, role }[]`.
- Frontend tests: Vitest, run `npx vitest run <path>` from `frontend/`. **No testing-library — do not write component render tests.**

---

## File Structure

**Backend:**
- `backend/routers/data_model.py` — add `build_rows_query` (pure), `GET /db/rows` endpoint, admin gates on the 4 DB endpoints.
- `backend/tests/routers/test_db_rows.py` — `build_rows_query` unit tests + admin-gate integration test.

**Frontend:**
- `frontend/src/lib/org-admin.ts` — `isOrgAdmin(user, orgId)` (pure) + `useIsOrgAdmin(orgId)` hook.
- `frontend/src/lib/org-admin.test.ts`
- `frontend/src/lib/db-rows.ts` — `nextSortState`, `dbRowsUrl`, `SortState`/`SortDir` types.
- `frontend/src/lib/db-rows.test.ts`
- `frontend/src/components/data-model/DatabaseBrowser.tsx` — controlled `table` prop, sort, `/db/rows`, total-based pagination.
- `frontend/src/components/data-model/EntityCardNode.tsx` — `onSelectTable` on title click.
- `frontend/src/components/data-model/ERDCanvas.tsx` — `onSelectTable` prop threaded into node data.
- `frontend/src/components/data-model/DataModelPanel.tsx` — admin gate (hide data sub-tabs), `selectedTable` wiring.

---

## Task 1: Backend — `build_rows_query` pure helper (TDD)

**Files:**
- Modify: `backend/routers/data_model.py`
- Test: `backend/tests/routers/test_db_rows.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/routers/test_db_rows.py
"""Tests for the data viewer rows endpoint."""
import pytest
from routers.data_model import build_rows_query


def test_builds_query_with_ascending_sort():
    sql, params = build_rows_query("leave_requests", {"id", "created_at"}, "created_at", "asc", 50, 0)
    assert sql == 'SELECT * FROM "leave_requests" ORDER BY "created_at" ASC LIMIT $1 OFFSET $2'
    assert params == [50, 0]


def test_builds_query_with_descending_sort():
    sql, _ = build_rows_query("t", {"c"}, "c", "desc", 25, 25)
    assert sql == 'SELECT * FROM "t" ORDER BY "c" DESC LIMIT $1 OFFSET $2'


def test_unknown_direction_defaults_to_ascending():
    sql, _ = build_rows_query("t", {"c"}, "c", "sideways", 10, 0)
    assert 'ORDER BY "c" ASC' in sql


def test_no_sort_omits_order_by():
    sql, params = build_rows_query("t", {"c"}, None, "asc", 10, 0)
    assert sql == 'SELECT * FROM "t" LIMIT $1 OFFSET $2'
    assert params == [10, 0]


def test_rejects_sort_column_not_in_table():
    with pytest.raises(ValueError):
        build_rows_query("t", {"id"}, "id; DROP TABLE users", "asc", 10, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/routers/test_db_rows.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_rows_query'`.

- [ ] **Step 3: Implement the helper** in `backend/routers/data_model.py` (place it just above `async def _get_db_connection`):

```python
def build_rows_query(
    table: str,
    valid_columns: set[str],
    sort: str | None,
    direction: str,
    limit: int,
    offset: int,
) -> tuple[str, list]:
    """Build a safe paginated SELECT for the data viewer.

    `table` is already validated by the caller (its columns were fetched from
    information_schema). `sort`, if given, MUST be a real column — otherwise a
    ValueError is raised (the injection guard). Identifiers are double-quoted;
    limit/offset are bound parameters.
    """
    if sort is not None and sort not in valid_columns:
        raise ValueError(f"Unknown sort column: {sort}")
    direction_sql = "DESC" if str(direction).lower() == "desc" else "ASC"
    order = f' ORDER BY "{sort}" {direction_sql}' if sort else ""
    sql = f'SELECT * FROM "{table}"{order} LIMIT $1 OFFSET $2'
    return sql, [limit, offset]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/routers/test_db_rows.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/routers/data_model.py backend/tests/routers/test_db_rows.py
git commit -m "feat(data-viewer): safe build_rows_query helper (TDD)"
```

---

## Task 2: Backend — `/db/rows` endpoint + admin gates

**Files:**
- Modify: `backend/routers/data_model.py`
- Test: `backend/tests/routers/test_db_rows.py`

- [ ] **Step 1: Add the failing admin-gate test**

```python
# append to backend/tests/routers/test_db_rows.py
import pytest


@pytest.mark.asyncio
async def test_db_rows_requires_admin(auth_client, org_id):
    # auth_client is the org OWNER (created the org) → passes the admin gate.
    proj = await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "DV Test"})
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    # Owner: gate passes; no preview running → 400 (NOT 403).
    res = await auth_client.get(f"/api/projects/{project_id}/db/rows?table=anything")
    assert res.status_code == 400, res.text  # "Start preview to view data"

    # A different user who is NOT a member of the org → 403.
    from httpx import ASGITransport, AsyncClient
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as outsider:
        signup = await outsider.post("/api/auth/signup", json={
            "email": "outsider@example.com", "name": "Out", "password": "testpass123",
        })
        assert signup.status_code == 201, signup.text
        outsider.headers["Authorization"] = f"Bearer {signup.json()['access_token']}"
        res2 = await outsider.get(f"/api/projects/{project_id}/db/rows?table=anything")
        assert res2.status_code == 403, res2.text
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/routers/test_db_rows.py::test_db_rows_requires_admin -q`
Expected: FAIL — 404 (route `/db/rows` does not exist yet), not 400/403.

- [ ] **Step 3: Add imports + endpoint + gates** in `backend/routers/data_model.py`.

At the top, add to the imports:

```python
from models.org import OrgMemberRole
from routers.orgs import _require_org_member
```

Add the new endpoint (place it right after `list_db_tables`):

```python
@router.get("/api/projects/{project_id}/db/rows")
async def get_table_rows(
    project_id: uuid.UUID,
    table: str = Query(...),
    limit: int = Query(50),
    offset: int = Query(0),
    sort: str | None = Query(None),
    dir: str = Query("asc"),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only: paginated, optionally-sorted rows from a project table."""
    project = await get_project_with_auth(project_id, user, db)
    await _require_org_member(project.org_id, user, db, min_role=OrgMemberRole.admin)

    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    conn = await _get_db_connection(project)
    try:
        cols = await conn.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = $1
            ORDER BY ordinal_position
            """,
            table,
        )
        if not cols:
            raise HTTPException(status_code=404, detail="Table not found")
        valid_columns = {c["column_name"] for c in cols}
        try:
            sql, params = build_rows_query(table, valid_columns, sort, dir, limit, offset)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        rows = await conn.fetch(sql, *params)
        total = await conn.fetchval(f'SELECT count(*) FROM "{table}"')
        columns = list(rows[0].keys()) if rows else [c["column_name"] for c in cols]
        data = [dict(r) for r in rows]
        for row in data:
            for k, v in row.items():
                if not isinstance(v, (str, int, float, bool, type(None), list, dict)):
                    row[k] = str(v)
        return {"columns": columns, "rows": data, "total": total, "limit": limit, "offset": offset}
    finally:
        await conn.close()
```

Then add the admin gate line to the three existing DB endpoints — immediately after their `project = await get_project_with_auth(...)` line, add:

```python
    await _require_org_member(project.org_id, user, db, min_role=OrgMemberRole.admin)
```

Apply it in `list_db_tables`, `query_db_readonly`, and `execute_db_write`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/routers/test_db_rows.py -q`
Expected: PASS (6 tests). If `test_db_rows_requires_admin` errors on project creation (fixture shape differs), read the `auth_client`/`org_id` fixtures in `tests/conftest.py` and adjust the create call — do NOT weaken the 403/400 assertions.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/data_model.py backend/tests/routers/test_db_rows.py
git commit -m "feat(data-viewer): admin-gated /db/rows endpoint + gate existing db endpoints"
```

---

## Task 3: Frontend — `isOrgAdmin` / `useIsOrgAdmin` (TDD)

**Files:**
- Create: `frontend/src/lib/org-admin.ts`
- Test: `frontend/src/lib/org-admin.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/org-admin.test.ts
import { describe, it, expect } from "vitest";
import { isOrgAdmin } from "./org-admin";

const user = (role: string, org = "o1") => ({ orgs: [{ org_id: org, role }] });

describe("isOrgAdmin", () => {
  it("is true for an owner of the org", () => {
    expect(isOrgAdmin(user("owner"), "o1")).toBe(true);
  });
  it("is true for an admin of the org", () => {
    expect(isOrgAdmin(user("admin"), "o1")).toBe(true);
  });
  it("is false for a member", () => {
    expect(isOrgAdmin(user("member"), "o1")).toBe(false);
  });
  it("is false for an admin of a different org", () => {
    expect(isOrgAdmin(user("admin", "other"), "o1")).toBe(false);
  });
  it("is false when user is null/undefined", () => {
    expect(isOrgAdmin(null, "o1")).toBe(false);
    expect(isOrgAdmin(undefined, "o1")).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/lib/org-admin.test.ts`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```typescript
// frontend/src/lib/org-admin.ts
import { useAuthStore } from "@/stores/auth";

interface UserLike {
  orgs?: { org_id: string; role: string }[];
}

/** True when the user is an owner or admin of the given org. */
export function isOrgAdmin(user: UserLike | null | undefined, orgId: string): boolean {
  return !!user?.orgs?.some(
    (o) => o.org_id === orgId && (o.role === "owner" || o.role === "admin"),
  );
}

/** Hook form, reads the current user from the auth store. */
export function useIsOrgAdmin(orgId: string): boolean {
  const user = useAuthStore((s) => s.user);
  return isOrgAdmin(user, orgId);
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/lib/org-admin.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/org-admin.ts frontend/src/lib/org-admin.test.ts
git commit -m "feat(data-viewer): isOrgAdmin / useIsOrgAdmin helper (TDD)"
```

---

## Task 4: Frontend — `db-rows` helpers (TDD)

**Files:**
- Create: `frontend/src/lib/db-rows.ts`
- Test: `frontend/src/lib/db-rows.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/db-rows.test.ts
import { describe, it, expect } from "vitest";
import { nextSortState, dbRowsUrl } from "./db-rows";

describe("nextSortState", () => {
  it("sorts a new column ascending", () => {
    expect(nextSortState({ sort: null, dir: "asc" }, "name")).toEqual({ sort: "name", dir: "asc" });
  });
  it("toggles asc -> desc on the same column", () => {
    expect(nextSortState({ sort: "name", dir: "asc" }, "name")).toEqual({ sort: "name", dir: "desc" });
  });
  it("clears sort on the third click of the same column", () => {
    expect(nextSortState({ sort: "name", dir: "desc" }, "name")).toEqual({ sort: null, dir: "asc" });
  });
  it("switching columns restarts at ascending", () => {
    expect(nextSortState({ sort: "name", dir: "desc" }, "age")).toEqual({ sort: "age", dir: "asc" });
  });
});

describe("dbRowsUrl", () => {
  it("builds a url without sort", () => {
    expect(dbRowsUrl("p1", "users", 0, 50, null, "asc")).toBe(
      "/api/projects/p1/db/rows?table=users&limit=50&offset=0",
    );
  });
  it("includes offset for later pages and the sort params", () => {
    expect(dbRowsUrl("p1", "users", 2, 50, "name", "desc")).toBe(
      "/api/projects/p1/db/rows?table=users&limit=50&offset=100&sort=name&dir=desc",
    );
  });
  it("url-encodes the table and sort", () => {
    expect(dbRowsUrl("p1", "a b", 0, 50, "c d", "asc")).toBe(
      "/api/projects/p1/db/rows?table=a%20b&limit=50&offset=0&sort=c%20d&dir=asc",
    );
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/lib/db-rows.test.ts`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```typescript
// frontend/src/lib/db-rows.ts
export type SortDir = "asc" | "desc";
export interface SortState {
  sort: string | null;
  dir: SortDir;
}

/** Click cycle for a column header: new column -> asc -> desc -> cleared. */
export function nextSortState(current: SortState, column: string): SortState {
  if (current.sort !== column) return { sort: column, dir: "asc" };
  if (current.dir === "asc") return { sort: column, dir: "desc" };
  return { sort: null, dir: "asc" };
}

/** Build the data-viewer rows URL (page is 0-based). */
export function dbRowsUrl(
  projectId: string,
  table: string,
  page: number,
  pageSize: number,
  sort: string | null,
  dir: SortDir,
): string {
  const offset = page * pageSize;
  let url = `/api/projects/${projectId}/db/rows?table=${encodeURIComponent(table)}&limit=${pageSize}&offset=${offset}`;
  if (sort) url += `&sort=${encodeURIComponent(sort)}&dir=${dir}`;
  return url;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/lib/db-rows.test.ts`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/db-rows.ts frontend/src/lib/db-rows.test.ts
git commit -m "feat(data-viewer): db-rows sort-cycle + url helpers (TDD)"
```

---

## Task 5: Frontend — `DatabaseBrowser` controlled table + sort + `/db/rows`

**Files:**
- Modify: `frontend/src/components/data-model/DatabaseBrowser.tsx`

Component change (no unit test — uses the helpers from Task 4; verified manually in Task 7). Keep all existing markup; change the data fetch and headers.

- [ ] **Step 1: Update props, types, and state**

Change the `QueryResult` interface and `DatabaseBrowserProps`, and add sort state + a controlled-table effect:

```typescript
import { useState, useEffect } from "react";
import { nextSortState, dbRowsUrl, type SortState } from "@/lib/db-rows";
// ...existing imports...

interface RowsResult {
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
}

interface DatabaseBrowserProps {
  projectId: string;
  dbPort?: number | null;
  /** When set, the browser is controlled to this table (e.g. from an ERD click). */
  table?: string | null;
}

export function DatabaseBrowser({ projectId, dbPort, table }: DatabaseBrowserProps) {
  const [selectedTable, setSelectedTable] = useState<string | null>(table ?? null);
  const [page, setPage] = useState(0);
  const [sortState, setSortState] = useState<SortState>({ sort: null, dir: "asc" });

  // When the controlled `table` prop changes, switch to it and reset view.
  useEffect(() => {
    if (table && table !== selectedTable) {
      setSelectedTable(table);
      setPage(0);
      setSortState({ sort: null, dir: "asc" });
    }
  }, [table]); // eslint-disable-line react-hooks/exhaustive-deps
```

- [ ] **Step 2: Replace the data query**

Replace the `queryResult` `useQuery` block with the `/db/rows` call:

```typescript
  const offset = page * PAGE_SIZE;
  const { data: queryResult, isLoading: queryLoading } = useQuery({
    queryKey: ["project", projectId, "db-rows", selectedTable, page, sortState.sort, sortState.dir],
    queryFn: () =>
      api.get<RowsResult>(
        dbRowsUrl(projectId, selectedTable as string, page, PAGE_SIZE, sortState.sort, sortState.dir),
      ),
    enabled: !!selectedTable && !!dbPort,
  });
```

- [ ] **Step 3: Make column headers sortable**

Replace the `<thead>` block so each header is a button that cycles sort and shows an indicator:

```tsx
                <thead className="sticky top-0 bg-slate-50">
                  <tr>
                    {queryResult.columns.map((col) => (
                      <th
                        key={col}
                        className="cursor-pointer select-none border-b px-3 py-2 text-left font-medium text-slate-600 hover:bg-slate-100"
                        onClick={() => {
                          setSortState((s) => nextSortState(s, col));
                          setPage(0);
                        }}
                      >
                        {col}
                        {sortState.sort === col ? (sortState.dir === "asc" ? " ▲" : " ▼") : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
```

- [ ] **Step 4: Fix pagination to use `total`**

Replace the pagination footer's count text and the next-button disable check:

```tsx
            <div className="flex items-center justify-between border-t px-3 py-2">
              <span className="text-xs text-muted-foreground">
                Showing {queryResult.rows.length === 0 ? 0 : offset + 1}–{offset + queryResult.rows.length} of {queryResult.total}
              </span>
              <div className="flex gap-1">
                <Button variant="ghost" size="icon" className="h-7 w-7" disabled={page === 0} onClick={() => setPage(page - 1)}>
                  <ChevronLeft className="h-3 w-3" />
                </Button>
                <Button variant="ghost" size="icon" className="h-7 w-7" disabled={offset + PAGE_SIZE >= queryResult.total} onClick={() => setPage(page + 1)}>
                  <ChevronRight className="h-3 w-3" />
                </Button>
              </div>
            </div>
```

Also update the empty-state condition that referenced `queryResult.rows.length === 0` — it already handles `!queryResult || queryResult.rows.length === 0`, which is fine with the new shape.

- [ ] **Step 5: Typecheck + commit**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep "DatabaseBrowser" || echo "DatabaseBrowser: clean"`
Expected: no errors in DatabaseBrowser.

```bash
git add frontend/src/components/data-model/DatabaseBrowser.tsx
git commit -m "feat(data-viewer): DatabaseBrowser controlled table + column sort via /db/rows"
```

---

## Task 6: Frontend — ERD click → open Browser; admin gate

**Files:**
- Modify: `frontend/src/components/data-model/EntityCardNode.tsx`
- Modify: `frontend/src/components/data-model/ERDCanvas.tsx`
- Modify: `frontend/src/components/data-model/DataModelPanel.tsx`

Component wiring (no unit test — manual in Task 7).

- [ ] **Step 1: `EntityCardNode` — clickable title**

In `EntityCardData` (the `interface EntityCardData extends Record<string, unknown>` block), add:

```typescript
  onSelectTable?: (tableName: string) => void;
```

Destructure it in `EntityCardNodeComponent` (`const { label, columns, ..., onSelectTable } = data;`) and make the title span open the data viewer:

```tsx
        <span
          className={onSelectTable ? "text-sm font-semibold text-slate-800 cursor-pointer hover:underline" : "text-sm font-semibold text-slate-800"}
          onClick={onSelectTable ? () => onSelectTable(label) : undefined}
          title={onSelectTable ? "View data" : undefined}
        >
          {label}
        </span>
```

- [ ] **Step 2: `ERDCanvas` — thread the callback**

Add `onSelectTable?: (tableName: string) => void;` to `ERDCanvasProps`, destructure it in the `ERDCanvas({ ... })` params, and include it in each node's `data`:

```typescript
      data: {
        label: table.name,
        columns: table.columns,
        relations: table.relations,
        onAddField,
        onEditField,
        onDeleteModel,
        onAddIndex,
        onAddRelation,
        onSelectTable,
      },
```

- [ ] **Step 3: `DataModelPanel` — admin gate + selection wiring**

At the top of the component:

```typescript
import { useParams } from "next/navigation";
import { useIsOrgAdmin } from "@/lib/org-admin";
// ...
  const params = useParams();
  const orgId = params?.orgId as string;
  const isAdmin = useIsOrgAdmin(orgId);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
```

Filter the data sub-tabs for non-admins — replace the `subTabs` array definition's usage so only `erd` shows when `!isAdmin`:

```typescript
  const allSubTabs = [
    { id: "erd" as SubTab, label: "ERD", icon: GitBranch },
    { id: "browser" as SubTab, label: "Browser", icon: Table2 },
    { id: "sql" as SubTab, label: "SQL", icon: Terminal },
    { id: "seed" as SubTab, label: "Seed", icon: Sprout },
  ];
  const subTabs = isAdmin ? allSubTabs : allSubTabs.filter((t) => t.id === "erd");
```

Guard the active sub-tab so a non-admin can never be on a data tab (e.g. after a role change):

```typescript
  useEffect(() => {
    if (!isAdmin && subTab !== "erd") setSubTab("erd");
  }, [isAdmin, subTab]);
```

Pass the selection callback to `ERDCanvas` (only for admins) and the controlled table to `DatabaseBrowser`:

```tsx
            <ERDCanvas
              appModel={appModel}
              /* ...existing handlers... */
              onSelectTable={isAdmin ? (t) => { setSelectedTable(t); setSubTab("browser"); } : undefined}
            />
```

```tsx
          {subTab === "browser" && (
            <DatabaseBrowser projectId={projectId} dbPort={dbPort} table={selectedTable} />
          )}
```

Ensure `useEffect` is imported from React in this file.

- [ ] **Step 4: Typecheck + commit**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -E "EntityCardNode|ERDCanvas|DataModelPanel" || echo "ERD wiring: clean"`
Expected: no errors in these three files.

```bash
git add frontend/src/components/data-model/EntityCardNode.tsx frontend/src/components/data-model/ERDCanvas.tsx frontend/src/components/data-model/DataModelPanel.tsx
git commit -m "feat(data-viewer): ERD table click opens Browser; hide data tabs from non-admins"
```

---

## Task 7: Manual end-to-end verification

No code. Servers must be running (backend 6500, frontend 6501, Postgres 5432) and a project's **preview must be started** so its DB exists.

- [ ] **Step 1: Start a project preview**

In the browser at `http://localhost:6501`, sign in as an org owner/admin (`admin@example.com` / `password123`), open a project that has generated entities, and start its **preview** (so `db_port` is set).

- [ ] **Step 2: Open data from the ERD**

Go to the **Data Model** tab → **ERD**. Click a table node's title. Verify it switches to the **Browser** sub-tab with that table selected and shows real rows.

- [ ] **Step 3: Sort + paginate**

Click a column header — rows re-sort ascending (▲); click again → descending (▼); click again → unsorted. Use the pagination arrows; verify "Showing X–Y of TOTAL" and that next is disabled on the last page.

- [ ] **Step 4: Admin gate**

Confirm the **Browser / SQL / Seed** sub-tabs are visible as an owner/admin. (If you have a member account, sign in as it and confirm those three sub-tabs are hidden and only ERD shows; a direct `GET /api/projects/{id}/db/rows?table=...` returns 403.)

- [ ] **Step 5: Preview-down state**

Stop the preview and reopen Browser — verify the friendly "No database running — start preview first" state instead of an error.

- [ ] **Step 6: Final commit (if any tweaks)**

```bash
git add -A && git commit -m "chore(data-viewer): manual verification fixes"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** ERD click → Browser on table (Tasks 6) · real rows (Tasks 2,5) · pagination (Task 5) · column sort asc/desc (Tasks 4,5) · admin-only FE hide (Task 6) + BE 403 (Task 2) · injection-safe query (Tasks 1,2) · requires preview / friendly state (Tasks 2,5) · read-only (no write paths added). All covered.
- **Placeholders:** none — every code step is concrete.
- **Type consistency:** `build_rows_query(table, valid_columns, sort, direction, limit, offset)` used identically in helper + endpoint; `SortState`/`nextSortState`/`dbRowsUrl` consistent across `db-rows.ts` and `DatabaseBrowser`; response shape `{columns, rows, total, limit, offset}` matches between endpoint (Task 2) and `RowsResult` (Task 5); `isOrgAdmin`/`useIsOrgAdmin` consistent across Tasks 3 and 6.
- **Note:** the endpoint param is named `dir` (FastAPI query) but the helper param is `direction` — the endpoint passes `dir` positionally into `build_rows_query(..., dir, ...)`, so they line up.

# Aggregate-Spec Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dashboard `MetricTile` bindings like `{{dashboardStats.todayCount}}` resolve to real numbers instead of rendering the literal template string, by giving `op:"aggregate"` dataSources a computable per-field `metrics` spec and a working runtime resolver.

**Architecture:** Three layers. (1) The **schema agent** emits a `metrics` map on each `op:"aggregate"` dataSource, each key matching a MetricTile binding. (2) A deterministic backend **floor** (`aggregate_spec.py`) reconciles bindings ↔ metrics — every `{{aggSource.field}}` referenced by a MetricTile gets a valid metric (synthesised from field-name heuristics + registry validation when the agent omits it), so a binding can never be left uncomputable. (3) A real runtime **resolver** (`resolveAggregate` in `data-engine.ts`, replacing the non-functional `executeAggregation` sketch) computes each metric with Drizzle and returns an object; the bridge + `renderSchemaPage` route `op:"aggregate"` to it so `previewData[name]` is `{todayCount: N, …}`.

**Tech Stack:** Python (backend pipeline + pytest), TypeScript (Next.js runtime, Drizzle ORM, vendored `@tentoroforge/{renderer,engine}` packages), Vitest for TS.

---

## Why this is needed (root cause)

On the vet-clinic app `4sashx7f`, `/analytics` MetricTiles render the literal `{{dashboardStats.todayCount}}`. Confirmed causes:
- The dataSource is `{"name":"dashboardStats","entity":"Appointment","op":"aggregate"}` with **no spec** — nothing says what `todayCount` is.
- The data-engine bridge (`data-engine-bridge.ts`) has **no `op:"aggregate"` branch** — an aggregate source falls through to the list branch and returns an array, so `previewData.dashboardStats` is an array and `.todayCount` is `undefined`.
- `interpolate()` (renderer) deliberately keeps the literal for unresolved whole-template bindings (so the editor preview shows placeholders) — so `undefined` surfaces as raw `{{…}}`.
- `executeAggregation` in `data-engine/aggregations.ts` is a **sketch** ("the implementer should adapt to the actual ORM"; uses `db[table]`, `db.count()` which are not real Drizzle) — it would throw if called.

The real Drizzle pattern already exists in `data-engine.ts` `stats()`: `db.select({ total: count() }).from(entity.table)`.

## Design decisions (locked)

**Metrics spec shape** (on an `op:"aggregate"` dataSource):
```jsonc
{
  "name": "dashboardStats",
  "entity": "Appointment",          // default entity for metrics that omit their own
  "op": "aggregate",
  "metrics": {
    "todayCount":          { "fn": "count", "window": "today", "dateField": "date" },
    "monthlyRevenue":      { "fn": "sum", "field": "total", "entity": "Invoice", "window": "month", "dateField": "issuedAt" },
    "pendingInvoiceCount": { "fn": "count", "entity": "Invoice", "filter": { "status": "pending" } },
    "overdueVaccineCount": { "fn": "count", "entity": "VaccinationRecord", "filter": { "status": "overdue" } }
  }
}
```
- `fn`: `count | sum | avg | min | max`. `field` required for all but `count`.
- `entity`: optional per-metric override (a dashboard can span tables); defaults to the source's `entity`.
- `window`: optional `today | week | month` → adds a `dateField >= <window start>` filter.
- `dateField`: column the window applies to (default `createdAt`).
- `filter`: optional equality map `{column: value}`.

**Resolver result:** `resolveAggregate(source)` returns a flat object `{ <metricKey>: number }`. `previewData.dashboardStats = { todayCount: 3, monthlyRevenue: 1280, … }`.

**The floor is the safety net, the agent is the brain.** The agent emits semantically correct specs (it knows `monthlyRevenue = sum Invoice.total this month`). The floor guarantees *every* MetricTile binding to an aggregate source resolves to a number — synthesising a safe `count` of the source entity when a metric is missing or invalid. A binding can never be left as literal `{{…}}`.

## File Structure

**Backend (Python):**
- Create `backend/services/aggregate_spec.py` — extract MetricTile→aggregate bindings; synthesise/validate the `metrics` map against the registry. One responsibility: reconcile a page's aggregate sources.
- Create `backend/tests/services/test_aggregate_spec.py`.
- Modify `backend/services/schema_prompt.py` — instruct the agent to emit `metrics` on aggregate sources.
- Modify `backend/routers/generate.py` (~line 2082, the per-page binding loop) — call the floor after `apply_bindings`.

**Runtime (TypeScript, template sources):**
- Modify `backend/templates/runtime/data-engine.ts` — add a real `resolveAggregate(source, ctx)` (Drizzle), replacing reliance on the sketch.
- Modify `backend/templates/app-foundation/src/lib/data-engine-bridge.ts` — keep returning arrays; export a separate `resolveAggregate` passthrough.
- Modify `backend/templates/app-foundation/src/lib/schema-page.tsx` — route `op:"aggregate"` sources to `resolveAggregate` (object), others to `dataEngine.run` (array).
- Modify `packages/renderer/src/runtime/types.ts` (the `DataSource` type) — add optional `op` + `metrics`.

**Tests (TS):**
- Create `backend/templates/runtime/__tests__/resolve-aggregate.test.ts` (or the repo's runtime test location) — resolver unit tests with a fake `db`.

---

## Task 1: Extract MetricTile→aggregate bindings (backend)

**Files:**
- Create: `backend/services/aggregate_spec.py`
- Test: `backend/tests/services/test_aggregate_spec.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_aggregate_spec.py
from services.aggregate_spec import find_aggregate_bindings


def test_finds_metrictile_bindings_to_aggregate_sources():
    page = {
        "dataSources": [
            {"name": "dashboardStats", "entity": "Appointment", "op": "aggregate"},
            {"name": "recent", "entity": "Appointment", "op": "list"},
        ],
        "root": {"children": [
            {"type": "MetricTile", "props": {"value": "{{dashboardStats.todayCount}}"}},
            {"type": "MetricTile", "props": {"value": "{{dashboardStats.monthlyRevenue}}"}},
            {"type": "DataGrid", "props": {"rows": "{{recent}}"}},  # not aggregate
        ]},
    }
    # → {source_name: set(field_names)}
    assert find_aggregate_bindings(page) == {"dashboardStats": {"todayCount", "monthlyRevenue"}}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/services/test_aggregate_spec.py::test_finds_metrictile_bindings_to_aggregate_sources -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.aggregate_spec'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/aggregate_spec.py
"""Reconcile dashboard MetricTile bindings with the metrics computed by an
op:"aggregate" dataSource, so {{dashboardStats.todayCount}} resolves to a real
number instead of rendering the literal template string."""
from __future__ import annotations
import re

_BINDING_RE = re.compile(r"\{\{\s*([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s*\}\}")


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def find_aggregate_bindings(page: dict) -> dict[str, set[str]]:
    """Map each aggregate dataSource name → the set of fields MetricTiles bind to it."""
    agg_names = {
        ds.get("name")
        for ds in (page.get("dataSources") or [])
        if ds.get("op") == "aggregate" and ds.get("name")
    }
    found: dict[str, set[str]] = {}
    for node in _walk(page.get("root") or page):
        if not isinstance(node, dict):
            continue
        for val in (node.get("props") or {}).values():
            if not isinstance(val, str):
                continue
            for src, field in _BINDING_RE.findall(val):
                if src in agg_names:
                    found.setdefault(src, set()).add(field)
    return found
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/services/test_aggregate_spec.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/aggregate_spec.py backend/tests/services/test_aggregate_spec.py
git commit -m "feat(aggregate): extract MetricTile→aggregate bindings from a page schema"
```

---

## Task 2: Synthesise a safe metric from a field name (backend)

**Files:**
- Modify: `backend/services/aggregate_spec.py`
- Test: `backend/tests/services/test_aggregate_spec.py`

- [ ] **Step 1: Write the failing test**

```python
from services.aggregate_spec import synthesise_metric


def test_synthesise_count_default():
    assert synthesise_metric("activeCount", "Pet", {"Pet": {"createdAt"}}) == {"fn": "count", "entity": "Pet"}


def test_synthesise_today_window():
    m = synthesise_metric("todayCount", "Appointment", {"Appointment": {"date", "createdAt"}})
    assert m["fn"] == "count" and m["window"] == "today"


def test_synthesise_sum_revenue_when_field_exists():
    m = synthesise_metric("monthlyRevenue", "Invoice", {"Invoice": {"total", "createdAt"}})
    assert m["fn"] == "sum" and m["field"] == "total" and m["window"] == "month"


def test_synthesise_falls_back_to_count_when_sum_field_absent():
    # "revenue" implies sum, but no total/amount column → safe count, never an uncomputable metric
    m = synthesise_metric("monthlyRevenue", "Invoice", {"Invoice": {"createdAt"}})
    assert m["fn"] == "count"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/services/test_aggregate_spec.py -k synthesise -v`
Expected: FAIL with `ImportError: cannot import name 'synthesise_metric'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/services/aggregate_spec.py
_SUM_FIELDS = ("total", "amount", "price", "revenue", "cost", "value")


def synthesise_metric(field_name: str, entity: str, entity_fields: dict[str, set[str]]) -> dict:
    """Best-effort metric for a binding the agent didn't declare. ALWAYS returns a
    computable metric (worst case: count of the entity), so the binding resolves to a
    number rather than a literal {{…}}."""
    lname = field_name.lower()
    fields = entity_fields.get(entity, set())

    window = None
    if lname.startswith("today") or "today" in lname:
        window = "today"
    elif lname.startswith("week") or "weekly" in lname or "thisweek" in lname:
        window = "week"
    elif lname.startswith("month") or "monthly" in lname or "thismonth" in lname:
        window = "month"

    metric: dict = {"fn": "count", "entity": entity}

    wants_sum = any(tok in lname for tok in ("revenue", "total", "amount", "sum", "sales"))
    wants_avg = "avg" in lname or "average" in lname or "mean" in lname
    if wants_sum or wants_avg:
        sum_field = next((f for f in _SUM_FIELDS if f in fields), None)
        if sum_field:
            metric["fn"] = "avg" if wants_avg else "sum"
            metric["field"] = sum_field
        # else: keep count — never emit a sum/avg without a real column

    if window:
        metric["window"] = window
        metric["dateField"] = "date" if "date" in fields else "createdAt"
    return metric
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/services/test_aggregate_spec.py -k synthesise -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/aggregate_spec.py backend/tests/services/test_aggregate_spec.py
git commit -m "feat(aggregate): synthesise a safe metric from a field name (count fallback)"
```

---

## Task 3: Reconcile a page's aggregate sources against the registry (backend)

**Files:**
- Modify: `backend/services/aggregate_spec.py`
- Test: `backend/tests/services/test_aggregate_spec.py`

- [ ] **Step 1: Write the failing test**

```python
from services.aggregate_spec import reconcile_aggregate_specs


def _registry():
    return {"entities": {
        "Appointment": {"fields": [{"name": "date"}, {"name": "createdAt"}]},
        "Invoice": {"fields": [{"name": "total"}, {"name": "status"}, {"name": "createdAt"}]},
    }}


def test_fills_missing_metrics_for_every_binding():
    page = {
        "dataSources": [{"name": "dashboardStats", "entity": "Appointment", "op": "aggregate"}],
        "root": {"children": [
            {"type": "MetricTile", "props": {"value": "{{dashboardStats.todayCount}}"}},
            {"type": "MetricTile", "props": {"value": "{{dashboardStats.monthlyRevenue}}"}},
        ]},
    }
    out, report = reconcile_aggregate_specs(page, _registry())
    ds = next(d for d in out["dataSources"] if d["name"] == "dashboardStats")
    assert set(ds["metrics"].keys()) == {"todayCount", "monthlyRevenue"}
    assert ds["metrics"]["todayCount"]["fn"] == "count"
    assert report["synthesised"] == 2


def test_preserves_agent_supplied_metrics_and_validates_field():
    page = {
        "dataSources": [{
            "name": "dashboardStats", "entity": "Appointment", "op": "aggregate",
            "metrics": {
                "monthlyRevenue": {"fn": "sum", "field": "total", "entity": "Invoice", "window": "month"},
                "bogus": {"fn": "sum", "field": "nonexistent", "entity": "Invoice"},  # invalid → demote to count
            },
        }],
        "root": {"children": [
            {"type": "MetricTile", "props": {"value": "{{dashboardStats.monthlyRevenue}}"}},
        ]},
    }
    out, report = reconcile_aggregate_specs(page, _registry())
    metrics = out["dataSources"][0]["metrics"]
    assert metrics["monthlyRevenue"] == {"fn": "sum", "field": "total", "entity": "Invoice", "window": "month"}
    assert metrics["bogus"]["fn"] == "count"  # invalid sum field demoted
    assert report["demoted"] == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/services/test_aggregate_spec.py -k reconcile -v`
Expected: FAIL with `ImportError: cannot import name 'reconcile_aggregate_specs'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/services/aggregate_spec.py
_VALID_FNS = {"count", "sum", "avg", "min", "max"}


def _entity_fields(registry: dict) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for name, ent in (registry.get("entities") or {}).items():
        out[name] = {f.get("name") for f in (ent.get("fields") or []) if f.get("name")}
    return out


def _validate_metric(metric: dict, default_entity: str, fields: dict[str, set[str]]) -> tuple[dict, bool]:
    """Return (clean_metric, demoted). A sum/avg/min/max whose field is absent (or whose
    entity is unknown) is demoted to count so it always computes."""
    m = dict(metric)
    entity = m.get("entity") or default_entity
    m["entity"] = entity
    fn = m.get("fn") if m.get("fn") in _VALID_FNS else "count"
    m["fn"] = fn
    demoted = False
    if fn != "count":
        field = m.get("field")
        if entity not in fields or not field or field not in fields[entity]:
            m = {"fn": "count", "entity": entity}
            for k in ("window", "dateField", "filter"):
                if k in metric:
                    m[k] = metric[k]
            demoted = True
    return m, demoted


def reconcile_aggregate_specs(page: dict, registry: dict) -> tuple[dict, dict]:
    """Ensure every MetricTile binding to an aggregate source has a valid, computable
    metric. Mutates a copy of `page`; returns (page, report)."""
    import copy
    page = copy.deepcopy(page)
    fields = _entity_fields(registry)
    bindings = find_aggregate_bindings(page)
    report = {"synthesised": 0, "demoted": 0}

    for ds in page.get("dataSources") or []:
        if ds.get("op") != "aggregate":
            continue
        name = ds.get("name")
        default_entity = ds.get("entity") or ""
        metrics = dict(ds.get("metrics") or {})

        # Validate / demote agent-supplied metrics.
        for key, metric in list(metrics.items()):
            clean, demoted = _validate_metric(metric or {}, default_entity, fields)
            metrics[key] = clean
            report["demoted"] += int(demoted)

        # Synthesise any field a MetricTile references but the spec lacks.
        for field in bindings.get(name, set()):
            if field not in metrics:
                metrics[field] = synthesise_metric(field, default_entity, fields)
                report["synthesised"] += 1

        ds["metrics"] = metrics
    return page, report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/services/test_aggregate_spec.py -v`
Expected: PASS (all tasks 1-3)

- [ ] **Step 5: Commit**

```bash
git add backend/services/aggregate_spec.py backend/tests/services/test_aggregate_spec.py
git commit -m "feat(aggregate): reconcile page aggregate specs vs registry (synthesise + demote)"
```

---

## Task 4: Wire the floor into the per-page binding loop (backend)

**Files:**
- Modify: `backend/routers/generate.py` (the per-page loop around line 2082)
- Test: `backend/tests/services/test_aggregate_spec.py` (integration-style on a temp file)

- [ ] **Step 1: Write the failing test** (a thin integration helper so the floor is callable on a written file)

```python
# append to test_aggregate_spec.py
import json, tempfile, pathlib
from services.aggregate_spec import reconcile_page_file


def test_reconcile_page_file_rewrites_schema(tmp_path):
    page = {
        "dataSources": [{"name": "dashboardStats", "entity": "Appointment", "op": "aggregate"}],
        "root": {"children": [{"type": "MetricTile", "props": {"value": "{{dashboardStats.todayCount}}"}}]},
    }
    fp = tmp_path / "analytics.json"
    fp.write_text(json.dumps(page))
    registry = {"entities": {"Appointment": {"fields": [{"name": "createdAt"}]}}}
    report = reconcile_page_file(fp, registry)
    out = json.loads(fp.read_text())
    assert out["dataSources"][0]["metrics"]["todayCount"]["fn"] == "count"
    assert report["synthesised"] == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/services/test_aggregate_spec.py -k reconcile_page_file -v`
Expected: FAIL with `ImportError: cannot import name 'reconcile_page_file'`

- [ ] **Step 3a: Add the file helper**

```python
# append to backend/services/aggregate_spec.py
import json as _json
from pathlib import Path


def reconcile_page_file(path: "Path", registry: dict) -> dict:
    """Load a page schema JSON, reconcile its aggregate specs, write it back. Returns the report."""
    try:
        page = _json.loads(Path(path).read_text())
    except Exception:
        return {"synthesised": 0, "demoted": 0, "error": "unreadable"}
    out, report = reconcile_aggregate_specs(page, registry or {})
    if report["synthesised"] or report["demoted"]:
        Path(path).write_text(_json.dumps(out, indent=2))
    return report
```

- [ ] **Step 3b: Call it in the binding loop** — in `backend/routers/generate.py`, immediately after the existing `schema_path.write_text(_json.dumps(bound_schema, indent=2))` (line ~2083):

```python
            # Aggregate-spec floor: ensure MetricTile bindings to op:aggregate sources
            # resolve to real numbers (never literal {{…}}). Idempotent.
            try:
                from services.aggregate_spec import reconcile_page_file
                _agg_report = reconcile_page_file(schema_path, registry)
                if _agg_report.get("synthesised") or _agg_report.get("demoted"):
                    yield sse_event("log", {"text": (
                        f"[Aggregate] {p.get('route')}: "
                        f"{_agg_report['synthesised']} metric(s) synthesised, "
                        f"{_agg_report['demoted']} demoted")})
            except Exception as _agg_err:
                yield sse_event("log", {"text": f"[Aggregate] floor skipped: {_agg_err}"})
```

- [ ] **Step 4: Run test + the full module**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/services/test_aggregate_spec.py -v`
Expected: PASS. Also `python3 -c "import ast; ast.parse(open('routers/generate.py').read())"` → no error.

- [ ] **Step 5: Commit**

```bash
git add backend/services/aggregate_spec.py backend/routers/generate.py backend/tests/services/test_aggregate_spec.py
git commit -m "feat(aggregate): run the aggregate-spec floor in the per-page binding loop"
```

---

## Task 5: Teach the schema agent to emit metrics (backend prompt)

**Files:**
- Modify: `backend/services/schema_prompt.py` (near the existing MetricTile guidance, ~line 114)
- Test: `backend/tests/services/test_schema_prompt_aggregate.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_schema_prompt_aggregate.py
from services.schema_prompt import build_schema_prompt  # adjust to the real builder name if different


def test_prompt_documents_aggregate_metrics():
    # Use whatever minimal args the builder needs; the assertion is on the static guidance text.
    text = build_schema_prompt.__doc__ or ""
    # Fallback: assert the constant is present in the module source.
    import services.schema_prompt as sp, inspect
    src = inspect.getsource(sp)
    assert '"op": "aggregate"' in src
    assert '"metrics"' in src
    assert "monthlyRevenue" in src  # the worked example
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/services/test_schema_prompt_aggregate.py -v`
Expected: FAIL (the guidance text isn't there yet)

- [ ] **Step 3: Add the guidance** — insert into the MetricTile/dataSources section of `schema_prompt.py`:

```
DASHBOARD METRICS — when a page shows KPI MetricTiles, declare ONE aggregate
dataSource and bind each tile to a named metric:

  "dataSources": [
    { "name": "dashboardStats", "entity": "Appointment", "op": "aggregate",
      "metrics": {
        "todayCount":     { "fn": "count", "window": "today", "dateField": "date" },
        "monthlyRevenue": { "fn": "sum", "field": "total", "entity": "Invoice", "window": "month", "dateField": "issuedAt" },
        "pendingCount":   { "fn": "count", "entity": "Invoice", "filter": { "status": "pending" } }
      } }
  ]
  // tiles bind to the metric KEYS:
  { "type": "MetricTile", "props": { "value": "{{dashboardStats.todayCount}}" } }

Rules:
- Every MetricTile value MUST reference a metric KEY that exists in `metrics`.
- `fn`: count | sum | avg | min | max. `field` is REQUIRED for everything but count
  and MUST be a real numeric column on the metric's entity.
- `entity` per-metric is optional (defaults to the source entity) — use it to count a
  related table (e.g. Invoice) from one dashboardStats source.
- `window` (today|week|month) + `dateField` add a time filter. `filter` adds equality
  filters. Omit what you don't need.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/services/test_schema_prompt_aggregate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/schema_prompt.py backend/tests/services/test_schema_prompt_aggregate.py
git commit -m "feat(aggregate): document the metrics spec in the schema-agent prompt"
```

---

## Task 6: Real `resolveAggregate` runtime resolver (TypeScript)

**Files:**
- Modify: `backend/templates/runtime/data-engine.ts` (add `resolveAggregate`; it already imports `count` from `drizzle-orm` and has `getEntity`)
- Test: `backend/templates/runtime/__tests__/resolve-aggregate.test.ts`

- [ ] **Step 1: Write the failing test** (fake `db` that records the built query; assert metric→value mapping + window/filter wiring)

```ts
// backend/templates/runtime/__tests__/resolve-aggregate.test.ts
import { describe, it, expect, vi } from "vitest";
import { __setTestDb, resolveAggregate } from "../data-engine";

function fakeDb(rowByCall: number[]) {
  let call = 0;
  const chain = {
    from: () => chain,
    where: () => chain,
    then: (res: any) => Promise.resolve([{ value: rowByCall[call++] ?? 0 }]).then(res),
  };
  return { select: () => chain };
}

describe("resolveAggregate", () => {
  it("returns one number per metric key", async () => {
    __setTestDb(fakeDb([3, 1280]));
    const out = await resolveAggregate({
      name: "dashboardStats", entity: "Appointment", op: "aggregate",
      metrics: {
        todayCount: { fn: "count", window: "today", dateField: "date" },
        monthlyRevenue: { fn: "sum", field: "total", entity: "Invoice", window: "month" },
      },
    });
    expect(out).toEqual({ todayCount: 3, monthlyRevenue: 1280 });
  });
});
```

> Note: if `data-engine.ts` has no test seam, add a tiny `let _testDb; export function __setTestDb(d){_testDb=d}` and use `(_testDb ?? db)` inside `resolveAggregate` only. Keep it out of production paths.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend/templates/runtime && npx vitest run __tests__/resolve-aggregate.test.ts` (or the repo's configured runner)
Expected: FAIL — `resolveAggregate` not exported.

- [ ] **Step 3: Implement** — add to `data-engine.ts` (mirrors the real `stats()` Drizzle pattern; uses `sum`/`avg`/`min`/`max`/`count` + `gte`/`eq`/`and` from `drizzle-orm`):

```ts
import { count, sum, avg, min, max, eq, gte, and, type SQL } from "drizzle-orm";

type Metric = {
  fn: "count" | "sum" | "avg" | "min" | "max";
  field?: string;
  entity?: string;
  window?: "today" | "week" | "month";
  dateField?: string;
  filter?: Record<string, unknown>;
};
type AggregateSource = { name: string; entity: string; op: "aggregate"; metrics?: Record<string, Metric> };

function windowStart(window?: string): Date | null {
  if (!window) return null;
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  if (window === "today") return d;
  if (window === "week") { d.setDate(d.getDate() - d.getDay()); return d; }
  if (window === "month") { d.setDate(1); return d; }
  return null;
}

async function computeMetric(defaultEntity: string, m: Metric): Promise<number> {
  const entity = getEntity(m.entity || defaultEntity);
  if (!entity) return 0;
  const cols = entity.table as any;
  const agg =
    m.fn === "count" ? count() :
    m.fn === "sum"   ? sum(cols[m.field!]) :
    m.fn === "avg"   ? avg(cols[m.field!]) :
    m.fn === "min"   ? min(cols[m.field!]) :
                       max(cols[m.field!]);

  const conds: SQL[] = [];
  const start = windowStart(m.window);
  const dateCol = cols[m.dateField || "createdAt"];
  if (start && dateCol) conds.push(gte(dateCol, start));
  for (const [k, v] of Object.entries(m.filter || {})) {
    if (cols[k] !== undefined) conds.push(eq(cols[k], v as any));
  }

  let q = (db as any).select({ value: agg }).from(entity.table);
  if (conds.length) q = q.where(conds.length === 1 ? conds[0] : and(...conds));
  const [row] = await q;
  return Number(row?.value ?? 0);
}

/** Resolve an op:"aggregate" dataSource into { metricKey: number }. Each failing
 *  metric degrades to 0 — the page never blanks or shows a literal binding. */
export async function resolveAggregate(source: AggregateSource): Promise<Record<string, number>> {
  const out: Record<string, number> = {};
  const metrics = source.metrics || {};
  await Promise.all(Object.entries(metrics).map(async ([key, m]) => {
    try { out[key] = await computeMetric(source.entity, m); }
    catch { out[key] = 0; }
  }));
  return out;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend/templates/runtime && npx vitest run __tests__/resolve-aggregate.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/templates/runtime/data-engine.ts backend/templates/runtime/__tests__/resolve-aggregate.test.ts
git commit -m "feat(aggregate): real Drizzle resolveAggregate runtime resolver"
```

---

## Task 7: Route op:aggregate through the bridge + renderSchemaPage (TypeScript)

**Files:**
- Modify: `backend/templates/app-foundation/src/lib/data-engine-bridge.ts` (re-export a `resolveAggregate` passthrough)
- Modify: `backend/templates/app-foundation/src/lib/schema-page.tsx` (branch on `op`)

- [ ] **Step 1** (no separate unit test — this is template glue verified by the e2e in Task 9). Add to `data-engine-bridge.ts` after the `dataEngine` export:

```ts
import { resolveAggregate as _resolveAggregate } from "./data-engine";

/** Resolve an op:"aggregate" dataSource to a flat { metricKey: number } object. */
export async function resolveAggregate(source: unknown): Promise<Record<string, number>> {
  try {
    return await _resolveAggregate(source as any);
  } catch (err) {
    console.warn(`[data-engine-bridge] aggregate run failed:`, err);
    return {};
  }
}
```

- [ ] **Step 2** Modify the resolution loop in `schema-page.tsx` (replace lines 32-39):

```tsx
  import { dataEngine, resolveAggregate } from "./data-engine-bridge";
  // …
  const previewData: Record<string, unknown> = {};
  for (const s of ((page as any).dataSources ?? []) as Array<{ name: string; op?: string }>) {
    try {
      previewData[s.name] = s.op === "aggregate"
        ? await resolveAggregate(s as any)            // → { todayCount: 3, … }
        : await dataEngine.run(s as any, { request, user });  // → array
    } catch (e) {
      console.warn(`[schema-page] dataSource '${s.name}' failed to resolve:`, e);
    }
  }
```

- [ ] **Step 3: Verify it parses** — `cd backend/templates/app-foundation && npx tsc --noEmit src/lib/schema-page.tsx` (or rely on the app build in Task 9).

- [ ] **Step 4: Commit**

```bash
git add backend/templates/app-foundation/src/lib/data-engine-bridge.ts backend/templates/app-foundation/src/lib/schema-page.tsx
git commit -m "feat(aggregate): route op:aggregate sources to resolveAggregate (object previewData)"
```

---

## Task 8: Extend the renderer DataSource type (TypeScript)

**Files:**
- Modify: `packages/renderer/src/runtime/types.ts` (the `DataSource` type — locate with `grep -n "DataSource" packages/renderer/src/runtime/types.ts`)

- [ ] **Step 1** Add optional fields so schemas with `op`/`metrics` typecheck:

```ts
export interface DataSource {
  name: string;
  entity?: string;
  op?: "list" | "detail" | "aggregate";
  metrics?: Record<string, {
    fn: "count" | "sum" | "avg" | "min" | "max";
    field?: string;
    entity?: string;
    window?: "today" | "week" | "month";
    dateField?: string;
    filter?: Record<string, unknown>;
  }>;
  query?: Record<string, unknown>;
}
```

- [ ] **Step 2: Rebuild + re-vendor the renderer dist** (the generated apps consume the vendored dist):

```bash
cd packages/renderer && npm run build
# re-vendor into the running app for the e2e
cp -R packages/renderer/dist/* output/4sashx7f/vendor/@tentoroforge/renderer/dist/  # adjust path
```

- [ ] **Step 3: Commit**

```bash
git add packages/renderer/src/runtime/types.ts packages/renderer/dist
git commit -m "feat(aggregate): DataSource type accepts op + metrics"
```

---

## Task 9: End-to-end verification on `4sashx7f`

**Files:** none (verification). The app `output/4sashx7f` is a complete, seeded, running app.

- [ ] **Step 1: Apply the floor to the existing analytics page** (the run that produced it predates this feature):

```bash
cd backend && /usr/local/bin/python3 -c "
import sys, json; sys.path.insert(0,'.')
from services.aggregate_spec import reconcile_page_file
reg = json.load(open('../output/4sashx7f/registry.json'))
print(reconcile_page_file('../output/4sashx7f/src/schemas/analytics.json', reg))
"
```
Expected: a report with `synthesised >= 4` (todayCount, overdueVaccineCount, pendingInvoiceCount, monthlyRevenue), and `analytics.json` now has a `metrics` map on `dashboardStats`.

- [ ] **Step 2: Copy the updated runtime files into the app** (it has vendored/templated copies):

```bash
cp backend/templates/runtime/data-engine.ts output/4sashx7f/src/lib/data-engine.ts        # verify import paths first
cp backend/templates/app-foundation/src/lib/data-engine-bridge.ts output/4sashx7f/src/lib/
cp backend/templates/app-foundation/src/lib/schema-page.tsx output/4sashx7f/src/lib/
```

- [ ] **Step 3: Seed a few rows + restart, then load `/analytics`**. Verify in the browser (or via `curl localhost:3001/analytics | grep -c '{{'`):
  - No `{{dashboardStats.…}}` literals remain (grep returns 0).
  - MetricTiles show numbers (0 on an empty table, real counts after seeding).

- [ ] **Step 4: Run the full backend test suite** to confirm nothing regressed:

```bash
cd backend && /usr/local/bin/python3 -m pytest tests/services/test_aggregate_spec.py tests/services/test_schema_prompt_aggregate.py -v
```
Expected: all PASS.

- [ ] **Step 5: Final commit (vendored app changes are not committed; only template/source). Then finish the branch.**

Use **superpowers:finishing-a-development-branch**.

---

## Self-Review (completed)

**Spec coverage:** binding extraction (T1) → safe synthesis (T2) → registry-validated reconcile + demote (T3) → pipeline wiring (T4) → agent prompt (T5) → real runtime resolver (T6) → bridge/render routing (T7) → renderer type (T8) → e2e (T9). The two root causes (no spec; bridge returns array) are addressed by T3+T5 and T6+T7 respectively. The "literal {{…}}" symptom is eliminated because T3's floor guarantees a computable metric for every binding and T6 degrades failures to 0.

**Placeholder scan:** every code step has concrete code. The one adaptation note (test seam `__setTestDb` in T6, vendor path in T8/T9) is flagged explicitly because the exact path depends on the repo's runtime test setup — the implementer confirms with `grep` first.

**Type consistency:** the metric shape `{fn, field?, entity?, window?, dateField?, filter?}` is identical across the Python synthesiser (T2/T3), the prompt example (T5), the TS `Metric` type (T6), and the renderer `DataSource.metrics` (T8). `resolveAggregate(source) → Record<string, number>` matches between T6 (definition), T7 (bridge passthrough + render call), and the T6 test.

## Out of scope
- Live (client-side) re-fetch of aggregates after mutations — `previewData` is SSR-initial; the Engine's existing client refetch path is unchanged.
- Grouped aggregates / charts driven by `groupBy` (the resolver computes scalar metrics; chart series still come from list sources).
- Caching/memoising aggregate queries.

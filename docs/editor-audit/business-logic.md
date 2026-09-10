# TentoroForge — Business Logic & Runtime Audit

Target project: Inventory Manager — `output/gh0mlpbp` (short id `gh0mlpbp`, project id `ad503658-18d3-42ac-bf3e-329c077ec17f`)
Branch: `smithv2`. Audit date: 2026-09-05.

Scope: the gap between what the editor lets a user author and what actually executes at runtime.

## Summary

| # | Area | Finding | Status |
|---|------|---------|--------|
| _(appended below as work proceeds)_ | | | |

---

## Findings

### A2UI → Forge translation — `KeyValueList.items` (and 40+ other literal-array props) is silently dropped, refusing every record/detail page — BUG (P0)

**Confirmed by reproduction against the real payload.**

`backend/services/a2ui_to_forge.py:66`
```python
_DATA_PROPS = frozenset({"data", "rows", "items", "series", "columns", "value", "entries"})
```
`backend/services/a2ui_to_forge.py:86`
```python
_CONFIG_DATA_PROPS = frozenset({"columns", "series"})
```
`backend/services/a2ui_to_forge.py:1288-1305`
```python
if k in _DATA_PROPS:
    if not isinstance(val, dict) and k not in _CONFIG_DATA_PROPS:
        if k == "value" and isinstance(val, (int, float)) and not isinstance(val, bool):
            ...                      # only numeric `value` is rescued
        binder.warnings.append(
            f'{c.get("id")}.{k}: dropped a literal on a data prop '
            f"— rows the page did not read from anywhere.")
        continue                     # <-- prop never reaches props{}
```
The rule assumes every `_DATA_PROPS` value arrives as an A2UI pointer `{"path": "/x/y"}`. For `KeyValueList` that is false **by contract**: `packages/registry/dist/component-contracts.json` types it

```json
"KeyValueList": { "items": { "type": "array" } }
```

so the composer correctly emits a literal array of `{label, value:{path:…}}` rows — the *pointers are one level down, inside the array*. `isinstance(val, dict)` is False, `items` is not in `_CONFIG_DATA_PROPS`, so the whole prop is discarded.

**Reproduction** (real payload, not synthetic): `output/gh0mlpbp/src/contracts/a2ui-surfaces/items-id.1.json`, node `metaList`, run through `translate()` with the project's own registry:

```
== WARNINGS ==
  - metaList.items: dropped a literal on a data prop - rows the page did not read from anywhere.
  - deleteButton.args.itemId: "/item/id" resolves to no source on this page - dropped ...
== resulting node ==
{ "type": "KeyValueList", "props": {}, "id": "metaList" }
```
and in the emitted tree it lands at exactly `root.children[1]`:
```
"children": [ {...statsCluster...}, { "type": "KeyValueList", "props": {}, "id": "metaList" }, {...actionsRow...} ]
```
which is verbatim the refusal seen twice in the logs:
`InvalidPatternTemplate: PAGE-003: root.children[1].props.(root): 'items' is a required property`.

The earlier synthetic repro failed because a hand-made node loses the surrounding `createSurface`/`updateDataModel` messages and the node is discarded earlier; the rule is only reached from a complete surface.

**Blast radius — 43 catalog components carry a `_DATA_PROPS`-named prop that is not `columns`/`series`:**
`KeyValueList.items(array)`, `Breadcrumb.items(array)`, `DescriptionList.items(array)`, `List.items(array)`, `Tree.items(array)`, `Carousel.items(array)`, `DropdownMenu.items(array)`, `ContextMenu.items(array)`, `MobileNav.items(array)`, `CommandPalette.items(array)`, `ValidationChecklist.items(array)`, `Timeline.entries`, `ActivityFeed.entries`, `Sparkline.data`, `Heatmap.rows`, `EditableLineGrid.rows`, `RecsRailReasoned/CommunityPulse/ReasonsToReturnRow/TrendingRail/TasteRecsRail/AttentionQueueHero/PrioritiesStrip/EscalationsQueue/RecognitionFeed.items`, plus every **string-valued** `value` prop: `Tabs.value`, `TabPanel.value`, `AccordionPanel.value`, `Calendar.value`, `QRCode.value`, `Scanner.value`, `Stat.value`, `RichTextEditor.value` (the `k == "value"` rescue at :1293 only covers `int`/`float`, so a literal string `value` — e.g. `Tabs.value: "overview"` naming the default tab — is dropped too).

**Impact:** every generated app that composes a record/detail page with a `KeyValueList` (the canonical detail-page component) is refused. `PAGE-003` `/items/[id]` in `gh0mlpbp` has no composed layout and 404s as a direct result. Nav/menu components (`Breadcrumb`, `DropdownMenu`, `ContextMenu`, `MobileNav`) are equally exposed.

**One-line fix candidate:** add the literal-array display props to `_CONFIG_DATA_PROPS`, or better, change the guard at :1289 to allow a `list` whose elements contain `{"path": …}` pointers and recurse into it.

---

### A2UI retry loop — the refusal feedback is fed to the wrong layer, so the retry is guaranteed to fail identically — BUG (P1)

`backend/services/a2ui_authority.py:621-631` threads the validator's message back into the composer's DOMAIN CONTEXT:
```
"\nWHAT WAS WRONG WITH YOUR LAST ATTEMPT AT THIS SCREEN. It was composed and then refused for this:\n\n" + feedback.strip()
```
and the code comment at `a2ui_authority.py:610` names this exact failure:
> "a composition refused for `'items' is a required property` was recomposed by a composer with no idea it had been refused"

But the composer's payload was **already correct** — `items` was present and well-formed. The prop is destroyed *downstream*, in `translate()`. So the loop tells the LLM composer "you omitted `items`" when it did not; the composer re-emits `items`; `translate` drops it again. Both PAGE-003 attempts (`items-id.1.json`, `items-id.2.json`) contain a valid `KeyValueList.items`.

**Impact:** a self-correction mechanism that burns LLM retries and can never converge, and misattributes a deterministic translator bug to the model. Any refusal originating in `translate`'s drop rules has this property.

---

### Registry — `KeyValueList.items` is declared `type: "action"` with an `actionPicker` control — BUG (P2)

`packages/registry/src/starter.ts:2296-2310`
```ts
export const keyValueListEntry: RegistryEntry = {
  name: "KeyValueList", ...
  props: {
    items: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { label, value, copyable? } item objects.",
    },
  },
};
```
The description says "Array of `{label, value, copyable?}` objects" and `component-contracts.json` types it `{"type":"array"}`, but the editor-facing registry types it as an **action** and renders an **action picker**. A user opening the properties panel for a KeyValueList is offered a workflow/action chooser for what is a data array, and cannot author the rows at all.

**Impact:** the single most common detail-page component cannot be authored in the editor, independently of the translation bug above.

---

### Bindings runtime — unresolved `{{...}}` bindings render as literal text to the end user — BUG (P0, live-confirmed)

Live against the running scaffold (port 6503, basePath `/p`):

```
$ curl -s http://localhost:6503/p/gh0mlpbp/items | grep -o '...metrics.list_total_inventory_value...'
muted-foreground">Total Inventory Value</span><div class="flex items-baseline gap-2">
<span class="text-2xl font-semibold text-foreground">{{metrics.list_total_inventory_value}}</span></div>
```

Three such bindings ship to the DOM: `{{metrics.list_total_inventory_value}}`, `{{metrics.list_low_stock_items}}`, `{{metrics.list_items}}`. There is no empty state, no em-dash, no visible error — the raw mustache IS the KPI value the operator reads.

`output/gh0mlpbp/src/schemas/PAGE-001.json`, `root.children[0].children[1].children[0..2]`:

```json
{"type":"Stat","id":"n-0-1-0","props":{"label":"Total Inventory Value","trend":"neutral","value":"{{metrics.list_total_inventory_value}}"}}
```

---

### Aggregates — the `metrics.*` binding namespace and the `dataSources` namespace are generated independently and never agree — BUG (P0)

The page **does** declare working aggregate dataSources (`output/gh0mlpbp/src/schemas/PAGE-001.json`):

```json
"dataSources": [
  {"name":"items","entity":"Item","op":"list","limit":500,"orderBy":{"createdAt":"desc"}},
  {"name":"totalInventoryValue","entity":"Item","op":"aggregate",
   "metrics":{"itemCount":{"expression":"count(id)","format":"number"},
              "totalValue":{"expression":"sum(quantity * price)","format":"currency"}}},
  {"name":"lowStockCount","entity":"Item","op":"aggregate","filter":{"quantity":{"lt":5}},
   "metrics":{"lowStockCount":{"expression":"count(id)","format":"number"}}}
]
```

So the aggregates are NOT absent — they are correct and executable. What is absent is any dataSource named **`metrics`**. The bindings reference `{{metrics.<key>}}`; the sources publish `totalInventoryValue` / `lowStockCount`.

Where `metrics.<key>` comes from — `backend/services/blueprint/page_planner.py:340` and `:346-350`:

```python
"value": f"{{{{metrics.{_metric_key(w)}}}}}",
...
def _metric_key(widget: dict) -> str:
    src = widget.get("dataSource") or {}
    parts = [str(src.get("op") or "value"), str(src.get("aggregation") or "")]
    label = re.sub(r"[^a-zA-Z0-9]+", "_", (widget.get("label") or "")).strip("_")
    return "_".join(p for p in parts + [label.lower()] if p)
```

The key is `<op>_<aggregation>_<label_snake>` — derived from the widget's **display label**. "Total Inventory Value" with `op:"list"` becomes `list_total_inventory_value`, which names nothing in the data layer and changes if anyone renames the tile.

The planner's own dataSource emitter (`page_planner.py:850-853`) would emit a matching source:

```python
if name == "metrics":
    out.append({"name": name, "entity": target.get("name"), "op": "aggregate"})
```

— but with **no `metrics` map**, i.e. no expressions at all, so even on that path every key resolves to undefined. In this project it never ran; the page's dataSources came from a different generator.

`backend/services/blueprint/functional_completeness.py:53-68` then whitelists the name so no gate complains:

```python
def _planner_placeholders() -> set[str]:
    from services.blueprint.page_planner import RECORD, ROWS
    return {ROWS, RECORD, "metrics"}
```

`metrics` is subtracted from the dangling-binding set, so the page passes the functional-completeness gate while rendering mustaches to the user.

`backend/services/aggregate_metrics_guard.py` is the guard written for exactly this failure ("aggregate declared but metrics keys omitted", per its own docstring) — but it iterates over existing `op:"aggregate"` dataSources and injects into `S.metrics` for each `{{S.key}}`. With `S == "metrics"` and no dataSource of that name, it can never fire.

**Impact:** every widget/KPI authored through the planner path renders its binding expression as literal text; the gate that exists to catch dangling bindings is explicitly configured to ignore this exact family; and the guard built to repair it cannot reach it.

---

### MCP — `getattr(result, "isError", False)` swallows every tool error under mcp 2.0 — BUG (P1, confirmed)

Version and attribute name verified in this environment:

```
$ python -c "import importlib.metadata as m; print(m.version('mcp'))"
2.0.0
CallToolResult fields: ['meta', 'content', 'structured_content', 'is_error', 'result_type']
   is_error   alias= isError
>>> r = CallToolResult(content=[], isError=True)
>>> getattr(r, "isError",  "MISSING")   ->  MISSING
>>> getattr(r, "is_error", "MISSING")   ->  True
```

`isError` is only a **serialisation alias**; the Python attribute is `is_error`. `getattr(..., "isError", False)` therefore always returns the default `False` — it does not even raise.

Broken call sites (each silently treats every error result as a success):

- `backend/services/mcp_client.py:245` — `"isError": bool(getattr(result, "isError", False))`. This is the generic platform-MCP tool-call path; the contract documented one line above at `:228` is `{content: [...], isError: bool}`. Every registered MCP server's tool errors are handed to the caller and the UI as `isError: false`, with the error text sitting in `content` where it will be parsed as a result.
- `backend/services/figma/gateway.py:233` — `if getattr(result, "isError", False): raise FigmaGatewayError("tool_error", ...)`. Never raises; a Figma tool error falls through to `_blocks_of(result)` and is parsed as if it were design data.
- `backend/agents/figma_mcp_agent.py:176` — same pattern; the `"[figma_mcp] tool returned isError"` warning at `:178` is unreachable.

**Already fixed in exactly one place, which independently corroborates the diagnosis** — `backend/services/a2ui_authority.py:733-742`:

```python
# `isError` ON THE WIRE, `is_error` ON THE OBJECT. mcp 2.0 renamed the field
# and kept the camelCase only as a serialisation alias, so reading
# `out.isError` raises AttributeError ... and hid the server's actual
# complaint through three retries.
if getattr(out, "is_error", None) or getattr(out, "isError", False):
```

The same one-line `is_error`-first guard has not been applied to the three sites above.

**Impact:** MCP failures are invisible platform-wide. A Figma import that failed server-side is consumed as valid design data; the platform-MCP test/call UI reports success on a failed tool call.

---

### Theme tokens — `brief_loop_cascade` writes to a path nothing reads — BUG (P2, confirmed)

`backend/services/brief_loop_cascade.py:93`

```python
tokens_path = out_dir / "src" / "app" / "tokens.custom.json"
```

Every other writer and every reader in the platform uses `src/theme/tokens.custom.json`:

- writers: `backend/routers/generate.py:2290, 2311, 4221, 4502`; `backend/routers/output_projects.py:220, 231`; `backend/routers/_debug_schema.py:132`
- readers: `apps/render-scaffold/src/lib/loadTokens.ts:14`; `apps/render-scaffold/src/app/[projectId]/[...slug]/page.tsx:71`; `backend/agents/feature_slice_schema_agent.py:282`

`output/gh0mlpbp/` has `src/theme/tokens.custom.json` (313 bytes, user-edited) and **no** `src/app/tokens.custom.json`. `brief_loop_cascade` is the sole outlier, and it returns `{"recompiled": True, "tokens_path": ...}` — reporting success for a write nothing will ever read.

**Impact:** the brief-to-design cascade appears to apply a theme and applies nothing.

---

### Theme tokens — the BUILT app reads a fourth path that is never populated, so editor theme edits never ship — BUG (P1, confirmed)

`output/gh0mlpbp/app/src/theme/load-custom.ts`:

```ts
const p = path.resolve(process.cwd(), "src/theme/tokens.custom.json");
try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch { return null; }
```

The generated Next app's cwd is `output/<id>/app/`, so this resolves to `output/gh0mlpbp/app/src/theme/tokens.custom.json` — confirmed ENOENT. The editor's tokens live one directory up at `output/gh0mlpbp/src/theme/tokens.custom.json` and contain real user edits:

```json
{"color":{"primary":{"50":"#c0c8d3"},"success":{"50":"#a9f9c1"}},
 "radius":{"scale":"soft"},"density":"comfortable","elevation":"layered"}
```

The ENOENT is swallowed by the bare `catch`, and `tokens.server.ts` then merges `defaultTokens` with `null`.

The render **preview** does read the correct file (`loadTokens.ts` is handed the project root, not the app root), so **preview and production disagree on the theme** and neither side reports it. Four distinct token paths are in play: `src/theme/` (editor + preview), `src/app/` (brief cascade — dead), `app/src/theme/` (built app — never populated), `app/src/app/tokens.css` (compiled CSS).

---

### Persistence divergence — the editor and the build write different files with different names, and the user's edits reach neither preview nor production — BUG (P0, live-confirmed)

Two schema roots, two naming conventions, both live:

| | editor | build (Blueprint projection) |
|---|---|---|
| root | `output/gh0mlpbp/src/schemas/` | `output/gh0mlpbp/app/src/schemas/` |
| name | page id — `PAGE-001.json` | route slug — `items.json`, `items/new.json`, `items/[id]/edit.json` |
| mtime | 15:15 (user edit) | 14:03 (last build) |

`apps/render-scaffold/src/lib/loadSchema.ts:17-25` searches both roots, `app/` first, and its own comment names the problem:

```ts
// TWO WRITERS, TWO ROOTS. The Blueprint projection writes
// `output/<id>/app/src/schemas/`; the editor writes `output/<id>/src/schemas/`.
// Resolving a single root per project makes one writer's pages invisible ...
// `app` is tried first: it is the built artifact the app actually ships
```

But the lookup key is the **route path** (`items`), so it can only ever match the build's route-slug filenames. The editor's `PAGE-001.json` is unreachable by construction — the dual-root search does not rescue it, because the two writers do not merely use two roots, they use two *names*.

Proof, a real user edit on `/items` — `diff src/schemas/PAGE-001.json app/src/schemas/items.json`:

```diff
-          "style": { "background": "#ffffff" },            (on a Text node)
-          "style": { "background": "#f41010",              (on the Table)
-                     "motion": "fade-up",
-                     "motionDuration": "5s" },
```

The editor copy carries these; the built copy does not. And live:

```
$ curl -s http://localhost:6503/p/gh0mlpbp/items | grep -c f41010
0
```

The user's red table background and fade-up motion are absent from the preview as well as from the build. The editor edit is written to disk, is never read by anything, and nothing tells the user.

**Which copy ships:** `output/gh0mlpbp/app/src/schemas/registry.ts` is the built app's route table, and it imports only from `./items.json`, `./items/new.json`, `./items/[id]/edit.json` — i.e. only the `app/` copy. The `src/schemas/` copy has no path into the shipped bundle at all.

**What happens to an editor edit at build time:** it is neither merged nor overwritten — it is simply orphaned in a directory the build does not read and the route resolver cannot name.

---

### Routing — PAGE-003 `/items/[id]` is absent from the generated route registry, so it 404s — BUG (P0, live-confirmed)

`output/gh0mlpbp/app/src/schemas/registry.ts`:

```ts
export const schemas: Record<string, () => Promise<unknown>> = {
  "/items": () => import("./items.json"),
  "/items/new": () => import("./items/new.json"),
  "/items/[id]/edit": () => import("./items/[id]/edit.json"),
};
export async function getSchema(route: string) {
  const loader = schemas[route];
  if (!loader) throw new Error(`unknown route '${route}'`);
```

`/items/[id]` is missing. `output/gh0mlpbp/app/src/schemas/items/[id]/` contains only `edit.json`. Live:

```
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:6503/p/gh0mlpbp/items/itm-1
404
```

This is the downstream consequence of the `KeyValueList.items` drop above: the composition was refused, so no layout was written, so no route entry was emitted. The Blueprint still lists PAGE-003 and the Edit button on the item row still navigates there. **A user who clicks through from the list lands on a 404 in the shipped app**, and nothing between the refusal and the deploy re-raises it.

---

### Rules — a short_id is passed where a project UUID is required, so DB-backed rules load for NO Blueprint project — BUG (P0, confirmed)

Call site found: `backend/services/blueprint/assembly.py:289-297`

```python
application = doc.get("application") or {}
return inject_runtime(
    str(app_root),
    preserve=PROJECTED_PATHS,
    app_name=application.get("name"),
    domain=application.get("domain"),
    project_id=application.get("id"),      # <-- the Blueprint's own id
)
```

The Blueprint's `application.id` is the **short id**, verified directly:

```
$ python -c "import json;b=json.load(open('output/gh0mlpbp/.forge/blueprint/current.json'));print(repr(b['application']['id']))"
'gh0mlpbp'
```

`inject_runtime`'s own docstring at `backend/services/runtime_injector.py:219` states the contract it violates: *"project_id: UUID of THIS project row"*.

That value reaches `runtime_injector.py:2722-2725`:

```python
"SELECT id, name, rule_type, model_name, field_name, config, is_active "
"FROM project_rules WHERE project_id = %s AND is_active = true",
(project_id,),
```

Postgres rejects `'gh0mlpbp'` against the uuid column, and the fallback at `runtime_injector.py:2836-2847` swallows it — this is the log line in the mission brief:

```python
if project_id:
    try:
        db_rules = _fetch_project_rules_sync(project_id)
        ...
    except Exception as exc:  # noqa: BLE001 — never break generation over rules
        logger.warning("[rules] DB rule export failed, using registry: %s", exc)
```

**Does it work for ANY project?** Yes for the classic pipelines, which pass a real UUID: `backend/routers/generate.py:2546` and `:4708` (`str(project_id)`), `backend/services/pipeline_graph.py:842` (`str(project_uuid)`), `backend/services/ir_pipeline.py:389`. So the answer is split: **the entire Blueprint pipeline is unconditionally on the registry fallback; the classic pipeline is not.** (`pipeline_graph.py:892` passes a bare `uuid.UUID` object rather than `str`, which psycopg2 needs `register_uuid()` for — that re-injection path is also suspect.)

**Second, independent instance** — `backend/routers/_debug_schema.py:114-123`: the `regen-rules` endpoint resolves the correct UUID from the DB (`select(Project.id).where(Project.short_id == short_id)`), passes it to `run_rules_agent(..., project_id=project_id)`, and then calls the exporter **without it**:

```python
rules = await run_rules_agent(str(output_dir), plan, project_id=project_id)
_export_rules_to_filesystem(output_dir)     # project_id dropped
```

**Why the file ends up `[]` rather than partial:** with the DB path dead, the fallback reads `output_path/registry.json` (`runtime_injector.py:2829-2836`). Neither `output/gh0mlpbp/registry.json` nor `output/gh0mlpbp/app/registry.json` exists, so `rules` stays `[]`.

---

### Rules — `app/rules/index.json` IS wired at runtime; it is simply always empty — GAP (P0)

Contrary to the "dead output" hypothesis, the wiring is live and correct. `output/gh0mlpbp/app/rules/index.json` is read by `output/gh0mlpbp/app/src/lib/rules/engine.ts:59-101` (`loadRules`), which probes `process.cwd()/rules` then `process.cwd()/src/rules` (`:72`). Consumers in the generated app:

- `src/lib/runtime-loader.ts:9,37`
- `src/app/api/form-rules/route.ts:17`
- `src/lib/data-engine.ts:335, 745, 813, 896, 970`
- `src/lib/workflows/index.ts:1001, 1040`

Writer: `backend/services/runtime_injector.py:2816` (`_export_rules_to_filesystem`), which writes both `<app>/rules/index.json` and `<app>/src/rules/index.json` (`:2847-2860`) — the second copy exists so the rules survive Next's serverless output-file tracing.

Both files in this project are 2 bytes: `[]`.

**Impact:** the plumbing is sound end to end, so every validation rule, row-access rule, computed field and condition-action the user authors is a silent no-op in the generated app — not because nothing reads them, but because the export upstream always produces an empty list (previous finding).

---

### Rules / Decisions — a full authoring UI writes rules the export cannot read, and decision tables nothing exports at all — BUG (P0)

There **is** a complete rule- and decision-authoring UI, mounted from `frontend/src/app/org/[orgId]/projects/[projectId]/page.tsx:40`:

- `frontend/src/components/business-rules/BusinessRulesPanel.tsx:74,108,110,124` — GET/PUT/POST/DELETE `/api/projects/${projectId}/rules`
- `frontend/src/components/rules/RulesPanel.tsx:89`, `RuleFormDialog.tsx:133,135,149`, `RecordScopeEditor.tsx:99,142`
- `frontend/src/components/rules/AppAccessPolicies.tsx:50,98,117` — `/access-policies`
- `frontend/src/components/rules/FieldAccessMatrix.tsx:70,120` — `/field-access`
- backed by `backend/routers/rules.py:70,131,216,249`

Decision tables: `frontend/src/components/decision/` (`DecisionTableEditor`, `DecisionTestPanel`, `DecisionVersionPanel`, `DRDCanvas`) against `backend/routers/decisions.py:35,55,117,193`, typed `project_id: uuid.UUID`.

Two independent breaks between authoring and execution:

1. The editor route supplies a **UUID**, so authoring and storage work. The filesystem export reads that same `project_rules` table with a **short_id** (previous finding), so nothing authored ever reaches the app.
2. There is **no bridge at all** from the `DecisionTable` model into `project_rules` or the filesystem export — `grep DecisionTable backend/services/` returns nothing. Only the `rule_type == "decision_table"` variant that happens to be stored inside `project_rules` (`runtime_injector.py:2753`, `rules.py:57`) could ever ship. A decision table authored in the DRD canvas is stored, versioned, testable in the UI, and unreachable by the generated app.

**Impact:** the platform's headline "business rules / decisions" surface is authoring-only. Users can build and test logic that provably never executes.

---

### Preview data — no database is ever consulted; every number in both previews is invented — GAP (P1)

Handler: `backend/routers/_debug_schema.py:421-789` (`get_preview_data(short_id)`). It returns fixture rows keyed by entity name plus aliases (`Item` / `item` / `items`, `:637-642`), a synthesised `stats` object, per-entity `<entity>Stats`, `currentUser`/`user` and `overview`.

Provenance is a four-layer cascade — `backend/services/fixtures/dispatcher.py:66-105` (`provide_records_async`):
1. hand-curated bank `backend/fixtures/<domain>/<entity>.json`
2. cache `output/<short_id>/.fixtures-cache/<entity>.json`
3. a live Sonnet call (`backend/services/fixtures/llm_gen.py`), written back to that cache
4. Faker (`backend/services/fixtures/faker_gen.py`), then empty dicts

On top of that, much of `stats` is `random.Random(short_id)` invention — `_debug_schema.py:697-737` fabricates `*Delta`, `*Trend`, `overdueCount`, `dueTodayCount`, `growthRate`, `monthlyCount`.

For `gh0mlpbp` specifically: `output/gh0mlpbp/.fixtures-cache/Item.json` holds 2.6 KB of LLM-invented rows ("Wireless Bluetooth Headphones", "Ergonomic Office Chair") — the only entity cached. `output/gh0mlpbp/app/src/db/seed.json` holds three placeholders (`Item 1 / Category 1 / 100`) and is not used by the preview path at all.

**Path bug in the same handler:** `_debug_schema.py:425-426` hardcodes `proj = output/<short_id>` (flat layout), so it probes `output/gh0mlpbp/src/db/schema/*.ts` (`:541-542`, does not exist) and enum-enriches against `output/gh0mlpbp/src/schemas` (`:650`) — which currently holds ~100 unrelated `probe_*.json` test fixtures. The real app is at `output/gh0mlpbp/app/src/{db/schema,schemas}`. The scaffold's own `resolveProject.ts:29` correctly probes for the nested `app/` layout; the backend endpoint has no equivalent, so schema-derived field hints and enum enrichment silently no-op for every Blueprint-layout project.

---

### Preview data — the editor canvas and the render preview use the SAME endpoint and TWO different resolvers, producing different numbers — BUG (P1)

Same source. Canvas: `frontend/src/components/canvas/hooks/useArtifacts.ts:92-99` fetches `${API}/api/_debug/preview-data/${projectId}`. Scaffold: `apps/render-scaffold/src/app/[projectId]/[...slug]/page.tsx:26-37` (`loadPreviewData`), called at `:274`, passed at `:308` → `ShellWrapper.tsx:58,71` → `SchemaRendererWrapper.tsx:72` (`resolvePreviewSync`) → `<Engine previewData={...}>` at `:102`.

The divergence is downstream — two resolvers with no shared code:

| behaviour | scaffold `apps/render-scaffold/src/lib/resolvePreviewSync.ts` | canvas `frontend/src/lib/preview-resolve.ts` |
|---|---|---|
| base object | `const resolved = {}` (`:24`) — entity keys and `stats` are **dropped** | `const out = { ...pd }` (`:138`) — they **survive** |
| `op:"aggregate"` | reads the endpoint's **pre-baked** `<entity>Stats` / `stats` blob (`:35-42`) | **recomputes** from `s.metrics` over the rows, honouring per-metric `filter` (`:81-88`, `:143-144`) |
| `op:"series"` | **no branch** — falls through to the list branch (`:62-74`), returns raw rows | `resolveSeries` returns `[{label,value}]` with day/week/month bucketing (`:106-126`, `:145-146`) |
| entity aliasing | literal candidate list + `PERSON_ALIASES` (Employee/Author/Manager → User) (`:48-61`) | punctuation-stripping `norm()` match, **no** person aliases (`:42-56`) |
| FK lifting | lifts joined sub-objects to top level on `op:"get"` (`:82-91`) | none |
| empty input | returns `{}` (`:19`) | returns `pd` unchanged (`:137`) |

Concrete consequences on the same page with byte-identical fixture JSON: `{{stats.totalCount}}` resolves on the canvas and renders as a literal mustache in the scaffold; a chart bound to a `series` source gets `[{label,value}]` on the canvas and a raw row array in the scaffold; a KPI whose metric carries a `filter` shows the filtered count on the canvas and the unfiltered pre-baked number in the scaffold.

**Impact:** the editor canvas is not a faithful preview of the preview, let alone of production. A user tuning a KPI or chart on the canvas is looking at numbers the deployed app will not show.

---

### Runtime error reporting — the generated app can never report an exception back to Forge — BUG (P2, confirmed)

`backend/services/runtime_injector.py:219` says `project_id` is "seeded into `.env.local` as `FORGE_PROJECT_ID` so the runtime error reporter can POST back to `/api/projects/<id>/runtime-exceptions`. Without it the reporter silently no-ops."

`output/gh0mlpbp/app/.env.local` in full:

```
DATABASE_URL=postgres://postgres:postgres@localhost:5432/app_gh0mlpbp
AUTH_SECRET=...
NEXTAUTH_SECRET=...
AUTH_TRUST_HOST=true
```

No `FORGE_PROJECT_ID`, no `FORGE_URL`. `output/gh0mlpbp/app/src/lib/error_reporter.ts:61` gates on exactly those:

```ts
if (!FORGE_URL || !FORGE_PROJECT_ID) return;
```

And even if seeded, the value available at that call site is the short_id (`assembly.py:296`), while `backend/routers/runtime_exceptions.py:122` declares `project_id: uuid.UUID = Path(...)` — so a report would 422 at the door.

**Impact:** the self-heal loop that is supposed to close runtime failures back into the platform is inert for Blueprint projects. Nothing in the generated app can tell Forge it broke.

---

### Workflows — the three definitions ARE projected, then deleted 2 ms later by a Windows path-separator bug — BUG (P0, proven)

This is the single highest-leverage defect found. The premise in the brief ("nothing was materialised") is half right: `output/gh0mlpbp/workflows/` is the *legacy* directory and is correctly empty for a Blueprint project. The Blueprint pipeline writes to `app/src/lib/workflows/definitions/` — and it **did**.

Evidence it ran: `output/gh0mlpbp/.forge/blueprint/current.json` `codeMap`

```json
{"artifact":"FLOW-001","service":["src/lib/workflows/definitions/add-inventory-item.json"]}
{"artifact":"FLOW-002","service":["src/lib/workflows/definitions/edit-inventory-item.json"]}
{"artifact":"FLOW-003","service":["src/lib/workflows/definitions/delete-inventory-item.json"]}
```

`codeMap` is upserted in `backend/services/blueprint/orchestrator.py:1462-1470` (`_project_integration`) **from the return value of** `project_workflows` (`backend/services/blueprint/projection.py:937`). Re-running `project_workflows(current.json, tmpdir)` today emits exactly those three files. Yet:

```
$ ls output/gh0mlpbp/app/src/lib/workflows/
OCR_SIDECAR.md  ai.ts  audit-log.ts  decision.ts  engine.ts  escalation.ts
index.ts  input-assembly.ts  node-io.ts  ocr.ts  types.ts
```

Every sibling engine file is there (10:30, the scaffold copy). `definitions/` is gone.

**Root cause** — `backend/services/runtime_injector.py:202-204`:

```python
for child in sorted(target.rglob("*"), key=lambda p: -len(p.parts)):
    rel = str(child.relative_to(root))
    if any(rel == p or rel.startswith(p + "/") for p in preserve):
        continue
```

`str(Path.relative_to())` yields backslashes on Windows; `PROJECTED_PATHS` (`backend/services/blueprint/assembly.py:63`) spells the entry with forward slashes. Demonstrated:

```
$ python -c "..."
rel        = 'src\\lib\\workflows\\definitions\\add-inventory-item.json'
as_posix   = 'src/lib/workflows/definitions/add-inventory-item.json'
preserved? = False
would be preserved with as_posix? = True
```

So the `preserve` guard matches nothing on Windows and every projected definition is `unlink()`ed, then the empty `definitions/` dir `rmdir()`ed. Scope is exactly the workflows dir: `_remove_except` is only called on `src/lib/{feel-lite,workflows,rules,events}` (`runtime_injector.py:242,258`), and `src/lib/workflows/definitions` is the only `PROJECTED_PATHS` entry underneath.

**The comment directly above the call site describes this exact bug being fixed** — `runtime_injector.py:251-257`:

```python
# `preserve` names paths a projection owns. This used to rmtree the
# whole directory, which installed the workflow engine correctly and
# deleted the 13 workflow definitions written moments earlier ...
# Two copiers, one directory, and the generated half lost every run.
```

The fix is correct on POSIX and a complete no-op on Windows.

**Timing:** this runs in `preview` → `apply_assembly` → `assemble()` (`assembly.py:396-400`) → `inject_runtime_layer`, the node immediately after `integration`. Run `.forge/runs/20260905-083143-a82644.jsonl`: `integration` done at +396 ms, `preview` starts at +398 ms.

**One-line fix:** `rel = child.relative_to(root).as_posix()`.

**Impact:** on Windows, every Blueprint build ships zero workflow definitions while its own Blueprint and `codeMap` assert three exist. Nothing reports it.

---

### Workflows — a complete execution engine ships in every app; only the definitions are missing — GAP (P0)

Contrary to expectation, there **is** a real interpreter, vendored into every generated app by `inject_runtime`:

- `output/gh0mlpbp/app/src/lib/workflows/engine.ts` (60 KB) — walks nodes/edges, `condition` at `:453`, `set_variable` at `:1071`, resume markers, gateways.
- `output/gh0mlpbp/app/src/lib/workflows/index.ts` — the real action handlers: `db_insert` (`:940`), `db_update` (`:1034`), `db_delete` (`:1080`), `db_query` (`:1114`), plus `http_call`, `send_email`, `send_notification`, `generate_document`, `mcp_tool_call`. `emit_event` routes through `lib/events/emit-node.ts` + `lib/events/bus.ts`.
- HTTP surface: `app/src/app/api/workflows/[id]/execute/route.ts` (POST, session-derived user, task resume, `?detach=1`), `api/workflows/event/[event]/route.ts`, and DB tables `_forge_workflow_tasks`, `_forge_workflow_execution_log`.

Steps are **interpreted, not compiled** — there is no per-workflow route-handler compiler.

The loader is the choke point — `index.ts:93-95`:

```ts
const dir = workflowsDir || path.join(process.cwd(), "src/lib/workflows/definitions");
```

Missing dir → `catch` → `workflowsLoaded = true` with an empty cache → `index.ts:167` returns `{ error: "Workflow not found: ${workflowIdOrName}" }`. Definitions are indexed by `id`, `name` **and** `blueprintId` (`index.ts:110-127`), so `FLOW-001` would resolve correctly if the file existed.

**So the answer to "can these workflows actually RUN" is: yes, everything except the three JSON files is present and correct.** Fixing `runtime_injector.py:202` alone turns this project's three workflows from missing into runnable.

---

### Workflows — both forms in the shipped app are wired to workflows and both fail at submit — BUG (P0)

The forms are correctly authored. `output/gh0mlpbp/app/src/schemas/items/new.json` (PAGE-002) is a single `Form` node with `fields`, `submitLabel: "Add Item"`, `workflow: "FLOW-001"`. `items/[id]/edit.json` (PAGE-004) carries `workflow: "FLOW-002"`.

`packages/library/src/components/Form/Form.tsx:156`:

```tsx
if (!workflow || submitting) return;
```

A Form with no workflow **does not submit at all**; with one it calls `dispatch(workflow, values)` (`Form.tsx:168`) → `lib/WorkflowDispatchProvider.tsx` → `createWorkflowDispatch` (`packages/renderer/src/client/WorkflowDispatcher.tsx`) → `POST /api/workflows/FLOW-001/execute` → `triggerWorkflow` → empty cache → `{"error":"Workflow not found: FLOW-001"}`, surfaced to the user as a red toast.

A generic CRUD surface **does** exist (`app/src/app/api/data/[...path]/route.ts`, GET/POST/PUT/DELETE) but nothing on PAGE-002/PAGE-004 posts to it — the Blueprint deliberately routes writes through workflows (`projection.py:1543-1554`: *"writes go through the workflow routes"*). There is no fallback path.

Independently confirmed by the binding validator run against the built app:

```
items/[id]/edit.json  workflow_ref FLOW-002 | Form references workflow 'FLOW-002', which does not exist.
items/new.json        workflow_ref FLOW-001 | Form references workflow 'FLOW-001', which does not exist.
```

**Impact:** the Inventory Manager cannot add, edit or delete an item. Every write path in the app is dead, and the failure surfaces only as a toast at submit time.

---

### Workflows — three separate stale-path readers, each returning empty for Blueprint projects — BUG (P1)

`backend/routers/workflows.py:65-87` got the correct fix — `PROJECTED_WORKFLOWS_DIR = "app/src/lib/workflows/definitions"` with a legacy fallback, and a docstring at `:70-80` describing the split-brain precisely. Three other readers did not:

1. `backend/routers/ir.py:398` — `/api/projects/{id}/registry/workflows` reads `registry.json` then falls back to `<output>/workflows` (legacy only). This is the endpoint **every editor workflow picker queries** (see next finding), so it returns `[]` for every Blueprint project.
2. `backend/runtime/engine.py:445` — `wf_file = Path(output_dir) / "workflows" / f"{workflow_id}.json"`. Legacy only, no projected fallback, so `POST /api/projects/{id}/workflows/start` (`routers/workflows.py:975`) can never find a Blueprint workflow even after the deletion bug is fixed. The whole Python `backend/runtime/` engine (~10 modules) additionally has no frontend caller at all.
3. The **generated app's own** `GET /api/workflows` (`app/src/app/api/workflows/route.ts:11`) and `GET /api/workflows/[id]` (`[id]/route.ts:15`) read `path.join(process.cwd(), "workflows")` — i.e. `app/workflows/`, a directory neither pipeline ever writes. Both return `[]`/404 unconditionally. Only `[id]/execute` uses the correct loader.

Also latent: `workflow_list_item()` (`routers/workflows.py:94-113`) reads `data["definition"]["steps"]`, but `project_workflows` emits `definition: {trigger, nodes, edges}` (`projection.py:998-1001`) — every Blueprint workflow lists with `step_count: 0`.

---

### Actions from the editor — `FLOW-001` is offered nowhere; the prop is a free-text box — BUG (P0)

The validator's requirement is real. `backend/services/blueprint/functional_completeness.py:150`:

```python
workflows = {str(w["id"]) for w in _live(doc.get("workflows")) if w.get("id")}
```

— the allowed set is Blueprint **ids** (`FLOW-001`), not names or slugs. `_workflow_refs()` (`:106`) walks props for any key literally named `workflow`; `:188-193` emits `workflow-not-defined` and `:184` emits `control-without-action`. These are hard rejections via `verification.py:385`, `agent_contract.py:501`, `blueprint_generate.py:122` — and they are what killed PAGE-002/003/004 in this project's run logs (`InvalidPatternTemplate: … targets workflow 'updateItem'/'deleteItem', which this application does not define`).

The contracts declare the prop: `packages/registry/dist/component-contracts.json` has `Button.workflow` and `Form.workflow` as `{type: string, optional: true}`. So the shape is legal.

**But the editor renders it as plain text.** `packages/registry/src/starter.ts:1257` (Form) and `:1332` (Button):

```ts
workflow: { type: "string", default: "", control: "text", group: "behavior", ... }
```

`control: "text"` → `frontend/src/components/properties/PropertiesPanel.tsx:249` (`CONTROL_BY_TYPE[descriptor.control]`) renders a free-text input. **The user must know and hand-type `FLOW-001`.**

A workflow-aware control exists and is unreachable for this prop: `frontend/src/components/properties/PropControls/ActionPicker.tsx` has a real dropdown (`:163-190`), registered as `actionPicker` (`PropControls/index.tsx:144`) — but `starter.ts` attaches `control: "actionPicker"` to ~40 *other* props (e.g. `Form.fields` at `:1267`, and `KeyValueList.items` — see the registry finding above) and never to `Button.workflow`/`Form.workflow`.

**And even that picker would be empty.** `ActionPicker.tsx:77`, `ir-editor/WorkflowBindingPanel.tsx:41`, `ir-editor/DataBindingPanel.tsx:79`, `visual-editor/ContextPanel.tsx:60` all fetch `/api/projects/{id}/registry/workflows` → `backend/routers/ir.py:352-418`, which reads only the legacy dir (previous finding). The UI degrades to the literal string `"workflow-id (registry empty — type manually)"` (`ActionPicker.tsx:193`).

Third divergence: `frontend/src/components/ir-editor/WorkflowBindingPanel.tsx:73` writes `node.onSuccessWorkflow = {workflowId, inputMapping}` — a prop name neither the contracts, nor `functional_completeness._workflow_refs`, nor `Form.tsx` recognise. Anything bound through that panel is inert and invisible to the gate.

**Answer to the brief's question: no.** A Button or Form can be wired to a workflow only by typing a raw id into a free-text field, with no list, no autocomplete and no validation anywhere in the editor — while a gate that hard-rejects a wrong id runs downstream.

Note the A2UI composer *does* get this right: `output/gh0mlpbp/src/contracts/a2ui-surfaces/items-id.1.json` contains `{"id":"deleteButton","component":"Button","workflow":"FLOW-003","args":{"itemId":{"path":"/item/id"}}}`, because `a2ui_authority.py:596-604` explicitly hands the composer the workflow list. The LLM path has the affordance the human editor lacks.

---

### Bindings — there is exactly one resolver, it is client-side only, and its "don't leak" guard is a root-name heuristic — BUG (P0)

`packages/renderer/src/runtime/interpolate.ts` is the only implementation (`packages/engine/src/data/interpolate.ts:7` re-exports it). Single call site — `packages/renderer/src/runtime/dispatch.tsx:105-108`:

```tsx
if (node.props && typeof node.props === "object") {
  const interp = interpolateDeep(node.props, { ...ctx.data, user: ctx.user });
  node = { ...node, props: interp };
}
```

`ctx.data` is only ever keyed by **dataSource `name`** — `packages/renderer/src/server/DataResolver.ts:12-16`, `output/gh0mlpbp/app/src/lib/schema-page.tsx:183-234`, `apps/render-scaffold/src/lib/resolvePreviewSync.ts:26-75`, `frontend/src/lib/preview-resolve.ts:139-155`.

**There is no pipeline-time substitution anywhere.** `backend/services/binding_resolver.py` is an LLM prompt asking which *entity* an ambiguous widget belongs to (`build_prompt`, `:63`), not a value resolver; `binding_contract.py`, `binding_prop_normalizer.py` and `read_binding_guard.py` rewrite binding *strings*. Bindings reach disk as literal `{{…}}` and are resolved 100% in the browser.

The leak — `interpolate.ts:141-151`:

```ts
if (v === undefined || v === null || v === false) {
  // Live render: when the binding's ROOT source is present in the data
  // context ... render empty rather than leaking the raw `{{…}}` placeholder
  // to users. Only the editor/preview canvas (no data context at all) keeps
  // the placeholder visible so authors can see what's bound.
  const root = expr.match(/^([A-Za-z_$][\w$]*)/)?.[1];
  if (root && Object.prototype.hasOwnProperty.call(data, root)) return "";
  return text;                       // <-- THE LEAK
}
```

The guard tests **root presence**, not "is this a live render". A binding whose root namespace is not a declared dataSource name — precisely the `metrics.*` case — falls through to `return text` on a live page. The code comment's claim that only the editor canvas keeps the placeholder is factually wrong for exactly this case, and the behaviour is locked in by `packages/renderer/tests/interpolate.test.ts:60-64`.

Three different failure behaviours for the same broken binding, verified by executing the bundled module:

| input | data | result |
|---|---|---|
| `{{metrics.list_total_inventory_value}}` | root absent | `"{{metrics.list_total_inventory_value}}"` — **leaks to the user** |
| `{{totalInventoryValue.nope}}` | root present, field absent | `""` — silent blank |
| `"Value: {{metrics.list_items}} today"` | root absent, mixed string | `"Value:  today"` — **silently deleted** (`interpolate.ts:159`) |

None produces an error, a log line the user can see, or a visible fallback.

---

### Bindings — no authoring-time validation; the editor's own canonical bind form is unimplemented by every renderer — BUG (P0)

The editor **has** an available-data contract: `frontend/src/components/properties/PropControls/BindingControl.tsx:109-166` builds `groups` from `pageSchemas[pageId].dataSources` plus `/api/projects/{id}/registry/entities`, and offers correct expressions per `op` (`aggregate` → metric keys, `series` → `label`/`value`, `list` → `name[0].field`). Nothing enforces it:

- `BindingControl.tsx:174` — an off-contract value is relabelled, not flagged: `const selectValue = val && known.has(val) ? val : val ? "__custom__" : "";`, rendered as `<option value="__custom__">Custom: {val}</option>` (`:239`).
- `BindingControl.tsx:345-352` — a free-text input accepts anything, unchecked against `known`.
- The `{{ }}` wrapping is unconditional with `v` unvalidated: `BindingsPanel.tsx:150` and `PropertiesPanel.tsx:289` both do `value: v ? \`{{${v}}}\` : ""`.
- A plain `TextControl` (`PropControls/index.tsx:28-41`) passes any string through verbatim, so typing `{{anything}}` into any non-bindable prop silently creates a binding.
- The patch layer validates nothing — `packages/patches/src/apply.ts:114-134` (`updateProp`) just assigns.
- There is no binding lint or diagnostics surface anywhere in `frontend/src`.

**Separate and worse:** the editor's `BindToggle` dispatches `bindProp`, which writes an **object** form — `packages/patches/src/apply.ts:318`:

```ts
node.props[action.propName] = { $binding: action.binding };
```

`$binding` appears **zero times** in `packages/renderer/src`, `packages/engine/src`, `packages/library/src`, `packages/registry/src` and `apps/render-scaffold/src` — confirmed by grep; its only occurrences in the repo are the 5 inside `packages/patches/src/apply.ts` itself. `interpolateDeep` leaves the object untouched (no `{{`), so it reaches `ctx.registry.validateProps` (`dispatch.tsx:247`) where e.g. `Stat.value: z.string()` rejects it, and the user gets the `⚠ Stat: invalid props` placeholder (`dispatch.tsx:263-286`).

**Impact:** the editor's canonical "bind this prop" gesture produces a value no renderer in the platform implements, and the free-text path produces bindings nothing checks — at type time, save time, or render time.

---

### Bindings — a correct strict gate exists and did not run for this project — BUG (P1)

`backend/services/binding_validator.py:407-418` implements exactly the right check (`_STAT_NODE_TYPES` / `_STAT_BINDING_KEYS` / `_ROOT_TOKEN_RE`), and `backend/services/pipeline/binding_gate.py:31-34` is strict by default, failing at `:111-123`. Run against the built app it catches everything:

```
$ validate_bindings('output/gh0mlpbp/app')
ok=False errors=5
  items.json           binding_unresolved metrics | Stat value binds '{{metrics.list_total_inventory_value}}' but no dataSource named 'metrics' is declared on this page.
  items.json           binding_unresolved metrics | ... '{{metrics.list_low_stock_items}}'
  items.json           binding_unresolved metrics | ... '{{metrics.list_items}}'
  items/[id]/edit.json workflow_ref FLOW-002 | Form references workflow 'FLOW-002', which does not exist.
  items/new.json       workflow_ref FLOW-001 | Form references workflow 'FLOW-001', which does not exist.
```

All five headline runtime defects in this app were catchable pre-ship by a validator that already exists. The app shipped anyway — either with `FORGE_BINDING_GATE` in warn mode or with the gate not wired into the Blueprint pipeline. Worth noting that `functional_completeness._planner_placeholders()` (see the aggregates finding) *whitelists* `metrics`, so the two validators disagree with each other about whether `{{metrics.x}}` is a defect.

**Encoding gap found while running it:** `output/gh0mlpbp/src/schemas/PAGE-001.json` is **CP1252-encoded, not UTF-8** (byte `0x85` at offset 4280). `binding_validator.py:574-578` catches the decode failure as a `parse_error` **warning**, so that file's bindings are never checked at all. Any editor-written schema containing a smart quote or ellipsis is silently exempted from binding validation.

---

### Bindings — the renderer cannot distinguish a broken binding from literal braces — GAP (P2)

`interpolate.ts:29-30`:

```ts
const TEMPLATE_RE = /\{\{\s*([^{}]+?)\s*\}\}/g;
const WHOLE_TEMPLATE_RE = /^\s*\{\{\s*([^{}]+?)\s*\}\}\s*$/;
```

Any `{{…}}` is an expression. There is no escape syntax, no `raw` marker, and `evalExpression` (`bindings.ts:66-77`) collapses parse error, missing path and type error into one value with a console-only warning. Verified:

```
LITERAL prose (whole)  '{{ this is not an expression }}'  ->  "{{ this is not an expression }}"
LITERAL prose (mixed)  'use {{ two words }} here'         ->  "use  here"
```

The only thing that changes the outcome is the string's shape and whether the first identifier happens to be a `data` key — never authorial intent. A literal `{{TODO}}` in copy is indistinguishable from a broken data binding, and in mixed text it is erased.

**Impact:** no render-time repair is possible without introducing an escape syntax or actually implementing the `$binding` typed form the editor already emits.

---

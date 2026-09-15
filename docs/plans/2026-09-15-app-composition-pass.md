# App-level composition pass (§34 addendum)

**Status (2026-09-15): built on claude/a2ui-pages-forms-spec-c002e1, then ported onto smithv2 as claude/composition-pass-smithv2. On smithv2 there is no `patterns` node: `composition` sits between `page_details` and `page_layouts`.** Contract, registry, DAG node,
briefs, prompts and tests are in; the sections below are the design they
follow. The composition pass has not yet been exercised against a live model.

**Problem.** `a2ui_pages` authors each page from `page_brief`, which shows one
page and nothing about its siblings. Coherence is meant to come from
`designSystem` and `patternTemplates`, but once a page is authored bespoke
nothing has seen the app as a whole. The one-shot alternative (A2UI designs the
whole app in one reply) is what the old platform did: 50–80k tokens a call,
one bad prop rejects the whole surface, output truncates at eighteen trees.

**Shape of the fix.** One cheap whole-app *composition* call after page
contracts and the design system. It produces a skeleton (per page: layout and
ordered sections, no props) plus app-wide conventions. Per-page authoring stays
exactly as it is, but each page is handed its skeleton entry, the conventions,
and a one-line view of its siblings. Catalog validation and retries stay per
page. Blueprint order is unchanged: data model, contracts, workflows and APIs
still precede all composition.

## 1. Contract first (`packages/schema/src/blueprint/blueprint.ts`)

Declare before any producer writes it, then `npm run emit:blueprint-schema
--workspace=packages/schema`.

```ts
// §34 · app-level composition — the one call that sees every page at once
export const SectionSketch = z.object({
  name: z.string(),                       // "Pipeline summary"
  purpose: z.string(),                    // what the user does in it
  /** Catalog component *names* only — no props. Validated against the catalog. */
  components: z.array(z.string()).default([]),
  emphasis: z.enum(["primary", "secondary"]).default("secondary"),
  region: z.enum(["main", "aside", "full"]).default("main"),
});

export const PageSketch = z.object({
  page: PageId,                           // natural key
  layout: z.enum(["single_column", "main_aside", "two_pane", "full_bleed"]),
  sections: z.array(SectionSketch).min(1),
  rationale: z.string().default(""),
});

export const Composition = z.object({
  /** One paragraph: what the whole app should feel like to use. */
  vision: z.string().default(""),
  /** App-wide rules every page inherits: header rhythm, where filters sit,
   *  how empty states read, where the primary action lives. */
  conventions: z.array(z.object({ topic: z.string(), rule: z.string() })).default([]),
  pages: z.array(PageSketch).default([]),
});

// in Blueprint:
/** §34 — whole-app skeleton and conventions. Authored by A2UI, once. */
composition: Composition.default({}),
```

Singleton, like `designSystem`: one per app, merged on write.

## 2. Registry (`backend/services/blueprint/service.py`, `agent_contract.py`)

- `SINGLETON_SECTIONS` += `"composition"`.
- `WRITABLE_SECTIONS` += `"composition"`.
- New capability, kept separate so the §30 boundary stays legible:

```python
"a2ui_composition": _cap(
    "a2ui_composition",
    {"composition"},
    reads={"requirements", "product", "pages", "modules", "navigation",
           "widgets", "roles", "designSystem"},
    tools={"blueprint:read", "page_contract:read", "design_system:read",
           "component_catalog:read", "mcp:a2ui"},
),
```

- `check_composition(result)` beside `check_pattern_templates`: every
  `pages[].page` is a live, non-deprecated page; every live page appears
  exactly once; every `components` entry names a catalog component. Rejection
  is fed back as retry feedback, same as templates. Nothing else is gated.

## 3. DAG (`backend/services/blueprint/orchestrator.py`)

```python
_n("composition", "a2ui_composition",
   ("page_contracts", "page_designs", "design_system"), ("composition",),
   note="§34; whole-app skeleton + conventions, no props, one call"),
_n("patterns", "a2ui_patterns", ("composition",), ("patternTemplates",), ...),
# page_layouts unchanged: depends on patterns, fanout="pages"
```

`INCREMENTAL_SECTIONS` += `"composition"`, with the same justification as
`patternTemplates`: §72 says "components", and a skeleton is a composition of
them. Adding a page re-runs `page_contracts`, and everything downstream
(composition, patterns, page_layouts) follows.

## 4. Briefs (`backend/services/blueprint/page_planner.py`)

- `catalog_index(catalog)`: names + category + one-line description, no
  props. Roughly a tenth of `catalog_digest`.
- `app_brief(doc)`: product, navigation tree, roles, and per page: name,
  route, purpose, pattern, primaryTasks, actions, entity name, widget count.
  ~150 tokens a page.
- `page_brief` gains:

```python
comp = doc.get("composition") or {}
brief["composition"] = {
    "vision": comp.get("vision", ""),
    "conventions": comp.get("conventions", []),
    "sketch": next((s for s in comp.get("pages", []) if s.get("page") == page_id), None),
    "siblings": [{"page": s["page"], "layout": s["layout"],
                  "sections": [x["name"] for x in s["sections"]]}
                 for s in comp.get("pages", []) if s.get("page") != page_id],
}
```

## 5. Prompts (`backend/services/blueprint/executors.py`)

- `NODE_TASKS["composition"]`: "Compose the whole application once. For every
  page, choose a layout and an ordered list of sections with the component
  families each uses. State the conventions every page will follow. No props,
  no bindings: structure and intent only. Make the app read as one product."
- `build_prompt` branch for `a2ui_composition`: system = SYSTEM + shapes +
  `catalog_index` + `pattern_page_facts`; user = `app_brief`.
- `a2ui_pages` user prompt adds: "Realise `composition.sketch` — those
  sections, in that order — using the catalog. `composition.conventions` are
  the app's decisions, not yours to re-make. `siblings` shows what the pages
  next to this one look like." No structural gate on divergence; the observer
  judges coherence, the sketch is the instruction.
- `a2ui_patterns` receives `vision` + `conventions` in the catalog addendum.

## 6. Tests

- `test_page_planner`: `page_brief` carries the page's sketch, conventions and
  siblings; `catalog_index` names every catalog component and no prop.
- `test_agent_contract`: `check_composition` rejects an unknown page, a
  missing page, and an unknown component name; accepts a full cover.
- `test_orchestrator`: `composition` sits between `design_system` and
  `patterns`; adding a page re-runs it; `is_foundational` is False for it.

## Cost

One extra call per run: ~8k in (index + app brief), ~3k out. Per-page calls
grow by the size of one sketch plus sibling lines, ~300 tokens each.

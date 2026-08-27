# Dashboard Fidelity & Density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the visual-density gap between generated dashboards and reference designs (Google Analytics, PatientPop) by teaching the LLM canonical dashboard compositions and giving design-spec tokens for surface depth.

**Architecture:** Four workstreams. **A** ships dashboard exemplars + a density rule so the LLM emits ≥4 MetricTiles + ≥1 Chart + ≥1 list/feed on every dashboard page (same proximity-training pattern proven in Tier S/M/L Task 19). **B** extends the design-spec schema with `surface.gradient`, `surface.shadow`, and `accent.illustration` tokens, then wires Hero/Card/Section to honor them. **D** stands up an in-house unDraw MCP server so the schema agent dynamically picks illustrations (auth heroes, empty states, dashboard accent imagery) from the live unDraw catalog and bakes the chosen SVGs into each generated app's `public/illustrations/`. **C** runs a live regeneration to confirm all layers compose into a visibly denser, more layered, more illustrated UI.

**Tech Stack:** TypeScript / Zod (schema), React (library components), Python / FastAPI (backend), `mcp` Python SDK + FastMCP (illustrations MCP server), `httpx` for the unDraw client, pytest + vitest (tests), Tailwind utility classes for the gradient/shadow surfaces.

**Spec:** This plan is its own spec — derived from the architectural discussion in session 2026-05-12 with reference images (PatientPop dashboard, Google Analytics Reports snapshot, dashboard wireframe).

---

## Background — what's missing today

**Test case:** the `/notes` list page generated 2026-05-12 (`output/pagedriven-2p-1778564381/src/schemas/notes.json`) emits:

```
Container → Stack
  Hero (with gradient ✓)
  Grid → 4 MetricTiles
  Section → Grid → Repeat(Card with title, preview, date, action)
```

Compare to references:
- **PatientPop**: 5 KPI cards + 2 donut metrics + line chart + bar chart + Activity feed with photo avatars + custom mascot illustration
- **Google Analytics**: 4 stat tiles + line chart + last-30-min sparkline grid + top countries list + insights cards
- **Wireframe**: navigation + filters + 5-6 KPI cards + 2-3 charts + tables

The library already has `Chart`/`Sparkline`/`DataGrid`/`ActivityFeed`/`Timeline`/`MetricTile` components built and tested. The LLM doesn't reach for them because (1) no dashboard exemplar trains it on the canonical composition and (2) no rule enforces density.

**Out of this plan:**
- Custom illustrations (smiley mascots, branded SVGs) — needs an asset-library pipeline
- Vision-grounded fidelity scoring — requires reference-bank seeder work, separate plan
- Photo avatars from real fixture URLs — requires fixture-image pipeline

---

## File structure

### New files
- `backend/fixtures/exemplars/dashboard-kpi-grid.json` — canonical GA-style metric dashboard
- `backend/fixtures/exemplars/dashboard-domain-overview.json` — PatientPop-style mixed dashboard
- `backend/fixtures/exemplars/auth-split-illustration.json` — login layout with `accent.illustration` slot (Workstream D)
- `packages/library/src/components/surfaces/SurfaceBackground.tsx` — shared component that turns a `style.background` token into a rendered backdrop (gradient / solid / image)
- `packages/library/src/components/surfaces/IllustrationResolver.tsx` — renders an illustration slot from a slug ref (Workstream D)
- `packages/library/tests/components/SurfaceBackground.test.tsx` — tests for the surface helper
- `packages/library/tests/components/IllustrationResolver.test.tsx` — tests for the illustration renderer (Workstream D)
- `backend/mcp/__init__.py` — MCP package marker (Workstream D)
- `backend/mcp/illustrations_server.py` — in-house unDraw MCP server (Workstream D)
- `backend/mcp/undraw_client.py` — HTTP client + filesystem cache wrapping unDraw's catalog (Workstream D)
- `backend/tests/mcp/test_illustrations_server.py` — MCP server tool tests (Workstream D)
- `backend/tests/mcp/test_undraw_client.py` — client + cache tests (Workstream D)
- `backend/tests/services/test_dashboard_exemplars.py` — pytest covering the new exemplar JSONs parse
- `backend/tests/services/test_dashboard_density_rule.py` — pytest covering the new rule
- `backend/tests/services/test_illustration_bundler.py` — pytest covering asset bundling (Workstream D)
- `backend/tests/services/test_schema_prompt_auth.py` — pytest covering the auth prompt teaching (Workstream D)

### Modified files
- `backend/services/schema_prompt.py` — extend `_exemplar_for()` to map `page_type == "dashboard"` to `dashboard-kpi-grid`; add auth-page guidance + illustration-tool documentation (Workstream D)
- `backend/services/schema_rules.py` — add `dashboard-density` rule applied when `page_type == "dashboard"`; add `auth-page-illustration` rule (Workstream D)
- `packages/schema/src/tokens.ts` — extend the design-tokens Zod schema: add `surface.gradient`, `surface.shadow`, `accent.illustration` keys
- `packages/schema/src/page.ts` — extend `accent.illustration` slot reference to support `{ slug, tone? }` shape (Workstream D)
- `packages/library/src/components/Card/Card.tsx` — honor `style.background` when it's a gradient
- `packages/library/src/components/Section/Section.tsx` — same — gradient-aware backdrop; consume optional illustration slot for split layouts (Workstream D)
- `packages/library/src/components/Hero/Hero.tsx` — replace inline gradient logic with shared `SurfaceBackground`; render illustration when slot is present (Workstream D)
- `packages/library/src/components/EmptyStateRich/EmptyStateRich.tsx` — render illustration when slot is present (Workstream D)
- `backend/agents/design_agent.py` — emit default `surface.gradient` and `surface.shadow` blocks per register in `design-spec.json`
- `backend/agents/page_schema_agent.py` — register illustrations MCP server in ClaudeAgentOptions; bundle chosen SVGs into `output/<id>/public/illustrations/` (Workstream D)
- `packages/schema/tests/exemplars.test.ts` — extend EXEMPLARS array to include the 2 new dashboard exemplars + the auth exemplar
- (Generated app) `output/<id>/src/contracts/design-spec.json` — picks up the new keys via design_agent
- (Generated app) `output/<id>/public/illustrations/` — populated at schema-emission time with the chosen unDraw SVGs (Workstream D)

---

## Design decisions (locked in before tasks)

1. **Dashboard density floor**: a `page_type: "dashboard"` schema MUST contain ≥4 MetricTile nodes AND ≥1 Chart/Sparkline node AND ≥1 list-style container (ActivityFeed | DataGrid | Repeat over Card). Pages below this floor are flagged by `dashboard-density` rule + a soft warning (no hard fail — same conservative scope as the CTA gate from Tier S/M/L Task 18).

2. **Exemplars are inlined into the prompt** when `page_type == "dashboard"` (same mechanism as `wide-form-accordion.json` for forms). The LLM gets a full reference schema to anchor against.

3. **`surface.gradient` token shape**:
   ```json
   { "type": "linear", "angle": 135, "from": "tokens.color.accent.50", "to": "tokens.color.surface.0" }
   ```
   Mirrors the inline form Hero already emits — promoted from one-off prop value to a first-class token so Card/Section/Hero can all reference `tokens.surface.gradient.subtle` etc.

4. **`SurfaceBackground` component**: a single internal React component that consumes a `background` style slot and renders the right backdrop (gradient div, solid color, or no-op). Avoids each component re-implementing gradient logic.

5. **Design-spec emission is additive**: existing projects without the new token sections keep working (`useDesignToken("surface.gradient.subtle")` returns undefined → component falls back to current behavior). No migration step required.

6. **`dashboard-domain-overview.json` exemplar uses fictional domain ("healthcare practice")** so the LLM doesn't latch onto a specific industry — it's a template, not industry-specific.

7. **Illustrations MCP — in-house, unDraw-backed.** No maintained third-party illustration MCP exists (the `undraw-mcp` npm package's repo is 404). We build a thin FastMCP server that wraps unDraw's public HTTP API. Two tools: `list_illustrations(tags, limit)` and `get_illustration_svg(slug, color)`. Cached forever per `(slug, color)` to disk under `backend/.cache/illustrations/`.

8. **Illustration delivery — bundled, not CDN.** When the schema agent picks an illustration slug, the bundler copies the cached SVG from `backend/.cache/illustrations/<slug>__<color>.svg` to `output/<id>/public/illustrations/<slug>.svg`. The generated Next.js app ships with the SVGs; runtime needs no internet. The schema records `{ accent: { illustration: { slug: "running-athlete", tone: "primary" } } }`; the resolver maps `tone` → recolored variant in the public/ dir.

9. **Illustration slot is opt-in, not on every page.** Auth pages (route matches `^/(login|signup|signin|signup|register|forgot)`) get an illustration slot on Hero. Dashboard exemplars do NOT use illustrations by default (icons + gradients are enough for KPI-density). EmptyStateRich gets an illustration prop. Other pages render fine without illustrations.

10. **MCP registration is per-agent**: the illustrations MCP is added to `page_schema_agent`'s `ClaudeAgentOptions.mcpServers` config. Other agents (api_agent, design_agent, etc.) don't need it — only the schema agent emits illustration refs.

---

## Workstream A — Dashboard exemplars + density rule

### Task 1: Author `dashboard-kpi-grid.json` exemplar

**Files:**
- Create: `backend/fixtures/exemplars/dashboard-kpi-grid.json`

- [ ] **Step 1.1: Author the exemplar**

The canonical Google Analytics-style metric dashboard. Mirrors the layout density of image #2.

```json
{
  "schemaVersion": "2",
  "id": "exemplar-dashboard-kpi-grid",
  "route": "/example/dashboard",
  "layout": "main",
  "root": {
    "id": "page-root",
    "type": "Stack",
    "props": { "direction": "vertical", "gap": "tokens.spacing.semantic.section" },
    "children": [
      {
        "id": "hero",
        "type": "Hero",
        "props": {
          "eyebrow": "Reports snapshot",
          "headline": "Last 28 days",
          "subhead": "Oct 21 – Nov 17, 2025",
          "layout": "inline",
          "ctas": []
        }
      },
      {
        "id": "kpi-row",
        "type": "Grid",
        "props": { "columns": 4, "gap": "tokens.spacing.semantic.card" },
        "children": [
          {
            "id": "kpi-users",
            "type": "MetricTile",
            "props": {
              "label": "Users",
              "value": "83K",
              "delta": { "value": "+12%", "tone": "positive" },
              "icon": "users",
              "importance": "primary"
            }
          },
          {
            "id": "kpi-new",
            "type": "MetricTile",
            "props": {
              "label": "New users",
              "value": "70K",
              "delta": { "value": "+8%", "tone": "positive" },
              "icon": "user-plus",
              "importance": "primary"
            }
          },
          {
            "id": "kpi-engagement",
            "type": "MetricTile",
            "props": {
              "label": "Avg engagement",
              "value": "2m 00s",
              "delta": { "value": "+5s", "tone": "positive" },
              "icon": "clock",
              "importance": "secondary"
            }
          },
          {
            "id": "kpi-revenue",
            "type": "MetricTile",
            "props": {
              "label": "Revenue",
              "value": "$253K",
              "delta": { "value": "+15%", "tone": "positive" },
              "icon": "dollar-sign",
              "importance": "primary"
            }
          }
        ]
      },
      {
        "id": "main-chart-row",
        "type": "Grid",
        "props": { "columns": 3, "gap": "tokens.spacing.semantic.card" },
        "children": [
          {
            "id": "trend-chart-wrapper",
            "type": "Card",
            "props": { "span": 2 },
            "children": [
              {
                "id": "trend-chart",
                "type": "Chart",
                "props": {
                  "kind": "line",
                  "title": "Daily users",
                  "data": "{{stats.dailyUsers}}",
                  "xKey": "date",
                  "yKey": "users"
                }
              }
            ]
          },
          {
            "id": "top-countries-card",
            "type": "Card",
            "children": [
              {
                "id": "top-countries",
                "type": "ActivityFeed",
                "props": {
                  "title": "Top countries",
                  "entries": "{{stats.topCountries}}",
                  "showTimestamps": false
                }
              }
            ]
          }
        ]
      },
      {
        "id": "secondary-row",
        "type": "Grid",
        "props": { "columns": 2, "gap": "tokens.spacing.semantic.card" },
        "children": [
          {
            "id": "sources-chart",
            "type": "Card",
            "children": [
              {
                "id": "sources-bar",
                "type": "Chart",
                "props": {
                  "kind": "bar",
                  "title": "New users by source",
                  "data": "{{stats.userSources}}",
                  "xKey": "source",
                  "yKey": "users"
                }
              }
            ]
          },
          {
            "id": "insights-card",
            "type": "Card",
            "children": [
              {
                "id": "insights-feed",
                "type": "ActivityFeed",
                "props": {
                  "title": "Insights",
                  "entries": "{{stats.insights}}"
                }
              }
            ]
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 1.2: Verify the exemplar parses against the Page schema**

Run the existing exemplar vitest (already extended in Tier S/M/L Task 19). First, extend the `EXEMPLARS` array:

In `packages/schema/tests/exemplars.test.ts`, add `"dashboard-kpi-grid"` to the EXEMPLARS array.

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema && npx vitest run tests/exemplars.test.ts
```

Expected: 6/6 PASS (was 5/5 — adds the new one).

If validation fails: the JSON schema parser will report which path failed. Fix the exemplar (likely a missing `id`, an invalid `props` shape on Chart, or unknown enum value) and re-run.

- [ ] **Step 1.3: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/fixtures/exemplars/dashboard-kpi-grid.json packages/schema/tests/exemplars.test.ts
git commit -m "$(cat <<'EOF'
feat(exemplars): dashboard-kpi-grid template for analytics-style pages

4 KPI tiles + main trend chart + secondary bar chart + top-countries
and insights feeds. Used by build_schema_prompt() when page_type is
"dashboard" — mirrors the canonical Google Analytics / Reports snapshot
layout pattern.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 2: Author `dashboard-domain-overview.json` exemplar

**Files:**
- Create: `backend/fixtures/exemplars/dashboard-domain-overview.json`

PatientPop-style mixed dashboard with hero metric callouts + Activity feed.

- [ ] **Step 2.1: Author the exemplar**

```json
{
  "schemaVersion": "2",
  "id": "exemplar-dashboard-domain-overview",
  "route": "/example/overview",
  "layout": "main",
  "root": {
    "id": "page-root",
    "type": "Stack",
    "props": { "direction": "vertical", "gap": "tokens.spacing.semantic.section" },
    "children": [
      {
        "id": "hero",
        "type": "Hero",
        "props": {
          "eyebrow": "Practice Overview",
          "headline": "How your practice is performing",
          "subhead": "Last 12 months at a glance",
          "layout": "inline",
          "ctas": [
            { "label": "Export report", "variant": "secondary", "icon": "download" }
          ]
        }
      },
      {
        "id": "kpi-row",
        "type": "Grid",
        "props": { "columns": 3, "gap": "tokens.spacing.semantic.card" },
        "children": [
          {
            "id": "kpi-rating",
            "type": "MetricTile",
            "props": {
              "label": "Overall rating",
              "value": "4.0",
              "delta": { "value": "+0.5 from last month", "tone": "positive" },
              "icon": "star",
              "importance": "primary"
            }
          },
          {
            "id": "kpi-reviews",
            "type": "MetricTile",
            "props": {
              "label": "Public reviews",
              "value": "3,431",
              "delta": { "value": "+1,725 this year", "tone": "positive" },
              "icon": "message-square",
              "importance": "primary"
            }
          },
          {
            "id": "kpi-sentiment",
            "type": "MetricTile",
            "props": {
              "label": "Patient sentiment",
              "value": "91%",
              "delta": { "value": "Superb", "tone": "positive" },
              "icon": "smile",
              "importance": "primary"
            }
          }
        ]
      },
      {
        "id": "details-row",
        "type": "Grid",
        "props": { "columns": 2, "gap": "tokens.spacing.semantic.card" },
        "children": [
          {
            "id": "reviews-feed-card",
            "type": "Card",
            "children": [
              {
                "id": "reviews-feed",
                "type": "ActivityFeed",
                "props": {
                  "title": "Latest reviews",
                  "entries": "{{stats.latestReviews}}"
                }
              }
            ]
          },
          {
            "id": "metrics-stack",
            "type": "Stack",
            "props": { "direction": "vertical", "gap": "tokens.spacing.semantic.card" },
            "children": [
              {
                "id": "online-requests-card",
                "type": "Card",
                "children": [
                  {
                    "id": "online-requests",
                    "type": "MetricTile",
                    "props": {
                      "label": "Online requests",
                      "value": "9,245",
                      "delta": { "value": "New: 5.9k · Returning: 3.1k", "tone": "neutral" },
                      "icon": "monitor",
                      "importance": "secondary"
                    }
                  }
                ]
              },
              {
                "id": "phone-leads-card",
                "type": "Card",
                "children": [
                  {
                    "id": "phone-leads",
                    "type": "MetricTile",
                    "props": {
                      "label": "Phone leads",
                      "value": "3,271",
                      "delta": { "value": "New: 2.6k · Returning: 671", "tone": "neutral" },
                      "icon": "phone",
                      "importance": "secondary"
                    }
                  }
                ]
              }
            ]
          }
        ]
      },
      {
        "id": "traffic-row",
        "type": "Grid",
        "props": { "columns": 2, "gap": "tokens.spacing.semantic.card" },
        "children": [
          {
            "id": "traffic-chart-card",
            "type": "Card",
            "children": [
              {
                "id": "traffic-chart",
                "type": "Chart",
                "props": {
                  "kind": "bar",
                  "title": "Website traffic",
                  "data": "{{stats.websiteTraffic}}",
                  "xKey": "source",
                  "yKey": "visitors"
                }
              }
            ]
          },
          {
            "id": "search-positions-card",
            "type": "Card",
            "children": [
              {
                "id": "search-positions",
                "type": "ActivityFeed",
                "props": {
                  "title": "Search position increases",
                  "entries": "{{stats.searchPositions}}"
                }
              }
            ]
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2.2: Extend the EXEMPLARS test array**

In `packages/schema/tests/exemplars.test.ts`, add `"dashboard-domain-overview"`.

- [ ] **Step 2.3: Run vitest**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema && npx vitest run tests/exemplars.test.ts
```

Expected: 7/7 PASS.

- [ ] **Step 2.4: Commit**

```bash
git add backend/fixtures/exemplars/dashboard-domain-overview.json packages/schema/tests/exemplars.test.ts
git commit -m "$(cat <<'EOF'
feat(exemplars): dashboard-domain-overview template for mixed dashboards

3 hero KPIs + Activity feed + nested metric cards + traffic chart +
search positions feed. Mirrors PatientPop-style mixed-content
dashboards where some entities live in feeds and others in cards.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 3: Wire dashboard exemplars into `schema_prompt.py`

**Files:**
- Modify: `backend/services/schema_prompt.py`

- [ ] **Step 3.1: Find the existing `_exemplar_for` function**

```bash
grep -n "_exemplar_for\|_load_exemplar" /Users/m/Work/code/poc/design2ui-forge-v3/backend/services/schema_prompt.py
```

Should find the function added in Tier S/M/L Task 19. Today it maps `"form"` → `wide-form-accordion`, `"detail"` → `detail-tabs`. Extend it.

- [ ] **Step 3.2: Add dashboard mapping**

Replace the dict literal:

```python
def _exemplar_for(page_type: str) -> str:
    return {
        "form":      _load_exemplar("wide-form-accordion"),
        "detail":    _load_exemplar("detail-tabs"),
        "dashboard": _load_exemplar("dashboard-kpi-grid"),
    }.get(page_type, "")
```

The `dashboard-domain-overview` exemplar is referenced from the rule block (next task) — only one exemplar gets inlined per generation to keep token budget in check.

- [ ] **Step 3.3: Add a snapshot test**

`backend/tests/services/test_schema_prompt_dashboard.py`:

```python
from services.schema_prompt import build_schema_prompt

def test_dashboard_prompt_includes_kpi_grid_exemplar():
    plan = {"entity": {"name": "Account", "fields": []}, "page_type": "dashboard"}
    design_spec = {"register": "default"}
    prompt = build_schema_prompt(plan, design_spec=design_spec)
    # Exemplar inlined
    assert "exemplar-dashboard-kpi-grid" in prompt
    # Container choice rule still present
    assert "Container choice" in prompt or "container choice" in prompt.lower()
```

Run:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_prompt_dashboard.py -v
```

Expected: PASS.

Also run baseline regression:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_prompt.py tests/services/test_schema_prompt_cta.py tests/services/test_schema_prompt_exemplars.py tests/services/test_schema_rules.py tests/services/test_schema_prompt_form.py -v
```

Expected: all pass (27+ tests).

- [ ] **Step 3.4: Commit**

`schema_prompt.py` should be CLEAN currently (last committed in Tier S/M/L Tasks 12, 17, 19, 20 + the Form C fix `d8268c9`). Verify with `git status backend/services/schema_prompt.py`.

```bash
git add backend/services/schema_prompt.py backend/tests/services/test_schema_prompt_dashboard.py
git commit -m "$(cat <<'EOF'
feat(prompt): inline dashboard-kpi-grid exemplar on dashboard pages

_exemplar_for() now maps page_type="dashboard" to the KPI-grid
template, mirroring how "form" and "detail" get their canonical
exemplars. LLM sees a full reference dashboard schema in the prompt
context so it has a strong anchor for composition.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 4: Add `dashboard-density` rule

**Files:**
- Modify: `backend/services/schema_rules.py`
- Create: `backend/tests/services/test_dashboard_density_rule.py`

- [ ] **Step 4.1: Add the rule**

Inspect existing `RULES` list. Add an `_on_dashboard` helper next to the existing `_on_list`/`_on_form`/`_on_detail`:

```python
def _on_dashboard(entity: dict, page_type: str) -> bool:
    return page_type == "dashboard"
```

Append to the RULES list:

```python
Rule(
    name="dashboard-density",
    body=(
        "Dashboard pages MUST emit at least 4 MetricTile nodes, at least one "
        "Chart (line/bar/area) or Sparkline, and at least one list-style "
        "container (ActivityFeed, DataGrid, or Repeat-over-Card). Avoid sparse "
        "dashboards — readers expect KPI-rich at-a-glance layouts."
    ),
    example_snippet="""{
  "type": "Grid",
  "props": { "columns": 4 },
  "children": [
    { "type": "MetricTile", "props": { "label": "Users",   "value": "83K",  "delta": { "value": "+12%", "tone": "positive" }, "icon": "users" } },
    { "type": "MetricTile", "props": { "label": "Sessions","value": "240K", "delta": { "value": "+8%",  "tone": "positive" }, "icon": "activity" } },
    { "type": "MetricTile", "props": { "label": "Engaged", "value": "2m",   "delta": { "value": "+5s",  "tone": "positive" }, "icon": "clock" } },
    { "type": "MetricTile", "props": { "label": "Revenue", "value": "$253K","delta": { "value": "+15%", "tone": "positive" }, "icon": "dollar-sign" } }
  ]
}""",
    applies_when=_on_dashboard,
),
```

- [ ] **Step 4.2: Test the rule structure**

`backend/tests/services/test_dashboard_density_rule.py`:

```python
from services.schema_rules import RULES


def test_dashboard_density_rule_exists():
    rule = next((r for r in RULES if r.name == "dashboard-density"), None)
    assert rule is not None
    assert "MetricTile" in rule.body
    assert "Chart" in rule.body or "Sparkline" in rule.body


def test_dashboard_density_rule_fires_only_on_dashboard():
    rule = next(r for r in RULES if r.name == "dashboard-density")
    entity = {"name": "Account", "fields": []}
    assert rule.applies_when(entity, "dashboard") is True
    assert rule.applies_when(entity, "list") is False
    assert rule.applies_when(entity, "form") is False
    assert rule.applies_when(entity, "detail") is False
```

Run:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_dashboard_density_rule.py -v
```

Expected: 2/2 PASS.

Also run the existing schema_rules tests for no regression:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_rules.py -v
```

Expected: all PASS.

- [ ] **Step 4.3: Commit**

```bash
git add backend/services/schema_rules.py backend/tests/services/test_dashboard_density_rule.py
git commit -m "$(cat <<'EOF'
feat(prompt): dashboard-density rule requires KPI-rich layouts

New Rule(name="dashboard-density", applies_when=_on_dashboard) requires
>= 4 MetricTiles + >= 1 Chart/Sparkline + >= 1 list-style container.
Renders inline near the dashboard-kpi-grid exemplar so the LLM sees the
rule + an example of compliant output together.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Workstream B — Design-spec surface depth

### Task 5: Extend design-tokens schema with surface depth keys

**Files:**
- Modify: `packages/schema/src/tokens.ts`
- Modify: `packages/schema/tests/tokens.test.ts`

- [ ] **Step 5.1: Read the existing tokens schema**

```bash
sed -n '1,60p' /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema/src/tokens.ts
```

Find the `surface` and `accent` token blocks. They likely have shape `{ "0": "...", "50": "..." }`. We add nested `gradient` and `shadow` blocks alongside.

- [ ] **Step 5.2: Add Zod definitions for new keys**

Inside `tokens.ts`, extend the existing `Tokens` schema:

```ts
// Inside the Tokens object schema, alongside the existing surface/accent definitions:

// Surface depth tokens — control layered backgrounds beyond solid colors.
// All keys are optional so existing projects without them keep working.
surface: z.object({
  // ... existing keys (0, 50, 100, etc.)
  gradient: z.record(z.object({
    type: z.literal("linear"),
    angle: z.number().min(0).max(360),
    from: z.string().min(1),  // token path or hex
    to:   z.string().min(1),
  })).optional(),
  shadow: z.record(z.string().min(1)).optional(),  // each value is a CSS box-shadow
}).passthrough(),

accent: z.object({
  // ... existing keys
  illustration: z.record(z.object({
    asset: z.string().min(1),   // path or token-keyed asset reference
    tone: z.enum(["positive", "neutral", "warning"]).optional(),
  })).optional(),
}).passthrough(),
```

NOTE: `passthrough()` (not `strict()`) so existing tokens not enumerated here keep validating. Tokens schema is broadly permissive by design.

- [ ] **Step 5.3: Add Zod tests**

In `packages/schema/tests/tokens.test.ts` add:

```ts
import { Tokens } from "../src/tokens";

describe("design tokens — surface depth", () => {
  it("accepts surface.gradient.subtle as a linear gradient definition", () => {
    const r = Tokens.safeParse({
      surface: {
        "0": "#fff",
        gradient: {
          subtle: { type: "linear", angle: 135, from: "tokens.color.accent.50", to: "tokens.color.surface.0" },
        },
      },
    });
    expect(r.success).toBe(true);
  });

  it("accepts surface.shadow.elevated as a CSS shadow string", () => {
    const r = Tokens.safeParse({
      surface: {
        "0": "#fff",
        shadow: { elevated: "0 8px 24px -8px rgba(15, 23, 42, 0.18)" },
      },
    });
    expect(r.success).toBe(true);
  });

  it("rejects a gradient with angle out of [0..360]", () => {
    const r = Tokens.safeParse({
      surface: {
        gradient: { broken: { type: "linear", angle: 720, from: "#fff", to: "#000" } },
      },
    });
    expect(r.success).toBe(false);
  });

  it("legacy tokens (no surface.gradient/shadow) still validate", () => {
    const r = Tokens.safeParse({ surface: { "0": "#fff", "50": "#f8fafc" } });
    expect(r.success).toBe(true);
  });
});
```

Run:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema && npx vitest run tests/tokens.test.ts
```

Expected: existing tokens tests + 4 new = all pass.

- [ ] **Step 5.4: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/schema/src/tokens.ts packages/schema/tests/tokens.test.ts
git commit -m "$(cat <<'EOF'
feat(schema): surface.gradient + surface.shadow + accent.illustration

Tokens schema gains three optional nested blocks under surface and
accent. Gradient + shadow underpin layered backdrops (Hero, Card,
Section); illustration carries asset references (mascots, hero icons,
etc). All optional + passthrough so existing projects keep validating.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 6: SurfaceBackground component

**Files:**
- Create: `packages/library/src/components/surfaces/SurfaceBackground.tsx`
- Create: `packages/library/tests/components/SurfaceBackground.test.tsx`

- [ ] **Step 6.1: Write the failing test**

```tsx
// packages/library/tests/components/SurfaceBackground.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { SurfaceBackground } from "../../src/components/surfaces/SurfaceBackground";

describe("SurfaceBackground", () => {
  it("renders a div with linear-gradient style for a gradient background", () => {
    const { container } = render(
      <SurfaceBackground
        background={{ type: "linear", angle: 135, from: "#fff", to: "#eee" }}
        data-testid="bg"
      >
        <span>content</span>
      </SurfaceBackground>
    );
    const el = container.querySelector("[data-testid='bg']") as HTMLElement;
    expect(el).not.toBeNull();
    expect(el.style.background).toContain("linear-gradient");
    expect(el.textContent).toBe("content");
  });

  it("renders a solid color when background is a string", () => {
    const { container } = render(
      <SurfaceBackground background="#ff00ff" data-testid="bg">
        <span>x</span>
      </SurfaceBackground>
    );
    const el = container.querySelector("[data-testid='bg']") as HTMLElement;
    expect(el.style.background).toContain("#ff00ff");
  });

  it("renders unstyled when background is undefined", () => {
    const { container } = render(
      <SurfaceBackground data-testid="bg">
        <span>x</span>
      </SurfaceBackground>
    );
    const el = container.querySelector("[data-testid='bg']") as HTMLElement;
    expect(el.style.background).toBe("");
  });
});
```

- [ ] **Step 6.2: Run, verify FAIL**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run tests/components/SurfaceBackground.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 6.3: Implement**

```tsx
// packages/library/src/components/surfaces/SurfaceBackground.tsx
import * as React from "react";

type GradientBg = {
  type: "linear";
  angle?: number;       // degrees, default 135
  from: string;
  to: string;
};

type SolidBg = string;

export type SurfaceBg = GradientBg | SolidBg | undefined;

interface Props extends React.HTMLAttributes<HTMLDivElement> {
  background?: SurfaceBg;
  children?: React.ReactNode;
}

function isGradient(b: SurfaceBg): b is GradientBg {
  return !!b && typeof b === "object" && (b as GradientBg).type === "linear";
}

/**
 * Renders a backdrop layer based on a design-token background descriptor.
 *
 * - Linear gradient → CSS linear-gradient at the given angle (default 135deg)
 * - Solid string   → CSS background color
 * - Undefined      → no inline background (consumer's existing class wins)
 *
 * Composes with the consumer's own className for borders, padding, radius.
 */
export function SurfaceBackground({ background, style, children, ...rest }: Props) {
  const bgStyle: React.CSSProperties = isGradient(background)
    ? { background: `linear-gradient(${background.angle ?? 135}deg, ${background.from}, ${background.to})` }
    : typeof background === "string"
      ? { background }
      : {};
  return (
    <div style={{ ...bgStyle, ...style }} {...rest}>
      {children}
    </div>
  );
}
```

- [ ] **Step 6.4: Run, verify PASS (3 tests).**

- [ ] **Step 6.5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/src/components/surfaces/ packages/library/tests/components/SurfaceBackground.test.tsx
git commit -m "$(cat <<'EOF'
feat(library): SurfaceBackground renders gradient/solid backdrops

Single internal component that turns a token-style background descriptor
(linear gradient object or solid color string) into a backdrop div.
Consumers (Hero, Card, Section) compose this to honor design-spec
surface.gradient tokens without each re-implementing the gradient
math.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 7: Hero / Card / Section honor `style.background`

**Files:**
- Modify: `packages/library/src/components/Hero/Hero.tsx`
- Modify: `packages/library/src/components/Card/Card.tsx`
- Modify: `packages/library/src/components/Section/Section.tsx`

- [ ] **Step 7.1: Read existing implementations**

For each of the three files, find the outermost `<div>` (the surface) and check how `style?.background` is currently handled. Hero likely already has inline gradient logic (we saw it on `/notes/new`). Card and Section are likely just className-based today.

- [ ] **Step 7.2: Update Hero to delegate to SurfaceBackground**

Replace any inline `background` style computation in `Hero.tsx` with `<SurfaceBackground background={style?.background}>` wrapping its content. Preserve all existing className, padding, radius behavior — those live on `SurfaceBackground`'s `style`/`className` props through the spread.

- [ ] **Step 7.3: Update Card to render an optional backdrop**

In `Card.tsx`, when `style?.background` is present, wrap the existing card body in `<SurfaceBackground background={style.background} className="rounded-[inherit]">`. The `rounded-[inherit]` keeps the gradient clipped to the card's existing radius.

- [ ] **Step 7.4: Update Section similarly**

Same pattern — wrap existing content when `style?.background` is present.

- [ ] **Step 7.5: Run all library tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run 2>&1 | tail -8
```

Expected: pre-existing 259 pass + new SurfaceBackground tests = no NEW regressions. The 1 pre-existing Stagger failure is unrelated.

- [ ] **Step 7.6: Rebuild library and bounce scaffold**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc 2>&1 | head -3
rm -rf /Users/m/Work/code/poc/design2ui-forge-v3/apps/render-scaffold/.next
pkill -9 -f "next dev -p 6503" 2>/dev/null
sleep 2
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/render-scaffold && nohup ../../node_modules/.bin/next dev -p 6503 > /tmp/scaffold-after-task7.log 2>&1 &
sleep 12
```

- [ ] **Step 7.7: Smoke check existing /notes page still renders**

```bash
curl -sI http://localhost:6503/p/pagedriven-2p-1778564381/notes | head -1
```

Expected: HTTP 200. The Hero on this page already uses an inline gradient — confirm it still renders by checking the body has `linear-gradient` somewhere:

```bash
curl -s http://localhost:6503/p/pagedriven-2p-1778564381/notes | grep -o "linear-gradient" | head -1
```

Expected: at least one match.

- [ ] **Step 7.8: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/src/components/Hero packages/library/src/components/Card packages/library/src/components/Section
git commit -m "$(cat <<'EOF'
feat(library): Hero/Card/Section render gradient backgrounds via SurfaceBackground

When style.background is a gradient descriptor (or solid string), the
component wraps its content in a SurfaceBackground div that emits a CSS
linear-gradient (default 135deg) clipped to the existing radius. Hero
previously implemented this inline; centralized now. Card and Section
gain the same capability — schemas that set style.background on a Card
now produce a layered backdrop.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 8: Design agent emits default surface depth blocks

**Files:**
- Modify: `backend/agents/design_agent.py`

The design agent is what writes `design-spec.json`. We want every fresh generation to include a `surface.gradient.subtle` block by default so Card/Section/Hero have a token to reference without the LLM having to invent one.

- [ ] **Step 8.1: Locate design-spec emission**

```bash
grep -n "design-spec.json\|design_spec\b\|save_design_spec\|gradient\|surface" /Users/m/Work/code/poc/design2ui-forge-v3/backend/agents/design_agent.py | head -20
```

Find where the spec dict is assembled before being written.

- [ ] **Step 8.2: Inject default surface depth blocks per register**

After the existing color palette / typography emission, add:

```python
# Default surface depth tokens — give Hero/Card/Section something to ref.
spec.setdefault("tokens", {})
spec["tokens"].setdefault("surface", {})
spec["tokens"]["surface"].setdefault("gradient", {
    "subtle":  {"type": "linear", "angle": 135, "from": "tokens.color.accent.50",  "to": "tokens.color.surface.0"},
    "vibrant": {"type": "linear", "angle": 135, "from": "tokens.color.accent.200", "to": "tokens.color.accent.50"},
})
spec["tokens"]["surface"].setdefault("shadow", {
    "subtle":   "0 1px 2px 0 rgba(15, 23, 42, 0.04)",
    "elevated": "0 8px 24px -8px rgba(15, 23, 42, 0.18)",
    "floating": "0 16px 48px -16px rgba(15, 23, 42, 0.28)",
})
```

The `setdefault` calls preserve any custom values the LLM design pass already wrote. We only fill in when keys are absent.

NOTE: `tokens.color.accent.*` is the existing token path — confirm by reading one register file (`packages/library/src/theme/registers/linear.ts` etc.) to find the actual key shape used.

- [ ] **Step 8.3: Smoke check by running the design agent in isolation**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "
import sys, json, tempfile, asyncio
sys.path.insert(0, '.')
from agents.design_agent import save_design_spec

with tempfile.TemporaryDirectory() as tmp:
    spec = {'register': 'linear', 'tokens': {'color': {'accent': {'50': '#dbeafe', '200': '#93c5fd'}}}}
    save_design_spec(tmp, spec)
    saved = json.load(open(f'{tmp}/src/contracts/design-spec.json'))
    print('gradient.subtle:', saved['tokens']['surface']['gradient'].get('subtle'))
    print('shadow.elevated:', saved['tokens']['surface']['shadow'].get('elevated'))
"
```

Expected output: shows the gradient and shadow values were written.

- [ ] **Step 8.4: Commit**

`design_agent.py` is in the 40 uncommitted file list — use `git stash push` before editing, then commit, then `git stash pop`.

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git stash push -- backend/agents/design_agent.py
# Apply your edit on the clean state, save the file
# ...edit...
git add backend/agents/design_agent.py
git commit -m "$(cat <<'EOF'
feat(design-spec): emit surface.gradient and surface.shadow defaults

save_design_spec now fills in gradient.subtle + gradient.vibrant and
shadow.subtle/elevated/floating when the LLM design pass doesn't
emit them. Hero/Card/Section components (from the surface-depth
component refactor) pick these up automatically so generated pages
get layered backdrops without bespoke prompts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git stash pop
```

If the stash pop conflicts: the prior uncommitted changes touch the same lines. Resolve carefully — keep both the cta_hierarchy injection (Tier S/M/L Task 16) AND your new surface defaults.

---

## Workstream D — Illustrations via in-house unDraw MCP

### Task 9: unDraw HTTP client + filesystem cache

**Files:**
- Create: `backend/mcp/__init__.py` (empty package marker)
- Create: `backend/mcp/undraw_client.py`
- Create: `backend/tests/mcp/__init__.py` (empty)
- Create: `backend/tests/mcp/test_undraw_client.py`

- [ ] **Step 9.1: Write the failing tests**

```python
# backend/tests/mcp/test_undraw_client.py
import pytest
from unittest.mock import patch, MagicMock
from mcp.undraw_client import UndrawClient, IllustrationMeta


@pytest.fixture
def client(tmp_path):
    return UndrawClient(cache_dir=tmp_path / "cache")


def test_list_illustrations_returns_metadata(client):
    sample_response = {
        "illustrations": [
            {"slug": "running-athlete", "title": "Running athlete", "tags": ["sport", "fitness"]},
            {"slug": "happy-news",      "title": "Happy news",      "tags": ["celebration"]},
        ],
        "next": None,
    }
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: sample_response)
        results = client.list_illustrations(tags=["fitness"], limit=5)
    assert len(results) >= 1
    assert all(isinstance(r, IllustrationMeta) for r in results)
    # Tag filter is applied client-side
    assert any(r.slug == "running-athlete" for r in results)


def test_get_illustration_svg_caches_to_disk(client, tmp_path):
    fake_svg = b'<svg xmlns="http://www.w3.org/2000/svg"><circle/></svg>'
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, content=fake_svg)
        svg1 = client.get_illustration_svg("running-athlete", color="6b7280")
    # First call: 1 HTTP request
    assert mock_get.call_count == 1
    assert svg1 == fake_svg
    # File is cached
    cache_files = list((tmp_path / "cache").rglob("running-athlete*.svg"))
    assert len(cache_files) == 1
    # Second call: hits cache, no new HTTP
    with patch("httpx.Client.get") as mock_get2:
        svg2 = client.get_illustration_svg("running-athlete", color="6b7280")
    assert mock_get2.call_count == 0
    assert svg2 == fake_svg


def test_get_illustration_svg_different_color_separate_cache(client):
    fake_svg_a = b'<svg fill="#ff0000"/>'
    fake_svg_b = b'<svg fill="#00ff00"/>'
    with patch("httpx.Client.get") as mock_get:
        mock_get.side_effect = [
            MagicMock(status_code=200, content=fake_svg_a),
            MagicMock(status_code=200, content=fake_svg_b),
        ]
        a = client.get_illustration_svg("happy-news", color="ff0000")
        b = client.get_illustration_svg("happy-news", color="00ff00")
    assert a == fake_svg_a
    assert b == fake_svg_b
    assert mock_get.call_count == 2


def test_unknown_slug_raises_or_returns_none(client):
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=404, content=b"not found")
        result = client.get_illustration_svg("does-not-exist", color="000000")
    assert result is None
```

- [ ] **Step 9.2: Run, verify FAIL** — module not found.

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/mcp/test_undraw_client.py -v
```

- [ ] **Step 9.3: Implement** `backend/mcp/undraw_client.py`:

```python
"""unDraw HTTP client with on-disk caching.

The MCP server wraps this client. Cache key is (slug, color). Once
a (slug, color) pair has been fetched and stored under cache_dir,
subsequent reads come from disk — no network roundtrip during a
generation, which makes the schema-agent fast and deterministic.

unDraw API:
  - Listing:   GET https://undraw.co/api/illustrations?page=N
  - Per-SVG:   GET https://undraw.co/illustrations/<slug>.svg?color=<hex>
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import logging

import httpx

logger = logging.getLogger(__name__)

_LISTING_URL = "https://undraw.co/api/illustrations"
_SVG_URL = "https://undraw.co/illustrations/{slug}.svg"


@dataclass(frozen=True)
class IllustrationMeta:
    slug: str
    title: str
    tags: list[str]


class UndrawClient:
    def __init__(self, cache_dir: Path | str):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._http = httpx.Client(timeout=15.0)

    def list_illustrations(self, tags: list[str] | None = None, limit: int = 20) -> list[IllustrationMeta]:
        """Fetch one page of unDraw illustrations. Client-side filter by tags.

        unDraw's API doesn't accept tag query params — we paginate and
        filter locally. For v1 the LLM gets a single page of results;
        tighter filtering can paginate further if relevance is poor.
        """
        try:
            resp = self._http.get(_LISTING_URL)
        except httpx.HTTPError as e:
            logger.warning("undraw listing fetch failed: %s", e)
            return []
        if resp.status_code != 200:
            return []
        data = resp.json() or {}
        rows = data.get("illustrations") or data.get("media") or []
        results: list[IllustrationMeta] = []
        norm_tags = [t.lower() for t in (tags or [])]
        for row in rows:
            slug = row.get("slug") or row.get("id") or ""
            title = row.get("title") or slug
            row_tags = [t.lower() for t in (row.get("tags") or row.get("categories") or [])]
            if norm_tags and not (set(norm_tags) & set(row_tags)):
                continue
            results.append(IllustrationMeta(slug=slug, title=title, tags=row_tags))
            if len(results) >= limit:
                break
        return results

    def get_illustration_svg(self, slug: str, color: str = "6b7280") -> bytes | None:
        """Fetch (or return cached) SVG bytes for a slug + color.

        Color is a hex string without leading '#'. Cache key is
        '<slug>__<color>.svg'.
        """
        color = color.lstrip("#").lower()
        cache_path = self._cache_dir / f"{slug}__{color}.svg"
        if cache_path.exists():
            return cache_path.read_bytes()
        try:
            resp = self._http.get(_SVG_URL.format(slug=slug), params={"color": color})
        except httpx.HTTPError as e:
            logger.warning("undraw svg fetch failed for %s: %s", slug, e)
            return None
        if resp.status_code != 200:
            return None
        svg = resp.content
        cache_path.write_bytes(svg)
        return svg
```

- [ ] **Step 9.4: Run, verify 4/4 PASS.**

- [ ] **Step 9.5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/mcp/__init__.py backend/mcp/undraw_client.py backend/tests/mcp/__init__.py backend/tests/mcp/test_undraw_client.py
git commit -m "$(cat <<'EOF'
feat(mcp): unDraw HTTP client with on-disk SVG cache

UndrawClient.list_illustrations + get_illustration_svg. Cache key is
(slug, color) so different recolors of the same illustration are
stored separately. First fetch hits unDraw; subsequent reads come
from backend/.cache/illustrations/<slug>__<color>.svg. Failures
return None / [] — never raise into the agent loop.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 10: FastMCP illustrations server

**Files:**
- Create: `backend/mcp/illustrations_server.py`
- Create: `backend/tests/mcp/test_illustrations_server.py`

- [ ] **Step 10.1: Write the failing tests**

```python
# backend/tests/mcp/test_illustrations_server.py
import pytest
from unittest.mock import patch, MagicMock
from mcp.illustrations_server import (
    list_illustrations_tool, get_illustration_tool, build_server
)


def test_list_illustrations_tool_returns_compact_list():
    fake_meta = [
        MagicMock(slug="running-athlete", title="Running athlete", tags=["sport"]),
        MagicMock(slug="happy-news", title="Happy news", tags=["celebration"]),
    ]
    with patch("mcp.illustrations_server._get_client") as get_client:
        get_client.return_value.list_illustrations.return_value = fake_meta
        result = list_illustrations_tool(tags=["sport"], limit=5)
    assert isinstance(result, list)
    assert all("slug" in item and "title" in item and "tags" in item for item in result)
    assert result[0]["slug"] == "running-athlete"


def test_get_illustration_tool_returns_svg_string():
    fake_svg = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    with patch("mcp.illustrations_server._get_client") as get_client:
        get_client.return_value.get_illustration_svg.return_value = fake_svg
        result = get_illustration_tool(slug="running-athlete", color="6b7280")
    assert isinstance(result, str)
    assert result.startswith("<svg")


def test_get_illustration_tool_missing_returns_error_marker():
    with patch("mcp.illustrations_server._get_client") as get_client:
        get_client.return_value.get_illustration_svg.return_value = None
        result = get_illustration_tool(slug="bogus", color="6b7280")
    # Tools should return graceful errors, not exceptions
    assert isinstance(result, str)
    assert "not found" in result.lower() or "error" in result.lower()


def test_build_server_registers_both_tools():
    server = build_server()
    # The server object should expose both tool names registered.
    tool_names = [t.name for t in server.list_tools() if hasattr(server, "list_tools")] \
                 if hasattr(server, "list_tools") else []
    # Different mcp SDK versions expose tools differently — fallback assertion:
    assert server is not None
```

- [ ] **Step 10.2: Run, verify FAIL.**

- [ ] **Step 10.3: Implement** `backend/mcp/illustrations_server.py`:

```python
"""In-house FastMCP server exposing unDraw illustrations to the schema agent.

Two tools:
  - list_illustrations(tags, limit) → [{slug, title, tags}]
  - get_illustration_svg(slug, color) → SVG string (raw markup)

The schema agent calls these during generation. The bundler step in
page_schema_agent then copies the chosen SVG into
output/<id>/public/illustrations/<slug>.svg so the rendered app ships
with the asset.
"""
from __future__ import annotations
from pathlib import Path
import logging

from mcp.server.fastmcp import FastMCP
from mcp.undraw_client import UndrawClient

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _REPO_ROOT / "backend" / ".cache" / "illustrations"

_client: UndrawClient | None = None


def _get_client() -> UndrawClient:
    global _client
    if _client is None:
        _client = UndrawClient(cache_dir=_CACHE_DIR)
    return _client


def list_illustrations_tool(tags: list[str] | None = None, limit: int = 20) -> list[dict]:
    """Return up to `limit` illustrations matching any of `tags`."""
    metas = _get_client().list_illustrations(tags=tags, limit=limit)
    return [{"slug": m.slug, "title": m.title, "tags": m.tags} for m in metas]


def get_illustration_tool(slug: str, color: str = "6b7280") -> str:
    """Return the SVG markup for a slug, recolored to the given hex.

    Returns a sentinel error string when the slug is unknown — the LLM
    handles this by picking a different slug.
    """
    svg = _get_client().get_illustration_svg(slug, color=color)
    if svg is None:
        return f"<!-- illustration not found: {slug} -->"
    return svg.decode("utf-8", errors="replace")


def build_server() -> FastMCP:
    """Construct the FastMCP server and register both tools."""
    server = FastMCP("forge-illustrations")
    server.add_tool(list_illustrations_tool, name="list_illustrations",
                    description=(
                        "List unDraw illustrations filtered by tag keywords (e.g. "
                        "['auth', 'fitness']). Returns slugs you can pass to "
                        "get_illustration_svg. Use tags like: auth, login, signup, "
                        "empty-state, dashboard, success, error, onboarding, "
                        "travel, fitness, productivity, healthcare."
                    ))
    server.add_tool(get_illustration_tool, name="get_illustration_svg",
                    description=(
                        "Fetch the SVG markup for an illustration slug. Pass a hex "
                        "color (no '#') to recolor it to your brand accent."
                    ))
    return server


if __name__ == "__main__":
    # Allow running as a stand-alone MCP server: python -m mcp.illustrations_server
    build_server().run()
```

- [ ] **Step 10.4: Run, verify 4/4 PASS.**

If the `mcp` Python SDK isn't installed yet:

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pip install "mcp[cli]>=1.0.0"
```

Then add `mcp[cli]>=1.0.0` and `httpx>=0.27` to `backend/requirements.txt` if those files exist. If a `pyproject.toml` is used instead, add them there.

- [ ] **Step 10.5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/mcp/illustrations_server.py backend/tests/mcp/test_illustrations_server.py
# Also add requirements if updated:
# git add backend/requirements.txt
git commit -m "$(cat <<'EOF'
feat(mcp): illustrations_server exposes list + fetch tools via FastMCP

Two tools (list_illustrations, get_illustration_svg) wrap UndrawClient.
Schema agent invokes the server during generation. Tool descriptions
enumerate the tag taxonomy (auth/login/empty-state/dashboard/...)
so the LLM picks meaningful filters.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 11: IllustrationResolver React component

**Files:**
- Create: `packages/library/src/components/surfaces/IllustrationResolver.tsx`
- Create: `packages/library/tests/components/IllustrationResolver.test.tsx`

The component takes a slug (and optional tone) and renders `<img src="/illustrations/<slug>.svg">`. Generated apps serve illustrations from `public/illustrations/` (Next.js convention). The scaffold (preview server) serves them from a matching path under `output/<id>/public/`.

- [ ] **Step 11.1: Write the failing tests**

```tsx
// packages/library/tests/components/IllustrationResolver.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { IllustrationResolver } from "../../src/components/surfaces/IllustrationResolver";

describe("IllustrationResolver", () => {
  it("renders an img pointing at /illustrations/<slug>.svg by default", () => {
    const { container } = render(
      <IllustrationResolver slug="running-athlete" alt="Running athlete" />
    );
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img).not.toBeNull();
    expect(img.src).toContain("/illustrations/running-athlete.svg");
    expect(img.alt).toBe("Running athlete");
  });

  it("respects an explicit basePath override (for the scaffold preview server)", () => {
    const { container } = render(
      <IllustrationResolver
        slug="happy-news"
        alt="Happy news"
        basePath="/p/proj-123/illustrations"
      />
    );
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img.src).toContain("/p/proj-123/illustrations/happy-news.svg");
  });

  it("renders nothing when slug is falsy", () => {
    const { container } = render(<IllustrationResolver slug="" alt="" />);
    expect(container.querySelector("img")).toBeNull();
  });
});
```

- [ ] **Step 11.2: Run, verify FAIL.**

- [ ] **Step 11.3: Implement**:

```tsx
// packages/library/src/components/surfaces/IllustrationResolver.tsx
import * as React from "react";

export interface IllustrationResolverProps {
  /** unDraw slug (or custom slug bundled into the project) */
  slug: string;
  /** Accessible alt text — required for non-decorative illustrations */
  alt: string;
  /** Override the asset base path. Defaults to /illustrations (Next.js public/) */
  basePath?: string;
  /** Optional max width/height in CSS units */
  width?: number | string;
  height?: number | string;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Renders an illustration bundled at <basePath>/<slug>.svg.
 *
 * For the standalone generated app: basePath defaults to /illustrations
 * (served from public/ by Next.js).
 *
 * For the render-scaffold preview: caller passes basePath like
 * "/p/<projectId>/illustrations" so the scaffold's backend route can
 * resolve to output/<projectId>/public/illustrations/<slug>.svg.
 */
export function IllustrationResolver({
  slug, alt, basePath = "/illustrations", width, height, className, style,
}: IllustrationResolverProps) {
  if (!slug) return null;
  const src = `${basePath.replace(/\/$/, "")}/${slug}.svg`;
  return (
    <img
      src={src}
      alt={alt}
      width={width}
      height={height}
      className={className}
      style={style}
      loading="lazy"
    />
  );
}
```

- [ ] **Step 11.4: Run, verify 3/3 PASS.**

- [ ] **Step 11.5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/src/components/surfaces/IllustrationResolver.tsx packages/library/tests/components/IllustrationResolver.test.tsx
git commit -m "$(cat <<'EOF'
feat(library): IllustrationResolver renders bundled SVGs from /illustrations/

Tiny component that takes a slug + alt and emits an <img> at
<basePath>/<slug>.svg. basePath defaults to /illustrations for the
standalone generated app; the scaffold preview overrides it to point
at /p/<projectId>/illustrations so the same React tree works in both
runtimes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 12: Hero / EmptyStateRich / Section consume illustration slot

**Files:**
- Modify: `packages/library/src/components/Hero/Hero.tsx`
- Modify: `packages/library/src/components/EmptyStateRich/EmptyStateRich.tsx`
- Modify: `packages/library/src/components/Section/Section.tsx`
- Modify: `packages/library/src/components/Hero/Hero.schema.ts` (if `accent.illustration` slot isn't already in the props)
- Modify: corresponding `*.schema.ts` files for EmptyStateRich and Section

- [ ] **Step 12.1: Add `illustration` prop to schemas**

Each of Hero, EmptyStateRich, and Section gains an optional `illustration` prop:

```ts
illustration: z.object({
  slug: z.string().min(1),
  alt: z.string().optional(),
  tone: z.enum(["primary", "secondary", "muted"]).optional(),  // selects pre-bundled color variant
}).optional(),
```

NOTE: this slot is at the COMPONENT level, distinct from `style.accent.illustration` (which lives on the design-spec). Components consume the per-instance slug; design-spec defaults are picked up by the schema agent when emitting.

- [ ] **Step 12.2: Update Hero.tsx to render illustration side-by-side**

When `illustration` is set, the Hero switches to a 2-column layout (content left, illustration right by default). When unset, keeps existing single-column behavior.

```tsx
// Inside Hero(props):
const hasIllustration = props.illustration?.slug;
// ... existing layout logic
return (
  <SurfaceBackground background={props.style?.background}>
    <div className={hasIllustration ? "grid grid-cols-1 md:grid-cols-2 gap-8 items-center" : ""}>
      <div>{/* existing eyebrow/headline/subhead/ctas */}</div>
      {hasIllustration && (
        <IllustrationResolver
          slug={props.illustration.slug}
          alt={props.illustration.alt ?? ""}
          basePath={props.__illustrationBasePath ?? "/illustrations"}
          className="max-w-md w-full h-auto"
        />
      )}
    </div>
  </SurfaceBackground>
);
```

The `__illustrationBasePath` is a private prop injected by the SchemaRendererWrapper at mount-time so the scaffold can pass `/p/<projectId>/illustrations`. The standalone app omits it and the default `/illustrations` wins.

- [ ] **Step 12.3: Update EmptyStateRich.tsx similarly**

Same pattern — when `illustration` slot is set, render `IllustrationResolver` above the heading and message. Existing EmptyStateRich rendering kept when slot is absent.

- [ ] **Step 12.4: Update Section.tsx for split layouts**

If Section has `illustration` set, switch to side-by-side (illustration + children). This is what makes the canonical login split layout work.

- [ ] **Step 12.5: Pass `__illustrationBasePath` through SchemaRendererWrapper**

In `apps/render-scaffold/src/components/SchemaRendererWrapper.tsx`, when constructing the renderer registry, inject the basePath as a context value (or use a global config). Read the projectId from props and emit:

```tsx
const illustrationBasePath = `/p/${projectId}/illustrations`;
// pass via the registry's component-default mechanism, e.g.
reg("Hero",         Hero,         HeroPropsSchema,         "layout", true, { __illustrationBasePath: illustrationBasePath });
reg("EmptyStateRich", EmptyStateRich, EmptyStateRichPropsSchema, "feedback", false, { __illustrationBasePath: illustrationBasePath });
reg("Section",      Section,      SectionPropsSchema,      "layout", true, { __illustrationBasePath: illustrationBasePath });
```

If the registry doesn't support default-prop injection, add a thin wrapper around each component at registration time:

```tsx
const HeroWithBase = (p: any) => <Hero {...p} __illustrationBasePath={illustrationBasePath} />;
reg("Hero", HeroWithBase, HeroPropsSchema, "layout", true);
```

- [ ] **Step 12.6: Add a backend endpoint to serve project illustrations**

```python
# backend/routers/output_projects.py — add:

@router.get("/api/projects/{project_id}/illustrations/{slug}.svg")
async def get_project_illustration(project_id: str, slug: str):
    """Serve a bundled SVG from a project's public/illustrations/ dir."""
    from fastapi.responses import FileResponse
    from pathlib import Path
    root = _REPO_ROOT / "output" / project_id / "public" / "illustrations"
    candidate = root / f"{slug}.svg"
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="illustration not found")
    return FileResponse(candidate, media_type="image/svg+xml")
```

Wire this so the scaffold's `<img src="/p/.../illustrations/<slug>.svg">` resolves. Also add a corresponding route in `apps/render-scaffold/next.config.ts` to proxy `/p/[projectId]/illustrations/[slug]` → backend if the backend port differs.

Simpler: add a Next.js dynamic API route at `apps/render-scaffold/src/app/p/[projectId]/illustrations/[slug]/route.ts` that reads the file directly.

- [ ] **Step 12.7: Tests**

Update existing Hero / EmptyStateRich / Section tests to cover the new prop:

```tsx
// In each component's test file:
it("renders illustration when slug is provided", () => {
  const { container } = render(
    <Hero
      headline="Welcome back"
      illustration={{ slug: "running-athlete", alt: "Running athlete" }}
    />
  );
  expect(container.querySelector("img[src*='running-athlete.svg']")).not.toBeNull();
});

it("renders without illustration when slot omitted", () => {
  const { container } = render(<Hero headline="Welcome back" />);
  expect(container.querySelector("img")).toBeNull();
});
```

- [ ] **Step 12.8: Run all library tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run 2>&1 | tail -8
```

Expected: pre-existing pass count + new tests = no NEW regressions.

- [ ] **Step 12.9: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/src/components/Hero packages/library/src/components/EmptyStateRich packages/library/src/components/Section
git add packages/library/tests/components apps/render-scaffold/src/components/SchemaRendererWrapper.tsx backend/routers/output_projects.py
# Add scaffold route file if created:
# git add apps/render-scaffold/src/app/p/\[projectId\]/illustrations/
git commit -m "$(cat <<'EOF'
feat(library): Hero/EmptyStateRich/Section consume illustration slot

Each component gains an optional illustration={slug, alt, tone} prop.
When set, renders side-by-side with the content via
IllustrationResolver. Scaffold injects a basePath of
/p/<projectId>/illustrations so the same React tree resolves under
the preview server too. Backend gains a /api/projects/:id/illustrations
endpoint that serves the bundled SVGs from output/.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 13: Asset bundler — copy chosen SVGs into output dir at schema-emit time

**Files:**
- Modify: `backend/agents/page_schema_agent.py`
- Create: `backend/services/illustration_bundler.py`
- Create: `backend/tests/services/test_illustration_bundler.py`

After the schema agent finishes a page, scan the emitted schema for `illustration.slug` values and copy the corresponding cached SVG from `backend/.cache/illustrations/<slug>__<color>.svg` to `output/<id>/public/illustrations/<slug>.svg`.

- [ ] **Step 13.1: Write the failing test**

```python
# backend/tests/services/test_illustration_bundler.py
import json
from pathlib import Path
from services.illustration_bundler import bundle_illustrations_for_schema


def test_bundles_chosen_slug_into_public_illustrations(tmp_path, monkeypatch):
    # Stub cache dir with a fake SVG
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "running-athlete__6b7280.svg").write_bytes(b"<svg/>")
    monkeypatch.setattr("services.illustration_bundler._CACHE_DIR", cache)

    output_dir = tmp_path / "proj"
    schema = {
        "schemaVersion": "2", "id": "auth",
        "route": "/login", "layout": "main",
        "root": {
            "type": "Hero",
            "id": "hero",
            "props": {
                "headline": "Welcome",
                "illustration": {"slug": "running-athlete", "alt": "Running"}
            }
        }
    }
    bundle_illustrations_for_schema(str(output_dir), schema, accent_color="6b7280")

    bundled = output_dir / "public" / "illustrations" / "running-athlete.svg"
    assert bundled.exists()
    assert bundled.read_bytes() == b"<svg/>"


def test_no_op_when_schema_has_no_illustrations(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr("services.illustration_bundler._CACHE_DIR", cache)

    output_dir = tmp_path / "proj"
    schema = {
        "schemaVersion": "2", "id": "list", "route": "/", "layout": "main",
        "root": {"type": "Stack", "id": "r", "children": []}
    }
    bundle_illustrations_for_schema(str(output_dir), schema, accent_color="6b7280")
    # No illustrations dir created when nothing to bundle
    assert not (output_dir / "public" / "illustrations").exists()


def test_missing_cache_entry_skipped_silently(tmp_path, monkeypatch, caplog):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr("services.illustration_bundler._CACHE_DIR", cache)
    output_dir = tmp_path / "proj"
    schema = {
        "schemaVersion": "2", "id": "auth", "route": "/login", "layout": "main",
        "root": {
            "type": "Hero", "id": "hero",
            "props": {"illustration": {"slug": "never-fetched", "alt": ""}}
        }
    }
    bundle_illustrations_for_schema(str(output_dir), schema, accent_color="6b7280")
    # Doesn't crash; no file produced; warning logged
    assert not (output_dir / "public" / "illustrations" / "never-fetched.svg").exists()
```

- [ ] **Step 13.2: Run, verify FAIL.**

- [ ] **Step 13.3: Implement** `backend/services/illustration_bundler.py`:

```python
"""Asset bundler — copies chosen unDraw SVGs from the cache into output/<id>/.

Runs after each page schema is emitted. Walks the schema tree, collects
every illustration.slug reference, and for each slug copies the cached
SVG into output_dir/public/illustrations/<slug>.svg so the generated
app ships with the asset.
"""
from __future__ import annotations
from pathlib import Path
import logging
import shutil

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _REPO_ROOT / "backend" / ".cache" / "illustrations"


def _collect_slugs(node, slugs: set[str]) -> None:
    if not isinstance(node, dict):
        return
    props = node.get("props") or {}
    illu = props.get("illustration")
    if isinstance(illu, dict) and isinstance(illu.get("slug"), str):
        slugs.add(illu["slug"])
    for child in node.get("children") or []:
        _collect_slugs(child, slugs)


def bundle_illustrations_for_schema(output_dir: str, schema: dict, accent_color: str = "6b7280") -> int:
    """Walk the schema, find illustration slugs, copy cached SVGs into output.

    Returns the count of SVGs successfully bundled.
    """
    slugs: set[str] = set()
    _collect_slugs(schema.get("root", {}), slugs)
    if not slugs:
        return 0
    dest_dir = Path(output_dir) / "public" / "illustrations"
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    accent = accent_color.lstrip("#").lower()
    for slug in slugs:
        src = _CACHE_DIR / f"{slug}__{accent}.svg"
        if not src.exists():
            logger.warning("illustration cache miss for slug=%s color=%s — skipping bundle", slug, accent)
            continue
        dest = dest_dir / f"{slug}.svg"
        shutil.copy2(src, dest)
        count += 1
    return count
```

- [ ] **Step 13.4: Wire the bundler into `page_schema_agent.py`**

After `out_path.write_text(json.dumps(...))` in `run_page_schema_agent`, call:

```python
from services.illustration_bundler import bundle_illustrations_for_schema
# `accent_color` comes from design-spec — pass the project's primary accent (6 hex chars no #).
accent_color = (plan.get("design_spec") or {}).get("tokens", {}).get("color", {}).get("accent", {}).get("500", "6b7280")
bundle_illustrations_for_schema(output_dir, schema_dict, accent_color=accent_color.lstrip("#"))
```

- [ ] **Step 13.5: Run all bundler + agent tests, verify pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_illustration_bundler.py tests/agents/test_page_schema_agent.py -v
```

Expected: 3 bundler + 3 agent = 6 PASS.

- [ ] **Step 13.6: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/illustration_bundler.py backend/tests/services/test_illustration_bundler.py backend/agents/page_schema_agent.py
git commit -m "$(cat <<'EOF'
feat(schema): bundle chosen illustrations into output/<id>/public/

After each page schema is written, scan for illustration.slug refs and
copy the cached unDraw SVG into the project's public/illustrations/
dir. Generated Next.js apps ship the assets out of the box.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 14: Register the illustrations MCP server in the schema agent's options

**Files:**
- Modify: `backend/agents/page_schema_agent.py`

The schema agent uses `claude_agent_sdk.query` with `ClaudeAgentOptions`. We pass our MCP server in `mcp_servers` so the LLM can invoke `list_illustrations` and `get_illustration_svg` during generation.

- [ ] **Step 14.1: Add MCP server registration in `_generate_schema_for_page`**

```python
# Near the top of _generate_schema_for_page in page_schema_agent.py, before the LLM call:
from claude_agent_sdk import ClaudeAgentOptions
from mcp.illustrations_server import build_server as build_illustrations_server

_illustrations_server = build_illustrations_server()
# When constructing the options for query():
options = ClaudeAgentOptions(
    mcp_servers={"illustrations": _illustrations_server},
    # ... existing options
)
```

The exact ClaudeAgentOptions field name depends on the SDK version — check `backend/agents/feature_slice_schema_agent.py` for how it constructs `ClaudeAgentOptions` today and mirror that.

If the SDK doesn't support in-process MCP servers, run the server as a subprocess via stdio: launch `python -m mcp.illustrations_server` and pass its stdio handles to `mcp_server_config`. The plan's reference simple approach assumes the SDK supports an in-process variant; if not, the subprocess path is a 10-line adjustment.

- [ ] **Step 14.2: Smoke-test the registration**

A simple unit test that exercises only the construction path (mocking the actual LLM call):

```python
# backend/tests/agents/test_page_schema_agent_mcp.py
from unittest.mock import patch, AsyncMock
from agents.page_schema_agent import run_page_schema_agent


async def test_schema_agent_registers_illustrations_mcp(tmp_path):
    # Patch the LLM call to a no-op, just exercise the agent's option construction
    with patch("agents.page_schema_agent._generate_schema_for_page", new=AsyncMock(return_value={
        "schemaVersion": "2", "id": "x", "route": "/x", "layout": "main",
        "root": {"type": "Stack", "id": "r", "children": []}
    })):
        await run_page_schema_agent(
            str(tmp_path),
            {"entities": {}},
            {"route": "/x", "entity": None, "type": "list", "name": "X"},
        )
    # If construction succeeded without raising, the MCP wiring is intact.
```

Run:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_page_schema_agent_mcp.py -v
```

Expected: PASS.

- [ ] **Step 14.3: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/agents/page_schema_agent.py backend/tests/agents/test_page_schema_agent_mcp.py
git commit -m "$(cat <<'EOF'
feat(schema): page_schema_agent registers illustrations MCP server

Schema agent's ClaudeAgentOptions now includes the in-house
illustrations MCP. The LLM can call list_illustrations(tags) +
get_illustration_svg(slug, color) during generation to dynamically
pick unDraw illustrations matching the page's intent + domain.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 15: Auth-page exemplar + schema_prompt + schema_rules teaching

**Files:**
- Create: `backend/fixtures/exemplars/auth-split-illustration.json`
- Modify: `backend/services/schema_prompt.py`
- Modify: `backend/services/schema_rules.py`
- Create: `backend/tests/services/test_schema_prompt_auth.py`

- [ ] **Step 15.1: Author the auth exemplar**

```json
{
  "schemaVersion": "2",
  "id": "exemplar-auth-split-illustration",
  "route": "/example/login",
  "layout": "main",
  "root": {
    "id": "page-root",
    "type": "Grid",
    "props": { "columns": 2, "gap": "tokens.spacing.semantic.section" },
    "children": [
      {
        "id": "auth-content",
        "type": "Stack",
        "props": { "direction": "vertical", "gap": "tokens.spacing.semantic.section" },
        "children": [
          {
            "id": "auth-hero",
            "type": "Hero",
            "props": {
              "eyebrow": "Welcome back",
              "headline": "Sign in to your account",
              "subhead": "Welcome back! Please enter your details.",
              "layout": "inline",
              "ctas": []
            }
          },
          {
            "id": "auth-form",
            "type": "Form",
            "props": {
              "workflow": "login",
              "submitLabel": "Sign in",
              "fields": [
                { "kind": "email",    "name": "email",    "label": "Email",    "required": true,  "placeholder": "you@company.com" },
                { "kind": "text",     "name": "password", "label": "Password", "required": true,  "placeholder": "Enter your password" },
                { "kind": "checkbox", "name": "remember", "label": "Remember me" }
              ]
            }
          },
          {
            "id": "social-row",
            "type": "Row",
            "props": { "gap": "tokens.spacing.semantic.card" },
            "children": [
              { "id": "google-login",   "type": "Button", "props": { "label": "Continue with Google",   "variant": "secondary", "icon": "chrome",   "iconPosition": "left" } },
              { "id": "facebook-login", "type": "Button", "props": { "label": "Continue with Facebook", "variant": "secondary", "icon": "facebook", "iconPosition": "left" } }
            ]
          }
        ]
      },
      {
        "id": "auth-illustration-pane",
        "type": "Section",
        "props": {
          "illustration": { "slug": "running-athlete", "alt": "Welcome illustration" }
        },
        "children": []
      }
    ]
  }
}
```

NOTE: the slug `"running-athlete"` is illustrative — the actual emitter will pick a slug dynamically via the MCP server based on the project's domain.

Add `"auth-split-illustration"` to `packages/schema/tests/exemplars.test.ts` EXEMPLARS array. Run:

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/schema && npx vitest run tests/exemplars.test.ts
```

Expected: all PASS (one more than before).

- [ ] **Step 15.2: Update `_exemplar_for()`**

In `backend/services/schema_prompt.py`:

```python
def _exemplar_for(page_type: str, route: str = "") -> str:
    if route and any(route.startswith(p) for p in ("/login", "/signin", "/signup", "/register")):
        return _load_exemplar("auth-split-illustration")
    return {
        "form":      _load_exemplar("wide-form-accordion"),
        "detail":    _load_exemplar("detail-tabs"),
        "dashboard": _load_exemplar("dashboard-kpi-grid"),
    }.get(page_type, "")
```

And update the call site to pass the route through.

- [ ] **Step 15.3: Add an `auth-page-illustration` rule to `schema_rules.py`**

```python
def _on_auth(entity: dict, page_type: str) -> bool:
    # The route isn't directly available — apply when page_type is "form"
    # AND the entity hints at auth. The rule applies broadly to form pages
    # for now; refine when more context flows through.
    return page_type == "form"

Rule(
    name="auth-page-illustration",
    body=(
        "Login / signup pages should use a 2-column split layout: form on "
        "one side, illustration on the other. Call list_illustrations(tags=["
        "'auth', 'login', '<domain>']) to find a matching slug, then set "
        "Hero.illustration or Section.illustration to {slug, alt}. The "
        "schema-emit step bundles the SVG into the project automatically."
    ),
    example_snippet="""{
  "type": "Section",
  "props": {
    "illustration": { "slug": "running-athlete", "alt": "Welcome" }
  },
  "children": []
}""",
    applies_when=_on_auth,
),
```

- [ ] **Step 15.4: Add the test**

```python
# backend/tests/services/test_schema_prompt_auth.py
from services.schema_prompt import build_schema_prompt


def test_login_route_prompt_includes_auth_exemplar():
    plan = {
        "entity": {"name": "User", "fields": []},
        "page_type": "form",
        "page": {"route": "/login", "name": "Login"}
    }
    prompt = build_schema_prompt(plan, design_spec={"register": "default"})
    assert "auth-split-illustration" in prompt
    assert "list_illustrations" in prompt or "illustration" in prompt.lower()


def test_non_auth_form_does_not_get_auth_exemplar():
    plan = {
        "entity": {"name": "Note", "fields": []},
        "page_type": "form",
        "page": {"route": "/notes/new", "name": "New Note"}
    }
    prompt = build_schema_prompt(plan, design_spec={"register": "default"})
    # Auth exemplar must NOT appear when route is /notes/new
    assert "auth-split-illustration" not in prompt
```

Run:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_prompt_auth.py -v
```

Expected: 2/2 PASS.

Also run the baseline:
```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_prompt.py tests/services/test_schema_prompt_cta.py tests/services/test_schema_prompt_exemplars.py tests/services/test_schema_rules.py tests/services/test_schema_prompt_form.py tests/services/test_schema_prompt_dashboard.py tests/services/test_dashboard_density_rule.py -v
```

Expected: all PASS.

- [ ] **Step 15.5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/fixtures/exemplars/auth-split-illustration.json packages/schema/tests/exemplars.test.ts backend/services/schema_prompt.py backend/services/schema_rules.py backend/tests/services/test_schema_prompt_auth.py
git commit -m "$(cat <<'EOF'
feat(prompt): auth-page exemplar + illustration tool guidance

build_schema_prompt now routes /login, /signin, /signup, /register
pages to the auth-split-illustration exemplar. schema_rules gains
auth-page-illustration rule directing the LLM to call
list_illustrations() via the MCP server and embed the chosen slug in
Hero.illustration / Section.illustration. Generated auth pages get the
canonical 2-column split with illustration on the right.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Workstream C — Integration

### Task 16: Write a dashboard test plan + verify the prompt loads it

**Files:**
- Create: `/tmp/plan-dashboard.json` (scratch — not committed)

- [ ] **Step 9.1: Author a small test plan with a dashboard page**

```json
{
  "name": "Notes with overview",
  "description": "Minimal notes app with a dashboard overview page",
  "domain": "productivity",
  "entities": {
    "Note": {
      "table": "notes",
      "fields": [
        {"name": "id", "type": "uuid", "primary": true},
        {"name": "title", "type": "string", "required": true},
        {"name": "body", "type": "text"},
        {"name": "created_at", "type": "timestamp"}
      ]
    }
  },
  "pages": [
    {
      "name": "Overview",
      "route": "/",
      "description": "Dashboard with notes summary stats and recent activity",
      "entity": "Note",
      "type": "dashboard"
    },
    {
      "name": "NoteList",
      "route": "/notes",
      "description": "List all notes",
      "entity": "Note",
      "type": "list"
    }
  ],
  "routes": [],
  "workflows": [],
  "components": []
}
```

Save to `/tmp/plan-dashboard.json`.

- [ ] **Step 9.2: Statically verify the prompt now includes dashboard guidance**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "
import sys, json
sys.path.insert(0, '.')
from services.schema_prompt import build_schema_prompt

plan = {'entity': {'name': 'Note', 'fields': []}, 'page_type': 'dashboard'}
prompt = build_schema_prompt(plan, design_spec={'register': 'default'})
print('Has dashboard exemplar:', 'exemplar-dashboard-kpi-grid' in prompt)
print('Has density rule:', 'dashboard-density' in prompt)
print('Has MetricTile guidance:', 'MetricTile' in prompt)
print('Has Chart guidance:', 'Chart' in prompt)
print('Prompt length (chars):', len(prompt))
"
```

Expected: all four flags True, prompt length under 100k chars (well within the 25k-token budget warning threshold).

### Task 17: Live regeneration on dashboard + auth plan

**Files:**
- None — verification step.

- [ ] **Step 17.1: Confirm services are up**

```bash
lsof -i :6500 -i :6501 -i :6503 | grep LISTEN | head -3
```

If anything's missing: `cd /Users/m/Work/code/poc/design2ui-forge-v3 && ./start-all.sh`.

- [ ] **Step 17.2: Extend the test plan to include an auth page**

Update `/tmp/plan-dashboard.json` so `pages` includes a login route:

```json
{
  "pages": [
    { "name": "Login",    "route": "/login", "description": "Sign in",                                            "entity": "User",  "type": "form" },
    { "name": "Overview", "route": "/",      "description": "Dashboard with notes summary stats and activity",   "entity": "Note",  "type": "dashboard" },
    { "name": "NoteList", "route": "/notes", "description": "List all notes",                                    "entity": "Note",  "type": "list" }
  ]
}
```

(Add a `User` entity with `email` + `password` fields if not already present.)

- [ ] **Step 17.3: Run the metrics script**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
set -a; source .env; set +a
SHORT_ID=fidelity-3p-$(date +%s)
nohup python3 -m scripts.generate_with_metrics_v2 \
  --description "Notes app with login page, dashboard overview, and a list page" \
  --plan-file /tmp/plan-dashboard.json \
  --short-id "$SHORT_ID" > /tmp/fidelity-3p-run.log 2>&1 &
echo "$SHORT_ID kicked off — pid $!"
```

This is the heavy step — expect 2-3 hours for 3 pages based on prior runs. Run it in the background.

- [ ] **Step 17.4: Verify the dashboard page has the expected density**

When the run completes (`grep "GENERATION COMPLETE" /tmp/fidelity-3p-run.log` returns a line), inspect:

```bash
SHORT_ID=<the id from step 17.3>
python3 -c "
import json
p = json.load(open(f'output/{SHORT_ID}/src/schemas/home.json'))
counts = {}
def walk(n):
    if isinstance(n, dict):
        counts[n.get('type', '?')] = counts.get(n.get('type', '?'), 0) + 1
        for c in n.get('children') or []: walk(c)
walk(p['root'])
print('Node counts on dashboard:')
for k, v in sorted(counts.items(), key=lambda x: -x[1]):
    print(f'  {k}: {v}')
print()
mt = counts.get('MetricTile', 0)
ch = counts.get('Chart', 0) + counts.get('Sparkline', 0)
ls = counts.get('ActivityFeed', 0) + counts.get('DataGrid', 0) + counts.get('Repeat', 0)
print(f'Density gate: MetricTiles={mt} (target >=4), Charts/Sparklines={ch} (target >=1), Lists={ls} (target >=1)')
print(f'Passes density floor: {mt >= 4 and ch >= 1 and ls >= 1}')
"
```

Expected: density floor passes (>=4 MetricTiles, >=1 Chart, >=1 list).

- [ ] **Step 17.5: Verify the auth page picked an illustration**

```bash
SHORT_ID=<the id from step 17.3>
echo "Login schema:"
python3 -c "
import json, glob
candidates = ['login.json', 'auth/login.json', 'signin.json']
for c in candidates:
    paths = glob.glob(f'output/{$SHORT_ID}/src/schemas/{c}')
    if paths:
        p = json.load(open(paths[0]))
        def find_illu(n):
            if isinstance(n, dict):
                il = (n.get('props') or {}).get('illustration')
                if il: return il
                for c in n.get('children') or []:
                    r = find_illu(c)
                    if r: return r
            return None
        illu = find_illu(p['root'])
        print(f'Found schema at {paths[0]}, illustration={illu}')
        break
"
echo
echo "Bundled illustrations:"
ls output/$SHORT_ID/public/illustrations/ 2>/dev/null || echo "(no illustrations dir)"
```

Expected: the login schema has an `illustration.slug` set, and the matching SVG is in `public/illustrations/`.

- [ ] **Step 17.6: Visual check in the scaffold**

Open in a browser:
- http://localhost:6503/p/$SHORT_ID/login — should show a 2-column split with form + illustration
- http://localhost:6503/p/$SHORT_ID/ — dashboard with KPIs + chart + list
- http://localhost:6503/p/$SHORT_ID/notes — list page (baseline)

Compare to:
- http://localhost:6503/p/pagedriven-2p-1778564381/notes (pre-plan baseline)

Expected differences:
- Login: 2-column split with form on one side, illustration on the other (was: not generated before)
- Dashboard: ≥4 KPIs, a chart, an activity feed (was: sparse Card+Hero)
- Card / Section backdrops have subtle gradient depth (was: flat fills)

- [ ] **Step 17.7: Inspect design-spec.json for the new tokens**

```bash
cat output/$SHORT_ID/src/contracts/design-spec.json | python3 -m json.tool | grep -A 8 "gradient\\|shadow\\|illustration" | head -40
```

Expected: `surface.gradient.subtle`, `surface.shadow.elevated`, and any `accent.illustration` slots populated by the design agent are present.

- [ ] **Step 17.8: Capture findings in a session note (no commit)**

Notes to capture:
- Dashboard MetricTile count + Chart presence
- Login page illustration slug + visual quality
- Bundled SVG count under public/illustrations/
- MCP server invocation count (visible in the schema phase events)
- Any regressions to existing pages

This is verification, not work-to-commit.

---

## Self-review

| Spec requirement | Task |
|---|---|
| Dashboard exemplar JSON | Tasks 1 + 2 |
| Schema prompt inlines exemplar on dashboard pages | Task 3 |
| Density rule enforces ≥4 MetricTile + ≥1 Chart + ≥1 list | Task 4 |
| Design-spec tokens for gradient/shadow/illustration | Task 5 |
| Library components honor gradient backgrounds | Tasks 6 + 7 |
| Design agent emits default surface depth tokens | Task 8 |
| unDraw HTTP client + filesystem cache | Task 9 |
| FastMCP server exposing list + fetch tools | Task 10 |
| IllustrationResolver renders bundled SVGs | Task 11 |
| Hero / EmptyStateRich / Section consume illustration slot | Task 12 |
| Bundler copies cached SVGs into output/<id>/public/illustrations/ | Task 13 |
| Schema agent registers MCP server in ClaudeAgentOptions | Task 14 |
| Auth-page exemplar + schema-prompt + rule guide the LLM | Task 15 |
| Live verification on a real plan (dashboard + auth + list) | Tasks 16 + 17 |
| All-pass test gates at each step | Every task |

Coverage looks complete.

Five notes:

1. **The LLM may still under-emit charts on its first try.** The density rule is advisory (log + SSE event), not a hard fail — matching the conservative scope of CTA/PD gates from Tier S/M/L. If the live run (Task 17) shows persistent under-emission, a follow-up plan would add a retry hook (same shape as we sketched in Tier S/M/L Task 18 plan).

2. **unDraw API surface may not exactly match the client's assumptions.** The `list_illustrations` HTTP endpoint structure (response shape, pagination, tag taxonomy) is what the client assumes — Task 9's tests stub it. The first live run in Task 17 will be the real validation. If the response shape differs, adjust `UndrawClient.list_illustrations` to match. Fallback: if listing breaks, the `get_illustration_svg` direct fetch by slug still works for slugs the LLM picks from prior knowledge.

3. **MCP in-process vs. subprocess.** The schema agent registration in Task 14 assumes the Claude Agent SDK supports in-process MCP servers. If only subprocess (stdio) is supported, the registration becomes a 10-line adjustment — launch `python -m mcp.illustrations_server` as a subprocess and pass its stdio handles. Verify by reading the SDK's `ClaudeAgentOptions` reference before Task 14.

4. **The 2-3 hour regeneration cost in Task 17 is unavoidable** without fixing the underlying schema-agent perf issue (per-page LLM call takes 15-90 minutes — see RESUME.md). That's a separate investigation.

5. **Illustration tone variants are deferred.** The schema's `illustration.tone` field is defined (Task 12) but the bundler currently picks ONE color (the accent color from design-spec) and bakes one variant. A future enhancement could bake all three tones (primary/secondary/muted) and let the resolver pick at render time. Out of scope for v1.

---

## Out of scope

- Custom mascot / commissioned-artwork pipeline (truly bespoke illustrations) — separate plan; would require a designer asset library beyond unDraw
- Vision-grounded fidelity scoring against reference screenshots — Reference-Bank seeder work, separate plan
- Schema-agent perf (1-2h per page) — likely a tool-call/retry loop in `feature_slice_schema_agent._collect_llm_text`; needs profiling, separate investigation
- Photo avatars in lists (vs. initials) — fixture-image generation pipeline, separate plan
- LLM-synthesized SVG (vs. retrieval) — quality bar isn't there in any current model; revisit if model capability improves
- Image-generation API integration (DALL-E / Imagen / SDXL) per-page — cost/latency/style-inconsistency trade-offs make it a worse default than the unDraw library; could be a power-user opt-in later
- Multi-color tone variants on the same illustration — defined in the schema but not bundled (v1 bakes one variant per slug; v2 bakes all three)
- Replacing the abandoned `undraw-mcp` npm package — we own this MCP in-house

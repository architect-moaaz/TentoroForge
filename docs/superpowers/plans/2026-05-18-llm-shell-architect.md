# LLM Shell Architect Implementation Plan

> Bring the schema-driven shell architecture (already working for Figma projects) to LLM-generated projects. The LLM picks the app shell — nav structure, sidebar, branding — based on domain knowledge, exactly as Figma projects pull it from the design.

## What just landed (context)

The Figma path now has:
- `<PageOutlet />` node type in schema + renderer
- `shell.json` per project — a regular PageV2 schema with one `<PageOutlet />` slot
- `nav-flow.json` declares `pages[].shell: bool`, `auth_routes`, `post_login_redirect`, `post_logout_redirect`
- Scaffold loader: shell pages render `<PageOutletContext.Provider value={content}><Shell/></...>`; auth pages render bare
- `figma_shell_extractor` pulls the recurring nav out of multi-page Figma input into shell.json

The LLM-generated pipeline currently emits each page schema with its own copy of the chrome (nav bar, sidebar). No shared shell. This plan makes the LLM emit shell.json once + content-only pages.

## North Star

A user describes their app in plain text → backend generates:
- `shell.json` — nav structure + branding, decided by domain
- `src/schemas/*.json` — content per page, sized to slot into the shell
- `nav-flow.json` — routes, shell membership, auth flow

Rendered exactly like Figma projects: one shell, many page contents.

---

## Architectural decisions

### Where does the shell decision happen?

Add a new agent: `backend/agents/shell_layout_agent.py`. It runs ONCE per project, AFTER the planner (so plan.pages is known) and BEFORE page_layout_agent (so per-page layouts know not to re-emit the chrome).

Pipeline insertion point in `backend/routers/generate.py:_run_relay_pipeline`:

```
plan → contracts → schema → ENTITIES → ROUTES
                                       ↓
                              ┌────────────────┐
                              │ shell_layout_  │  ← NEW: emits shell.json + sets nav-flow.shell flags
                              │ agent          │
                              └────────────────┘
                                       ↓
                              page_layout × N     ← MODIFIED: emits content-only schemas
                                       ↓
                              api, biz, components, …
```

### Shell agent inputs

- `plan.pages` — full page list with types (auth, dashboard, form, list, detail)
- `plan.app_type` — CRM, marketing, dashboard, e-commerce, admin (inferred from description or asked)
- `brand` — colors, typography, logo URL (extracted earlier)
- `domain_context` — persona, industry (already used by other agents)

### Shell agent output

A `shell.json` PageV2-shaped schema. Constraints:
- Exactly one `<PageOutlet id="page-outlet" />` somewhere in the tree
- Nav items use `<Button label="..." navigate="/route" />` referencing routes in plan.pages
- Brand row uses Heading/Image as appropriate
- May include `<UserMenu />` (logout button → `workflow:auth.signOut`)
- Total emitted schema ≤ ~150 nodes

### Shell regions (header / nav / footer)

A real app shell is composed of up to four optional regions arranged around the `<PageOutlet />`. The LLM picks which to include based on app type:

| Region | What it carries | When |
|---|---|---|
| **Header** | Logo, primary nav, search bar, user menu, notifications, CTAs | Almost always for shell pages |
| **Sidebar** | Vertical nav (when ≥6 pages or admin/CRM type) | Data-heavy apps |
| **Footer** | Copyright, secondary links, legal, newsletter, social icons | Marketing, e-commerce, content sites |
| **Page content** | The `<PageOutlet />` slot | Always |

These are NOT separate node types — they're just regions of the shell.json schema. To make them semantically identifiable for the editor (and for downstream tools), the LLM annotates each region with a `data-shell-region` prop:

```
Container data-shell-region="header" → [logo, nav, user-menu]
Container data-shell-region="sidebar" → [logo, nav-items, user-menu]
PageOutlet
Container data-shell-region="footer" → [copyright, link-columns, newsletter]
```

The renderer treats these as normal Containers but the editor uses them to surface "Edit Header" / "Edit Footer" actions distinctly.

### Four output flavors (agent picks based on app_type)

**Flavor A — Top-header only** (SaaS dashboards, simple admin):
```
Stack flex-col min-h-screen
  Container data-shell-region="header"
    Row: logo + nav-tabs + user-menu
  PageOutlet
```

**Flavor B — Sidebar + top-header** (data-heavy admin, CRMs):
```
Row flex-row h-screen
  Container data-shell-region="sidebar"
    Stack: logo, nav-items (vertical), user-menu (bottom)
  Stack flex-col flex-1
    Container data-shell-region="header"
      Row: page-title + page-actions
    PageOutlet
```

**Flavor C — Header + footer** (marketing sites, content/blog, public-facing):
```
Stack flex-col min-h-screen
  Container data-shell-region="header"
    Row: logo + nav + CTAs (Get Started, Login)
  PageOutlet (flex-grow-1)
  Container data-shell-region="footer"
    Grid: link-columns, newsletter, social, copyright row
```

**Flavor D — Header + sidebar + footer** (e-commerce, docs):
```
Stack flex-col min-h-screen
  Container data-shell-region="header"
    Row: logo + primary-nav + search + cart + user
  Row flex-row flex-grow-1
    Container data-shell-region="sidebar"
      Stack: category/section nav
    PageOutlet
  Container data-shell-region="footer"
    Grid: link-columns, payment-methods, social, copyright
```

### Flavor selection heuristic

The agent reads `app_type` and `plan.pages` to pick:

| app_type | pages | flavor |
|---|---|---|
| `crm`, `admin`, `dashboard-heavy` | ≥6 navigable | B |
| `crm`, `admin` | <6 navigable | A |
| `saas`, `dashboard` | any | A |
| `marketing`, `landing`, `content`, `blog` | any | C |
| `ecommerce`, `docs` | any | D |
| unknown / default | <6 | A |
| unknown / default | ≥6 | B |

For Flavor C/D, the agent must also decide footer content based on industry:
- SaaS marketing: product / company / resources / contact columns + newsletter
- E-commerce: shop categories / customer service / about / payment methods
- Content/blog: topics / authors / about / newsletter

### What goes inside each region

Each region is a focused sub-decision the LLM makes:

**Header** content menu — agent picks 2-4 of these by app_type:
- Logo + app name (always)
- Primary nav (Button per shell page route)
- Search bar (`<Input data-role="search">`)
- Cart icon (e-commerce only)
- Notifications bell
- User menu (Avatar + dropdown with profile / settings / logout)
- CTAs (Get Started, Book Demo — marketing only)

**Sidebar** content menu — agent picks 2-3:
- Logo
- Vertical nav-items (Button per shell page)
- Section dividers / labels
- User menu (bottom-aligned)
- Collapse toggle

**Footer** content menu — agent picks based on app_type:
- Link-column grid: 3-4 columns × 3-6 links each, e.g.
  - Product / Features / Pricing / Roadmap
  - Company / About / Blog / Careers
  - Resources / Docs / API / Support
  - Legal / Privacy / Terms / Security
- Newsletter signup (`<Form>` with `<Input type="email">` + `<Button>`)
- Social icons row (Twitter/X, LinkedIn, GitHub, etc.)
- Payment method badges (e-commerce)
- Copyright row + language picker / region picker
- Sitemap link

### Page agent modification

`page_layout_agent.py` already exists. Modify its system prompt so:
- For pages with `type=auth`: emit a full page (NO PageOutlet awareness — auth pages render bare)
- For all other page types: emit ONLY the content. DON'T include nav, sidebar, header, branding. Those come from the shell.

Add to its prompt:
> "Authenticated pages (any page where shell=true in the plan) render INSIDE an app shell that already provides the navigation bar, sidebar, and branding. Your page schema must NOT include a top-nav, sidebar, or app-name header — emit only the content that's specific to THIS page (its title, body sections, data tables, forms, etc.)."

### nav-flow.json emission

Currently nav-flow is emitted from per-page transforms in the Figma path. For the LLM path:
- Planner annotates plan.pages with `type`
- A new `nav_flow_from_plan(plan)` helper builds nav-flow.json from plan.pages
- Auth pages (type=auth) get `shell: false`
- Other pages get `shell: true`
- `post_login_redirect` = first non-auth route
- `post_logout_redirect` = first auth route

Call this once after the planner, BEFORE shell_layout_agent (which needs nav-flow to know the routes).

---

## Tasks

### Task 1 — Shell schema validator

**File:** `packages/schema/src/shell-schema-validator.ts` (or similar)

Add a validator that asserts:
- Exactly one PageOutlet in the tree
- Any Button with `navigate` points to a route in nav-flow.pages
- No data-bound nodes (no PlaceholderSlot — the shell is "static" chrome)

Wire into the existing validator pipeline that catches schema errors before pages get rendered.

**Tests:**
- Valid shell with one PageOutlet → passes
- Shell with two PageOutlets → fails with clear error
- Shell with Button.navigate to undeclared route → fails
- Shell with PlaceholderSlot → fails

### Task 2 — `nav_flow_from_plan` helper

**File:** `backend/services/nav_flow_from_plan.py`

```python
def nav_flow_from_plan(plan: dict) -> dict:
    """Emit nav-flow.json from plan.pages."""
    pages = plan.get("pages", [])
    out = {"version": "1.0", "pages": [], "auth_routes": []}
    for p in pages:
        is_auth = p.get("type") == "auth"
        out["pages"].append({
            "id": p["id"],
            "route": p["route"],
            "title": p["name"],
            "schemaFile": f"src/schemas/{p['id']}.json",
            "shell": not is_auth,
        })
        if is_auth:
            out["auth_routes"].append(p["route"])
    non_auth = [p["route"] for p in out["pages"] if p["shell"]]
    if non_auth:
        out["post_login_redirect"] = non_auth[0]
    if out["auth_routes"]:
        out["post_logout_redirect"] = out["auth_routes"][0]
    out["initialPage"] = pages[0]["id"] if pages else None
    return out
```

Call sites:
- `_run_relay_pipeline`: emit nav-flow.json after planner, before shell_layout_agent

**Tests:**
- Plan with mixed auth + dashboard pages → correct shell flags + redirects
- Plan with only auth pages → empty `post_login_redirect`
- Plan with no auth pages → empty `auth_routes` + no `post_logout_redirect`

### Task 3 — `shell_layout_agent.py`

**File:** `backend/agents/shell_layout_agent.py`

Mirror the structure of `page_layout_agent.py`. System prompt sketch:

```
You are an app shell architect. Given a plan with pages and domain context, design ONE app shell schema (the persistent chrome that wraps every authenticated page).

You output a single PageV2-shaped JSON. Key constraints:
- Include EXACTLY ONE <PageOutlet id="page-outlet" /> node where page content goes
- Include navigation Buttons that reference routes in nav-flow.pages — emit `navigate: "/<route>"` on each
- Include brand row at top (app name + optional logo)
- DO NOT include data-bound content
- DO NOT include per-page content
- Pick layout flavor based on app type:
  - CRM / admin / data-heavy → side-nav + top-bar (Flavor B)
  - SaaS dashboard / marketing / simple → top-nav only (Flavor A)
- Total schema ≤ 150 nodes

Input you'll receive:
- App description and type
- nav-flow.json (routes + which are auth vs shell)
- Brand spec (colors, typography, logo URL)
- Domain context (persona, industry)

Output:
```ir-shell
{ "schemaVersion": "2.0", "title": "App Shell", "children": [...] }
```
```

Validation: the agent's output goes through shell-schema-validator before writing.

**Tests:**
- Mock LLM response → valid shell extracted from `ir-shell` markers
- Multiple pages → all become nav Buttons with correct navigate props
- App type=CRM → returns Flavor B layout
- App type=marketing → returns Flavor A layout
- Missing PageOutlet in LLM output → validator catches it

Add a `run_shell_layout_agent(plan, nav_flow, brand, domain_context, output_dir)` async function. Writes `output_dir/src/schemas/shell.json`.

### Task 4 — Modify `page_layout_agent` prompt

Add to its system prompt:
> "If the page's `type` is one of `{auth}`, render the full page (no shell will wrap it).
> Otherwise, the page renders INSIDE an app shell that provides the top/side nav, brand, and user menu. DO NOT emit any of those in your page schema. Start the page tree at the content (a Stack with the page title + body)."

Inject the page type into the user prompt so the agent knows what to emit.

**Tests:**
- Mock LLM response for type=auth → includes branding + form (current behavior)
- Mock LLM response for type=dashboard → starts with Heading, no nav bar

### Task 5 — Pipeline wiring

**File:** `backend/routers/generate.py:_run_relay_pipeline`

Insertion order:
```python
# after planner
yield sse_event("log", {"text": "[NavFlow] building from plan"})
nav_flow = nav_flow_from_plan(plan)
write_nav_flow(output_dir, nav_flow)

# new shell phase, before page_layout
yield sse_event("log", {"text": "[ShellLayout] generating app shell"})
async for evt in stream_agent_messages(
    run_shell_layout_agent(plan, nav_flow, brand, domain_context, output_dir),
    phase="shell_layout"
):
    yield evt

# existing page_layout phase — modified to pass page.type
for page in plan["pages"]:
    async for evt in stream_agent_messages(
        run_page_layout_agent(page, plan, brand, output_dir, page_type=page.get("type")),
        phase=f"layout:{page['id']}"
    ):
        yield evt
```

### Task 6 — Editor: shell as a tab

The editor can already open any schema file. Add a `shell` tab/route in the editor UI so users can open shell.json explicitly (instead of having to know the file name).

**File:** `frontend/src/<editor>/...` — add a "Shell" navigation entry in the editor's file picker.

This is a small UX addition; defer to a separate plan if it adds scope.

### Task 7 — Visual regression test

**File:** `backend/tests/integration/test_llm_shell_e2e.py`

Run a full LLM generation for a small fixture description ("Build a customer-feedback admin app with login, dashboard, settings"). Assert:
- shell.json emitted with PageOutlet + nav Buttons
- Each non-auth page schema has NO top-nav, NO sidebar
- Render-scaffold loads `/p/<id>/dashboard` correctly with shell + content composed

Heavy but the only way to catch regressions in the LLM phase. Run on demand, not every CI run.

---

## Sequencing

1. **Task 2** (`nav_flow_from_plan`) — pure function, easy
2. **Task 1** (shell schema validator) — catches errors early
3. **Task 3** (shell_layout_agent) — the real work
4. **Task 4** (page_layout_agent prompt mod) — small + needed before integration
5. **Task 5** (pipeline wiring) — integration
6. **Task 7** (E2E test) — validation
7. **Task 6** (editor shell tab) — UX polish, can defer

Total: ~3-4 days focused work. Largest risk is Task 3 — the agent's prompt needs iteration to consistently produce valid PageOutlet-bearing schemas. Plan to spend 1 day on prompt+validator+fixture-iteration.

---

## Open questions

1. **App-type inference**: do we ask the user for `app_type` upfront, or infer it from description? If inferred — by what mechanism? Probably an extension of the existing classify_page logic, applied at the app level. Worth a small experiment before committing.

2. **Branding in shell vs theme**: the brand colors/logo are already in the theme tokens. Does shell.json reference tokens (`text-primary`) or hardcode (`text-[#841013]`)? Tokens are more editable; hardcoded is more Figma-like. Recommend tokens for LLM-generated shells.

3. **Per-role shells**: should we support multi-shell? E.g., an admin user sees `shell-admin.json`, a regular user sees `shell-user.json`. Defer — single shell per project for v1.

4. **Sidebar vs no-sidebar dynamic**: should the shell layout switch responsively (sidebar collapses on mobile)? AppShell already supports this — we just need the agent to emit a shape AppShell can consume, OR emit the responsive structure inline. Recommend inline for now.

5. **Logout button placement**: in Flavor A, it goes in the top-right user menu. In Flavor B, bottom of sidebar. Agent decides — add to system prompt.

6. **Domain-aware page count threshold**: 6 pages → side-nav is a hand-tuned heuristic. Could ask the agent to decide both flavor and threshold from app_type. Or hardcode and revisit after seeing 5-10 generated projects.

---

## Acceptance: end of plan

After all tasks land:
- `localhost:6501` → describe an app → backend generates project including shell.json + content-only pages
- Render scaffold composes the result exactly like Figma projects
- Editor can open shell.json and edit it
- Auth pages render bare; shell pages render with nav-and-content composed
- LLM picks Flavor A or B based on app_type
- Visual regression test passes

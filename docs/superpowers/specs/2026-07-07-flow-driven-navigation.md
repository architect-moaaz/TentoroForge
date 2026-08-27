# Flow-Driven Navigation — Design Spec

**Date:** 2026-07-07
**Goal:** Make navigation in generated apps correct-by-construction and governed by a single, editable flow: auth pages and the entry point are first-class, and every page→page / click→page navigation resolves through one authoritative model that the Pages & Nav editor edits.

## Problem

Navigation is currently spread across **three** overlapping representations that drift:

1. **`nav-flow.json`** — runtime contract (pages[] with route/shell/schemaFile, transitions[], guards, auth_routes, redirects). Read by the generated app's layout + engine, and by the editor's page picker.
2. **`navigation-flow.json`** — agent-only CRUD contract (per-entity flows: every action's trigger→target→API). Read by page/component/QA agents at generation. Not editable.
3. **`navigation.json`** — the visual editor's canvas state (screens[] + edges[] + sidebarLinks). "Apply" runs an LLM agent to reflect it back into schemas.

The *actual* runtime mechanism is a fourth encoding: each page schema's `Button`/`Link` carries a literal `navigate` route string, and the engine navigates via those.

Consequences observed:
- **Auth-gating isn't modeled.** login/signup exist only if the planner emits `type:"auth"` pages; when it doesn't, `nav-flow.json` has `auth_routes:[]` and no login/signup entries/schemas — yet the scaffold's `(dashboard)/layout.tsx` still redirects to `/login`. The editor (which *does* handle `/login`+`/signup`) has nothing to show. Entry point is wrong (`initialPage` points at a dashboard even when the app forces login).
- **Nav drift → 404s.** The route a page is filed/registered under and the route the nav links to can diverge (fixed reactively by `nav_route_reconcile_guard`, but the root is the multi-model spread).
- **The editor's flow is not authoritative.** It's derived from `navigate` props and re-applied via an LLM agent — slow, lossy, non-deterministic.

## Target architecture

**One authoritative navigation model: `nav-flow.json`.** It is already both the runtime contract and the editor's page source. Extend it to be the single source of truth; make the other encodings *projections* of it.

### 1. Auth-gating is a first-class, single decision
- New top-level field `authGated: boolean`, decided **once** in the planner (`_decide_auth_gating(plan)`), derived from the plan/domain (does the app have users/roles/protected data?).
- When `authGated`:
  - login + signup are guaranteed real pages in `plan.pages` (`type:"auth"`), which flow into real schemas (`emit_auth_page_schemas`) and `nav-flow.pages[]` (`shell:false`).
  - `auth_routes = ["/login","/signup"]`; `post_login_redirect` = first shell page; `post_logout_redirect = "/login"`.
  - **Unauthenticated entry point = `/login`**; the scaffold's session gate already enforces this — now the flow metadata agrees.
- When not gated:
  - No auth pages; the scaffold does **not** gate `(dashboard)/layout`.
  - **Entry point = `/`** (root serves / redirects to the first shell page).
- `initialPage` and the root `src/app/page.tsx` redirect are derived from this decision (not hard-coded `/dashboard`).

### 2. Transitions are the authoritative connection graph
`nav-flow.transitions[]` becomes the editable flow:
```
{ id, from: pageId, trigger: "button:Label" | "row_click" | "submit" | "link", to: pageId|route, navType: "link"|"redirect"|"back" }
```
- Populated deterministically at generation from each page's schema (`Button.navigate`, `Link.navigate`, Hero CTA, table `rowHref`, form submit `onSuccess`) — the same walk `navigation.py._derive_edges_from_schemas` already does, but written into `nav-flow.transitions` as the source of truth (not a throwaway editor derivation).
- Entry→dashboard and login↔signup transitions are added when gated.

### 3. The editor edits `nav-flow.json` directly
- The navigation API (`GET/POST /api/projects/{id}/navigation`) reads/writes `nav-flow.json` (`pages[]`↔screens, `transitions[]`↔edges) instead of a divergent `navigation.json`.
- Canvas positions persist as `pages[].position {x,y}` on nav-flow (or a thin positions side-file), so no data lives only in the editor.
- login/signup already render (`flow-generator.ts` handles them) — once they exist in `nav-flow`, they appear with no editor change.

### 4. Runtime binding: navigate props generated from + validated against transitions
No engine rewrite. Keep `navigate` props, but make them a **projection** of the flow:
- A deterministic pass rewrites each page's Button/Link `navigate` targets **from** `nav-flow.transitions` (source page's outgoing transitions).
- A guard validates every `navigate`/`rowHref`/redirect target resolves to a real `nav-flow` page route (generalize `nav_route_reconcile_guard` to actions, not just nav links).
- The editor's **"Apply" becomes deterministic** (rewrite navigate props from edited transitions) — no LLM agent, fast and reliable.

### 5. `navigation-flow.json` folds in
Still emitted for the generation agents, but reconciled so its action targets == `nav-flow.transitions` == navigate props. Post-generation, `nav-flow` is authoritative; a guard keeps them consistent.

## Slices

- **Slice 1 — Auth-gating foundation (backend).** `_decide_auth_gating` in the planner; guarantee login/signup plan pages + schemas + nav-flow entries when gated; derive entry point / redirects / root redirect from the decision; make the scaffold's session gate conditional on `authGated`. *Outcome:* login/signup show in the editor; entry point correct. Directly fixes the reported symptom.
- **Slice 2 — Authoritative transitions + editor legibility.** Populate `nav-flow.transitions` deterministically from schemas at generation; add entry/auth transitions; editor renders entry-point marker + auth grouping + these connections. *Outcome:* the full route flow is visible and correct.
- **Slice 3 — Editor-authoritative flow + deterministic apply.** Navigation API reads/writes `nav-flow` directly; deterministic apply rewrites navigate props from edited transitions; guard keeps schemas↔transitions↔navigate in sync; retire the `navigation.json` divergence. *Outcome:* navigation is governed by the flow designed in the editor.

## Out of scope
- New engine navigation primitives (transition-ID references at runtime) — kept as a possible future; this spec keeps `navigate` props as the runtime binding.
- Multi-step wizard / conditional-guard authoring UI beyond simple `guards`.

## Test strategy
Backend: pytest (route/auth-gating sanitizers, nav-flow transition emission, deterministic apply, guards). Each slice ships with unit tests. Live E2E on a freshly generated auth-gated app (login entry, sidebar links resolve, editor shows auth pages + flow).

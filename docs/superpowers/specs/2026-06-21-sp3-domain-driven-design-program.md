# SP3: Domain-Driven Design — Program Roadmap

**Date:** 2026-06-21
**Status:** Decomposition approved; sub-projects to be brainstormed/spec'd/planned individually.
**Branch:** forge-v3

## Problem

Generated apps look like the same template even across different domains. Evidence
(comparing CRM `output/3v2f1yev` vs Leave Mgmt `output/17tdblyu`): the apps differ in
entities/routes/some archetypes/fonts, but **read as the same product** because five
design layers are template/mandate/deterministic rather than domain-derived:

1. The app **shell/frame** is one fixed sidebar template (near-identical `shell.json`
   composition; only labels change).
2. **CRUD-over-entities dominates** (~75% of pages are list/detail/form triplets).
3. The **dashboard** is a fixed `4×MetricTile + DataGrid` pattern.
4. **Themes collapse** to a blue/`sidebar-dark` family (`#1D4ED8` vs `#2563A8`).
5. **Workflows** are ~90% mechanical `Create/Update/Delete<Entity>` CRUD.

The domain drives the app's **nouns** (entity names, labels, a few archetypes) but not its
**skeleton** (frame, page shapes, dashboard, theme family, workflow set).

SP1/SP1.5 (already shipped) addressed only the page-archetype layer. SP3 addresses the
remaining four sameness drivers.

## Sub-projects

Each is an independent pipeline subsystem; each gets its own brainstorm → spec → TDD plan →
subagent-driven implementation.

### SP3.1 — Domain-varied app shell  *(do first — highest leverage)*
- **Stage:** `backend/agents/shell_layout_agent.py` (+ `industry_design` layout, nav-flow).
- **Today:** always emits dark sidebar + nav-from-routes + avatar + search.
- **Target:** a finite **shell-archetype catalog** (e.g. left-sidebar, top-bar, icon-rail+flyout,
  grouped-sections sidebar, command-bar) + a domain/IA→archetype map + a guardrail — mirroring
  the SP1 archetype-catalog pattern. The shell agent receives a chosen shell archetype.
- **Key decision:** the finite archetype set + the domain/IA mapping.
- **Effort:** M. **Risk:** M (touches every page's frame; must preserve the content-only page rule).
- **Deps:** none.

### SP3.2 — Relax the CRUD-for-every-entity mandate  *(IA variety)*
- **Stage:** `backend/agents/planner.py` (`_ONESHOT_SYSTEM_PROMPT`, `_annotate_page_types`).
- **Today:** prompt mandates a CRUD journey for EVERY entity.
- **Target:** classify **primary vs secondary** entities; primaries get workflow-centered pages,
  secondaries collapse into grouped/settings/nested-tab CRUD — **plus a reachability guard** so
  no entity becomes unreachable / no page set is under-generated.
- **Key decision:** primary/secondary classification + the reachability guarantee.
- **Effort:** M. **Risk:** M–H (risk of dropping pages/nav).
- **Deps:** interacts with SP3.1 (nav grouping).

### SP3.3 — Design-language differentiation
- **Stage:** `backend/services/industry_design.py` (`generate_design_spec_from_industry`).
- **Today:** domain → one hue + `sidebar-dark`; collapses to blue/corporate.
- **Target:** map domains to full **design languages** (palette family + type scale + density +
  radius + surface/shadow treatment), driven by domain + the research dossier's brand character —
  extending the `typography_registers` idea to whole design languages.
- **Key decision:** the finite design-language set + domain mapping + dossier-character input.
- **Effort:** M. **Risk:** L–M (mostly additive data + token wiring).
- **Deps:** coordinate **nav-style ownership** with SP3.1 (one of them owns nav style).

### SP3.5 — Domain-shaped dashboard
- **Stage:** `backend/agents/page_schema_agent.py` dashboard path (+ planner dashboard intent).
- **Today:** fixed `4×MetricTile + DataGrid`.
- **Target:** derive the domain's real **signals** (e.g. pipeline value / win-rate / aging vs
  leave-balance / pending-approvals / coverage) from entities + dossier, then compose the
  dashboard metrics + layout from them.
- **Key decision:** where domain signals come from + the metric-derivation logic.
- **Effort:** M. **Risk:** M.
- **Deps:** none.

### SP3.4 — Real domain workflows  *(largest / riskiest — do last or as its own SP2 track)*
- **Stage:** `backend/agents/business_logic_agent.py` (GF‑6 600s timeout) + workflow generation.
- **Today:** bizlogic agent times out / under-produces; workflows are ~90% mechanical CRUD.
- **Target:** **root-cause the 600s timeout first** (likely the same single-blob output overflow
  the chunked-schema work addressed, or an over-large prompt/too-many-workflows-in-one-call), then
  chunk/scope per-process generation + a completeness check, so apps get real domain processes
  (approval-with-escalation, lead-qualification, …).
- **Key decision:** the timeout root cause, then per-process chunking strategy.
- **Effort:** L (large). **Risk:** H (flaky core agent; overlaps the SP2 domain-feature engine).
- **Deps:** reuses the chunked-generation pattern from `services/chunked_schema.py`.

## Recommended sequence

1. **SP3.1 shell** — biggest "same product" cue, independent.
2. **SP3.3 design language** — high leverage, low risk, additive (coordinate nav-style with 3.1).
3. **SP3.2 CRUD/IA** — high leverage; needs the reachability guard.
4. **SP3.5 dashboard** — independent, medium.
5. **SP3.4 domain workflows** — biggest/riskiest; reuses chunked pattern; SP2-class.

## Execution model

Each sub-project runs the established loop: brainstorm (resolve the "finite set + mapping"
design decision) → spec → TDD implementation plan → subagent-driven development with review.
No sub-project ships until its tests pass and the existing binding/CRUD/render reliability is
unchanged.

## Out of scope (whole program)

- The standalone-app SSR render blocker (GF‑1) and other unrelated runtime items.
- New UI components (SP3 composes existing ones; new design languages reuse the token system).
- Figma path (it already differentiates from the source design).

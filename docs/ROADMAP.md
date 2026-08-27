# Tentoro Forge — Roadmap Additions

New backlog items **surfaced by the 2026‑06 end‑to‑end validation** (generate → npm install →
drizzle‑kit push → run → click‑through against a live Postgres). These are gaps/follow‑ups
that only became visible by actually running a generated app, not from code inspection.

Status legend: **Open** (not started) · **Partial** (mitigated this session, more needed).
Priority: **P0** blocks a usable app · **P1** important · **P2/P3** nice‑to‑have.

## Group A — Generated‑app runtime (blocks "open in browser & use")

| ID | Item | Why / Evidence | Pri | Status |
|----|------|----------------|-----|--------|
| GF‑1 | Fix browser page rendering | Renderer → `isomorphic-dompurify` → `html-encoding-sniffer@6` → `require("@exodus/bytes/encoding-lite.js")`, but `@exodus/bytes@1.15` is ESM‑only → `ERR_REQUIRE_ESM`. SSR pages can 500 even though the API works. Options: pin `@exodus/bytes`/`html-encoding-sniffer` via npm `overrides`, run Node ≥20.19/≥22.12 (which support `require(esm)`), Next `serverExternalPackages`, or load dompurify client‑only. | **P0** | Open |
| GF‑2 | Complete vendoring of renderer runtime deps | `_vendor_engine_packages` now **drops** `@tentoroforge/feel-lite` + `@forge/patches` so `npm install` resolves — but the renderer imports both at runtime (FEEL expression eval). Bundle them into the renderer `dist`, or vendor a transpilable copy + add to `transpilePackages`. | P1 | Partial |
| GF‑3 | Enforce Node version for generated apps | Generated app + scaffold need Node ≥18 (≥20.19 preferred, see GF‑1). Add `engines` to the generated `package.json` and a Node check in `start.sh`. | P1 | Open |

## Group B — Generation correctness (pipeline emitting a correct app)

| ID | Item | Why / Evidence | Pri | Status |
|----|------|----------------|-----|--------|
| GF‑4 | Figma‑path CRUD action wiring | The Figma binding pass runs **before** the entity/workflow‑producing agents, so CRUD/Delete/form wiring isn't applied to Figma‑generated apps (the prompt path is done). Add a second binding pass after entities+workflows exist, or reorder the Figma pipeline. | **P0** | Open |
| GF‑5 | De‑duplicate generated schema files | Generation sometimes emits >1 `pgTable("users", …)` for the same table (e.g. `user.ts` and a barrel/`index.ts`), so tooling can disagree on the canonical columns. The CRUD parser now prefers the fuller definition as a mitigation; the root cause (schema agent emitting duplicates) remains. | P1 | Partial |
| GF‑6 | BusinessLogic agent 600s timeout | The domain‑workflow (bizlogic) agent times out at 600s on **every** run — slows generation and risks empty/partial domain workflows. Investigate latency / chunk the work / raise or stream the call. | P1 | Open |
| GF‑7 | Broader type coercion for DB writes | `db_insert`/`db_update` now coerce ISO date strings → `Date` (fixed). Extend to numbers/booleans/enums, and validate/convert FK **uuid** inputs (a non‑uuid FK string produced `invalid input syntax for type uuid`). Forms should validate field types before dispatch. | P2 | Partial |
| GF‑8 | Validate Update + edit‑form wiring | Only Create/Delete were live‑validated against the DB. Verify `Update<Entity>` (edit forms → `UpdateX`) end‑to‑end, including the row id source on detail/edit pages. | P2 | Open |
| GF‑9 | Human‑task / approval completion flow | Domain approval workflows correctly **pause** at the `approval` node, but the task‑inbox → submit decision → resume → `db_update` path wasn't exercised. Verify and wire the UI submit. | P2 | Open |

## Group C — Verification & docs

| ID | Item | Why / Evidence | Pri | Status |
|----|------|----------------|-----|--------|
| GF‑10 | Ship test templates with generated apps | (= existing p0‑6) Generated projects ship no tests. Add a vitest/Playwright smoke suite (boot, login, one CRUD round‑trip) to every project. | P1 | Open |
| GF‑11 | Per‑module runtime verification sweep | ~150 platform tasks have their files present, but only the generation/data/workflow path is live‑verified. Smoke‑test the rest at runtime: Visual Editor, AHTML/GrapeJS editor, Decisions (DRD), Agent Builder, Navigation, Templates, Monitoring. "Code exists" ≠ "works". | P1 | Open |
| GF‑12 | Fix stale roadmap path | Task 14.13 "Workflow tester" points to `frontend/src/components/workflow/WorkflowTester.tsx`; the actual implementation is `frontend/src/components/workflow/simulator/WorkflowSimulator.tsx`. | P3 | Open |

## Context — what this session already shipped (foundation beneath the above)

Not roadmap line‑items, but the layer that made the validation possible and is now committed on
`forge-v3`: 39 UI library components wired into generation; monorepo `dist` rebuild + reproducible
build; generated‑app dependency / `start.sh` / `getWorkflowEngine` route fixes; the plan‑driven
**binding pass** (data + workflow wiring) for Figma and prompt paths; the **LLM completeness guard**;
deterministic **CRUD workflow generation**; and the data‑layer fixes (date coercion, real‑column
sourcing, `definition.trigger`, schema‑parse brace handling) — all DB‑validated end‑to‑end on the
prompt path.

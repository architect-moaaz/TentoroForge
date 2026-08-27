# Smith Feature-Authoring Roadmap

**Vision:** Smith can complete a whole feature in one chat turn — "add resume parsing that fires on CV upload and populates profile fields" → workflow created + form wired + event flow closed + user sees it work — with zero orphans possible.

**Three layered slices**, in dependency order:

| Slice | Plan | Effort | What it unlocks |
|---|---|---|---|
| **A. Submit-Authority** | [2026-07-20-submit-authority.md](2026-07-20-submit-authority.md) | ~1.5 weeks | Every form/workflow declares its wiring; validators + guards make orphans impossible on new generations. Foundation. |
| **B. Plan & Apply (Smith)** | [2026-07-20-plan-and-apply.md](2026-07-20-plan-and-apply.md) | ~1 week | Smith gets `plan_and_apply(ask)` — LLM decides which pages/workflows/entities to add, dispatcher creates them with SUBMIT-AUTHORITY declarations included. Whole-feature asks in one turn. |
| **C. Wire Form-Workflow** | [2026-07-20-wire-form-workflow.md](2026-07-20-wire-form-workflow.md) | ~2 days | Deterministic `wire_form_to_workflow(page, workflow, field_map)` seam + Smith tool. Retrofit orphan workflows on existing apps. |

## Recommended order of implementation

```
C  (2 days)  ─ ship first — unblocks retrofit on existing apps + tests the seam shape
│
A  (1.5 wk)  ─ ship next — prevents new orphans on newly generated apps
│
B  (1 wk)    ─ ship last — depends on A's contract shape being stable
```

## Why C first (small + immediately useful)

Right now `4ct3h8z2` has 10-11 orphaned workflows. Smith can't wire them because he lacks the seam. Once C ships, Smith can be asked *"wire ParseCvWorkflow to the CV upload on /candidates/new"* and it works. This validates the seam contract before A depends on it, and gives us a live retrofit path for every already-generated app that has orphans.

## Why A before B

B (`plan_and_apply`) emits fragments that need to declare `page.submit`, `workflow.source`, `workflow.inputs[].source`. That shape MUST be stable before B can produce it. A locks that shape.

## Cross-slice contracts

All three slices share the SUBMIT-AUTHORITY contract defined in Slice A:

```
page.submit          = { kind: "workflow"|"data_api"|"custom", target, field_map? }
workflow.source      = { kind: "form"|"button"|"event"|"timer"|"webhook"|"cron", page/event/schedule }
workflow.inputs[].source = { kind: "form_field"|"route"|"auth"|"static"|"computed", ... }
```

Slice C **consumes** this contract when it wires an existing form to an existing workflow.
Slice A **produces + validates** it at plan time.
Slice B **produces** it in scoped fragments.

## Session's acceptance test (after all three ship)

Ask Smith on a **fresh recruitment app**:

> "Add a resume parsing feature: when a candidate uploads their CV on the create form, extract personal info + work history and prefill the profile fields."

Expected:
1. Smith fires `plan_and_apply` (Slice B)
2. Fragment declares:
   - A new `ParseCvWorkflow` with `source: {kind:"event", event:"cv.uploaded"}` and inputs `{cvUrl: form_field, candidateId: route}`
   - Edits to `/candidates/new` — CV upload emits `cv.uploaded`; profile fields subscribe to workflow completion
3. Apply-scope dispatches to `add_workflow` + `edit_page` (Slice B) + `wire_form_to_workflow` (Slice C)
4. Post-generate guards verify no orphans (Slice A)
5. User uploads a CV → sees fields populate

Zero manual seam calls. Zero orphans. Zero UI plumbing left to inference.

## Anti-goals

- Retrofit-only OR generation-only — the whole point is both work through the same contract
- Massive rewrite of existing generation pipeline — SUBMIT-AUTHORITY is additive; deterministic pages still work; only new declarations flow through
- Smith making implicit wiring judgments — every wire is explicit in the fragment; no "figure out what to connect"

## Kill switches

- SUBMIT-AUTHORITY behind `FORGE_SUBMIT_AUTHORITY=1` env (opt-in during rollout; flip on when validated)
- `plan_and_apply` behind Smith's routing prompt — user can bypass with direct seam calls if the composed path misbehaves
- `wire_form_to_workflow` is additive — never removes wiring; safe to expose immediately

## Progress tracking

Add to task tracker as work begins:
- `AUTH-SLICE-A-*` — SUBMIT-AUTHORITY tasks (T1-T10 in that plan)
- `AUTH-SLICE-B-*` — plan_and_apply tasks (T1-T7 in that plan)
- `AUTH-SLICE-C-*` — wire seam tasks (T1-T5 in that plan)

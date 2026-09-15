# A reference frame is routed by what it shows, and a design can be disconnected

**Date:** 2026-09-13 · **Project that surfaced it:** Criterion Refunds v2 (`188b8l0s`) · **Branch:** `claude/figma-frame-identity`

## What happened

A refund and case management app was defined from a written brief with the Case-Management Figma file
(`llRwGmNM8NX72r9r4gmnEq`, 15 frames) connected as a reference. The build passed every node, served 15 of 15
pages, and every page was wrong: the Properties page rendered the Write-off Approval drawing, the posting queue
rendered the Front Desk search, the case record rendered an Approval Queue list. Each page was a single `Text`
node holding the whole frame's words.

Three faults, each on the REST capture path (the hosted Figma MCP's design-context code is gated to partners,
so production extraction always falls back to the REST node tree):

1. **`shows` was never recorded for REST frames.** `store._frame_headings` and `_chrome_evidence` read
   `structure.code` only. All 15 frames carried the same layer name, so `page_contracts` bound them to the 15
   pages in file order. The `shows` field on `designSources[].frames` existed for exactly this failure and was
   empty.
2. **A frame named "Body" folded the screen into one text node.** `figma_name_classifier.classify` gave the
   text role to any layer named body/paragraph/description. The file nests every screen as
   Screen > Body > Shell > …, so Body became a leaf `Text` and the fold concatenated 171 text layers into it.
3. **An unidentified reference frame was still a slot the planner had to answer.** With nothing to tell the
   frames apart, answering by position was the only answer available.

## What changed

- `services/figma/store.py`: `_screen_tree` / `_screen_trees` read a screen from code or from the REST document
  through the same transforms `figma_layout` composes with; both readers use them. The rail's destinations are
  typed as Buttons in REST trees, so the "names a rail entry" set now reads Button and Link labels on the chrome
  side. The fallback heading skips any word the chrome already owns (brand, section labels, signed-in user).
- `services/figma_name_classifier.py`: a text-role name on a FRAME with children is structure, not text.
- `services/blueprint/page_planner.py`: `identified_frames` — a reference frame is a slot only if it says what it
  shows or its name is its own; two frames showing one heading are one slot (one screen in two states).
- Smith verb `disconnect_design` (`services/smith/design_disconnect.py`, wired in `smith_session`,
  `verbs`, `understand_ask`, `smith_tools`): removes the design source, unbinds every page's frame, retires drawn
  layouts, commits with the reason, then runs `page_layouts` and what consumes it. Nothing upstream re-runs.

Proof on the real extraction: 14 of 15 frames identify by their rail entry (Ticket Queue, Dashboard, Front Desk,
Guest Self-Service, Approval Queue, Complaint Queue, GM Review, Chargeback Register, Write-off Approval, Policy
Manager), Notifications by its breadcrumb; the three drawn-twice screens collapse to one slot each, giving 11
slots for 15 frames.

## Route 1, as it was done by hand (recorded so the verb replaces it)

On `188b8l0s`, before the verb existed:

1. `BlueprintService.load`; snapshot.
2. Pop `figmaFrame` from all 15 pages (a pinned page field, so no agent proposal can remove it).
3. `designSources = []`; drop every `pageLayouts` entry with `composedBy == "figma"`.
4. `svc.commit(user_request=…, smith_interpretation=…, before=snapshot, affected=<page ids>)` → version 116.
5. Plan = `page_layouts` + `descendants(page_layouts)` + `verification` + its descendants, i.e.
   `page_layouts, frontend, integration, preview, verification`; run through `make_executor(tiered_router)` with
   the Anthropic observer, `commit=True`.

`incremental_plan` over "the pages changed" was rejected for this because it seeds every node that writes
`pages`, including the page-set planner, which is the churn the change exists to avoid.

## Later the same day: what the recomposition and the workflows change surfaced

Each of these was found on Criterion Refunds v2 after route 1 and fixed on the same branch, with tests:

- **A form that chooses the record supplies it** (`functional_completeness._form_chooses`, guidance in
  `a2ui_authority._input_guidance`). The record rule accepted a required record input only from the page's own
  record, a table row, a repeat or `args`; every intake form was refused for the property it asked for.
- **A plan cut off at the output limit says so** (`ModelReply.stop_reason`, `interpret`), and the CLI gives Smith's
  interpretation the 64k budget. A twelve-workflow request came back as 50,891 characters of JSON cut mid-string.
- **A plan the Blueprint refuses is re-asked once with the verdict** (`Smith.turn`, `interpret(rejected=…)`), and the
  workflow catalogue addendum states what a condition may be (FEEL, no subqueries).
- **A dropdown says where its options come from in the contract's words** (`a2ui_to_forge.option_source`,
  `_translate_option_sources`, and the composer-agnostic seam `layout_vocabulary.translate_layout_vocabulary` in
  `apply_agent_result`). Both composers write `optionsFrom: {entity, labelField, valueField}`; the contract reads
  `interaction.optionsFrom: {source, value, label}`. A placeholder written as an option with value "" becomes
  `placeholder`; label-only items take their label as value.
- **A create page offers no workflow that needs its own record** (`a2ui_authority.launchable`, now handed the whole
  registry). "Edit Property" beside "Create Property" on `/properties/new` bound Save to Edit.
- **A refused composition is kept for reading** (`blueprint/refusals.py`, `.forge/refused/`). Without it, three rounds
  of "needs a Property record" could not be diagnosed.

Prompt-to-change on a built app goes through `services.smith.cli --output-dir <project> --run-agents "<request>"`;
the chat route only builds on approval or runs verbs. Sequence that took v2 from 8 to 15 composed pages: the
workflows request through the CLI (version 133, 13 new workflows), then `compose_route` turns per refused page.

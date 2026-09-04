# Giving Smith more than one verb

**Status:** plan, nothing built. Written 2026-09-01, from a conversation where
Smith was asked four times to build a dashboard and answered four times that
nothing needed changing.

---

## 1. The complaint, and what it actually is

> *"I want smith to be smarter — it's dumb and unable to fix, even though it has
> far more control and access than its ancestor."*

Smith is not reasoning badly. In the conversation that prompted this it read the
brief correctly, honoured the phasing, proposed exactly the right six modules,
deferred the right four, and offered — unprompted — to build the dashboard with
the five widgets the user wanted. Then:

```
Smith  Do you want me to build the dashboard at that route now, with all five
       widgets (Upcoming Sessions, Quorum Status, Recent Votes, Pending Agenda
       Items, Document Counts) visible to every role?
You    yes please
Smith  I looked at what you asked and I don't see anything to change — the
       current state already matches.
```

The understanding was perfect. There was nowhere to put it.

### Measured

| | |
|---|---|
| tools advertised in `TOOL_CATALOG` | **53** |
| handlers registered | 48 |
| handlers that write anything | **1** (`use_21st_component`) |
| advertised with no handler at all | `answer`, `ask_user`, `propose_fix`, `verify_app`, `handoff_to_pipeline` |
| write moves in `move_dispatcher` | **1** — rename an element |

And the turn contract closes it. `_UNDERSTAND_ASK_REQUIRED` is:

```
screen · element_label · current_behavior · desired_behavior · target_file
```

Every field is the shape of *"change this label on that screen"*. "Build a
dashboard at `/` with five widgets" has no `element_label`, so it cannot be
**expressed** in the structure Smith must answer in — before any question of
whether it could be executed.

The catalogue meanwhile tells Smith it has `add_page`, `add_entity`,
`add_workflow`, `edit_page`, `create_business_rule`, and coaches it: *"Look this
up BEFORE proposing a `page_schema_patch`."* There is no `page_schema_patch`
handler.

**So Smith has perception and no agency.** Its ancestor was cruder and could
regenerate a whole application. That gap is the frustration.

## 2. The part that is already built

This is not a request to build a change engine. One exists.

| exists | what it does | reachable from chat? |
|---|---|---|
| `smith/change.apply_change` | §114 steps 3–7: impact, commit Blueprint, run sub-DAG | **no** |
| `orchestrator.incremental_plan` | §72 sub-DAG selection, NEW + MODIFIED seeding | only via `apply_change` |
| `add_page_seam.build_add_page_bundle` | a whole new page through the pipeline's own builders | no |
| `add_workflow_seam`, `remove_page_seam` | same shape, other artifacts | no |
| `atomic_apply.apply_bundle` | all-or-nothing file writes | via the seams |
| `blueprint/landing_page` | deterministic entry-point layout | via the frontend projection |
| `smith_session.run_iteration` → `move_dispatcher` | **rename an element** | **yes — this is the chat path** |

**There are two change paths and chat uses the weak one.** That is the
two-representations defect at architecture scale: the capable path exists, is
tested, implements the spec — and nothing routes a conversation into it.

## 3. The verbs

Ordered by what users actually hit, with the two from the transcript first.

### V1 — `compose_route` · "build the page at /X"

The one that failed twice in one conversation. A page contract exists (or can
be written) and the route has no layout, or has one the user wants replaced.

- **Understanding needs:** `route`, and optionally `widgets` / `sections`.
  Not `element_label`.
- **Machinery:** `page_layouts`' own composer for one subject, or
  `landing_page.compose_landing` for the entry point. Both exist.
- **Then:** `apply_change` with the new `pageLayouts` artifact, which seeds the
  incremental DAG so `frontend` re-projects it.

### V2 — `add_widgets` · "put five widgets on the dashboard"

- **Understanding needs:** `route`, `widgets[]` with what each shows.
- **Machinery:** compose the page again *with the widgets named in the brief*
  rather than patching a tree in place. Recomposition is cheaper to get right
  than surgery, and A2UI already accepts a requirement string.
- **Watch:** this must not silently discard a page the user liked. Recompose
  only on an explicit ask, and say what changed.

### V3 — `add_page` · "add a page for X"

- **Machinery:** `add_page_seam.build_add_page_bundle` — already written,
  already atomic, already uses `deterministic_pages.build_crud_page`.
- **Work:** a router branch and an understanding shape. Nothing new underneath.

### V4 — `rebuild` · "just build it again"

The escape hatch that makes the others safe to ship incomplete. Today a user
must know the word "rebuild"; Smith should offer it when it has no verb.

- **Machinery:** the existing approved-run path.
- **Value:** it is the honest answer to "I cannot do that yet", and it is what
  the ancestor could always do.

### V5 — `edit_field` / `add_rule` / `add_workflow`

`add_workflow_seam` exists. Lower frequency; defer until V1–V4 are real.

## 4. What has to change structurally

1. **The understanding schema becomes a union, not one shape.**
   `_UNDERSTAND_ASK_REQUIRED` describes a rename and is enforced for every
   request. It should be *per verb*: a rename needs `element_label`, a
   `compose_route` needs `route`. The current schema does not under-describe
   the problem — it mis-describes it, which is why the model cannot comply.

2. **`run_iteration` dispatches on the verb.** `move_dispatcher` becomes one
   handler among several rather than the only path.

3. **Chat reaches `apply_change`.** Every verb above ends there: Blueprint
   first, then the incremental DAG (§13, §72). Nothing writes files behind the
   Blueprint's back.

4. **The catalogue tells the truth.** Either wire the advertised tools or stop
   advertising them. A model coached to call `page_schema_patch` when no handler
   exists will keep trying, and every attempt reads to the user as stupidity.

## 5. Order, and how to know each step worked

| step | done when |
|---|---|
| 1. Verb field on the understanding; per-verb required fields | "build a dashboard at /" produces `verb: compose_route`, not a validation failure |
| 2. `run_iteration` dispatches; unknown verb says so | the transcript's four no-ops become one honest "I can't yet, say rebuild" — **already shipped in `f1a601f`** |
| 3. V4 `rebuild` | "rebuild" from chat runs the approved DAG and reports the ledger's outcome |
| 4. V1 `compose_route` | "build the page at /" composes, commits, re-projects, and the route renders |
| 5. V2 `add_widgets` | the five-widget request from the transcript produces those five widgets |
| 6. V3 `add_page` | "add a page for X" writes a schema, a nav entry, and a working route |

Each step is separately shippable and separately verifiable in a real
conversation, which is the only test that has caught any of this.

## 6. What not to do

- **Do not add a repair pass.** If a composition is refused, the answer is a
  better composition or an honest refusal — not editing the output until it
  passes. That is what produced the component library's preprocessors.
- **Do not let a verb write files directly.** The Blueprint is the record; a
  seam that writes `src/schemas/*.json` without a `pageLayouts` artifact
  recreates the divergence §115 exists to refuse.
- **Do not widen `_UNDERSTAND_ASK_REQUIRED` to make everything optional.** That
  turns a mis-shaped contract into no contract, and the relevance check that
  closes the "cheapest-edit-wins" loophole depends on it.
- **Do not start with V5.** The two verbs in the transcript are V1 and V2.

## 7. The one-line summary

Smith can see everything and change one thing. The change engine it needs was
built, tested, and never wired to a conversation.

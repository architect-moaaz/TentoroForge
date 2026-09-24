# Smith as a loop — Claude Code parity for the change turn

**Status:** spec, nothing built.
**Date:** 2026-09-24
**Branch the question was asked on:** `claude/smith-claude-code-parity-0b49a1`
**Owner:** Smith
**Companions:**
- `docs/SMITH-VERBS.md` (the complaint this answers, from the other end)
- `2026-07-17-smith-as-architect.md` (what Smith is for)
- `2026-08-07-smith-auto-act.md` (act rather than ask — the legacy Smith's version of this)
- `2026-08-01-self-verify-pass-design.md` + `2026-08-06-vf-self-healing.md` (the verify and recover halves, built, unwired from the turn)
- `2026-08-11-intelligent-rich-forge.md` (already names the goal: "plans, verifies, recovers, learns — like Claude Code operates on our codebase")

---

## 0. The governing principle (added 2026-09-25)

Stated by the owner after the measurement, and it overrules the caveats below
where they conflict:

> Smith should know the whole code in and out. It should be smart enough to
> fix the problem rather than saying that it cannot, and it should actually fix
> it. Smith is the whole development team by itself.

Read against Claude Code, that resolves to one structural difference. Claude
Code has **no verb table and no intent classifier**. Its determinism is in the
*execution* layer — a dozen exact tools (`Read`, `Edit`, `Grep`, `Bash`) that
never guess, and a world that judges the result (compiler, tests, git). Smith's
determinism is in the *interpretation* layer — one call decides the verb, code
does the rest. A capability list is a list of what is missing, which is why
Smith has a `limits.py` and Claude Code has no equivalent: Claude Code says "I
cannot" only for **policy** (credentials, irreversible deletes), never for lack
of a capability, because capability is not a list.

So, for Smith:

- **The verb table stops being the ceiling.** Verbs stay as conveniences — a
  `restyle` that knows which agent to brief is faster than working it out —
  but they no longer define what is possible. `limits.py`'s four refusals and
  "I did not recognise that" are cases to close, not features.
- **`apply_agent_result` stays exactly as it is.** It is Smith's permission
  system — a *policy* boundary on writes, contract-validated, better than a
  prompt. Nothing here loosens it.
- **Smith gets the primitives.** Read the real tree, not a string about it
  (§4.3, widened from Blueprint sections to code). Write through the build's
  own seams — `pageCode` through `ui_engineer` and `tsc`, sections through
  their owning agents — so anything Smith authors is compiled, type-checked
  against the SDK and observed like build output. Run the oracles and see the
  result (§4.4).
- **§116's "one interpretation call" stays true for what is deterministic** —
  id allocation, projection, the contract — and stops being a bound on reach.

The line in §5 against "a free-form file-edit tool" stands in its narrow form:
no tool that writes a projected file behind the Blueprint's back. It does not
stand as "Smith may not write code": the build already writes every page as
React, through a seam with a compiler on it, and that seam is Smith's too.

## 1. What is actually being asked

Claude Code has one load-bearing property. The model **acts, sees the result,
and decides again**, over a small set of general primitives, with no fixed idea
of what a request will turn into. Todo lists, subagents and permission prompts
are scaffolding around that loop; none of them is the thing.

Smith's change turn has the opposite shape, on purpose.
`services/smith/turn.py` states it in its first paragraph: the model is
consulted **once** to say what the message meant, and "deterministic code
decides everything that follows from it" (§116).

So the question is not "which Claude Code feature is missing". It is: **can the
turn become a loop without giving back the thing determinism bought?**

---

## 2. The fact that changes the design

Forge has already built this loop. It is running today.

`backend/agents/smith_agent.py`, first paragraph:

> Given the user's plain-language turn PLUS the app's recall dossier + the
> cross-turn memory block, Smith picks a tool from `services.smith_tools`,
> observes the result, and picks again — until he invokes one of three terminal
> tools.

85 tools in `services/smith_tools.py` (`TOOL_CATALOG`, split into
`READONLY_HANDLERS` and `PROJECT_HANDLERS`), including `think`, `ask_user`,
`answer` and `propose_fix`. Bounded by an unknown-tool streak and a
per-target failure count, not by a step cap. `backend/agent.py` goes further
still and runs the Claude Agent SDK itself (`max_turns=80`) for the
Figma→Next.js path.

That is the **legacy** Smith — the one `docs/SMITH-VERBS.md` calls "its
ancestor". It writes through `propose_fix` into generated files that a
Blueprint app does not have, which is why it could not come forward.

The two Smiths, side by side:

| | legacy (`agents/smith_agent.py`) | Blueprint (`services/smith/*`) |
|---|---|---|
| Model's role in a turn | act → observe → act, until terminal | one interpretation call |
| Tools | 85, open palette | ~30 closed verbs (`verbs.py`) |
| Writes through | `propose_fix` → generated files | `apply_agent_result`, capability-bounded |
| Boundary on writes | none worth the name | §30 capability, contract-validated |
| Verification | none in the turn | compile / observer / dry run — **only inside a build** |
| Context | pulled by tool calls | pushed, deterministically sliced (`context.py`) |
| An unnamed request | decomposed into tool calls | named as unknown, answered honestly (`verbs.is_known`) |

**The legacy Smith kept the loop and had no boundary. The Blueprint Smith kept
the boundary and dropped the loop.** Parity is one Smith with both, and neither
half has to be invented — both are in the tree.

---

## 3. Why the loop was dropped, and what of that reasoning survives

Three files argue the case, and they are right about what they are arguing
about:

- `turn.py` — a plan naming an artifact that does not exist is "rejected and
  re-asked once, with the failure named — not patched up", because a repair
  pass that maps a hallucinated `PAGE-099` onto the nearest real page "is right
  often enough that nobody removes it. Then it is load-bearing."
- `verbs.py` — an open verb string "would let the model invent
  `refactor_everything` and the dispatcher would fall through to the same silent
  no-op this exists to remove."
- `move_dispatcher.py` — no model call, because `understand_ask` already
  decided, and "a second model here would be a second opinion about a question
  that has already been answered, and a place for the two to disagree."

Every one of those is an argument about **writes**: about a second author, a
silent fallback, a guessed-at repair. None of them is an argument against the
model **reading more**, **sequencing its own steps**, or **seeing what its
change did**.

And the project already accepts bounded loops where the feedback is *verified*
rather than guessed:

- `ui_engineer.py:861` — page code goes back to its author with the compiler's
  errors, `COMPILE_ROUNDS = 3`.
- `observer.py` — each node is judged as it lands and re-briefed to the agent
  that owns the section; the observer itself is registered `writes = ∅`.
- `build_repair.py` — a failing proof goes back to the step that owns it,
  `REPAIR_ROUNDS = 2`.

That is the distinction this spec rests on, and it should be stated once,
plainly:

> **Iterating on a verified result is not a repair chain. A repair chain is
> iterating on a guess.** The 151-pass ancestor mapped bad output onto
> plausible output with no oracle. Every loop above has an oracle — a compiler,
> a judge with the requirements in hand, a database that either stands up or
> does not.

The change turn is the only part of Smith that has an oracle available and does
not use it.

---

## 4. The design

Five changes. None adds a verb, none adds a write path.

### 4.1 The turn becomes a bounded loop

**Today.** `understand_ask` returns one understanding → `move_dispatcher` (or
the section handler in `smith_session.py`) performs one move → the turn ends.
The model never sees the result of its own change.

**Change.** The turn runs the model in an act→observe loop with a hard step cap
(start at 8) and three terminal moves, which already exist by name in the
legacy palette: `answer`, `ask_user`, `done`. Each step's result — including
refusals, contract violations and `AuthorRefusal` — comes back as an
observation in the model's own context rather than as an exception that ends
the turn.

**Why it is safe.** The loop changes *who decides the next step*. It does not
change who may write: every write still goes through `apply_agent_result`
against a declared capability, exactly as now. A model that asks for a
forbidden write gets the refusal as an observation and picks again — which is
strictly better than today, where the refusal ends the turn.

**What it costs.** More model calls per turn. Mitigated by 4.3 (a pulled
context is smaller than a pushed one) and capped by the step limit. Measure
before assuming: a multi-ask message today costs one interpretation call plus
one full turn per step via `plan.py`, which is not obviously cheaper.

### 4.2 The verbs become the loop's tools

**Today.** `verbs.py`'s `REQUIRED_BY_VERB` maps each verb to the fields a turn
must carry to be actionable. That is a tool schema written in a different
notation.

**Change.** Expose the existing verbs as the loop's tools, generated from
`REQUIRED_BY_VERB` so there is one source. **No new verbs, no open verb
string.** `verbs.is_known` stays exactly as it is — an unknown tool name is a
tool error the model sees and recovers from, instead of a turn that ends in
"I don't know how to do that."

The interesting consequence is what stops being needed. `plan.py` exists because
`understand_ask` returns one verb and the other asks were dropped silently. A
loop that can call `add_field`, then `edit_page`, then `edit_workflow` does not
need a pending-plan file to hold the second and third — though it still needs
`plan.py`'s *consent* step (§4.5).

### 4.3 Reading is pulled, not pushed

**Today.** `context.py` ranks artifacts deterministically and hands over a
capped slice. Its own docstring gives the budget: the ATS fixture is ~313
artifacts and ~80k tokens of JSON, and "handing all of it to every turn is what
makes a conversation cost more than the work."

That is an argument **for** pull-based reading. Claude Code stays affordable on
repositories far larger than 80k tokens precisely because it greps and reads on
demand rather than being handed the tree.

**Change.** Keep the resolver as the **opening page** — it is a good first
guess and it costs nothing. Add read-only tools the loop can call for more:
`read_section(name)`, `find(query)` over identity fields, `read_page_code(route)`,
`dependents(id)` over §19's graph. `smith_tools.py` already has the shape of
most of these against the legacy stores.

**Why it is safe.** Reads have no boundary to violate. Capability-scoped
context (`executors.context_for`) applies unchanged — and this is the point at
which narrowing `reads` from `{"*"}` starts to pay, because an agent that must
ask for a section can be told no.

### 4.4 Reality becomes an observation

**Today.** The oracles exist and none of them is wired to a change turn:

- `move_dispatcher`'s caller "snapshots git before calling, then asks git what
  actually changed and fails the turn unless the diff mentions `element_label`
  and `target_file` is among the modified files." That is a real oracle used as
  a **pass/fail gate** — the finding is never handed back to the model.
- `verify & fix` reads every page as it renders and re-composes anything off
  (`capabilities.py:120`) — and it is a thing the user types.
- The first-click dry run and the DB gate fire during a build only
  (`build_repair.py`).
- `recode_page` already reads the asked-for widgets back off the generated code
  and returns `missing` (`compose.py:735`) — then returns it to the caller
  rather than to the author.

**Change.** Make each one a tool the loop may call after it writes, and feed
the finding back as an observation within the same step budget. The cheapest
first: turn the existing git-diff relevance check from a gate into an
observation. "The diff did not touch the file you named" is exactly the
sentence that makes a model try the other reading — and it is the literal text
of the `SMITH-VERBS.md` failure, where Smith reported that "the current state
already matches" after doing nothing.

**Why it is safe.** These are oracles, not heuristics. Bounded by the same step
cap. What survives the cap is reported as an issue of the application, the way
`build_repair` already ends: "the app ships, it says what is wrong."

### 4.5 The plan is the loop's, and it is mutable

**Today.** `plan.py` splits a multi-ask message into ≤6 steps, gets one yes,
and works them as separate turns. The list is frozen at interpretation time, so
a step that step 1 made unnecessary is still performed.

**Change.** The plan stays a user-facing object — the consent step is worth
keeping and is not something Claude Code has an answer for — but the remaining
steps become writable by the loop, with any change to them surfaced rather than
silent. Dropping a step says why; adding one asks.

`MAX_STEPS = 6` stays. Its reasoning ("more than this on screen is a list
nobody reads before agreeing to it") is about consent, not about capability.

---

## 5. What must not be imported

Worth writing down, because "make it like Claude Code" invites all four:

1. **A free-form file-edit tool.** §115 makes the Blueprint the source and the
   implementation derived. `move_dispatcher` is explicit: editing generated
   files directly "is precisely what makes the legacy pipeline's Blueprint a
   post-hoc record of whatever the code happened to become." Writes stay
   proposals. The loop goes around reading and sequencing.
2. **An open tool namespace.** Claude Code's `Bash` is a universal escape hatch.
   Smith's equivalent would be a write with no capability, i.e. the second
   unbounded author `observer.py` registered `writes = ∅` to avoid.
3. **An unbounded step count.** Output tokens dominate a run's cost. Every loop
   in the tree is capped (3, 2, 3); this one is capped too, and the cap is
   reported when it is hit.
4. **Repair-by-mapping.** A tool call naming an artifact that does not exist is
   still rejected and re-asked with the failure named. The difference the loop
   makes is that the model gets to *act* on the rejection instead of the turn
   ending on it — not that the rejection becomes softer.

---

## 6. Slices

**S1 — the harness. Built (2026-09-24), unmeasured.** Today's dispatch, wrapped
in a loop with a step cap and the three terminal moves. No new tools, no new
reads, no new writes; the catalogue is generated from `REQUIRED_BY_VERB` and
`VERB_HELP`.

- `services/smith/tools.py` — the verbs as tools. 49 of them, one source.
- `services/smith/loop.py` — `next_step`, the observation, the step identity,
  `MAX_STEPS = 8`.
- `smith_session._loop` drives it; the verb chain and the ground-truth checks
  moved out of `_iterate` into `_perform` **whole**, so step two is carried out
  by the code that carries out step one. Each step snapshots its own baseline.
- `next_step_fn` is a seam beside `understand_ask_fn` and `iteration_move_fn`,
  wired in `smith_chat_v2`. Absent — every caller predating this, and every
  test that injects seams — a turn is the single step it always was, which is
  also what `MAX_STEPS = 1` gives.

Three defects surfaced while building it, each fixed at its source rather than
worked around:

1. `verbs.missing_fields` counted an empty **dict** as present, so `add_field`
   with no field spec walked through the gate and reached the seam as
   "Nurse has no field ''". Empty lists were already checked one line above.
2. `phrasebook`'s drift detector failed loudly on the `_iterate` → `_perform`
   move, which is exactly what it is for. It now reads both methods, in the
   order they run.
3. A cap of one reported that it had "stopped after 1 steps" — a turn claiming
   it was cut short when it had done everything there was.

**Measured 2026-09-24**, against a real model, on a throwaway copy of
`output/0l133sp2` (the tool-lending app this repo's own comments cite). Seven
runs. Harness in the session scratchpad; it only observes.

*It found a defect in the loop, which is fixed:* asked to build a dashboard and
told "yes please", the loop built it and then **appended a fabricated answer
about identity documents** — a subject taken out of the Blueprint slice. Two
causes, both in S1 as first written: the chooser was shown the ask but not the
**exchange**, so "yes please" arrived as a word with nothing behind it; and
`answer` was allowed to add prose to a turn that had already changed something,
contradicting the rule written two paragraphs above it in the same file. Both
fixed, both with a test.

*Three findings that change what to build next:*

1. **The motivating failure no longer reproduces.** `SMITH-VERBS.md`'s "I don't
   see anything to change" is gone: current smithv2 composes the page and says
   what it added. §7's first success criterion is already met, by something
   else, before the loop.
2. **The outcome is not deterministic.** The identical turn resolved 3 times
   out of 4 (222s, 229s, 247s) and once ended `needs_user` with "the new screen
   does not show what you asked for" (193s). Any future measurement needs
   repeats; n=1 per arm proves nothing. (An earlier run of this same case
   failed differently and for a reason that was mine — the project copy had no
   `node_modules`, so page code could not compile. A measurement copy must
   carry them.)
3. **The loop did not engage in any real scenario.** Not once, for three
   different reasons, none of them a bug in the loop:
   - dashboard: step one ends `resolved`, so there is nothing left to choose;
     or `needs_user`, which S1 treats as terminal by design.
   - multi-ask: `plan.py` returns `asked` before any verb runs, so the turn
     ends at the consent gate.
   - multi-ask, consent given: **0 loop steps** — `_run_step` re-enters
     `_iterate`, not `_loop`.

*What that means.* S1 is sound and costs little when it runs (+1 call, ~19k
input tokens, ~11s), but the paths that would use it are all closed upstream.
The order in §6 should change: the cheap half of **S3** comes first, because
the one case where a second look was clearly worth something — "I changed
/admin/dashboard, but the new screen does not show what you asked for … say
what it should contain and I will compose the screen again" — is a `needs_user`
that hands an oracle's finding to the person as a dead end. Then `_run_step`,
which is one line. Both are worth more than S2 until the loop has a path to
run on.

**Both reordered items built and re-measured, same day.**

*`_run_step` now enters `_loop`, not `_iterate`.* One line. The agreed plan
that took **0 loop steps** takes 1, and the loop ends it correctly rather than
swallowing the plan's remaining steps, which are the person's to consent to
one at a time.

*The cheap half of S3: `TurnResult.finding`.* `needs_user` had come to mean two
things at once, and nothing separated them:

- a **finding** — something the platform PROVED about the work it just did.
  git says the diff did not touch the file that was named; the composer laid
  the page out without what it was told to draw; a guard that passed now
  fails. Five sites, all of which already knew what they had proved and had
  nowhere to say it except to the person, with three chips, at the end of four
  minutes' work.
- a **question** — "I do not recognise that", "building runs from the card",
  "are you sure, this deletes a column". No amount of thinking makes these
  answerable.

A finding is now an observation the loop acts on; a question still ends the
turn. A finding the loop cannot settle is added back to the reply after what
did land, so a turn cannot say "Done" and report `needs_user` in the same
breath — it did, once, before that was fixed.

*What the re-measurement showed.* The agreed-plan improvement is confirmed
live (0 → 1 steps). The composer finding is **not**: across seven dashboard
runs it occurred once, before this change, and not in the three runs after it,
so the live path has not been observed recovering. It is covered by test
(`test_the_composer_not_drawing_what_it_was_told_is_a_finding`) and by the git
oracle's equivalent, and that is the honest status. The earlier "1 in 4" was
n=4; over all seven runs it is 1 in 7, and the true rate is unknown.

*Cost of the loop when it runs and has nothing to do:* 1 extra call, ~11s,
~19k input tokens — the `done`. Every dashboard run after the fixes took
exactly one loop step and stopped.

Still to do: a full UAT replay (§7.2). Worth attempting now that two paths
reach the loop, where before it would have measured a loop that never ran.

**S2 — reading the real code. Started 2026-09-25.** Widened by §0 from
Blueprint sections to the application itself: `read_section`, `find`,
`read_page_code`, `read_file`, `grep`, `list_files`, `dependents`. Read-only;
no boundary to violate, one policy to keep — a file that holds a credential is
refused by name (`.env*`, keys) and content is scrubbed by
`secrets_scrub` on the way out, because an observation is written to the
conversation. Reads cost a step like anything else; `MAX_STEPS` rises to 12
because a turn that looks before it acts needs the room. The resolver stays as
the opening page. Watch tokens per turn.

Built and checked against the `0l133sp2` copy the same day: every tool answers
on the real tree; `.env*` refused with the reason; a path outside the project
refused as given; `grep` finds `Overdue` in twenty lines of real page code and
leaves `node_modules` out. Two things found on the way: `code_intel.dependencies`
returned only its seed on the engine document (cause not chased — `dependents`
asks the artifact directly through `refs_of`), and the navigation tree, having
no id, is invisible as a referrer.

**Measured live, same day.** Asked "what exactly is the code that decides
which rentals need attention, and what statuses count?":

- *before* — `understand_ask` answered from the slice in 14s: five statuses,
  and the sentence "the Blueprint does not expose the underlying filter code".
  It knew it could not see and had no way to look. `view.tsx:16` says three.
  The loop never ran: an answered question ended the turn before any step.
- *fix* — an answer written from the slice alone is step one, recorded under
  the terminal name `answer`, and the loop gets its turn; the first answer is
  kept out of what "landed" so a better one can replace it.
- *after* — **2 loop steps, 36s**: `answer` (from the slice) → `read_page_code
  /rentals` → `answer` from the code, quoting `ATTENTION_STATUSES =
  ["requested", "overdue", "disputed"]` with line numbers, the `load.ts`
  counts and the lead-card priority order, and a table of which status counts
  for what. Exactly right. Cost went from 26k to 82k input tokens and 2 to 6
  calls — three times the price for the difference between wrong and right.

**`write_page_code` built and measured live, 2026-09-25.** A primitive of the
loop, not a verb (`services/smith/writes.py`): the loop, having read a page,
briefs `compose.recode_page` → `ui_engineer` → `tsc` → `apply_agent_result` →
one commit. The compiler's refusal, the contract's refusal and "the code does
not draw it" all come back as findings; `_compose`'s own refusal became one
too. Two more places where `understand_ask` ended the turn before the loop
could look were made step one: an **answer** written from the slice, and a
**clarification** raised from it — with one structural rule, a second
question with nothing read in between is sent to look first, once.

Asked *"rentals that have been accepted but not yet handed over should also
count as needing attention"* — a change no verb describes:

- *before* — `understand_ask` asked whether a needs-attention section existed
  (`view.tsx:211` says it does); 0 loop steps.
- *after* — **3 steps, 86s, 8 calls, 116k in**: `ask_user` (slice) →
  `read_page_code /rentals` → `write_page_code` with a brief in the code's
  own terms (`RentalCounts`, the `counts` object, `ATTENTION_STATUSES`) →
  `done`. `view.tsx:16` now reads `["requested", "accepted", "overdue",
  "disputed"]`; it compiled; version 103 → 104.

Of `limits.py`'s four refusals this closes `reorder` on coded pages (it was
already routed to the composer) and nothing else: `rename_entity`,
`change_field_type` and `edit_api` are data-model and API writes, which need
the same primitive through *their* owning agents — `write_section`, next.

**S3 — reality as observation.** Git-diff relevance first (gate → observation),
then `verify & fix` and the first-click dry run as callable tools.

**S4 — the mutable plan.** Only after S1 shows what the loop does to multi-ask
messages; it may shrink `plan.py` to its consent step.

**S5 — one Smith.** Retire `agents/smith_agent.py` and the `smith_tools.py`
palette that writes to legacy files, once the Blueprint loop covers them. Not
before: the legacy path is what currently serves legacy apps.

---

## 7. How we would know it worked

Not "it feels smarter". Four concrete things, all of which have a recorded
failure to compare against:

1. **The dashboard conversation** (`docs/SMITH-VERBS.md` §1): "yes please" after
   an offer to build a dashboard produces a dashboard, not "the current state
   already matches."
2. **A UAT replay** (16 turns, ~25 min today) completes with fewer turns ending
   in a clarification the transcript shows was answerable from the Blueprint.
3. **Multi-ask messages**: asks silently dropped per message → 0, measured
   against `plan.py`'s step list rather than by reading transcripts.
4. **Unknown-verb terminations** fall, *without* `REQUIRED_BY_VERB` gaining an
   entry. If closing a gap needs a new verb, the loop did not do the work.

Also worth a scoreboard column: model calls and output tokens per change turn,
before and after. S1 is allowed to cost more; S2 is expected to pay it back.

---

## 8. Open questions

- **Where does the loop live?** `smith_session.run_iteration` is the natural
  seat, but `handle_chat_v2` is the only entry that has history. Probably the
  session, with the handler passing history through unchanged.
- **Streaming.** A reasoning-chunk callback already reaches the user as a
  `thought` event. A loop makes per-step narration possible and probably
  necessary — and raises interruption, which nothing in Smith supports today.
  Out of scope here; worth its own spec if S1 lands.
- **Does the observer judge change turns too?** It judges build nodes. A change
  turn that writes a section is the same kind of event. Tempting, and it
  doubles the cost of every turn; not decided.
- **Capability narrowing.** `AGENT_REGISTRY` still declares `reads = {"*"}`
  everywhere. S2 makes narrowing meaningful for the first time. Separate
  decision, named here so it is not rediscovered.

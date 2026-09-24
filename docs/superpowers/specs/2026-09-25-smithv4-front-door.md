# Smith v4 — the loop is the front door

**Status:** built and measured 2026-09-25, uncommitted. Branch `smithv4`, from `fda48717`.
**Owner:** Smith
**Companions:**
- `2026-09-24-smith-as-a-loop.md` — §0 is the governing principle; S1–S3 and `write_page_code` are the parts v4 is built from
- `docs/SMITH-VERBS.md` — the complaint

---

## 1. Why a fourth

The Blueprint Smith's turn was: one model call decides a verb, deterministic
code does it, the turn ends. The loop spec bolted a second look onto that,
and every place the dispatcher ended a turn early had to be patched so the
loop could see it — an answer from the slice (`_last_verb = "answer"`), a
clarification from the slice (`_last_verb = "ask_user"`), an oracle's refusal
(`TurnResult.finding`). Each patch was measured to matter. Together they were
three markers on a shape that was wrong: the loop was not the front door, it
was a second opinion after the front door had spoken.

The owner's bar, stated 2026-09-24: Smith knows the whole code, fixes rather
than refuses, is the whole team. Read against Claude Code (§0 of the loop
spec), that is one structural fact — Claude Code has **no classifier and no
verb table**; its determinism is in exact tools and a world that judges the
result. A rebuild was asked for. This is it, with one refinement the owner
agreed to: **the seams are kept**.

## 2. What it is

`backend/services/smith4/`:

| | |
|---|---|
| `turn.py` | act → observe → act **from step one**. The chooser is shown the ask, the exchange, a first page and the catalogue. Reads, writes, verbs-as-tools, and the ways a turn ends. |
| `verbs.py` | the forty-nine verbs as a **table**, not a chain — each lifted from `smith_session`'s adapter into a function over `Ctx`, calling the same `services.smith.*_change.run` it always called. `set(PERFORM) == set(REQUIRED_BY_VERB)` by test. |
| `handle.py` | what the ask *is* before the loop: the carried ask, an agreed plan's next step, a yes to an import. Nothing here interprets. |
| `context.py` | the opening page — the resolver's slice plus the plan still waiting. |
| `outcome.py` | one result shape for a step and a turn; `from_seam` reads the envelope every seam returns, once, instead of twenty-five times. |

Reused unchanged: `services/smith/tools.py` (the catalogue; `propose_plan` added as a terminal), `reads.py`, `writes.py`, `loop.py` (the chooser and its prompt, now written for a first step too), every seam.

`smith_chat_v2.handle_chat_v2`'s iteration branch now calls `smith4.handle`. Bootstrap stays on `SmithSession` for now.

## 3. What the old front door did, and where it went

| before | now |
|---|---|
| `understand_ask` returns `answer` → turn ends | the chooser ends with `answer`, allowed only in a turn that changed nothing |
| `understand_ask` returns `clarification_needed` → turn ends | the chooser ends with `ask_user` — but a question with **nothing read** this turn is sent to look, once (`LOOK_FIRST`) |
| `understand_ask` returns `asks` → `plan.py` shows a plan | the chooser ends with `propose_plan(steps)`; same chips, same consent fingerprint, nothing done before the yes |
| `verbs.is_known` false → "I did not recognise that", nearest-verb chips | a name outside the catalogue is an error observation; the model picks again |
| `limits.cannot` gate → refusal | the four are ordinary verbs whose outcome is `limits.answer`; no gate, and `write_section` will close them |
| `missing_fields` → ask for the slot | `slot_options.fill_from` tries the message and the document; still missing → error observation, the model calls again or asks |
| `_perform` if-chain | `PERFORM` table |
| ground-truth checks → `needs_user` + chips | the same checks → `finding`, the loop carries on |

## 4. Structural rules (not policies about content)

- a name outside the catalogue is named, never mapped to the nearest verb
- the same call twice is refused by identity
- a question with nothing read is sent to look, once
- a finding carries on; a question for the person ends the turn
- `answer` may not add prose to a turn that changed something
- the reply is what the seams reported; an unsettled finding is added back
- `MAX_STEPS` (12), and the cap is said

## 5. Measured, same day

The loop spec's harness runs through `handle_chat_v2`, so the same two cases
ran through the new front door on the same `0l133sp2` copy. The comparison is
against the patched Blueprint Smith of the day before, not against the
original:

| case | Blueprint Smith + loop (patched) | **v4** |
|---|---|---|
| "what code decides which rentals need attention" | `answer` from slice → `read_page_code` → `answer` — 3 steps, 36s, 82k in | `read_page_code` → `answer` — **2 steps, 18s, 55k in** |
| "accepted rentals should count as needing attention" | `ask_user` from slice → `read_page_code` → `write_page_code` → `done` — 86s, 116k in | `read_page_code` → `write_page_code` → `done` — **3 steps, 80s, 90k in** |

Both answers exactly right (the constant at `view.tsx:16`, quoted; then
rewritten to include `accepted`, compiled, v103 → v104). The difference is the
absent first call: with no classifier in front, the model's first step is the
read, not an answer or a question it then has to walk back. Half the time and
a third fewer tokens on the read case; the write case sheds the clarification
detour entirely and its brief names lines 16 and 17.

3,076 tests pass in the Smith selection (16 new in `test_smith4.py`); the
same four pre-existing failures.

## 6. Not yet

Decided 2026-09-25: **self-heal, the verify pass, the journey verifier's
autofix and verify & fix are reimplemented on v4** rather than kept on the
legacy agent. Each is a turn whose ask comes from the platform instead of a
person — a runtime error, a rendered page, a failed journey — and whose steps
are the same reads, writes and verbs. That makes `agents/smith_agent.py` and
`smith_tools.py` deletable, with their consumers (`self_healing`,
`self_verify_pass`, `journey_verifier/smith_autofix`, the legacy route in
`routers/generate.py`), as a second deletion after the front door's.

- **`write_section`** — the entity, API and rules writers exposed to the loop the way `write_page_code` exposes the UI engineer. Closes `rename_entity`, `change_field_type`, `edit_api`.
- ~~Deleting the old front door~~ **Done 2026-09-25**, in two halves:
  - *Gone*: `understand_ask()` and its prompt (the module keeps only the shape
    of an understanding and the normalisers the loop applies); `SmithSession`'s
    entire iteration half — `run_iteration`, `_iterate`, `_perform`, `_loop`
    and twenty-five adapter methods, ~1,600 lines (bootstrap stays);
    `limits.cannot`; `capabilities.nearest` and its word arithmetic; the
    phrasebook's AST reading of the if-chain (it reads `PERFORM` now, and
    `move_requires` reads `tree_edit`).
  - *Kept, deliberately*: `agents/smith_agent.py` + `smith_tools.py` and their
    consumers — the second deletion, once self-heal, the verify pass and the
    journey verifier exist on v4.
  - The ~250 seam tests that drove `run_iteration` with an injected
    understanding now run through `tests/services/_front_door.py`, a
    test-only adapter that turns the understanding into a v4 turn's first
    step. Production has no such thing.
  - Four things the deletion turned up and fixed in v4: `rename` declared
    five required fields of which three were descriptions (now `element_label`
    + `target_file`); `ask_user` carried no chips; a plan proposed inside an
    agreed plan's step replaced the plan instead of splicing into it; the
    phrasebook coloured `rebuild` as acting. And a gap with known answers —
    "Which record?" — now ends the turn with those answers as chips rather
    than going back to the model. The 28 example sentences the old prompt
    quoted per verb live in `verbs.VERB_EXAMPLES` and render in the catalogue.
- **Bootstrap** through the same loop.

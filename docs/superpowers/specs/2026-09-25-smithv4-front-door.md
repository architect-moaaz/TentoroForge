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
- **`write_section`** — the entity, API and rules writers exposed to the loop the way `write_page_code` exposes the UI engineer. Closes `rename_entity`, `change_field_type`, `edit_api`.
- **Deleting the old front door**: `understand_ask.py`, `smith_session._iterate/_perform/_loop` and the adapters, `limits.py`, `capabilities.nearest`, the phrasebook's dispatcher reading, `agents/smith_agent.py` + `smith_tools.py`. After measurement, not before.
- **Bootstrap** through the same loop.

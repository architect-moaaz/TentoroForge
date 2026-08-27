# Design Brief — Rollout & Flag Promotion Guide

**Companion to** `docs/superpowers/specs/2026-08-07-design-brief.md`.
Covers the operational path from "code merged" to "brief-canonical
in prod." Written for whoever's driving UAT — you or a future me.

---

## Flag ladder (three-step promotion)

Three env flags gate the rollout. Each unlocks a strictly larger blast
radius; each has an independent rollback (turn the flag off).

| Flag | What turning it on does | Rollback impact | Recommend hold |
|---|---|---|---|
| `FORGE_BRIEF_AUTHOR=1` | Discovery writes `contracts/brief.json` per project. **Nothing downstream reads it.** | Instant. New projects stop getting briefs. Existing briefs stay on disk. | 3–5 days on UAT. |
| `FORGE_BRIEF_CONSUME=1` | component/page/figma agents inject the brief into their prompts. Antipatterns become hard-reject in prompts. | Instant. Agents fall back to old design-spec-only prompt path. | 5–7 days on UAT, with SV pipeline running. |
| `FORGE_BRIEF_CANONICAL=1` | (**not implemented in this session**) `design_agent` is bypassed; brief → token_compiler chain is the only path. | Emergency flag `FORGE_LEGACY_DESIGN_AGENT=1` restores. | Flip only after CONSUME has soaked 2+ weeks with critic pass rate holding. |

Rule of thumb: **only advance one rung at a time**, and don't advance
until the previous rung has produced boring, uneventful data.

---

## Step 1 — AUTHOR (safe, boring)

**Goal**: prove briefs are being authored, cached, distinctive.

Enable on UAT:
```bash
FORGE_BRIEF_AUTHOR=1
```

**Watch**:
- `[brief] cache hit for <domain>` logs on regeneration — anchors always hit.
- `[brief] LLM author for <domain>` on novel domains, ~5 s LLM call.
- `output/<id>/contracts/brief.json` exists and validates against the
  Pydantic schema.

**Eyeball 5 briefs before advancing**:
1. A vet clinic (anchor Healthcare) — should be verbatim `_HEALTHCARE`.
2. A CRM (anchor CRM & Sales) — verbatim `_CRM`.
3. A novel domain like "insurance broker" or "language-learning app" —
   LLM-authored. Check: palette hexes distinctive (not #4F46E5 default),
   type pair is deliberate (not Inter+Inter), signature moves present.
4. Same novel domain rerun — cache hit, identical output.
5. Restart backend, rerun same novel domain — cache re-primed via
   anchors only; LLM re-authors with a slightly different result. Track
   this variance in a snapshot log; large drift = prompt regression.

**Advance criterion**: 5/5 briefs pass eyeball, no antipattern hits.

---

## Step 2 — CONSUME (first user-visible win)

**Goal**: generated apps actually use the brief. No more cream+terracotta.

Enable on UAT (in addition to AUTHOR):
```bash
FORGE_BRIEF_AUTHOR=1
FORGE_BRIEF_CONSUME=1
```

**Watch**:
- SV pipeline pass rate — should hold or improve (~90%+ on the standard
  10-app rotation).
- design_critic adherence score (Angle B) — track weekly average.
- Zero antipattern hits in generated CSS across 10 rebuilt apps
  (`design_brief_critic.critique` on rendered_text).

**Compare before/after screenshots**:
- Pick 3 apps regenerated across both AUTHOR-only and CONSUME states.
- Palette, type pair, and signature moves should all shift toward the
  brief's declared values.

**Regression watch**:
- Pipeline latency +5% ceiling. Adding one LLM call at brief-author +
  extended prompts on 3 agents shouldn't exceed 5% end-to-end.
- Build success rate must not drop.
- Journey-verification pass rate must not drop.

**Advance criterion (to CANONICAL)**:
- 2 weeks with CONSUME on, no regressions.
- Critic adherence score is stable or rising.
- Zero antipattern hits in the last 10 generations.

---

## Step 3 — CANONICAL (deferred — not shipped this session)

Not implemented in this session. When you're ready:

**Prep work**:
- Delete `agents/design_agent.py` (Python file, its callers, and its
  test file). See the Phase 3 files-touched section in the spec.
- Wire `token_compiler.py` to consume brief directly (not design-spec).
- Add a migration script that back-fills `Project.brief` for existing
  projects (run `brief_author` on their stored domain).
- Add the emergency flag `FORGE_LEGACY_DESIGN_AGENT=1` to restore the
  old path if brief-canonical breaks.

**Then**:
```bash
FORGE_BRIEF_AUTHOR=1
FORGE_BRIEF_CONSUME=1
FORGE_BRIEF_CANONICAL=1
```

**Soak 1 week internally** with `LEGACY_DESIGN_AGENT` escape hatch on;
then remove the escape hatch flag entirely.

---

## Smith gets brief awareness — automatic in this commit

Smith's `<smith-design-brief>` memory line renders whenever
`brief.json` exists — no flag needed. Same for `get_brief` and
`edit_brief` tools. This means:

- Users can ask "what colors are we using?" today (once step 1 is on).
- Users can ask "make it more compact" today; `edit_brief` fires,
  `brief_loop_cascade` recompiles tokens, and `DesignBriefCard`
  renders inline.

**Do not** enable `edit_brief` in prod without also having
CONSUME on — otherwise the edit updates the brief JSON but the
already-generated app ignores it, which is confusing.

---

## Observability signals (add to your dashboard)

- **Brief authored count** — daily count of successful `brief.json`
  writes. Should track "new generations with AUTHOR on."
- **Brief cache hit ratio** — anchors + repeats vs novel-domain LLM
  calls. Anchor coverage rises over time as domains recur.
- **Antipattern hit count in critic** — should be 0. Non-zero = the
  brief-author LLM is producing bad output, or the CONSUME-side
  injection isn't landing.
- **edit_brief invocation rate** — how often users ask for aesthetic
  edits. Low = brief-loop UX is discoverable; high = base briefs
  aren't landing on the mark.

---

## What NOT to do

- **Never delete anchors** from `services.design_brief_anchors`. They
  seed the LLM few-shot corpus AND the cache. Removing one silently
  degrades LLM output quality for novel domains.
- **Never modify `BASE_ANTI_PATTERNS`** without a snapshot-test run.
  Removing a hard-reject rule means we'll start shipping the AI-default
  cluster it was preventing.
- **Never enable `CANONICAL` before doing the delete-design_agent prep
  work.** The flag currently doesn't exist in code; adding it without
  removing the old path leaves both authors racing.

---

## Rollback playbook

| Symptom | Rollback |
|---|---|
| Briefs look wrong on eyeball | `FORGE_BRIEF_AUTHOR=0`, revisit anchors + prompt |
| SV pass rate drops after CONSUME | `FORGE_BRIEF_CONSUME=0`; brief still authored, just not consumed |
| Smith `edit_brief` produces bad results | Nothing to roll back — Smith tool is behavior-driven. Tune the routing prompt in `smith_agent.py` |
| Token recompile breaks a running app | `brief_loop_cascade` failures are already swallowed; `tokens.custom.json` retains its previous value until next successful compile |

---

## Follow-ups (spec'd, not shipped)

1. **Snapshot-test corpus** — CI job that runs `author` on 20 fixed
   domains, snapshots outputs, diffs against baseline. Catches
   silent prompt-drift regressions.
2. **Full CANONICAL implementation** — delete `design_agent.py`, wire
   brief → token_compiler directly, migration script.
3. **Voice-driven content agent** — read `identity.voice` + `register`
   for plausible domain-specific seed data instead of "John Doe."
4. **Per-domain antipattern discovery** — analyze past bad generations
   for that domain, feed into brief antipatterns automatically.

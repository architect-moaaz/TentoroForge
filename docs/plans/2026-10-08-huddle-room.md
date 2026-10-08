# Huddle Room — agents settle what one agent cannot

Plan, 2026-10-08. Built on `claude/kind-wu-eb2bb1` (from `smithv4` a782d617): steps 1–5 below, uncommitted, not deployed.

## Why

Forge's agents each own their part of the app's definition: the data model, the screens, the processes, the permissions. When one part needs something from another part, nothing settles it:

- **Change requests are dropped.** An agent can ask for a change to another agent's part (`change_requests`). Only "retire this item" is ever carried out (`corrections.apply_corrections`); everything else is collected into the run report and dropped.
- **Unrepaired findings ship.** The observer sends a finding back to the node's own author for two rounds, then marks it out of sync. Across 258 local runs on 57 apps there were 585 repairs and **220 findings still unrepaired**, close to one per build. Many need a *different* agent:
  - "age has no 1–120 range, and no data constraint exists": the fields author can't create constraints; the data-model agent owns them.
  - "REQ-009 was retired as a duplicate but is still in the requirements": the requirements agent's part.
  - A page "declares edit, but nothing updates the record": the page or the process.
- **Faults with an unclear owner loop.** TCommerce's admin hit 403s. Smith rewrote the permissions six times (REQ-018 to REQ-023), because the cause sat between permissions, processes and screens and no single owner could see it.
- **Big decisions are judged alone.** The data model is reviewed by one critic, never by the agents that must build screens, processes and permissions on it.

## What a huddle is

The agents that own the parts involved meet. Each states its view, a chair (the observer) decides, the owners carry out the decision, and the result is checked. You watch it happen and can overrule it afterwards.

There are two kinds.

### 1. Review huddle: at a big decision, inside the build

- **When:** a node is a big decision when it is made once for the whole app (not per page or per record type) and five or more other agents read what it writes. This is derived from the build graph and the agents' read scopes, not listed. Today that is `data_model`, `page_contracts`, `workflows` and `security`.
- **Who:** the agents that build on it, at most three, chosen by how much of their own work depends on it.
- **How:** it is part of the observer's judgement of that node. Each builder answers one question: can I build my part on this, and if not, what exactly is missing or wrong? The objections become findings, and the existing repair loop sends them to the owner as its brief. Rounds, holding back dependents, and refusals all stay as they are. A builder's objection the owner cannot meet is carried to a deadlock huddle.

### 2. Deadlock huddle: after the build, for what one agent could not settle

- **When:**
  - an observer finding still unrepaired after its rounds that names another agent's part;
  - a blocked node;
  - an agent's change request to another agent's part.

  (Later: a failed expected-behaviour statement whose owner is unclear.)
- **Who:** the owners of the parts the finding names (from the verification section-owner map), at most three, with the observer chairing.
- **How:**
  1. Each owner states its position in parallel: what it sees, what it would change, and what it needs from the others.
  2. The chair decides: one decision, a reason, a brief for each owner who must change something, or a deadlock with the question to put to the person.
  3. Each brief re-runs its owner through the same seam Smith uses (`section_change.rerun`).
  4. The observer checks the finding again.
- **Placement:** it runs before page repair, process trials and the app check, so the definition is settled before code is mended.

## What every huddle leaves behind

- **A record:** `.forge/huddles/HUD-nnn.json` holds the topic, the trigger, the participants, each position, the decision, the briefs, and what happened after.
- **A binding decision:** written to the Blueprint's `decisions` with `source: "huddle"`, so later agents respect it (§20).
- **Ledger lines:** `huddle:start`, `huddle:position`, `huddle:decided` and `huddle:deadlock`.
- **Events** on the project event stream (`/api/projects/{id}/events`): `huddle` for the panel, and `office` events for the meeting room.

## What you see, and how you overrule

- **Office view:** a meeting room, the tenth room. The participants walk in, each position shows as a speech bubble, the decision shows above the chair, and they walk back to their desks.
- **Smith panel:** a card for each huddle with the topic, who took part, the decision and its reason, and an **Overrule** box. Overruling starts a Smith turn with your words and the huddle's record. The decision is superseded by yours (`approvedBy: "user"`), and the owners are re-run.
- **Deadlocks:** an undecided huddle appears as a question in the Smith panel. The build does not wait for it.

## Guardrails

- **Bounded:** at most three participants and two rounds. Positions use the agent's own read scope and medium effort.
- **No decision without action:** every decision either briefs an owner or records that nothing needs to change, with the reason.
- **No decision without a check:** the finding is judged again after the briefs land. A huddle that changed nothing it meant to is recorded as unresolved.
- **Off switch per project** for cost measurement, not a feature flag: `application.huddles: false` in the Blueprint.

## Cost (estimate, to be measured)

- **Per huddle:** about 3–4 calls for positions plus one for the chair, at medium effort, roughly $0.20–0.60.
- **Per build:** about 4 review huddles plus 1–2 deadlock huddles, roughly $1.5–4 more, plus the repairs they cause. This must be measured on a real build before it is turned on for everyone; the target is a build under $20.

## Build order

1. **Core** (`services/huddle/`): the record, participants, convene (positions in parallel, then the chair), the decision written to `decisions`, briefs dispatched, ledger and events. Contract: `Decision.source` gains `"huddle"`.
2. **Deadlock pass** after the build, before page repair.
3. **Review huddles** inside the observer for big-decision nodes.
4. **Office meeting room** and events, and feed the office from build runs too (today only Smith turns feed it).
5. **Smith panel card** and overrule.
6. **Measure** on a real build: cost, number of huddles, and unrepaired findings before and after.

## Status (2026-10-08)

**Built:**
- `services/huddle/room.py` holds the record, who takes part, convening and carrying out.
- `services/huddle/deadlocks.py` is the after-build pass, wired into `_finish_unfinished_pages` before page repair.
- The observer's review huddle (`Observer._review`) is wired into the build through `anthropic_observer(..., output_dir, emit)`.
- Contract: `Decision.source` gains `huddle`, and `application.huddles` is added.
- `GET /api/projects/{id}/huddles` and `POST …/huddles/{hid}/overrule`.
- The office has a meeting room (row 3, under Verification), the observer at a desk, and the `huddle_start`, `huddle_say` and `huddle_end` events. `office_bridge.bind_office` lets build runs reach the office.
- `HuddleCards` in the Smith panel.

**Measured:** one real deadlock huddle on a copy of TCommerce v91 (the admin is refused when creating a category).
- **Who met:** security, the page designer and the requirements agent.
- **Size:** 19 s; 4 calls, about 65k tokens in and 3k out on Sonnet 5, about $0.25.
- **Agreement:** all three named PERM-034 (still PROPOSED) as the cause, and the chair decided to confirm it.
- **Carried out:** the security node was re-run through `section_change.rerun` in 39 s and moved PERM-034, 035 and 036 to IMPLEMENTED.
- **Recorded:** the decision went in as DEC-019 (`source: huddle`). An overrule wrote DEC-020, superseding it.

**Found on the way:** the chair briefed agents whose part needed no change ("no changes needed to PAGE-012"). Each brief now carries `changes`, and only `true` ones are sent.

**Not done yet:**
- A review huddle has not been run against a real model.
- The office meeting room has not been seen running: the type-check passes and every agent can path to every seat, but nothing has rendered it.
- The full-build cost has not been measured.
- Statement failures (the expected-behaviour runner) are not yet a trigger.

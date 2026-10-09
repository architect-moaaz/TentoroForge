# One engineer per app: building by proof instead of by assembly

Date: 2026-10-09
Status: proposal, for decision

## 1. Why this proposal exists

Forge's AI builds apps, yet the apps arrive incomplete, fail when used, and
Smith cannot fix them. This is not a model-quality problem. It is the shape
of the pipeline: no AI is responsible for the app working, and no AI sees the
app running while it builds.

What the record on forge-v3 shows (35 apps, 107 build runs, 95 requests to
Smith, read on 2026-10-09):

| | |
|---|---|
| Apps that shipped with no page code at all | 9 of 35 |
| Planned pages with no code | 120; another 48 routes in 11 apps written but not served |
| Author replies refused by the contract | 150; 33 never accepted |
| Observer verdicts that failed / findings left unrepaired | 54% / 214 |
| Processes with 0 steps still wired to a live page | 5, in 4 apps |
| Built apps that had statements of what must happen | 4 of 30; 23 of 169 held, 126 never tried |
| Database check skipped on forge-v3 ("docker is not installed") | 23 of 24 apps |
| Requests to Smith fixed cleanly | 9 of 95 (9%); ~30 misdiagnosed; 33 changed nothing |
| Smith turn length | median 13.6 min, max 43 min; 24 turns posted "Still working…" |
| E-commerce, tried live today | 12 of 46 statements held; its dev server restarted itself 20 times in 35 minutes |

The analysis behind these numbers is summarised in §2. This document proposes
the change that removes the causes, not the symptoms.

## 2. What goes wrong today, and why

### How an app is built now

The build is a graph of 33 steps (`services/blueprint/orchestrator.py`, the
`DAG` table) authored by 22 agent roles. Each step fills one slice of the
definition — one entity's fields, one page's details, one process's steps, one
group of statements — from a filtered view of the rest (`_READS` in
`agent_contract.py`, `context_for` in `executors.py`). Code then judges each
reply (15 contract checks, 19 completeness rules, the statement writer's own
checks) and projects the accepted definition into an app. The app is run only
at the end.

### The six causes

1. **Pieces written apart, with no shared decisions.** Pages choose their
   status filters before any process exists; a process's steps are written
   without its siblings or the rules; the page writer receives a process's
   name and purpose but not its steps (`ui_engineer._page_brief`), so it
   recomputes totals; charts and statements are written before anyone knows
   what a process writes. Business policy — currency, shipping and tax, record
   life cycles, time zone, accumulate-or-replace, what a signed-out person may
   do — has no place in the definition, so every writer invents its own. The
   page-writer prompt's money examples all say GBP. Result: E-commerce stores
   shipping 0 while its checkout shows £6.99; orders are created "pending"
   and immediately set "processing" while the merchant's list filters
   "pending"; GBP and USD on different pages; TStyle replaces the day's water
   instead of adding a glass.

2. **Partial failure ships silently.** A fan-out step counts as done if any
   subject landed (`orchestrator.complete`); refused subjects stay as holes;
   a refused page layout is only logged; page code is optional, so its failure
   degrades instead of stopping; huddles take no failed subjects; nothing
   retracts what depends on a hole. Result: pages with no code, processes with
   no steps wired to buttons (Change Password tells the user "Password
   changed" and does nothing).

3. **A dialect that invites the errors the checks refuse.** 29 of the 37
   refused process steps are format mistakes — `{{$user.id}}` with braces,
   `?? null`, expression parse errors — not wrong logic. An author gets two
   attempts and stops on the same refusal twice. Refusals go only to the
   refused author even when the cause is upstream (a declaration that promised
   a password change no action can perform). One app received the same
   `account: true` refusal in seven builds in a row.

4. **The environment that tries the app is not the one that ships, and it is
   starved.** Statements, Smith's trials and the page review run a cold
   `next dev` per use, with its own build directory, capped at 2.5 GB, given
   180 seconds to start (`page_review.RunningApp`, `dev_servers.HEAP_MB`).
   Near the cap it restarts itself and recompiles every page, 20–30 s each.
   The database check needs Docker, which forge-v3 does not have, and a skipped
   check counts as passed (`data_gate.gate_server`). Install and seed did not
   record that they had finished, so an interrupted run poisoned every later
   one (TStyle: a broken lockfile, an empty database).

5. **Reports say what was written, not what was proven.** The handover is
   sent before any checks run, counts written pages rather than working ones,
   omits failed pieces and database issues, and named logins that did not
   exist. Statements the checker could not run were reported as "0 of 46 held"
   or as "my check failing, not your app".

6. **Smith works blind.** A request carries only text — no reporter, role,
   signed-in state, page or device; screenshots are dropped on this path.
   Untargeted trials run as the sign-up role. The "try the process" tool posts
   to the API and bypasses the button, and any trial satisfies the rule to try
   first, so "the workflow works" is reported for a button that never calls it.
   The context (~90,000 characters per step) holds the whole definition and a
   90-tool catalogue but not the reported page's code, and only the last 12
   observations. A turn has 20 steps, no time budget, no journal, and writes
   its reply only at the end, so a process death loses a finished fix. About
   30 of the 95 reported faults were platform faults Smith cannot change, so
   it patched around them or said nothing needed doing. Instructions can be
   written into requirements (REQ-015).

The common root: the reasoning is split across many narrow authors, the
authority sits with rules and templates, and whether the app works is checked
once, at the end, in an environment that cannot run it.

## 3. Principles

1. **One owner per app.** An engineer agent holds the whole design and is
   responsible for the app working. Everything else is a tool it uses.
2. **Decide once, then build.** Policies, life cycles, access and the anonymous
   rule are decisions made once, recorded in the definition, and read by
   everything after.
3. **Prove by running.** The engineer builds against the running app from the
   first feature. Statements are its tests, run continuously, not a final exam.
4. **Code provides capabilities, not judgement.** The platform's job is solid
   building blocks (sign-in, data, the process engine, formatting from policy,
   life-cycle enforcement). Checks that remain are ones the engineer runs and
   reads — schema, type check, statements, the page in a browser — not
   refusals of fragments.
5. **Nothing is reported that was not proven.** Every message to the person is
   built from recorded proof; "could not check" is unproven, never passed.
6. **The same engineer changes the app afterwards.** Smith is the engineer in
   change mode, with the same environment, tools and definition.

These keep the commitments already in place: the Living Blueprint stays the
source of truth; agents decide and prompts stay neutral; no post-hoc repair
passes — building by proof replaces them.

## 4. The design

### 4.1 The Workbench — one proving environment per app

One running copy of the app per project, owned by the platform. Everything
that needs the running app uses this one copy: the build, the statements,
Smith, the Preview tab, page looks and self-heal.

**What it is made of.** Mostly parts that exist today, joined up and given a
contract:

| Part | Today | In the Workbench |
|---|---|---|
| Database | `app_databases` on the apps server; the build's data gate needs Docker and is skipped on forge-v3 | The app's database on the apps server, plus a seeded template copy that trials reset from (today's `expects.runner.Fresh`). The data gate runs against this server. |
| Schema and seed | `schema_push.push_now`, run only when the database is created | Run whenever their precondition is missing (§ below) |
| Install and boot | `assembly.install_dependencies`, `verify_build`, `verify_boot` | The same, recording completion so an interrupted step is never built on |
| Server | A cold `next dev` per use, own build folder, 2.5 GB cap, 180 s to start, restarts itself near the cap | One server per active app, kept warm while the app is built or changed, memory sized to the app, stopped by least-recent use (`dev_servers` slots, reworked) |
| Browser and logins | `expect_browser.mjs`, `expects.runner.Logins` | The same, shared by every user of the Workbench |

**The contract.** Before any use, the Workbench proves five preconditions and
re-establishes any that is missing:

1. installed — `node_modules` carries its completion marker and the lockfile
   is readable;
2. schema pushed — the database has the tables the definition declares;
3. seed applied — the seed's own marker row is present and every role has a
   login;
4. the server answers;
5. each role can sign in through the sign-in form.

A failed precondition is a platform fault: fixed, or escalated to us as an
incident, and never counted as a result for the app. Today these five are
checked in five places or not at all; their absence produced TStyle's six
builds, the empty database, 126 untried statements across the fleet, and
most of Smith's slow trials.

**Production build or dev mode.** The Workbench runs the production build —
`next build` with a persistent build cache, then `next start` — rebuilt
incrementally after a change, because it is what ships and it does not
restart itself. The person's own preview may stay on dev mode. Which mode
gives the faster change-to-proof on our apps is the first measurement of the
rollout (§7, step 1); if dev mode with proper memory proves faster, the
Workbench uses it for the build loop and the production build for the
whole-app pass.

**Uses and rules.**

- The build loop (§4.2) runs each feature's statements on it.
- Statements and page looks run on a reset copy of the database, as today.
- Smith's reproduction and proof run on it as the person who reported the
  problem.
- The Preview tab shows it.
- Self-heal reproduces the crash on it (§4.7).
- Workbench servers never report incidents as the app, so a trial can never
  start a self-heal.
- One job uses the Workbench at a time per app (§4.7); the preview is
  read-only alongside.

### 4.2 The Engineer — one agent session per app

One agent session per app, from the approved modules to handover, and the
same agent afterwards for changes (today's Smith role, §4.9). It is the only
author of record for the build-phase definition sections. It holds the whole
design, makes the decisions once, writes the app feature by feature, runs
each feature on the Workbench, fixes what fails and stops when it holds.

**Where it fits in the code.** The Smith4 loop (`services/smith4/turn.py`,
`handle.py`) and its seams are the closest existing thing: a model choosing
tools in a loop, with the definition and app under it. The engineer is that
loop given the build to do, a feature-sized context, the Workbench and
durability. The 33-step DAG stops being the author; its ordering of work
becomes the engineer's plan, and its node executors become tools.

**The build loop.**

1. **Decide.** From the approved requirements and modules, write the app's
   decisions into the definition: `policies` (§4.4), roles and who may
   self-register, the anonymous rule per action, each record's life cycle.
   The person sees these at the model review, as the modules are seen today.
2. **Data.** Entities and fields for the whole app, drafted by the data-model
   tool, accepted or amended by the engineer, pushed to the Workbench.
3. **Feature by feature,** in order of dependence (a feature is a slice a
   person would recognise: "browse and add to cart", "log a glass of water"):
   1. processes as units — declaration, steps, what they write, who may start
      them — checked against the action catalogue, including platform-owned
      actions such as password change; a process the catalogue cannot express
      is a decision taken now (a built-in action, a different design, or a
      question to the person), not a refused reply later;
   2. screens that bind to those processes' declared inputs and outputs,
      reading stored values rather than recomputing them;
   3. statements for the feature, drafted by the testing tool from the
      requirements, accepted by the engineer;
   4. build on the Workbench, run the feature's statements, read the failures,
      fix, run again — done when the statements hold, or when a failure is
      shown to be a platform fault and escalated;
   5. commit a definition version with the app files and what was proven.
4. **Whole-app pass:** every statement, every page as every role, the look
   review across pages, the arrival rule per role.
5. **Handover** written from the proof (§4.8).

Early handover stays: the person is handed the app when its first features
hold, and watches the rest land one by one.

**Context.** A pinned brief — product, decisions, entity names, module map,
the platform's capabilities — plus the current feature's slice: its
processes, screens, statements, code and latest results. Findings stay pinned
until resolved. The definition and the journal (§4.7) are the memory; nothing
depends on a sliding window of observations. Today's turn rebuilds ~90,000
characters every step and keeps the last 12 observations; the engineer's
context is smaller and stable, which is also what makes prompt caching pay.

**Tools.** Today's agents and seams, called by the engineer:

| Tool | Today |
|---|---|
| Read and write definition sections, schema-validated | `edit_definition`, `write_section`, the verbs |
| Read and edit app files, type-checked | `edit_file`, `read_page_code` |
| Write a page from a brief | `ui_engineer.compose_page`, `recode_page` |
| Draft the data model, statements, copy, seed data | the data-model, testing and content agents |
| Design decisions and page looks | design director, design system, `page_look` |
| Look at a page as a role (browser, screenshot) | `open_page` |
| Run statements — all, a feature's, one | `services/expects/runner.run` |
| Press a control as a person; query the database copy | `expect_browser.mjs`, the Workbench database |
| Research a reference product | the Brain Juice researcher |
| Second opinion on a section | the observer's review, on request |
| Ask the person | the review gates; questions only for real product decisions |

Specialists run in parallel within a feature when the engineer asks for
several things at once; the engineer remains the only author of record, and
each result is proven on the Workbench before it counts.

**What makes it different from Smith today.**

- It owns the whole app, not one request; it decides policies and life cycles
  before writing anything that depends on them.
- Its context is the feature, not the whole definition and a 90-tool
  catalogue.
- It proves by running on the Workbench from the first feature, through the
  screens, not by posting to the API.
- It is a durable job (§4.7): a journal, a time budget, one job per app,
  changes reported as they land, "carry on" resumes from the journal.
- In change mode it starts from a problem report and reproduces as the
  reporter (§4.9).

**Parallelism.** Features with no dependence on each other can be built by
parallel engineer sessions that share the decisions and the data model; the
Workbench serialises their proofs per app.

### 4.3 The Blueprint stays the source of truth

The Blueprint is still generated, reviewed and kept; the proposal changes who
writes its build-phase sections and in what order, not whether it exists.

Unchanged:

- the path from prompt to Blueprint through the two gates — requirements and
  modules are written and approved before anything is built, by the same
  agents;
- the schema, versions and change history: every section stays, every change
  is a committed version;
- the Blueprint tabs, the Design tab and the App Flow, read from it;
- projection: the platform-owned files (schema, routes, process JSON,
  navigation, SDK keys) are still generated from it, deterministically.

Changed:

1. **Who writes the build-phase sections.** Today 33 DAG steps each fill a
   slice and the contract checks judge each piece; under the proposal the
   engineer writes those sections feature by feature, with the specialists
   drafting. Each section's schema still validates every write.
2. **Three additions to the schema,** declared first as the rule requires:
   `policies`, life cycles on status fields, and `writes` on each process
   (§4.4).
3. **The order:** decisions, then data, then per feature: processes, screens,
   statements. Today pages are detailed before processes exist, which is
   where the wrong filters and recomputed totals come from.
4. **When it is proven.** Today the Blueprint is finished, projected and run
   once at the end; under the proposal every feature is run on the Workbench
   as soon as it is written, so the Blueprint is kept true by the running
   app. A person reviewing it mid-build sees features landing one at a time,
   each already proven.

### 4.4 Decisions in the definition: `policies` and processes as units

New, declared first in the zod schema (per the existing rule):

- `policies`
  - `money`: currency, how prices are shown, and the rules that compute
    amounts (shipping, tax, discounts) — or that none apply.
  - `time`: the time zone rule (per person, per app) and what "today" means.
  - `quantities`: per process that records an amount, whether a new entry adds
    to or replaces what is there.
  - `anonymous`: per action a signed-out person can reach — allowed, asked to
    sign in, or owned by a guest session.
  - `selfRegistration`: which roles a person may sign up as (empty means the
    default role only, never the request's choice).
- Life cycles on status fields: states, the initial state, allowed moves and
  who may make each move. The process engine enforces moves; screens and
  charts read states from here.
- Processes declare what they write (`writes`: fields and states) so screens,
  charts and statements bind to it.

Formatting, life-cycle enforcement, the anonymous rule and self-registration
are applied by platform code from these fields, so a page cannot disagree with
them.

### 4.5 Platform capabilities and safe defaults

Fixed in the templates every app inherits, independent of the engineer and
worth doing first:

- Sign-up takes its role only from `policies.selfRegistration` (today any
  `accountType` passes when the list is empty, so anyone can become Merchant).
- The shared form calls its success path only on success and shows refusals;
  "silent" never hides a refusal (today checkout says "Order confirmed" for a
  failed order, and TStyle's forms close and lose input on refusal).
- Built-in actions for change and reset password.
- Money and date formatting from `policies`, one formatter in the SDK.
- Seeded logins for every role are guaranteed by the Workbench preconditions.

### 4.6 What checks become

| Kind | Today | Proposed |
|---|---|---|
| Shape of the definition | zod schema + contract checks | Schema validation at write, unchanged |
| Format of steps and references | refusals (`{{$user.id}}`, `??`, source kinds) | Structured values (`{ "ref": "user.id" }`, expressions as typed nodes) so the mistakes cannot be written; existing dialect accepted where models naturally write it |
| Consistency between pieces | partly in completeness rules, partly nowhere | Follows from processes-as-units and `policies`; confirmed by statements |
| Quotas and taste (charts per dashboard, look rhythm) | refusals (`InvalidAnalytics`) | Guidance in the brief and the look review — findings the engineer weighs, not refusals |
| Does it work | statements at the end, often untried | Statements per feature on the Workbench, continuously |

The observer, huddles and page repair exist to reconcile authors who cannot
see each other. With one author they retire; the observer's review becomes a
tool the engineer can call for a second opinion.

### 4.7 Turns as durable jobs

For the build and for Smith alike:

- One job per app at a time; requests queue behind it.
- A journal on disk of every step, finding and change; the context is rebuilt
  from it, and "carry on" resumes from it.
- A time budget per turn, not only a step count; when it runs out, the job
  reports what it proved and what is left.
- Each change is reported in the chat as it lands, so a process death never
  loses a finished fix.
- Self-heal stays. It runs as a queued job on the Workbench, never beside a
  live turn, starts only from a crash the real app reported (never from a
  Workbench server), carries the incident as its problem report, and
  reproduces the crash on the Workbench before changing anything.

### 4.8 Messages from proof

The handover and every Smith reply are composed from the job's recorded
proof: which statements held, which failed and why, which could not run and
why (with the platform fault named and escalated), which pages were seen
working as which roles, and the logins that were proven to sign in.

### 4.9 Smith as the engineer in change mode

- **A problem report, captured by the panel:** who (role or signed out),
  which page, what they did, device and viewport, and any screenshot.
- **First step, set by the platform:** reproduce in the browser on the
  Workbench, as that person, on that page — through the button, not the API.
- **Context from the reported surface:** that page's code and wiring, the
  processes its controls call, their recent runs, and the related statements.
- **Fix, then prove** with the reproduction and the affected statements.
- **Platform faults go to the platform** (an incident to us) and are never
  patched around in the app; the person is told plainly.
- **Requirements take only statements of what the product must do,** written
  when the person changes what the product must do; fixes go to the section
  that owns the behaviour.

## 5. What stays, what changes, what goes

| Part | Fate |
|---|---|
| Blueprint schema, service, versions, change history | Stays; gains `policies`, life cycles, process `writes` |
| Requirements review and module review | Stay |
| Projection of platform-owned files (schema, routes, process JSON, navigation, SDK keys) | Stays, deterministic |
| Process engine and action catalogue | Stays; gains password actions and life-cycle enforcement |
| Data engine, ownership, guest ownership | Stays |
| SDK and templates | Stay; safe defaults (§4.5) |
| Statement writer and runner | Stay; become the engineer's tests |
| `compose_page`, page look, data-model / testing / content / design agents, researcher | Become tools the engineer calls |
| `app_databases`, `schema_push`, install/boot, `dev_servers` | Become the Workbench |
| Smith4 loop and its seams | Become the engineer's change mode (§4.9) |
| The 33-step DAG as an authoring pipeline; per-subject fan-out authorship | Goes; the engineer orders the work |
| Self-heal | Stays; a queued job on the Workbench with the incident as its problem report (§4.7) |
| Observer repair rounds, huddles, `page_repair`, `build_repair`, the flag-only verification node | Go |
| Refusals of format and quotas | Go (§4.6) |

## 6. Cost and time

Today's measured runs: ToroCommerce rebuilds cost $8.79 and $10.19 (34/61 and
36/60 statements held); the original run $16.55, unfinished. Output tokens are
about 70% of a run's cost. A large share of today's spend is refusals,
re-authoring, observer rounds, repair passes and rebuild loops (TStyle: 14
runs in one day). The engineer spends on building and fixing against proof
instead. One long session costs more per step than a short call, but with a
pinned, cached brief and feature-sized context the total should be at or below
today's; this is measured in step 2 of §7, not assumed.

Time to handover may grow, because every feature is proven before the next.
The person can watch features land one by one, and the early handover can
remain: hand over when the first features hold, keep building the rest.

## 7. How to get there

Each step is useful on its own and proven before the next.

1. **Workbench and safe defaults.** Production-build environment per app on
   the apps server with proven preconditions; the database check on the apps
   server; the template fixes in §4.5; trial servers never report incidents.
   The current pipeline and Smith use it at once, which by itself removes most
   untried statements, Smith's slow trials and its timeouts. Measure dev mode
   against production builds for change-to-proof time here.
2. **The engineer, proven on copies.** The build loop of §4.2 run from a
   script against copies of TStyle and E-commerce from their approved
   requirements and modules, side by side with today's pipeline. Measured:
   statements held, pages with code, holes, cost, time.
3. **`policies`, life cycles and processes as units** in the schema, the SDK
   and the engine — needed by step 2 from its first feature, so built with it.
4. **Switch the build** to the engineer when step 2 beats today's pipeline on
   both apps; retire the DAG authoring steps, observer rounds, huddles and
   repair passes.
5. **Smith in change mode:** the problem report, durable jobs, reproduction
   through the button, platform-fault routing. The problem report and durable
   jobs can start in parallel with step 2.

For Monday's competition the realistic path is today's pipeline with the
fixes already made today plus step 1's safe defaults; the engineer build is a
multi-week change and should not be rushed onto forge-v3.

## 8. How we will know it works

| Measure | Today | Target |
|---|---|---|
| Statements tried at handover | 43 of 169 | all |
| Statements held at handover | 14% | ≥ 90%, the rest named with cause |
| Pages planned that ship working | 120 + 48 routes missing across the fleet | all |
| Processes wired to pages with no steps | 5 | 0 |
| Smith requests fixed and proven | 9% | ≥ 70% |
| Smith median turn | 13.6 min | ≤ 5 min |
| Cost per app build | $9–17 | ≤ today |

## 9. Risks

- **A long session drifts or loses track.** Mitigated by the definition as
  memory, the pinned brief, feature-sized context and statements as the check
  on every feature.
- **One author is slower.** Specialists run in parallel within a feature;
  features with no dependence on each other can be built by parallel engineer
  sessions that share the decisions.
- **Design quality falls without dedicated designers.** The design system,
  looks and page look review stay as tools; the engineer must pass the look
  review as it must pass statements.
- **Losing what the current seams learned.** The seams and their checks become
  tools and diagnostics, not deleted knowledge; the rules worth keeping move
  into the schema, the engine or the SDK where they cannot be broken.
- **Production builds may be slow to iterate.** Measured in step 1; the
  Workbench may use dev mode with proper memory if it proves faster.

## 10. Decisions needed

1. Agree the direction: one engineer per app, building by proof.
2. Start with step 1 (Workbench and safe defaults) now, and step 2 on copies of
   TStyle and E-commerce.
3. Smith does not patch platform faults; they come to us as incidents.
4. A cost ceiling per app build for the engineer's sessions.

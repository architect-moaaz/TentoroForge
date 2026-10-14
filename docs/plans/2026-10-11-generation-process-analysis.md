# The generation process, measured: Ecom L1 and ECom L2 (2026-10-11)

Two complete runs of the same brief ("a multi-vendor marketplace: buyers,
vendors, an admin; one combined checkout; admin splits payouts") on two
branches, both watched end to end from the ledgers, the journals and the
usage log. Ecom L1 ran on today's code (smithv41: the engineer-owned build
with statements, Workbench and proof). ECom L2 ran on the code as it was on
the night of 7 October (smith-revamp: the graph build with the post-build
page repair, process trials and app check).

## 1. What each run produced and what it cost

| | Ecom L1 (smithv41) | ECom L2 (smith-revamp) |
|---|---|---|
| Requirements | 42 (+1 from chat) | 21 |
| Modules / screens / records / processes | 10 / 29 / 17 / 62 | 6 / 21 / 15 / 33 |
| Define + model | 25 min, $4.50 | 17 min, $4.50 |
| Build to a booting app | 45–55 min when nothing failed | 29 min |
| First ask to a booting app, as it happened | ~2 h 50 (faults stopped the build four times) | 47 min |
| After the app booted | proof of 1 of 9 features: 66 min, ~$25 | page repair 3 min, process trials 56 min, app check 38 min |
| Spend | $76 (791 calls) | $25 (753 calls) |
| Hand-over | stopped by hand at feature 2 of 9 | not handed over: state PLAN_REVIEW, Publish disabled, 10 runtime issues |

Neither run handed over a proven application. L2 was cheaper by 3× and
faster by 3× to a booting app, and the app is roughly half the size (33
processes against 62; the older requirements writer asked for less).
Per screen and per process the two branches cost about the same: L1's
screen code was $0.78 a screen, L2's $0.28 a screen without the look
review on every page and with less reasoning (L1's writer is told to use
the kit and reviewed with screenshots; L2's is not). The difference in the
totals is the proof phase ($57 of L1's $76 was statements and proof) and
the app's size.

## 2. The stages, and where the time goes

A build has five stages. The first three are the same on both branches;
the fourth and fifth differ.

**Define.** Requirements (one call, 2–3 min), then the product model in
parallel: application model, data model (2.5 min), entity fields (fan-out,
~1.5 min wall), integrations, UX architecture, then the page set (one call
of 5–7 min) and security (one call of 3–7 min). 13–17 minutes on both
branches, dominated by two single calls: the page set and security.

**Opening.** Everything the screens need, in the graph's order: design
system (1.5 min), page details (fan-out, 2–6 min), UI direction (1.3 min),
workflows (one call, 3.5–5 min), then in parallel the step graphs (fan-out
over every process, 3–7.5 min), rules (2.5 min), analytics (4–6 min) and
the app flows (4–8 min). 17 minutes on L1, 17 on L2. The critical path is
workflows → workflow steps / app flows: two long single calls and one
fan-out, each a quarter of the stage.

**Landing.** Page layouts and the data layer (seconds), screen code
(fan-out: 29 screens in 12 min on L1 with looks, 21 screens in 5 min on
L2 without), then assembly: type check, production build, database push
and seed, boot. 2–6 minutes. The assembly is the one place the build runs
the app itself, and on L1 it was where the database gate's repairs hid
for ten minutes twice.

**Proof (smithv41).** Statements of what must happen are written from the
requirements (27 calls now, 10 min, $8–10), tried in a real browser as
each role on two benches (8 min for 48 statements, no model cost), what
fails is sent back to its authors with what the trial showed (page
rewrites, 6 min in parallel, $6), then unattended fix turns (10 min and
$2.50 each). The first feature took 66 minutes and ended with 23 of 48
statements holding. Now reshaped to one pass over the whole app with at
most six fix turns that stop after two in a row fix nothing; unmeasured.

**Checks (smith-revamp).** Page repair for screens written without their
contracts (3 min), then process trials: every process run once as its
role, each failure repaired by its author and run again (25 processes,
56 minutes, $4.40, 8 still not running through), then the app check:
every page opened as every role and every control pressed (21 pages, 38
minutes, $2.56, 14 pages sent to repair). The checks run inside the build
turn, so the tester sees "building" and a disabled Publish for an hour
and a half after the app booted, and the state never moved past review.

## 3. What actually consumed the day

Ranked by hours lost, across both runs:

1. **Validators and checks that were wrong.** A checker demanded a direct
   rule on a `through` target the engine walks fine; the edit it forced
   demoted four vendor rules to prose. A sample-reference check read a
   primary key and a tax number as foreign keys and sent entity authors
   through two repair rounds with a production build after each. The app
   check on L2 sent ten pages to repair because its own screenshot script
   failed (`page_shots.mjs:154`). Each wrong check costs a model call to
   satisfy and often a rewrite that makes the app worse. This is the
   single largest class, and it compounds: the fix turns then spend more
   money on faults that were never in the app.

2. **Single calls at the output cap.** The statements writer with 62
   processes in one call was cut off at 32,000 tokens three times, then
   at 64,000 once (seven minutes each). The page set is one 7-minute
   call; workflows one 5-minute call; app flows 8 minutes on L2. A call
   that cannot finish inside its budget is thrown away whole.

3. **Serial proof and repair.** Features proved one after another, pages
   rewritten one after another with a look review each, repairs run one
   process at a time. The page rewrites went from 25 to 6 minutes when
   run in parallel; the rest is now reshaped but unmeasured.

4. **Silence and false stops.** "Building…" with nothing moving for
   25 minutes; a stopped opening answered "already built"; a restart that
   left the panel disabled; "Done." from a turn that changed nothing.
   None of these cost model money directly; all of them cost the
   person's trust and led to killed runs and rebuilds.

5. **Platform gaps that no repair can close.** A public catalogue could
   not be read by a signed-out visitor because a scope rule had no way to
   say "everyone reads, the owner writes"; image fields are seeded empty
   so every card showed a broken picture; the live-refresh client logged
   an error on every public page that the trials counted against every
   control. The fix turns correctly reported the first as a platform
   fault; the proof loop cannot fix these, only find them.

## 4. What is true of both branches

- The graph itself is sound: given a definition, it writes screens and
  processes that compile, build, seed and boot. L2 booted in 47 minutes
  with zero node failures past page details; L1's landing passed every
  time it was reached.
- Nothing proves the app without a browser. Statements (L1) and the app
  check (L2) both found real faults a screenshot review cannot: a stock
  cap that made the refusal unreachable, a checkout link that times out,
  a "Go to Vendor Dashboard" that lands on 403, eight processes that do
  not run through.
- Repair by an unattended agent is expensive and low-yield when the
  cause is a platform gap or a wrong check: four turns on L1 held four
  statements for $10; L2's process repairs left 8 of 25 unfixed after
  an hour.
- The person cannot see what is happening. Both branches narrate per
  phase at best; neither says "this is the check's fault, not the app's".

## 5. What to change, in order

1. **Every check is held to the engine.** A validator may refuse only what
   the runtime would refuse, and must be tested against the runtime's
   own behaviour (the ownership chain, the sample references, the
   `$user.id` template, the screenshot script). A check that cannot say
   how to satisfy itself does not refuse. This removes the largest cost
   class and most of the wasted repairs.
2. **No call near the cap.** Split the page set per module, the
   statements per four processes (done), workflows by module; a reply cut
   off is never retried at the same budget (done).
3. **Prove the whole app once, repair by cause, cap by yield** (done,
   unmeasured). Then make repair an action the person chooses, not a cost
   every build pays: the build reports "23 of 48 hold" and offers to fix.
4. **Hand over before the checks.** The app is the person's the moment it
   boots; Publish is enabled then; the checks run after and report. L1
   already does this in design; L2 does not.
5. **Say what is happening and whose fault it is.** Node starts in the
   chat (done), the office's pipeline strip, and "could not be tried: the
   check's browser failed" as a distinct sentence from "does not work".
6. **Close the three platform gaps found**: public reads (done), seeded
   pictures (the Picture part, done; real images need an image source),
   the live-refresh probe (done).

## 6. What a clean run should cost now

For an app of L1's size (29 screens, 62 processes) on smithv41 with the
fixes landed and nothing failing: define 25 min and $4.50; opening 17 min
and $12; landing 12 min and $17; statements 10 min and $9; one proof pass
and capped repair 30–45 min and $15–20. About 95 minutes and $55 to a
proven hand-over, or 55 minutes and $35 to a booting app with a verdict.
For an app of L2's size, roughly half of each. These are estimates from
the ledgers, not measurements; one run that completes without a platform
fault is the measurement this document still lacks.

## 7. What changed on smith-revamp after this analysis (2026-10-11, afternoon)

Built from the plan the owner approved ("hand over, then fix to green";
"a domain reference the build writes first"); commits aae4d540 and
3b94d9f2 on `smith-revamp`, with twelve smithv41 fixes carried over
between them (ownership chains, database-gate false findings, `reads:
"everyone"`, orphan ledgers, USR1 stacks, the Picture part, live-refresh
probe, built = runtime.build stamp, three prompt/template fixes).

- The build turn ends the moment the app boots: "Your application is
  built" + logins + a six-criterion **scorecard** (`runtime.scorecard`);
  Publish lights within seconds; the checks run in the background and
  speak into the transcript; the panel shows a strip, never "Building…".
- Checks: routes over HTTP (guest → sign in, wrong role → 403), access
  as two people of each role, every gated rule tried with an input it
  must refuse, processes run through, the domain scored against the
  reference. A check's own failure is `untried`, never repaired.
- One fix loop over every red by cause (pages three at once, the rest
  alone), capped at six turns and two dry turns, each green said.
- Stop is a file the orchestrator and the checks read; a stopped build
  hands over what booted.
- `domainReference` written by a new `domain_reference` node after the
  requirements, shown at the first review, held to by every model node
  (answer by name or decline with a reason), scored at the end.

**Measured so far.** On the built ECom L2 (rwt6ef5p), the route check
found 8 reds and the access check 16 — all three causes were the
check's, not the app's, and are fixed: the back-office ranking tied
Vendor with the role named Admin and took the first (so the seeded
administrator was a Vendor); a trial "as Admin" resolved to that computed
role; the access check treated a person the users table never saw as a
leak. After: 78 of 78 routes green; 17 of 24 access green, 0 red, 7
untried for want of rows; ~90 s on a running copy, no model calls.

A fresh end-to-end run (ECom L3, fv3d6h4y) got through define, the
reference node (15 screens, 6 records, 4 processes, 5 rules with refused
cases, 4 benchmarks; held to by the model: 26 of 34 items answered by
name before the rules node ran) and the model phase, then **paused on an
exhausted Anthropic credit balance** at the opening (20 min, $4.93 to
that point). The hand-over, the background checks and the fix loop are
therefore proven by tests and by the L2 smoke, not yet by a complete
build. Two things the aborted run showed: a chat approval sent before any
definition exists runs the graph from an empty description (an API-only
path; the panel cannot do it), and the reference's sub-domain was a
"single-vendor storefront" for a brief that said "multi-vendor
marketplace" — because that brief never reached the Blueprint on that
path, not because the node ignored it. Re-run with credit: start a
project from the panel, answer Smith's language question, approve the two
reviews, Build; expect the card at ≈ the graph's end and the checks to
report into the chat afterwards.

## 8. Two builds on the fixed platform, through the panel (2026-10-11, evening)

Same marketplace brief, started from the panel as a tester would, after the
credit top-up. The hand-over, the scorecard, the background checks and the
panel's strip worked on both.

| | ECom L4 (7ttp60zi) | ECom L5 (6132cfss) |
|---|---|---|
| First ask → requirements | 3 min 15 s (after a colour question waited 20 min for an answer) | 2 min 30 s |
| Product model | 2.5 min, stopped on a platform catch-22 (two login entities) | 9 min, clean |
| Build to a booting app | 29 min graph + 7 min assembly, resumed twice (the second time after a 33-min deadlock in the database gate's repairs) | 29.5 min, uninterrupted |
| First ask → hand-over | 1 h 44 min as it happened | **42 min** |
| Spend to hand-over | $16.72 (381 calls incl. Smith changes: $19.22) | $16.36 (343 calls) |
| Pages served | 22 of 22 | 21 of 21 |

**Platform faults found by using L4 and fixed before L5** (all with tests,
on smith-revamp): two login entities deadlocked the data model (`one_login`
decides); the database gate's parallel repairs deadlocked the assembly
(sequential, from smithv41 7612ec7d); a `role_restricted` page naming no
role became the administrator's, so a vendor got 403 on their own
catalogue (refused at the author); a mask hint matched "ssn" inside
"businessName", masking every vendor's name (whole-word hints); integers
were seeded as the row number, never their examples (prices of 1, 2, 3
cents; a cart line of 14 against stock 7; subtotal US$0.00); the app's
client calls to its own API ignored the preview prefix (404 on add-to-cart
behind the proxy) and the sign-in landing doubled it; the engine's
expression parser had no `??` (the checkout commission formula was refused
at the opening); a crashed process trial left the logic criterion blank
(now untried with the reason, and the trial retries a dropped connection).

**What L5 showed working:** storefront, search, categories, product pages
with variants and vendor; sign-in per role landing on its own page
(`/`, `/vendor`, `/admin`); vendor pages gated to Vendor; admin pages gated
to Admin; vendor names and emails as they should read; prices from the
model's own examples; add-to-cart reaching the workflow API under the
preview prefix (answered 422 for a guest — the app's rule, not a 404).

**Still open after L5:** money fields in minor units are formatted by each
page as major units ("$8,900.00" for 8900 cents) — a page-writer rule or an
SDK money part is the shape; the seeded demo vendor is Pending, so the
vendor's own catalogue says "only an approved vendor can view this page"
(the seed should approve the demo login's own vendor record); the
preview proxy sends a signed-out visitor of the app to the platform's own
login; the Preview pane's "Built in N stages" card says built after a run
that skipped everything; the panel polls `/app-model` and gets 404 on
every tick before the app exists; 19 modules for 19 screens (one module per
screen) from ux_architecture; the background checks' first round (one
browser pass per role over 21 pages, controls pressed) takes 20–25 min.

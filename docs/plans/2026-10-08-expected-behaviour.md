# The AI says what must happen, and tries it

Sketch, 2026-10-08. Steps 1–5 built (uncommitted, smithv4 worktree); see **Status** at the end.

## Why

The three faults testers found in TCommerce and ToroCommerce were:

- a deactivated product still showed in the shop;
- Add to Cart failed;
- the admin landed on the home page after signing in.

None of them was a wrong decision by the AI. TCommerce's definition already says each of these things:

- RULE-003: "Shoppers … only ever see products whose isActive flag is true".
- REQ-004's criterion: "Shopper can add a product to the cart".
- The landing map: Admin starts on `/admin`.

Hand-written platform code did something else, and nothing ever tried the app the way a person would. The evidence:

- **The criteria were never run.** Every requirement carries `acceptanceCriteria`, but the only code that reads them is the requirements review screen (`services/smith/gates.py`), which displays them and nothing more.
- **Our checks skip the paths people use.** `page_shots.mjs` signs in through NextAuth's API, not through the form. So the form's landing fault was invisible to every check we had.
- **Smith wrote mechanisms, not behaviour.** When the tester complained, Smith recorded REQ-017 ("Change initialRoute … set the map as …") and five near-identical requirements, REQ-018 to REQ-023 ("change PERM-001…PERM-019 to CONFIRMED"). The behaviour was never stated, so it was never tried. Smith kept rewriting the mechanism.
- **Each fix added a hand-written check for one fault.** The sign-in landing check (`app_check.arrival_findings`) signs in as the admin only and looks only at landing. The next fault would need the next such check.

## The shape, in one sentence

The AI states what must happen for each action, in the app's own words. One generic runner tries every statement in the running app, as that person. A statement that fails goes to the AI that owns the fault, which may change any file. The fixer may not change the statement.

## A statement

A statement uses the app's own roles, screens, record types, fields, processes and rules, plus a fixed set of verbs that every web app shares. There are no domain words in the code or the prompts.

```yaml
- id: EXP-054
  says: "When the admin deactivates a product, shoppers stop seeing it; the admin still does."
  covers: [REQ-012, RULE-003]
  kind: cross-person
  given:
    - Product: { name: "Linen Shirt", isActive: true }
      with: [ ProductVariant: { size: "M", stockQuantity: 5 } ]
  steps:
    - as: Admin
      on: PAGE-013            # "the product's edit screen"; bound when pages exist
      do: "turn the product off and save"
  then:
    - as: Admin,  on: PAGE-011, sees:     { Product: "Linen Shirt", shown_as: "inactive" }
    - as: guest,  on: PAGE-002, not_sees: { Product: "Linen Shirt" }
    - as: guest,  opens: "Linen Shirt's own page by its address", gets: not_found
    - stored: { Product: "Linen Shirt", isActive: false }
```

**The vocabulary is the whole capability.** It's the part we build once, for every app:

| | |
|---|---|
| **who** | a role · `guest` · `new person` (signs up during the statement) · a second person of a role (for "another shopper must not see …") |
| **given** | records that exist, in the app's record types, with field values and owners · who is signed in · where they start · the clock (`now`) |
| **steps** | `open` a screen or an address · `do` "<what the control does, in words>" · `fill` a field · `choose` · `sign in` (through the app's form) · `sign out` · `reload` · `come back later` (same browser) · `switch` to another person · `wait` for a background job or a time |
| **then** | `on` a screen (where they ended up) · `sees` / `not_sees` a record or text · `told` success, refusal or error, and what about · `gets` not_found, sign_in_asked or not_allowed · `stored`: a record exists, has changed, is gone, or a count · `sent` an email or notification to someone (captured from the outbox) |
| **covers** | the requirement and rule ids it proves |
| **kind** | arrival · reach · action · rule · cross-person · journey · first-use · recovery · background |
| **origin** | requirements · rule · the person's words · a report (Smith) |

## Who writes them, and when

**1. The architect writes them at the requirements stage, before any screen exists.** Each requirement gets at least one statement per criterion. Each rule gets its refusal and its edge case. Each role gets its arrival, and each restricted area gets its reach check (who gets in, who is turned away). These replace the prose `acceptanceCriteria`.

The review shows them as plain sentences:

> "When the admin deactivates a product, shoppers stop seeing it; the admin still does."

**2. Writing them surfaces the questions an architect asks.** A statement has to say what is observable. Where the requirements don't decide, the writer can't write one and asks at the review instead. TCommerce raises six such questions (see the end of this document). Today these are silently decided by whichever agent writes the page.

**3. Screens are bound after the pages exist.** A statement written as "the product's edit screen" gets `on: PAGE-013` filled in by the page planner. If a statement names a screen that doesn't exist, the page plan is refused.

This is a shape check on the definition. It is not a behaviour check.

**4. Every behaviour Smith is asked for becomes a statement first.** A complaint is recorded as a statement that fails today. "Admin lands on the home page" becomes EXP-001, failing. Smith's fix is done when EXP-001 passes.

This is the reproduce-first rule (try the fault before fixing it), satisfied by construction. REQ-017 to REQ-023 would have been one statement, not seven mechanism instructions.

## The runner — one, for every app

1. **It plays the person in a real browser.**
   - Playwright, one context per person.
   - Sign-in goes through the app's own form.
   - Guests get their own cookie jar.
   - It reuses `page_shots.mjs`'s engine and the trial bench Smith already uses: the copy of the app's database, `fill_records` and `default_person`.
2. **The starting state is built through the app.** `given` records are created through the app's data API, as the role that owns them, on a fresh copy of the database. Each statement starts from the same copy (`CREATE DATABASE … TEMPLATE`).
3. **A small model finds the right control the first time; after that, replays run without one.**
   - **First run:** a small model reads the page's accessibility tree and picks the control for `do: "add size M to the bag"`.
   - **Recipe:** the pick is stored as a recipe (role plus accessible name), in `.forge/expects/recipes.json`.
   - **Replays:** these are deterministic and free.
   - **Self-heal:** a recipe that no longer finds its control is resolved again.
   - **No control:** "nothing on the product page adds it to the bag" is itself the finding.
4. **Code judges the outcomes, not a model.** Each kind of outcome has a mechanical test:

   | Outcome | How code checks it |
   |---|---|
   | `on` | the URL against the page's route |
   | `stored` | a query on the database copy |
   | `sees` / `not_sees` | the record's identifying field in the page's visible text |
   | `told` | a status or alert element in the page, plus whether the call was refused (422) or failed (500) |
   | `sent` | the outbox |

   A vague outcome ("shows a summary of sales") is rewritten by the writer into a checkable one ("revenue equals the sum of the placed orders' totals"). A model-judged outcome is the exception, and it is marked as one.
5. **Every step keeps its evidence:** URL, screenshot, browser console, server log lines, and refused or failed calls with their response bodies. That's what the fixer gets.

## When it runs

| When | What | Replaces over time |
|---|---|---|
| Build, after pages | all statements | `app_check.arrival_findings`, `flow_move_findings`, the process-trial runs, page review's click probes |
| Each Smith turn | the statement for the ask, plus statements touching what changed, plus one per role's arrival | the turn's own trial checks: the reproduce-first and done-means-tried rules (`_still_failing` / `_new_failures`) |
| Before publish | all | — |
| After publish, on the live URL | sign-in and read-only statements, using the seeded test logins | nothing today (this is the ihf6pjga class: a fault that only appears after publishing) |

## When one fails

- **During the build:** the finding goes to the agent that owns the fault, through the observer loop, as findings already do. What's left over ships as `runtime.issues`.
- **After the build:** Smith gets it. It runs the statement to see the fault and may change any file, including platform code inside the app (`edit_file`, with patches registered). It's done when this statement passes and nothing that passed before now fails.
- **The fixer can't change the statement.** Changing what should happen is a requirements change: the person is told ("I changed what should happen: …") and it shows in the review. This guardrail stops the AI from grading its own homework.

## What the existing checks become

Every check we have asks whether the app is **broken**. None asks whether it is **right**, because none knows what right is. That is why all three TCommerce faults passed.

| Part | Answers today | Missed in TCommerce because | Becomes |
|---|---|---|---|
| `app_check` (build end) | Every page as every role on a copy of the database: crashes, browser errors, swallowed reads, "undefined"/NaN, raw ids, 2001 dates, placeholder text, 404s; every control pressed from a fresh load. | The shop loaded and showed products with no error; it can't know one of them shouldn't be there. "Add to bag" pressed with no size chosen was refused, and since 9cdcecb2 a refusal counts as an answer, so it can't tell a right refusal from a wrong one. It signs in through the NextAuth API, never the form. | Its universal screen checks (no crash, no "undefined", no raw id, no 2001 date) run inside every statement as background checks. Its browser, role sessions and database copy are the runner's engine. Purposeless fresh-load presses, `arrival_findings` and `flow_move_findings` are retired. |
| `process_trials` (build end) | Every process once, as its role, with model-written inputs called straight in: does it finish and write. | It sent a quantity; the page sends none, and that was the bug (`{{quantity ?? 1}}` came out empty). | Statements run processes from the page, with what a person enters. A process no statement reaches gets one written for it, so coverage is kept. |
| Smith's trials (`try_workflow`, `try_request`, `open_page`) | What Smith chose to ask during a turn. | — | Stay as Smith's tools for exploring. Running the statement is how a turn reproduces the fault and proves the fix, so "done" is no longer Smith's own judgment. |
| page_review / page_look | Does it look right. | — | Stay. Look isn't behaviour. |
| Contract checks / observer | Is the definition well-formed. | — | Stay, and also check that statements name what exists. |
| The test suite (16,458 tests) | Forge's own code, with made-up inputs. | The data-engine tests passed real booleans; apps send the text "true". | Stays. Each runtime capability (filters, guests, sign-in) also gets one test through the path a generated app actually uses: one per capability, not one per bug. |

## What stays hand-written

- **Shape checks:** is the definition well-formed, and does every reference resolve. This includes contract refusals, typecheck, and screen binding.
- **Look:** page_look and the page reviewer, because visual quality isn't behaviour.

The rule from here on: **code may check shape; only statements check behaviour.**

## Why this works for every app

The code and prompts know only people, screens, records, processes, rules and time. TCommerce's statements below are generated from TCommerce's definition, not written by us. The same verbs carry other domains, for example:

- **A clinic booking app:** "When a patient books the 10:00 slot, a second patient no longer sees it; the doctor sees it in tomorrow's list" (`given` slots, `switch` person, `not_sees`, `sees`).
- **An internal leave tool:** "When a manager rejects a request, the employee is told why and their balance is unchanged" (`told`, `stored` unchanged).
- **A background reminder:** "With the clock set to the day before the appointment, the patient is sent a reminder" (`given now`, `wait`, `sent`).

What a browser can't see needs a stand-in, decided once per capability, never per app:

- **Payments:** the provider's test mode, or a stated "not connected" outcome.
- **Email and notifications:** the outbox.
- **Time:** the runner sets `now` on the database copy.
- **Uploads:** fixture files.
- **Camera and maps:** stubs.
- **External APIs:** the provider's sandbox, or a recorded reply.

## TCommerce's statements

These are the statements the writer would produce from the definition on forge-v3 (`ihf6pjga`). It has 14 product requirements and 7 rules; REQ-015 to REQ-024 are Smith's recorded instructions.

Some statements are marked:
- **⚑** marks a fault a tester actually found.
- **?** marks a statement the writer can't finish and asks at the review.
- **✗** marks one I expect to fail today, from reading the code. That isn't verified.

### Arrival and reach (from roles, access and the landing map)

| id | statement | covers |
|---|---|---|
| EXP-001 ⚑ | The admin signs in from the sign-in page → lands on the admin dashboard. | landing map, REQ-009 |
| EXP-002 ⚑ | The admin presses "Sign in" in the home page header and signs in → admin dashboard, not the home page. | landing map |
| EXP-003 | A shopper signs in from the header → the home page, where the header now shows their account instead of "Sign in". | landing map |
| EXP-004 ✗ | A guest at checkout presses "Sign in" and signs in → back at checkout, with the same bag. | REQ-005 |
| EXP-005 | A guest opens their order history by address → asked to sign in; after signing in, lands on their order history. | REQ-007 |
| EXP-006 | A shopper opens any admin screen by address → not allowed, and no admin data in the page. | access |
| EXP-007 | A guest opens an admin screen → asked to sign in. | access |
| EXP-008 | Someone signs in with a wrong password → told the email and password don't match, and stays on sign-in. | auth |

### Storefront

| id | statement | covers |
|---|---|---|
| EXP-010 | A guest visits the root → the home page, without being asked to sign in. | REQ-001 |
| EXP-011 ⚑ | Given 3 active products in 2 categories and 1 inactive product, a guest opens the shop → sees the 3 active ones and not the inactive one. | REQ-002, RULE-003 |
| EXP-012 | A guest filters the shop by one category → sees only that category's active products. | REQ-002 |
| EXP-013 | A guest opens an inactive product by its address → not found, not the product. | RULE-003 |
| EXP-014 | A guest opens a product → sees its name, price, sizes, description and image. | REQ-003 |
| EXP-015 | Given a product whose sizes all have zero stock → the shop shows it as out of stock, and its page offers no way to add it. | RULE-007 |

### Bag

| id | statement | covers |
|---|---|---|
| EXP-020 ⚑ | A guest on a product page chooses size M, quantity 1, and adds it → told it was added; the bag shows one item in size M; a cart item exists in the guest's cart. | REQ-004 |
| EXP-021 | A guest adds an item and comes back later in the same browser → the bag still holds it. | REQ-004 |
| EXP-022 | A second guest, in another browser → their bag is empty. | ownership |
| EXP-023 | A shopper changes an item's quantity to 2 in the bag → the line total and subtotal double; the stored quantity is 2. | REQ-004 |
| EXP-024 | A shopper removes the only item → the bag says it's empty; the cart item is gone. | REQ-004 |
| EXP-025 | Given size M has stock 2, a shopper sets the quantity to 3 → refused and told only 2 are left; the quantity stays as it was. | RULE-002 |
| EXP-026 ? | A guest adds an item and then signs in → does the bag come with them into their account? | REQ-004, REQ-005 |

### Checkout

| id | statement | covers |
|---|---|---|
| EXP-030 | A guest with one item goes to checkout → isn't asked to sign in or create an account. | REQ-005 |
| EXP-031 | A guest fills in shipping and contact details and places the order → the confirmation shows an order number, the items and the total; the order is stored with the guest's name, email and phone; the bag is empty. | REQ-005, REQ-006, RULE-001 |
| EXP-032 | A guest leaves the email blank and places the order → refused and told the email is needed; no order is stored. | RULE-001 |
| EXP-033 | A placed order's total equals subtotal + shipping + tax, both on the confirmation and as stored. | RULE-005 |
| EXP-034 ? | Placing an order reduces the size's stock by the quantity bought. Not stated anywhere; the writer asks. | RULE-002 |
| EXP-035 ? | The payment gateway is PROPOSED, not connected → is the order placed as unpaid, or is checkout blocked? REQ-005 says "complete payment". | REQ-005 |
| EXP-036 ? | After an order is placed, a confirmation email is sent to the guest's address. Email is PROPOSED; the writer asks. | REQ-006 |
| EXP-037 | A signed-in shopper places an order → it appears in their order history. | REQ-007 |

### Shopper account

| id | statement | covers |
|---|---|---|
| EXP-040 | A shopper with 2 orders opens their order history → sees both, with status; doesn't see another shopper's order. | REQ-007 |
| EXP-041 | A shopper opens another shopper's order by its address → not found. | REQ-007, ownership |
| EXP-042 | A shopper edits their name and phone and saves → told it's saved; after a reload the new values show. | REQ-008 |

### Admin console

| id | statement | covers |
|---|---|---|
| EXP-050 | Given 3 placed orders totalling X → the admin dashboard shows revenue X and 3 orders. | REQ-009 |
| EXP-051 | The admin creates a product with a name, price, category, size M with stock 5, and an image → it appears in the admin list; a guest then sees it in the shop with its image and size M. | REQ-010 |
| EXP-052 | The admin saves a product with price 0 → refused and told the price must be above zero; nothing is created. | RULE-004 |
| EXP-053 | The admin changes a product's price → a guest's product page shows the new price. | REQ-011 |
| EXP-054 ⚑ | The admin deactivates a product → it stays in the admin list, marked inactive; a guest no longer sees it in the shop or by its address. | REQ-012, RULE-003 |
| EXP-055 ? | The admin deletes a product → a guest no longer sees it. What does a past order that contained it show? | REQ-012 |
| EXP-056 | The admin sets an order to shipped → the admin sees "shipped"; the shopper sees "shipped" in their order history. | REQ-013 |
| EXP-057 | Given a shipped order → the admin isn't offered "cancel", and trying it directly is refused. | RULE-006 |
| EXP-058 | The admin opens customers → sees the registered shoppers. | REQ-014 |
| EXP-059 | The admin edits a customer's phone and saves → it's saved. | REQ-014 |
| EXP-060 ? | The admin deactivates a customer → can that customer still sign in? | REQ-014 |

### Journeys (statements chained into one person's path)

- **J-1:** a guest buys. Home → shop → product → add size M → bag → checkout → confirmation → (signs up) → the order is in their history. Chains EXP-010, 011, 014, 020, 030, 031 and 037.
- **J-2:** the admin lists a product, a shopper buys it, the admin ships it, and the shopper sees it shipped. Chains EXP-051, 020, 031, 056 and 040.

**Size of the set:** 43 statements and 2 journeys; 6 questions for the review. All four faults testers met (the three above, plus the landing from the header) are statements the writer produces from requirements that already existed. Writing them needed no knowledge of the faults.

## Cost and time (estimates, not measured)

- **Writing:** one call per module at the requirements stage, and one binding pass after pages. About $0.30–0.60 per app.
- **First run:** about 43 statements × 3 steps on a small model, reading a trimmed accessibility tree. About $1; replays cost nothing.
- **Time:** about 15 s per statement, run serially on one app server with the database reset between statements. That's about 10 minutes for TCommerce.
- **Running in parallel:** this needs one server per database copy, which is the memory limit that caused the UAT out-of-memory crash (leftover dev servers). So it runs serially first, and goes parallel only once memory is measured.

## How it would be built

1. **Contract.** Add `expects` on requirements and rules, and the vocabulary above, in the zod source first. Bump the schema version.
2. **Writer.** The requirements agent writes statements and the questions it can't settle. The review shows the sentences. The page planner binds screens. Prompts stay domain-neutral.
3. **Runner.** Build a `services/expects/` runner on the Playwright engine and the trial bench, with sign-in through the form, recipes, and code-judged outcomes. Each result carries its evidence.
4. **Build wiring.** Run after `page_code`. Failures go through the observer loop to the agent that owns them; what's left over goes to `runtime.issues`.
5. **Smith wiring.** A request becomes a statement first, and a turn is done when its statements pass. Smith can't edit statements. REQ-017-style mechanism requirements stop being written.
6. **Retire the per-fault checks.** Retire `arrival_findings`, `flow_move_findings` and the process-trial runs only once statements cover what they caught.
7. **After publish.** Run the read-only set on the live URL.

**Proof before rollout:**
- **Pre-fix TCommerce and ToroCommerce:** the runner, with statements written by the writer from the requirements alone, must find the faults testers found, unaided, on the versions in which they found them. Earlier Blueprint versions are kept under `.forge/blueprint/versions`.
- **A non-shop app** (F&B or the kids app), to show nothing in it is about shops.

## Open questions

- **Isolating statements:** one database copy per statement (clean, but slow) or one per journey (fast, but statements interfere). The sketch above assumes per statement.
- **Statements for apps already built:** the writer can produce them from the existing requirements in one pass, with the same review, so the questions get asked of old apps too.
- **Who answers the questions** when the person skips the review: the writer's default, recorded as a decision the person can see and change.

## Status (2026-10-08)

**Built (uncommitted):**
- The contract: `expectations` (`EXP-…`, zod + emitted schema + dist).
- **The writer:** an `expectations` DAG node (testing agent). It is optional and fans out per `expect_subjects` (the people, then requirements in groups of at most 4 with their rules). Its prompt is domain-neutral. `check_expectations` refuses what a statement names wrongly, and what its part leaves untried.
- **The runner:** `services/expects/` (`statements`, `resolve`, `browser`, `runner`) plus `scripts/expect_browser.mjs`.

**The runner's rules, learned on TCommerce:**
- One person is one browser. A role that signs in is signed out until then.
- Checks are judged at the end of the statement.
- Starting records are made through the app by a signed-in maker. When the app refuses, they go into the copy directly, with whose they are filled in the way the app would.
- The database copy is reset in place, never dropped, because dropping it cut the server's connections.
- Screens are warmed signed in as the administrator.
- A form that won't send gets its required fields filled.
- A remembered step that no longer sends is resolved again.

**Tried on the local TCommerce copy (v91, from before the 2026-10-07 platform fixes):**
- 57 statements written in about 4 minutes; 42 passed, 14 failed on real faults, 1 failed on the runner (two forms in one step).
- Faults it found, unaided:
  - deactivated products shown, and active ones missing from the category filter;
  - a deleted product still shown;
  - guest Add to Cart sends nothing;
  - shipped orders can be cancelled (RULE-006);
  - Update Profile answers "done" and stores nothing;
  - customers' emails are masked, so their edits can't be saved;
  - the administrator is refused when creating categories and variants.
- Not reproduced: the admin landing on the home page after sign-in. It passes on the local copy, so it stays the open published-app case.

**Step 4, in the build (`services/expects/build.py`):**
- After `app_check`, every statement is tried.
- One that fails goes to Smith unattended (`statement_ask`: the statement, what was seen, "do not change it", "try_expectation it").
- Then the failing statements are tried again, up to 2 rounds.
- The result is recorded in `runtime.expectations` (in the contract) and as `runtime.issues` kind `expectation`, and said in the completion message.

**Step 5, in Smith:**
- **`try_expectation` trial:** runs on the turn's database copy, which is restored afterwards. Its first line is the verdict, read by `trials.failed`; turn rules compare failures check by check.
- **`add_expectation` write:** adds only — a repeated statement is refused, and every statement is shape-checked. `edit_definition` refuses to edit `expectations`.
- **Context:** "What must happen" in Smith's context, failing statements first.
- **Prompt:** a loop-prompt paragraph saying how to use statements.
- **After a chat turn:** the statements the change reaches are tried, and a failure is repaired once (`handle._checked`).

**Live turn on the TCommerce copy:**
- **The report:** "I deactivated a product… it still shows."
- **Smith's own turn:** it tried EXP-227 first and saw it fail. It changed the product page, tried again and saw it still fail. It went into the engine (the old copy's reversed true/false filter) and ran out of steps.
- **The page check's repair:** a real Add Item to Cart fault (a text condition that matched every row).
- **The statement check:** it named the two statements still failing.
- **The reply:** it told the person, truthfully, that the change did not fix it.
- **Cost and time:** $1.28 in total, about 18 minutes.

**Not yet built:**
- step 6, retiring the per-fault checks;
- step 7, after publish;
- the `sent` check;
- running on UAT's apps-db.

**Slow:** a full run takes about 35 minutes against `next dev`.

## 2026-10-09: the separate checks retired

**The finding.** On a local ToroCommerce build (`memg8iw6`), process trials and the app check cost $3.92 against about $7 of generation. Nearly all of it went on faults that were not the app's:
- **A seeder bug:** the demo customer's account status was "Default Customer (demo)", so every customer process was refused as a disabled account. That meant six separate Smith repairs.
- **A crash in the checker's own screenshot step:** six customer pages were sent to Smith.
- **A React development-only notice:** three more pages.

**What changed:**
- **Removed from the build:** `_finish_unfinished_pages` runs page repair, then the statements, and nothing else. Smith's after-turn check tries only the statements a change reaches, and reports what no longer holds.
- **The statement pass gives back, it doesn't grind:**
  - one failure across 3 or more statements is a platform fault, reported and not repaired;
  - otherwise `owner_of` reads what was sent: a refused, failed or not-kept process goes to `workflow_steps` for that process, and a screen that did nothing or showed the wrong thing goes to `recode_page`;
  - each author gets its findings once (at most 6), and those statements are tried once more.
- **Every process is covered:** steps carry `workflow`, every manual process is assigned to a writer part and must be started by a statement, and the runner fails a step that didn't start the process it names.
- **Always-wrong screen checks** (`app_check.screen_findings`) run on every screen a statement opens, reported as issues of kind `screen`.
- **Speed:** signed-in sessions are reused across statements; the form is used only when the statement is about signing in.
- **Kept and fixed:**
  - the checker's own crash is `unchecked`, never a page fault;
  - React's attribute-hydration notice is ignored;
  - process trials group repairs by cause (`repair_groups`);
  - the seeder starts demo accounts from `ACCOUNT_INITIAL` and corrects its own old placeholders.

## 2026-10-09: the ToroCommerce rebuild (torob1) and the fixes it led to

**The rebuild.** It started from memg8iw6 v22. It cost $8.79 and finished in about 55 minutes, against $16.55 for the old build, which never finished. 34 of 61 statements held; 1 of the 6 failures sent back to their authors was fixed.

**Fixed after it:**
- **Dates in the data API (platform):** `parseDatesForDateColumns`. JSON dates reached date-mode columns as text and every order create failed. Covered by `run-date-tests.sh`, which uses real drizzle.
- **Runner, records and evidence:**
  - the direct-insert fallback fills the database's own required columns and reports why an insert was refused;
  - a reused session sets the person's email;
  - request bodies are recorded;
  - "is stored" is judged against a count taken before the steps, not timestamps.
- **Runner, using the screen:**
  - a record that opens in a screen's panel is opened there (`?param=id`);
  - only controls inside an open dialog are offered;
  - a click retries after Escape and scrolling, and keeps Playwright's reason;
  - actions are done one at a time, looking again after each;
  - a control that isn't enabled yet is a hint, and a control held disabled is the screen refusing;
  - the model is told which records the statement is about.
- **Writer and checks:**
  - screens carry `opens_for` (the access rule) beside `for` (the audience);
  - a `gets not_allowed` that contradicts access is refused, and so is `sign_in_asked` for someone signed in;
  - `self: true` givens set the person's own account;
  - given records may be listed in any order;
  - a part counts as written only when all its requirements and processes are covered.
- **Give-back:**
  - the owner is chosen from what the screen sent, compared with the inputs the process declares;
  - the brief carries the request and the answer;
  - each author gets two looks.
- **Build:**
  - a `dispatches` that names no process is dropped (it had cost the checkout feature its details);
  - no "Verify & fix" is offered after the statements.

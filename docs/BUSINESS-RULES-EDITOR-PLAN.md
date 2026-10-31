# Business Rules: editor, decision tables, workflows

Builds on `BUSINESS-RULES-SYNC-PLAN.md` (one record for rules across the build, the
tab, Smith and the running app). That made rules *consistent*; this makes them
*authorable*, like Drools' guided rules and decision tables, and part of workflows.

## What was broken (found by reading the code and the tab)

| # | Problem | Why |
|---|---|---|
| 1 | "New rule" and "Decision table" disabled | Both need a record to act on; an app with no records (a calculator) could not add a rule at all, and every rule it had read "Not enforced" with no way forward. |
| 2 | A new decision table could not be saved | It opened with placeholder columns `input1`/`output1` the server refuses; outputs lost their field binding on save. |
| 3 | Table cells half-worked | `[1..10]` (offered in the help) was compared as a string; cells were never checked; the editor's tester used a different evaluator from the app, so they could disagree. |
| 4 | Hit policies were labels | F, U, P and A all meant "first match"; C and R meant "last write wins"; nothing reported two rows matching a Unique table. |
| 5 | Tables said "live on the form" | The form never evaluates tables. |
| 6 | Rules and workflows did not meet | A workflow `decision` step ignored `decisionTableId`, followed every edge whatever matched, and read hit policy as words the Blueprint never writes. No step could run a rule of the app. |
| 7 | No way to know when a rule fires | Every rule ran on create and update alike; "only when a record is created" could not be said. |

## The design

**One engine.** The generated app's TypeScript rules engine is the only evaluator.
The server's checks, the editor's tester and workflow steps all run it (bundled with
esbuild, as `feel_check` already does for conditions). Nothing re-implements a rule
in Python or in the browser.

### 1. The rule editor (Drools' guided rule, plainer)
A full editor, not a form:
- **When** — fires on *created*, *updated* or both (new `on` field); a condition
  builder typed by field (enum values as a picker, numbers, dates, yes/no, "changed
  from", "is blank"), nested all/any groups, with a FEEL view kept in step.
- **Then / Otherwise** — action rows (refuse with a message, set or default a value,
  require, show/hide, read-only, options, start a workflow, notify).
- **Reads as a sentence** — "When an Expense is created and its amount is more than
  5000, refuse it: 'A manager note is required'".
- **Test it** — a sample record built from the entity's fields (and the record
  before, for updates); the app's own engine says what would happen: refused with
  which message, which fields change, which workflow starts.
- **Where it applies** — the workflows that save this record (rules already run
  inside them) and the workflow steps that run it.

### 2. Rules for apps without records
"New rule" is never disabled. Without records, a rule is a *written rule*: kept,
shown, and given to the app's builder; the tab says plainly why it cannot be checked
on save and offers **Ask Smith to build it into the app**.

### 3. Decision tables (DMN-grade, guided)
- Columns chosen from the record's fields (no placeholders); each output keeps its field.
- Cells: `-` any · `a, b` either · `"text"` · numbers · `> 5`, `<= 10` · ranges
  `[1..10]`, `(0..5]` · `not(…)` — parsed, typed and checked per cell at save.
- Hit policies with their real meaning: **Unique** (overlapping rows are refused at
  save), **First**, **Priority** (by the output's value order), **Any** (matches must
  agree), **Collect** with sum/count/min/max, **Rule order** (in workflows).
- Analysis at save: rows that overlap under Unique, rows a First table can never
  reach, rows with a cell the engine cannot read.
- Test it: which rows matched, which one won, the outputs.
- Honest about where it runs: on every save, and as a workflow step.

### 4. Rules inside workflows (jBPM's business-rule task)
- A `decision` step can name a rule of the app (`config.rule = RULE-nnn`): a table
  computes values for the rest of the workflow; a condition rule branches.
- The step branches: *then* when a row matched / the condition held, *else*
  otherwise — and when no *else* path was drawn, it carries on as before.
- From a rule: **Use in a workflow** → pick the workflow and the step it follows;
  for a condition rule, choose "stop the workflow with this rule's message" or
  "carry on either way". The step is written into the Blueprint and the app at once.

## Tests
Runtime unit tests for the cell grammar, hit policies and analysis; backend tests
for check, simulate and attach; a live check against a running Forge with a real
built app (create → test → save → enforced on the app's API → used in a workflow →
the workflow refuses / branches), and a browser walk-through of every screen.

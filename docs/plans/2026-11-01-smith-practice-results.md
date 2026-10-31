# Smith practice runs: old against new (2026-11-01)

Each case ran once with the old Smith (smithv5 f297b668) and once with the new one (claude/smith-learns), on separate copies of DITANS (wzml1sa6). Each copy had its own database and was given the same fault and the same ask. One unattended Smith turn ran per copy, and a fixed measure was read off the Blueprint afterwards.

The API credit ran out after the first three cases. The other five (arabic, design, logins, filters, rawid) ended at once with "could not reach my reasoning service" on both sides and spent nothing. They still need a run.

| Case | Ask | Old Smith | New Smith |
|---|---|---|---|
| menu | "Find talent and Agencies in the left menu don't open anything" | **Not fixed.** 40 min, $6.77, 47 calls. Rewrote the menu config, edited the error/loading pages and nav-flow, and the two entries still pointed nowhere (`#`). | **Fixed.** 3 min, $0.94, 10 calls. `bind_menu` bound both entries to their screens, then `open_page` was used to check. |
| cursor | "cursor is not turning into the finger … in every portal" | **Not fixed.** 6 min, $1.83. Found the cause, but every `edit_file` was refused by the unattended proof gate. It proposed a CSS rule and asked for a go-ahead. | **Fixed.** 24 min, $2.14. Five `write_frame` changes, one per drawn shell, all stored in the Blueprint rows; a sixth caught a missed row. Every shell's menu rows are now n/n. About 15 of the 24 min went on three restarts of a check dev server that grew past its memory cap. |
| drawer | "the user drawer is getting hid … when I click my name" | **Not fixed (lost later).** 9 min, $2.56. Removed the clip in the projected `.tsx` only, so the Blueprint row still clips and the next projection puts the fault back. | **Fixed.** 9 min, $0.64, 7 calls. `write_frame` removed `overflow-hidden` from the top bar in the Blueprint row and added `relative z-30`. |

Totals:
- Old Smith: 0 of 3 fixed (one fix only lands in a file that is regenerated), $11.16.
- New Smith: 3 of 3 fixed, $3.71.
- Spent overall: $14.87.

## Caveats

- **The proof gate applies to both sides.** The harness runs turns `unattended=True`, which puts the "a failed run first" proof gate on file edits. That gate is why the old Smith's cursor turn could not land its CSS rule. In a chat with the person present, it may have landed it.
- **The drawer turns did not finish verifying.** Both reached the credit limit while checking. Both had already applied their change.
- **`seed.json` and `src/db/schema/*` diffs appear in every copy.** They come from the per-turn platform catch-up (`refresh_engine`), not from either Smith. The catch-up turns DITANS's encrypted `candidate.email` back into a plain unique column. That is worth checking separately against the DITANS Blueprint.

## Test suite

The full suite on the branch has 60 failures. Every failing file was re-run on f297b668, which has the same failures, except one: `test_a_build_still_open_when_the_platform_starts_is_followed_again::test_a_build_on_expo…`. It passes 3 out of 3 times on its own, because it is a timing test. The branch introduces no regressions.

## Re-running

The harness is in the session scratchpad: `practice/run_case.py <new|before> <case>`, `cases.py` and `all.sh`. It needs API credit. The remaining cases are arabic, design, logins, filters and rawid, at about $1–3 per run.

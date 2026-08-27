# A11y Known Issues

Items surfaced by the Playwright + axe-core suite
(`apps/visual-regression/tests/a11y.spec.ts`) that we have **consciously
deferred**. Each entry describes the rule, why a library-level fix is
inappropriate or out-of-scope, and what would have to change to retire
the entry.

Items that **were** fixable in the library are not listed here — they
have been resolved and the relevant commit is referenced in the entry
that covered them.

---

## 1. NEXTJS-PORTAL appears in the Tab order under `next dev`

**Original symptom:** `Tab focus stuck on NEXTJS-PORTAL...` at step 13
on `/tasks/detail` and step 23 on `/users/list`.

**Root cause:** Next.js mounts a `<nextjs-portal>` custom element into
the body in development mode to host the error / RSC overlay UI. It is
focusable and shows up in the Tab cycle when present. Production builds
(`next build && next start`) do not render this element at all.

**Status:** Deferred — environment artifact.

**Why not fix in library / scaffold:** the portal is internal to the
Next.js framework and cannot be removed from `next dev` without
disabling the dev overlay we want to keep.

**Mitigation in the test suite:** `tests/a11y.spec.ts` filters out
`NEXTJS-PORTAL` (and any element inside a `nextjs-portal` ancestor)
from the stuck-check. The check fails only on real Tab traps.

**To retire this entry:** run the a11y suite against a `next start`
build of the scaffold (or wire the suite up to `playwright.config.ts`
`webServer` running `next build && next start`). The portal will not
appear and the filter can be removed.

---

## 2. Native `<input type="date">` consumes Tab for its internal spinners

**Original symptom:** `Tab focus stuck on INPUT:...:` on
`/tasks/form` — the date field's `<input type="date">` cycles through
month / day / year sub-fields before yielding to the next focusable
element.

**Root cause:** This is correct, specified browser behaviour for native
date / datetime / time / month / week inputs. Pressing Tab inside the
control moves focus to the next internal sub-field; `document.activeElement`
stays on the same `<input>` until all sub-fields are exhausted. The
original stuck-check fingerprint (tagName + className + text) treats
each of those internal Tabs as "stuck on the same element".

**Status:** Deferred — correct browser behaviour, not an a11y bug.

**Why not fix in library:** replacing native date inputs with a custom
date picker introduces a *worse* a11y story (we would have to
re-implement keyboard navigation, screen-reader semantics, locale
formatting, etc.). Native inputs are the AA-friendly default.

**Mitigation in the test suite:** the keyboard test in
`tests/a11y.spec.ts` now allows native date / datetime-local / time /
month / week inputs to re-focus themselves on consecutive Tab presses
(it derives a unique per-Tab fingerprint for these element types).

**To retire this entry:** unblocked — the test correctly distinguishes
"trap" from "internal spinner cycling" today.

---

## 3. Inline-styled link colour at `--token-primary-500` scores 4.46:1

**Original symptom:** axe-core reports 1 serious color-contrast
violation on `/tasks/detail`:
> `color:var(--token-primary-500)` (#6366f1) on `#ffffff` = 4.46:1,
> expected 4.5:1.

The element is a generator-produced anchor in the "related tasks"
list, rendered with an inline `style="color:var(--token-primary-500); ..."`
attribute. The colour is the project's brand `primary-500` token
(indigo-500), set on the scaffold theme.

**Status:** Deferred — content / token-level concern, not a library or
test bug.

**Why not fix in library:** the link does not pass through a library
component; it is a `<a>` emitted directly by the renderer from
schema-driven inline-style annotations. Bumping every consumer to a
darker tone (e.g. `primary-700`) would alter brand colour on every
generated page, not just this link.

**Right place to fix (future task):**
- Either re-tune the design-system seed so `primary-500` lands at
  ≥ 4.5:1 on white (e.g. shift indigo-500 → indigo-600 in
  `backend/scripts/seed_reference_bank.py` token defaults), **or**
- Teach the schema-emit step (`backend/agents/page_agent.py`) to use
  `--token-primary-700` for inline-styled link text, leaving
  `--token-primary-500` for backgrounds / accents where contrast is
  not body-text-bound.

**Test impact:** the `axe-core: no serious or critical violations`
test on `/tasks/detail` will remain failing on the seeded project
fixture until the token / schema fix lands. All other pages
(`/tasks/list`, `/tasks/form`, `/users/list`) and all keyboard tests
pass.

---

## Resolved (for reference)

| Issue                                                        | Fix                                                                                              | Commit                                                              |
|--------------------------------------------------------------|--------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| `text-emerald-600` on white in MetricTile delta indicators   | Bumped to `text-emerald-700` / `text-rose-700` across all MetricTile variants                    | `a11y(library): bump MetricTile delta tones to 700 series ...`      |
| `text-muted-foreground` on `bg-muted` in Avatar initials     | Avatar initials use `text-foreground`                                                            | `a11y(library): Avatar initials use text-foreground ...`            |
| `text-muted-foreground` on `bg-muted` in Badge neutral pills | Neutral Badge uses `text-foreground`                                                             | `a11y(library): Badge neutral variant uses text-foreground ...`     |
| Sibling-button false Tab-trap on "View" row buttons          | Test fingerprint switched from class/text to a per-element `data-a11y-idx`                       | `test(a11y): refine Tab-focus stuck-check ...`                      |
| NEXTJS-PORTAL appears in Tab cycle (`next dev`)              | Test filters `NEXTJS-PORTAL` elements; root cause documented above (#1)                          | `test(a11y): refine Tab-focus stuck-check ...`                      |
| Native date input cycling counted as Tab trap                | Test treats native date / time / datetime-local inputs as fresh focus identity per Tab (see #2)  | `test(a11y): refine Tab-focus stuck-check ...`                      |

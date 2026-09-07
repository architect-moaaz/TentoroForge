Five rounds of auditing every component in the palette by driving the real
editor as a user, and fixing what was found at the root cause.

## The recurring shape

The same mistake repeated because nothing owned the answer. Three binding
formats, two input state contracts, two aggregate dialects, two prop-write
boundaries — each divergence produced a bug that looked fine in one surface and
broken in another, which is why they survived so long.

## What was broken

**Binding a prop broke the node.** The editor wrote `{$binding:"expr"}`, a shape
no renderer, engine, library or schema package implemented — zero occurrences
outside the editor. It reached React in child position, so the node rendered
"⚠ render error" the moment you asked to bind it, and autosave persisted the
breakage into the generated app. Now writes the `{{expr}}` string the renderer
already resolves; legacy objects heal on page load, and the renderer forgives
any that never pass through the editor again.

**Half the input library was dead.** Fully controlled components waiting on a
`value`/`onChange` pair nothing supplies: Slider reverted to 0, Rating filled no
stars, ColorPicker was frozen at `#000000` while React logged the read-only-field
warning. One shared `useFieldValue` contract — controlled requires BOTH, `value`
alone is a declarative seed — plus `defaultValue` so a schema can express one.

**35 of 36 `actionPicker` controls could only emit an action object**, so on an
array prop the control emptied the prop it existed to fill. Converted to
authorable arrays/objects with a repeating-row editor, and unshadowed
`DATA_SOURCE_PROPS` so the registry's declared control is actually used.

**`bind: null` silently disabled props validation on 53 descriptors.** `null` is
not `undefined`, so the parse failed and step-3 coercion had no branch for it —
`validateProps` returned raw props and every Zod `.default()` was skipped.

**Three components shipped an empty registry `props: {}`** — Carousel, Lightbox,
Tree — so their Props panel held no control at all while the page schema
declared the omitted prop required.

**Every route of every generated app returned 500.** `schema-page.tsx` imported
`./FigmaCanvas` and the file was never added to the template.

**Design-token prose was emitted as CSS.** `designSystem` carries LLM guidance
under the same keys as real tokens; a semicolon mid-sentence closed the
declaration and broke `tokens.css`, which `globals.css` imports unconditionally.

**Editor saves never reached the app.** The read fell through to `app/`, the
write did not — so the first save forked a shadow copy and the application never
received another edit.

**No library-only Tailwind class ever compiled.** Every `@source` glob in
`globals.css` was one `../` too deep and resolved above the repo root. Calendar
rendered SUN–SAT stacked vertically at 1150×1511.

## The measure that matters

Dropping each of the 21 round-5 display components produced page JSON that
`PageV2` rejected in **14 of 21** cases. It is now **0 of 21**.

## Verification

All six packages build with 0 TS errors. frontend 613 tests / 0 failures;
patches 68; registry 27; library and renderer at their pre-existing baselines
(24 and 30 failures), unchanged in count and identity.

## Merge note

`origin/smithv2` was merged in; six conflicts, all resolved by keeping both
sides. Worth a reviewer's eye: in `assembly.py` we kept `written.append(key)`
(posix) alongside the new retired-file sweep — that sweep tests membership
against `RETIRED_SCAFFOLD_FILES`, which is spelled with forward slashes, so
`str(dst_rel)` would never match on Windows and the retired root page would
survive in every app built there.

## Still open

`RESUME.md` records it. Most notably the four app routes were audited
**unauthenticated** — the app redirects to `/login` — so those findings are void
and need re-testing with a session. Audit trail in `docs/editor-audit/` (five
rounds) and `qa-audit-log.md`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01LkPqDeefjmTKMdve3MokRp

# QA audit log — two-agent workflow

Append-only. Agent A (User-Experience Auditor) logs findings; Agent B
(Fixer/Builder) appends the resolution to the same entry. Never overwrite.

**Project under test:** `gh0mlpbp` (generated Inventory app)
**Editor:** http://localhost:6501/editor/gh0mlpbp
**Generated app (standalone):** http://localhost:6510
**Scaffold preview:** http://localhost:6503/p/gh0mlpbp/&lt;route&gt;

## Scope

43 components across the three categories not covered by audit rounds 1–5,
plus the app's four real routes.

| batch | count | components |
|---|---|---|
| 1 — navigation | 10 | Breadcrumb, CartBadge, CommandPalette, ContextMenu, DropdownMenu, Link, Menubar, NavLink, Redirect, SkipLink |
| 2 — feedback | 21 | Alert, AutoFocus, Banner, Drawer, EmptyState, EmptyStateRich, FocusRing, FocusTrap, HoverCard, IllustratedEmpty, InspectorPanel, LoadingState, OptimisticProvider, Popover, PresenceIndicator, Progress, Skeleton, Spinner, Tooltip, TourOverlay, UndoManager |
| 3 — data | 12 | CartPanel, Chart, Conditional, DataBoundary, DataGrid, EditableLineGrid, Repeat, Slot, Sparkline, Table, TableSortable, Timeline |
| 4 — routes | 4 | `/items`, `/items/new`, `/items/[id]`, `/items/[id]/edit` |

Already covered by rounds 1–5 and excluded here: 18 layout, 41 input,
31 display. Reports in `docs/editor-audit/`.

## Entry format

Each component gets one entry. Agent A writes the first three fields, Agent B
appends the last three.

```
### <Component or route>
- **Bugs found:** repro steps · expected vs actual · severity (blocker/major/minor)
- **Missing/desired features:** what a user expected and did not get
- **Status:** NEEDS_FIX | CLEAN
- **Fix applied:** what changed, files touched
- **Feature added:** what was implemented, files touched
- **Status:** RESOLVED
```

---

# Entries

<!-- Agent A — navigation batch. Scratch page /nav-lab-6 in project gh0mlpbp,
     own Chrome tab. All 10 navigation components dropped from the palette by
     real clicks; evidence is javascript_tool DOM probes on the live canvas. -->

### Breadcrumb
- **Bugs found:** **The Breadcrumb renders perfectly in the editor and is invisible in the real app.** Repro: with the finished breadcrumb on `/nav-lab-6`, open the production renderer at `http://localhost:6503/p/gh0mlpbp/nav-lab-6`. The page body text is `nav lab 6 Search… Ctrl+K Right-click here ActionsLearn moreLink Skip to main content` — **no breadcrumb**. Its two anchors are present in the document but measure **0x0**, and walking their ancestors shows the trail is still sitting inside React's streaming buffer: `<div hidden id="S:0">` whose `textContent` is exactly `Items/Widget A/Edit`. The Suspense boundary that holds it is never swapped into the page — on a full document load the completion script is not emitted at all (`document.querySelectorAll('script:not([src])')` contains **no `$RC(...)` call**, though `window.$RC` is defined). Reproduced on three separate loads. Expected: the crumbs I authored appear in the app. Actual: they exist in the HTML and stay hidden.
  **Refinement worth having:** it is not permanent — after I clicked something else on the page (forcing a client re-render) the breadcrumb *did* appear correctly as `Items / Widget A / Edit`. So the component is fine; **the page's first paint is what drops it.** This is the same failure as the `/items`, `/items/new`, `/items/[id]` and `/items/[id]/edit` route entries below and should be fixed once, in the renderer, not five times. Severity: **major**.
  Everything I did in the *editor* worked. Repro: palette search "Breadcrumb" → click to insert on `/nav-lab-6`. Renders immediately with a real seed (`Home / Current page`, `<nav aria-label="Breadcrumb">`, 960x24). Props panel exposes ITEMS (JSON, marked REQUIRED) and SEPARATOR. Replaced ITEMS with `[{"label":"Items","href":"/items"},{"label":"Widget A","href":"/items/1"},{"label":"Edit"}]` → canvas updated to `Items / Widget A / Edit` with anchors `Items->/items`, `Widget A->/items/1` and the last crumb correctly rendered as plain text, not a link. Typed deliberately broken JSON (`[{"label":"Items", href:/items}`) → panel showed `Not saved — Expected double-quoted property name in JSON at position 19` and the canvas kept the last good value. Clicking the "Home" anchor inside the editor canvas selected the node instead of navigating the editor away — correct. No console errors.
- **Missing/desired features:** the ITEMS editor is a raw JSON textarea with the note "Editing as JSON — no value / key / id on every row"; as a user I wanted a row-per-crumb editor with a label field and a route picker that offers the pages that actually exist in this project (`/items`, `/items/new`, …) instead of me typing route strings by hand and hoping they match. No `currentPageAuto` option either — every breadcrumb has to be hand-authored per page even though the editor knows the page's route.
- **Status:** NEEDS_FIX

### CartBadge
- **Bugs found:** **Renders nothing at all.** Repro: palette search "CartBadge" → click to insert. The node is persisted and appears in the tree as `cartbadge-00zfnb`, but its wrapper has `childElementCount === 0` — `firstElementChild` is `null`, rect 0x0, `innerText` empty. There is no DOM under it whatsoever, and because the box is zero-sized it gets **no empty-node hint overlay either**, so there is nothing on the canvas to click, select or diagnose. This is round 5's Lightbox/Dialog failure (invisible *and* undiagnosable) recurring in a navigation component — same class as round 5 rows 2 and 12. Severity: **major** (a user drops it, sees nothing appear, and has no way to tell whether the drop even worked).
- **Missing/desired features:** I expected a cart icon with a count bubble and a zero/empty state ("0" or a dimmed icon) so it is visible while I lay the page out. Also expected the drop to seed a sample count the way Breadcrumb seeds sample crumbs.
- **Status:** NEEDS_FIX

### `/items` · `/items/new` · `/items/[id]` · `/items/[id]/edit` — standalone app at :6510
- **Bugs found:** **NOT TESTABLE IN BROWSER — the standalone app is down on all four routes.** Repro: open `http://localhost:6510/items` in a fresh tab. `/` 307-redirects, then every one of the four routes returns HTTP 500 with the same server error: `Module not found: Can't resolve './FigmaCanvas'` — `> 19 | import { FigmaCanvas } from "./FigmaCanvas";` — `Import trace for requested module: ./src/app/(dashboard)/[entity]/page.tsx`. Verified in the browser (the Next `_error` payload is in the DOM) and by direct request: `/items` 500 in 1.4s; `/items/new`, `/items/1` and `/items/1/edit` never respond at all (60s timeout each, same module error in the build). Every route of the generated app is behind the `(dashboard)/[entity]` page, so the app has no working page. Severity: **blocker**.
- **Missing/desired features:** as a user, a 500 stack trace about a missing internal module is not something I can act on. n/a otherwise — routes re-audited against the scaffold preview on :6503 in the entries below.
- **Status:** NEEDS_FIX

### ContextMenu
- **Bugs found:** **Right-clicking it opens a completely empty menu.** Repro: insert ContextMenu on `/nav-lab-6` → it renders a dashed 960x48 target reading "Right-click here" → right-click it. A Radix menu opens (`[role="menu"]`, portalled outside the canvas root) measuring **160 x 10 px with `childElementCount === 0`** — a bare white sliver with nothing in it. The reason is visible in the Props panel: the only control the panel offers for this component is **LABEL**. There is no `items` control at all, and the persisted node is `{"type":"ContextMenu","props":{"label":"Right-click here"}}`. So the component's entire purpose — the menu — is unreachable from the editor. Severity: **major**. Same class as round 5 rows 1–8 (the one prop the component exists to show is not in the registry), new instance.
- **Missing/desired features:** an `items` control (label + action per row), and a disabled/destructive row style. I also expected the empty menu to say something like "No menu items" rather than opening a 10px-tall blank box — as a user I could not tell whether it was broken or still loading.
- **Status:** NEEDS_FIX

### DropdownMenu
- **Bugs found:** Two, both verified by clicking.
  1. **Opens an empty menu.** Repro: insert DropdownMenu → renders a 75x34 "Actions" button → click it. A `[role="menu"]` opens measuring **160 x 10 px, `childElementCount === 0`**. Persisted node is `{"type":"DropdownMenu","props":{"trigger":"Actions"}}` — no items, and no items control anywhere in the editor. Severity: **major** (same class as ContextMenu above).
  2. **The node cannot be selected in the editor, so its Props panel is unreachable.** Repro: click the "Actions" button on the canvas → the runtime menu opens and the Properties panel still reads *"Select a node on the canvas to edit its props."* Press Escape, click again → same result, every time. There is no layers/outline panel in this editor (the left rail is Pages only), so once dropped there is **no way to select a DropdownMenu to configure, restyle or delete it**. Contrast: ContextMenu selects correctly on left-click (its menu is bound to right-click), and CommandPalette's trigger button selects correctly. Severity: **major**.
- **Missing/desired features:** an `items` control; and, since the trigger swallows clicks, either a layers panel or the usual design-time convention of suppressing runtime click handlers inside the canvas.
- **Status:** NEEDS_FIX

### CommandPalette
- **Bugs found:** **Its own advertised shortcut does not work — in the editor OR in the real app.** The trigger button literally reads "Search… **Ctrl+K**". Repro in the production renderer (`http://localhost:6503/p/gh0mlpbp/nav-lab-6`): click empty page background, press Ctrl+K → nothing opens (`[role=dialog]` count 0, no `input[placeholder="Search commands…"]`, `activeElement` still BODY). Click the trigger button instead → the palette **does** open, correctly, with the seeded commands grouped as `PAGES / GO TO DASHBOARD` and `ACTIONS / CREATE RECORD`, and typing `dash` filters it down to just "GO TO DASHBOARD". So the palette works; only the keyboard shortcut it advertises on its own face does not. Severity: **major**.
  Two smaller things found while it was open: (a) **focus is not moved into the search box on open** — `document.activeElement` is `BODY`, so a keyboard user has to reach for the mouse before typing; (b) the overlay is a plain `div.fixed.inset-0…` with **no `role="dialog"` and no `aria-modal`**, so it is not announced as a modal (severity: minor each).
  Pressing Enter on the filtered "Go to dashboard" row ran its `navigate → /` action and landed on `http://localhost:6503/` → **404**: the base path `/p/gh0mlpbp` is dropped, the same base-path bug as Redirect below. Browser Back from there returned correctly to the page.
  And, importantly, **it does not steal the editor's keyboard** — this is the round-4/5 trap and it does NOT recur here. Repro: (a) click the editor's own "Search components…" box and press Ctrl+K → nothing opens, focus stays in the editor's input, its value is untouched; (b) click on the canvas and press Ctrl+K → no dialog, `[role=dialog]` count 0. Clicking the component's own "Search… Ctrl+K" trigger button on the canvas selects the node (Props panel shows `CommandPalette / commandpalette-megoq6`) rather than opening the palette — correct design-time behaviour. Props panel exposes ITEMS (JSON, REQUIRED), PLACEHOLDER and TRIGGERKEY, and the drop seeds two real sample commands (`Go to dashboard` → navigate `/`, `Create record` → workflow `createRecord`) so it is not blank on arrival.
- **Missing/desired features:** the TRIGGERKEY control is a free-text box that takes a bare letter (`k`) — nothing tells me whether that means Ctrl+K, Cmd+K or plain K, and nothing stops me typing something that collides with a browser shortcut. I wanted a modifier picker plus a conflict warning. The ITEMS JSON also lets me type `{"type":"navigate","to":"/anything"}` with no validation that the route exists in this project.
- **Status:** NEEDS_FIX

### Redirect
- **Bugs found:** Three, all reproduced in the browser.
  1. **A Redirect dropped with its default props makes the page permanently unreachable, and traps the Back button.** Repro: insert Redirect on `/nav-lab-6` (seeded `{"to":"/","label":""}`) → open the page in the production renderer (`http://localhost:6503/p/gh0mlpbp/nav-lab-6`). The URL immediately becomes `http://localhost:6503/` and the page reads **"404 This page could not be found."** Press Back → you land back on the page, it redirects again, and you end up on the same 404 (`history.length` stayed 3, `location.href` still `/`). Expected: I can still get out of a page I just previewed. Actual: the page is a one-way door. Severity: **blocker** — the same thing happens in the editor's built-in preview overlay and in a standalone tab, and there is no visible clue in the editor that a page has become unopenable.
  2. **`to` is resolved against the origin root and ignores the renderer's base path** — so *every* Redirect 404s in preview. Repro: set TO to `/nav-lab-6` (the page's own route) in the Props panel, reload `http://localhost:6503/p/gh0mlpbp/nav-lab-6`. The browser goes to `http://localhost:6503/nav-lab-6` — the `/p/gh0mlpbp` prefix is **dropped** — and shows 404. Expected: it resolves the same way the Breadcrumb/Link routes do, within the previewed app. Severity: **major**.
  3. **A self-referential Redirect does not loop, it soft-locks.** Repro: with TO = `/nav-lab-6` (its own route), the first paint shows the page with the text **"Redirecting…"** at the bottom and then bounces once to the 404 above. Where the base path *did* match, the page would sit on "Redirecting…" indefinitely. Good news for the brief's "does a Redirect loop?" question: **no infinite loop, no browser hang** — but the stuck "Redirecting…" state has no timeout and no escape. Severity: **minor** (relative to 1 and 2).
- **Missing/desired features:** the TO field is a free-text box; I wanted a picker listing the project's real routes (the editor already lists them in the Pages rail) and a guard that refuses `to` == the page's own route. There is also no design-time indication on the canvas that this node will make the page unopenable — it just renders the words "Redirecting…" like any other text. A "disabled while editing" toggle would have saved me from having to delete it to preview anything else on the page.
- **Status:** NEEDS_FIX

### Link
- **Bugs found:** **A freshly dropped Link is not a link — it goes nowhere, but looks exactly like one.** Repro: insert Link on `/nav-lab-6` → renders the text "Learn more" as blue, underlined, `cursor: pointer`. Open the page in the production renderer and click it: **nothing happens, the URL does not change.** The rendered anchor is `<a href="">` — an *empty* href (verified via the element's attributes in the live page), because the registry seeds `{"label":"Learn more","navigate":"","workflow":""}` and neither destination is set. In the editor canvas the anchor has **no `href` attribute at all**. Expected: either a seeded destination, or a visibly "unset" state. Actual: a control that is styled as a working link and is inert. Severity: **major**. This is round 5's C3c class (`""` seeded where absent was correct — CodeBlock.code / QRCode.value), in a navigation component where the consequence is a dead link rather than an empty box.
  **And setting a destination does not fix it.** Follow-up repro: select the Link in the editor, type `/items` into the NAVIGATE prop, blur. The editor updates correctly — the canvas anchor becomes `href="/items"` and so does the anchor in the production renderer. Click it in the production renderer (verified I hit the right element: `document.elementFromPoint` at the anchor's centre returns `A|Learn more`, `href="/items"`, `onClick` present on its React fiber). **The URL does not change.** So the Link's own click handler swallows the navigation even when a valid destination is configured — the empty seed is the visible symptom, but the component is inert either way. Severity: **major**, and this is the part to fix first.
- **Missing/desired features:** the destination is split across two free-text props (`navigate` and `workflow`) with no indication of which one wins if I fill both, and no route picker — the editor knows this project's routes (they are listed in the Pages rail) and does not offer them. I also wanted `target="_blank"` / external-URL support and an `aria-current`/disabled state.
- **Status:** NEEDS_FIX

### NavLink
- **Bugs found:** **Same as Link — a nav item that navigates nowhere, plus no active state.** Repro: insert NavLink → renders a padded pill reading "Link". In the production renderer the anchor is `href="#"` (registry seeds `{"label":"Link","target":"","icon":""}`). Click it: the URL does not change and no hash is added. It also carries **no `aria-current`** attribute at all, so even once you give it a target there is nothing marking the current page — which is the one thing a NavLink is for. Severity: **major** for the dead default, **minor** for the missing active state (untested with a real target because the default gives nothing to compare against).
- **Missing/desired features:** a route picker for `target` instead of free text; an `activeClassName` / active style control; and the `icon` prop is a bare text box with no icon picker even though the editor resolves icons elsewhere.
- **Status:** NEEDS_FIX

### SkipLink
- **Bugs found:** **The skip link reaches nothing.** Repro: open `/nav-lab-6` in the production renderer, click into the page, then Shift+Tab / Tab to the first focusable element. The link correctly becomes visible on real keyboard focus (147x24, `clip: auto`, `:focus-visible` matches) — that part works. Press Enter: **the URL hash stays empty, focus stays on the link, nothing scrolls or moves.** Cause is visible in the DOM: the component's default `target` is `"main"`, so it renders `href="#main"`, but the rendered page's `<main>` element has attributes `style, data-project-id, data-page-path, data-register` and **no `id`** — `document.getElementById('main')` is `null`. Severity: **major** (this is an accessibility component whose whole job silently fails).
  - *Retracted false positive:* calling `.focus()` programmatically leaves it 1x1 with `clip: rect(0,0,0,0)`, which looks like "invisible when focused". Driving a real Tab keypress shows it reveals correctly. Not a bug.
- **Missing/desired features:** the TARGET field is free text with no validation and no picker; I expected it to default to something that exists in the generated page shell, or for the renderer to stamp `id="main"` on its `<main>`. A user has no way to discover that the default is broken.
- **Status:** NEEDS_FIX

### ContextMenu — addendum, production renderer
- **Bugs found:** **In the real app it does not open at all.** Repro: open `http://localhost:6503/p/gh0mlpbp/nav-lab-6`, right-click the "Right-click here" target → **no `[role=menu]` appears anywhere in the document**; you get the browser's own context menu instead. So the behaviour is worse in the app than in the editor: the editor at least showed an empty 160x10 popup, the app shows nothing. The renderer says why — the server console logs `[scaffold] schema validation failed for gh0mlpbp/nav-lab-6 (3 issues), rendering raw. First: ["root.children.4.type: type is already covered by a strict node shape, or collides with a reserved structural bucket", ...]` and **children 4, 5 and 9 are exactly ContextMenu, DropdownMenu and Menubar** — the three nodes whose required content prop the registry does not seed. Same class as round 5's C3 (the editor writes page JSON its own schema rejects), new instances. Severity: **major**.
- **Missing/desired features:** as above — an `items` control.
- **Status:** NEEDS_FIX

### DropdownMenu — addendum, production renderer
- **Bugs found:** **Completely dead in the real app.** Repro: open the page in the production renderer, click the "Actions" button → `aria-expanded` stays `"false"`, `data-state` stays `"closed"`, no `[role=menu]` in the document. Focus it and press Enter → same. The button's React fiber does have `onPointerDown` / `onKeyDown` wired, so the handler exists and the open state simply never flips. This node is one of the three that fail the scaffold's schema validation (`root.children.5`, see the ContextMenu addendum). Severity: **major**.
- **Missing/desired features:** as above.
- **Status:** NEEDS_FIX

### Menubar
- **Bugs found:** **The Props panel for Menubar is completely empty, and the component renders an empty bar.** Repro: insert Menubar on `/nav-lab-6` → it renders a 960x24 `<div class="flex items-center gap…">` with **no text and no items**, and gets the editor's amber empty-node hint reading *"Menubar — Horizontal application menu bar."* — the palette description verbatim, naming no prop to fill in. Select it: the Properties panel shows **`Menubar` / `menubar-gs1inx` / the ALL·SM·MD·LG·XL breakpoint row and nothing else — zero controls.** The persisted node is literally `{"type":"Menubar","props":{}}`. In the production renderer it is the same empty 960x24 bar. It is also one of the three nodes the scaffold rejects: `[scaffold] schema validation failed … root.children.9.type`. Severity: **major**. This is round 5's `props: {}` class (rows 1–3, Carousel / Lightbox / Tree) — same class as round 5 row 1, new instance in the navigation category.
- **Missing/desired features:** everything — a `menus` control (top-level menu titles, each with items, separators, submenus and shortcuts). As it stands a user cannot put a single item in a Menubar from this editor.
- **Status:** NEEDS_FIX

### CartBadge — addendum, production renderer + selectability
- **Bugs found:** Confirmed in the real app: in `http://localhost:6503/p/gh0mlpbp/nav-lab-6` the CartBadge is the third child of the page container and renders as `SPAN[0x0] childElementCount=0` — **no DOM, no icon, no count, in the app as well as in the editor**, even though the registry does seed real props (`{"href":"/cart","label":"Cart","hideZero":false}` — note `hideZero` is *false*, so a zero count should still be shown). Follow-on: because the node has no box **and this editor has no layers/outline panel** (the left rail is Pages only), there is no way to select it — I could not open its Props panel, restyle it, or delete it once dropped. Severity: **major**, upgraded from the initial entry.
- **Missing/desired features:** as above, plus: a fallback/empty rendering so the node is at least selectable, or a layers panel so zero-box nodes are reachable.
- **Status:** NEEDS_FIX

### `/items` (scaffold preview — :6510 is down, see the standalone entry above)
- **Bugs found:** **The item list is invisible. The page shows its header and three stat tiles and nothing else.** Repro: open `http://localhost:6503/p/gh0mlpbp/items`. Visible body text is exactly: *"Inventory Items … Total Inventory Value 46851.48 · Low Stock Items 0 · Items 10"* and then it stops. The search box, the "All items / Low stock" filter tabs, the Table/Cards view toggle and the **entire 10-row table** are all present in the HTML but parked in React streaming buffers that are never swapped in — `div[hidden] id="S:0"` (empty), `S:1` = `All itemsLow stock`, `S:2` = `ViewTableCards`, `S:3` = `ItemsAll stocked items, newest first…` containing all 11 `<tr>`. `document.querySelectorAll('a').length === 0` on the whole page. Reproduced on a fresh navigation and on a hard reload. Expected: a browsable inventory list. Actual: a header, three numbers, and no way to do anything. Severity: **blocker**.
- **Root cause I could observe from the browser:** the page emits the Suspense-completion script (`$RC("B:1","S:1")` is in the document and `window.$RC` is a live function) but the content stays in the hidden div, and for some boundaries the completion script is never emitted at all. This same failure hits every route below **and** the Breadcrumb entry above — it is one bug, not five.
- **Missing/desired features:** even when the table is dug out of the hidden div, **the rows contain no links** — only `Edit` / `Delete` buttons — so there is no click-through from a row to `/items/[id]`. As a user wanting to open a record I had nothing to click; I had to type the URL.
- **Status:** NEEDS_FIX

### `/items/new` (scaffold preview)
- **Bugs found:** **The page is completely blank.** Repro: open `http://localhost:6503/p/gh0mlpbp/items/new`. `document.body.innerText` is the **empty string**; `<main>` measures **1525 x 0**. The whole form — Item Name, Category, Quantity, Unit Price and the "Add Item" button — exists in the DOM (`input[name=name]`, `category`, `quantity`, `price`) but every field measures 0x0 and `input.closest('div[hidden]')` is truthy: it is all inside `div[hidden] id="S:0"`. Severity: **blocker**.
- **NOT TESTABLE IN BROWSER — could not submit valid or invalid data, because there is no visible form to submit.** Everything the brief asked for here (empty submit, valid submit, navigate away mid-edit) is blocked behind the blank page.
- **Missing/desired features:** n/a until the page renders.
- **Status:** NEEDS_FIX

### `/items/[id]` (scaffold preview)
- **Bugs found:** Two, and the second is the worst thing I found today.
  1. **The `[id]` segment is ignored — every id shows the same record.** Repro: open `/p/gh0mlpbp/items/1` → "Wireless Bluetooth Headphones · Electronics", qty 42, price 89.99. Now open `/p/gh0mlpbp/items/2` → **the identical record**. Now open `/p/gh0mlpbp/items/99999`, an id that does not exist → **still the identical record**, no 404, no "not found", no error. So a deep link into a detail page does *not* load the right record, it loads the first one, and a bad id is indistinguishable from a good one. Severity: **blocker**.
  2. **Half the record is invisible.** The visible text is only `Wireless Bluetooth Headphones · Electronics · Stock status · Edit Item`. `Quantity in Stock 42`, `Unit Price 89.99`, `Line Value (Qty × Price)`, `Added 2024-…` and the **Delete Item** button are all stuck in `div[hidden] id="S:0"` / `id="S:1"` — the same streaming failure as `/items`. Severity: **blocker**.
  3. Minor, spotted inside the hidden block: **`Line Value (Qty × Price)` renders as `—`** although quantity is 42 and unit price is 89.99. Severity: **minor** (and it belongs to a display component outside this batch — flagging it, not claiming it).
- **Missing/desired features:** a real not-found state for an unknown id; and a "back to list" link — there is none.
- **Status:** NEEDS_FIX

### `/items/[id]/edit` (scaffold preview)
- **Bugs found:** Two.
  1. **The page is completely blank.** Repro: open `http://localhost:6503/p/gh0mlpbp/items/2/edit` → `document.body.innerText` is the empty string. The form (Name, Category, Quantity, Unit Price, "Save Changes", "Cancel") is in `div[hidden] id="S:0"` / `id="S:1"`. Severity: **blocker**.
  2. **The server-rendered edit form arrives with every field empty.** Reading the markup out of the hidden buffer, the four inputs are `name=""`, `category=""`, `quantity=""`, `price=""` (no `value` attribute at all) for a record whose real values are `Wireless Bluetooth Headphones / Electronics / 42 / 89.99`. Expected: an edit form prefilled with the record. Severity: **blocker** if it stands. **Caveat, stated honestly:** these inputs have **no React fiber** (`__reactProps$…` is absent) because they live in a Suspense buffer that was never adopted, so I could not tell whether a client-side effect *would* have filled them once the page hydrated. This one needs re-testing after bug 1 is fixed — do not treat it as confirmed.
- **NOT TESTABLE IN BROWSER — could not submit, cancel, or navigate away mid-edit,** because the form never becomes visible.
- **Missing/desired features:** n/a until the page renders and prefills.
- **Status:** NEEDS_FIX

<!-- Agent A — navigation batch, session notes.

ONE ROOT CAUSE ACCOUNTS FOR SIX OF THE ENTRIES ABOVE. On a full document load
the scaffold renderer never completes its React Suspense boundaries: the content
is streamed into `<div hidden id="S:n">` and the `$RC("B:n","S:n")` completion
script is simply not emitted (`window.$RC` exists; no call to it does). Anything
inside a boundary is therefore in the HTML and invisible. That is the whole of
the Breadcrumb bug, the whole of `/items/new` and `/items/[id]/edit` being blank
pages, and most of `/items` and `/items/[id]`. Forcing a client re-render (I did
it accidentally by clicking a link) makes the content appear correctly. Fix it
once in the renderer and six entries above collapse to two.

WHAT WORKS, verified and worth recording:
- The CommandPalette does NOT capture the editor's keyboard. Ctrl+K with focus
  in the editor's own "Search components…" box left the box focused and its
  value untouched; Ctrl+K on the canvas opened nothing. ContextMenu is likewise
  correctly scoped: right-clicking a *different* node opened no menu. The
  round-4/5 document-listener trap does not recur in this batch.
- The Style panel works on Breadcrumb: BACKGROUND = `color.primary.500` resolved
  to `rgb(59, 130, 246)` on the rendered `<nav>` (computed, not just persisted),
  and sizing landed on the wrapper. Round 5's "style is dropped or applied
  unresolved" class does not recur here.
- The JSON prop editor has a real error state: invalid JSON in Breadcrumb.ITEMS
  showed "Not saved — Expected double-quoted property name in JSON at position
  19" and kept the last good value rather than blanking the node.
- Browser Back/Forward behave correctly on the previewed app on every page that
  has no Redirect on it.
- Zero React warnings and zero console errors from any of the ten components,
  in the editor or in the renderer. The only editor console traffic was Fast
  Refresh (three fix agents were rebuilding under me throughout).

ENVIRONMENT, for whoever reads this next:
- Editor :6501 was fine but slow — the first compile of /editor/[projectId]
  exceeded 180s while the fix agents were rebuilding; after that, ~7s.
- Scaffold :6503 was up the whole session (first compile 106s).
- Standalone app :6510 was down the whole session (see its entry).
- Scratch page used: /nav-lab-6. /items, /ops-dashboard, /stock-intake,
  /input-lab-2, /input-lab-3, /display-lab-4 and /display-lab-5 were not edited.
  The Redirect node was deleted from /nav-lab-6 after testing so the page is
  previewable; everything else was left in place for Agent B to reproduce.
-->

---

#### CORRECTION (coordinator) — the standalone app and the "Suspense never completes" finding

Agent A's navigation batch reported two things that **do not reproduce** and that
fixers should NOT act on. Both were measured against a state that has since
changed, or misattributed. Recorded here so the final report is honest.

**1. `:6510` is NOT down.** The `Module not found: Can't resolve './FigmaCanvas'`
blocker was real, and I fixed it while Agent A was still running — the file was
missing from `backend/templates/app-foundation/src/lib/` entirely, so *every*
generated app failed to compile, not just this one. Written to the template
(root cause, all future generations) and copied into `output/gh0mlpbp/app`.
Re-measured after the fix:

| route | before | after |
|---|---|---|
| `/items` | 500 | **200** |
| `/items/new` | timeout | **200** |
| `/items/[id]` | timeout | **200** |
| `/items/[id]/edit` | timeout | **200** |

**2. "The scaffold renderer never completes its Suspense boundaries" — NOT
CONFIRMED.** Measured directly on `:6503/p/gh0mlpbp/items`: **4 hidden
`<div hidden id="S:n">` boundaries and 4 `$RC(` completion calls**, i.e. every
boundary completes, with 5300 visible characters of content. The claim that
`$RC` "is never emitted" does not hold against the current build.

**3. What the blank page actually was — auth, not rendering.** The generated app
served 31 characters (`Skip to main content I Loading…`) and appeared frozen.
Driven in a real browser it **redirects to `/login`** and renders a complete
sign-in page (heading "Welcome back", `email` + `password` inputs, "Sign in"
button, footer). The app is behind NextAuth and no session existed. Every route
returning a loading shell to an unauthenticated client is correct behaviour, not
a renderer bug.

**Consequence for the route entries.** `/items`, `/items/new`, `/items/[id]` and
`/items/[id]/edit` were audited **unauthenticated**, so "blank page", "list
invisible", "form arrives empty" and "`[id]` ignored — 1, 2 and 99999 render the
same record" are all unsafe conclusions: an unauthenticated client never reached
the page. **These four routes need re-auditing with a signed-in session before
any fix is attempted.** Agent A flagged the `[id]/edit` hydration caveat itself,
which was the right instinct.

Still open and NOT invalidated by this correction — these were observed in the
**editor canvas**, which needs no auth, and stand as logged: CartBadge rendering
zero DOM, Menubar's empty Props panel, DropdownMenu being unselectable,
CommandPalette's Ctrl+K, Link/NavLink inert defaults, SkipLink's `#main` target,
and Redirect's default making a page unopenable.

---

#### FIX — empty-node hint, rows 27/28 (`Stepper`, `Carousel`, `DescriptionList`, `List`, `Tree`, `ValidationChecklist`)  (frontend)
- **Fix applied:** the hint is now derived from the **component's own Zod schema**, not from the registry descriptor. `frontend/src/components/canvas/empty-hints.ts` gains `schemaMissingProp()`, which reads `propsSchema` off the live library registry (`buildDefaultRegistry().list()`, built lazily on first hint) and ranks the node's blank props structurally: (1) required *and* list-shaped, (2) required, (3) list-shaped with a `[]` default. Wrapper-peeling (`optional` / `default` / `catch` → not required; `nullable` / `preprocess` / `brand` / `pipeline` / `lazy` → still required) is purely by Zod type, so there is **no per-component table anywhere** — it is one rule over all 133 components and it follows a component when its schema changes. `hintFor()` consults it before the old registry-descriptor path, which stays as the fallback for registry-only entries. Row 27: Stepper now reads *“set “steps” in the Properties panel.”* (`steps` is the required array; the old hint named `bind`, `z.string().optional()`, the one prop that was never the problem). Row 28: the five that named no prop at all now name `items` / `images` — their schemas default to `[]`, so nothing was *required*, which is exactly why the descriptor-driven code fell through to the palette blurb.
  Where the schema requires a prop the Properties panel has **no control for**, the hint says so — `“<Type> — needs “<prop>”, which has no control yet.”` — rather than pointing at a control that does not exist. That case is a registry gap, routed below, not patched here.
- **Feature added:** a swept test rather than a fixture list — `frontend/src/__tests__/empty-node-hints.test.tsx` walks every leaf in `starterRegistry`, asks the schema what is missing, and asserts the hint names *that* prop. Assertions are on the prop NAME, never on "a hint appeared": the Stepper bug was a real hint on a real empty node, so a presence-only test passed against it.
- **Status:** RESOLVED

#### FIX — empty-node hint, row 29 (`Lightbox` 960×0, `Dialog` 0×0, `BulkActionBar`, `CartBadge`)  (frontend)
- **Fix applied:** `frontend/src/components/canvas/EmptyNodeHints.tsx` no longer discards a hint when the node's box is smaller than 24×12 — which was backwards, since the node that lays out at 960×0 or 0×0 is the one that most needs marking (invisible *and* undiagnosable). Any empty node smaller than `MIN_HINT_W`×`MIN_HINT_H` (120×16) is now padded out to that minimum and drawn at the node's own position, carrying `data-empty-hint-ghost` and a stronger amber so "renders nothing at all" reads differently from "renders an empty box". The rule is **geometric, not per-component** — nothing in the code knows what a Lightbox is. Editor-only: it inflates the overlay's rectangle, never the node's, so a shipped app's layout is untouched. The hint stays `pointer-events-none`, so a ghost box over a zero-height node's neighbours still cannot eat a click or a drop.
- **Feature added:** none requested. Side effect worth noting — `CartBadge` (span, 0×0, no DOM) now gets a visible marker on the canvas, so the "there is nothing on the canvas to click, select or diagnose" half of that entry is diagnosable; the *selectability* half is not fixed by this and is tracked separately.
- **Status:** RESOLVED

#### ROUTED — registry gaps found by the same sweep (not patched in the frontend)
Running the new schema-vs-descriptor check over the whole registry names, generically, every leaf whose component requires a prop the Properties panel offers no control for. This is the machine-checked version of the auditors' ContextMenu / DropdownMenu / Menubar findings, and it turned up four more:
- `ROUTED: registry — DropdownMenu needs "items" (z.array({label,value,icon?,disabled?})); no descriptor, panel shows only "trigger".`
- `ROUTED: registry — ContextMenu needs "items" (same shape); no descriptor, panel shows only "label".`
- `ROUTED: registry — Menubar needs "menus" (z.array({label, items:[{label,value}]})); entry has props:{} — the empty Props panel reported above.`
- `ROUTED: registry — MoneyInput needs "currencies".`
- `ROUTED: registry — Kanban needs "columnOrder".`
- `ROUTED: registry — CartPanel needs "paymentMethods".`
- `ROUTED: registry — CartPage needs "paymentMethods".`
Until those descriptors exist the canvas hint tells the user the prop is missing *and* that there is no control for it, instead of sending them hunting.
- **Status:** ROUTED

#### GATES (after the above)
`npx tsc --noEmit` → 49 errors, unchanged from the pre-existing baseline (all in `src/lib/*.test.ts` navFlow fixtures). `npx vitest run` → 47 files / **622** tests / 0 failures (613 baseline + 9 new). `npx vitest run src/__tests__/editor-validation.test.tsx` → 21/21, `selectable=129 invalidProps=0 unknownType=0`.

<!-- Agent A — feedback batch (21 components). Scratch page /feedback-lab-7 in
     project gh0mlpbp, own Chrome tab 2076428911. Contract half executed with
     `npx tsx` against the real Zod modules (component <Name>.schema.ts, the
     starter registry, and NodeV2/PageV2); browser half is javascript_tool DOM
     probes on the live canvas. className/style excluded from "missing" counts.
     NOTE: the editor's active page appears to be shared across browser tabs —
     one Alert node (`alert-brw9s7`) of mine landed on /data-lab-7 before I
     noticed and Delete/Backspace on the selected node would not remove it.
     Whoever owns /data-lab-7 should drop that node. -->

### Alert
- **Bugs found:** none. Repro: palette search "Alert" → insert on `/feedback-lab-7` → node `alert-fl8gmf`, **960x48**, renders `Alert message` in a real `role="alert"` box. Contract diff is exact: the Zod object has 4 props (`message`, `variant`, `title`, `style`), the registry exposes all 3 non-style ones, the `variant` enum matches the Zod enum value-for-value **and in order** (`neutral|info|success|danger|warning`), no dead props, no `null` defaults, no control mismatches. `defaultPropsFor("Alert")` = `{message:"Alert message",variant:"neutral",title:""}` parses clean against `AlertProps` **and** against `NodeV2`. `style` is destructured and passed through `resolveStyle`; `useMotion` is wired.
- **Missing/desired features:** the component branches on the `elevation` and `radiusScale` theme tokens but nothing in the Props panel says so — the same Alert looks different between two projects with no visible cause. Minor: no `dismissible` (its sibling `Banner` declares one), and no icon slot even though the palette description promises "severity variants" which usually implies an icon.
- **Status:** CLEAN

### Banner
- **Bugs found:** **`dismissible` is unreachable from the editor** — it is the only Banner prop with no registry descriptor, and it is the one that turns the ✕ button on. Repro: insert Banner → node `banner-u5tiuj`, 960x44, text `Message`; the Props panel offers exactly VARIANT / TITLE / MESSAGE, and there is no way to author a dismissible banner from the editor at all. Expected: a toggle. Actual: the prop exists in `Banner.schema.ts`, is destructured in `Banner.tsx:29` and gates the entire close button, and the editor cannot set it. Severity: **minor** (nothing breaks; a documented feature is simply not authorable).
- **Missing/desired features:** the four-value `variant` enum matches the schema exactly, but there is no `icon` and no `action`/link slot, so a "page-level notification banner" cannot carry the call-to-action that is the usual reason to show one. Also, `Banner` keeps its dismissed state in local `useState`, so in the editor a dismissed banner cannot be brought back except by re-selecting the node — worth a design-time override the way Dialog needs one.
- **Status:** NEEDS_FIX

### Spinner
- **Bugs found:** the dispatcher wrapper for the node measures **0x0 with `display: contents`** (`spinner-nolxmu`) while the actual spinner inside is 24x24 and visible. The component itself is fine — it renders `role="status"` with the sr-only label — but the *selectable box* the canvas draws for the node has no area, so the node is hard to click and any hint overlay has nothing to attach to. This is the mild form of round 5's C9/#29 (Lightbox/Dialog), not the fatal one: the spinner IS visible. Severity: **minor**.
  Contract half is otherwise clean: 4 Zod props, registry exposes `label` and `size`, the `size` enum matches `sm|md|lg` exactly, defaults parse against both `SpinnerProps` and `NodeV2`.
- **Missing/desired features:** no `variant` (dots/bars) and no colour control — the ring is hardwired to `border-t-primary`, so a spinner on a primary-coloured surface is invisible and the Style panel cannot fix it (`resolveStyle` reaches the outer span, not the ring). A user who puts a Spinner on a dark Hero gets nothing.
- **Status:** NEEDS_FIX

### LoadingState
- **Bugs found:** none. Insert → `loadingstate-75f50y`, **960x132**, renders `Loading…`. The Zod object is `.strict()` with exactly `label` (`z.string().min(1)`) and `style`; the registry seeds `label: "Loading…"`, which is a real non-empty value, so the `.min(1)` is satisfied — the failure mode that killed `CodeBlock.code` and `QRCode.value` in round 5 does not occur here. Parses clean against `LoadingStateProps` and `NodeV2`.
- **Missing/desired features:** it is a one-prop component — no `variant` (spinner vs. skeleton vs. text), no `size`, no way to say "this is loading a table" versus "loading a card", so every loading state in a generated app looks identical. Given that `Skeleton` and `Spinner` both exist, `LoadingState` having no way to choose between them is the gap a user notices first.
- **Status:** CLEAN

### EmptyState
- **Bugs found:** none. Insert → `emptystate-tvtnye`, **960x124**, renders `Nothing here yet.` plus a `Get started` button. All 3 non-style Zod props are exposed; `action` is correctly typed `type:"object", control:"json"` against the `union({label,workflow}, {label,navigate})` schema and seeded with a valid `{"label":"Get started","workflow":"createRecord"}` — this is the shape round 4/5 got wrong on eight other components (`actionPicker` on an object prop) and it is right here. Defaults parse clean against `EmptyStateProps` and `NodeV2`.
- **Missing/desired features:** `action` is a raw JSON textarea, so a user has to know that the two legal shapes are `{label,workflow}` and `{label,navigate}` — nothing in the panel says so, and the `description` on the descriptor is the only hint. A two-field control (label + a picker that offers this project's workflows and routes) is what a user expects. Also no `title` — the whole state is one line of message text.
- **Status:** CLEAN

### EmptyStateRich
- **Bugs found:** `illustration` carries **`default: null`** in the registry (`starter.ts`, `emptyStateRichEntry`). `normalizeSeed` now strips `null` before it reaches the node, so this no longer breaks validation — but it is still the wrong way to spell "no seed", and it is the only `default: null` in this whole batch. Per the brief, logging it, **not** treating it as a P0. Severity: **minor**.
  Everything else measured clean: insert → `emptystaterich-hckvbm`, **960x274**, renders the 📦 glyph, `Nothing here yet`, a `Get started` CTA and a `Load sample data` link. `primaryCta` and `sampleDataLink` are both `type:"object", control:"json"` with structurally valid seeds. Defaults parse against `EmptyStateRichProps` and `NodeV2`.
- **Missing/desired features:** `illustration` accepts `union(string, {slug,alt,tone})` and resolves against `/p/<projectId>/illustrations`, but the control is a bare JSON box — there is no picker showing which illustration slugs this project actually has, so the one prop that distinguishes `EmptyStateRich` from `EmptyState` is authorable only by someone who already knows the slug list.
- **Status:** NEEDS_FIX

<!-- Agent A — data batch (batch 3). Scratch page /data-lab-7 in project gh0mlpbp,
     own Chrome tab. Phase 1 = contract diff (registry ↔ component Zod ↔ PageV2,
     introspected with tsx against the real schemas). Phase 2 = live DOM probes
     on the editor canvas. -->

### Sparkline
- **Bugs found:** **A Sparkline dropped from the palette is invisible — it draws a line with `stroke: none`.** Repro: palette search "Sparkline" → click to insert on `/data-lab-7`. The node lands (`sparkline-aq8mkf`, wrapper 960x24, a real `<svg>` 100x24 with a `<polyline>` whose `points` are correct: `0.0,16.7 20.0,10.4 40.0,13.6 60.0,4.1 80.0,7.3 100.0,1.0`). But the polyline's `stroke` **attribute is the empty string** and its computed `stroke` is **`none`** — SVG treats an invalid paint value as the initial value, so nothing is painted. The geometry is right and the ink is off. Counterfactual proven in the same session: select the node → Props → set COLOR to `#ff0000` → the attribute becomes `#ff0000`, computed `rgb(255, 0, 0)`, and the line appears. Cause: the registry seeds `color: { type:"string", default:"", control:"color" }` (`starter.ts` sparklineEntry) while `Sparkline.tsx` declares `color = "currentColor"` as a **JS parameter default**, which only fires for `undefined`. `""` is not `undefined`, so the seed overrides the component's own fallback. This is the `ActivityFeed.maxHeight: 0` class exactly — a registry default read as a command rather than as "unset" — and the round-5 C3c class (`""` seeded where absent was correct). Severity: **major** (drop it and there is nothing to see; the node's box is 24px tall so it is barely selectable, and nothing tells you why).
  Second, smaller: **the COLOR control lies about the current value.** It renders as a native `<input type="color">` whose value reads `#000000` while the prop is actually `""`. So the panel says "black", the canvas says "none", and because a native colour input cannot express "no value" there is **no way to get back to unset** once you touch it.
  Third: the DATA textarea's placeholder is `[{"value": "one", "label": "Option one"}]` — the `Select.options` placeholder — even though this prop is `z.array(z.number()).min(2)`. And the helper line under it reads *"Editing as JSON — rows are not all the same shape"* for a plain array of numbers. Both mislead about the shape required (severity: minor).
  Contract check (tsx introspection): registry ↔ `SparklineNode.shape.props` agree on all five props, no dead props, no truncated enums, and the registry defaults **pass** both the component schema and `PageV2` on a fresh drop.
- **Missing/desired features:** nothing missing from the editor — all five schema props are exposed. What I wanted was a token picker for COLOR (the Style panel offers `Primary · 500` etc. for backgrounds; the sparkline stroke gets a raw hex swatch only) and a way to clear the colour back to "inherit from text".
- **Status:** NEEDS_FIX

#### FIX — DropdownMenu (and every node that acts on pointer-down)  (frontend)
- **Fix applied:** the canvas now takes selection on **pointer-down in the capture phase**, ahead of any runtime handler on the node. `frontend/src/components/canvas/hooks/useSelection.ts` gains `useCanvasPointerDown()` (sharing the modifier logic with the existing click path), wired in `Canvas.tsx` as `onPointerDownCapture` / `onMouseDownCapture` on the canvas root.
  Root cause, and why this is not a DropdownMenu fix: overlay primitives open on **pointer-down**, and while open they put `pointer-events: none` on the document body. By the time the `click` the canvas used to select on was dispatched, the element under the cursor was no longer the node — `closest("[data-node-id]")` returned null and the canvas *cleared* the selection instead of making it. Every component that opens on pointer-down had the same fate; nothing in the fix knows what a DropdownMenu is. `stopPropagation()` on the captured synthetic event is what makes the canvas inert — React replays propagation itself, so the target's own `onPointerDown` never runs and the runtime menu no longer opens while the user is editing. This is the "usual design-time convention of suppressing runtime click handlers inside the canvas" the entry asked for, one event layer below `INERT_NAVIGATOR`.
  Deliberately **not** `preventDefault()`: the defaults there are focus and the start of a native drag, and the canvas needs both (reorder is HTML5 drag). Primary button only, so a right-click still reaches the browser; pointer-down on bare canvas is left alone so a background drag is unaffected.
- **Feature added:** none requested. `frontend/src/__tests__/canvas-selection-pointerdown.test.tsx` (6 tests) covers the report's exact sequence — select on pointer-down, runtime handler suppressed, and selection surviving a follow-up click that has lost the node.
- **Status:** RESOLVED

#### GATES (after the pointer-down fix)
`npx tsc --noEmit` → 49, baseline unchanged. `npx vitest run` → 48 files / **628** tests / 0 failures.

---

<!-- Fixer R — registry pass 1. All edits confined to packages/registry/src/starter.ts
     and packages/registry/tests/. Gates run after every batch: registry build
     (134 entries), packages/registry vitest (27/27), frontend
     editor-validation.test.tsx (21/21, invalidProps=0, selectable=129), and a
     throwaway PageV2 sweep that drops all 133 palette components and parses the
     resulting page. That sweep went 9 failing -> 7, and the remaining 7 are all
     schema-side and routed below. -->

#### FIX — DropdownMenu  (registry)
- **Fix applied:** added the `items` descriptor the component exists for — `type: "array"`, `control: "json"`, seeded `[{label:"Edit",value:"edit"},{label:"Duplicate",value:"duplicate"},{label:"Delete",value:"delete"}]`. `json`, not `actionPicker`: an item is `{label, value, icon?, disabled?}` (DropdownMenuNode/MenuItem is `.strict()` on exactly those four) and actionPicker's only output is an action object, which validateProps' step-3 coercion replaces with `[]`. Seeded rather than empty for the same reason `Breadcrumb.items` is: an empty `json` textarea tells the user nothing about the shape, and a menu that opens empty on drop is indistinguishable from a broken one. Checked against BOTH contracts before writing: `DropdownMenuProps` (library) and `DropdownMenuNode` (schema).
- **Feature added:** `triggerIcon` (iconPicker) and `align` (select: start/center/end) — both declared on DropdownMenuNode and reachable from nothing. NEITHER carries a default: they are `.optional()`, so a seed would freeze a choice on every dropped menu, and `""` on an optional string is present-and-meaningless. Row-level `disabled` is documented in the `items` description (it is part of MenuItem), which covers the auditor's ask for a disabled row; a genuinely *destructive* row style is a component change — see the route below.
- **Status:** RESOLVED
- **Not fixed here (routed):** the node was unselectable on the canvas because the trigger swallows the click — that is design-time click suppression in the editor canvas. ROUTED: frontend — trigger-bearing nodes need runtime click handlers suppressed inside the canvas, or a layers panel. The dead-in-the-app open state and the empty-menu affordance are library-side and already in flight there (MenuEmptyNote).

#### FIX — ContextMenu  (registry)
- **Fix applied:** added the same `items` descriptor (same shape, same seed). LABEL was the only control the panel offered, so the menu a ContextMenu exists to show could not be authored at all — the persisted node was `{"type":"ContextMenu","props":{"label":"Right-click here"}}`.
- **Feature added:** none beyond `items` — `ContextMenuNode` declares only `label` + `items`, so there is nothing further the registry can honestly expose.
- **Status:** RESOLVED

#### FIX — Menubar  (registry)
- **Fix applied:** `props: {}` — the entry had ZERO controls — now carries `menus`: `type: "array"`, `control: "json"`, seeded `[{label:"File",items:[{label:"New",value:"new"},{label:"Open",value:"open"}]},{label:"Edit",items:[...]}]`. Shape is MenubarNode's exactly: `MenubarItem` is `.strict()` on `{label, value}` — no icon, no disabled — so the seed and the description say that and no more.
- **Feature added:** the auditor asked for separators, submenus and shortcuts. NOT added, deliberately: `Menubar.tsx` renders `RMenubar.Item` only and `MenubarItem` is `.strict()` on two keys, so a registry control for them would write props nothing reads and the schema rejects — the exact defect this round is fixing. ROUTED: library/schema — Menubar needs separator / submenu / shortcut support on MenubarItem before the editor can offer it.
- **Status:** RESOLVED

#### FIX — Link  (registry)
- **Fix applied:** removed the `""` defaults from `navigate` and `workflow`. `Link.tsx` puts `navigate` straight into `href`, so the seeded `""` rendered `<a href="">` on every dropped Link — blue, underlined, `cursor:pointer`, and completely inert. Absent lets `LinkProps.navigate`'s own `.default("#")` apply, which is the component's declared "no destination yet" value. `workflow` is `.optional()` and gated on `if (workflow)`, so `""` was only a longer spelling of absent that made the prop look set in the panel.
- **Feature added:** none requested that the registry can supply. `target="_blank"` / external-URL handling, an explicit unset/disabled visual state and `aria-current` are all props `LinkProps` does not have and `Link.tsx` does not read. ROUTED: library — Link needs target/rel, a visibly-unset state, and aria-current. ROUTED: frontend — destination props (Link.navigate, NavLink.navigate, Redirect.to, SkipLink.target) want a picker over the project's real routes instead of free text.
- **Status:** RESOLVED

#### FIX — NavLink  (registry)
- **Fix applied:** the entry's two behaviour props were **dead descriptors** — `NavLink.tsx` reads `href | navigate | label | children | currentPath | className | style` and neither `target` nor `icon` is among them, so `target` was a text box whose value validateProps silently stripped and `icon` was an icon picker with no reader at all. Replaced `target` with `navigate` (the name the component and the `unifyLabelHref` remap actually read) and removed `icon`. `navigate` carries NO default for the same reason as Link's — `""` would put `href=""` on the anchor; absent lets NavLink.tsx's own `?? "#"` apply. The missing `aria-current` the auditor reported is not missing from the component (`NavLink.tsx` emits it when `currentPath === dest`); it was unreachable because the destination prop the user filled in was being thrown away.
- **Feature added:** none. The icon control is not re-added as a lie. ROUTED: library — NavLink needs an `icon` prop and an activeClassName before the registry can expose them.
- **Status:** RESOLVED

#### FIX — Redirect  (registry)
- **Fix applied:** removed the `to: "/"` default. This is the command-default trap in its purest form: `Redirect.tsx` runs `nav.replace(to)` in a mount effect, so a seeded `to` is not a placeholder value, it is an instruction the component executes the instant the node exists — which is why a Redirect dropped with its defaults made the page permanently unopenable and trapped the Back button. The mount effect is gated on `if (to)`, so an unseeded Redirect sits quietly showing "Redirecting…" until the user names a destination. Also dropped the `label: ""` seed (`.optional()`, rendered as `label || "Redirecting…"`).
- **Feature added:** none requested that the registry can supply. The base-path bug (`to` resolved against the origin root, so every Redirect 404s under `/p/<project>/`), the self-route guard and the "disabled while editing" toggle are all outside the registry. ROUTED: library/renderer — Redirect.to must resolve through the Navigator's base path, and refuse a `to` equal to the page's own route.
- **Status:** RESOLVED

#### FIX — Grid  (registry) — class fix, not logged by an auditor
- **Fix applied:** removed `rowGap`, `columnGap`, `padding` and `align`. They were dead in both directions at once: `renderer/src/nodes/layout/Grid.tsx` reads exactly `columns`, `gap`, `rows`, `equalRows`, `equalCols`, `className`, `style` — the four had no reader, so setting them moved nothing on the canvas — and `V2GridNode.props` is `.strict()` over `{columns, rows, gap, equalRows, equalCols}`, so seeding them ALSO made every palette-dropped Grid produce a page `PageV2` rejects. That is the same mechanism as the ContextMenu addendum's `[scaffold] schema validation failed … rendering raw`, where three bad nodes took the other nine on the page down with them. `gap` remains and covers the common case.
- **Feature added:** none. ROUTED: renderer/schema — Grid should implement rowGap / columnGap / padding / align (unread by Grid.tsx today, and undeclared on V2GridNode) before the editor offers them again.
- **Status:** RESOLVED

#### FIX — Skeleton  (registry) — class fix, not logged by an auditor
- **Fix applied:** removed the `lines: 3` default. `variant` defaults to `"rect"` and `SkeletonNode` carries a cross-field refinement — "Skeleton.lines is only valid when variant is 'text'" — so the two seeds contradicted each other and every dropped Skeleton produced a page `PageV2` rejects. The control stays; its description now says it is only valid when VARIANT is text.
- **Feature added:** none requested.
- **Status:** RESOLVED

#### FIX — the 21 input `name` seeds  (registry) — class fix, 21 descriptors, one rule
Input, Textarea, Select, Checkbox, Switch, NumberInput, RadioGroup, Slider, FileUpload, Combobox, TimePicker, ColorPicker, InputOTP, Rating, MaskedInput, KeyValueInput, SegmentedControl, Calendar, RichTextEditor, CameraCapture, DatePicker.
- **Fix applied:** removed `default: ""` from all 21 `name` descriptors. `name` is `z.string().min(1)` on every input's node schema, so `""` is not "unset" — it is present-and-too-short, and it made the registry's own published seed the one value the schema is guaranteed to reject. It was never what a dropped field actually carried either: `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so two "Email" fields do not collide. Unseeded, the drop path behaves exactly as before and the registry stops publishing an invalid value to its other consumers (the JSON export, the LLM catalog, the properties panel).
- **Feature added:** none requested.
- **Status:** RESOLVED

#### FIX — Repeat / Conditional  (registry) — class fix, not logged by an auditor
- **Fix applied:** removed the `""` seeds from `Repeat.source`, `Repeat.bind` and `Conditional.when`. `V2RepeatNode.props.source` is `z.string().min(1).optional()` (absent is valid, `""` never is); `V2ConditionalNode.props.when` is an Expression that rejects the empty string outright; and `bind` is not a declared key of `V2RepeatNode`'s `.strict()` props at all, so seeding it guaranteed a rejected page. All three render identically when absent, so nothing on the canvas changes.
- **Feature added:** none requested. `bind` is kept as a control because `renderer/src/nodes/data/Repeat.tsx` genuinely reads `props.bind`. ROUTED: schema — V2RepeatNode.props needs `bind` (the runtime reads it; the node documents it as a TOP-LEVEL key the properties panel cannot reach).
- **Status:** RESOLVED

#### FIX — registry ↔ node-schema parity guard  (registry) — the mechanism, not the instances
- **Fix applied:** new `packages/registry/tests/node-schema-parity.test.ts`. Every defect above is one class: *the registry publishes a prop or a value the component's own `.strict()` node schema refuses, the editor writes page JSON `PageV2` rejects, and the scaffold drops the WHOLE page out of validated rendering.* The test introspects `NodeV2`'s own union (the same one `PageV2` validates with, resolved after a warm-up parse so the `z.lazy` body is built) and asserts four things per prop, with no page assembly and no copy of the frontend drop pipeline: that the strict shapes actually resolved (guard-the-guard, so it can never pass vacuously); that no registry prop is absent from the strict node props shape; that no `default` is a value that prop's schema refuses; and that every prop the node marks REQUIRED has a control to fill it — which is exactly what Menubar / ContextMenu / DropdownMenu failed. Numeric-domain enums (`Heading.level: "2"`) are exempted the same way `normalizeSeed` exempts them, keyed off the descriptor and never off a component name. The outstanding schema-side gaps are listed by name with their reason, so they have to be deleted rather than the list quietly grown.
- **Feature added:** n/a (test).
- **Status:** RESOLVED

#### NOT FIXED by the registry — routed, with reasons (nothing left silent)
- **CartBadge** — `CartBadge.tsx` returns `null` whenever `count == null`, which is every editor canvas and every app without a live `/api/cart`. The registry defaults are already correct and complete (`href:"/cart"`, `label:"Cart"`, `hideZero:false`); no descriptor change can make a component that returns `null` render, and seeding a fake count would be a command default. ROUTED: library — CartBadge must render a design-time/zero state instead of null. (Already in flight there.)
- **SkipLink** — the registry default `target: "main"` matches `SkipLinkProps`' own `.default("main")` and its documented contract ("the id the shell template stamps on its `<main>`"). The failure is that the rendered `<main>` carries no `id`. Changing the registry default would point the link at a different element that also does not exist. ROUTED: renderer/scaffold — the page shell's `<main>` must carry `id="main"`.
- **Breadcrumb** — no registry defect: `items` is already a seeded `json` array with the right shape and `separator` is correct. The ask is a row-per-crumb editor with a route picker and a `currentPageAuto` option. The first two are a control the editor does not have; `currentPageAuto` is not a prop `BreadcrumbProps` or `BreadcrumbNode` accepts, so a descriptor for it would be a control writing a prop nothing reads. ROUTED: frontend — array-of-objects props want a row editor with a route picker (Breadcrumb.items, CommandPalette.items, DropdownMenu/ContextMenu.items, Menubar.menus). ROUTED: library/schema — Breadcrumb needs currentPageAuto.
- **CommandPalette** — registry seeds are correct (two real sample commands, placeholder, triggerKey). `triggerKey` is left as free text because `CommandPaletteNode` types it as a plain string: an enum of modifiers would be a registry control writing a shape the schema does not accept. ROUTED: frontend — triggerKey wants a modifier picker plus a browser-shortcut conflict warning. ROUTED: library — the advertised Ctrl+K listener never fires, focus is not moved into the search box on open, and the overlay has no `role="dialog"` / `aria-modal`.
- **`/items`, `/items/new`, `/items/[id]`, `/items/[id]/edit`, and the standalone app on :6510** — no registry surface at all. The React-streaming boundaries that never swap in, the ignored `[id]` segment, the unprefilled edit form and `Can't resolve './FigmaCanvas'` are generator/scaffold defects. ROUTED: scaffold/generator — not a registry change. Flagged explicitly rather than left silent.
- **Container** — the six flex props (`direction`, `gap`, `padding`, `align`, `justify`, `wrap`) are fully implemented by `renderer/src/nodes/layout/Container.tsx` (its header documents them) but `V2ContainerNode.props` is `.strict()` over `maxWidth` alone, so **every palette-dropped Container makes its page fail `PageV2`**. Deliberately NOT patched by deleting working controls or unseeding them — that would change the default look of every new page in order to fix a schema bug. ROUTED: schema — V2ContainerNode.props needs direction/gap/padding/align/justify/wrap. This is the widest instance of the class, since Container is the node every page is built inside.
- **FileUpload / RadioGroup / TimePicker** — same shape: `filenameField`, `mimeTypeField`, `resumable`, `retryOn5xx`, `chunkSizeMb` (declared in `FileUpload.schema.ts`) and `disabled` (destructured and forwarded by `RadioGroup.tsx` / `TimePicker.tsx`) are all implemented and all rejected by their `.strict()` node schemas. ROUTED: schema — FileUploadNode needs the five Wave-3 upload props; RadioGroupNode and TimePickerNode need `disabled`.
- **Tabs** — `tabs: []` is refused by `TabsNodePlain.props.tabs.min(1)`, but a freshly dropped Tabs legitimately has no panels and Tabs now derives one tab per CHILD. Seeding a tab would cap the strip at one panel — the exact bug the Tabs remap exists to undo. ROUTED: schema — TabsNode.props.tabs should allow `[]` (under-configured is not malformed), the same relaxation the menu nodes just received.
- **Repeat / Conditional, structural** — both are `children.min(1)` on their node schemas, so an empty control-flow node dropped from the palette can never be valid no matter what the registry seeds. ROUTED: schema — V2RepeatNode / V2ConditionalNode children should allow `[]` while unconfigured.

### IllustratedEmpty
- **Bugs found:** **The registry seeds the required title as the empty string, so the component drops onto the canvas with no words on it.** Repro: palette search "IllustratedEmpty" → insert on `/feedback-lab-7`. The node (`illustratedempty-df4qvp`, then `illustratedempty-osb989`) measures **960x239** and its `innerText` is **`""`** — the SVG glyph renders and the heading is blank. The persisted page JSON is literally `{"kind":"list","title":"","message":"","action":""}`. `IllustratedEmptyProps.title` is `z.string().min(1)` and **not** optional; `safeParse(defaultPropsFor("IllustratedEmpty"))` fails with `title: too_small`. Expected: a seeded headline the way `EmptyState` seeds `"Nothing here yet."`. Actual: a 240px-tall illustration with an empty heading where the headline belongs. Severity: **major**.
- **Second bug in the same entry:** **`action` has the wrong descriptor type entirely.** The Zod prop is `union({label,workflow}, {label,navigate})` — an object — and the registry declares it `type:"string", control:"text", default:""`. The Props panel therefore offers a plain text box for a structured action, and the seed `""` makes the same props parse fail a second time with `action: invalid_union`. Because `validateProps` step-3 coercion has no branch for `too_small` or `invalid_union`, **both errors fall through and the raw props are handed to the component uncoerced** — so every Zod `.default()` on this component is skipped, which is round 5's C2 mechanism arriving through a different door. `""` is falsy so the CTA silently renders nothing rather than crashing. Severity: **major**.
- **Missing/desired features:** the ten-value `kind` enum is complete and correctly ordered, which is the one thing this entry gets right — but with the title blank, none of the ten presets is usable out of the box. A user also expects the CTA to be authored with a label field plus a workflow/route picker, exactly as `EmptyState.action` already is in the sibling entry.
- **Status:** NEEDS_FIX

### Skeleton
- **Bugs found:** **A palette-dropped Skeleton writes page JSON that the project's own `PageV2` schema rejects.** Repro: insert Skeleton → the node is seeded `{"variant":"rect","lines":3}` (both registry defaults, verified via `defaultPropsFor`). `NodeV2`'s `superRefine` carries the invariant *"Skeleton.lines is only valid when variant is 'text'"*, so `NodeV2.safeParse({id,type:"Skeleton",props:{variant:"rect",lines:3}})` **FAILS** at `props.lines`. This is the **only one of the 21 that fails the node-schema check**, and it fails on nothing but its own untouched registry defaults. Expected: the seed the editor writes is valid against the schema the editor validates against. Actual: `rect` + `lines: 3` is a contradiction the registry ships by default. Severity: **major** (a page that cannot be re-validated is a page no strict consumer can re-open).
  The render itself is fine — `skeleton-xs9v9y` measures 960x64 and shows the `animate-pulse bg-muted` block, because `Skeleton.tsx` only reads `lines` inside the `variant === "text"` branch. So the invalid prop is *silent* at render time and only bites at validation time, which is the worst of both.
- **Missing/desired features:** `lines` is offered unconditionally, with no indication that it applies to exactly one of the three variants — the Props panel should hide or disable it for `rect`/`circle` rather than seeding a value the page schema forbids. There is also no `width`/`height` control, so a `rect` skeleton is always `h-16 w-full` and cannot be shaped to stand in for the thing it is loading.
- **Status:** NEEDS_FIX

### Progress
- **Bugs found:** **`showValue` is unreachable, so a Progress can never display its own number.** Repro: insert Progress → `progress-wd1wy3`, 960x58, renders the label `Progress` and a filled bar; the Props panel offers exactly LABEL / VALUE / VARIANT. `ProgressProps` declares 8 props; `max`, `showValue` and `bind` have **no registry descriptor at all**. `showValue` is the flag that gates the percentage readout in both the bar and the circular branch (`Progress.tsx`), so from the editor the percentage is unauthorable. Switching `variant` to `circular` makes it worse: that branch renders a ring **and nothing else** — no label, no number — so a circular Progress in a generated app is a decorative arc with no readable value. Severity: **major**.
  `max` being unreachable means every Progress is hardwired to a 0–100 scale; a "3 of 7 steps complete" progress cannot be expressed. `bind` being unreachable means the value cannot be driven from data at all — a progress bar that can only ever show the literal number typed at design time. Severity: **major**.
- **Missing/desired features:** no colour control, no indeterminate state (the obvious companion to `Spinner`), and no size. Given `Gauge` exists separately with threshold zones, `Progress` at least needs its own value readout.
- **Status:** NEEDS_FIX

### PresenceIndicator
- **Bugs found:** **Renders absolutely nothing on the canvas, and gets no empty-node hint either.** Repro: palette search "PresenceIndicator" → insert on `/feedback-lab-7` → node `presenceindicator-ufyu7g` exists in the tree but measures **0x0**, `childElementCount === 0`, `display: contents`, `innerText` empty. There is no DOM under it whatsoever. I probed the canvas for the hint overlay and there are **zero** hint elements on the page — the zero-sized box has nothing for the overlay to attach to. This is round 5's Lightbox/Dialog failure and the navigation batch's CartBadge failure, a third time: **invisible AND undiagnosable**. Severity: **major**.
  Cause (explains the observation, does not stand in for it): `PresenceIndicator.tsx` ends its setup with `if (users.length === 0) return null;`. `users` is populated only from a `users` prop — which is **not in the Zod schema and not in the registry**, so nothing can ever set it — or from `window.__forgePresenceHook__`, which the renderer installs at runtime and the editor canvas does not. So in the editor the list is permanently empty and the component permanently returns `null`.
- **Missing/desired features:** a design-time preview. Every other avatar-ish component seeds sample data; this one needs either a seeded `users` array (which would also make `max`, `size` and `showTooltips` meaningful, since all three are exposed and none can currently change anything you can see) or a canvas-only placeholder showing two or three stub avatars. As shipped, the four exposed props are four controls that provably cannot alter the render.
- **Status:** NEEDS_FIX

### UndoManager
- **Bugs found:** **Renders absolutely nothing on the canvas, with no hint.** Repro: insert UndoManager → node `undomanager-qbrypp`, **0x0, `kids: 0`, `display: contents`**, empty text, and no hint overlay anywhere on the page. Identical shape to PresenceIndicator above. Severity: **major**. Cause: `UndoManager.tsx` returns `null` while `entries.length === 0`, and entries arrive **only** from a `window` `CustomEvent("forge:undo:push")` dispatched by the renderer's mutation queue — which never fires in the editor. All four exposed props (`position`, `timeoutMs`, `labelPrefix`, `maxStack`) therefore control something the author can never see.
- **Second bug:** **`position` is a free-text box against a four-value Zod enum.** The registry declares `position: { type:"string", control:"text", default:"bottom-center" }`, but `UndoManagerProps.position` is `z.enum(["bottom-left","bottom-center","bottom-right","top-center"])`. The panel invites the user to type, and any typo — `bottom-centre`, `bottomCenter` — fails the props parse; `validateProps` has no coercion branch for `invalid_enum_value`, so the raw string is passed through, `POSITION_STYLES[position]` is `undefined`, and the toast stack lands unpositioned in the top-left corner of the viewport. Same class as round 5's `SplitArc.segments`, one type over. It should be `type:"enum", control:"select"` with the four options. Severity: **major**.
- **Missing/desired features:** a design-time "show a sample toast" toggle, the way `InspectorPanel` gained `defaultOpen` for exactly this reason. Without one, `position` and `maxStack` cannot be checked against the page layout they will eventually cover.
- **Status:** NEEDS_FIX

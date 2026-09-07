# Live browser test — Claude in Chrome, 2026-09-05

Driven as a user: real Chrome, real editor, real clicks. Drop actions dispatched as
genuine HTML5 DragEvents with a real DataTransfer (synthetic mouse events cannot
drive native drag-and-drop), so the app's own `onDrop` handler ran unmodified.

## VERIFIED WORKING (first browser confirmation of these fixes)

| What | Evidence |
|---|---|
| Grid drops as a fixed 2x2 with addressable cells | `grid-bd8gng` + `gridcell-{jqkmu6,jr367d,3oc7a2,m3g4i3}` |
| Editor-only gridlines render on canvas | dashed cell boundaries visible, no borders in output |
| **Card drops INTO a grid cell** | `card-tdyjoy`.closest('[data-grid-cell]') === `gridcell-jqkmu6` |
| Drop-derived sizing (REGION shape) | `width: 604px; max-width: 100%; min-height: 108px` |
| Background accepts a CSS colour NAME | typed `rebeccapurple` -> inline `background: rebeccapurple` -> computed `rgb(102,51,153)` |
| Token-wrap bug gone (all 3 copies) | no `var(--token-rebeccapurple)` anywhere in the emitted style |
| Design System offers valid union values | RADIUS SCALE shows `sharp` (was the dead `rounded`/`pill`) |
| Empty-node hint overlay renders | "Container — empty. Drag a component in here." |
| `/items/[id]` exists in the page list | listed as DETAIL |

## NEW BUGS FOUND IN THE BROWSER

### B1. `/editor/<shortId>` is a broken shell — HIGH
Navigating to `http://localhost:6501/editor/gh0mlpbp` (the obvious editor URL) renders
no palette, no pages list, no properties panel — just a phantom tab "home" reading
**"No schema at home.json"**, a page that does not exist. The working editor is only
reachable via `/org/<orgId>/projects/<projectId>` then the layout icon in the rail.
A user who bookmarks or guesses the editor URL gets a dead screen.

### B2. Empty-node hint overlay overflows the viewport and covers the Properties panel — MEDIUM
`getBoundingClientRect()` on the hint: `right: 1575.2` against a **1568px** viewport.
It paints over the STYLE panel between ELEVATION and RADIUS SCALE, and is clipped off
the right edge of the window. The overlay is not constrained to the canvas bounds.
Regression in the brand-new `EmptyNodeHints` overlay.

### B3. Palette click-to-insert does nothing — HIGH (confirms audit finding)
Clicking `Grid` in the COMPONENTS palette adds no node; the canvas still contained only
`container-nvtlqo` afterwards. Components are drag-only. Any user who cannot drag
(trackpad, accessibility, touch) has no way to add a component at all.

### B4. Committing a style value clears the selection — MEDIUM
Typing a colour into BACKGROUND and pressing Enter applies the value, but the node is
deselected: the panel resets to "Select a node to edit its style." A second edit
requires re-selecting the node on canvas. Breaks the natural edit-tweak-tweak flow.

### B5. `{{metrics.*}}` binding leak confirmed on-canvas — P0 (already in audit)
`/items` renders `{{metrics.list_total_inventory_value}}` and `{{metrics.list_items}}`
as literal text in the editor canvas, exactly as it does in preview.

---

## Round 2 — layout group driven live

### VERIFIED WORKING
| What | Evidence |
|---|---|
| All 9 remaining layout components drop VISIBLE | Split 604x108 (+2 panes), Tabs 604x108, Divider 604x1 (hairline intact), Stack/Row/Section/Cluster 604x108, Spacer 604x26, Hero 604x292 |
| **Tabs multi-panel FIXED** | 2 `role="tab"` buttons, 2 `role="tabpanel"` rendered, 2 TabPanel nodes |
| **Split two-pane works** | inner `grid gap-6 w-full`, columns `289.993px 290.005px` |
| Sidebar scaffolds both panes on drop | panes `aside` + `main`, each a Card |
| Card into a grid cell | `card-tdyjoy` inside `gridcell-jqkmu6` |

### B6. Sidebar's main pane collapses to 22px in a narrow parent — HIGH
Dropped into a grid cell (~294px), computed `grid-template-columns: 239.993px 22.0114px`.
The 240px sidebar track is hard-coded with no minimum on the content track, so in any
parent narrower than ~400px the main pane is effectively zero. Renders as a solid block.

### B7. Device preview does not reflow ANYTHING — HIGH
Switching to the phone viewport sets the canvas frame to **375px**, but:
- container stays `width: 668px` (overflows the frame by 293px)
- grid stays `width: 604px`, columns `294px + 294px`
- sidebar stays `240px + 22px`, split stays `290px + 290px`

Root cause chain: drop-sizing writes a px `width` on every node, and the `max-width: 100%`
guard resolves against a parent that is ITSELF px-fixed (`container` = 668px from a user
resize), so it never binds. The device buttons change the frame and nothing inside responds.

**This is the direct cost of "size everything to match the parent".** It conflicts with the
user's other decision ("fixed in editor, responsive in app"). Needs a deliberate resolution:
e.g. store the drop size as a max/min rather than a fixed width, or make the device switch
temporarily neutralise authored px widths.

### B2 (updated) — empty-node hints paint across the whole app — now HIGH, was MEDIUM
Screenshots show hints rendering over the toolbar (across the Export button) and over the
Properties panel, not merely off the right edge. They also do NOT reposition when the device
viewport changes. The overlay is unclipped and stale.

---

## Round 3 — the 6 untested layout components. COVERAGE NOW 21/21.

| # | Component | Result |
|---|---|---|
| 16 | `AppShell` | **PASS** — 604x678, canvas + palette survive. **The CRITICAL prop crash is FIXED**: sidebar/topbar/actions now render as raw JSON textareas (pre-filled `{"type":"SideNav","props":{}}`) instead of the `actionPicker` that blanked the page. |
| 17 | `InspectorPanel` | **INVISIBLE** — 0x0. `position: fixed`, `if(!active) return null`. Not canvas layout; should not be in the layout palette. |
| 18 | `TabPanelWithDeepLink` | PASS — 604x108 |
| 19 | `Drawer` | **INVISIBLE** — 0x0. Viewport-anchored overlay, same class as InspectorPanel. |
| 20 | `CartPage` | PASS — 604x200 |
| 21 | `SplitView` | **PASS — the 117-failure bug is FIXED.** 3 nodes added (itself + 2 scaffolded panes), 604x142, visible. |

### B8. Two layout-palette entries can never render on canvas — MEDIUM
`InspectorPanel` and `Drawer` are both 0x0 by construction (fixed-position, conditionally
null). They are offered in the LAYOUT group but cannot be used as layout. Either move them
out of that group, or give them an editor-only canvas representation.

### B9. AppShell's topbar/actions default to a SideNav — LOW
All three composition props pre-fill with `{"type":"SideNav","props":{}}`. A top bar and an
actions slot defaulting to a *side* nav looks like a copy-paste default.

## FULL LAYOUT COVERAGE — 21/21 tested live in the browser
PASS (17): Container, Grid, GridCell, Card, Divider, Spacer, Hero, Stack, Row, Section,
Tabs, TabPanel, Sidebar, Cluster, Split, AppShell, TabPanelWithDeepLink, CartPage, SplitView
INVISIBLE BY CONSTRUCTION (2): InspectorPanel, Drawer
Defects found: B6 (Sidebar 22px pane), B7 (no reflow), B8, B9 — plus shell bugs B1-B5.

---

## Round 4 — creating a page per layout kind, from the New page dialog

Created live via the dialog: Layout Sidebar / Topnav / Dashboard / List / Detail.

| Page | Kind | Root | Nodes | Encoding |
|---|---|---|---|---|
| layout-sidebar | Sidebar | `Sidebar` | 7 | utf-8 OK |
| layout-topnav | Top nav | `Stack` | 12 | utf-8 OK |
| layout-dashboard | Dashboard | `Container` | 10 | utf-8 OK |
| layout-list | List | `Container` | 7 | utf-8 OK |
| layout-detail | Detail | `Container` | 12 on disk / **0 rendered** | **BROKEN** |

### B10. The Detail template writes a corrupt file — cp1252 instead of UTF-8 — HIGH
`output/gh0mlpbp/src/schemas/layout-detail.json` fails UTF-8 decode at byte 2305:

    context: b'"content": "\x97",'

`0x97` is an em-dash encoded in **cp1252**. The Detail template is the only one of the five whose
placeholder content contains a non-ASCII character, so it is the only one that corrupts. The page
holds 12 nodes on disk and renders **0** — a blank page with no error shown to the user.

This is a LIVE instance of the systemic bug Phase 1a reported: **260 `write_text` call sites under
`backend/{services,routers,agents}` with no `encoding=`**, which on Windows default to cp1252.
Phase 1a fixed three test-visible cases and flagged the class; this is the first confirmed
user-facing one. Any page whose content contains an em-dash, curly quote, accent or symbol will
corrupt the same way.

### Corrections to earlier entries in this file
- The first "New page silently failed" observation was **wrong** — a mis-landed click on a dialog
  that reflows when a kind is selected (choosing Sidebar adds a "Navigation links" section and
  moves the Create button down ~26px). Page creation works. Retained as a minor UX note: the
  primary button moves after the user picks an option.
- New page DOES switch the canvas to the newly created page.

### Also observed
- The Sidebar kind derives its nav links from the project's real routes (Items / New / Issueform).
- The dialog's helper text updates per kind ("A bare container. Drag components in from the palette.",
  "A pinned left nav rail beside the page content.").

---

## Round 5 — pages for Row / Section / Cluster / Tabs / Split / SplitView / AppShell / CartPage / InspectorPanel / Drawer

**`/layout-structure`** — Container > Stack > Heading, Row, Section, Cluster, Divider, Spacer
| Component | Size | Children accepted |
|---|---|---|
| Row | 1150x40 | 1 of 2 Buttons |
| Section | 1150x96 | 2 of 2 (Heading, Text) |
| Cluster | 1150x96 | 3 of 3 Badges |
| Divider | 1150x17 | n/a |
| Spacer | 1150x24 | n/a |

**`/layout-panels`** — Container > Stack > Heading + the seven panel components
| Component | Size | Note |
|---|---|---|
| Tabs | 1150x56 | only 1 tab button — 1 of 2 TabPanels landed |
| Split | 1150x96 | + 2 scaffolded Card panes |
| SplitView | 1150x130 | + 2 scaffolded Card panes |
| AppShell | 1150x678 | renders full page frame |
| CartPage | 1150x483 | renders |
| InspectorPanel | **0x0** | invisible by construction |
| Drawer | **0x0** | invisible by construction |

### B11. Rapid successive drops into the SAME parent can silently lose one — PROBABLE BUG
Two independent occurrences in this session:
- `Row` received 1 of 2 Button drops
- `Tabs` received 1 of 2 TabPanel drops (with ~1.0-1.1s between them)

Not deterministic — an earlier run on `/issueform` DID get 2 TabPanels into one Tabs with slightly
shorter gaps. Consistent with a race in the store's insert path where a second insert computed
against a stale parent is dropped. Needs a deterministic repro before it is called confirmed;
recorded here because it happened twice and it loses user work SILENTLY (no error, no toast).

### Confirms B8 again
`InspectorPanel` and `Drawer` measured 0x0 on a second, independent page. They are in the LAYOUT
palette group but cannot render on a canvas.

## PAGES BUILT (8 new, all via the New page dialog)
layout-sidebar, layout-topnav, layout-dashboard, layout-list, layout-detail (corrupt),
layout-grid, layout-structure, layout-panels

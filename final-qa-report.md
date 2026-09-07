# Final QA report

Cross-check of `qa-audit-log.md` and the round reports in `docs/editor-audit/`, against the **registry** as the source of truth for what exists.

Coverage is asserted against the registry rather than against the log, so a component nobody tested shows up as a gap instead of silently missing.


**112 of 133 components have a row below.** Never tested: **21**. Found but not fixed: **12**.


| Component/Route | Category | Tested | Bugs Found | Bugs Fixed | Features Requested | Features Added | Final Status |
|---|---|---|---|---|---|---|---|
| Container | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Grid | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Card | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Divider | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Spacer | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Input | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Textarea | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Select | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Checkbox | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Switch | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| NumberInput | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| MoneyInput | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| MoneyDisplay | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| RadioGroup | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Slider | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| FileUpload | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Combobox | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| DropdownMenu | navigation | Y | 2 | yes | 2 | yes | RESOLVED |
| Popover | feedback | **N** | - | - | - | - | **NEVER TESTED** |
| Tooltip | feedback | **N** | - | - | - | - | **NEVER TESTED** |
| ContextMenu | navigation | Y | 2 | yes | 2 | yes | RESOLVED |
| HoverCard | feedback | **N** | - | - | - | - | **NEVER TESTED** |
| Menubar | navigation | Y | 1 | yes | 1 | yes | RESOLVED |
| Drawer | feedback | **N** | - | - | - | - | **NEVER TESTED** |
| Button | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Heading | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Hero | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| MetricTile | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Avatar | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Stack | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Row | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Breadcrumb | navigation | Y | 1 | no | 1 | - | **OPEN** |
| NavLink | navigation | Y | 1 | yes | 1 | yes | RESOLVED |
| Section | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Tabs | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| TabPanel | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Table | data | **N** | - | - | - | - | **NEVER TESTED** |
| Badge | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Alert | feedback | Y | 0 | - | 1 | - | CLEAN |
| EmptyState | feedback | Y | 0 | - | 1 | - | CLEAN |
| Form | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| IconButton | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Sidebar | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Cluster | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Split | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| AppShell | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| InspectorPanel | feedback | **N** | - | - | - | - | **NEVER TESTED** |
| TabPanelWithDeepLink | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Chart | data | **N** | - | - | - | - | **NEVER TESTED** |
| Sparkline | data | Y | 1 | no | 1 | - | **OPEN** |
| DataGrid | data | **N** | - | - | - | - | **NEVER TESTED** |
| EditableLineGrid | data | **N** | - | - | - | - | **NEVER TESTED** |
| Timeline | data | **N** | - | - | - | - | **NEVER TESTED** |
| TableSortable | data | **N** | - | - | - | - | **NEVER TESTED** |
| ApprovalStepper | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| PersonCard | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| FilterBar | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| CommandPalette | navigation | Y | 1 | no | 1 | - | **OPEN** |
| ActivityFeed | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| EmptyStateRich | feedback | Y | 1 | no | 1 | - | **OPEN** |
| DateRangePicker | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| MultiSelect | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| FeatureCard | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Skeleton | feedback | Y | 1 | yes | 1 | yes | RESOLVED |
| LoadingState | feedback | Y | 0 | - | 1 | - | CLEAN |
| KeyValueList | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Link | navigation | Y | 1 | yes | 1 | yes | RESOLVED |
| TimePicker | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| ColorPicker | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| InputOTP | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Rating | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| MaskedInput | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| KeyValueInput | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Gauge | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| SplitArc | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Heatmap | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Schematic | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Stepper | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Tag | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Stat | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| DescriptionList | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| List | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| SegmentedControl | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Tree | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Transfer | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Cascader | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Calendar | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Kanban | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| ResourceTimeline | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| RichTextEditor | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Carousel | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Lightbox | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| CodeBlock | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| QRCode | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| BarcodeScanner | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| CameraCapture | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Scanner | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| ValidationChecklist | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| DatePicker | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| FadeIn | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Stagger | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Repeat | data | **N** | - | - | - | - | **NEVER TESTED** |
| Conditional | data | **N** | - | - | - | - | **NEVER TESTED** |
| DataBoundary | data | **N** | - | - | - | - | **NEVER TESTED** |
| Slot | data | **N** | - | - | - | - | **NEVER TESTED** |
| Progress | feedback | Y | 1 | no | 1 | - | **OPEN** |
| Spinner | feedback | Y | 1 | no | 1 | - | **OPEN** |
| Redirect | navigation | Y | 1 | yes | 1 | yes | RESOLVED |
| Banner | feedback | Y | 1 | no | 1 | - | **OPEN** |
| Dialog | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| AddToCart | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| CartBadge | navigation | Y | 2 | no | 2 | - | **OPEN** |
| CartPanel | data | **N** | - | - | - | - | **NEVER TESTED** |
| CartPage | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| BulkActionBar | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| SavedViewsPicker | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| GlobalSearch | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| SearchInput | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| SearchResults | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| KeyboardShortcuts | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| ThemeToggle | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| IllustratedEmpty | feedback | Y | 1 | no | 1 | - | **OPEN** |
| UndoManager | feedback | Y | 1 | no | 1 | - | **OPEN** |
| PresenceIndicator | feedback | Y | 1 | no | 1 | - | **OPEN** |
| OptimisticProvider | feedback | **N** | - | - | - | - | **NEVER TESTED** |
| FocusTrap | feedback | **N** | - | - | - | - | **NEVER TESTED** |
| SkipLink | navigation | Y | 1 | no | 1 | - | **OPEN** |
| FocusRing | feedback | **N** | - | - | - | - | **NEVER TESTED** |
| AutoFocus | feedback | **N** | - | - | - | - | **NEVER TESTED** |
| Wizard | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| SplitView | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| FilterBuilder | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| TourOverlay | feedback | **N** | - | - | - | - | **NEVER TESTED** |

---

## Never tested — coverage gaps

- `Popover` (feedback)
- `Tooltip` (feedback)
- `HoverCard` (feedback)
- `Drawer` (feedback)
- `Table` (data)
- `InspectorPanel` (feedback)
- `Chart` (data)
- `DataGrid` (data)
- `EditableLineGrid` (data)
- `Timeline` (data)
- `TableSortable` (data)
- `Repeat` (data)
- `Conditional` (data)
- `DataBoundary` (data)
- `Slot` (data)
- `CartPanel` (data)
- `OptimisticProvider` (feedback)
- `FocusTrap` (feedback)
- `FocusRing` (feedback)
- `AutoFocus` (feedback)
- `TourOverlay` (feedback)

## Found but NOT fixed

- `Breadcrumb` (navigation) — severity: major
- `Sparkline` (data) — severity: major, minor
- `CommandPalette` (navigation) — severity: major, minor
- `EmptyStateRich` (feedback) — severity: minor
- `Progress` (feedback) — severity: major
- `Spinner` (feedback) — severity: minor
- `Banner` (feedback) — severity: minor
- `CartBadge` (navigation) — severity: major
- `IllustratedEmpty` (feedback) — severity: major
- `UndoManager` (feedback) — severity: major
- `PresenceIndicator` (feedback) — severity: major
- `SkipLink` (navigation) — severity: major

## Requested but NOT implemented

- `Breadcrumb` (navigation)
- `Sparkline` (data)
- `CommandPalette` (navigation)
- `EmptyStateRich` (feedback)
- `Progress` (feedback)
- `Spinner` (feedback)
- `Banner` (feedback)
- `CartBadge` (navigation)
- `IllustratedEmpty` (feedback)
- `UndoManager` (feedback)
- `PresenceIndicator` (feedback)
- `SkipLink` (navigation)

## Known gaps this table cannot show

- **The four app routes** (`/items`, `/items/new`, `/items/[id]`, `/items/[id]/edit`) were audited **unauthenticated**; the app redirects to `/login`. Those findings are void and the routes need re-auditing with a session. See the CORRECTION block at the end of `qa-audit-log.md`.
- Components marked *COVERED* were audited in rounds 1–5 with their own reports; their bug/fix counts live there, not in the log this script parses.

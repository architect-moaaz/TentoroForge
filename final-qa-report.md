# Final QA report

Cross-check of `qa-audit-log.md` and the round reports in `docs/editor-audit/`, against the **registry** as the source of truth for what exists.

Coverage is asserted against the registry rather than against the log, so a component nobody tested shows up as a gap instead of silently missing.


**133 of 133 components have a row below.** Never tested: **0**. Found but not fixed: **18**.


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
| Popover | feedback | Y | 1 | no | 1 | - | **OPEN** |
| Tooltip | feedback | Y | 1 | no | 1 | - | **OPEN** |
| ContextMenu | navigation | Y | 2 | yes | 2 | yes | RESOLVED |
| HoverCard | feedback | Y | 1 | yes | 1 | yes | RESOLVED |
| Menubar | navigation | Y | 1 | yes | 1 | yes | RESOLVED |
| Drawer | feedback | Y | 1 | no | 1 | - | **OPEN** |
| Button | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Heading | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Hero | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| MetricTile | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Avatar | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Stack | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Row | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Breadcrumb | navigation | Y | 1 | yes | 1 | yes | RESOLVED |
| NavLink | navigation | Y | 1 | yes | 1 | yes | RESOLVED |
| Section | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Tabs | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| TabPanel | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Table | data | Y | 1 | yes | 1 | yes | RESOLVED |
| Badge | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| Alert | feedback | Y | 0 | - | 1 | - | CLEAN |
| EmptyState | feedback | Y | 0 | - | 1 | - | CLEAN |
| Form | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| IconButton | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| Sidebar | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Cluster | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Split | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| AppShell | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| InspectorPanel | feedback | Y | 1 | yes | 1 | yes | RESOLVED |
| TabPanelWithDeepLink | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| Chart | data | Y | 1 | no | 1 | - | **OPEN** |
| Sparkline | data | Y | 1 | yes | 1 | yes | RESOLVED |
| DataGrid | data | Y | 1 | no | 0 | - | **OPEN** |
| EditableLineGrid | data | Y | 0 | - | 1 | - | CLEAN |
| Timeline | data | Y | 1 | no | 1 | - | **OPEN** |
| TableSortable | data | Y | 1 | no | 1 | - | **OPEN** |
| ApprovalStepper | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| PersonCard | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| FilterBar | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| CommandPalette | navigation | Y | 1 | yes | 1 | yes | RESOLVED |
| ActivityFeed | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| EmptyStateRich | feedback | Y | 1 | yes | 1 | yes | RESOLVED |
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
| Repeat | data | Y | 1 | no | 1 | - | **OPEN** |
| Conditional | data | Y | 1 | no | 1 | - | **OPEN** |
| DataBoundary | data | Y | 1 | no | 1 | - | **OPEN** |
| Slot | data | Y | 1 | no | 1 | - | **OPEN** |
| Progress | feedback | Y | 1 | yes | 1 | yes | RESOLVED |
| Spinner | feedback | Y | 1 | yes | 1 | yes | RESOLVED |
| Redirect | navigation | Y | 1 | yes | 1 | yes | RESOLVED |
| Banner | feedback | Y | 1 | yes | 1 | yes | RESOLVED |
| Dialog | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| AddToCart | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| CartBadge | navigation | Y | 2 | yes | 2 | yes | RESOLVED |
| CartPanel | data | Y | 1 | yes | 1 | yes | RESOLVED |
| CartPage | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| BulkActionBar | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| SavedViewsPicker | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| GlobalSearch | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| SearchInput | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| SearchResults | display | Y | see report | see report | - | - | COVERED — display-components{,-2}.md |
| KeyboardShortcuts | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| ThemeToggle | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| IllustratedEmpty | feedback | Y | 1 | yes | 1 | yes | RESOLVED |
| UndoManager | feedback | Y | 1 | no | 1 | - | **OPEN** |
| PresenceIndicator | feedback | Y | 1 | no | 1 | - | **OPEN** |
| OptimisticProvider | feedback | Y | 1 | no | 1 | - | **OPEN** |
| FocusTrap | feedback | Y | 1 | no | 1 | - | **OPEN** |
| SkipLink | navigation | Y | 1 | yes | 1 | yes | RESOLVED |
| FocusRing | feedback | Y | 1 | no | 1 | - | **OPEN** |
| AutoFocus | feedback | Y | 1 | no | 1 | - | **OPEN** |
| Wizard | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| SplitView | layout | Y | see report | see report | - | - | COVERED — containment.md / browser-test.md |
| FilterBuilder | input | Y | see report | see report | - | - | COVERED — input-components{,-2,-3}.md |
| TourOverlay | feedback | Y | 1 | no | 1 | - | **OPEN** |

---

## Never tested — coverage gaps

None. Every registry component has a row.

## Found but NOT fixed

- `Popover` (feedback) — severity: major, minor
- `Tooltip` (feedback) — severity: major, minor
- `Drawer` (feedback) — severity: blocker, major, minor
- `Chart` (data) — severity: major, minor
- `DataGrid` (data) — severity: minor
- `Timeline` (data) — severity: unspecified
- `TableSortable` (data) — severity: major, minor
- `Repeat` (data) — severity: major
- `Conditional` (data) — severity: unspecified
- `DataBoundary` (data) — severity: major, minor
- `Slot` (data) — severity: major, minor
- `UndoManager` (feedback) — severity: major
- `PresenceIndicator` (feedback) — severity: major
- `OptimisticProvider` (feedback) — severity: minor
- `FocusTrap` (feedback) — severity: major, minor
- `FocusRing` (feedback) — severity: major
- `AutoFocus` (feedback) — severity: major, minor
- `TourOverlay` (feedback) — severity: major

## Requested but NOT implemented

- `Popover` (feedback)
- `Tooltip` (feedback)
- `Drawer` (feedback)
- `Chart` (data)
- `Timeline` (data)
- `TableSortable` (data)
- `Repeat` (data)
- `Conditional` (data)
- `DataBoundary` (data)
- `Slot` (data)
- `UndoManager` (feedback)
- `PresenceIndicator` (feedback)
- `OptimisticProvider` (feedback)
- `FocusTrap` (feedback)
- `FocusRing` (feedback)
- `AutoFocus` (feedback)
- `TourOverlay` (feedback)

## Known gaps this table cannot show

- **The four app routes** (`/items`, `/items/new`, `/items/[id]`, `/items/[id]/edit`) were audited **unauthenticated**; the app redirects to `/login`. Those findings are void and the routes need re-auditing with a session. See the CORRECTION block at the end of `qa-audit-log.md`.
- Components marked *COVERED* were audited in rounds 1–5 with their own reports; their bug/fix counts live there, not in the log this script parses.

# Editor audit — 113 components, every control

Measured, not asserted. Props, Style, Bindings and Tokens were each driven through
the **real editor UI** in Chromium against an isolated throwaway project.

**Legend** — ✅ works · ❌ broken · ⚠️ needs a state the probe could not create · ➖ not
applicable (with reason) · ⬜ untested (with reason)

A prop that changed nothing in the DOM is **not** reported as a bug on that basis alone.
It is marked ❌ only where a classifier — reading the author's description and forbidden
from seeing the code — judged it should be visible, AND a second agent reading the source
failed to refute that. 26 of 28 such claims were refuted and are absent here.


## AddToCart  `input`

**Props**

  ➖ `entity` *(string)* — config — not visible by design
  ➖ `itemId` *(string)* — config — not visible by design
  ➖ `quantity` *(number)* — config — not visible by design
  ➖ `price` *(string)* — config — not visible by design
  ➖ `label` *(string)* — config — not visible by design
  ✅ `text` *(string)* — renders
  ✅ `variant` *(enum)* — values differ
  ✅ `size` *(enum)* — values differ
  ✅ `fullWidth` *(boolean)* — values differ

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## BarcodeScanner  `input`

**Props**

  ➖ `name` *(string)* — config — not visible by design
  ✅ `label` *(string)* — renders
  ✅ `hint` *(string)* — renders
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## BulkActionBar  `input`

**Props**

  ➖ no props declared in the registry

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Button  `input`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `variant` *(enum)* — values differ
  ✅ `size` *(enum)* — values differ
  ✅ `disabled` *(boolean)* — values differ
  ➖ `onClick` *(action)* — config — not visible by design
  ➖ `clearsFilters` *(boolean)* — config — not visible by design
  ✅ `opensDialog` *(string)* — renders

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Calendar  `input`

**Props**

  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## CameraCapture  `input`

**Props**

  ✅ `label` *(string)* — renders
  ➖ `captureLabel` *(string)* — config — not visible by design
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Cascader  `input`

**Props**

  ❌ `placeholder` *(string)* — declared but never read
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Checkbox  `input`

**Props**

  ✅ `label` *(string)* — renders
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## ColorPicker  `input`

**Props**

  ✅ `label` *(string)* — renders
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Combobox  `input`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `placeholder` *(string)* — renders
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## DatePicker  `input`

**Props**

  ✅ `name` *(string)* — renders
  ✅ `label` *(string)* — renders
  ➖ `bind` *(binding)* — binding — see Bindings
  ✅ `min` *(string)* — renders
  ✅ `max` *(string)* — renders

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## DateRangePicker  `input`

**Props**

  ➖ `name` *(string)* — config — not visible by design
  ✅ `label` *(string)* — renders
  ➖ `startDate` *(string)* — config — not visible by design
  ➖ `endDate` *(string)* — config — not visible by design
  ⚠️ `presets` *(action)* — needs: Picker popover/dropdown open — preset shortcut labels live
  ⚠️ `minDate` *(string)* — needs: Calendar popover open, showing day cells that can be marke
  ⚠️ `maxDate` *(string)* — needs: Calendar popover open, showing day cells that can be marke

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## FileUpload  `input`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `accept` *(string)* — renders
  ✅ `multiple` *(boolean)* — values differ
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## FilterBar  `input`

**Props**

  ➖ `chips` *(action)* — config — not visible by design
  ⚠️ `savedViews` *(action)* — needs: Saved-views menu/dropdown opened — the preset labels are l
  ✅ `showSearch` *(boolean)* — values differ

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## FilterBuilder  `input`

**Props**

  ⚠️ `fields` *(string)* — needs: At least one condition/rule row present (or the field sele
  ➖ `paramKey` *(string)* — config — not visible by design
  ⚠️ `combinator` *(enum)* — needs: Builder holding at least two rules/conditions (or at least
  ✅ `emptyLabel` *(string)* — renders
  ➖ `onApplyWorkflow` *(string)* — config — not visible by design

**Style** — ⚠️ partial — applied: Background,Padding,Radius,Shadow · missing: Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Form  `input`

**Props**

  ➖ `workflow` *(string)* — config — not visible by design
  ➖ `fields` *(action)* — config — not visible by design
  ✅ `submitLabel` *(string)* — renders
  ⚠️ `defaultValues` *(action)* — needs: Form must have fields defined whose names match the record

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## GlobalSearch  `input`

**Props**

  ✅ `placeholder` *(string)* — renders
  ➖ `workflow` *(string)* — config — not visible by design
  ➖ `debounceMs` *(number)* — config — not visible by design

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## IconButton  `input`

**Props**

  ✅ `icon` *(string)* — renders
  ✅ `aria-label` *(string)* — renders
  ✅ `variant` *(enum)* — values differ
  ✅ `size` *(enum)* — values differ
  ✅ `disabled` *(boolean)* — values differ
  ➖ `workflow` *(string)* — config — not visible by design

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Input  `input`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `placeholder` *(string)* — renders
  ✅ `type` *(enum)* — values differ
  ➖ `binding` *(binding)* — binding — see Bindings
  ⚠️ `validation` *(string)* — needs: Field must be in an invalid/touched state — a value entere

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## InputOTP  `input`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `length` *(number)* — values differ
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## KeyboardShortcuts  `input`

**Props**

  ➖ no props declared in the registry

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## KeyValueInput  `input`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `description` *(string)* — renders
  ➖ `valueType` *(enum)* — config — not visible by design
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## MaskedInput  `input`

**Props**

  ✅ `label` *(string)* — renders
  ⚠️ `mask` *(string)* — needs: Input must hold a value (user-typed or seeded text); with 
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## MoneyInput  `input`

**Props**

  ✅ `label` *(string)* — renders
  ➖ `currency` *(string)* — config — not visible by design
  ✅ `currencyEditable` *(boolean)* — values differ
  ✅ `min` *(number)* — values differ
  ✅ `step` *(number)* — values differ
  ✅ `placeholder` *(string)* — renders
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## MultiSelect  `input`

**Props**

  ➖ `name` *(string)* — config — not visible by design
  ✅ `label` *(string)* — renders
  ✅ `placeholder` *(string)* — renders
  ⚠️ `options` *(action)* — needs: Dropdown must be open; option labels live inside the popup
  ⚠️ `selected` *(action)* — needs: Matching `options` must be supplied so the selected values
  ⚠️ `showSearch` *(boolean)* — needs: Dropdown must be open — the description says the search fi

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ✅ `options` RESOLVED

## NumberInput  `input`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `min` *(number)* — values differ
  ✅ `max` *(number)* — values differ
  ✅ `step` *(number)* — values differ
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## RadioGroup  `input`

**Props**

  ✅ `label` *(string)* — renders
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Rating  `input`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `max` *(number)* — values differ
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## RichTextEditor  `input`

**Props**

  ✅ `label` *(string)* — renders
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## SavedViewsPicker  `input`

**Props**

  ➖ `views` *(string)* — config — not visible by design
  ⚠️ `activeViewId` *(string)* — needs: `views` must be populated with entries whose ids match — w
  ➖ `onSelectWorkflow` *(string)* — config — not visible by design

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Scanner  `input`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `deviceType` *(enum)* — values differ
  ✅ `status` *(enum)* — values differ
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## SearchInput  `input`

**Props**

  ✅ `placeholder` *(string)* — renders
  ➖ `endpoint` *(string)* — config — not visible by design
  ➖ `debounceMs` *(number)* — config — not visible by design
  ➖ `minChars` *(number)* — config — not visible by design

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## SegmentedControl  `input`

**Props**

  ✅ `label` *(string)* — renders
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Select  `input`

**Props**

  ✅ `label` *(string)* — renders
  ➖ `options` *(string)* — config — not visible by design
  ➖ `binding` *(binding)* — binding — see Bindings
  ⚠️ `multiple` *(boolean)* — needs: Dropdown/list open, or at least one option selected — a cl

**Style** — ✅ all 11 keys applied

**Bindings** — ✅ `options` RESOLVED

## Slider  `input`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `min` *(number)* — values differ
  ✅ `max` *(number)* — values differ
  ✅ `range` *(boolean)* — values differ
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Switch  `input`

**Props**

  ✅ `label` *(string)* — renders
  ➖ `checked` *(boolean)* — config — not visible by design
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Textarea  `input`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `placeholder` *(string)* — renders
  ➖ `rows` *(number)* — config — not visible by design
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ✅ `rows` RESOLVED

## ThemeToggle  `input`

**Props**

  ⚠️ `lightLabel` *(string)* — needs: Component must currently be in dark theme — the descriptio
  ✅ `darkLabel` *(string)* — renders
  ➖ `storageKey` *(string)* — config — not visible by design

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## TimePicker  `input`

**Props**

  ✅ `label` *(string)* — renders
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Transfer  `input`

**Props**

  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Wizard  `input`

**Props**

  ➖ `steps` *(string)* — config — not visible by design
  ➖ `onComplete` *(string)* — config — not visible by design
  ➖ `successRoute` *(string)* — config — not visible by design
  ✅ `title` *(string)* — renders
  ✅ `skipReview` *(boolean)* — values differ
  ⚠️ `submitLabel` *(string)* — needs: Wizard advanced to its final step, where the submit button

**Style** — ⚠️ partial — applied: Background,Padding,Radius,Shadow · missing: Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## ActivityFeed  `display`

**Props**

  ➖ `entries` *(action)* — config — not visible by design
  ✅ `title` *(string)* — renders
  ⚠️ `showFilter` *(boolean)* — needs: Feed holding entries that carry categories, so filter chip
  ✅ `maxHeight` *(number)* — values differ

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ✅ `entries` RESOLVED

## ApprovalStepper  `display`

**Props**

  ➖ `steps` *(action)* — config — not visible by design
  ✅ `orientation` *(enum)* — values differ
  ➖ `onStepClick` *(string)* — config — not visible by design

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Avatar  `display`

**Props**

  ✅ `name` *(string)* — renders
  ✅ `photoUrl` *(string)* — renders
  ⚠️ `src` *(string)* — needs: photoUrl unset/empty so the legacy src fallback path is ta
  ✅ `size` *(enum)* — values differ
  ✅ `status` *(enum)* — values differ

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Badge  `display`

**Props**

  ✅ `content` *(string)* — renders
  ✅ `variant` *(enum)* — values differ

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Carousel  `display`

**Props**

  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## CodeBlock  `display`

**Props**

  ✅ `code` *(string)* — renders
  ✅ `language` *(string)* — renders
  ✅ `showCopy` *(boolean)* — values differ

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## DescriptionList  `display`

**Props**

  ➖ no props declared in the registry

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Dialog  `display`

**Props**

  ➖ no props declared in the registry

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## FadeIn  `display`

**Props**

  ✅ `delay` *(number)* — values differ
  ✅ `duration` *(number)* — values differ

**Style** — ⚠️ partial — applied: Background,Padding,Radius,Shadow · missing: Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## FeatureCard  `display`

**Props**

  ✅ `title` *(string)* — renders
  ✅ `description` *(string)* — renders
  ✅ `icon` *(string)* — renders
  ⚠️ `cta` *(action)* — needs: cta set to a complete {label, href} object; the card rende
  ✅ `layout` *(enum)* — values differ

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Gauge  `display`

**Props**

  ✅ `value` *(number)* — values differ
  ✅ `min` *(number)* — values differ
  ⚠️ `max` *(number)* — needs: A non-zero value bound to the gauge (and/or a scale with m
  ✅ `label` *(string)* — renders
  ✅ `unit` *(string)* — renders
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Heading  `display`

**Props**

  ✅ `content` *(string)* — renders
  ✅ `level` *(enum)* — values differ
  ✅ `weight` *(enum)* — values differ

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Heatmap  `display`

**Props**

  ➖ `color` *(string)* — config — not visible by design
  ⚠️ `showValues` *(boolean)* — needs: Heatmap must be holding a non-empty data matrix so cells a
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ⚠️ partial — applied: Background,Padding,Radius,Shadow · missing: Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Kanban  `display`

**Props**

  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ⚠️ partial — applied: Background,Padding,Radius,Shadow · missing: Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## KeyValueList  `display`

**Props**

  ⚠️ `items` *(action)* — needs: The items binding must resolve to a non-empty array of { l

**Style** — ✅ all 11 keys applied

**Bindings** — ✅ `items` RESOLVED

## Lightbox  `display`

**Props**

  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## List  `display`

**Props**

  ✅ `divided` *(boolean)* — values differ
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## MetricTile  `display`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `value` *(string)* — renders
  ➖ `format` *(enum)* — config — not visible by design
  ✅ `importance` *(enum)* — values differ
  ➖ `icon` *(string)* — config — not visible by design
  ⚠️ `delta` *(action)* — needs: A resolvable delta object { value, direction } must actual
  ⚠️ `trend` *(action)* — needs: A resolvable array of numbers must be supplied/bound so th

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## MoneyDisplay  `display`

**Props**

  ➖ `currency` *(string)* — config — not visible by design
  ➖ `locale` *(string)* — config — not visible by design
  ⚠️ `compact` *(boolean)* — needs: The displayed amount must be large enough for compact nota
  ➖ `showSymbol` *(boolean)* — config — not visible by design
  ➖ `align` *(string)* — config — not visible by design
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## PersonCard  `display`

**Props**

  ✅ `name` *(string)* — renders
  ✅ `role` *(string)* — renders
  ➖ `department` *(string)* — config — not visible by design
  ✅ `avatarUrl` *(string)* — renders
  ⚠️ `avatarInitials` *(string)* — needs: avatarUrl empty/unset so the avatar falls back to initials
  ➖ `email` *(string)* — config — not visible by design
  ✅ `status` *(enum)* — values differ
  ✅ `layout` *(enum)* — values differ

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## QRCode  `display`

**Props**

  ✅ `value` *(string)* — values differ
  ✅ `size` *(number)* — values differ
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## ResourceTimeline  `display`

**Props**

  ➖ `resources` *(binding)* — binding — see Bindings
  ➖ `items` *(binding)* — binding — see Bindings
  ➖ `itemResourceField` *(string)* — config — not visible by design
  ➖ `startField` *(string)* — config — not visible by design
  ➖ `endField` *(string)* — config — not visible by design
  ➖ `titleField` *(string)* — config — not visible by design
  ➖ `statusField` *(string)* — config — not visible by design
  ➖ `resourceGroupField` *(string)* — config — not visible by design
  ➖ `days` *(number)* — config — not visible by design
  ➖ `itemHref` *(string)* — config — not visible by design

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ✅ `items` RESOLVED

## Schematic  `display`

**Props**

  ✅ `width` *(number)* — values differ
  ✅ `height` *(number)* — values differ
  ⚠️ `showLabels` *(boolean)* — needs: Component must be holding marker/region data; with no mark
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## SearchResults  `display`

**Props**

  ➖ `hrefPattern` *(string)* — config — not visible by design
  ⚠️ `skeletonRows` *(number)* — needs: Component must be in the loading state (query in flight, r
  ✅ `pristineText` *(string)* — renders
  ⚠️ `emptyText` *(string)* — needs: Component must be in the empty state — a query that has ru

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## SplitArc  `display`

**Props**

  ➖ `segments` *(binding)* — binding — see Bindings
  ⚠️ `total` *(number)* — needs: Component must hold segment values whose sum differs from 
  ✅ `title` *(string)* — renders
  ✅ `size` *(number)* — values differ
  ✅ `showLegend` *(boolean)* — values differ
  ✅ `showEndLabels` *(boolean)* — values differ
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Stagger  `display`

**Props**

  ✅ `delay` *(number)* — values differ
  ✅ `interval` *(number)* — values differ

**Style** — ⚠️ partial — applied: Background,Padding,Radius,Shadow · missing: Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Stat  `display`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `value` *(string)* — renders
  ✅ `delta` *(string)* — renders
  ✅ `trend` *(enum)* — values differ
  ✅ `caption` *(string)* — renders

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Stepper  `display`

**Props**

  ✅ `orientation` *(enum)* — values differ
  ➖ `activeStep` *(number)* — config — not visible by design
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Tag  `display`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `variant` *(enum)* — values differ
  ✅ `removable` *(boolean)* — values differ

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Tree  `display`

**Props**

  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## ValidationChecklist  `display`

**Props**

  ✅ `orientation` *(enum)* — values differ
  ➖ `binding` *(binding)* — binding — see Bindings

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## CartPanel  `data`

**Props**

  ✅ `title` *(string)* — renders
  ✅ `emptyState` *(string)* — renders
  ⚠️ `currency` *(string)* — needs: Panel must be holding at least one priced line item or a r
  ➖ `checkoutLabel` *(string)* — config — not visible by design
  ➖ `onCheckoutNavigate` *(string)* — config — not visible by design

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Chart  `data`

**Props**

  ✅ `chartType` *(enum)* — values differ
  ⚠️ `data` *(action)* — needs: The chart must have series (and xKey) configured that matc
  ➖ `xKey` *(string)* — config — not visible by design
  ⚠️ `series` *(action)* — needs: The chart must be holding resolved data rows whose keys ma
  ✅ `height` *(number)* — values differ
  ➖ `showGrid` *(boolean)* — config — not visible by design
  ✅ `showLegend` *(boolean)* — values differ
  ✅ `showTooltip` *(boolean)* — values differ

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ✅ `data` RESOLVED

## Conditional  `data`

**Props**

  ➖ no props declared in the registry

**Style** — ⬜ HARNESS-BLOCKED: drop refused

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## DataBoundary  `data`

**Props**

  ➖ no props declared in the registry

**Style** — ⬜ HARNESS-BLOCKED: drop refused

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## DataGrid  `data`

**Props**

  ⚠️ `columns` *(action)* — needs: The actionPicker binding must resolve to a real array of c
  ⚠️ `rows` *(action)* — needs: Columns must be defined with keys matching the row objects
  ➖ `rowKey` *(string)* — config — not visible by design
  ⚠️ `virtualise` *(boolean)* — needs: The grid must hold enough rows to exceed the viewport (the
  ⚠️ `selectable` *(boolean)* — needs: The grid must have resolved columns/rows so a checkbox col
  ⚠️ `expandable` *(boolean)* — needs: Grid must be holding at least one row; the expander afford
  ➖ `rowActions` *(action)* — config — not visible by design

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ✅ `rows` RESOLVED

## EditableLineGrid  `data`

**Props**

  ⚠️ `columns` *(action)* — needs: The picker must be bound to a real array of column definit
  ⚠️ `rows` *(action)* — needs: The grid must be bound to real row data keyed by column.ke
  ➖ `rowKey` *(string)* — config — not visible by design
  ✅ `showLookup` *(boolean)* — values differ
  ✅ `lookupPlaceholder` *(string)* — renders
  ✅ `removable` *(boolean)* — values differ
  ⚠️ `totals` *(action)* — needs: A footer rollup object must actually resolve (and the grid
  ✅ `emptyMessage` *(string)* — renders

**Style** — ✅ all 11 keys applied

**Bindings** — ✅ `rows` RESOLVED

## Repeat  `data`

**Props**

  ➖ no props declared in the registry

**Style** — ⬜ HARNESS-BLOCKED: drop refused

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Slot  `data`

**Props**

  ➖ no props declared in the registry

**Style** — ⬜ HARNESS-BLOCKED: drop refused

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Sparkline  `data`

**Props**

  ➖ no props declared in the registry

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ✅ `data` RESOLVED

## Table  `data`

**Props**

  ⚠️ `columns` *(action)* — needs: Bound to a valid array of { key, label, width? } objects; 
  ✅ `caption` *(string)* — renders

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## TableSortable  `data`

**Props**

  ⚠️ `columns` *(action)* — needs: Bound to a valid array of { key, label, width? } objects; 
  ✅ `caption` *(string)* — renders
  ➖ `onSort` *(action)* — config — not visible by design

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Timeline  `data`

**Props**

  ⚠️ `entries` *(action)* — needs: Timeline must be holding real entry data ({ timestamp, tit
  ➖ `orientation` *(enum)* — config — not visible by design

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ✅ `entries` RESOLVED

## Alert  `feedback`

**Props**

  ✅ `message` *(string)* — renders
  ✅ `variant` *(enum)* — values differ
  ✅ `title` *(string)* — renders

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## AutoFocus  `feedback`

**Props**

  ➖ no props declared in the registry

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Banner  `feedback`

**Props**

  ✅ `variant` *(enum)* — values differ
  ✅ `title` *(string)* — renders
  ✅ `message` *(string)* — renders

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## EmptyState  `feedback`

**Props**

  ✅ `message` *(string)* — renders
  ✅ `icon` *(string)* — renders
  ➖ `action` *(action)* — config — not visible by design

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## EmptyStateRich  `feedback`

**Props**

  ✅ `heading` *(string)* — renders
  ✅ `body` *(string)* — renders
  ✅ `icon` *(string)* — renders
  ➖ `illustration` *(action)* — config — not visible by design
  ➖ `primaryCta` *(action)* — config — not visible by design
  ➖ `sampleDataLink` *(action)* — config — not visible by design

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## FocusRing  `feedback`

**Props**

  ➖ no props declared in the registry

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## FocusTrap  `feedback`

**Props**

  ✅ `active` *(boolean)* — values differ
  ➖ `autoFocus` *(boolean)* — config — not visible by design
  ➖ `restoreFocus` *(boolean)* — config — not visible by design

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## HoverCard  `feedback`

**Props**

  ✅ `label` *(string)* — renders
  ⚠️ `title` *(string)* — needs: Card open — trigger hovered or focused so the hover panel 
  ⚠️ `content` *(string)* — needs: Card open — trigger hovered or focused so the hover panel 

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## IllustratedEmpty  `feedback`

**Props**

  ✅ `kind` *(enum)* — values differ
  ✅ `title` *(string)* — renders
  ✅ `message` *(string)* — renders
  ⚠️ `action` *(string)* — unclear from the description

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## LoadingState  `feedback`

**Props**

  ✅ `label` *(string)* — renders

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## OptimisticProvider  `feedback`

**Props**

  ➖ no props declared in the registry

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Popover  `feedback`

**Props**

  ✅ `trigger` *(string)* — renders
  ⚠️ `title` *(string)* — needs: Popover open — the panel (and its title) is only rendered/
  ⚠️ `content` *(string)* — needs: Popover open — the panel body is only rendered/visible onc

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## PresenceIndicator  `feedback`

**Props**

  ➖ no props declared in the registry

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Progress  `feedback`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `value` *(number)* — values differ
  ✅ `variant` *(enum)* — values differ

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Skeleton  `feedback`

**Props**

  ✅ `variant` *(enum)* — values differ
  ✅ `lines` *(number)* — values differ

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Spinner  `feedback`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `size` *(enum)* — values differ

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Tooltip  `feedback`

**Props**

  ✅ `label` *(string)* — renders
  ⚠️ `content` *(string)* — needs: Tooltip shown — trigger hovered or focused so the hint bub

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## TourOverlay  `feedback`

**Props**

  ➖ no props declared in the registry

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## UndoManager  `feedback`

**Props**

  ➖ no props declared in the registry

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Breadcrumb  `navigation`

**Props**

  ⚠️ `items` *(action)* — unclear from the description
  ⚠️ `separator` *(string)* — needs: At least two breadcrumb items present, so a separator is r

**Style** — ✅ all 11 keys applied

**Bindings** — ✅ `items` RESOLVED

## CartBadge  `navigation`

**Props**

  ➖ no props declared in the registry

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## CommandPalette  `navigation`

**Props**

  ⚠️ `items` *(action)* — needs: Command palette open, so the command list is rendered.
  ⚠️ `placeholder` *(string)* — needs: Command palette open, so the search input (and its placeho
  ✅ `triggerKey` *(string)* — values differ

**Style** — ❌ none applied — missing: Background,Padding,Radius,Shadow,Motion

**Bindings** — ✅ `items` RESOLVED

## ContextMenu  `navigation`

**Props**

  ✅ `label` *(string)* — renders

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## DropdownMenu  `navigation`

**Props**

  ✅ `trigger` *(string)* — renders

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Link  `navigation`

**Props**

  ✅ `label` *(string)* — renders
  ✅ `navigate` *(string)* — renders
  ➖ `workflow` *(string)* — config — not visible by design

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## NavLink  `navigation`

**Props**

  ✅ `label` *(string)* — renders
  ➖ `target` *(string)* — config — not visible by design
  ❌ `icon` *(string)* — declared but never read

**Style** — ✅ all 11 keys applied

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## Redirect  `navigation`

**Props**

  ➖ no props declared in the registry

**Style** — ⬜ HARNESS-BLOCKED: drop refused

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

## SkipLink  `navigation`

**Props**

  ➖ no props declared in the registry

**Style** — ⬜ HARNESS-BLOCKED: drop refused

**Bindings** — ➖ no data-source prop (`data/rows/options/items/entries/records`)

---

## Totals across all components

| | |
|---|---|
| ✅ props working | 172 |
| ❌ props broken | 2 |
| ⚠️ props needing an uncreated state | 54 |
| ➖ props not applicable | 116 |
| ⬜ props untested | 0 |

---

# Fix log — dead controls, closed

A **dead control** is a prop the registry declares, the editor renders a control for,
and nothing consumes: the user types, it saves, it persists to disk, and no pixel ever
changes. There is no error to notice.

The static conformance check (`tests/matrix/contract-conformance.mjs`) found this class
in under a second across all 133 components — including the 20 layout ones the browser
sweep structurally could not reach.

## The second layer, found while fixing the first

A prop passes through `registry.validateProps()` (`packages/renderer/src/runtime/dispatch.tsx:269`)
before any component sees it, and **zod drops anything the node schema does not declare —
silently, on a *successful* parse**.

That makes a component-only fix inert, and it is invisible to a unit test that renders the
component directly. Three consequences, all measured:

| | |
|---|---|
| `NavLink.target`, `NavLink.icon`, `Divider.thickness` | fixed earlier in the component, **still dead in the product** — the value never arrived |
| `Switch.checked` | a **new** defect. The component reads it, so a source scan says it is fine; the schema was dropping it |
| `Select.multiple`, `Input.validation` | needed both layers, not just the component |

`packages/library/tests/registry-prop-passthrough.test.ts` now locks this: every registry
prop must survive `validateProps`, with `binding` the one declared exception.

## Closed in this pass

| Prop | Layer | What it does now |
|---|---|---|
| `Select.multiple` | schema + component | native multi-select; selection joins/splits on `,`, so the `(value: string) => void` contract is unchanged |
| `Input.validation` | schema + component | parses `required\|email\|min:N\|max:N\|pattern:…` into the `validators` shape the component already honours — one enforcement path, not two |
| `Cascader.placeholder` | component | shown when there is nothing to cascade through; with options present the columns are the UI |
| `DataGrid.expandable` | component | per-row disclosure; the panel lists the fields the columns do not already show |
| `ActivityFeed.showFilter` | component | category chips derived from the entries present, so a filter can never empty the feed |
| `ApprovalStepper.onStepClick` | component | dispatches through `WorkflowDispatcherContext` — the same path `Button.workflow` uses |
| `Switch.checked` | schema | reaches the component at all |
| `NavLink.target` / `NavLink.icon` | schema | the earlier component fix is now reachable |
| `Divider.thickness` | schema | as above |

Every one is off by default: with the prop unset, the rendered DOM is byte-for-byte what
it was. No page already on disk changes.

## Three reported dead props that were not

`CartPage.currency`, `CartPage.checkoutLabel`, `CartPage.onCheckoutNavigate` all work.
`CartPage` renders `<CartPanel {...rest} />` and `CartPanel` destructures and uses all
three — so the names never appear in `CartPage`'s own source and a name search called them
dead. The checker gained a `forwardsRest` guard and now reports such props as
NEEDS-MANUAL-CHECK rather than as defects.

## What is left

**39 dead props, and every one of them is `binding`.** That is a single architectural
hole, not 39 defects: the Props panel's bind toggle writes `{$binding: "expr"}`, and
`$binding` appears nowhere in `renderer`, `engine` or `library` — the only prop transform
is `interpolateDeep`, which rewrites *strings* containing `{{`. The object form passes
through untouched. Implementing it is a feature build with a new renderer data path.

No non-binding dead prop remains.

## Verification

- Full suites against the measured pristine baseline: library **22 failed** (unchanged)
  with 978 passing, up from 953 — the 25 new tests all pass. Renderer **31 failed**
  (unchanged). Schema's 4 failures reproduce with the change reverted, so they pre-date it.
- `npm run build:engine-stack` clean.
- The conformance check re-run: 61 dead props → 39, all `binding`.

import type { Registry, RegistryEntry } from "./types";

// ---------------------------------------------------------------------------
// §13.1 Layout
// ---------------------------------------------------------------------------

export const containerEntry: RegistryEntry = {
  name: "Container",
  category: "layout",
  icon: "Square",
  description: "Flex layout container.",
  slots: { type: "list" },
  props: {
    direction: {
      type: "enum",
      options: ["vertical", "horizontal"],
      default: "vertical",
      control: "select",
      group: "style",
      description: "Primary flex axis.",
    },
    gap: {
      type: "enum",
      options: ["none", "xs", "sm", "md", "lg", "xl"],
      default: "md",
      control: "select",
      group: "style",
      description: "Gap between children.",
    },
    padding: {
      type: "enum",
      options: ["none", "xs", "sm", "md", "lg", "xl"],
      default: "md",
      control: "select",
      group: "style",
      description: "Inner padding.",
    },
    align: {
      type: "enum",
      options: ["start", "center", "end", "stretch"],
      default: "start",
      control: "select",
      group: "style",
      description: "Cross-axis alignment.",
    },
    justify: {
      type: "enum",
      options: ["start", "center", "end", "between", "around", "evenly"],
      default: "start",
      control: "select",
      group: "style",
      description: "Main-axis justification.",
    },
    wrap: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "style",
      description: "Allow children to wrap onto multiple lines.",
    },
    maxWidth: {
      type: "enum",
      options: ["sm", "md", "lg", "xl", "2xl", "full"],
      default: "lg",
      control: "select",
      group: "style",
      description: "Constrain inner content width.",
    },
  },
};

export const gridEntry: RegistryEntry = {
  name: "Grid",
  category: "layout",
  icon: "LayoutGrid",
  description: "Grid layout container.",
  slots: { type: "list" },
  props: {
    columns: {
      type: "number",
      default: 2,
      control: "number",
      group: "style",
      description: "Number of grid columns.",
    },
    rows: {
      // Default 0, NOT 2, and the difference matters. 0 means "auto": rows are
      // implicit and children just wrap, which is what every schema written
      // before this prop existed does. Defaulting to 2 would make the properties
      // panel display "2" for those legacy grids and the first edit to any other
      // prop would then reconcile their free-form children into a 2×N cell grid
      // they never asked for. A grid dropped from the palette sets rows: 2
      // explicitly instead — see buildDroppedNode in frontend useDrop.ts.
      type: "number",
      default: 0,
      control: "number",
      group: "style",
      description:
        "Fixed row count. 0 = auto (rows grow to fit). Above 0 the grid holds exactly rows x columns cells you can drop into.",
    },
    // rowGap / columnGap / padding / align USED TO BE HERE and are gone.
    //
    // They were dead in both directions at once. `renderer/src/nodes/layout/
    // Grid.tsx` reads exactly `columns`, `gap`, `rows`, `equalRows`, `equalCols`,
    // `className` and `style` — the four had no reader, so setting them moved
    // nothing on the canvas (the same write-with-no-reader bug Container.tsx's
    // header describes, still standing on Grid). And `V2GridNode.props` is
    // `.strict()` over { columns, rows, gap, equalRows, equalCols }, so seeding
    // them ALSO made every palette-dropped Grid produce a page PageV2 rejects —
    // which is what makes the scaffold log "schema validation failed … rendering
    // raw" and drop the whole page out of validated rendering.
    //
    // `gap` below is the live control and covers the common case. Independent
    // row/column gaps, grid padding and block-axis alignment need the RENDERER
    // to implement them and V2GridNode to declare them before the editor can
    // honestly offer them again — routed, not faked here.
    gap: {
      type: "enum",
      options: ["none", "xs", "sm", "md", "lg", "xl"],
      default: "md",
      control: "select",
      group: "style",
      description: "Combined row + column gap (shorthand).",
    },
  },
};

/**
 * GridCell — one box of a fixed R x C Grid. Never dragged from the palette
 * (hence `hidden`); the editor materialises exactly rows x columns of them when
 * the user sets a row count, and the drop handler routes drops into them.
 *
 * It is a registry entry rather than an editor-only fiction because
 * validateForCommit (packages/patches/src/validate.ts) enforces registry-type
 * closure and SILENTLY rejects the whole page when a node's type is unknown —
 * a cell that only existed in the editor's head would make every grid edit
 * vanish on commit with no error surfaced.
 *
 * `rejects: ["GridCell"]` keeps cells from nesting: a cell inside a cell has no
 * grid track of its own, so it would look identical to its parent while making
 * the row-major addressing ambiguous.
 */
export const gridCellEntry: RegistryEntry = {
  name: "GridCell",
  category: "layout",
  icon: "Square",
  description: "One cell of a fixed grid. Drop anything inside it.",
  hidden: true,
  slots: { type: "list", rejects: ["GridCell"] },
  props: {},
};

export const cardEntry: RegistryEntry = {
  name: "Card",
  category: "layout",
  icon: "CreditCard",
  description: "Surface container with optional title, footer, and shadow elevation.",
  slots: { type: "list" },
  props: {
    title: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Optional card heading.",
    },
    footer: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Optional card footer text.",
    },
    elevation: {
      type: "enum",
      options: ["none", "sm", "md", "lg"],
      default: "sm",
      control: "select",
      group: "style",
      description: "Drop shadow size.",
    },
    density: {
      type: "enum",
      options: ["tight", "regular", "loose"],
      default: "regular",
      control: "select",
      group: "style",
      description: "Internal padding density.",
    },
  },
};

export const dividerEntry: RegistryEntry = {
  name: "Divider",
  category: "layout",
  icon: "Minus",
  description: "Visual separator.",
  slots: { type: "leaf" },
  props: {
    orientation: {
      type: "enum",
      options: ["horizontal", "vertical"],
      default: "horizontal",
      control: "select",
      group: "style",
      description: "Direction of the divider line.",
    },
    thickness: {
      type: "enum",
      options: ["thin", "medium", "thick"],
      default: "thin",
      control: "select",
      group: "style",
      description: "Stroke thickness.",
    },
  },
};

export const spacerEntry: RegistryEntry = {
  name: "Spacer",
  category: "layout",
  icon: "ArrowUpDown",
  description: "Empty space.",
  slots: { type: "leaf" },
  props: {
    size: {
      type: "enum",
      options: ["xs", "sm", "md", "lg", "xl", "2xl"],
      default: "md",
      control: "select",
      group: "style",
      description: "Amount of empty space to insert.",
    },
  },
};

// ---------------------------------------------------------------------------
// §13.2 Input
// ---------------------------------------------------------------------------

export const inputEntry: RegistryEntry = {
  name: "Input",
  category: "input",
  icon: "TextCursor",
  description: "Single-line text input.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label: {
      type: "string",
      default: "Label",
      control: "text",
      group: "content",
      description: "Visible field label.",
    },
    placeholder: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Placeholder text.",
    },
    type: {
      type: "enum",
      options: ["text", "email", "password", "number", "tel", "url"],
      default: "text",
      control: "select",
      group: "behavior",
      description: "HTML input type.",
    },
    bind: {
      type: "binding",
      default: null,
      control: "binding",
      group: "data",
      description: "Data path to bind the input value.",
    },
    validators: {
      type: "action",
      // `validation` (a free-text "rule expression") matched nothing: the schema
      // field is `validators`, and it is an OBJECT — `{required, min, max,
      // pattern, message}` — so a string could never have satisfied it. The old
      // control wrote a prop no consumer read, on every Input.
      default: null,
      control: "json",
      group: "behavior",
      description: "Validation rules: { required, min, max, pattern, message }.",
    },
  },
};

export const textareaEntry: RegistryEntry = {
  name: "Textarea",
  category: "input",
  icon: "AlignLeft",
  description: "Multi-line text input.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label: {
      type: "string",
      default: "Label",
      control: "text",
      group: "content",
      description: "Visible field label.",
    },
    placeholder: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Placeholder text.",
    },
    rows: {
      type: "number",
      default: 4,
      control: "number",
      group: "style",
      description: "Visible row height.",
    },
    bind: {
      type: "binding",
      default: null,
      control: "binding",
      group: "data",
      description: "Data path to bind the textarea value.",
    },
  },
};

export const selectEntry: RegistryEntry = {
  name: "Select",
  category: "input",
  icon: "ChevronDown",
  description: "Dropdown.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label: {
      type: "string",
      default: "Label",
      control: "text",
      group: "content",
      description: "Visible field label.",
    },
    options: {
      type: "array",
      // A NON-EMPTY ARRAY, NOT A COMMA-SEPARATED STRING. The contract is
      // `z.array(SelectOption).min(1)`, but this shipped as a `textarea` storing
      // `""` — so every Select dropped from the palette was schema-invalid AND
      // rendered with zero <option> elements. Verified live: `select.options.length === 0`.
      default: [{ value: "one", label: "Option one" }, { value: "two", label: "Option two" }],
      control: "json",
      group: "content",
      description: "Options as [{ value, label }]. At least one is required.",
    },
    bind: {
      type: "binding",
      default: null,
      control: "binding",
      group: "data",
      description: "Data path to bind the selected value.",
    },
  },
};

export const checkboxEntry: RegistryEntry = {
  name: "Checkbox",
  category: "input",
  icon: "CheckSquare",
  description: "Boolean checkbox.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label: {
      type: "string",
      default: "Check me",
      control: "text",
      group: "content",
      description: "Checkbox label text.",
    },
    bind: {
      type: "binding",
      default: null,
      control: "binding",
      group: "data",
      description: "Data path to bind the checked state.",
    },
  },
};

export const switchEntry: RegistryEntry = {
  name: "Switch",
  category: "input",
  icon: "ToggleLeft",
  description: "Boolean on/off toggle switch.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:   { type: "string",  default: "Enabled", control: "text",    group: "content",  description: "Switch label." },
    bind: { type: "binding", default: null,      control: "binding", group: "data",     description: "Data path to bind the on/off state." },
  },
};

export const numberInputEntry: RegistryEntry = {
  name: "NumberInput",
  category: "input",
  icon: "Hash",
  description: "Numeric input with +/- steppers.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:   { type: "string",  default: "Quantity", control: "text",    group: "content",  description: "Field label." },
    min:     { type: "number",  default: 0,          control: "number",  group: "behavior", description: "Minimum value." },
    max:     { type: "number",  default: 100,        control: "number",  group: "behavior", description: "Maximum value." },
    step:    { type: "number",  default: 1,          control: "number",  group: "behavior", description: "Increment step." },
    bind: { type: "binding", default: null,       control: "binding", group: "data",     description: "Data path to bind the value." },
  },
};

// ── Money — first-class banking money field (Slice 2 of the banking-app work) ─
// Amount is a decimal STRING (never a JS number → no lost cents); the currency
// rides alongside as a 3-letter ISO code, mirroring the DB sibling `<field>_currency`
// column the schema builder emits for a `type: "money"` column.
export const moneyInputEntry: RegistryEntry = {
  name: "MoneyInput",
  category: "input",
  icon: "DollarSign",
  description: "Decimal amount + currency chip (banking-grade money field).",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:            { type: "string",  default: "Amount", control: "text",    group: "content",  description: "Field label." },
    currency:         { type: "string",  default: "USD",    control: "text",    group: "content",  description: "3-letter ISO currency code (locked unless currencyEditable)." },
    currencyEditable: { type: "boolean", default: false,    control: "toggle",  group: "behavior", description: "Let the user pick the currency from a dropdown." },
    // The list that dropdown offers, and it had no control at all — so turning
    // CURRENCYEDITABLE on gave the user a picker they could not populate.
    // NO default: `Money.tsx` falls back to DEFAULT_CURRENCIES (nine codes)
    // whenever this is absent or empty, so any seed here would silently NARROW
    // the picker on every dropped field — a seed read as a restriction rather
    // than as "unset".
    currencies:       { type: "array",                       control: "json",    group: "content",  description: "Currency codes the picker offers, e.g. [\"USD\",\"EUR\"]. Unset offers the built-in nine." },
    min:              { type: "number",  default: 0,        control: "number",  group: "behavior", description: "Minimum amount." },
    step:             { type: "number",  default: 0.01,     control: "number",  group: "behavior", description: "Amount increment (default 0.01 for cents)." },
    placeholder:      { type: "string",  default: "0.00",   control: "text",    group: "content",  description: "Empty-state amount placeholder." },
  },
};

export const moneyDisplayEntry: RegistryEntry = {
  name: "MoneyDisplay",
  category: "display",
  icon: "Coins",
  description: "Read-only, locale-aware formatted currency amount (tabular).",
  slots: { type: "leaf" },
  props: {
    // THE AMOUNT. The entry exposed the five formatting knobs and not the one
    // value the component exists to render, and had no `bind` either — so
    // `hasValue` was permanently false and every MoneyDisplay on every page
    // showed a permanent em-dash. Per-prop `{{expr}}` binding could not rescue
    // it: the bind toggle is rendered per DECLARED descriptor, so a prop that
    // isn't here cannot be bound. Seeded with a sample amount so a dropped node
    // shows formatted money rather than a dash. The schema takes a number or a
    // decimal STRING (strings keep cents exact); MoneyDisplay renders `—` for
    // null/undefined/"" so clearing the field is still a valid "no amount".
    value:      { type: "string",  default: "1234.56", control: "text",  group: "content",  description: "Amount to format — a number or a decimal string. Empty renders an em-dash." },
    bind:       { type: "binding", default: null,    control: "binding", group: "data",     description: "Data path to bind the amount." },
    currency:   { type: "string",  default: "USD",   control: "text",    group: "content",  description: "3-letter ISO currency code." },
    locale:     { type: "string",  default: "en-US", control: "text",    group: "content",  description: "BCP-47 locale (drives grouping + decimals)." },
    compact:    { type: "boolean", default: false,   control: "toggle",  group: "behavior", description: "Compact notation ($1.2M)." },
    showSymbol: { type: "boolean", default: true,    control: "toggle",  group: "behavior", description: "Show the currency symbol vs the 3-letter code." },
    align:      { type: "string",  default: "right", control: "select",  group: "style",    description: "Horizontal alignment.", options: ["left", "right"] },
  },
};

export const radioGroupEntry: RegistryEntry = {
  name: "RadioGroup",
  category: "input",
  icon: "CircleDot",
  description: "Single-select radio option group.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:   { type: "string",  default: "Choose one", control: "text",    group: "content", description: "Group label." },
    options: {
      type: "array",
      // REQUIRED (`z.array(RadioOption).min(1)`) and previously exposed by NO
      // control whatsoever, so a dropped RadioGroup rendered its label and zero
      // radios — verified live: `input[type=radio]` count was 0. Seeded with two
      // real options so the component is usable the moment it lands.
      default: [{ value: "one", label: "Option one" }, { value: "two", label: "Option two" }],
      control: "json",
      group: "content",
      description: "Options as [{ value, label }]. At least one is required.",
    },
    orientation: { type: "enum", options: ["vertical", "horizontal"], default: "vertical", control: "select", group: "style", description: "Stack the radios vertically or in a row." },
    required:    { type: "boolean", default: false, control: "toggle", group: "behavior", description: "Must be answered before the form submits." },
    disabled:    { type: "boolean", default: false, control: "toggle", group: "behavior", description: "Disable the whole group." },
    bind: { type: "binding", default: null,         control: "binding", group: "data",    description: "Data path to bind the selected value." },
  },
};

export const sliderEntry: RegistryEntry = {
  name: "Slider", category: "input", icon: "SlidersHorizontal",
  description: "Numeric slider (single value or range).",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:   { type: "string",  default: "Value", control: "text",    group: "content",  description: "Slider label." },
    min:     { type: "number",  default: 0,       control: "number",  group: "behavior", description: "Minimum." },
    max:     { type: "number",  default: 100,     control: "number",  group: "behavior", description: "Maximum." },
    range:   { type: "boolean", default: false,   control: "toggle",  group: "behavior", description: "Two-thumb range mode." },
    step:      { type: "number",  default: 1,     control: "number", group: "behavior", description: "Increment between values. 0.5 for half-steps, 0.01 for currency." },
    showValue: { type: "boolean", default: false, control: "toggle", group: "content",  description: "Show the current value beside the label." },
    defaultValue: { type: "number", default: 0, control: "number", group: "content", description: "Starting value. A SEED, not ownership — the field stays editable (see library util/useFieldValue.ts)." },
    validators: {
      type: "object",
      // Every input node carries a `validators` slot and these five never
      // exposed it, so "this field is required" was unsayable in the editor for
      // half the input library — even now that the components honour
      // `validators.required`. Seeded with the no-op form because the `json`
      // control renders an EMPTY textarea for a null default and teaches nothing.
      default: { required: false },
      control: "json",
      group: "behavior",
      description: "Validation rules { required?, min?, max?, pattern?, message? }.",
    },
    bind: { type: "binding", default: null,    control: "binding", group: "data",     description: "Data path to bind the value." },
  },
};

export const fileUploadEntry: RegistryEntry = {
  name: "FileUpload", category: "input", icon: "Upload",
  description: "File upload dropzone (drag & drop + browse).",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:    { type: "string",  default: "Upload file", control: "text",    group: "content",  description: "Field label." },
    accept:   { type: "string",  default: "",            control: "text",    group: "behavior", description: "Accepted MIME/extensions, e.g. image/*,.pdf." },
    multiple: { type: "boolean", default: false,         control: "toggle",  group: "behavior", description: "Allow multiple files." },
    bind:  { type: "binding", default: null,          control: "binding", group: "data",     description: "Data path to bind selected files." },
    // The upload CONSTRAINTS were the half of FileUpload the panel never showed:
    // a dropzone whose size limit, hint text and retry behaviour are all
    // unreachable is a dropzone you cannot configure for a real bucket.
    // NO default: FileUpload reads `maxSizeMb === undefined ? Infinity : maxSizeMb * 1024 * 1024`,
    // so seeding the usual `0` would cap every dropped uploader at zero bytes
    // and reject every file with "over the 0 MB limit". Unset means no limit.
    maxSizeMb: { type: "number",               control: "number",  group: "behavior", description: "Reject files larger than this many MB. Leave empty for no limit." },
    hint:      { type: "string",  default: "", control: "text",    group: "content",  description: "Helper text under the dropzone, e.g. \"PDF or PNG, up to 10MB\"." },
    filenameField: { type: "string", default: "", control: "text", group: "data",     description: "Hidden-input name the original filename submits under — match the entity's column." },
    mimeTypeField: { type: "string", default: "", control: "text", group: "data",     description: "Hidden-input name the MIME type submits under — match the entity's column." },
    resumable:  { type: "boolean", default: false, control: "toggle", group: "behavior", description: "Opt into chunked/resumable upload instead of a single-shot POST." },
    retryOn5xx: { type: "boolean", default: false, control: "toggle", group: "behavior", description: "Retry with exponential backoff on transient 5xx responses." },
    chunkSizeMb: { type: "number", default: 5,     control: "number", group: "behavior", description: "Chunk size in MB when `resumable` is on (1-50)." },
  },
};

export const comboboxEntry: RegistryEntry = {
  name: "Combobox", category: "input", icon: "ChevronsUpDown",
  description: "Typeahead select with filterable suggestions.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:       { type: "string",  default: "Select", control: "text",    group: "content",  description: "Field label." },
    placeholder: { type: "string",  default: "Search…", control: "text",   group: "content",  description: "Placeholder text." },
    options: {
      type: "array",
      // ABSENT ENTIRELY until now — not mis-controlled, simply missing. A
      // Combobox is a typeahead over `options`, so a dropped one was a search
      // box that could never have anything to search. Same `array` + `json` +
      // seeded treatment as `Select.options`, for the same reason: the control
      // shows an empty textarea for a null default and teaches nothing.
      default: [{ value: "one", label: "Option one" }, { value: "two", label: "Option two" }],
      control: "json",
      group: "content",
      description: "Options as [{ value, label }] — the list the typeahead filters.",
    },
    filterable: { type: "boolean", default: true,  control: "toggle", group: "behavior", description: "Filter the option list as the user types (off = a plain dropdown)." },
    clearable:  { type: "boolean", default: false, control: "toggle", group: "behavior", description: "Show an \u00d7 button that clears the selection." },
    bind:     { type: "binding", default: null,     control: "binding", group: "data",     description: "Data path to bind the selected value." },
  },
};

export const dropdownMenuEntry: RegistryEntry = {
  name: "DropdownMenu",
  category: "navigation",
  icon: "ChevronDown",
  description: "Button that opens a dropdown menu of actions.",
  slots: { type: "leaf" },
  props: {
    trigger: { type: "string", default: "Actions", control: "text", group: "content", description: "Trigger button label." },
    // THE PROP THE COMPONENT EXISTS FOR, and the editor offered no control for
    // it at all: the persisted node was `{"type":"DropdownMenu","props":
    // {"trigger":"Actions"}}`, the button opened a 160x10 empty popup, and the
    // menu was unreachable from the editor entirely. Same defect on ContextMenu
    // and Menubar below — one class, three instances.
    //
    // `json`, not `actionPicker`: an item is `{ label, value, icon?, disabled? }`
    // (DropdownMenuNode/MenuItem is `.strict()` on exactly those four keys), and
    // actionPicker's only output is an action object, which validateProps' step-3
    // coercion would replace with `[]`.
    //
    // Seeded, like Breadcrumb.items and Select.options: an empty `json` textarea
    // tells the user nothing about the shape it wants, and a menu that opens
    // empty on drop is indistinguishable from a broken one.
    items: {
      type: "array",
      default: [{ label: "Edit", value: "edit" }, { label: "Duplicate", value: "duplicate" }, { label: "Delete", value: "delete" }],
      control: "json",
      group: "content",
      description: "Menu rows as [{ label, value, icon?, disabled? }]. `disabled: true` greys a row out.",
    },
    triggerIcon: {
      type: "string",
      // No default: an unset icon is absent, not "". DropdownMenuNode types it
      // `z.string().optional()`, so `""` would be present-and-meaningless.
      control: "iconPicker",
      group: "content",
      description: "Optional leading icon on the trigger button.",
    },
    align: {
      type: "enum",
      options: ["start", "center", "end"],
      // No default: `align` is `.optional()` on the node and the component's own
      // fallback decides. Seeding one here would freeze that choice on every
      // dropped menu.
      control: "select",
      group: "behavior",
      description: "Which edge of the trigger the menu aligns to.",
    },
  },
};

export const popoverEntry: RegistryEntry = {
  name: "Popover",
  category: "feedback",
  icon: "MessageSquare",
  description: "Click-triggered floating panel anchored to a button.",
  slots: { type: "leaf" },
  props: {
    trigger: { type: "string", default: "Open",    control: "text", group: "content", description: "Trigger button label." },
    title:   { type: "string", default: "",         control: "text", group: "content", description: "Panel title." },
    content: { type: "string", default: "Content",  control: "text", group: "content", description: "Panel body text." },
  },
};

export const tooltipEntry: RegistryEntry = {
  name: "Tooltip",
  category: "feedback",
  icon: "Info",
  description: "Hover/focus hint anchored to an element.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string", default: "Hover me",  control: "text", group: "content", description: "Trigger text." },
    content: { type: "string", default: "Hint text", control: "text", group: "content", description: "Tooltip hint." },
  },
};

export const contextMenuEntry: RegistryEntry = {
  name: "ContextMenu",
  category: "navigation",
  icon: "MousePointerClick",
  description: "Right-click context menu on a surface.",
  slots: { type: "leaf" },
  props: {
    label: { type: "string", default: "Right-click here", control: "text", group: "content", description: "Surface text." },
    // See dropdownMenuEntry.items — same class, same shape. LABEL was the only
    // control the panel offered, so the menu a ContextMenu exists to show could
    // not be authored at all.
    items: {
      type: "array",
      default: [{ label: "Edit", value: "edit" }, { label: "Duplicate", value: "duplicate" }, { label: "Delete", value: "delete" }],
      control: "json",
      group: "content",
      description: "Menu rows as [{ label, value, icon?, disabled? }]. `disabled: true` greys a row out.",
    },
  },
};

export const hoverCardEntry: RegistryEntry = {
  name: "HoverCard",
  category: "feedback",
  icon: "IdCard",
  description: "Rich preview card shown on hover.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string", default: "Hover me", control: "text", group: "content", description: "Trigger text." },
    title:   { type: "string", default: "",         control: "text", group: "content", description: "Card title." },
    content: { type: "string", default: "Details",  control: "text", group: "content", description: "Card body." },
  },
};

export const menubarEntry: RegistryEntry = {
  name: "Menubar",
  category: "navigation",
  icon: "Menu",
  description: "Horizontal application menu bar.",
  slots: { type: "leaf" },
  props: {
    // `props: {}` — the whole entry had ZERO controls, so the Properties panel
    // showed a breakpoint row and nothing else and the persisted node was
    // literally `{"type":"Menubar","props":{}}`. Same class as Carousel /
    // Lightbox / Tree in round 5, and the same class as the two menus above.
    //
    // Shape is MenubarNode's: a list of menus, each with its own item list.
    // `MenubarItem` is `.strict()` on { label, value } — no icon, no disabled —
    // so the seed says exactly that and no more.
    menus: {
      type: "array",
      default: [
        { label: "File", items: [{ label: "New", value: "new" }, { label: "Open", value: "open" }] },
        { label: "Edit", items: [{ label: "Undo", value: "undo" }, { label: "Redo", value: "redo" }] },
      ],
      control: "json",
      group: "content",
      description: "Top-level menus as [{ label, items: [{ label, value }] }].",
    },
  },
};

export const drawerEntry: RegistryEntry = {
  name: "Drawer",
  // NOT CANVAS LAYOUT. Drawer is viewport-anchored (position: fixed, and
  // conditionally renders null), so dropped on the canvas it measures 0x0 —
  // invisible AND unselectable. Listing it under "layout" invites the user to
  // reach for it as a layout primitive and get nothing. Grouped with the other
  // overlays (Popover, Tooltip, HoverCard) instead.
  category: "feedback",
  icon: "PanelRight",
  description: "Side-anchored slide-in sheet opened by a button.",
  slots: { type: "leaf" },
  props: {
    trigger: { type: "string", default: "Open",    control: "text", group: "content",  description: "Trigger button label." },
    title:   { type: "string", default: "Panel",   control: "text", group: "content",  description: "Drawer title." },
    side:    { type: "enum",   default: "right",    control: "select", group: "behavior", options: ["left", "right", "top", "bottom"], description: "Edge the drawer slides from." },
    content: { type: "string", default: "Content",  control: "text", group: "content",  description: "Drawer body text." },
  },
};

export const buttonEntry: RegistryEntry = {
  name: "Button",
  category: "input",
  icon: "MousePointer",
  description: "Triggers an action when pressed.",
  slots: { type: "leaf" },
  props: {
    label: {
      type: "string",
      default: "Button",
      control: "text",
      group: "content",
    },
    variant: {
      type: "enum",
      // The component's Zod enum is primary|secondary|accent|danger|ghost
      // (Button.schema.ts). The registry offered three of the five, so the two
      // that carry MEANING — `danger` for a destructive action, `accent` for a
      // secondary emphasis — were unreachable from the panel: there was no way
      // to make a red "Delete" button in the editor at all.
      options: ["primary", "secondary", "accent", "danger", "ghost"],
      default: "primary",
      control: "select",
      group: "style",
      description: "Visual colour variant. `danger` is the destructive-action red.",
    },
    size: {
      type: "enum",
      options: ["sm", "md", "lg"],
      default: "md",
      control: "select",
      group: "style",
    },
    disabled: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "state",
    },
    onClick: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "behavior",
    },
    clearsFilters: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
    },
    opensDialog: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Id of a Dialog node this button opens when clicked.",
    },
    // EVERYTHING BELOW IS PROP SURFACE THE COMPONENT ALREADY HAD AND THE PANEL
    // COULD NOT REACH. `onClick` (the one prop that stayed an actionPicker) is
    // the schema-renderer's descriptor slot; `navigate` / `workflow` / `submit`
    // are the three declarative behaviours Button actually implements, and none
    // of them were exposed — so "make this button go somewhere" was not a thing
    // the editor could express even though the component has done it all along.
    navigate: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Path this button navigates to when clicked, e.g. /invoices/new.",
    },
    workflow: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Workflow id dispatched when clicked.",
    },
    args: {
      type: "object",
      // Seeded `{}` rather than null: the `json` control shows an empty textarea
      // for null, and an empty record is the shape the user extends.
      default: {},
      control: "json",
      group: "behavior",
      description: "Arguments passed to `workflow` as { key: value }.",
    },
    submit: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Render as a native submit button so it triggers the enclosing Form.",
    },
    loading: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "state",
      description: "Show a spinner and block clicks while the action is in flight.",
    },
    icon: {
      type: "string",
      default: "",
      control: "iconPicker",
      group: "content",
      description: "Lucide icon name rendered beside the label.",
    },
    iconSrc: {
      type: "string",
      default: "",
      control: "image",
      // Required alongside `control: "image"` — the prop IS the url string, the
      // same shape as Avatar.photoUrl.
      imageShape: "url",
      group: "content",
      description: "Image URL used as the icon instead of a Lucide glyph.",
    },
    iconPosition: {
      type: "enum",
      options: ["left", "right"],
      default: "left",
      control: "select",
      group: "style",
      description: "Which side of the label the icon sits on.",
    },
    togglesSidebar: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Make this the app shell's mobile sidebar (hamburger) trigger.",
    },
    "aria-label": {
      type: "string",
      // NO default, deliberately, where every other text prop here defaults to
      // "": Button renders `aria-label={ariaLabel}` unguarded, so a seeded ""
      // would stamp `aria-label=""` on every button the palette drops and
      // override the accessible name its own label provides. `defaultPropsFor`
      // skips descriptors whose default is undefined, which is exactly right —
      // the control is here to ADD a name to an icon-only button, not to blank
      // the one a labelled button already has.
      control: "text",
      group: "content",
      description: "Accessible name — set this when the button is icon-only.",
    },
    dataJourney: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Stable slug emitted as data-journey, used by the journey verifier to pin this CTA.",
    },
  },
};

// ---------------------------------------------------------------------------
// §13.3 Display
// ---------------------------------------------------------------------------

export const headingEntry: RegistryEntry = {
  name: "Heading",
  category: "display",
  icon: "Heading",
  description: "Heading 1–6.",
  slots: { type: "leaf" },
  props: {
    content: {
      type: "string",
      default: "Heading",
      control: "textarea",
      group: "content",
      description: "Text content (supports {{ binding }} expressions).",
    },
    level: {
      type: "enum",
      options: ["1", "2", "3", "4", "5", "6"],
      default: "2",
      control: "select",
      group: "style",
      description: "HTML heading level (h1–h6).",
    },
    weight: {
      type: "enum",
      options: ["light", "regular", "bold", "display"],
      default: "bold",
      control: "select",
      group: "style",
      description: "Font weight bucket.",
    },
    id: {
      type: "string",
      // NO default. This is the element's DOM id — the anchor target an
      // in-page nav or a deep link jumps to. `""` would stamp `id=""` on every
      // heading on the page, and duplicate ids are exactly the failure a
      // seeded default guarantees.
      control: "text",
      group: "behavior",
      description: "DOM id, so in-page links and anchors can jump to this heading.",
    },
  },
};

export const heroEntry: RegistryEntry = {
  name: "Hero",
  category: "layout",
  icon: "Layout",
  description: "Page hero banner with headline, layout variant, and CTAs.",
  slots: { type: "list" },
  props: {
    headline: {
      type: "string",
      default: "Welcome",
      control: "text",
      group: "content",
      description: "Primary hero headline.",
    },
    subhead: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Secondary subheadline.",
    },
    eyebrow: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Small eyebrow label above the headline.",
    },
    layout: {
      type: "enum",
      options: ["centered", "split", "stacked"],
      default: "centered",
      control: "select",
      group: "style",
      description: "Visual layout variant.",
    },
    role: {
      type: "enum",
      options: ["headline", "banner", "inline"],
      default: "headline",
      control: "select",
      group: "style",
      description: "Semantic role hint for the hero.",
    },
    ctas: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ label: "Get started", action: { type: "navigate", to: "/" }, variant: "primary" }],
      control: "json",
      group: "behavior",
      description: "CTA buttons as [{ label, action: { type: \"navigate\", to } | { type: \"workflow\", name }, variant? }].",
    },
    backgroundImage: {
      type: "action",
      default: null,
      control: "image",
      imageShape: "overlay",
      group: "style",
      description: "Background image with optional overlay opacity.",
    },
    media: {
      type: "action",
      default: null,
      control: "image",
      imageShape: "media",
      group: "content",
      description: "Side image or illustration (kind / src / alt).",
    },
  },
};

export const metricTileEntry: RegistryEntry = {
  name: "MetricTile",
  category: "display",
  icon: "BarChart2",
  description: "KPI tile showing a numeric metric with optional delta and trend.",
  slots: { type: "leaf" },
  props: {
    label: {
      type: "string",
      default: "Metric",
      control: "text",
      group: "content",
      description: "Metric label.",
    },
    value: {
      type: "number",
      // `type: "string"` / `default: "0"` against `z.union([z.number(),
      // z.string().min(1)])` (display-components.md C8). The string passed
      // validation, but it declared the wrong primary shape: `format` is
      // "number"|"currency"|"percent"|"duration" and every one of those paths in
      // `MetricTile/formatValue` short-circuits on `typeof value === "string"`,
      // so a string value silently opts the tile out of its own formatting.
      // A number seed formats; a mustache binding still round-trips through the
      // per-prop bind toggle, which is how the string case is meant to arrive.
      default: 0,
      control: "number",
      group: "content",
      description: "Metric value. A number is formatted per FORMAT; bind it for live data.",
    },
    format: {
      type: "enum",
      options: ["number", "currency", "percent", "duration"],
      default: "number",
      control: "select",
      group: "style",
      description: "Display format applied to the value.",
    },
    importance: {
      type: "enum",
      options: ["primary", "secondary", "tertiary"],
      default: "primary",
      control: "select",
      group: "style",
      description: "Visual emphasis level.",
    },
    icon: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Icon name displayed alongside the metric.",
    },
    delta: {
      type: "object",
      // Was `actionPicker`. An action object carries none of these keys, so the
      // schema rejected it and step-3 coercion blanked the prop to `{}` — the
      // control could only ever destroy what it was pointed at.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      // 0.125, NOT 12.5. `MetricTile/delta.ts` documents the numeric contract as
      // a FRACTION (0.12 == 12%) and formats with `style: "percent"`, so the old
      // seed rendered "↑ 1,250%" on every freshly-dropped KPI tile.
      default: { value: 0.125, direction: "up" },
      control: "json",
      group: "data",
      description: "Delta object { value, direction: up|down|flat }. `value` is a FRACTION — 0.125 renders as 12.5%.",
    },
    trend: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [4, 8, 6, 12, 10, 14],
      control: "json",
      group: "data",
      description: "Array of numbers for the sparkline trend.",
    },
    // ── Widget anatomy (display-components.md C7) ────────────────────────
    // `MetricTile.tsx` implements all three in full — a `<dl
    // data-metric-breakdown>` grid and `pickThresholdTone` — and the editor
    // exposed none of them. NONE carries a `default`: a seeded `breakdown` adds
    // sub-lines to every dropped tile, and a seeded `threshold` is a colouring
    // RULE, so any number in `warnAbove` would paint fresh tiles amber. Both
    // are `.optional()` on MetricTileNode, and omission leaves the tile
    // rendering exactly as it does today.
    breakdown: {
      type: "array",
      control: "json",
      group: "content",
      description: "Sub-lines under the value, as [{ label, value }] — e.g. [{\"label\":\"Male\",\"value\":984}].",
    },
    threshold: {
      type: "object",
      control: "json",
      group: "style",
      description: "Colouring rule { warnAbove?, criticalAbove?, colorOnValue? }. Always stamps data-threshold for app CSS.",
    },
    trendWindow: {
      type: "string",
      control: "text",
      group: "data",
      // Honest label: unlike `breakdown`/`threshold`, `MetricTile.tsx` does not
      // destructure this one — it is a composer hint that widens the upstream
      // aggregate query, so setting it changes the DATA, never the pixels. Said
      // in the description so it does not read as a broken control (the
      // `Cascader.placeholder` mistake one file over).
      description: "Data hint, not a visual: the window the delta/sparkline aggregate covers — week | month | quarter | year.",
    },
  },
};

export const avatarEntry: RegistryEntry = {
  name: "Avatar",
  category: "display",
  icon: "User",
  description: "User avatar with optional photo, name, size, and presence status.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      default: "User",
      control: "text",
      group: "content",
      description: "Display name (used for initials fallback).",
    },
    photoUrl: {
      // NO DEFAULT. Both image slots are `z.string().min(1).optional()` in
      // AvatarNode: absent is fine, `""` is present-and-too-short. Seeding `""`
      // put a `too_small` error on every dropped Avatar — and unlike an
      // `invalid_type`, validateProps' step-3 coercion table does not handle it,
      // so the node was invalid against PageV2 everywhere upstream while
      // rendering correctly by luck (`photoUrl || src` is falsy → initials).
      // Omitting `default` keeps the key off the node entirely, which is what
      // "no photo" actually means.
      type: "string",
      control: "image",
      imageShape: "url",
      group: "content",
      description: "Photo URL (Unsplash CDN or relative path). Leave empty for initials.",
    },
    src: {
      // NO DEFAULT — same `too_small` bug as photoUrl above.
      type: "string",
      control: "image",
      imageShape: "url",
      group: "content",
      description: "Alternate image src (legacy; prefer photoUrl).",
    },
    size: {
      type: "enum",
      options: ["xs", "sm", "md", "lg", "xl"],
      default: "md",
      control: "select",
      group: "style",
      description: "Avatar diameter.",
    },
    status: {
      type: "enum",
      // "none" is an explicit OFF value, not padding. The schema's contract is
      // "omit `status` to render no indicator" — undefined is the absent signal
      // — but a `<select>` has no way to express undefined, so every dropped
      // Avatar wore a green presence dot with no value in the control that
      // removed it. "" would fail the schema's `z.string().min(1)` arm; "none"
      // passes it and misses `STATUS_CLASS`, so `statusCls` is undefined and the
      // dot is not rendered. A plain avatar in a table row is expressible again.
      options: ["none", "online", "offline", "away", "busy"],
      default: "none",
      control: "select",
      group: "state",
      description: "Presence indicator. \"none\" hides it.",
    },
  },
};

export const stackEntry: RegistryEntry = {
  name: "Stack",
  category: "layout",
  icon: "AlignJustify",
  description: "Vertical or horizontal flex stack of children.",
  slots: { type: "list" },
  props: {
    direction: {
      type: "enum",
      options: ["vertical", "horizontal"],
      default: "vertical",
      control: "select",
      group: "style",
      description: "Primary flex axis.",
    },
    gap: {
      type: "enum",
      options: ["none", "xs", "sm", "md", "lg", "xl"],
      default: "md",
      control: "select",
      group: "style",
      description: "Gap between children (token name).",
    },
    align: {
      type: "enum",
      options: ["start", "center", "end", "stretch"],
      default: "stretch",
      control: "select",
      group: "style",
      description: "Cross-axis alignment.",
    },
    justify: {
      type: "enum",
      options: ["start", "center", "end", "between", "around"],
      default: "start",
      control: "select",
      group: "style",
      description: "Main-axis justification.",
    },
    wrap: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "style",
      description: "Allow children to wrap onto multiple lines.",
    },
  },
};

export const rowEntry: RegistryEntry = {
  name: "Row",
  category: "layout",
  icon: "AlignHorizontalJustifyStart",
  description: "Horizontal flex row of children.",
  slots: { type: "list" },
  props: {
    gap: {
      type: "enum",
      options: ["none", "xs", "sm", "md", "lg", "xl"],
      default: "md",
      control: "select",
      group: "style",
      description: "Gap between children (token name).",
    },
    align: {
      type: "enum",
      options: ["start", "center", "end", "stretch"],
      default: "center",
      control: "select",
      group: "style",
      description: "Cross-axis (vertical) alignment.",
    },
    justify: {
      type: "enum",
      options: ["start", "center", "end", "between", "around"],
      default: "start",
      control: "select",
      group: "style",
      description: "Main-axis (horizontal) justification.",
    },
    wrap: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "style",
      description: "Allow children to wrap onto multiple lines.",
    },
  },
};

// ---------------------------------------------------------------------------
// §13.4 Navigation
// ---------------------------------------------------------------------------

export const breadcrumbEntry: RegistryEntry = {
  name: "Breadcrumb",
  category: "navigation",
  icon: "ChevronRight",
  description: "Breadcrumb trail with clickable path items.",
  slots: { type: "leaf" },
  props: {
    items: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      // `items` is `z.array(...).min(1)`, so the coerced `[]` also rendered a
      // breadcrumb with no crumbs at all.
      default: [{ label: "Home", href: "/" }, { label: "Current page" }],
      control: "json",
      group: "content",
      description: "Breadcrumb trail as [{ label, href? }]. At least one is required.",
    },
    separator: {
      type: "string",
      default: "/",
      control: "text",
      group: "style",
      description: "Separator character between items.",
    },
  },
};

export const navLinkEntry: RegistryEntry = {
  name: "NavLink",
  category: "navigation",
  icon: "Link",
  description: "Link to another page.",
  slots: { type: "leaf" },
  props: {
    label: {
      type: "string",
      default: "Link",
      control: "text",
      group: "content",
      description: "Visible link text.",
    },
    // WAS `target` AND `icon`, and NavLink.tsx reads NEITHER. Its props are
    // `href | navigate | label | children | currentPath | className | style`
    // (NavLink.schema.ts / NavLink.tsx), so `target` was a text box whose value
    // was silently stripped by validateProps and `icon` was an icon picker with
    // no reader at all — two live controls, zero effect, and a rendered
    // `href="#"` the auditor clicked to nowhere.
    //
    // `navigate` is the name the component (and the `unifyLabelHref` remap, which
    // folds `href` into it) actually reads. NO default: `""` here would put
    // `href=""` on the anchor, which is the Link defect one entry over; absent
    // lets NavLink.tsx's own `?? "#"` fallback apply.
    navigate: {
      type: "string",
      control: "text",
      group: "behavior",
      description: "Target route (e.g. /items) or absolute URL. The active page gets aria-current automatically.",
    },
  },
};

// ---------------------------------------------------------------------------
// §13.5 Layout (extended)
// ---------------------------------------------------------------------------

export const sectionEntry: RegistryEntry = {
  name: "Section",
  category: "layout",
  icon: "Layout",
  description: "Page section with optional eyebrow + heading.",
  slots: { type: "list" },
  props: {
    variant: {
      type: "enum",
      options: ["plain", "feature", "cta", "stats", "split", "full-bleed"],
      default: "plain",
      control: "select",
      group: "style",
      description: "Visual layout variant.",
    },
    title: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Section heading.",
    },
    subtitle: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Section sub-heading.",
    },
    anchor: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "HTML id used as a scroll-to anchor.",
    },
    role: {
      type: "enum",
      options: ["headline", "content", "aside", "footer"],
      default: "content",
      control: "select",
      group: "style",
      description: "Semantic role hint.",
    },
  },
};

export const tabsEntry: RegistryEntry = {
  name: "Tabs",
  category: "layout",
  icon: "Layout",
  description: "Tab container — each child TabPanel maps to one tab.",
  slots: { type: "list", accepts: ["TabPanel"] },
  props: {
    tabs: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // NOT seeded, deliberately, unlike every other array here: the tab strip is
      // DERIVED from the TabPanel children (`buildTabDefs` takes each tab's label
      // from the panel's own `label`), and a seeded entry would override the label
      // the user typed on panel 1 with a placeholder. Empty is the resting state;
      // entries are per-child overrides.
      default: [],
      control: "json",
      group: "content",
      description: "Optional { id?, label, icon? } overrides, one per child — leave empty unless you need to override a panel's own label. The strip itself is built from the TabPanel children.",
    },
    value: {
      type: "string",
      default: "tab-0",
      control: "text",
      group: "state",
      description:
        "Id of the tab to open. Matches a TabPanel's `value`; ignored when it names no tab, in which case the first one opens.",
    },
  },
};

export const tabPanelEntry: RegistryEntry = {
  name: "TabPanel",
  category: "layout",
  icon: "Layout",
  description: "Content panel for one tab inside a Tabs component.",
  slots: { type: "list" },
  props: {
    label: {
      type: "string",
      default: "Tab",
      control: "text",
      group: "content",
      description: "Tab header label.",
    },
    value: {
      type: "string",
      default: "",
      control: "text",
      group: "state",
      description: "Unique value matching its TabDef id.",
    },
  },
};

// ---------------------------------------------------------------------------
// §13.6 Data
// ---------------------------------------------------------------------------

export const tableEntry: RegistryEntry = {
  name: "Table",
  category: "data",
  icon: "Table",
  description: "Data table with typed column definitions.",
  slots: { type: "leaf" },
  props: {
    columns: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ key: "name", label: "Name" }, { key: "status", label: "Status" }],
      control: "json",
      group: "content",
      description: "Columns as [{ key, label, width?, align?, sortable?, format? }].",
    },
    caption: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Accessible table caption.",
    },
  },
};

// ---------------------------------------------------------------------------
// §13.7 Display (extended)
// ---------------------------------------------------------------------------

export const badgeEntry: RegistryEntry = {
  name: "Badge",
  category: "display",
  icon: "Tag",
  description: "Small status or category badge.",
  slots: { type: "leaf" },
  props: {
    content: {
      type: "string",
      default: "Badge",
      control: "text",
      group: "content",
      description: "Badge text.",
    },
    variant: {
      type: "enum",
      // `accent` is implemented — `Badge.tsx` types it in `Variant` and carries a
      // full, commented `VARIANT_CLASS` row wired to --accent/--accent-foreground
      // — and was reachable from nothing. Listed here so the editor can express
      // the second brand hue. `BadgeProps` (Badge.schema.ts) now carries the
      // same six values, so the selection round-trips instead of being stripped
      // back to the parameter default by validateProps.
      options: ["neutral", "primary", "accent", "success", "danger", "warning"],
      default: "neutral",
      control: "select",
      group: "style",
      description: "Colour variant.",
    },
  },
};

// ---------------------------------------------------------------------------
// §13.8 Feedback
// ---------------------------------------------------------------------------

export const alertEntry: RegistryEntry = {
  name: "Alert",
  category: "feedback",
  icon: "AlertCircle",
  description: "Inline alert message with severity variants.",
  slots: { type: "leaf" },
  props: {
    message: {
      type: "string",
      default: "Alert message",
      control: "textarea",
      group: "content",
      description: "Primary alert body text.",
    },
    variant: {
      type: "enum",
      options: ["neutral", "info", "success", "danger", "warning"],
      default: "neutral",
      control: "select",
      group: "style",
      description: "Colour + icon variant.",
    },
    title: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Optional bold title above the message.",
    },
  },
};

export const emptyStateEntry: RegistryEntry = {
  name: "EmptyState",
  category: "feedback",
  icon: "Inbox",
  description: "Empty state placeholder with optional action.",
  slots: { type: "leaf" },
  props: {
    message: {
      type: "string",
      default: "Nothing here yet.",
      control: "textarea",
      group: "content",
      description: "Body text explaining the empty state.",
    },
    icon: {
      type: "string",
      default: "",
      control: "iconPicker",
      group: "content",
      description: "Icon name displayed above the message.",
    },
    action: {
      type: "object",
      // Looks like an action, is not one: ActionPicker emits
      // `{ action: "navigate" | "workflow", ... }` and the schema wants the keys
      // below, so every pick produced a prop the component could not read.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: { label: "Get started", workflow: "createRecord" },
      control: "json",
      group: "behavior",
      description: "CTA button — exactly one of { label, workflow } or { label, navigate }.",
    },
  },
};

// ---------------------------------------------------------------------------
// §13.9 Input (extended)
// ---------------------------------------------------------------------------

export const formEntry: RegistryEntry = {
  name: "Form",
  category: "input",
  icon: "FileText",
  description: "Form container — declarative or children-slot mode.",
  // A `rejects` list, deliberately, where this used to be a 6-entry `accepts`
  // whitelist.
  //
  // What the restriction is FOR: `Form` renders a real `<form>` element, and the
  // only hard constraints on what may live inside one are (a) HTML parser rules
  // and (b) "this component IS the page, not a field in it". A whitelist cannot
  // express that — it expresses "the six components that existed when this entry
  // was written", which is exactly how it ended up refusing 127 of the library's
  // 133 palette components, including NumberInput, MoneyInput, DatePicker,
  // RadioGroup, Combobox, MultiSelect, Switch, Slider, FileUpload and every
  // layout wrapper you need to arrange them ("i cannot add every component
  // inside the form only input field"). Every component added to the library
  // since would have inherited the same refusal silently.
  //
  // So the invariant is stated as the set of things that are genuinely wrong:
  //  • Form — the HTML parser DROPS a nested <form>. The inner node and every
  //    field in it would vanish from the DOM with no error anywhere.
  //  • AppShell — the page frame (min-h-screen, sidebar/topbar props). Audit
  //    finding #1: setting any of its four props blanks the whole page. It is
  //    the thing a Form lives inside, never the reverse.
  //  • InspectorPanel — `position: fixed` and returns null until a URL param is
  //    set, so inside a form it is either not there or not in the form.
  //
  // Everything else — every input, every layout wrapper (Stack/Row/Grid/
  // Container/Section/Card/Cluster/Split/Sidebar), every display and feedback
  // component — is now accepted. Sibling caps still apply normally: a Split
  // dropped in a Form still enforces its own maxChildren, and leaf components
  // still refuse children of their own.
  slots: {
    type: "list",
    rejects: ["Form", "AppShell", "InspectorPanel"],
  },
  props: {
    workflow: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Workflow action id called on submit.",
    },
    fields: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // NOT seeded: `Form` flips to declarative mode the moment `fields.length > 0`
      // (Form.tsx `isDeclarative`) and stops rendering its CHILDREN, so a seeded
      // field would make every Form dropped from the palette silently ignore
      // everything dragged into it.
      default: [],
      control: "json",
      group: "content",
      description: "Declarative field definitions, e.g. [{ kind: \"text\", name: \"email\", label: \"Email\" }]. Leave empty to build the form by dropping inputs into it instead.",
    },
    submitLabel: {
      type: "string",
      default: "Submit",
      control: "text",
      group: "content",
      description: "Label for the submit button (declarative mode).",
    },
    onSuccess: {
      type: "object",
      // The whole point of a Form, and the panel had no word for it: without
      // these two the only post-submit behaviour available was the runtime's
      // own fallback, whatever the page actually wanted.
      //
      // Seeded WITHOUT a `navigate` key on purpose. Form merges this through
      // `withDefaults(onSuccess, { toast: "Saved", navigate: parentPath() })`,
      // and that merge is `??` — so a seeded `navigate: ""` is not nullish, wins
      // the merge, and silently disables the "form submitted, take me back to
      // the list" navigation on every Form the palette drops. An absent key is
      // the only way to say "use the default".
      default: { toast: "Saved" },
      control: "json",
      group: "behavior",
      description: "After a successful submit: { toast?, navigate? }. Omit `navigate` to fall back to the parent list page.",
    },
    onError: {
      type: "object",
      // Mirrors the runtime's own fallback message, for the same reason.
      default: { toast: "Couldn't save — please try again" },
      control: "json",
      group: "behavior",
      description: "After a failed submit: { toast?, navigate? }.",
    },
    autoSave: {
      type: "object",
      // Not seeded: a non-null value TURNS AUTO-SAVE ON, so a seed would make
      // every Form dropped from the palette start writing in the background.
      default: null,
      control: "json",
      group: "behavior",
      description: "Background auto-save: { debounceMs, conflictStrategy: overwrite|merge|prompt }. Leave empty to keep it off.",
    },
    defaultValues: {
      type: "object",
      // Was `actionPicker`. An action object carries none of these keys, so the
      // schema rejected it and step-3 coercion blanked the prop to `{}` — the
      // control could only ever destroy what it was pointed at.
      // Seeded as an empty record rather than sample keys: the keys must match
      // field names, and a fresh Form has none yet. `{}` is the honest template.
      default: {},
      control: "json",
      group: "data",
      description: "Initial field values keyed by field name, e.g. { email: \"a@b.c\" }.",
    },
  },
};

export const iconButtonEntry: RegistryEntry = {
  name: "IconButton",
  category: "input",
  icon: "MousePointer",
  description: "Icon-only button for compact actions.",
  slots: { type: "leaf" },
  props: {
    icon: {
      type: "string",
      default: "Plus",
      control: "iconPicker",
      group: "content",
      description: "Icon name (Lucide).",
    },
    "aria-label": {
      type: "string",
      default: "Action",
      control: "text",
      group: "content",
      description: "Accessible label (required for screen readers).",
    },
    variant: {
      type: "enum",
      options: ["primary", "secondary", "danger", "ghost"],
      default: "secondary",
      control: "select",
      group: "style",
      description: "Visual colour variant.",
    },
    size: {
      type: "enum",
      options: ["sm", "md", "lg"],
      default: "md",
      control: "select",
      group: "style",
      description: "Button size.",
    },
    disabled: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "state",
      description: "Disable the button.",
    },
    workflow: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Workflow action id triggered on click.",
    },
    // `workflow` was exposed but `args` and `navigate` were not, so an IconButton
    // could dispatch a workflow and never say WHAT to, and could not link at all.
    args: {
      type: "object",
      default: {},
      control: "json",
      group: "behavior",
      description: "Arguments passed to `workflow` as { key: value }.",
    },
    navigate: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Path this button navigates to when clicked.",
    },
    loading: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "state",
      description: "Show a spinner and block clicks while the action is in flight.",
    },
    iconSrc: {
      type: "string",
      default: "",
      control: "image",
      imageShape: "url",
      group: "content",
      description: "Image URL used as the icon instead of a Lucide glyph.",
    },
  },
};

// ---------------------------------------------------------------------------
// B1 — Layout extension (6)
// ---------------------------------------------------------------------------

export const sidebarEntry: RegistryEntry = {
  name: "Sidebar",
  category: "layout",
  icon: "PanelLeft",
  description: "Two-column layout: fixed-width sidebar + main content area.",
  slots: { type: "list", maxChildren: 2 },
  props: {
    width: {
      type: "string",
      default: "240px",
      control: "text",
      group: "style",
      description: "CSS width of the sidebar column (px, rem, or %).",
    },
    breakpoint: {
      type: "enum",
      options: ["sm", "md", "lg", "none"],
      default: "md",
      control: "select",
      group: "style",
      description:
        "Viewport breakpoint below which the two columns stack. 'none' keeps them side by side at every width.",
    },
  },
};

export const clusterEntry: RegistryEntry = {
  name: "Cluster",
  category: "layout",
  icon: "LayoutPanelTop",
  description: "Wrapping flex container for groups of same-size children.",
  slots: { type: "list" },
  props: {
    gap: {
      type: "enum",
      options: ["none", "xs", "sm", "md", "lg", "xl"],
      default: "md",
      control: "select",
      group: "style",
      description: "Gap between child elements.",
    },
    justify: {
      type: "enum",
      options: ["start", "center", "end", "between"],
      default: "start",
      control: "select",
      group: "style",
      description: "Main-axis justification.",
    },
    align: {
      type: "enum",
      options: ["start", "center", "end", "stretch"],
      default: "center",
      control: "select",
      group: "style",
      description: "Cross-axis alignment.",
    },
    equalCols: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "style",
      description: "Switch to CSS grid for equal-width columns.",
    },
    equalRows: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "style",
      description: "Apply equal row heights (only when equalCols is true).",
    },
  },
};

export const splitEntry: RegistryEntry = {
  name: "Split",
  category: "layout",
  icon: "Columns2",
  description: "Two-panel split layout with a configurable ratio.",
  slots: { type: "list", maxChildren: 2 },
  props: {
    ratio: {
      type: "enum",
      options: ["1:1", "2:1", "1:2", "1:3", "3:1"],
      default: "1:1",
      control: "select",
      group: "style",
      description: "Width ratio between the two panels.",
    },
    breakpoint: {
      type: "enum",
      options: ["sm", "md", "lg", "none"],
      default: "md",
      control: "select",
      group: "style",
      description:
        "Viewport breakpoint below which the layout stacks vertically. 'none' keeps the two panels side by side at every width.",
    },
  },
};

export const appShellEntry: RegistryEntry = {
  name: "AppShell",
  category: "layout",
  icon: "AppWindow",
  description: "Full-page app shell with optional sidebar, topbar, and right rail.",
  slots: { type: "list" },
  props: {
    sidebar: {
      type: "action",
      default: null,
      control: "json",
      group: "content",
      description: "Schema sub-tree for the navigation sidebar (a node object, e.g. {\"type\":\"SideNav\",...}). A plain string renders as text.",
    },
    topbar: {
      type: "action",
      default: null,
      control: "json",
      group: "content",
      description: "Schema sub-tree for the breadcrumb + user-menu topbar. A plain string renders as text.",
    },
    actions: {
      type: "action",
      default: null,
      control: "json",
      group: "content",
      description: "Schema sub-tree for the page actions toolbar. A plain string renders as text.",
    },
    rightRail: {
      type: "action",
      default: null,
      control: "json",
      group: "content",
      description: "Schema sub-tree for the context sidebar (right rail). A plain string renders as text.",
    },
    breakpoint: {
      type: "enum",
      options: ["sm", "md", "lg", "none"],
      default: "md",
      control: "select",
      group: "style",
      description:
        "Viewport below which the nav rail and right rail collapse away. 'none' keeps every rail visible at all widths.",
    },
  },
};

export const inspectorPanelEntry: RegistryEntry = {
  name: "InspectorPanel",
  // NOT CANVAS LAYOUT. InspectorPanel is viewport-anchored (position: fixed, and
  // conditionally renders null), so dropped on the canvas it measures 0x0 —
  // invisible AND unselectable. Listing it under "layout" invites the user to
  // reach for it as a layout primitive and get nothing. Grouped with the other
  // overlays (Popover, Tooltip, HoverCard) instead.
  category: "feedback",
  icon: "SidebarRight",
  description: "URL-driven inspector panel for detail views and selection context.",
  slots: { type: "list" },
  props: {
    paramKey: {
      type: "string",
      default: "inspector",
      control: "text",
      group: "behavior",
      description: "URL search param key used to track the active selection.",
    },
    title: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Optional panel heading.",
    },
    width: {
      type: "enum",
      options: ["narrow", "default", "wide"],
      default: "default",
      control: "select",
      group: "style",
      description: "Panel width preset (narrow=320px, default=480px, wide=640px).",
    },
    defaultOpen: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "state",
      description:
        "Show the panel with no selection. Off, the panel renders nothing until the URL carries its param — which is why it is invisible on the canvas.",
    },
  },
};

export const tabPanelWithDeepLinkEntry: RegistryEntry = {
  name: "TabPanelWithDeepLink",
  category: "layout",
  icon: "Layers",
  description: "Tab container that syncs the active tab to the URL via a search param.",
  slots: { type: "list" },
  props: {
    paramKey: {
      type: "string",
      default: "tab",
      control: "text",
      group: "behavior",
      description: "URL search param key for the active tab id.",
    },
    tabs: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Not seeded, for the same reason as `Tabs.tabs`: one tab is derived per
      // child, so a seeded entry would override a real child's label.
      default: [],
      control: "json",
      group: "content",
      description: "Optional { id?, label } overrides, one per child. Leave empty — the strip is built from the children.",
    },
    defaultTab: {
      type: "string",
      default: "",
      control: "text",
      group: "state",
      description: "Tab id to activate when the URL param is absent.",
    },
  },
};

// ---------------------------------------------------------------------------
// B2 — Data components (5)
// ---------------------------------------------------------------------------

export const chartEntry: RegistryEntry = {
  name: "Chart",
  category: "data",
  icon: "LineChart",
  description: "Recharts chart — line, bar, area, pie, donut, funnel, or radar.",
  slots: { type: "leaf" },
  props: {
    chartType: {
      type: "enum",
      options: ["line", "bar", "area", "pie", "donut", "funnel", "radar"],
      default: "line",
      control: "select",
      group: "style",
      description: "Chart variant.",
    },
    data: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      // Seeded to match the default `xKey` and the seeded `series` so a Chart
      // dropped from the palette actually DRAWS instead of rendering empty axes.
      default: [{ date: "Mon", value: 12 }, { date: "Tue", value: 18 }, { date: "Wed", value: 9 }, { date: "Thu", value: 22 }],
      control: "json",
      group: "data",
      description: "Rows as [{ <xKey>: string|number, ... }], or a Mustache binding string ({{stats.series}}).",
    },
    xKey: {
      type: "string",
      default: "date",
      control: "text",
      group: "data",
      description: "Data key used for the X axis.",
    },
    series: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ name: "Value", dataKey: "value" }],
      control: "json",
      group: "data",
      description: "Series as [{ name, dataKey, color? }] — dataKey names a field in `data`.",
    },
    height: {
      type: "number",
      default: 300,
      control: "number",
      group: "style",
      description: "Chart height in pixels.",
    },
    showGrid: {
      type: "boolean",
      default: true,
      control: "toggle",
      group: "style",
      description: "Show background grid lines.",
    },
    showLegend: {
      type: "boolean",
      default: true,
      control: "toggle",
      group: "style",
      description: "Show series legend.",
    },
    showTooltip: {
      type: "boolean",
      default: true,
      control: "toggle",
      group: "style",
      description: "Show value tooltip on hover.",
    },
  },
};

export const sparklineEntry: RegistryEntry = {
  name: "Sparkline",
  category: "data",
  icon: "TrendingUp",
  description: "Compact inline sparkline for trend indication.",
  slots: { type: "leaf" },
  props: {
    data: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      // `z.array(z.number()).min(2)`, so the coerced `[]` drew nothing at all.
      default: [4, 8, 6, 12, 10, 14],
      control: "json",
      group: "data",
      description: "Array of at least 2 numbers representing the trend.",
    },
    width: {
      type: "number",
      default: 100,
      control: "number",
      group: "style",
      description: "Sparkline width in pixels.",
    },
    height: {
      type: "number",
      default: 24,
      control: "number",
      group: "style",
      description: "Sparkline height in pixels.",
    },
    color: {
      type: "string",
      // NO default. `Sparkline.tsx` declares `color = "currentColor"` as a JS
      // PARAMETER default, and a parameter default only fires for `undefined` —
      // `""` is a value, so the seed beat the component's own fallback, the
      // polyline got `stroke=""`, and SVG resolves an invalid paint to `none`.
      // The geometry was right and the ink was off: every dropped Sparkline drew
      // an invisible line in a 24px-tall box. Same class as `ActivityFeed.
      // maxHeight: 0` — a seed the component reads as a command rather than as
      // "unset" — and the only `""` left on a `control: "color"` descriptor.
      control: "color",
      group: "style",
      description: "Stroke colour (CSS colour or token path). Unset inherits the surrounding text colour.",
    },
    showDots: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "style",
      description: "Show data point dots.",
    },
  },
};

export const dataGridEntry: RegistryEntry = {
  name: "DataGrid",
  category: "data",
  icon: "Table2",
  description: "Virtualised data grid with sortable, frozen, and custom-rendered columns.",
  slots: { type: "leaf" },
  props: {
    columns: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ key: "id", label: "ID", width: 80 }, { key: "name", label: "Name", sortable: true }, { key: "status", label: "Status" }],
      control: "json",
      group: "content",
      description: "Columns as [{ key, label, width?, sortable?, frozen?, align? }].",
    },
    rows: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ id: "1", name: "First row", status: "Active" }, { id: "2", name: "Second row", status: "Pending" }],
      control: "json",
      group: "data",
      description: "Row objects — keys must match column.key values. Also accepts a binding string.",
    },
    rowKey: {
      type: "string",
      default: "id",
      control: "text",
      group: "data",
      description: "Property name that uniquely identifies each row.",
    },
    virtualise: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Enable row virtualisation (auto-enabled when rows > 100).",
    },
    selectable: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Allow row selection via checkbox.",
    },
    expandable: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Allow rows to expand for detail content.",
    },
    rowActions: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // The irony: this prop DOES hold actions, but one per row and wrapped in a
      // label — a shape ActionPicker has no way to express.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ label: "View", action: { type: "workflow", workflow: "viewRecord" } }],
      control: "json",
      group: "behavior",
      description: "Row actions as [{ label, action: { type: \"workflow\", workflow } }].",
    },
  },
};

export const editableLineGridEntry: RegistryEntry = {
  name: "EditableLineGrid",
  category: "data",
  icon: "Table",
  description: "Line-item editor with inline-editable cells, optional SKU lookup, and a Subtotal/Tax/Total footer. Use for purchase orders, invoices, and order builders.",
  slots: { type: "leaf" },
  props: {
    columns: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ key: "item", label: "Item", type: "text" }, { key: "qty", label: "Qty", type: "number", align: "right" }, { key: "price", label: "Price", type: "currency", align: "right" }],
      control: "json",
      group: "content",
      description: "Columns as [{ key, label, type?, options?, align?, width? }]. type: text|number|currency|select|readonly.",
    },
    rows: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ id: "1", item: "Line item", qty: 1, price: 0 }],
      control: "json",
      group: "data",
      description: "Row objects keyed by column.key, each carrying the `rowKey` id.",
    },
    rowKey: {
      type: "string",
      default: "id",
      control: "text",
      group: "data",
      description: "Property name that uniquely identifies each row.",
    },
    showLookup: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Render an SKU lookup input above the grid.",
    },
    lookupPlaceholder: {
      type: "string",
      default: "Add item — enter name, code, or barcode",
      control: "text",
      group: "content",
      description: "Placeholder text for the lookup input.",
    },
    removable: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Show a per-row remove button.",
    },
    totals: {
      type: "object",
      // Was `actionPicker`. An action object carries none of these keys, so the
      // schema rejected it and step-3 coercion blanked the prop to `{}` — the
      // control could only ever destroy what it was pointed at.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: { auto: true, taxLabel: "VAT", currency: "" },
      control: "json",
      group: "data",
      description: "Footer rollup { auto, subtotal?, tax?, taxRate?, taxLabel?, total?, currency? }. auto=true derives it from the rows.",
    },
    emptyMessage: {
      type: "string",
      default: "No line items.",
      control: "text",
      group: "content",
      description: "Message when rows is empty.",
    },
  },
};

export const timelineEntry: RegistryEntry = {
  name: "Timeline",
  category: "data",
  icon: "Clock",
  description: "Chronological event list with status indicators.",
  slots: { type: "leaf" },
  props: {
    entries: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ timestamp: "2026-01-01T09:00:00Z", title: "Created", status: "completed" }, { timestamp: "2026-01-02T09:00:00Z", title: "Approved", actor: "Jane Doe", status: "approved" }],
      control: "json",
      group: "data",
      description: "Entries as [{ timestamp, title, actor?, status?, detail? }], or a binding string.",
    },
    orientation: {
      type: "enum",
      options: ["vertical", "horizontal"],
      default: "vertical",
      control: "select",
      group: "style",
      description: "Layout direction of the timeline.",
    },
  },
};

export const tableSortableEntry: RegistryEntry = {
  name: "TableSortable",
  category: "data",
  icon: "ArrowUpDown",
  description: "Table with client-side sortable column headers.",
  slots: { type: "leaf" },
  props: {
    columns: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ key: "name", label: "Name", sortable: true }, { key: "status", label: "Status", sortable: true }],
      control: "json",
      group: "content",
      description: "Columns as [{ key, label, width?, align?, sortable? }].",
    },
    caption: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Accessible table caption.",
    },
    onSort: {
      type: "object",
      // The one prop here that is not authorable by ANY control, and was wired to
      // the most dangerous one. TableSortable CALLS this — `onSort(key, dir)` —
      // so ActionPicker's `{ action: "navigate", ... }` was a truthy non-function
      // that threw "onSort is not a function" on the first header click. It is not
      // a `{ key, dir }` descriptor either; that is the ARGUMENT, not the value.
      // Left null: the host wires the callback at runtime and the headers already
      // sort client-side without one. Kept in the registry so the prop is visible
      // and documented rather than mysteriously absent.
      default: null,
      control: "json",
      group: "behavior",
      description: "Runtime callback invoked as onSort(key, dir) when a header is clicked. Wired by the host app, not authorable here — sorting works without it.",
    },
  },
};

// ---------------------------------------------------------------------------
// B3 — Enterprise batch 2 (5)
// ---------------------------------------------------------------------------

export const approvalStepperEntry: RegistryEntry = {
  name: "ApprovalStepper",
  category: "display",
  icon: "CheckCircle",
  description: "Multi-step approval workflow with per-step status badges.",
  slots: { type: "leaf" },
  props: {
    steps: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      // `.min(1)`, so the coerced `[]` left a stepper with no steps.
      default: [{ label: "Submitted", status: "approved" }, { label: "Manager review", status: "current" }, { label: "Finance", status: "pending" }],
      control: "json",
      group: "data",
      description: "Steps as [{ label, status: pending|current|approved|rejected|skipped, actor?, timestamp? }].",
    },
    orientation: {
      type: "enum",
      options: ["horizontal", "vertical"],
      default: "horizontal",
      control: "select",
      group: "style",
      description: "Layout direction of the stepper.",
    },
    // `onStepClick` was here, described as "Workflow ID triggered when a step is
    // clicked". `ApprovalStepper.tsx` destructures `{ steps, orientation }` and
    // the file contains no `onClick` anywhere — the steps are `<li>`s and
    // `<div>`s. A control that promises behaviour the component does not have is
    // worse than no control, so it is gone. Re-add it the day the component
    // grows a click handler.
  },
};

export const personCardEntry: RegistryEntry = {
  name: "PersonCard",
  category: "display",
  icon: "UserCircle",
  description: "Employee / contact card with avatar, role, and contact details.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      default: "Jane Doe",
      control: "text",
      group: "content",
      description: "Full display name.",
    },
    role: {
      type: "string",
      // "Senior Engineer", not "". `PersonCard.tsx:62` renders the role line
      // only `{role && …}`, so the empty seed dropped a card with a name and a
      // blank line where its subtitle belongs — the same headless-on-drop shape
      // as `ActivityFeed.title: ""`. The dead `paletteDefaults.ts` table (C8)
      // had this right all along.
      default: "Senior Engineer",
      control: "text",
      group: "content",
      description: "Job title or role.",
    },
    department: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Department or team name.",
    },
    avatarUrl: {
      type: "string",
      default: "",
      control: "image",
      imageShape: "url",
      group: "content",
      description: "Photo URL for the avatar.",
    },
    avatarInitials: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Initials fallback when no avatarUrl is provided.",
    },
    email: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Contact email address.",
    },
    status: {
      type: "enum",
      options: ["active", "away", "on-leave", "offline"],
      default: "active",
      control: "select",
      group: "state",
      description: "Presence / availability status.",
    },
    manager: {
      type: "object",
      // NO default. `manager` is the only thing `layout: "expanded"` renders
      // that compact does not (`PersonCard.tsx:65-73`, gated on
      // `expanded && manager`), so it must be reachable — but seeding it would
      // stamp a fictional "Reports to" line onto every expanded card, and the
      // schema's string branch is `z.string().min(1)`, which `""` fails.
      control: "json",
      group: "content",
      description: "Reports-to, as a bare name \"Jane Doe\" or { name, role? }. Only rendered when LAYOUT is expanded.",
    },
    layout: {
      type: "enum",
      options: ["compact", "expanded"],
      default: "compact",
      control: "select",
      group: "style",
      description: "Compact shows avatar + name; expanded shows all fields.",
    },
  },
};

export const filterBarEntry: RegistryEntry = {
  name: "FilterBar",
  category: "input",
  icon: "Filter",
  description: "Horizontal filter chip bar with optional saved views and search.",
  slots: { type: "leaf" },
  props: {
    chips: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      // `.min(1)`, so the coerced `[]` left a filter bar with nothing to filter by.
      default: [{ key: "status", label: "Status", options: [{ value: "open", label: "Open" }, { value: "closed", label: "Closed" }] }],
      control: "json",
      group: "content",
      description: "Filter chips as [{ key, label, options: [{ value, label }], defaultValue? }].",
    },
    savedViews: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ label: "All open", filters: { status: "open" } }],
      control: "json",
      group: "content",
      description: "Saved views as [{ label, filters: { <chip key>: <value> } }].",
    },
    showSearch: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Show a free-text search field alongside the filter chips.",
    },
    bind: {
      type: "binding",
      default: null,
      control: "binding",
      group: "data",
      description: "Data path to bind the active filter values.",
    },
  },
};

export const commandPaletteEntry: RegistryEntry = {
  name: "CommandPalette",
  category: "navigation",
  icon: "Command",
  description: "Keyboard-driven command palette (Cmd+K / Ctrl+K).",
  slots: { type: "leaf" },
  props: {
    items: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Each item carries its OWN action, so one action object at the top level
      // was never the right shape.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ label: "Go to dashboard", group: "Pages", action: { type: "navigate", to: "/" } }, { label: "Create record", group: "Actions", action: { type: "workflow", workflow: "createRecord" } }],
      control: "json",
      group: "content",
      description: "Commands as [{ label, group?, shortcut?, action: { type: \"navigate\", to } | { type: \"workflow\", workflow } }].",
    },
    placeholder: {
      type: "string",
      default: "Search commands…",
      control: "text",
      group: "content",
      description: "Input placeholder text.",
    },
    triggerKey: {
      type: "string",
      default: "k",
      control: "text",
      group: "behavior",
      description: "Key combined with Cmd/Ctrl to open the palette (default: k).",
    },
  },
};

export const activityFeedEntry: RegistryEntry = {
  name: "ActivityFeed",
  category: "display",
  icon: "Activity",
  description: "Chronological activity log with actor avatars and action descriptions.",
  slots: { type: "leaf" },
  props: {
    entries: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: [{ timestamp: "2026-01-01T09:00:00Z", actor: { name: "Jane Doe" }, action: "created", target: "Q1 report" }, { timestamp: "2026-01-02T14:30:00Z", actor: { name: "Sam Patel" }, action: "approved", target: "Q1 report" }],
      control: "json",
      group: "data",
      description: "Entries as [{ timestamp, actor: { name, avatarUrl? }, action, target, detail?, category? }], or a binding string.",
    },
    title: {
      type: "string",
      // "Activity", not "". `ActivityFeed.tsx` declares `title = "Activity"` as a
      // PARAMETER default, which `""` does not trigger — so the seeded empty
      // string won, the header `<h3>` rendered with no text and zero height, and
      // the feed arrived headless. A parameter default is only reachable when
      // the prop is absent or undefined; `defaultPropsFor` copies `""` verbatim.
      default: "Activity",
      control: "text",
      group: "content",
      description: "Optional section title above the feed.",
    },
    showFilter: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Show category filter chips above the feed.",
    },
    maxHeight: {
      type: "number",
      // 480, not 0. `defaultPropsFor` copies this verbatim onto every dropped
      // node, so a default of 0 was not "unset" — it was an instruction to clip
      // the feed to zero height. 480 is the component's own fallback, so the
      // number field now shows the height actually in effect instead of a magic
      // value the user has no way to restore (clearing the field snapped back
      // to 0). Typing 0 still means unconstrained.
      default: 480,
      control: "number",
      group: "style",
      description: "Maximum height in px before the feed scrolls (0 = unconstrained).",
    },
    // Two props the editor could not reach (display-components.md C7). Neither
    // carries a `default`: `limit` is `z.number().int().positive()`, so the
    // obvious `0` seed is BOTH schema-invalid AND the command "render no rows"
    // — exactly the `maxHeight: 0` failure one prop above. `fields` is a
    // partial column map; an empty `{}` is not "unset", it is "map nothing",
    // and the component's contract-name fallbacks are the right behaviour
    // until the composer or the user supplies a real map.
    limit: {
      type: "number",
      control: "number",
      group: "content",
      description: "Max rows to render. Unset = all. Must be 1 or more.",
    },
    fields: {
      type: "object",
      control: "json",
      group: "data",
      description: "Map of contract slot to entity column, e.g. {\"actor\":\"user_name\",\"target\":\"order_id\"}. Stops a bound feed rendering \"Someone\" on every row.",
    },
  },
};

// ---------------------------------------------------------------------------
// B4 — Enterprise batch 3 + misc (7)
// ---------------------------------------------------------------------------

export const emptyStateRichEntry: RegistryEntry = {
  name: "EmptyStateRich",
  category: "feedback",
  icon: "PackageOpen",
  description: "Rich empty state with illustration, heading, body, and CTA.",
  slots: { type: "leaf" },
  props: {
    heading: {
      type: "string",
      default: "Nothing here yet",
      control: "text",
      group: "content",
      description: "Primary empty state heading.",
    },
    body: {
      type: "string",
      default: "",
      control: "textarea",
      group: "content",
      description: "Supporting body text.",
    },
    icon: {
      type: "string",
      default: "",
      control: "iconPicker",
      group: "content",
      description: "Lucide icon name shown as placeholder (use instead of illustration).",
    },
    illustration: {
      type: "object",
      // Was `actionPicker`. An action object carries none of these keys, so the
      // schema rejected it and step-3 coercion blanked the prop to `{}` — the
      // control could only ever destroy what it was pointed at.
      // Deliberately NOT seeded: `{ slug }` resolves to `<basePath>/<slug>.svg`
      // and no illustration assets ship with the editor, so any seed would put a
      // broken <img> on every EmptyStateRich the palette drops. `icon` is the
      // zero-config path; this is for projects that bundle their own art.
      //
      // Spelled by OMITTING `default`, not by `default: null`. The `null`
      // convention belongs to the binding/action descriptors, where a reader
      // (`normalizeSeed`) strips it; on a `json` object descriptor it was just a
      // second spelling of absent, and `null` is a value the component schema
      // rejects if it ever reaches one. `default?: unknown` — absence already
      // says this, unambiguously and with nothing to strip.
      control: "json",
      group: "content",
      description: "Illustration: a URL string, or a bundled slot { slug, alt?, tone? } resolved to <basePath>/<slug>.svg.",
    },
    primaryCta: {
      type: "object",
      // Looks like an action, is not one: ActionPicker emits
      // `{ action: "navigate" | "workflow", ... }` and the schema wants the keys
      // below, so every pick produced a prop the component could not read.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: { label: "Get started", action: { type: "navigate", to: "/" } },
      control: "json",
      group: "behavior",
      description: "Primary CTA { label, action: { type: \"navigate\", to } | { type: \"workflow\", workflow } }.",
    },
    sampleDataLink: {
      type: "object",
      // Looks like an action, is not one: ActionPicker emits
      // `{ action: "navigate" | "workflow", ... }` and the schema wants the keys
      // below, so every pick produced a prop the component could not read.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: { label: "Load sample data", action: { type: "workflow", workflow: "loadSampleData" } },
      control: "json",
      group: "behavior",
      description: "Secondary link — a bare URL string, or { label, href? , action? } for loading sample data.",
    },
  },
};

export const dateRangePickerEntry: RegistryEntry = {
  name: "DateRangePicker",
  category: "input",
  icon: "CalendarRange",
  description: "Date range selector with built-in presets and URL-driven state.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      default: "dateRange",
      control: "text",
      group: "behavior",
      description: "Form field name / URL param key.",
    },
    label: {
      type: "string",
      default: "Date range",
      control: "text",
      group: "content",
      description: "Visible field label.",
    },
    startDate: {
      type: "string",
      default: "",
      control: "text",
      group: "state",
      description: "Initial start date in ISO format (YYYY-MM-DD).",
    },
    endDate: {
      type: "string",
      default: "",
      control: "text",
      group: "state",
      description: "Initial end date in ISO format (YYYY-MM-DD).",
    },
    presets: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: ["today", "last-7-days", "last-30-days"],
      control: "json",
      group: "content",
      description: "Preset keys: today, yesterday, last-7-days, last-30-days, quarter-to-date, year-to-date, custom.",
    },
    minDate: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Earliest selectable date (ISO).",
    },
    maxDate: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Latest selectable date (ISO).",
    },
    bind: {
      type: "binding",
      default: null,
      control: "binding",
      group: "data",
      description: "Data path to bind the selected { start, end } range.",
    },
  },
};

export const multiSelectEntry: RegistryEntry = {
  name: "MultiSelect",
  category: "input",
  icon: "ListChecks",
  description: "Searchable multi-value select with chip display.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      default: "multiSelect",
      control: "text",
      group: "behavior",
      description: "URL key / form field name.",
    },
    label: {
      type: "string",
      default: "Select",
      control: "text",
      group: "content",
      description: "Visible field label.",
    },
    placeholder: {
      type: "string",
      default: "Choose options…",
      control: "text",
      group: "content",
      description: "Placeholder text when nothing is selected.",
    },
    options: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      // `.min(1)`, so the coerced `[]` left a MultiSelect with nothing to select.
      default: [{ value: "one", label: "Option one" }, { value: "two", label: "Option two" }],
      control: "json",
      group: "content",
      description: "Options as [{ value, label }]. At least one is required.",
    },
    selected: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Left empty rather than seeded: this is the INITIAL SELECTION, and a seed
      // would hand every dropped MultiSelect a choice the user never made.
      default: [],
      control: "json",
      group: "state",
      description: "Initially selected values — a subset of the `options` value strings.",
    },
    showSearch: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Show search field inside the dropdown.",
    },
    optionsFrom: {
      type: "object",
      // Not seeded: a non-null value REPLACES the static `options` with a
      // dataSource lookup, so a seed pointing at a source that does not exist
      // would empty the dropdown on every drop.
      default: null,
      control: "json",
      group: "data",
      description: "Build the options from a page dataSource instead: { source, value, label }.",
    },
    maxSelectionLabel: {
      type: "number",
      // 3, matching the component's own parameter default. NOT 0: the test is
      // `selected.size > maxSelectionLabel`, so a seeded 0 would collapse to
      // "N selected" the instant anything is picked and the chips — the whole
      // reason this component exists — would never render.
      default: 3,
      control: "number",
      group: "style",
      description: "Collapse the chips to \"N selected\" once more than this many are picked.",
    },
    bind: {
      type: "binding",
      default: null,
      control: "binding",
      group: "data",
      // FilterBar, DateRangePicker and MultiSelect were the only inputs in the
      // library with no binding descriptor at all — the three that most need
      // one, since they exist to drive a query.
      description: "Data path to bind the selected values.",
    },
  },
};

export const featureCardEntry: RegistryEntry = {
  name: "FeatureCard",
  category: "display",
  icon: "Sparkles",
  description: "Marketing-style feature card with icon, title, and description.",
  slots: { type: "leaf" },
  props: {
    title: {
      type: "string",
      default: "Feature",
      control: "text",
      group: "content",
      description: "Feature card heading.",
    },
    description: {
      type: "string",
      // NOT "". `FeatureCardNode.props.description` is `z.string()` — REQUIRED,
      // no `.optional()` — and the Props panel now paints a red REQUIRED marker
      // above it, so seeding `""` shipped a required field the editor itself
      // left blank plus an empty `<p>` under every dropped card's title.
      default: "Short feature description",
      control: "textarea",
      group: "content",
      description: "Supporting description text.",
    },
    icon: {
      type: "string",
      default: "",
      control: "iconPicker",
      group: "content",
      description: "Lucide icon name.",
    },
    cta: {
      type: "object",
      // Looks like an action, is not one: ActionPicker emits
      // `{ action: "navigate" | "workflow", ... }` and the schema wants the keys
      // below, so every pick produced a prop the component could not read.
      // `href` in particular is a key ActionPicker cannot emit at all.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      default: { label: "Learn more", href: "#" },
      control: "json",
      group: "behavior",
      description: "CTA link { label, href } — both required when present.",
    },
    layout: {
      type: "enum",
      options: ["icon-top", "icon-left"],
      default: "icon-top",
      control: "select",
      group: "style",
      description: "Icon position relative to the text content.",
    },
  },
};

export const skeletonEntry: RegistryEntry = {
  name: "Skeleton",
  category: "feedback",
  icon: "Loader",
  description: "Loading skeleton placeholder for content regions.",
  slots: { type: "leaf" },
  props: {
    variant: {
      type: "enum",
      options: ["rect", "circle", "text"],
      default: "rect",
      control: "select",
      group: "style",
      description: "Shape variant: rect for blocks, circle for avatars, text for lines.",
    },
    lines: {
      type: "number",
      // NO default. `variant` defaults to "rect" and SkeletonNode carries a
      // cross-field refinement — "Skeleton.lines is only valid when variant is
      // 'text'" — so seeding `lines: 3` next to `variant: "rect"` made every
      // dropped Skeleton produce a page PageV2 rejects. Two defaults that
      // contradict each other; the one that has to go is the one that is only
      // meaningful in a variant the drop does not choose.
      control: "number",
      group: "style",
      description: "Number of shimmer lines. Only valid when VARIANT is text.",
    },
  },
};

export const loadingStateEntry: RegistryEntry = {
  name: "LoadingState",
  category: "feedback",
  icon: "RefreshCw",
  description: "Full-panel loading indicator with a label.",
  slots: { type: "leaf" },
  props: {
    label: {
      type: "string",
      default: "Loading…",
      control: "text",
      group: "content",
      description: "Descriptive loading message shown below the spinner.",
    },
  },
};

export const keyValueListEntry: RegistryEntry = {
  name: "KeyValueList",
  category: "display",
  icon: "List",
  description: "Structured key–value pair list for detail views.",
  slots: { type: "leaf" },
  props: {
    items: {
      type: "array",
      // Was `actionPicker`, whose ONLY output is an action object. Writing one
      // into an array-typed prop made validateProps' step-3 coercion replace it
      // with `[]` — the control silently emptied the prop it exists to fill.
      // Seeded, like `Select.options`: the `json` control renders an EMPTY
      // textarea for a null default, which tells the user nothing about the shape.
      // `.min(1)`, so the coerced `[]` rendered an empty list every time.
      default: [{ label: "Status", value: "Active" }, { label: "Owner", value: "Jane Doe" }],
      control: "json",
      group: "content",
      description: "Items as [{ label, value, copyable? }]. At least one is required.",
    },
  },
};

// ---------------------------------------------------------------------------
// B5 — Input + motion (4)
// ---------------------------------------------------------------------------

export const linkEntry: RegistryEntry = {
  name: "Link",
  category: "navigation",
  icon: "ExternalLink",
  description: "Inline navigational link that can trigger a page transition or workflow.",
  slots: { type: "leaf" },
  props: {
    label: {
      type: "string",
      default: "Learn more",
      control: "text",
      group: "content",
      description: "Visible link text.",
    },
    navigate: {
      type: "string",
      // NO default. `""` was seeded here and `Link.tsx` puts `navigate`
      // straight into `href`, so every dropped Link rendered `<a href="">` —
      // blue, underlined, cursor:pointer, and completely inert when clicked.
      // Round 5's C3c class (`""` seeded where absent was correct), in the one
      // component where the consequence is a dead link rather than an empty
      // box. Absent lets `LinkProps.navigate`'s own `.default("#")` apply,
      // which is the component's declared "no destination yet" value.
      control: "text",
      group: "behavior",
      description: "Target route (e.g. /items) or absolute URL. Internal routes go through the Navigator.",
    },
    workflow: {
      type: "string",
      // NO default, same reason: `workflow` is `.optional()` and `Link.tsx`
      // gates its dispatch on `if (workflow)`, so `""` is only a longer way of
      // spelling absent — and it makes the prop LOOK set in the panel.
      control: "text",
      group: "behavior",
      description: "Optional workflow ID dispatched on click (alongside or instead of navigate).",
    },
  },
};

export const timePickerEntry: RegistryEntry = {
  name: "TimePicker",
  category: "input",
  icon: "Clock",
  description: "Time-of-day picker.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:   { type: "string",  default: "Time", control: "text",    group: "content", description: "Field label." },
    min:      { type: "string",  default: "",    control: "text",   group: "behavior", description: "Earliest selectable time, HH:MM." },
    max:      { type: "string",  default: "",    control: "text",   group: "behavior", description: "Latest selectable time, HH:MM." },
    step:     { type: "number",  default: 60,    control: "number", group: "behavior", description: "Granularity in seconds. 60 = minutes, 900 = quarter hours." },
    disabled: { type: "boolean", default: false, control: "toggle", group: "state",    description: "Read-only." },
    defaultValue: { type: "string", default: "", control: "text", group: "content", description: "Starting value. A SEED, not ownership — the field stays editable (see library util/useFieldValue.ts)." },
    validators: {
      type: "object",
      // Same slot, same reason as Slider.validators above.
      default: { required: false },
      control: "json",
      group: "behavior",
      description: "Validation rules { required?, min?, max?, pattern?, message? }.",
    },
    bind: { type: "binding", default: null,   control: "binding", group: "data",    description: "Data path to bind the time value." },
  },
};

export const colorPickerEntry: RegistryEntry = {
  name: "ColorPicker",
  category: "input",
  icon: "Palette",
  description: "Color swatch picker with hex value.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:   { type: "string",  default: "Color", control: "text",    group: "content", description: "Field label." },
    disabled: { type: "boolean", default: false, control: "toggle", group: "state", description: "Read-only." },
    defaultValue: { type: "string", default: "#000000", control: "color", group: "content", description: "Starting value. A SEED, not ownership — the field stays editable (see library util/useFieldValue.ts)." },
    validators: {
      type: "object",
      // Same slot, same reason as Slider.validators above.
      default: { required: false },
      control: "json",
      group: "behavior",
      description: "Validation rules { required?, min?, max?, pattern?, message? }.",
    },
    bind: { type: "binding", default: null,    control: "binding", group: "data",    description: "Data path to bind the color value." },
  },
};

export const inputOtpEntry: RegistryEntry = {
  name: "InputOTP",
  category: "input",
  icon: "Hash",
  description: "Segmented one-time-code / PIN input.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:   { type: "string",  default: "Code", control: "text",    group: "content",  description: "Field label." },
    length:  { type: "number",  default: 6,      control: "number",  group: "behavior", description: "Number of digits." },
    validators: {
      type: "object",
      // Same slot, same reason as Slider.validators above.
      default: { required: false },
      control: "json",
      group: "behavior",
      description: "Validation rules { required?, min?, max?, pattern?, message? }.",
    },
    bind: { type: "binding", default: null,   control: "binding", group: "data",     description: "Data path to bind the code." },
  },
};

export const ratingEntry: RegistryEntry = {
  name: "Rating",
  category: "input",
  icon: "Star",
  description: "Star rating input.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:   { type: "string",  default: "Rating", control: "text",    group: "content",  description: "Field label." },
    max:     { type: "number",  default: 5,        control: "number",  group: "behavior", description: "Number of stars." },
    disabled: { type: "boolean", default: false, control: "toggle", group: "state", description: "Read-only display." },
    defaultValue: { type: "number", default: 0, control: "number", group: "content", description: "Starting value. A SEED, not ownership — the field stays editable (see library util/useFieldValue.ts)." },
    validators: {
      type: "object",
      // Same slot, same reason as Slider.validators above.
      default: { required: false },
      control: "json",
      group: "behavior",
      description: "Validation rules { required?, min?, max?, pattern?, message? }.",
    },
    bind: { type: "binding", default: null,     control: "binding", group: "data",     description: "Data path to bind the rating." },
  },
};

export const maskedInputEntry: RegistryEntry = {
  name: "MaskedInput",
  category: "input",
  icon: "TextCursorInput",
  description: "Pattern-masked text input (e.g. phone, ID).",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:   { type: "string",  default: "Field", control: "text",    group: "content",  description: "Field label." },
    mask:    { type: "string",  default: "###-####", control: "text",  group: "behavior", description: "Mask pattern (# = a digit)." },
    defaultValue: { type: "string", default: "", control: "text", group: "content", description: "Starting value. A SEED, not ownership — the field stays editable (see library util/useFieldValue.ts)." },
    bind: { type: "binding", default: null,    control: "binding", group: "data",     description: "Data path to bind the value." },
  },
};

export const keyValueInputEntry: RegistryEntry = {
  name: "KeyValueInput",
  category: "input",
  icon: "ListPlus",
  description: "Editable key→value map for a jsonb / config column.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:       { type: "string",  default: "Configuration", control: "text",   group: "content",  description: "Field label." },
    description: { type: "string",  default: "",              control: "text",   group: "content",  description: "Helper text below the label." },
    valueType:   { type: "enum",    default: "text",          control: "select", group: "behavior", options: ["text", "number", "boolean"], description: "How each value is coerced." },
    bind:     { type: "binding", default: null,            control: "binding", group: "data",     description: "Data path to bind the object." },
  },
};

// ── Enterprise visualisation gap-fill (Gauge / Heatmap / Schematic / Stepper) ──

export const gaugeEntry: RegistryEntry = {
  name: "Gauge",
  category: "display",
  icon: "Gauge",
  description: "Radial KPI dial with coloured threshold zones.",
  slots: { type: "leaf" },
  props: {
    value:   { type: "number",  default: 72,             control: "number",  group: "data",     description: "Current value." },
    min:     { type: "number",  default: 0,              control: "number",  group: "behavior", description: "Range minimum." },
    max:     { type: "number",  default: 100,            control: "number",  group: "behavior", description: "Range maximum." },
    label:   { type: "string",  default: "Utilization",  control: "text",    group: "content",  description: "Caption below the dial." },
    unit:    { type: "string",  default: "%",            control: "text",    group: "content",  description: "Value unit (e.g. %, °C)." },
    // The threshold zones are the whole reason Gauge exists rather than
    // Progress, and the editor could not reach them at all. Seeded ascending
    // and spanning min→max so a dropped dial shows the banding immediately;
    // `GaugeNode.props.thresholds` accepts the same {value,color,label} shape.
    thresholds: {
      type: "array",
      default: [
        { value: 60,  color: "#16a34a", label: "Healthy" },
        { value: 85,  color: "#f59e0b", label: "Warning" },
        { value: 100, color: "#dc2626", label: "Critical" },
      ],
      control: "json",
      group: "style",
      description: "Coloured zone bands as [{ value, color, label? }], ascending by value.",
    },
    size:      { type: "number",  default: 180,          control: "number",  group: "style",    description: "Dial diameter in px." },
    showValue: { type: "boolean", default: true,         control: "toggle",  group: "content",  description: "Show the numeric value inside the dial." },
    bind: { type: "binding", default: null,           control: "binding", group: "data",     description: "Data path to bind the value." },
  },
};

export const splitArcEntry: RegistryEntry = {
  name: "SplitArc",
  category: "display",
  icon: "PieChart",
  description: "Half-arc gauge split across ≥2 coloured segments — the received-vs-costs / income-vs-spend ratio shape from consumer utility dashboards. Distinct from Gauge (single value + needle).",
  slots: { type: "leaf" },
  props: {
    // `SplitArcProps.segments` is `z.array(...).min(1)` — REQUIRED — and this
    // was declared `type:"binding", default:null`, so the one prop the
    // component exists to draw could only ever be bound, never authored, and
    // the seeded `null` coerced to `[]` → an arc with no segments on every
    // drop. A literal array with a `json` editor (the Bindings tab still
    // offers "{{expr}}" for the bound case, as it does for every prop).
    segments: {
      type: "array",
      default: [
        { value: 62, color: "#2563eb", label: "Received", endLabel: "2.15 kW" },
        { value: 38, color: "#f59e0b", label: "Costs" },
      ],
      control: "json",
      group: "data",
      description: "Segments as [{ value, color, label, endLabel?, trend? }], in display order left→right along the arc. At least one is required.",
    },
    total:         { type: "number",  default: 0,                                                                                          control: "number",  group: "behavior", description: "Optional normalisation total. 0/omitted → sum of segment values." },
    title:         { type: "string",  default: "Energy Balance Today",                                                                    control: "text",    group: "content",  description: "Title above the arc." },
    size:          { type: "number",  default: 220,                                                                                         control: "number",  group: "style",    description: "Diameter in px." },
    showLegend:    { type: "boolean", default: true,                                                                                        control: "toggle",  group: "content",  description: "Show the dot + label legend row." },
    showEndLabels: { type: "boolean", default: true,                                                                                        control: "toggle",  group: "content",  description: "Show endpoint values under the arc." },
    // NO DEFAULT — the component derives the stroke from `size` (~11%). A
    // seeded number is a command that overrides that derivation for every
    // dropped arc; absent means "derive it".
    stroke:        { type: "number",                                                                                                        control: "number",  group: "style",    description: "Arc stroke width in px. Leave empty to derive it from size." },
    bind:       { type: "binding", default: null,                                                                                        control: "binding", group: "data",     description: "Data path to bind the segments array." },
  },
};

export const heatmapEntry: RegistryEntry = {
  name: "Heatmap",
  category: "display",
  icon: "Grid3x3",
  description: "Matrix heatmap — rows × columns with colour intensity.",
  slots: { type: "leaf" },
  props: {
    // `data` is the prop the component exists to render and the registry
    // exposed no control for it, so every dropped Heatmap showed the dashed
    // "No heatmap data." placeholder forever. The key names are configurable,
    // so xKey/yKey/valueKey are seeded to match the seeded rows.
    data: {
      type: "array",
      default: [
        { x: "Mon", y: "Week 1", value: 12 }, { x: "Tue", y: "Week 1", value: 28 }, { x: "Wed", y: "Week 1", value: 19 },
        { x: "Mon", y: "Week 2", value: 31 }, { x: "Tue", y: "Week 2", value: 8 },  { x: "Wed", y: "Week 2", value: 24 },
      ],
      control: "json",
      group: "data",
      description: "Flat cells as [{ x, y, value }] — field names configurable below.",
    },
    xKey:       { type: "string",  default: "x",     control: "text",   group: "data",    description: "Cell field holding the column key." },
    yKey:       { type: "string",  default: "y",     control: "text",   group: "data",    description: "Cell field holding the row key." },
    valueKey:   { type: "string",  default: "value", control: "text",   group: "data",    description: "Cell field holding the numeric value." },
    color:      { type: "string",  default: "var(--color-primary-500)", control: "text",   group: "style",   description: "Base cell colour." },
    // NO DEFAULTS on min/max — the component infers the intensity scale from
    // the data. A seeded 0/100 is a command that rescales every heatmap.
    min:        { type: "number",                    control: "number", group: "behavior", description: "Value mapped to zero intensity. Leave empty to use the data minimum." },
    max:        { type: "number",                    control: "number", group: "behavior", description: "Value mapped to full intensity. Leave empty to use the data maximum." },
    cellSize:   { type: "number",  default: 34,      control: "number", group: "style",    description: "Cell size in px." },
    showValues: { type: "boolean", default: false,       control: "toggle",  group: "content", description: "Show numeric value in each cell." },
    bind:    { type: "binding", default: null,        control: "binding", group: "data",    description: "Data path to bind the cells [{x,y,value}]." },
  },
};

export const schematicEntry: RegistryEntry = {
  name: "Schematic",
  category: "display",
  icon: "Map",
  description: "SVG floor/zone/route map with status markers + regions.",
  slots: { type: "leaf" },
  props: {
    width:      { type: "number",  default: 100,   control: "number",  group: "behavior", description: "Coordinate-space width." },
    height:     { type: "number",  default: 60,    control: "number",  group: "behavior", description: "Coordinate-space height." },
    // `markers` is the data prop — with no control the SVG was always empty.
    // Coordinates are in the width×height space declared above.
    markers: {
      type: "array",
      default: [
        { id: "m1", x: 25, y: 20, label: "Aisle A", status: "ok" },
        { id: "m2", x: 60, y: 38, label: "Aisle B", status: "warning" },
      ],
      control: "json",
      group: "data",
      description: "Markers as [{ x, y, id?, label?, status?, color?, shape? }] in the coordinate space above.",
    },
    regions: {
      type: "array",
      default: [
        { id: "z1", label: "Zone 1", x: 10, y: 8,  w: 35, h: 40 },
        { id: "z2", label: "Zone 2", x: 52, y: 8,  w: 35, h: 40 },
      ],
      control: "json",
      group: "data",
      description: "Background regions as [{ x, y, w, h }] or [{ points: [[x,y], …] }], with an optional label/color.",
    },
    statusColors: {
      type: "object",
      default: { ok: "#16a34a", warning: "#f59e0b", error: "#dc2626" },
      control: "json",
      group: "style",
      description: "Marker status → colour map, e.g. { ok: \"#16a34a\" }.",
    },
    // NO DEFAULT — a grid is an opt-in overlay; { cols, rows } drawn on every
    // dropped schematic is a command, not an unset value. Same for heightPx,
    // which the component defaults to 320.
    grid:       { type: "object",                  control: "json",    group: "style",    description: "Optional grid overlay as { cols, rows }." },
    heightPx:   { type: "number",                  control: "number",  group: "style",    description: "Rendered height in px. Leave empty for the 320px default." },
    showLabels: { type: "boolean", default: true,  control: "toggle",  group: "content",  description: "Show marker/region labels." },
    bind:    { type: "binding", default: null,  control: "binding", group: "data",     description: "Data path to bind the markers array." },
  },
};

export const stepperEntry: RegistryEntry = {
  name: "Stepper",
  category: "display",
  icon: "ListChecks",
  description: "Generic process stepper (pending/active/complete/error).",
  slots: { type: "leaf" },
  props: {
    // `StepperProps.steps` is REQUIRED (no `.optional()`, no `.default()`) and
    // the registry exposed only the cosmetic knobs, so a dropped Stepper was an
    // empty 24px strip and the node failed `StepperNode.props.steps: Required`.
    steps: {
      type: "array",
      default: [
        { id: "draft",  label: "Draft",     status: "complete" },
        { id: "review", label: "In review", status: "active" },
        { id: "done",   label: "Done",      status: "pending" },
      ],
      control: "json",
      group: "content",
      description: "Steps as [{ label, id?, description?, status? }]. Status is pending/active/current/complete/done/error/skipped.",
    },
    orientation: { type: "enum",    default: "horizontal", control: "select", group: "style", options: ["horizontal", "vertical"], description: "Layout direction." },
    activeStep:  { type: "number",  default: 0,            control: "number", group: "state", description: "Active step index (derives status)." },
    // NO DEFAULT — `activeId` matches a step by id/label; "" matches nothing
    // and would silently override the index-derived status.
    activeId:    { type: "string",                         control: "text",   group: "state", description: "Current step by id or label (e.g. \"{{record.status}}\"). Takes precedence over activeStep." },
    bind:     { type: "binding", default: null,        control: "binding", group: "data",  description: "Data path to bind the steps array." },
  },
};

// ── Wave 4 — data display ────────────────────────────────────────────────

export const tagEntry: RegistryEntry = {
  name: "Tag",
  category: "display",
  icon: "Tag",
  description: "Dismissible label/chip.",
  slots: { type: "leaf" },
  props: {
    label:     { type: "string",  default: "Tag",      control: "text",   group: "content",  description: "Tag text." },
    variant:   { type: "enum",    default: "default",  control: "select", group: "style", options: ["default", "primary", "accent", "success", "warning", "danger"], description: "Visual style." },
    removable: { type: "boolean", default: false,      control: "toggle", group: "behavior", description: "Show a remove (×) button." },
  },
};

export const statEntry: RegistryEntry = {
  name: "Stat",
  category: "display",
  icon: "TrendingUp",
  description: "KPI metric tile with value and trend.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string", default: "Metric", control: "text",   group: "content", description: "Metric label." },
    value:   { type: "string", default: "0",      control: "text",   group: "content", description: "Metric value." },
    delta:   { type: "string", default: "",       control: "text",   group: "content", description: "Change indicator (e.g. +8%)." },
    trend:   { type: "enum",   default: "neutral", control: "select", group: "style", options: ["up", "down", "neutral"], description: "Trend direction." },
    caption: { type: "string", default: "",       control: "text",   group: "content", description: "Caption beneath the value." },
  },
};

export const descriptionListEntry: RegistryEntry = {
  name: "DescriptionList",
  category: "display",
  icon: "List",
  description: "Term/description key-value pairs.",
  slots: { type: "leaf" },
  props: {
    // With neither `items` nor `emptyText` the component hits its
    // `return null` branch — the dropped node had zero DOM under it and the
    // page failed `DescriptionListNode.props.items: Required`. The canonical
    // {term, description} shape is the one the strict node schema accepts.
    items: {
      type: "array",
      default: [
        { term: "Status",  description: "Active" },
        { term: "Owner",   description: "Unassigned" },
        { term: "Updated", description: "Today" },
      ],
      control: "json",
      group: "content",
      description: "Pairs as [{ term, description }].",
    },
    emptyText:   { type: "string",  default: "No details to show.", control: "text",    group: "content", description: "Shown instead of an empty list — without it the component renders nothing at all." },
    // NO DEFAULT — `dataSource` is the bind-an-object alternative to `items`;
    // an empty {} / [] is an empty configuration, not "unset".
    dataSource:  { type: "binding",                                 control: "binding", group: "data",    description: "Bind an object (or array) and render one row per key/value with itemMode: \"entries\"." },
    itemMode:    { type: "enum",    options: ["items", "entries"],  control: "select",  group: "data",    description: "\"items\" reads `items`; \"entries\" reads the bound `dataSource` object." },
    orientation: { type: "enum",    default: "vertical", control: "select", group: "style", options: ["vertical", "horizontal"], description: "Layout direction." },
  },
};

export const listEntry: RegistryEntry = {
  name: "List",
  category: "display",
  icon: "ListChecks",
  description: "Data-driven item list with title/subtitle.",
  slots: { type: "leaf" },
  props: {
    // `ListNode.props.items` is `.min(1)` required and the registry exposed
    // only `divided`, so every dropped List was an empty bordered <ul> and an
    // invalid node.
    items: {
      type: "array",
      default: [
        { title: "First item",  subtitle: "Subtitle" },
        { title: "Second item", subtitle: "Subtitle" },
      ],
      control: "json",
      group: "content",
      description: "Rows as [{ title, subtitle?, icon? }]. At least one is required.",
    },
    divided: { type: "boolean", default: true, control: "toggle",  group: "style", description: "Show dividers between items." },
    // NO DEFAULT — `limit` is a positive-int cap; 0 is not "unlimited", it is
    // "render nothing" (the ActivityFeed.maxHeight trap).
    limit:   { type: "number",                 control: "number",  group: "behavior", description: "Max rows to render. Leave empty to render them all." },
  },
};

export const segmentedControlEntry: RegistryEntry = {
  name: "SegmentedControl",
  category: "input",
  icon: "Columns",
  description: "Single-select segmented button group.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:   { type: "string",  default: "",   control: "text",    group: "content", description: "Field label." },
    options: {
      type: "array",
      // A NON-EMPTY ARRAY, NOT A COMMA-SEPARATED STRING. Same fix as
      // `Select.options` / `RadioGroup.options`: the contract is
      // `z.array({value,label}).min(1)` and the registry exposed NO control at
      // all, so a dropped SegmentedControl rendered a 6px hairline with zero
      // buttons (verified live: `[data-segmented-control] button` count = 0).
      default: [{ value: "one", label: "Option one" }, { value: "two", label: "Option two" }],
      control: "json",
      group: "content",
      description: "Segments as [{ value, label }]. At least one is required.",
    },
    bind: { type: "binding", default: null, control: "binding", group: "data",    description: "Data path to bind the selected value." },
  },
};

export const treeEntry: RegistryEntry = {
  name: "Tree",
  category: "display",
  icon: "FolderTree",
  description: "Hierarchical expandable tree view.",
  slots: { type: "leaf" },
  props: {
    // The entry carried NO props at all: the Props panel was empty, the node
    // rendered an empty <ul>, and `TreeNode.props.items` (`.min(1)`) made the
    // saved page invalid. Items nest recursively via `children`.
    items: {
      type: "array",
      default: [
        {
          label: "Root",
          children: [
            { label: "Child", value: "c1" },
            { label: "Second child", value: "c2" },
          ],
        },
      ],
      control: "json",
      group: "content",
      description: "Nodes as [{ label, value?, children? }] — `children` nests recursively.",
    },
  },
};

export const transferEntry: RegistryEntry = {
  name: "Transfer",
  category: "input",
  icon: "ArrowLeftRight",
  description: "Dual list-box to move items between two columns.",
  slots: { type: "leaf" },
  props: {
    options: {
      type: "array",
      // A NON-EMPTY ARRAY, NOT A COMMA-SEPARATED STRING. Same fix as
      // `Select.options`: `z.array({value,label}).min(1)` with no control in the
      // registry, so a dropped Transfer showed two empty panels and arrows that
      // moved nothing.
      default: [{ value: "one", label: "Option one" }, { value: "two", label: "Option two" }, { value: "three", label: "Option three" }],
      control: "json",
      group: "content",
      description: "Available items as [{ value, label }]. At least one is required.",
    },
    titles: {
      type: "array",
      // Seeded with the exact strings `Transfer.tsx:36,41` hardcodes as its
      // `titles?.[0] ?? "Available"` fallbacks, so the control shows the labels
      // actually on screen instead of an empty box the user has to guess at.
      // Same value in, same value out — nothing renders differently on drop.
      default: ["Available", "Selected"],
      control: "json",
      group: "content",
      description: "Column headings as [availableTitle, selectedTitle]. Defaults to [\"Available\",\"Selected\"].",
    },
    selected: {
      type: "array",
      // `[]` is the component's own initial state (`useState(selected ?? [])`),
      // so this is genuinely "nothing selected" rather than a command.
      default: [],
      control: "json",
      group: "state",
      description: "Initially-selected option values, as [\"one\"]. Read once on mount.",
    },
    bind: { type: "binding", default: null, control: "binding", group: "data", description: "Data path to bind the selected values." },
  },
};

export const cascaderEntry: RegistryEntry = {
  name: "Cascader",
  category: "input",
  icon: "ChevronsRight",
  description: "Cascading multi-level dropdown select.",
  slots: { type: "leaf" },
  props: {
    options: {
      type: "array",
      // A NON-EMPTY ARRAY, NOT A COMMA-SEPARATED STRING. Same fix as
      // `Select.options`: `z.array(recursive).min(1)` with no control in the
      // registry, so a dropped Cascader rendered one empty column — and the
      // empty-node hint pointed at `bind`, the one prop that is optional.
      default: [
        { value: "na", label: "North America", children: [{ value: "us", label: "United States" }, { value: "ca", label: "Canada" }] },
        { value: "eu", label: "Europe", children: [{ value: "de", label: "Germany" }, { value: "fr", label: "France" }] },
      ],
      control: "json",
      group: "content",
      description: "Nested options as [{ value, label, children? }]. At least one is required.",
    },
    // `placeholder` REMOVED — it was a dead control. `Cascader.tsx` destructures
    // only `{ options, style, onChange }`; the string was written to the node,
    // saved, and rendered nowhere (verified: innerText was ""). Cascader has no
    // placeholder position to render one in either — it paints its columns
    // inline, with no collapsed trigger — so honouring it would mean inventing a
    // new UI affordance, not wiring an existing one. The prop stays in
    // CascaderProps / CascaderNode so existing pages keep parsing; it is simply
    // no longer offered as something the editor can usefully set.
    bind:     { type: "binding", default: null,       control: "binding", group: "data",    description: "Data path to bind the selected path." },
  },
};

// ── Wave 5 — heavy composites ────────────────────────────────────────────

export const calendarEntry: RegistryEntry = {
  name: "Calendar",
  category: "input",
  icon: "Calendar",
  // The palette used to say "Month-grid date picker", which is only half the
  // component: `Calendar.tsx` gates on `Array.isArray(props.events)` and its own
  // schema calls event mode "preferred for data views". Naming both modes here
  // is how a user finds out the other one exists.
  description: "Month/week/agenda calendar: plots bound records as events, or acts as a month-grid date picker.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    // ── Event-calendar mode ──────────────────────────────────────────────
    // Ten props the component implements and the editor could reach none of
    // (docs/editor-audit/input-components-3.md C9 — the largest contract gap in
    // the library). `CalendarNode` was `.strict()` over `{name,value,bind}`, so
    // these needed a schema slot before a descriptor here was safe to add; they
    // are declared on CalendarNode now.
    //
    // ONLY `events` and `view` carry a `default`. Every other one is a FIELD
    // NAME the component already falls back on ("date", "title"/"name") — a
    // seeded default would replace a two-way fallback with a one-way command
    // and silently break feeds whose date column is not called `date`. Omitting
    // `default` means `defaultPropsFor` writes nothing on drop, so the
    // component's own fallbacks stay in charge until the user types something.
    events: {
      type: "binding",
      // `null`, not `[]`. Event mode is entered by `Array.isArray(props.events)`
      // — an empty array IS the command "render event mode with no events", so
      // seeding `[]` would flip every dropped Calendar out of picker mode into a
      // permanently empty month grid. `null` is the honest "unset".
      default: null,
      control: "binding",
      group: "data",
      description: "Records to plot as events. Setting this switches the calendar from date-picker to event mode.",
    },
    view: {
      type: "enum",
      options: ["month", "week", "agenda"],
      default: "month",
      control: "select",
      group: "style",
      description: "Initial view. Users can switch between them in the header.",
    },
    dateField: {
      type: "string",
      control: "text",
      group: "data",
      description: "Event field holding the (start) date. Defaults to \"date\".",
    },
    endDateField: {
      type: "string",
      control: "text",
      group: "data",
      description: "Event field holding an end date, for multi-day spans.",
    },
    titleField: {
      type: "string",
      control: "text",
      group: "data",
      description: "Event field used as the label. Defaults to \"title\", then \"name\".",
    },
    colorField: {
      type: "string",
      control: "text",
      group: "data",
      description: "Categorical event field mapped to the event colour.",
    },
    eventHref: {
      type: "string",
      control: "text",
      group: "behavior",
      description: "Per-event deep link template, e.g. /bookings/{id}.",
    },
    detailFields: {
      type: "array",
      control: "json",
      group: "data",
      description: "Field names to show in the event-detail popup, as [\"status\",\"room\"]. Omitted = the record's own fields.",
    },
    emptyText: {
      type: "string",
      control: "text",
      group: "content",
      description: "Message shown when a day or the agenda has no events.",
    },
    // ── Date-picker mode ─────────────────────────────────────────────────
    value: {
      type: "string",
      // No default. `value` is ISO yyyy-mm-dd and drives BOTH the displayed
      // month and the selection; `""` would be a parse failure on every drop
      // and any real date would pin every new calendar to that day.
      control: "text",
      group: "state",
      description: "Selected date as ISO yyyy-mm-dd. Also controls which month is shown.",
    },
    bind: { type: "binding", default: null, control: "binding", group: "data", description: "Data path to bind the selected date." },
  },
};

export const kanbanEntry: RegistryEntry = {
  name: "Kanban",
  category: "display",
  icon: "Trello",
  description: "Column board with movable cards.",
  slots: { type: "leaf" },
  props: {
    // `bind` was the ONLY prop, so eleven schema props were unreachable and
    // `KanbanNode.props.columns` (`.min(1)`, required) was always absent.
    // `columns` is the static mode and the one the strict node shape demands,
    // so it is what a fresh drop is seeded with.
    columns: {
      type: "array",
      default: [
        { id: "todo",  title: "To do",       cards: [{ id: "c1", title: "Draft the brief" }] },
        { id: "doing", title: "In progress", cards: [{ id: "c2", title: "Review the copy" }] },
        { id: "done",  title: "Done",        cards: [] },
      ],
      control: "json",
      group: "content",
      description: "Columns as [{ id, title, cards: [{ id, title, description? }] }]. At least one is required.",
    },
    // Data-driven mode — NO DEFAULTS. These replace `columns` when set; a
    // seeded groupBy/cardTitle field name would silently re-derive the board
    // from data that is not there.
    data:      { type: "binding",                    control: "binding", group: "data",    description: "Bind an array of records to derive columns from data instead of `columns`." },
    groupBy:   { type: "string",                     control: "text",    group: "data",    description: "Record field whose distinct values become the columns (used with `data`)." },
    // Also no default, and for the sharper reason: `columnOrder` is an explicit
    // column ALLOW-LIST as well as an ordering, so any seed would hide every
    // lane it did not name. Absent means "derive the lanes from the data", which
    // is what a board without it should do.
    columnOrder: { type: "array",                    control: "json",    group: "data",    description: "Explicit lane order / allow-list, e.g. [\"todo\",\"doing\",\"done\"] (used with `data`). Unset derives lanes from the data." },
    cardTitle: { type: "string",                     control: "text",    group: "data",    description: "Record field rendered as the card title (used with `data`)." },
    emptyText: { type: "string",                     control: "text",    group: "content", description: "Shown when the board has no cards." },
    bind: { type: "binding", default: null, control: "binding", group: "data", description: "Data path to the columns array." },
  },
};

export const resourceTimelineEntry: RegistryEntry = {
  name: "ResourceTimeline",
  category: "display",
  icon: "CalendarRange",
  description: "Resource-scheduler / Gantt grid: resources as rows, days as columns, items as bars (reservations, shifts, bookings).",
  slots: { type: "leaf" },
  props: {
    resources: { type: "binding", default: null, control: "binding", group: "data", description: "Data path to the resource rows (rooms, staff, vehicles)." },
    items: { type: "binding", default: null, control: "binding", group: "data", description: "Data path to the items drawn as bars." },
    // NO DEFAULTS on the resource field names: each one falls back through a
    // chain ("name"/"label"/"title") when absent, and seeding one pins the
    // resolution to a field the user's records may not have.
    resourceIdField: { type: "string", control: "text", group: "data", description: "Resource field holding the id. Leave empty for \"id\"." },
    resourceLabelField: { type: "string", control: "text", group: "data", description: "Resource field holding the row label. Leave empty to try name/label/title." },
    resourceSubField: { type: "string", control: "text", group: "data", description: "Resource field for the secondary row line (e.g. \"1 King\")." },
    itemResourceField: { type: "string", default: "resourceId", control: "text", group: "data", description: "Item field holding the resource id." },
    startField: { type: "string", default: "start", control: "text", group: "data", description: "Item start-date field." },
    endField: { type: "string", default: "end", control: "text", group: "data", description: "Item end-date field." },
    titleField: { type: "string", default: "title", control: "text", group: "data", description: "Item bar label field." },
    subtitleField: { type: "string", control: "text", group: "data", description: "Item field for the small secondary bar label." },
    // THE `default` KEY IS DELIBERATELY ABSENT on these three. They were
    // seeded `null` against `z.string().optional()`, which is not `undefined`:
    // every dropped ResourceTimeline failed `ResourceTimelineNode` (and so
    // `PageV2`) three times over. `""` is not the fix either — these are field
    // NAMES and the empty string is not one. Absent is what "unset" means.
    statusField: { type: "string", control: "text", group: "data", description: "Item status field → bar colour + legend." },
    resourceGroupField: { type: "string", control: "text", group: "data", description: "Resource field to group rows under (room type, floor)." },
    // NO DEFAULT — a seeded ISO date pins the grid to the day it was written.
    // Absent means "start at today", which is what the component does.
    rangeStart: { type: "string", control: "text", group: "behavior", description: "ISO date of the first column. Leave empty to start at today." },
    days: { type: "number", default: 14, control: "number", group: "content", description: "Number of day columns." },
    emptyText: { type: "string", control: "text", group: "content", description: "Shown when there are no resources to draw." },
    itemHref: { type: "string", control: "text", group: "behavior", description: "Per-item deep link, e.g. /reservations/{id}." },
    // No `default: null` here — see the three above; a binding descriptor that
    // seeds `null` writes a value the node schema rejects.
    bind: { type: "binding", control: "binding", group: "data", description: "Data path to bind the timeline data." },
  },
};

export const richTextEditorEntry: RegistryEntry = {
  name: "RichTextEditor",
  category: "input",
  icon: "Pilcrow",
  description: "Rich text editor with formatting toolbar.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:   { type: "string",  default: "",       control: "text",    group: "content", description: "Field label." },
    // Four props the component/schema accept and the editor could reach none of
    // (input-components-3.md C9). None carries a `default`:
    //   • `value` is stamped into innerHTML once on mount, so a seeded default
    //     is content the user cannot clear from the panel afterwards.
    //   • `placeholder`/`mentions`/`embeds` are opt-in features; `""` / `{}` /
    //     `[]` are not "unset" here, they are empty configurations that
    //     `mentions.source: z.string().min(1)` would reject outright.
    value: {
      type: "string",
      control: "textarea",
      group: "content",
      description: "Initial HTML content. Applied on mount only — edit it here and reload to see it.",
    },
    placeholder: {
      type: "string",
      control: "text",
      group: "content",
      description: "Placeholder shown while the editor is empty.",
    },
    mentions: {
      type: "object",
      control: "json",
      group: "data",
      description: "Mention autocomplete as { source: workflowName, trigger?: \"@\" }. `source` is required when set.",
    },
    embeds: {
      type: "array",
      control: "json",
      group: "behavior",
      description: "Inline block kinds insertable from the / menu, as [\"image\",\"link\",\"table\"].",
    },
    bind: { type: "binding", default: null,     control: "binding", group: "data",    description: "Data path to bind the HTML value." },
  },
};

export const carouselEntry: RegistryEntry = {
  name: "Carousel",
  category: "display",
  icon: "GalleryHorizontal",
  description: "Slideshow with prev/next and dots.",
  slots: { type: "leaf" },
  props: {
    // The entry carried NO props at all — an empty Props panel, a 45px empty
    // div on the canvas, and `CarouselNode.props.items` (`.min(1)`) missing,
    // which made the saved page invalid. `image` is left out of the seed on
    // purpose: an empty <img> src is a broken-image icon, and the slide
    // renders from title/caption alone.
    items: {
      type: "array",
      default: [
        { title: "Slide one", caption: "Replace this with your own slides." },
        { title: "Slide two", caption: "Each slide takes an image, title and caption." },
      ],
      control: "json",
      group: "content",
      description: "Slides as [{ image?, title?, caption? }]. At least one is required.",
    },
  },
};

export const lightboxEntry: RegistryEntry = {
  name: "Lightbox",
  category: "display",
  icon: "Image",
  description: "Thumbnail gallery with fullscreen viewer.",
  slots: { type: "leaf" },
  props: {
    // The entry carried NO props at all, so the node rendered 960×0 — zero
    // height, no hint overlay, undiagnosable — and `LightboxNode.props.images`
    // (`.min(1)`) made the page invalid. The seed uses inline SVG data URIs
    // rather than a CDN URL so a fresh gallery renders offline and the
    // registry stays free of external hosts.
    images: {
      type: "array",
      default: [
        { src: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='120'><rect width='160' height='120' fill='%23cbd5e1'/></svg>", alt: "Placeholder image one" },
        { src: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='120'><rect width='160' height='120' fill='%2394a3b8'/></svg>", alt: "Placeholder image two" },
      ],
      control: "json",
      group: "content",
      description: "Images as [{ src, alt? }]. At least one is required.",
    },
  },
};

export const codeBlockEntry: RegistryEntry = {
  name: "CodeBlock",
  category: "display",
  icon: "Code",
  description: "Monospace code block with copy button.",
  slots: { type: "leaf" },
  props: {
    // `CodeBlockNode.props.code` is `z.string().min(1)`, so the old `""` seed
    // was `too_small` — every dropped CodeBlock rendered an empty black block
    // AND made the page fail PageV2.
    code:     { type: "string",  default: "const total = items.length;", control: "textarea", group: "content",  description: "Code to display." },
    language: { type: "string",  default: "",   control: "text",     group: "content",  description: "Language label." },
    showCopy: { type: "boolean", default: true, control: "toggle",   group: "behavior", description: "Show a copy button." },
  },
};

export const qrCodeEntry: RegistryEntry = {
  name: "QRCode",
  category: "display",
  icon: "QrCode",
  description: "QR code generated from a value.",
  slots: { type: "leaf" },
  props: {
    // `QRCodeNode.props.value` is `z.string().min(1)`: the old `""` seed was
    // `too_small` and produced a scannable QR encoding the empty string.
    value:   { type: "string",  default: "https://example.com",  control: "text",   group: "content", description: "Encoded value/URL." },
    size:    { type: "number",  default: 128, control: "number", group: "style",   description: "Pixel size." },
    // NO DEFAULT — the caption is optional and a seeded one is copy the user
    // has to delete rather than a value they have to fill in.
    label:   { type: "string",                control: "text",   group: "content", description: "Caption rendered under the code." },
  },
};

// ── Wave 6 — device & capture ────────────────────────────────────────────

export const barcodeScannerEntry: RegistryEntry = {
  name: "BarcodeScanner",
  category: "input",
  icon: "ScanBarcode",
  description: "Real barcode/QR decoder: live camera scan or drag-and-drop image; decoded value lands in a form field.",
  slots: { type: "leaf" },
  props: {
    name:    { type: "string",  default: "barcode", control: "text",    group: "data",    description: "Form field name that receives the decoded value." },
    label:   { type: "string",  default: "Scan a barcode", control: "text", group: "content", description: "Field label." },
    hint:    { type: "string",  default: "",        control: "text",    group: "content", description: "Helper text under the scanner." },
    autoSubmit: {
      type: "boolean",
      // `false` is the component's own behaviour today, so seeding it changes
      // nothing on drop — it just makes the switch findable. The audit's point
      // (BarcodeScanner.tsx:88-89) is that scan-to-search is the whole reason to
      // put a scanner on an inventory page and it could not be turned on.
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Submit the enclosing Form as soon as a code is decoded (scan-to-search).",
    },
    formats: {
      type: "array",
      // NO default. The schema comment reads "Empty = all", but that is the
      // ABSENT case; writing `[]` onto every dropped node is an explicit
      // "accept these formats" list with nothing in it. Left unset so the
      // decoder keeps accepting every format it supports.
      control: "json",
      group: "behavior",
      description: "BarcodeDetector format ids to accept, e.g. [\"ean_13\",\"qr_code\"]. Unset = all formats.",
    },
    bind: { type: "binding", default: null,      control: "binding", group: "data",    description: "Data path to bind the decoded value." },
  },
};

export const cameraCaptureEntry: RegistryEntry = {
  name: "CameraCapture",
  category: "input",
  icon: "Camera",
  description: "Live webcam photo capture.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      // NO default. `name` is `z.string().min(1)` on every input's node schema,
      // so `""` is not "unset" — it is present-and-too-short, and it made the
      // registry's own seed the one value the schema is guaranteed to reject.
      // It was never what a dropped field actually carried either:
      // `buildDroppedNode` derives `name` from the node id (`input_a1b2c3`) so
      // two "Email" fields on one page do not collide. Leaving it unseeded means
      // the registry stops publishing an invalid value to every other consumer
      // (the JSON export, the LLM catalog, the properties panel) while the drop
      // path keeps doing exactly what it did. This control is how the user
      // renames it.
      control: "text",
      group: "content",
      description: "Form field name — the key this value submits under.",
    },
    label:        { type: "string",  default: "Capture Photo", control: "text",    group: "content", description: "Field label." },
    captureLabel: { type: "string",  default: "Capture Photo", control: "text",    group: "content", description: "Capture button text." },
    bind:      { type: "binding", default: null,            control: "binding", group: "data",    description: "Data path to bind the captured image." },
  },
};

export const scannerEntry: RegistryEntry = {
  name: "Scanner",
  category: "input",
  icon: "ScanLine",
  description: "RFID/barcode/QR scan trigger with result panel.",
  slots: { type: "leaf" },
  props: {
    label:      { type: "string",  default: "Scanner", control: "text",   group: "content",  description: "Panel label." },
    deviceType: { type: "enum",    default: "rfid",    control: "select", group: "behavior", options: ["rfid", "barcode", "qr"], description: "Device kind." },
    status:     { type: "enum",    default: "idle",    control: "select", group: "state",    options: ["idle", "scanning", "success", "error"], description: "Scan status." },
    // Three props the component accepts and the editor could not reach. None
    // carries a `default`: all three are optional strings the component renders
    // only when present, and `""` would replace each internal fallback (the
    // scan button's own caption, "no value yet", "no message") with a blank.
    scanLabel:     { type: "string", control: "text", group: "content", description: "Caption on the scan trigger button." },
    value:         { type: "string", control: "text", group: "state",   description: "Scanned value shown in the result panel." },
    statusMessage: { type: "string", control: "text", group: "state",   description: "Message shown beside the status indicator." },
    bind:    { type: "binding", default: null,      control: "binding", group: "data",    description: "Data path to bind the scanned value." },
  },
};

export const validationChecklistEntry: RegistryEntry = {
  name: "ValidationChecklist",
  category: "display",
  icon: "ListChecks",
  description: "List of labelled pass/fail validation items.",
  slots: { type: "leaf" },
  props: {
    // `ValidationChecklistNode.props.items` is `.min(1)` required and the
    // registry exposed only `orientation`, so the node was an empty div and
    // the page failed PageV2. One passing and one failing row so the two
    // states are both visible on drop.
    items: {
      type: "array",
      default: [
        { label: "Has a SKU", valid: true },
        { label: "Price set", valid: false },
      ],
      control: "json",
      group: "content",
      description: "Checks as [{ label, valid }]. At least one is required.",
    },
    // Options ordered as the Zod enum orders them (`["horizontal","vertical"]`)
    // so a reset lands on the schema's first value, not a different one.
    orientation: { type: "enum",    default: "vertical", control: "select", group: "style", options: ["horizontal", "vertical"], description: "Layout direction." },
  },
};

export const datePickerEntry: RegistryEntry = {
  name: "DatePicker",
  category: "input",
  icon: "Calendar",
  description: "Single-date picker input bound to a form field or URL param.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      default: "date",
      control: "text",
      group: "behavior",
      description: "Form field / URL param name.",
    },
    label: {
      type: "string",
      default: "Date",
      control: "text",
      group: "content",
      description: "Visible field label.",
    },
    bind: {
      type: "binding",
      default: null,
      control: "binding",
      group: "data",
      description: "Data path to bind the selected date value.",
    },
    min: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Earliest selectable date (ISO YYYY-MM-DD).",
    },
    max: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Latest selectable date (ISO YYYY-MM-DD).",
    },
    validators: {
      type: "object",
      // Every input node carries a `validators` slot; DatePicker was the one
      // that never exposed it, so "this date is required" was unsayable here.
      // Seeded with the no-op form so the json box arrives showing the shape.
      default: { required: false },
      control: "json",
      group: "behavior",
      description: "Validation rules { required?, min?, max?, pattern?, message? }.",
    },
  },
};

export const fadeInEntry: RegistryEntry = {
  name: "FadeIn",
  category: "display",
  icon: "Sunrise",
  description: "Wraps children in a CSS fade-in entrance animation.",
  slots: { type: "list" },
  props: {
    delay: {
      type: "number",
      default: 0,
      control: "number",
      group: "style",
      description: "Animation delay in milliseconds.",
    },
    duration: {
      type: "number",
      default: 300,
      control: "number",
      group: "style",
      description: "Animation duration in milliseconds.",
    },
  },
};

export const staggerEntry: RegistryEntry = {
  name: "Stagger",
  category: "display",
  icon: "Layers3",
  description: "Stagger-animates direct children one after another.",
  slots: { type: "list" },
  props: {
    delay: {
      type: "number",
      default: 0,
      control: "number",
      group: "style",
      description: "Initial delay before the first child animates (ms).",
    },
    interval: {
      type: "number",
      default: 80,
      control: "number",
      group: "style",
      description: "Delay added between each successive child (ms).",
    },
  },
};

// ---------------------------------------------------------------------------
// Flow primitives — Repeat / Conditional / DataBoundary / Slot.
// These are not rendered components; they're control-flow nodes the LLM uses
// to bind data, branch, or compose templates. Listing them keeps the
// peer-patcher's domain validator from rejecting valid output.
// ---------------------------------------------------------------------------

export const repeatEntry: RegistryEntry = {
  name: "Repeat",
  category: "data",
  icon: "Repeat",
  description: "Render children once per item in a bound list.",
  slots: { type: "list" },
  props: {
    // NO defaults on either. `source` is `z.string().min(1).optional()` on
    // V2RepeatNode, so the seeded `""` was present-and-too-short — absent is
    // valid, "" never is. `bind` is not a declared key of that `.strict()` props
    // object at all (the node schema documents `bind` as a TOP-LEVEL key, while
    // the editor can only ever write into `props`), even though the runtime
    // Repeat does read `props.bind` as an alias — so seeding it guaranteed a
    // page PageV2 rejects. Unseeded, a dropped Repeat carries neither and stays
    // valid until the user binds it. See the ROUTED note for the schema gap.
    source: { type: "string", control: "text", group: "data",
      description: "Binding path of the array (e.g. 'requests'). Alias: `bind`." },
    bind:   { type: "string", control: "text", group: "data",
      description: "Shorthand for source — binding path of the array." },
    path:   { type: "string", default: "", control: "text", group: "data",
      description: "Optional dotted sub-path within the bound array." },
    as:     { type: "string", default: "item", control: "text", group: "data",
      description: "Loop variable name for the child scope." },
    keyPath:{ type: "string", default: "id", control: "text", group: "data",
      description: "Property used as the React key." },
  },
};

export const conditionalEntry: RegistryEntry = {
  name: "Conditional",
  category: "data",
  icon: "GitBranch",
  description: "Render children when an expression is truthy; else otherwise.",
  slots: { type: "list" },
  props: {
    // NO default. `V2ConditionalNode.props.when` is an Expression that rejects
    // the empty string outright ("expression cannot be empty"), so the seed was
    // the one value guaranteed to fail — same rule as the input `name` seeds
    // above. Absent and "" both render nothing, so nothing on the canvas changes.
    when: { type: "string", control: "text", group: "data",
      description: "Expression evaluated against scope; truthy renders children, otherwise the else branch." },
  },
};

export const dataBoundaryEntry: RegistryEntry = {
  name: "DataBoundary",
  category: "data",
  icon: "Database",
  description: "Wraps children with loading/empty fallbacks driven by bound data.",
  slots: { type: "list" },
  props: {
    fallback: { type: "string", default: "", control: "text", group: "data",
      description: "Text shown while data is loading or empty." },
  },
};

export const slotEntry: RegistryEntry = {
  name: "Slot",
  category: "data",
  icon: "Box",
  description: "Named placeholder filled by a parent template.",
  slots: { type: "leaf" },
  props: {
    name: { type: "string", default: "default", control: "text", group: "data",
      description: "Slot name the parent fills." },
  },
};

export const progressEntry: RegistryEntry = {
  name: "Progress",
  category: "feedback",
  icon: "Loader",
  description: "Determinate progress bar or circular ring.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string", default: "Progress", control: "text",   group: "content",  description: "Label." },
    value:   { type: "number", default: 50,         control: "number", group: "state",    description: "Current value." },
    variant: { type: "enum",   default: "bar",      control: "select", group: "style", options: ["bar", "circular"], description: "Bar or circular." },
  },
};

export const spinnerEntry: RegistryEntry = {
  name: "Spinner",
  category: "feedback",
  icon: "LoaderCircle",
  description: "Indeterminate loading spinner.",
  slots: { type: "leaf" },
  props: {
    label: { type: "string", default: "Loading", control: "text",   group: "content", description: "Accessible label." },
    size:  { type: "enum",   default: "md",      control: "select", group: "style", options: ["sm", "md", "lg"], description: "Spinner size." },
  },
};

export const redirectEntry: RegistryEntry = {
  name: "Redirect",
  category: "navigation",
  icon: "CornerUpRight",
  description: "Route alias — replaces the current URL with `to` on mount. Used when two routes serve the same job.",
  slots: { type: "leaf" },
  props: {
    // NO default on `to`. This is the command-default trap in its purest form:
    // `Redirect.tsx` runs `nav.replace(to)` in a mount effect, so a seeded
    // `to: "/"` is not a placeholder value, it is an instruction the component
    // executes the instant the node exists. A Redirect dropped with its defaults
    // made the page it was dropped on permanently unopenable — preview bounced
    // to "/", Back bounced again, and nothing in the editor said why.
    // Undefined is read as "not configured": the mount effect is gated on
    // `if (to)`, so an unseeded Redirect sits quietly showing "Redirecting…"
    // until the user names a destination.
    to:    { type: "string", control: "text", group: "content", description: "Destination route, e.g. /items. Replaces the current URL on mount — nothing happens until it is set." },
    // `label` is `.optional()` and the component renders `label || "Redirecting…"`,
    // so `""` was only a longer spelling of absent.
    label: { type: "string", control: "text", group: "content", description: "Note shown while redirecting (defaults to \"Redirecting…\")." },
  },
};

export const bannerEntry: RegistryEntry = {
  name: "Banner",
  category: "feedback",
  icon: "Megaphone",
  description: "Page-level notification banner.",
  slots: { type: "leaf" },
  props: {
    variant: { type: "enum",   default: "info",        control: "select", group: "style", options: ["info", "success", "warning", "error"], description: "Banner style." },
    title:   { type: "string", default: "",            control: "text",   group: "content", description: "Banner title." },
    message: { type: "string", default: "Message",     control: "text",   group: "content", description: "Banner message." },
    // The only Banner prop with no descriptor, and the one that turns the ✕ on:
    // `BannerProps.dismissible` is declared, `Banner.tsx:29` destructures it and
    // it gates the entire close button, and the editor could not set it — so a
    // dismissible banner was not authorable at all. `false` is a safe seed, not
    // a command: it is exactly what the component already does when the prop is
    // absent, and `BannerNode` types it `z.boolean().optional()`.
    dismissible: { type: "boolean", default: false, control: "toggle", group: "behavior", description: "Show a ✕ that lets the reader dismiss the banner." },
  },
};

export const dialogEntry: RegistryEntry = {
  name: "Dialog",
  category: "display",
  icon: "Square",
  description: "Modal overlay opened by a button with matching opensDialog id.",
  slots: { type: "list", accepts: ["*"] },
  props: {
    id: { type: "string", default: "dialog", control: "text", group: "content",
      description: "Unique id; a Button's opensDialog prop targets this." },
    title: { type: "string", default: "", control: "text", group: "content",
      description: "Header title shown at the top of the dialog." },
    description: { type: "string", default: "", control: "text", group: "content",
      description: "Optional short description shown beneath the title." },
    size: { type: "enum", options: ["sm", "md", "lg", "xl"], default: "md",
      control: "select", group: "style", description: "Maximum width." },
  },
};

// ---------------------------------------------------------------------------
// starterRegistry — 50 components (28 original + 22 B1–B5 additions)
// ---------------------------------------------------------------------------
// Commerce — cart runtime primitives. Storage + API live in the Forge runtime
// (forge_cart table + /api/cart routes); these entries are the UI surface the
// planner/LLM can drop onto pages.
// ---------------------------------------------------------------------------

export const addToCartEntry: RegistryEntry = {
  name: "AddToCart",
  category: "input",
  icon: "ShoppingCart",
  description: "Button that adds the referenced entity row to the current user's cart.",
  slots: { type: "leaf" },
  props: {
    // `AddToCart.tsx` disables itself on `!entity || itemId == null`, so the old
    // `""`/`""` defaults made EVERY freshly-dropped AddToCart a greyed-out,
    // unclickable button. Both are required by the schema with no `.default()`,
    // so nothing downstream could supply them — the registry is the only place
    // a working sample can come from. Rename them to the real entity/row.
    entity:    { type: "string",  default: "Product",  control: "text",   group: "data",     description: "Entity name (e.g. \"Plant\")." },
    itemId:    { type: "string",  default: "1",        control: "text",   group: "data",     description: "Row id of the item being added." },
    quantity:  { type: "number",  default: 1,          control: "number", group: "behavior", description: "Quantity to add. Increments existing lines." },
    price:     { type: "string",  default: "",         control: "text",   group: "content",  description: "Price to snapshot on the cart line." },
    label:     { type: "string",  default: "",         control: "text",   group: "content",  description: "Display label to snapshot on the cart line." },
    text:      { type: "string",  default: "Add to cart", control: "text", group: "content", description: "Button text." },
    variant:   { type: "enum",    default: "primary",  control: "select", group: "style",    options: ["primary", "secondary", "outline", "ghost"], description: "Visual variant." },
    size:      { type: "enum",    default: "md",       control: "select", group: "style",    options: ["sm", "md", "lg"], description: "Button size." },
    fullWidth: { type: "boolean", default: false,      control: "toggle", group: "style",    description: "Stretch to container width." },
  },
};

export const cartBadgeEntry: RegistryEntry = {
  name: "CartBadge",
  category: "navigation",
  icon: "ShoppingBag",
  description: "Nav indicator showing the current user's cart count. Links to a cart page.",
  slots: { type: "leaf" },
  props: {
    href:     { type: "string",  default: "/cart", control: "text",   group: "behavior", description: "Where the badge links to." },
    label:    { type: "string",  default: "Cart",  control: "text",   group: "content",  description: "Visible label next to the count." },
    hideZero: { type: "boolean", default: false,   control: "toggle", group: "behavior", description: "Hide the badge when count is zero." },
  },
};

export const cartPanelEntry: RegistryEntry = {
  name: "CartPanel",
  category: "data",
  icon: "ShoppingBag",
  description: "Cart contents: line items, quantity controls, subtotal, payment method + place-order button.",
  slots: { type: "leaf" },
  props: {
    title:              { type: "string", default: "Your cart",   control: "text",   group: "content",  description: "Panel heading." },
    emptyState:         { type: "string", default: "Your cart is empty.", control: "text", group: "content", description: "Text shown when the cart has no items." },
    currency:           { type: "string", default: "USD",         control: "text",   group: "content",  description: "ISO currency code used for formatting." },
    checkoutLabel:      { type: "string", default: "Place order", control: "text",   group: "content",  description: "Primary CTA label." },
    // `paymentMethods` had no control, so the panel could not name the methods
    // the checkout offers. NO default: `z.array(z.string()).optional()`, and a
    // seeded list would advertise payment methods the app may not actually
    // accept — a seed read as a claim rather than as "unset".
    paymentMethods:     { type: "array",                          control: "json",   group: "content",  description: "Payment methods offered at checkout, e.g. [\"card\",\"invoice\"]." },
    onCheckoutNavigate: { type: "string", default: "/orders",     control: "text",   group: "behavior", description: "Route to visit after a successful checkout." },
  },
};

export const cartPageEntry: RegistryEntry = {
  name: "CartPage",
  category: "layout",
  icon: "ShoppingBag",
  description: "Page-shell wrapper around CartPanel — for /cart routes.",
  slots: { type: "leaf" },
  props: {
    title:              { type: "string", default: "Your cart",   control: "text", group: "content",  description: "Page heading." },
    currency:           { type: "string", default: "USD",         control: "text", group: "content",  description: "ISO currency code used for formatting." },
    checkoutLabel:      { type: "string", default: "Place order", control: "text", group: "content",  description: "Primary CTA label." },
    // `paymentMethods` had no control, so the panel could not name the methods
    // the checkout offers. NO default: `z.array(z.string()).optional()`, and a
    // seeded list would advertise payment methods the app may not actually
    // accept — a seed read as a claim rather than as "unset".
    paymentMethods:     { type: "array",                          control: "json", group: "content",  description: "Payment methods offered at checkout, e.g. [\"card\",\"invoice\"]." },
    onCheckoutNavigate: { type: "string", default: "/orders",     control: "text", group: "behavior", description: "Route to visit after a successful checkout." },
  },
};

// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Spec C Slices 7 + 8 + 9 — interaction depth, dark-mode toggle, illustrated empty
// ---------------------------------------------------------------------------

export const bulkActionBarEntry: RegistryEntry = {
  name: "BulkActionBar",
  category: "input",
  icon: "CheckSquare",
  description: "Selection toolbar: renders count + workflow actions when a Table has rows selected.",
  slots: { type: "leaf" },
  props: {
    selectedCount: {
      type: "number",
      // 2, NOT 0. `BulkActionBar.tsx` returns `null` when selectedCount === 0,
      // so the seeded 0 was not "unset" — it was the command "render nothing",
      // and a dropped BulkActionBar arrived as an invisible, unselectable node.
      //
      // CHOSEN FIX: the registry seed, not a zero-selection render state. The
      // component's hide-at-zero behaviour is its contract in a shipped app —
      // `selectedCount` is bound to a live selection count, and a bar that
      // painted "0 selected · Archive" permanently on every table page would be
      // a real regression in every generated app to fix an editor-only problem.
      // A non-zero seed makes the dropped node visible and editable (which is
      // all the editor needs) and leaves the runtime semantics untouched.
      default: 2,
      control: "number",
      group: "state",
      description: "Number of selected rows. 0 hides the bar entirely — bind this to a live selection count.",
    },
    actions: {
      type: "array",
      // A NON-EMPTY ARRAY, NOT A ONE-LINE TEXT BOX. `type:"string"` renders
      // TextControl, whatever the user types is written to the schema as a
      // STRING, and validateProps' step-3 coercion then turns any non-array in
      // an array position into `[]` — the control that exists to fill the prop
      // was the control that emptied it. Same fix as `Select.options`.
      default: [{ label: "Archive", workflow: "archive_selected", variant: "secondary" }],
      control: "json",
      group: "content",
      description: "Actions as [{ label, workflow, variant?: primary|secondary|ghost|destructive }]. At least one is required.",
    },
    onClear:       { type: "string",  default: "",   control: "text",   group: "behavior", description: "Workflow name to fire on clear-selection ✕." },
  },
};

export const savedViewsPickerEntry: RegistryEntry = {
  name: "SavedViewsPicker",
  category: "input",
  icon: "Bookmark",
  description: "Segmented picker over a list of saved filter+sort configs for a page.",
  slots: { type: "leaf" },
  props: {
    views: {
      type: "array",
      // A NON-EMPTY ARRAY, NOT A ONE-LINE TEXT BOX. Verified live: typing a
      // real JSON array into the text field left the canvas unchanged and
      // autosaved the prop as a quoted string, which step-3 coercion then
      // replaced with `[]` — 0 buttons, forever. Same fix as `Select.options`.
      default: [{ id: "all", label: "All items", isDefault: true }, { id: "recent", label: "Recent" }],
      control: "json",
      group: "content",
      description: "Views as [{ id, label, isDefault? }]. At least one is required.",
    },
    activeViewId:     { type: "string", default: "", control: "text",   group: "state",   description: "Currently selected view id (falls back to default or first)." },
    onSelectWorkflow: { type: "string", default: "", control: "text",   group: "behavior", description: "Workflow name to fire when a view is picked." },
  },
};

export const globalSearchEntry: RegistryEntry = {
  name: "GlobalSearch",
  category: "input",
  icon: "Search",
  description: "App-wide search input; debounced workflow dispatch; Cmd+K focus from anywhere.",
  slots: { type: "leaf" },
  props: {
    placeholder: { type: "string", default: "Search…", control: "text",   group: "content",  description: "Placeholder text." },
    // NOT `""`. `workflow` is `z.string().min(1)` — required — and an empty
    // string is CONSUMED rather than skipped: `GlobalSearch.fire()` injected a
    // `<button data-forge-workflow="">` and clicked it on every keystroke,
    // dispatching a workflow whose name is the empty string. A placeholder name
    // is a misconfiguration the user can see; `""` is one they cannot.
    workflow:    { type: "string", default: "global_search", control: "text", group: "behavior", description: "Workflow name to fire with { query } on submit." },
    debounceMs:  { type: "number", default: 200,       control: "number", group: "behavior", description: "Keystroke debounce in ms (0..2000)." },
  },
};

// SEARCH-3 — full-text search input backed by op:"search" (tsvector/GIN).
// Debounces keystrokes + publishes results into a shared store the paired
// SearchResults reads from. Distinct from GlobalSearch (workflow dispatch)
// — SearchInput calls a data endpoint directly.
export const searchInputEntry: RegistryEntry = {
  name: "SearchInput",
  category: "input",
  icon: "Search",
  description: "Debounced full-text search input; op:\"search\" endpoint; publishes to shared store.",
  slots: { type: "leaf" },
  props: {
    placeholder: { type: "string", default: "Search…", control: "text",   group: "content",  description: "Placeholder text." },
    // NOT `""`. `endpoint` is `z.string().min(1)` — required — and `""` is used
    // rather than skipped: `fetchResults()` built `"" + "?q=…"`, a RELATIVE url
    // that resolved against whatever page the component was on, so an
    // unconfigured SearchInput issued a search request at the editor itself
    // every 300ms of typing. `/api/search` is the documented convention.
    endpoint:    { type: "string", default: "/api/search", control: "text", group: "behavior", description: "URL that resolves op:\"search\" and returns SearchHit[]." },
    debounceMs:  { type: "number", default: 300,       control: "number", group: "behavior", description: "Keystroke debounce in ms (0..2000)." },
    minChars:    { type: "number", default: 2,         control: "number", group: "behavior", description: "Minimum query length before firing (0..20)." },
  },
};

export const searchResultsEntry: RegistryEntry = {
  name: "SearchResults",
  category: "display",
  icon: "List",
  description: "Ranked hit list from SearchInput's shared store; pristine/loading/empty/list states.",
  slots: { type: "leaf" },
  props: {
    hrefPattern:  { type: "string", default: "/${entity}/${id}",                                       control: "text",   group: "behavior", description: "Route template — ${entity}/${id} substituted. Empty = non-navigating rows." },
    skeletonRows: { type: "number", default: 5,                                                        control: "number", group: "behavior", description: "Skeleton row count while loading (1..20)." },
    pristineText: { type: "string", default: "Search across your data.",                               control: "text",   group: "content",  description: "Copy shown before a query is entered." },
    emptyText:    { type: "string", default: "No matches found. Try different keywords or check spelling.", control: "text", group: "content",  description: "Copy shown when a query returns no matches." },
  },
};

export const keyboardShortcutsEntry: RegistryEntry = {
  name: "KeyboardShortcuts",
  category: "input",
  icon: "Keyboard",
  description: "Floating shortcut-legend dialog; opens on triggerKey (default '?'); Escape closes.",
  slots: { type: "leaf" },
  props: {
    shortcuts: {
      type: "array",
      // A NON-EMPTY ARRAY, NOT A ONE-LINE TEXT BOX — `z.array(...).min(1)`, and
      // a string in an array position is coerced to `[]` by validateProps'
      // step 3, so the legend had nothing to list. Same fix as `Select.options`.
      default: [
        { keys: "?", label: "Show keyboard shortcuts", group: "General" },
        { keys: "Cmd+K", label: "Open global search", group: "General" },
      ],
      control: "json",
      group: "content",
      description: "Shortcuts as [{ keys, label, group? }]. At least one is required.",
    },
    triggerKey: { type: "string", default: "?", control: "text", group: "behavior", description: "Key that toggles the dialog open." },
  },
};

export const themeToggleEntry: RegistryEntry = {
  name: "ThemeToggle",
  category: "input",
  icon: "SunMoon",
  description: "Toggles document-root data-theme between light/dark; persists to localStorage; honors prefers-color-scheme on first run.",
  slots: { type: "leaf" },
  props: {
    lightLabel: { type: "string", default: "Switch to light mode", control: "text", group: "content",  description: "aria-label when currently dark." },
    darkLabel:  { type: "string", default: "Switch to dark mode",  control: "text", group: "content",  description: "aria-label when currently light." },
    storageKey: { type: "string", default: "forge-theme",          control: "text", group: "behavior", description: "localStorage key for persisted preference." },
  },
};

export const illustratedEmptyEntry: RegistryEntry = {
  name: "IllustratedEmpty",
  category: "feedback",
  icon: "ImageOff",
  description: "Empty-state with one of 10 built-in monogram-style SVG glyphs; adopts brand tokens.",
  slots: { type: "leaf" },
  props: {
    kind:    { type: "enum",   default: "list", control: "select", group: "content",
               options: ["list", "search", "filtered", "first-use", "no-data", "success", "error", "coming-soon", "no-access", "offline"],
               description: "Which built-in glyph to render." },
    title:   { type: "string", default: "",     control: "text",   group: "content", description: "Primary heading." },
    message: { type: "string", default: "",     control: "text",   group: "content", description: "Optional supporting sentence." },
    action:  { type: "string", default: "",     control: "text",   group: "behavior", description: "Optional {label, workflow} CTA below the illustration." },
  },
};

// ---------------------------------------------------------------------------
// Spec E Wave 1 — advanced interactions (undo / presence / optimistic UI)
// ---------------------------------------------------------------------------

export const undoManagerEntry: RegistryEntry = {
  name: "UndoManager",
  category: "feedback",
  icon: "Undo2",
  description:
    "Global toast bar that listens for undoable mutations emitted by the runtime queue; renders nothing when idle.",
  slots: { type: "leaf" },
  props: {
    position:    { type: "string", default: "bottom-center", control: "text", group: "style",   description: "Dock corner: bottom-left|bottom-center|bottom-right|top-center." },
    timeoutMs:   { type: "number", default: 6000,            control: "number", group: "behavior", description: "Auto-dismiss timeout in ms (0 = keep until dismissed)." },
    labelPrefix: { type: "string", default: "",              control: "text",   group: "content",  description: "Optional label prefix prepended to the emitted mutation label." },
    maxStack:    { type: "number", default: 5,               control: "number", group: "behavior", description: "Maximum stacked undo entries visible at once." },
  },
};

export const presenceIndicatorEntry: RegistryEntry = {
  name: "PresenceIndicator",
  category: "feedback",
  icon: "Users",
  description:
    "Stacked avatars of other users currently viewing the same route (SSE-backed presence stream).",
  slots: { type: "leaf" },
  props: {
    route:        { type: "string",  default: "",   control: "text",   group: "behavior", description: "Optional explicit route key; defaults to current pathname." },
    max:          { type: "number",  default: 5,    control: "number", group: "style",   description: "Maximum avatars before collapsing into '+N'." },
    size:         { type: "number",  default: 28,   control: "number", group: "style",   description: "Avatar diameter in px." },
    showTooltips: { type: "boolean", default: true, control: "toggle", group: "behavior", description: "Show name tooltips on hover." },
  },
};

export const optimisticProviderEntry: RegistryEntry = {
  name: "OptimisticProvider",
  category: "feedback",
  icon: "Zap",
  description:
    "Wraps a subtree that should see intended state immediately and roll back on server error. Layout-neutral (display:contents).",
  slots: { type: "list" },
  props: {
    resource:        { type: "string",  default: "",    control: "text",   group: "behavior", description: "Optional resource key ('tasks', 'orders/42') for scoped cache invalidation." },
    toastOnRollback: { type: "boolean", default: true,  control: "toggle", group: "behavior", description: "On rollback, publish an UndoManager toast explaining the revert." },
    timeoutMs:       { type: "number",  default: 15000, control: "number", group: "behavior", description: "Rollback if the server hasn't confirmed after this many ms (0 disables)." },
  },
};

// ---------------------------------------------------------------------------
// Spec E Wave 2 — accessibility focus primitives
// ---------------------------------------------------------------------------

export const focusTrapEntry: RegistryEntry = {
  name: "FocusTrap",
  category: "feedback",
  icon: "Focus",
  description:
    "Traps Tab/Shift-Tab inside its subtree; auto-restores focus on unmount. Wrap Modal/Drawer/Popover bodies to meet WAI-ARIA dialog focus rules.",
  slots: { type: "list" },
  props: {
    active:       { type: "boolean", default: true, control: "toggle", group: "behavior", description: "When false the trap is inert." },
    autoFocus:    { type: "boolean", default: true, control: "toggle", group: "behavior", description: "Focus the first focusable descendant on mount." },
    restoreFocus: { type: "boolean", default: true, control: "toggle", group: "behavior", description: "Return focus to the prior element on unmount." },
  },
};

export const skipLinkEntry: RegistryEntry = {
  name: "SkipLink",
  category: "navigation",
  icon: "SkipForward",
  description:
    "Hidden-until-focused anchor that jumps to a landmark (default #main). Auto-injected by the shell template so keyboard users can bypass the nav.",
  slots: { type: "leaf" },
  props: {
    target: { type: "string", default: "main",                    control: "text",    group: "behavior", description: "DOM id of the landmark to jump to (# is added automatically)." },
    label:  { type: "string", default: "Skip to main content",    control: "text",    group: "content",  description: "Visible label shown on focus." },
  },
};

export const focusRingEntry: RegistryEntry = {
  name: "FocusRing",
  category: "feedback",
  icon: "CircleDot",
  description:
    "display:contents wrapper that carries --focus-ring-* CSS variables so descendants get a WCAG-visible :focus-visible outline.",
  slots: { type: "list" },
  props: {
    color:  { type: "string", control: "color", group: "style", description: "CSS colour or var expression. Falls back to --focus-ring-color." },
    width:  { type: "number", control: "number", group: "style", description: "Ring width in px. Falls back to --focus-ring-width." },
    offset: { type: "number", control: "number", group: "style", description: "Ring offset in px. Falls back to --focus-ring-offset." },
  },
};

export const autoFocusEntry: RegistryEntry = {
  name: "AutoFocus",
  category: "feedback",
  icon: "MousePointer2",
  description:
    "On mount, focuses the first focusable descendant (or a selector match). Zero-layout wrapper for forms/dialogs.",
  slots: { type: "list" },
  props: {
    enabled:  { type: "boolean", default: true, control: "toggle", group: "behavior", description: "Master toggle." },
    selector: { type: "string",  control: "text",  group: "behavior", description: "Optional preferred CSS selector for the focus target." },
    delayed:  { type: "boolean", default: true, control: "toggle", group: "behavior", description: "Focus on next microtask so we out-race browser scroll-restore." },
  },
};

// ---------------------------------------------------------------------------
// Spec E Wave 3 — advanced UX patterns
// ---------------------------------------------------------------------------

export const wizardEntry: RegistryEntry = {
  name: "Wizard",
  category: "input",
  icon: "ListOrdered",
  description:
    "Multi-step form with back/next validation, per-step field render, and review-before-submit. Dispatches onComplete as a workflow with accumulated values.",
  slots: { type: "leaf" },
  props: {
    steps: {
      type: "array",
      // A NON-EMPTY ARRAY, NOT A ONE-LINE TEXT BOX. `steps: ""` was coerced to
      // `[]` by validateProps' step 3, which gave `total = 0` ⇒ `reviewIdx = 0`
      // ⇒ `isReview` true at step 0: every dropped Wizard opened on its own
      // review screen with an armed Submit. Same fix as `Select.options`.
      default: [
        { id: "details", title: "Details", fields: [{ name: "title", label: "Title", kind: "text", required: true }] },
        { id: "notes", title: "Notes", fields: [{ name: "notes", label: "Notes", kind: "textarea" }] },
      ],
      control: "json",
      group: "content",
      description: "Steps as [{ id, title, description?, fields: [{ name, label, kind, required?, placeholder?, options? }], nextIf? }]. At least one is required.",
    },
    onComplete:   { type: "string",  default: "",     control: "text",   group: "behavior", description: "Workflow name dispatched on final submit." },
    successRoute: { type: "string",  default: "",     control: "text",   group: "behavior", description: "Route to navigate on success (template substituted)." },
    title:        { type: "string",  default: "",     control: "text",   group: "content",  description: "Optional heading above the stepper." },
    skipReview:   { type: "boolean", default: false,  control: "toggle", group: "behavior", description: "When true, the review step is skipped and Next submits directly." },
    submitLabel:  { type: "string",  default: "Submit", control: "text", group: "content",  description: "Label for the final submit button." },
  },
};

export const splitViewEntry: RegistryEntry = {
  name: "SplitView",
  category: "layout",
  icon: "Columns",
  description:
    "Master-detail split: first child = list on the left, second child = detail pane on the right. Selected id syncs to a URL query param.",
  // maxChildren: 2 was missing, so the editor accepted an unbounded number of
  // children into a component that lays out exactly two panes — 117 of 133
  // child pairs were lost (docs/editor-audit/containment.md #2). The renderer
  // now folds any extras into the detail pane rather than dropping them, and
  // this cap tells the user the shape before they get there.
  slots: { type: "list", maxChildren: 2 },
  props: {
    syncKey:     { type: "string",  default: "selected", control: "text",   group: "behavior", description: "URL query key used to sync the selected id." },
    masterWidth: { type: "number",  default: 320,        control: "number", group: "style",    description: "Fixed pixel width for the master column." },
    emptyText:   { type: "string",  default: "Select an item to see details.", control: "text", group: "content", description: "Shown in the detail pane when there is no second child." },
    responsive:  { type: "boolean", default: true,       control: "toggle", group: "style",    description: "Stacks the two panes below 768px when true." },
    requireSelection: { type: "boolean", default: false, control: "toggle", group: "behavior", description: "Hide the detail pane until a row is selected. Off by default — the editor never sets the URL param, so this used to make the second pane invisible." },
  },
};

export const filterBuilderEntry: RegistryEntry = {
  name: "FilterBuilder",
  category: "input",
  icon: "Filter",
  description:
    "Chip-based expression builder that serialises to a URL query param. Configure available fields + operators; wire onApplyWorkflow for server-side data refresh.",
  slots: { type: "leaf" },
  props: {
    fields: {
      type: "array",
      // A NON-EMPTY ARRAY, NOT A ONE-LINE TEXT BOX. `fields: ""` was coerced to
      // `[]`, and `addClause()` early-returns on `!fields[0]` — so "Add a
      // filter…" was a dead button on every dropped FilterBuilder. Same fix as
      // `Select.options`.
      default: [
        { name: "status", label: "Status", type: "enum", options: [{ value: "open", label: "Open" }, { value: "closed", label: "Closed" }] },
        { name: "name", label: "Name", type: "string" },
      ],
      control: "json",
      group: "content",
      description: "Fields as [{ name, label?, type: string|number|boolean|date|enum, operators?, options? }]. At least one is required.",
    },
    paramKey:        { type: "string",  default: "filter", control: "text",   group: "behavior", description: "URL query param the serialised expression is stored under." },
    combinator:      { type: "enum",    default: "AND",    control: "select", group: "behavior", options: ["AND", "OR"], description: "Top-level combinator." },
    emptyLabel:      { type: "string",  default: "Add a filter…", control: "text", group: "content", description: "Placeholder shown when there are no clauses yet." },
    onApplyWorkflow: { type: "string",  default: "",       control: "text",   group: "behavior", description: "Workflow dispatched with the compiled expression on Apply." },
  },
};

export const tourOverlayEntry: RegistryEntry = {
  name: "TourOverlay",
  category: "feedback",
  icon: "Compass",
  description:
    "Step-by-step onboarding tour. Auto-starts on first visit; dismissal is persisted to localStorage under storageKey so it never re-triggers.",
  slots: { type: "leaf" },
  props: {
    steps:      { type: "string",  default: "",                 control: "text",   group: "content",  description: "Array of {target, title, body, placement?} step defs (JSON)." },
    storageKey: { type: "string",  default: "forge-tour-default", control: "text", group: "behavior", description: "localStorage key used to record dismissal." },
    autoStart:  { type: "boolean", default: true,               control: "toggle", group: "behavior", description: "When true, the tour auto-opens on mount." },
    nextLabel:  { type: "string",  default: "Next",             control: "text",   group: "content",  description: "Label for the Next button." },
    doneLabel:  { type: "string",  default: "Done",             control: "text",   group: "content",  description: "Label for the Done button on the last step." },
    skipLabel:  { type: "string",  default: "Skip",             control: "text",   group: "content",  description: "Label for the Skip button." },
  },
};

export const starterRegistry: Registry = {
  // §13.1 Layout
  Container: containerEntry,
  Grid: gridEntry,
  GridCell: gridCellEntry,
  Card: cardEntry,
  Divider: dividerEntry,
  Spacer: spacerEntry,
  Hero: heroEntry,
  Stack: stackEntry,
  Row: rowEntry,
  // §13.2 Input
  Input: inputEntry,
  Textarea: textareaEntry,
  Select: selectEntry,
  Checkbox: checkboxEntry,
  Switch: switchEntry,
  NumberInput: numberInputEntry,
  MoneyInput: moneyInputEntry,
  MoneyDisplay: moneyDisplayEntry,
  RadioGroup: radioGroupEntry,
  Slider: sliderEntry,
  FileUpload: fileUploadEntry,
  Combobox: comboboxEntry,
  Button: buttonEntry,
  // §13.3 Display
  Heading: headingEntry,
  MetricTile: metricTileEntry,
  Avatar: avatarEntry,
  // §13.4 Navigation
  NavLink: navLinkEntry,
  Breadcrumb: breadcrumbEntry,
  // §13.5 Layout (extended)
  Section: sectionEntry,
  Tabs: tabsEntry,
  TabPanel: tabPanelEntry,
  // §13.6 Data
  Table: tableEntry,
  // §13.7 Display (extended)
  Badge: badgeEntry,
  // §13.8 Feedback
  Alert: alertEntry,
  EmptyState: emptyStateEntry,
  // §13.9 Input (extended)
  Form: formEntry,
  IconButton: iconButtonEntry,
  // B1 — Layout extension
  Sidebar: sidebarEntry,
  Cluster: clusterEntry,
  Split: splitEntry,
  AppShell: appShellEntry,
  InspectorPanel: inspectorPanelEntry,
  TabPanelWithDeepLink: tabPanelWithDeepLinkEntry,
  // B2 — Data
  Chart: chartEntry,
  Sparkline: sparklineEntry,
  DataGrid: dataGridEntry,
  EditableLineGrid: editableLineGridEntry,
  Timeline: timelineEntry,
  TableSortable: tableSortableEntry,
  // B3 — Enterprise batch 2
  ApprovalStepper: approvalStepperEntry,
  PersonCard: personCardEntry,
  FilterBar: filterBarEntry,
  CommandPalette: commandPaletteEntry,
  ActivityFeed: activityFeedEntry,
  // B4 — Enterprise batch 3 + misc
  EmptyStateRich: emptyStateRichEntry,
  DateRangePicker: dateRangePickerEntry,
  MultiSelect: multiSelectEntry,
  FeatureCard: featureCardEntry,
  Skeleton: skeletonEntry,
  LoadingState: loadingStateEntry,
  KeyValueList: keyValueListEntry,
  // B5 — Input + motion
  Link: linkEntry,
  DatePicker: datePickerEntry,
  TimePicker: timePickerEntry,
  ColorPicker: colorPickerEntry,
  InputOTP: inputOtpEntry,
  Rating: ratingEntry,
  MaskedInput: maskedInputEntry,
  KeyValueInput: keyValueInputEntry,
  Gauge: gaugeEntry,
  SplitArc: splitArcEntry,
  Heatmap: heatmapEntry,
  Schematic: schematicEntry,
  Stepper: stepperEntry,
  Tag: tagEntry,
  Stat: statEntry,
  DescriptionList: descriptionListEntry,
  List: listEntry,
  SegmentedControl: segmentedControlEntry,
  Tree: treeEntry,
  Transfer: transferEntry,
  Cascader: cascaderEntry,
  Calendar: calendarEntry,
  Kanban: kanbanEntry,
  ResourceTimeline: resourceTimelineEntry,
  RichTextEditor: richTextEditorEntry,
  Carousel: carouselEntry,
  Lightbox: lightboxEntry,
  CodeBlock: codeBlockEntry,
  QRCode: qrCodeEntry,
  CameraCapture: cameraCaptureEntry,
  BarcodeScanner: barcodeScannerEntry,
  Scanner: scannerEntry,
  ValidationChecklist: validationChecklistEntry,
  FadeIn: fadeInEntry,
  Stagger: staggerEntry,
  // Flow primitives
  Repeat: repeatEntry,
  Conditional: conditionalEntry,
  DataBoundary: dataBoundaryEntry,
  Slot: slotEntry,
  // Wave 3 — feedback
  Progress: progressEntry,
  Spinner: spinnerEntry,
  Banner: bannerEntry,
  Redirect: redirectEntry,
  // Overlays
  Dialog: dialogEntry,
  DropdownMenu: dropdownMenuEntry,
  Popover: popoverEntry,
  Tooltip: tooltipEntry,
  Drawer: drawerEntry,
  ContextMenu: contextMenuEntry,
  HoverCard: hoverCardEntry,
  Menubar: menubarEntry,
  // Commerce
  AddToCart: addToCartEntry,
  CartBadge: cartBadgeEntry,
  CartPanel: cartPanelEntry,
  CartPage: cartPageEntry,
  // Spec C Slice 7 — interaction depth
  BulkActionBar: bulkActionBarEntry,
  SavedViewsPicker: savedViewsPickerEntry,
  GlobalSearch: globalSearchEntry,
  // SEARCH-3 — full-text search input + results pair, backed by op:"search".
  SearchInput: searchInputEntry,
  SearchResults: searchResultsEntry,
  KeyboardShortcuts: keyboardShortcutsEntry,
  // Spec C Slice 8 — dark-mode toggle
  ThemeToggle: themeToggleEntry,
  // Spec C Slice 9 — illustrated empty state
  IllustratedEmpty: illustratedEmptyEntry,
  // Spec E Wave 2 — accessibility focus primitives
  FocusTrap: focusTrapEntry,
  SkipLink: skipLinkEntry,
  FocusRing: focusRingEntry,
  AutoFocus: autoFocusEntry,
  // Spec E Wave 1 — advanced interactions
  UndoManager: undoManagerEntry,
  PresenceIndicator: presenceIndicatorEntry,
  OptimisticProvider: optimisticProviderEntry,
  // Spec E Wave 3 — advanced UX patterns
  Wizard: wizardEntry,
  SplitView: splitViewEntry,
  FilterBuilder: filterBuilderEntry,
  TourOverlay: tourOverlayEntry,
};

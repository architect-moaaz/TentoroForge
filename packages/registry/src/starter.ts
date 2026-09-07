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
    rowGap: {
      type: "enum",
      options: ["none", "xs", "sm", "md", "lg", "xl"],
      default: "md",
      control: "select",
      group: "style",
      description: "Vertical gap between rows.",
    },
    columnGap: {
      type: "enum",
      options: ["none", "xs", "sm", "md", "lg", "xl"],
      default: "md",
      control: "select",
      group: "style",
      description: "Horizontal gap between columns.",
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
      default: "stretch",
      control: "select",
      group: "style",
      description: "Align items in the block axis.",
    },
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
      description: "Form field name — the key this value submits under.",
    },
    label:            { type: "string",  default: "Amount", control: "text",    group: "content",  description: "Field label." },
    currency:         { type: "string",  default: "USD",    control: "text",    group: "content",  description: "3-letter ISO currency code (locked unless currencyEditable)." },
    currencyEditable: { type: "boolean", default: false,    control: "toggle",  group: "behavior", description: "Let the user pick the currency from a dropdown." },
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
  props: {},
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
      type: "string",
      default: "0",
      control: "text",
      group: "content",
      description: "Metric value (number or string).",
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
    target: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Target page ID or external URL.",
    },
    icon: {
      type: "string",
      default: "",
      control: "iconPicker",
      group: "content",
      description: "Optional leading icon name.",
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
      // the second brand hue. NOTE: `BadgeProps` in
      // packages/library/src/components/Badge/Badge.schema.ts is still a
      // five-value `.strict()` enum, so `accent` needs adding there (and on
      // BadgeNode) before it round-trips through validation cleanly.
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
      default: "",
      control: "color",
      group: "style",
      description: "CSS color or token path for the sparkline stroke.",
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
      default: "",
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
      default: null,
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
      default: 3,
      control: "number",
      group: "style",
      description: "Number of text lines to show (only when variant is text).",
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
      default: "",
      control: "text",
      group: "behavior",
      description: "Target page ID or absolute URL.",
    },
    workflow: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Optional workflow ID triggered on click (alongside or instead of navigate).",
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
    segments:      { type: "binding", default: null,                                                                                        control: "binding", group: "data",     description: "Data path to the segments array — each item {value, color, label, endLabel?, trend?}. In display order left→right along the arc." },
    total:         { type: "number",  default: 0,                                                                                          control: "number",  group: "behavior", description: "Optional normalisation total. 0/omitted → sum of segment values." },
    title:         { type: "string",  default: "Energy Balance Today",                                                                    control: "text",    group: "content",  description: "Title above the arc." },
    size:          { type: "number",  default: 220,                                                                                         control: "number",  group: "style",    description: "Diameter in px." },
    showLegend:    { type: "boolean", default: true,                                                                                        control: "toggle",  group: "content",  description: "Show the dot + label legend row." },
    showEndLabels: { type: "boolean", default: true,                                                                                        control: "toggle",  group: "content",  description: "Show endpoint values under the arc." },
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
    color:      { type: "string",  default: "var(--color-primary-500)", control: "text",   group: "style",   description: "Base cell colour." },
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
    orientation: { type: "enum",    default: "horizontal", control: "select", group: "style", options: ["horizontal", "vertical"], description: "Layout direction." },
    activeStep:  { type: "number",  default: 0,            control: "number", group: "state", description: "Active step index (derives status)." },
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
    variant:   { type: "enum",    default: "default",  control: "select", group: "style", options: ["default", "primary", "success", "warning", "danger"], description: "Visual style." },
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
    divided: { type: "boolean", default: true, control: "toggle",  group: "style", description: "Show dividers between items." },
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
    placeholder: { type: "string",  default: "Select…", control: "text",    group: "content", description: "Placeholder text." },
    bind:     { type: "binding", default: null,       control: "binding", group: "data",    description: "Data path to bind the selected path." },
  },
};

// ── Wave 5 — heavy composites ────────────────────────────────────────────

export const calendarEntry: RegistryEntry = {
  name: "Calendar",
  category: "input",
  icon: "Calendar",
  description: "Month-grid date picker.",
  slots: { type: "leaf" },
  props: {
    name: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
      description: "Form field name — the key this value submits under.",
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
    itemResourceField: { type: "string", default: "resourceId", control: "text", group: "data", description: "Item field holding the resource id." },
    startField: { type: "string", default: "start", control: "text", group: "data", description: "Item start-date field." },
    endField: { type: "string", default: "end", control: "text", group: "data", description: "Item end-date field." },
    titleField: { type: "string", default: "title", control: "text", group: "data", description: "Item bar label field." },
    statusField: { type: "string", default: null, control: "text", group: "data", description: "Item status field → bar colour + legend." },
    resourceGroupField: { type: "string", default: null, control: "text", group: "data", description: "Resource field to group rows under (room type, floor)." },
    days: { type: "number", default: 14, control: "number", group: "content", description: "Number of day columns." },
    itemHref: { type: "string", default: null, control: "text", group: "behavior", description: "Per-item deep link, e.g. /reservations/{id}." },
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
      description: "Form field name — the key this value submits under.",
    },
    label:   { type: "string",  default: "",       control: "text",    group: "content", description: "Field label." },
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
  },
};

export const lightboxEntry: RegistryEntry = {
  name: "Lightbox",
  category: "display",
  icon: "Image",
  description: "Thumbnail gallery with fullscreen viewer.",
  slots: { type: "leaf" },
  props: {
  },
};

export const codeBlockEntry: RegistryEntry = {
  name: "CodeBlock",
  category: "display",
  icon: "Code",
  description: "Monospace code block with copy button.",
  slots: { type: "leaf" },
  props: {
    code:     { type: "string",  default: "",   control: "textarea", group: "content",  description: "Code to display." },
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
    value:   { type: "string",  default: "",  control: "text",   group: "content", description: "Encoded value/URL." },
    size:    { type: "number",  default: 128, control: "number", group: "style",   description: "Pixel size." },
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
      default: "",
      control: "text",
      group: "content",
      // REQUIRED by the schema (`z.string().min(1)`) and previously exposed by
      // nothing, so every input the palette dropped was invalid the moment it
      // landed. `buildDroppedNode` seeds it so a fresh field is valid without
      // the user typing anything; this control is how they rename it.
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
    orientation: { type: "enum",    default: "vertical", control: "select", group: "style", options: ["vertical", "horizontal"], description: "Layout direction." },
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
    source: { type: "string", default: "", control: "text", group: "data",
      description: "Binding path of the array (e.g. 'requests'). Alias: top-level `bind`." },
    bind:   { type: "string", default: "", control: "text", group: "data",
      description: "Shorthand for source — top-level binding path." },
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
    when: { type: "string", default: "", control: "text", group: "data",
      description: "Expression evaluated against scope; truthy renders children." },
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
    to:    { type: "string", default: "/", control: "text", group: "content", description: "Destination route." },
    label: { type: "string", default: "",  control: "text", group: "content", description: "Note shown while redirecting." },
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
    selectedCount: { type: "number",  default: 0,    control: "number", group: "state",   description: "Number of selected rows (0 = component renders nothing)." },
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

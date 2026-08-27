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
    binding: {
      type: "binding",
      default: null,
      control: "binding",
      group: "data",
      description: "Data path to bind the input value.",
    },
    validation: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Validation rule expression.",
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
    binding: {
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
    label: {
      type: "string",
      default: "Label",
      control: "text",
      group: "content",
      description: "Visible field label.",
    },
    options: {
      type: "string",
      default: "",
      control: "textarea",
      group: "content",
      description: "Comma-separated option values or binding expression.",
    },
    binding: {
      type: "binding",
      default: null,
      control: "binding",
      group: "data",
      description: "Data path to bind the selected value.",
    },
    multiple: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Allow multiple selections.",
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
    label: {
      type: "string",
      default: "Check me",
      control: "text",
      group: "content",
      description: "Checkbox label text.",
    },
    binding: {
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
    label:   { type: "string",  default: "Enabled", control: "text",    group: "content",  description: "Switch label." },
    checked: { type: "boolean", default: false,     control: "toggle",  group: "state",    description: "On/off state." },
    binding: { type: "binding", default: null,      control: "binding", group: "data",     description: "Data path to bind the on/off state." },
  },
};

export const numberInputEntry: RegistryEntry = {
  name: "NumberInput",
  category: "input",
  icon: "Hash",
  description: "Numeric input with +/- steppers.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string",  default: "Quantity", control: "text",    group: "content",  description: "Field label." },
    min:     { type: "number",  default: 0,          control: "number",  group: "behavior", description: "Minimum value." },
    max:     { type: "number",  default: 100,        control: "number",  group: "behavior", description: "Maximum value." },
    step:    { type: "number",  default: 1,          control: "number",  group: "behavior", description: "Increment step." },
    binding: { type: "binding", default: null,       control: "binding", group: "data",     description: "Data path to bind the value." },
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
    label:            { type: "string",  default: "Amount", control: "text",    group: "content",  description: "Field label." },
    currency:         { type: "string",  default: "USD",    control: "text",    group: "content",  description: "3-letter ISO currency code (locked unless currencyEditable)." },
    currencyEditable: { type: "boolean", default: false,    control: "toggle",  group: "behavior", description: "Let the user pick the currency from a dropdown." },
    min:              { type: "number",  default: 0,        control: "number",  group: "behavior", description: "Minimum amount." },
    step:             { type: "number",  default: 0.01,     control: "number",  group: "behavior", description: "Amount increment (default 0.01 for cents)." },
    placeholder:      { type: "string",  default: "0.00",   control: "text",    group: "content",  description: "Empty-state amount placeholder." },
    binding:          { type: "binding", default: null,     control: "binding", group: "data",     description: "Data path to bind the amount." },
  },
};

export const moneyDisplayEntry: RegistryEntry = {
  name: "MoneyDisplay",
  category: "display",
  icon: "Coins",
  description: "Read-only, locale-aware formatted currency amount (tabular).",
  slots: { type: "leaf" },
  props: {
    currency:   { type: "string",  default: "USD",   control: "text",    group: "content",  description: "3-letter ISO currency code." },
    locale:     { type: "string",  default: "en-US", control: "text",    group: "content",  description: "BCP-47 locale (drives grouping + decimals)." },
    compact:    { type: "boolean", default: false,   control: "toggle",  group: "behavior", description: "Compact notation ($1.2M)." },
    showSymbol: { type: "boolean", default: true,    control: "toggle",  group: "behavior", description: "Show the currency symbol vs the 3-letter code." },
    align:      { type: "string",  default: "right", control: "select",  group: "style",    description: "Horizontal alignment.", options: ["left", "right"] },
    binding:    { type: "binding", default: null,    control: "binding", group: "data",     description: "Data path to the amount value." },
  },
};

export const radioGroupEntry: RegistryEntry = {
  name: "RadioGroup",
  category: "input",
  icon: "CircleDot",
  description: "Single-select radio option group.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string",  default: "Choose one", control: "text",    group: "content", description: "Group label." },
    binding: { type: "binding", default: null,         control: "binding", group: "data",    description: "Data path to bind the selected value." },
  },
};

export const sliderEntry: RegistryEntry = {
  name: "Slider", category: "input", icon: "SlidersHorizontal",
  description: "Numeric slider (single value or range).",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string",  default: "Value", control: "text",    group: "content",  description: "Slider label." },
    min:     { type: "number",  default: 0,       control: "number",  group: "behavior", description: "Minimum." },
    max:     { type: "number",  default: 100,     control: "number",  group: "behavior", description: "Maximum." },
    range:   { type: "boolean", default: false,   control: "toggle",  group: "behavior", description: "Two-thumb range mode." },
    binding: { type: "binding", default: null,    control: "binding", group: "data",     description: "Data path to bind the value." },
  },
};

export const fileUploadEntry: RegistryEntry = {
  name: "FileUpload", category: "input", icon: "Upload",
  description: "File upload dropzone (drag & drop + browse).",
  slots: { type: "leaf" },
  props: {
    label:    { type: "string",  default: "Upload file", control: "text",    group: "content",  description: "Field label." },
    accept:   { type: "string",  default: "",            control: "text",    group: "behavior", description: "Accepted MIME/extensions, e.g. image/*,.pdf." },
    multiple: { type: "boolean", default: false,         control: "toggle",  group: "behavior", description: "Allow multiple files." },
    binding:  { type: "binding", default: null,          control: "binding", group: "data",     description: "Data path to bind selected files." },
  },
};

export const comboboxEntry: RegistryEntry = {
  name: "Combobox", category: "input", icon: "ChevronsUpDown",
  description: "Typeahead select with filterable suggestions.",
  slots: { type: "leaf" },
  props: {
    label:       { type: "string",  default: "Select", control: "text",    group: "content",  description: "Field label." },
    placeholder: { type: "string",  default: "Search…", control: "text",   group: "content",  description: "Placeholder text." },
    binding:     { type: "binding", default: null,     control: "binding", group: "data",     description: "Data path to bind the selected value." },
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
  category: "layout",
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
      options: ["primary", "secondary", "ghost"],
      default: "primary",
      control: "select",
      group: "style",
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
      type: "action",
      default: [],
      control: "actionPicker",
      group: "behavior",
      description: "Array of CTA buttons (label + action).",
    },
    backgroundImage: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "style",
      description: "Background image with optional overlay opacity.",
    },
    media: {
      type: "action",
      default: null,
      control: "actionPicker",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "data",
      description: "Delta object { value, direction: up|down|flat }.",
    },
    trend: {
      type: "action",
      default: null,
      control: "actionPicker",
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
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Photo URL (Unsplash CDN or relative path).",
    },
    src: {
      type: "string",
      default: "",
      control: "text",
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
      options: ["online", "offline", "away", "busy"],
      default: "online",
      control: "select",
      group: "state",
      description: "Presence indicator. Omit to hide.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { label, href? } breadcrumb items.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { label, icon? } tab definitions — must match children count.",
    },
    value: {
      type: "string",
      default: "tab-0",
      control: "text",
      group: "state",
      description: "Active tab id (controlled).",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { key, label, width? } column definitions.",
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
      options: ["neutral", "primary", "success", "danger", "warning"],
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "behavior",
      description: "Optional CTA button { label, workflow }.",
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
  slots: {
    type: "list",
    accepts: ["Input", "Textarea", "Select", "Checkbox", "Button", "Heading"],
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Declarative field definitions (discriminated union).",
    },
    submitLabel: {
      type: "string",
      default: "Submit",
      control: "text",
      group: "content",
      description: "Label for the submit button (declarative mode).",
    },
    defaultValues: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "data",
      description: "Record of initial field values keyed by field name.",
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
      options: ["sm", "md", "lg"],
      default: "md",
      control: "select",
      group: "style",
      description: "Viewport breakpoint below which the layout stacks vertically.",
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
      control: "actionPicker",
      group: "content",
      description: "Schema sub-tree for the navigation sidebar.",
    },
    topbar: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Schema sub-tree for breadcrumb + user menu topbar.",
    },
    actions: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Schema sub-tree for page actions toolbar.",
    },
    rightRail: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Schema sub-tree for context sidebar (right rail).",
    },
  },
};

export const inspectorPanelEntry: RegistryEntry = {
  name: "InspectorPanel",
  category: "layout",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { id?, label } tab definitions — one child per tab.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "data",
      description: "Array of row objects or Mustache binding string ({{stats.series}}).",
    },
    xKey: {
      type: "string",
      default: "date",
      control: "text",
      group: "data",
      description: "Data key used for the X axis.",
    },
    series: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "data",
      description: "Array of { name, dataKey, color? } series definitions.",
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
      type: "action",
      default: null,
      control: "actionPicker",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { key, label, width?, sortable?, frozen?, align? } column defs.",
    },
    rows: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "data",
      description: "Array of row objects — keys must match column.key values.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "behavior",
      description: "Array of { label, action } row-level actions shown in an overflow menu.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { key, label, type?, options?, align?, width? } column defs. type: text|number|currency|select|readonly.",
    },
    rows: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "data",
      description: "Array of row objects keyed by column.key.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "data",
      description: "Object { auto, subtotal?, tax?, taxRate?, taxLabel?, total?, currency? } for the footer rollup. Set auto=true to derive from rows.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "data",
      description: "Array of { timestamp, title, actor?, status?, detail? } entries.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { key, label, width? } column definitions.",
    },
    caption: {
      type: "string",
      default: "",
      control: "text",
      group: "content",
      description: "Accessible table caption.",
    },
    onSort: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "behavior",
      description: "Callback { key, dir: asc|desc } triggered when a column header is clicked.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "data",
      description: "Array of { label, status, actor?, timestamp? } step objects.",
    },
    orientation: {
      type: "enum",
      options: ["horizontal", "vertical"],
      default: "horizontal",
      control: "select",
      group: "style",
      description: "Layout direction of the stepper.",
    },
    onStepClick: {
      type: "string",
      default: "",
      control: "text",
      group: "behavior",
      description: "Workflow ID triggered when a step is clicked (optional).",
    },
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
      control: "text",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { key, label, options: [{value,label}][] } filter chips.",
    },
    savedViews: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { label, filters } saved view presets.",
    },
    showSearch: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Show a free-text search field alongside the filter chips.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { label, group?, shortcut?, action } command items.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "data",
      description: "Array of { timestamp, actor, action, target, detail?, category? } entries or Mustache binding.",
    },
    title: {
      type: "string",
      default: "",
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
      default: 0,
      control: "number",
      group: "style",
      description: "Maximum height in px (0 = unconstrained).",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Illustration slot: URL string or { slug, alt?, tone? } object.",
    },
    primaryCta: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "behavior",
      description: "Primary CTA { label, action: navigate|workflow }.",
    },
    sampleDataLink: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "behavior",
      description: "Secondary link for loading sample data.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of preset labels to show (today, last-7-days, last-30-days, etc.).",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { value, label } option objects.",
    },
    selected: {
      type: "action",
      default: null,
      control: "actionPicker",
      group: "state",
      description: "Array of selected value strings (initial state).",
    },
    showSearch: {
      type: "boolean",
      default: false,
      control: "toggle",
      group: "behavior",
      description: "Show search field inside the dropdown.",
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
      default: "",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "behavior",
      description: "Optional CTA link { label, href }.",
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
      type: "action",
      default: null,
      control: "actionPicker",
      group: "content",
      description: "Array of { label, value, copyable? } item objects.",
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
    label:   { type: "string",  default: "Time", control: "text",    group: "content", description: "Field label." },
    binding: { type: "binding", default: null,   control: "binding", group: "data",    description: "Data path to bind the time value." },
  },
};

export const colorPickerEntry: RegistryEntry = {
  name: "ColorPicker",
  category: "input",
  icon: "Palette",
  description: "Color swatch picker with hex value.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string",  default: "Color", control: "text",    group: "content", description: "Field label." },
    binding: { type: "binding", default: null,    control: "binding", group: "data",    description: "Data path to bind the color value." },
  },
};

export const inputOtpEntry: RegistryEntry = {
  name: "InputOTP",
  category: "input",
  icon: "Hash",
  description: "Segmented one-time-code / PIN input.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string",  default: "Code", control: "text",    group: "content",  description: "Field label." },
    length:  { type: "number",  default: 6,      control: "number",  group: "behavior", description: "Number of digits." },
    binding: { type: "binding", default: null,   control: "binding", group: "data",     description: "Data path to bind the code." },
  },
};

export const ratingEntry: RegistryEntry = {
  name: "Rating",
  category: "input",
  icon: "Star",
  description: "Star rating input.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string",  default: "Rating", control: "text",    group: "content",  description: "Field label." },
    max:     { type: "number",  default: 5,        control: "number",  group: "behavior", description: "Number of stars." },
    binding: { type: "binding", default: null,     control: "binding", group: "data",     description: "Data path to bind the rating." },
  },
};

export const maskedInputEntry: RegistryEntry = {
  name: "MaskedInput",
  category: "input",
  icon: "TextCursorInput",
  description: "Pattern-masked text input (e.g. phone, ID).",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string",  default: "Field", control: "text",    group: "content",  description: "Field label." },
    mask:    { type: "string",  default: "###-####", control: "text",  group: "behavior", description: "Mask pattern (# = a digit)." },
    binding: { type: "binding", default: null,    control: "binding", group: "data",     description: "Data path to bind the value." },
  },
};

export const keyValueInputEntry: RegistryEntry = {
  name: "KeyValueInput",
  category: "input",
  icon: "ListPlus",
  description: "Editable key→value map for a jsonb / config column.",
  slots: { type: "leaf" },
  props: {
    label:       { type: "string",  default: "Configuration", control: "text",   group: "content",  description: "Field label." },
    description: { type: "string",  default: "",              control: "text",   group: "content",  description: "Helper text below the label." },
    valueType:   { type: "enum",    default: "text",          control: "select", group: "behavior", options: ["text", "number", "boolean"], description: "How each value is coerced." },
    binding:     { type: "binding", default: null,            control: "binding", group: "data",     description: "Data path to bind the object." },
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
    binding: { type: "binding", default: null,           control: "binding", group: "data",     description: "Data path to bind the value." },
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
    binding:       { type: "binding", default: null,                                                                                        control: "binding", group: "data",     description: "Data path to bind the segments array." },
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
    binding:    { type: "binding", default: null,        control: "binding", group: "data",    description: "Data path to bind the cells [{x,y,value}]." },
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
    binding:    { type: "binding", default: null,  control: "binding", group: "data",     description: "Data path to bind the markers array." },
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
    binding:     { type: "binding", default: null,        control: "binding", group: "data",  description: "Data path to bind the steps array." },
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
    binding:     { type: "binding", default: null,       control: "binding", group: "data",     description: "Data path to the items array." },
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
    binding: { type: "binding", default: null, control: "binding", group: "data",       description: "Data path to the items array." },
  },
};

export const segmentedControlEntry: RegistryEntry = {
  name: "SegmentedControl",
  category: "input",
  icon: "Columns",
  description: "Single-select segmented button group.",
  slots: { type: "leaf" },
  props: {
    label:   { type: "string",  default: "",   control: "text",    group: "content", description: "Field label." },
    binding: { type: "binding", default: null, control: "binding", group: "data",    description: "Data path to bind the selected value." },
  },
};

export const treeEntry: RegistryEntry = {
  name: "Tree",
  category: "display",
  icon: "FolderTree",
  description: "Hierarchical expandable tree view.",
  slots: { type: "leaf" },
  props: {
    binding: { type: "binding", default: null, control: "binding", group: "data", description: "Data path to the nested items array." },
  },
};

export const transferEntry: RegistryEntry = {
  name: "Transfer",
  category: "input",
  icon: "ArrowLeftRight",
  description: "Dual list-box to move items between two columns.",
  slots: { type: "leaf" },
  props: {
    binding: { type: "binding", default: null, control: "binding", group: "data", description: "Data path to bind the selected values." },
  },
};

export const cascaderEntry: RegistryEntry = {
  name: "Cascader",
  category: "input",
  icon: "ChevronsRight",
  description: "Cascading multi-level dropdown select.",
  slots: { type: "leaf" },
  props: {
    placeholder: { type: "string",  default: "Select…", control: "text",    group: "content", description: "Placeholder text." },
    binding:     { type: "binding", default: null,       control: "binding", group: "data",    description: "Data path to bind the selected path." },
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
    binding: { type: "binding", default: null, control: "binding", group: "data", description: "Data path to bind the selected date." },
  },
};

export const kanbanEntry: RegistryEntry = {
  name: "Kanban",
  category: "display",
  icon: "Trello",
  description: "Column board with movable cards.",
  slots: { type: "leaf" },
  props: {
    binding: { type: "binding", default: null, control: "binding", group: "data", description: "Data path to the columns array." },
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
    label:   { type: "string",  default: "",       control: "text",    group: "content", description: "Field label." },
    binding: { type: "binding", default: null,     control: "binding", group: "data",    description: "Data path to bind the HTML value." },
  },
};

export const carouselEntry: RegistryEntry = {
  name: "Carousel",
  category: "display",
  icon: "GalleryHorizontal",
  description: "Slideshow with prev/next and dots.",
  slots: { type: "leaf" },
  props: {
    binding: { type: "binding", default: null, control: "binding", group: "data", description: "Data path to the slides array." },
  },
};

export const lightboxEntry: RegistryEntry = {
  name: "Lightbox",
  category: "display",
  icon: "Image",
  description: "Thumbnail gallery with fullscreen viewer.",
  slots: { type: "leaf" },
  props: {
    binding: { type: "binding", default: null, control: "binding", group: "data", description: "Data path to the images array." },
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
    binding: { type: "binding", default: null, control: "binding", group: "data",  description: "Data path to bind the encoded value." },
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
    binding: { type: "binding", default: null,      control: "binding", group: "data",    description: "Data path to bind the decoded value." },
  },
};

export const cameraCaptureEntry: RegistryEntry = {
  name: "CameraCapture",
  category: "input",
  icon: "Camera",
  description: "Live webcam photo capture.",
  slots: { type: "leaf" },
  props: {
    label:        { type: "string",  default: "Capture Photo", control: "text",    group: "content", description: "Field label." },
    captureLabel: { type: "string",  default: "Capture Photo", control: "text",    group: "content", description: "Capture button text." },
    binding:      { type: "binding", default: null,            control: "binding", group: "data",    description: "Data path to bind the captured image." },
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
    binding:    { type: "binding", default: null,      control: "binding", group: "data",    description: "Data path to bind the scanned value." },
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
    binding:     { type: "binding", default: null,       control: "binding", group: "data",  description: "Data path to the items array." },
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
    entity:    { type: "string",  default: "",         control: "text",   group: "data",     description: "Entity name (e.g. \"Plant\")." },
    itemId:    { type: "string",  default: "",         control: "text",   group: "data",     description: "Row id of the item being added." },
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
    actions:       { type: "string",  default: "",   control: "text",   group: "content", description: "Array of {label, workflow, variant?} action buttons (JSON)." },
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
    views:            { type: "string", default: "",   control: "text",   group: "content", description: "Array of {id, label, isDefault?} view entries." },
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
    workflow:    { type: "string", default: "",        control: "text",   group: "behavior", description: "Workflow name to fire with { query } on submit." },
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
    endpoint:    { type: "string", default: "",        control: "text",   group: "behavior", description: "URL that resolves op:\"search\" and returns SearchHit[]." },
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
    shortcuts:  { type: "string", default: "",  control: "text", group: "content",  description: "Array of {keys, label, group?} shortcut entries (JSON)." },
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
    steps:        { type: "string",  default: "",     control: "text",   group: "content",  description: "Array of {id, title, fields[], nextIf?} step defs (JSON)." },
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
  slots: { type: "list" },
  props: {
    syncKey:     { type: "string",  default: "selected", control: "text",   group: "behavior", description: "URL query key used to sync the selected id." },
    masterWidth: { type: "number",  default: 320,        control: "number", group: "style",    description: "Fixed pixel width for the master column." },
    emptyText:   { type: "string",  default: "Select an item to see details.", control: "text", group: "content", description: "Empty-state text for when nothing is selected." },
    responsive:  { type: "boolean", default: true,       control: "toggle", group: "style",    description: "Hides the master column on narrow viewports when true." },
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
    fields:          { type: "string",  default: "",       control: "text",   group: "content",  description: "Array of {name, type, operators?, options?} field defs (JSON)." },
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

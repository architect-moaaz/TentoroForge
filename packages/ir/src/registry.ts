/**
 * Node Registry — defines the valid props, slots, and categories for all IR node types.
 *
 * The compiler, validator, and UI editor all import this registry.
 */

// ---------------------------------------------------------------------------
// Prop type definitions
// ---------------------------------------------------------------------------

export type PropType =
  | "string"
  | "number"
  | "boolean"
  | "token:spacing"
  | "token:color"
  | "token:radius"
  | "token:typography"
  | "enum"
  | "icon"
  | "binding"
  | "action"
  | "node"
  | "node[]"
  | "columns"
  | "options"
  | "validation"
  | "responsive:number"
  | "responsive:spacing"
  | "responsive:direction"
  | "padding"
  | "colorMap"
  | "any";

export interface PropSpec {
  name: string;
  type: PropType;
  required?: boolean;
  default?: unknown;
  values?: string[]; // for enum type
  description?: string;
}

export type NodeCategory = "layout" | "content" | "input" | "composite" | "control" | "escape";

export interface ChildSlot {
  name: string;
  type: "any" | "any[]" | "typed";
  acceptedTypes?: string[]; // for typed slots
  required?: boolean;
}

export interface NodeSpec {
  type: string;
  category: NodeCategory;
  description: string;
  props: PropSpec[];
  slots: ChildSlot[];
  /** Whether this node can accept children in its main slot */
  hasChildren: boolean;
  /** Icon name for UI editor */
  icon: string;
}

// ---------------------------------------------------------------------------
// Common prop groups (reused across node specs)
// ---------------------------------------------------------------------------

const BASE_PROPS: PropSpec[] = [
  { name: "visible", type: "binding", description: "Condition expression for visibility" },
  { name: "if", type: "binding", description: "Condition for rendering (Slot context)" },
  { name: "margin", type: "padding", description: "Outer spacing" },
];

const LAYOUT_PROPS: PropSpec[] = [
  { name: "gap", type: "responsive:spacing", description: "Gap between children" },
  { name: "padding", type: "padding", description: "Inner spacing" },
  { name: "align", type: "enum", values: ["start", "center", "end", "stretch"] },
  { name: "justify", type: "enum", values: ["start", "center", "end", "between", "around"] },
  { name: "width", type: "string" },
  { name: "height", type: "string" },
  { name: "flex", type: "number" },
  { name: "scroll", type: "boolean" },
  { name: "wrap", type: "boolean" },
];

const INPUT_BASE_PROPS: PropSpec[] = [
  { name: "bind", type: "binding", required: true, description: "State or form binding path" },
  { name: "label", type: "string" },
  { name: "placeholder", type: "string" },
  { name: "required", type: "boolean" },
  { name: "disabled", type: "binding" },
  { name: "error", type: "binding" },
  { name: "hint", type: "string" },
  { name: "size", type: "enum", values: ["sm", "md", "lg"], default: "md" },
];

// ---------------------------------------------------------------------------
// Node specifications
// ---------------------------------------------------------------------------

const NODE_SPECS: NodeSpec[] = [
  // ── Layout ──
  {
    type: "Stack",
    category: "layout",
    description: "Vertical flex container",
    icon: "rows-3",
    hasChildren: true,
    props: [...BASE_PROPS, ...LAYOUT_PROPS],
    slots: [{ name: "children", type: "any[]", required: true }],
  },
  {
    type: "Row",
    category: "layout",
    description: "Horizontal flex container",
    icon: "columns-3",
    hasChildren: true,
    props: [
      ...BASE_PROPS,
      ...LAYOUT_PROPS,
      { name: "direction", type: "responsive:direction", description: "Can flip to column on small screens" },
    ],
    slots: [{ name: "children", type: "any[]", required: true }],
  },
  {
    type: "Grid",
    category: "layout",
    description: "CSS grid container",
    icon: "layout-grid",
    hasChildren: true,
    props: [
      ...BASE_PROPS,
      { name: "columns", type: "responsive:number", required: true },
      { name: "gap", type: "responsive:spacing" },
      { name: "padding", type: "padding" },
      { name: "width", type: "string" },
      { name: "height", type: "string" },
    ],
    slots: [{ name: "children", type: "any[]", required: true }],
  },
  {
    type: "Spacer",
    category: "layout",
    description: "Explicit vertical gap",
    icon: "space",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "size", type: "token:spacing", required: true },
    ],
    slots: [],
  },
  {
    type: "Divider",
    category: "layout",
    description: "Horizontal or vertical rule",
    icon: "minus",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "direction", type: "enum", values: ["horizontal", "vertical"], default: "horizontal" },
      { name: "label", type: "string" },
    ],
    slots: [],
  },

  // ── Content ──
  {
    type: "Text",
    category: "content",
    description: "Text display — headings, body, captions",
    icon: "type",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "content", type: "string", required: true },
      { name: "typography", type: "token:typography", default: "body" },
      { name: "weight", type: "enum", values: ["normal", "medium", "semibold", "bold"] },
      { name: "color", type: "token:color" },
      { name: "align", type: "enum", values: ["left", "center", "right"] },
      { name: "truncate", type: "number" },
      { name: "monospace", type: "boolean" },
    ],
    slots: [],
  },
  {
    type: "Icon",
    category: "content",
    description: "Lucide icon",
    icon: "star",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "name", type: "icon", required: true },
      { name: "size", type: "enum", values: ["xs", "sm", "md", "lg", "xl"], default: "md" },
      { name: "color", type: "token:color" },
    ],
    slots: [],
  },
  {
    type: "Image",
    category: "content",
    description: "Image display",
    icon: "image",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "src", type: "string", required: true },
      { name: "alt", type: "string", required: true },
      { name: "width", type: "string" },
      { name: "height", type: "string" },
      { name: "aspect", type: "string" },
      { name: "fit", type: "enum", values: ["cover", "contain", "fill"] },
      { name: "radius", type: "token:radius" },
      { name: "fallback", type: "string" },
    ],
    slots: [],
  },
  {
    type: "Avatar",
    category: "content",
    description: "User avatar with fallback initials",
    icon: "circle-user",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "src", type: "string" },
      { name: "name", type: "string" },
      { name: "size", type: "enum", values: ["xs", "sm", "md", "lg", "xl"], default: "md" },
      { name: "shape", type: "enum", values: ["circle", "rounded"], default: "circle" },
      { name: "status", type: "enum", values: ["online", "offline", "busy", "none"] },
    ],
    slots: [],
  },
  {
    type: "Badge",
    category: "content",
    description: "Status badge with optional color mapping",
    icon: "tag",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "content", type: "string", required: true },
      { name: "variant", type: "enum", values: ["default", "primary", "success", "warning", "danger", "outline"] },
      { name: "colorMap", type: "colorMap" },
      { name: "size", type: "enum", values: ["sm", "md"], default: "md" },
      { name: "icon", type: "icon" },
      { name: "dot", type: "boolean" },
    ],
    slots: [],
  },
  {
    type: "Tag",
    category: "content",
    description: "Removable tag/chip",
    icon: "hash",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "content", type: "string", required: true },
      { name: "removable", type: "boolean" },
      { name: "onRemove", type: "action" },
      { name: "variant", type: "enum", values: ["default", "outline"] },
      { name: "color", type: "token:color" },
    ],
    slots: [],
  },
  {
    type: "Button",
    category: "content",
    description: "Clickable button with label and optional icon",
    icon: "mouse-pointer-click",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "label", type: "string", required: true },
      { name: "variant", type: "enum", values: ["primary", "secondary", "ghost", "outline", "danger", "link"], default: "primary" },
      { name: "size", type: "enum", values: ["sm", "md", "lg"], default: "md" },
      { name: "icon", type: "icon" },
      { name: "iconPosition", type: "enum", values: ["left", "right"], default: "left" },
      { name: "disabled", type: "binding" },
      { name: "loading", type: "binding" },
      { name: "width", type: "string" },
      { name: "action", type: "action" },
      { name: "submit", type: "boolean" },
    ],
    slots: [],
  },
  {
    type: "StatCard",
    category: "content",
    description: "KPI card with value, trend, and optional action",
    icon: "bar-chart-3",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "label", type: "string", required: true },
      { name: "value", type: "binding", required: true },
      { name: "format", type: "enum", values: ["number", "currency", "percent", "compact"] },
      { name: "trend", type: "binding" },
      { name: "trendDirection", type: "enum", values: ["up-good", "down-good"] },
      { name: "icon", type: "icon" },
      { name: "action", type: "action" },
    ],
    slots: [],
  },
  {
    type: "EmptyState",
    category: "content",
    description: "Placeholder for empty collections",
    icon: "inbox",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "icon", type: "icon" },
      { name: "title", type: "string" },
      { name: "message", type: "string", required: true },
      { name: "action", type: "any" },
      { name: "secondary", type: "any" },
    ],
    slots: [],
  },
  {
    type: "Skeleton",
    category: "content",
    description: "Loading placeholder",
    icon: "loader",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "variant", type: "enum", values: ["text", "card", "table", "avatar"], default: "text" },
      { name: "lines", type: "number", default: 3 },
      { name: "repeat", type: "number", default: 1 },
    ],
    slots: [],
  },

  // ── Inputs ──
  {
    type: "TextInput",
    category: "input",
    description: "Single-line text input",
    icon: "text-cursor-input",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      ...INPUT_BASE_PROPS,
      { name: "type", type: "enum", values: ["text", "email", "url", "tel", "number", "password"], default: "text" },
      { name: "icon", type: "icon" },
      { name: "suffix", type: "string" },
      { name: "debounce", type: "number" },
      { name: "maxLength", type: "number" },
      { name: "clearable", type: "boolean" },
    ],
    slots: [],
  },
  {
    type: "TextArea",
    category: "input",
    description: "Multi-line text input",
    icon: "align-left",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      ...INPUT_BASE_PROPS,
      { name: "rows", type: "number", default: 3 },
      { name: "maxLength", type: "number" },
      { name: "resize", type: "enum", values: ["none", "vertical", "auto"], default: "vertical" },
    ],
    slots: [],
  },
  {
    type: "Select",
    category: "input",
    description: "Dropdown select",
    icon: "chevron-down-square",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      ...INPUT_BASE_PROPS,
      { name: "options", type: "options", required: true },
      { name: "multiple", type: "boolean" },
      { name: "searchable", type: "boolean" },
      { name: "clearable", type: "boolean" },
      { name: "groupBy", type: "string" },
    ],
    slots: [],
  },
  {
    type: "Checkbox",
    category: "input",
    description: "Checkbox with label",
    icon: "check-square",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      ...INPUT_BASE_PROPS,
      { name: "description", type: "string" },
    ],
    slots: [],
  },
  {
    type: "Toggle",
    category: "input",
    description: "Toggle switch",
    icon: "toggle-right",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      ...INPUT_BASE_PROPS,
      { name: "description", type: "string" },
    ],
    slots: [],
  },
  {
    type: "RadioGroup",
    category: "input",
    description: "Radio button group",
    icon: "circle-dot",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      ...INPUT_BASE_PROPS,
      { name: "options", type: "options", required: true },
      { name: "direction", type: "enum", values: ["row", "col"], default: "col" },
      { name: "variant", type: "enum", values: ["default", "card"], default: "default" },
    ],
    slots: [],
  },
  {
    type: "DatePicker",
    category: "input",
    description: "Date/time picker",
    icon: "calendar",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      ...INPUT_BASE_PROPS,
      { name: "mode", type: "enum", values: ["single", "range"], default: "single" },
      { name: "min", type: "string" },
      { name: "max", type: "string" },
      { name: "format", type: "string" },
      { name: "includeTime", type: "boolean" },
      { name: "presets", type: "any" },
    ],
    slots: [],
  },
  {
    type: "FilePicker",
    category: "input",
    description: "File upload input",
    icon: "upload",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      ...INPUT_BASE_PROPS,
      { name: "accept", type: "string" },
      { name: "maxSize", type: "number" },
      { name: "multiple", type: "boolean" },
      { name: "endpoint", type: "string" },
      { name: "preview", type: "boolean" },
    ],
    slots: [],
  },
  {
    type: "RichTextEditor",
    category: "input",
    description: "Rich text / WYSIWYG editor",
    icon: "file-text",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      ...INPUT_BASE_PROPS,
      { name: "toolbar", type: "enum", values: ["minimal", "standard", "full"], default: "standard" },
    ],
    slots: [],
  },
  {
    type: "Slider",
    category: "input",
    description: "Range slider",
    icon: "sliders-horizontal",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      ...INPUT_BASE_PROPS,
      { name: "min", type: "number", required: true },
      { name: "max", type: "number", required: true },
      { name: "step", type: "number", default: 1 },
      { name: "showValue", type: "boolean" },
      { name: "marks", type: "any" },
    ],
    slots: [],
  },
  {
    type: "ColorPicker",
    category: "input",
    description: "Color picker",
    icon: "palette",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      ...INPUT_BASE_PROPS,
      { name: "format", type: "enum", values: ["hex", "rgb", "hsl"], default: "hex" },
      { name: "presets", type: "any" },
      { name: "alpha", type: "boolean" },
    ],
    slots: [],
  },

  // ── Composites ──
  {
    type: "DataTable",
    category: "composite",
    description: "Data table with sorting, pagination, and actions",
    icon: "table",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "data", type: "binding", required: true },
      { name: "rowKey", type: "string", default: "id" },
      { name: "columns", type: "columns", required: true },
      { name: "pagination", type: "any" },
      { name: "sorting", type: "any" },
      { name: "filtering", type: "boolean" },
      { name: "selection", type: "enum", values: ["none", "single", "multiple"], default: "none" },
      { name: "density", type: "enum", values: ["compact", "default", "comfortable"], default: "default" },
      { name: "stickyHeader", type: "boolean" },
      { name: "onRowClick", type: "action" },
      { name: "rowActions", type: "any" },
      { name: "bulkActions", type: "any" },
    ],
    slots: [
      { name: "emptyState", type: "any" },
      { name: "expandable", type: "any" },
    ],
  },
  {
    type: "Form",
    category: "composite",
    description: "Form with validation and submit handling",
    icon: "file-input",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "bind", type: "binding", required: true },
      { name: "onSubmit", type: "action", required: true },
      { name: "layout", type: "enum", values: ["auto", "single-column", "two-column", "sectioned"], default: "auto" },
      { name: "fields", type: "any" },
      { name: "sections", type: "any" },
      { name: "resetOnSubmit", type: "boolean" },
      { name: "confirmUnsaved", type: "boolean" },
    ],
    slots: [{ name: "actions", type: "any[]" }],
  },
  {
    type: "Card",
    category: "composite",
    description: "Card container with header, body, footer",
    icon: "square",
    hasChildren: true,
    props: [
      ...BASE_PROPS,
      { name: "padding", type: "token:spacing", default: "md" },
      { name: "radius", type: "token:radius", default: "md" },
      { name: "shadow", type: "enum", values: ["none", "sm", "md"], default: "sm" },
      { name: "border", type: "boolean", default: true },
      { name: "hoverable", type: "boolean" },
      { name: "selected", type: "binding" },
      { name: "action", type: "action" },
    ],
    slots: [
      { name: "header", type: "any" },
      { name: "media", type: "any" },
      { name: "children", type: "any[]" },
      { name: "footer", type: "any" },
    ],
  },
  {
    type: "Tabs",
    category: "composite",
    description: "Tab container with multiple panels",
    icon: "panel-top",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "defaultTab", type: "string" },
      { name: "variant", type: "enum", values: ["underline", "pills", "enclosed"], default: "underline" },
      { name: "tabs", type: "any", required: true },
    ],
    slots: [],
  },
  {
    type: "ModalTrigger",
    category: "composite",
    description: "Triggers a modal dialog",
    icon: "panel-top-open",
    hasChildren: true,
    props: [
      ...BASE_PROPS,
      { name: "modal", type: "string", required: true },
    ],
    slots: [{ name: "children", type: "any[]", required: true }],
  },
  {
    type: "Accordion",
    category: "composite",
    description: "Collapsible sections",
    icon: "chevrons-down-up",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "type", type: "enum", values: ["single", "multiple"], default: "single" },
      { name: "items", type: "any", required: true },
    ],
    slots: [],
  },
  {
    type: "Chart",
    category: "composite",
    description: "Data visualization chart",
    icon: "bar-chart-3",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "type", type: "enum", values: ["bar", "line", "area", "pie", "donut", "scatter", "horizontal-bar"], required: true },
      { name: "data", type: "binding", required: true },
      { name: "xAxis", type: "any" },
      { name: "yAxis", type: "any" },
      { name: "series", type: "any" },
      { name: "colors", type: "any" },
      { name: "legend", type: "boolean", default: true },
      { name: "tooltip", type: "boolean", default: true },
      { name: "height", type: "string", default: "300" },
    ],
    slots: [],
  },

  // ── Control Flow ──
  {
    type: "Slot",
    category: "control",
    description: "Conditional rendering (if/else or switch/cases)",
    icon: "git-branch",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "switch", type: "binding" },
      { name: "cases", type: "any" },
      { name: "then", type: "node" },
      { name: "else", type: "node" },
    ],
    slots: [],
  },
  {
    type: "Repeater",
    category: "control",
    description: "Loop over data, render template per item",
    icon: "repeat",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "data", type: "binding", required: true },
      { name: "itemKey", type: "string", default: "id" },
      { name: "direction", type: "enum", values: ["vertical", "horizontal", "grid"], default: "vertical" },
      { name: "gap", type: "token:spacing" },
      { name: "columns", type: "responsive:number" },
      { name: "limit", type: "number" },
    ],
    slots: [
      { name: "template", type: "any", required: true },
      { name: "emptyState", type: "any" },
    ],
  },
  {
    type: "AsyncSlot",
    category: "control",
    description: "Renders children when async data loads",
    icon: "cloud-download",
    hasChildren: true,
    props: [
      ...BASE_PROPS,
      { name: "data", type: "binding", required: true },
      { name: "params", type: "any" },
    ],
    slots: [
      { name: "loading", type: "any" },
      { name: "error", type: "any" },
      { name: "children", type: "any[]", required: true },
    ],
  },

  // ── Escape Hatch ──
  {
    type: "Custom",
    category: "escape",
    description: "Raw code component (escape hatch)",
    icon: "code",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "code", type: "string", required: true },
      { name: "imports", type: "any" },
      { name: "props", type: "any" },
    ],
    slots: [],
  },

  // ── Fragment Reference ──
  {
    type: "FragmentRef",
    category: "control",
    description: "Reference to a reusable fragment",
    icon: "puzzle",
    hasChildren: false,
    props: [
      ...BASE_PROPS,
      { name: "$ref", type: "string", required: true },
    ],
    slots: [],
  },
];

// ---------------------------------------------------------------------------
// Registry access
// ---------------------------------------------------------------------------

/** Map of node type → spec for O(1) lookup */
const REGISTRY_MAP = new Map<string, NodeSpec>();
for (const spec of NODE_SPECS) {
  REGISTRY_MAP.set(spec.type, spec);
}

/** Get the spec for a node type. Returns undefined if unknown. */
export function getNodeSpec(nodeType: string): NodeSpec | undefined {
  return REGISTRY_MAP.get(nodeType);
}

/** Get all registered node types */
export function getAllNodeTypes(): string[] {
  return NODE_SPECS.map((s) => s.type);
}

/** Get node types by category */
export function getNodeTypesByCategory(category: NodeCategory): NodeSpec[] {
  return NODE_SPECS.filter((s) => s.category === category);
}

/** Check if a node type exists */
export function isValidNodeType(nodeType: string): boolean {
  return REGISTRY_MAP.has(nodeType);
}

/** Check if a prop is valid for a given node type */
export function isValidProp(nodeType: string, propName: string): boolean {
  const spec = REGISTRY_MAP.get(nodeType);
  if (!spec) return false;
  return spec.props.some((p) => p.name === propName);
}

/** Get all required props for a node type */
export function getRequiredProps(nodeType: string): PropSpec[] {
  const spec = REGISTRY_MAP.get(nodeType);
  if (!spec) return [];
  return spec.props.filter((p) => p.required);
}

/** Get the full list of node specs */
export function getAllNodeSpecs(): readonly NodeSpec[] {
  return NODE_SPECS;
}

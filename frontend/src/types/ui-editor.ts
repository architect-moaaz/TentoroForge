// ---------------------------------------------------------------------------
// GrapesJS Component Categories
// ---------------------------------------------------------------------------

export type ComponentCategory =
  | "layout"
  | "display"
  | "navigation"
  | "form"
  | "data"
  | "media";

// ---------------------------------------------------------------------------
// Component Type Registry
// ---------------------------------------------------------------------------

export interface ComponentTypeInfo {
  type: string;
  label: string;
  category: ComponentCategory;
  icon?: string;
  defaultContent?: string;
  traits?: TraitDefinition[];
}

export interface TraitDefinition {
  name: string;
  label: string;
  type: "text" | "number" | "checkbox" | "select" | "color" | "button";
  options?: { id: string; name: string }[];
  default?: string | number | boolean;
  placeholder?: string;
}

// ---------------------------------------------------------------------------
// Layout Component Types
// ---------------------------------------------------------------------------

export const LAYOUT_COMPONENTS: ComponentTypeInfo[] = [
  { type: "container", label: "Container", category: "layout" },
  { type: "grid", label: "Grid", category: "layout" },
  { type: "flex-row", label: "Row (Flex)", category: "layout" },
  { type: "flex-col", label: "Column (Flex)", category: "layout" },
  { type: "card", label: "Card", category: "layout" },
  { type: "tabs-container", label: "Tabs", category: "layout" },
  { type: "sidebar-layout", label: "Sidebar Layout", category: "layout" },
  { type: "header", label: "Header", category: "layout" },
  { type: "footer", label: "Footer", category: "layout" },
  { type: "section", label: "Section", category: "layout" },
  { type: "divider", label: "Divider", category: "layout" },
];

// ---------------------------------------------------------------------------
// Display Component Types
// ---------------------------------------------------------------------------

export const DISPLAY_COMPONENTS: ComponentTypeInfo[] = [
  { type: "heading", label: "Heading", category: "display" },
  { type: "text-block", label: "Text", category: "display" },
  { type: "image", label: "Image", category: "display" },
  { type: "badge", label: "Badge", category: "display" },
  { type: "avatar", label: "Avatar", category: "display" },
  { type: "alert", label: "Alert", category: "display" },
  { type: "table-display", label: "Table", category: "display" },
  { type: "data-table", label: "Data Table", category: "display" },
  { type: "chart", label: "Chart", category: "display" },
  { type: "separator", label: "Separator", category: "display" },
  { type: "accordion", label: "Accordion", category: "display" },
  { type: "tooltip", label: "Tooltip", category: "display" },
  { type: "progress-bar", label: "Progress Bar", category: "display" },
  { type: "skeleton", label: "Skeleton", category: "display" },
  { type: "stat-card", label: "Stat Card", category: "display" },
  { type: "icon", label: "Icon", category: "display" },
];

// ---------------------------------------------------------------------------
// Navigation Component Types
// ---------------------------------------------------------------------------

export const NAVIGATION_COMPONENTS: ComponentTypeInfo[] = [
  { type: "button", label: "Button", category: "navigation" },
  { type: "link", label: "Link", category: "navigation" },
  { type: "breadcrumb", label: "Breadcrumb", category: "navigation" },
  { type: "navbar", label: "Navbar", category: "navigation" },
  { type: "dropdown-menu", label: "Dropdown Menu", category: "navigation" },
  { type: "pagination", label: "Pagination", category: "navigation" },
  { type: "tabs-nav", label: "Tab Navigation", category: "navigation" },
];

// ---------------------------------------------------------------------------
// Form Component Types
// ---------------------------------------------------------------------------

export const FORM_COMPONENTS: ComponentTypeInfo[] = [
  { type: "form", label: "Form", category: "form" },
  { type: "form-field", label: "Form Field", category: "form" },
  { type: "label", label: "Label", category: "form" },
  { type: "text-input", label: "Text Input", category: "form" },
  { type: "textarea", label: "Text Area", category: "form" },
  { type: "rich-text", label: "Rich Text", category: "form" },
  { type: "email-input", label: "Email Input", category: "form" },
  { type: "url-input", label: "URL Input", category: "form" },
  { type: "phone-input", label: "Phone Input", category: "form" },
  { type: "password-input", label: "Password Input", category: "form" },
  { type: "number-input", label: "Number Input", category: "form" },
  { type: "select", label: "Select", category: "form" },
  { type: "combobox", label: "Combobox", category: "form" },
  { type: "checkbox", label: "Checkbox", category: "form" },
  { type: "radio-group", label: "Radio Group", category: "form" },
  { type: "switch", label: "Switch", category: "form" },
  { type: "date-picker", label: "Date Picker", category: "form" },
  { type: "time-picker", label: "Time Picker", category: "form" },
  { type: "slider", label: "Slider", category: "form" },
  { type: "file-upload", label: "File Upload", category: "form" },
  { type: "color-picker", label: "Color Picker", category: "form" },
  { type: "signature", label: "Signature", category: "form" },
  { type: "code-editor", label: "Code Editor", category: "form" },
  { type: "search-input", label: "Search Input", category: "form" },
  { type: "tags-input", label: "Tags Input", category: "form" },
];

// ---------------------------------------------------------------------------
// All component types combined
// ---------------------------------------------------------------------------

export const ALL_COMPONENT_TYPES: ComponentTypeInfo[] = [
  ...LAYOUT_COMPONENTS,
  ...DISPLAY_COMPONENTS,
  ...NAVIGATION_COMPONENTS,
  ...FORM_COMPONENTS,
];

export const COMPONENT_CATEGORIES = [
  { id: "layout" as ComponentCategory, label: "Layout", components: LAYOUT_COMPONENTS },
  { id: "display" as ComponentCategory, label: "Display", components: DISPLAY_COMPONENTS },
  { id: "navigation" as ComponentCategory, label: "Navigation", components: NAVIGATION_COMPONENTS },
  { id: "form" as ComponentCategory, label: "Form", components: FORM_COMPONENTS },
];

// ---------------------------------------------------------------------------
// Page Definition
// ---------------------------------------------------------------------------

export interface PageDefinition {
  id: string;
  name: string;
  route: string;
  html: string;
  css: string;
  dataBindings?: DataBinding[];
}

export interface DataBinding {
  componentId: string;
  field: string;
  modelName: string;
  fieldName: string;
  bindingType: "display" | "input" | "list" | "conditional";
}

// ---------------------------------------------------------------------------
// UI Editor State
// ---------------------------------------------------------------------------

export interface UIEditorConfig {
  pages: PageDefinition[];
  globalCss?: string;
  theme?: Record<string, string>;
}

// ---------------------------------------------------------------------------
// Device Preview
// ---------------------------------------------------------------------------

export type DeviceType = "desktop" | "tablet" | "mobile";

export interface DevicePreset {
  type: DeviceType;
  label: string;
  width: string;
}

export const DEVICE_PRESETS: DevicePreset[] = [
  { type: "desktop", label: "Desktop", width: "100%" },
  { type: "tablet", label: "Tablet", width: "768px" },
  { type: "mobile", label: "Mobile", width: "375px" },
];

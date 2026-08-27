/**
 * Tentoro Forge IR (Intermediate Representation) Type Definitions
 *
 * The IR is a structured JSON format that describes UI pages.
 * It compiles deterministically to React/TSX + Tailwind code.
 */

// ---------------------------------------------------------------------------
// Top-level manifest
// ---------------------------------------------------------------------------

export interface AppIR {
  $schema: "tentoroforge/ir/1.0";
  app: {
    name: string;
    theme?: string;
  };
  tokens: TokenMap;
  dataSources: Record<string, DataSourceDef>;
  pages: PageIR[];
  fragments?: Record<string, FragmentDef>;
  navigation?: NavigationDef;
  /** User/domain context passed through for layout decisions */
  userContext?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Tokens — design system bridge
// ---------------------------------------------------------------------------

export type SpacingToken = "xs" | "sm" | "md" | "lg" | "xl" | "2xl";
export type ColorToken =
  | "primary"
  | "secondary"
  | "danger"
  | "warning"
  | "success"
  | "muted"
  | "default"
  | "surface"
  | "surface-alt";
export type RadiusToken = "none" | "sm" | "md" | "lg" | "full";
export type TypographyToken =
  | "heading-1"
  | "heading-2"
  | "heading-3"
  | "body"
  | "body-sm"
  | "caption"
  | "overline";

export interface TypographyDef {
  size: string;
  weight: string;
  tracking?: string;
  color?: string;
}

export interface TokenMap {
  color?: Record<string, string>;
  spacing?: Record<SpacingToken, string>;
  radius?: Record<RadiusToken, string>;
  typography?: Record<TypographyToken, TypographyDef>;
}

// ---------------------------------------------------------------------------
// Data Sources
// ---------------------------------------------------------------------------

export interface DataSourceDef {
  type: "rest";
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  params?: Record<string, DataSourceParam>;
  body?: { from: string };
  shape?: Record<string, string>;
  refresh?: "on-focus" | "on-interval" | "manual";
  cache?: "none" | "session" | "persistent";
  onSuccess?: DataSourceEffect;
  onError?: DataSourceEffect;
}

export interface DataSourceParam {
  type: "string" | "number" | "boolean";
  from?: string; // binding expression
  default?: string | number | boolean;
}

export interface DataSourceEffect {
  invalidate?: string[];
  action?: string; // shorthand action string
}

// ---------------------------------------------------------------------------
// Pages
// ---------------------------------------------------------------------------

export interface PageIR {
  $id: string;
  route: string;
  title?: string;
  auth?: PageAuth;
  state?: Record<string, StateFieldDef>;
  root: IRNode;
  modals?: Record<string, ModalDef>;
}

export interface PageAuth {
  required: boolean;
  roles?: string[];
}

export type StateFieldDef = string | number | boolean | null | string[] | Record<string, unknown>;

export interface ModalDef {
  title: string;
  description?: string;
  size?: "sm" | "md" | "lg" | "xl" | "full";
  body: IRNode;
  footer?: IRNode;
}

// ---------------------------------------------------------------------------
// Fragments — reusable node subtrees
// ---------------------------------------------------------------------------

export interface FragmentDef {
  props?: string[];
  root: IRNode;
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

export interface NavigationDef {
  items: NavItem[];
}

export interface NavItem {
  label: string;
  icon?: string;
  route?: string;
  children?: NavItem[];
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

export type ActionDef =
  | NavigateAction
  | MutateAction
  | SetStateAction
  | OpenModalAction
  | CloseModalAction
  | ToastAction
  | InvalidateAction
  | SequenceAction
  | CustomAction;

export interface NavigateAction {
  type: "navigate";
  to: string;
}

export interface MutateAction {
  type: "mutate";
  source: string;
  confirm?: string;
}

export interface SetStateAction {
  type: "setState";
  path: string;
  value: string | number | boolean | null;
}

export interface OpenModalAction {
  type: "openModal";
  modal: string;
}

export interface CloseModalAction {
  type: "closeModal";
  modal?: string;
}

export interface ToastAction {
  type: "toast";
  variant?: "success" | "error" | "info" | "warning";
  message: string;
  duration?: number;
  id?: string;
}

export interface InvalidateAction {
  type: "invalidate";
  sources: string[];
}

export interface SequenceAction {
  type: "sequence";
  steps: ActionDef[];
}

export interface CustomAction {
  type: "custom";
  code: string;
}

// ---------------------------------------------------------------------------
// Validation Rules
// ---------------------------------------------------------------------------

export type ValidationRule =
  | { rule: "required"; message?: string }
  | { rule: "minLength"; value: number; message?: string }
  | { rule: "maxLength"; value: number; message?: string }
  | { rule: "min"; value: number; message?: string }
  | { rule: "max"; value: number; message?: string }
  | { rule: "pattern"; value: string; message?: string }
  | { rule: "email"; message?: string }
  | { rule: "url"; message?: string }
  | { rule: "match"; field: string; message?: string }
  | { rule: "custom"; code: string; message?: string };

// ---------------------------------------------------------------------------
// Responsive Values
// ---------------------------------------------------------------------------

/** A value that can vary by breakpoint */
export type ResponsiveValue<T> = T | { default: T; sm?: T; md?: T; lg?: T; xl?: T };

// ---------------------------------------------------------------------------
// Padding / Spacing shorthand
// ---------------------------------------------------------------------------

export type PaddingValue =
  | SpacingToken
  | { x?: SpacingToken; y?: SpacingToken }
  | { top?: SpacingToken; right?: SpacingToken; bottom?: SpacingToken; left?: SpacingToken };

// ---------------------------------------------------------------------------
// Node Types — the IR node union
// ---------------------------------------------------------------------------

export type IRNode =
  // Layout
  | StackNode
  | RowNode
  | GridNode
  | SpacerNode
  | DividerNode
  // Content
  | TextNode
  | IconNode
  | ImageNode
  | AvatarNode
  | BadgeNode
  | TagNode
  | ButtonNode
  | StatCardNode
  | EmptyStateNode
  | SkeletonNode
  // Input
  | TextInputNode
  | TextAreaNode
  | SelectNode
  | CheckboxNode
  | ToggleNode
  | RadioGroupNode
  | DatePickerNode
  | FilePickerNode
  | RichTextEditorNode
  | SliderNode
  | ColorPickerNode
  // Composite
  | DataTableNode
  | FormNode
  | CardNode
  | TabsNode
  | ModalTriggerNode
  | AccordionNode
  | ChartNode
  // Control flow
  | SlotNode
  | RepeaterNode
  | AsyncSlotNode
  // Escape hatch
  | CustomNode
  // Reference
  | FragmentRefNode
  // Placeholder (filled by slot-filler before compilation)
  | PlaceholderSlotNode;

// ---------------------------------------------------------------------------
// Placeholder Slot — filled by the pattern library during generation
// ---------------------------------------------------------------------------

export type SlotType =
  | "entity-table"
  | "entity-form"
  | "entity-detail"
  | "auth-form"
  | "stat-cards"
  | "crud-actions"
  | "detail-tabs"
  | "features-list"
  | "branding"
  | "nav-sidebar"
  | "nav-topbar"
  | "recent-items"
  | "search-bar"
  | "status-filter"
  | "empty-state";

export interface PlaceholderSlotNode extends BaseNodeProps {
  node: "PlaceholderSlot";
  /** The slot type that determines which subtree fills this placeholder */
  $slot: SlotType;
  /** Entity name for entity-bound slots */
  entity?: string;
  /** Additional configuration hints for the slot filler */
  config?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Common base props shared by all nodes
// ---------------------------------------------------------------------------

export interface BaseNodeProps {
  /** Condition expression — if falsy, node is not rendered */
  visible?: string;
  /** Same as visible but used in Slot context */
  if?: string;
  /** Margin (outside spacing) */
  margin?: PaddingValue;
}

// ---------------------------------------------------------------------------
// Layout Nodes
// ---------------------------------------------------------------------------

export interface StackNode extends BaseNodeProps {
  node: "Stack";
  gap?: ResponsiveValue<SpacingToken>;
  padding?: PaddingValue;
  align?: "start" | "center" | "end" | "stretch";
  justify?: "start" | "center" | "end" | "between" | "around";
  width?: string;
  height?: string;
  flex?: number;
  scroll?: boolean;
  wrap?: boolean;
  children: IRNode[];
}

export interface RowNode extends BaseNodeProps {
  node: "Row";
  gap?: ResponsiveValue<SpacingToken>;
  padding?: PaddingValue;
  align?: "start" | "center" | "end" | "stretch";
  justify?: "start" | "center" | "end" | "between" | "around";
  direction?: ResponsiveValue<"row" | "col">;
  width?: string;
  height?: string;
  flex?: number;
  scroll?: boolean;
  wrap?: boolean;
  children: IRNode[];
}

export interface GridNode extends BaseNodeProps {
  node: "Grid";
  columns: ResponsiveValue<number>;
  gap?: ResponsiveValue<SpacingToken>;
  padding?: PaddingValue;
  width?: string;
  height?: string;
  children: IRNode[];
}

export interface SpacerNode extends BaseNodeProps {
  node: "Spacer";
  size: SpacingToken;
}

export interface DividerNode extends BaseNodeProps {
  node: "Divider";
  direction?: "horizontal" | "vertical";
  label?: string;
}

// ---------------------------------------------------------------------------
// Content Nodes
// ---------------------------------------------------------------------------

export interface TextNode extends BaseNodeProps {
  node: "Text";
  content: string;
  typography?: TypographyToken;
  weight?: "normal" | "medium" | "semibold" | "bold";
  color?: ColorToken | string;
  align?: "left" | "center" | "right";
  truncate?: number | false;
  monospace?: boolean;
}

export interface IconNode extends BaseNodeProps {
  node: "Icon";
  name: string;
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  color?: ColorToken | string;
}

export interface ImageNode extends BaseNodeProps {
  node: "Image";
  src: string;
  alt: string;
  width?: string;
  height?: string;
  aspect?: "square" | "video" | "portrait" | number;
  fit?: "cover" | "contain" | "fill";
  radius?: RadiusToken;
  fallback?: string;
}

export interface AvatarNode extends BaseNodeProps {
  node: "Avatar";
  src?: string;
  name?: string;
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  shape?: "circle" | "rounded";
  status?: "online" | "offline" | "busy" | "none";
}

export interface BadgeNode extends BaseNodeProps {
  node: "Badge";
  content: string;
  variant?: "default" | "primary" | "success" | "warning" | "danger" | "outline";
  colorMap?: Record<string, string>;
  size?: "sm" | "md";
  icon?: string;
  dot?: boolean;
}

export interface TagNode extends BaseNodeProps {
  node: "Tag";
  content: string;
  removable?: boolean;
  onRemove?: ActionDef;
  variant?: "default" | "outline";
  color?: ColorToken;
}

export interface ButtonNode extends BaseNodeProps {
  node: "Button";
  label: string;
  variant?: "primary" | "secondary" | "ghost" | "outline" | "danger" | "link";
  size?: "sm" | "md" | "lg";
  icon?: string;
  iconPosition?: "left" | "right";
  disabled?: string | boolean;
  loading?: string | boolean;
  width?: string;
  action?: ActionDef;
  submit?: boolean;
}

export interface StatCardNode extends BaseNodeProps {
  node: "StatCard";
  label: string;
  value: string;
  format?: "number" | "currency" | "percent" | "compact";
  trend?: string;
  trendDirection?: "up-good" | "down-good";
  icon?: string;
  action?: ActionDef;
}

export interface EmptyStateNode extends BaseNodeProps {
  node: "EmptyState";
  icon?: string;
  title?: string;
  message: string;
  action?: { label: string; action: ActionDef };
  secondary?: { label: string; action: ActionDef };
}

export interface SkeletonNode extends BaseNodeProps {
  node: "Skeleton";
  variant?: "text" | "card" | "table" | "avatar";
  lines?: number;
  repeat?: number;
}

// ---------------------------------------------------------------------------
// Input Nodes
// ---------------------------------------------------------------------------

/** Common props shared by all input nodes */
export interface InputBaseProps extends BaseNodeProps {
  bind: string;
  label?: string;
  placeholder?: string;
  required?: boolean;
  disabled?: string | boolean;
  error?: string;
  hint?: string;
  size?: "sm" | "md" | "lg";
}

export interface TextInputNode extends InputBaseProps {
  node: "TextInput";
  type?: "text" | "email" | "url" | "tel" | "number" | "password";
  icon?: string;
  suffix?: string;
  debounce?: number;
  maxLength?: number;
  clearable?: boolean;
}

export interface TextAreaNode extends InputBaseProps {
  node: "TextArea";
  rows?: number;
  maxLength?: number;
  resize?: "none" | "vertical" | "auto";
}

export interface SelectOption {
  value: string;
  label: string;
  description?: string;
  icon?: string;
  disabled?: boolean;
}

export interface SelectDynamicOptions {
  source: string;
  value: string;
  label: string;
}

export interface SelectNode extends InputBaseProps {
  node: "Select";
  options: SelectOption[] | SelectDynamicOptions;
  multiple?: boolean;
  searchable?: boolean;
  clearable?: boolean;
  groupBy?: string;
}

export interface CheckboxNode extends InputBaseProps {
  node: "Checkbox";
  description?: string;
}

export interface ToggleNode extends InputBaseProps {
  node: "Toggle";
  description?: string;
}

export interface RadioGroupNode extends InputBaseProps {
  node: "RadioGroup";
  options: Array<{
    value: string;
    label: string;
    description?: string;
    icon?: string;
    disabled?: boolean;
  }>;
  direction?: "row" | "col";
  variant?: "default" | "card";
}

export interface DatePickerNode extends InputBaseProps {
  node: "DatePicker";
  mode?: "single" | "range";
  min?: string;
  max?: string;
  format?: string;
  includeTime?: boolean;
  presets?: Array<{ label: string; value: string }>;
}

export interface FilePickerNode extends InputBaseProps {
  node: "FilePicker";
  accept?: string;
  maxSize?: number;
  multiple?: boolean;
  endpoint?: string;
  preview?: boolean;
}

export interface RichTextEditorNode extends InputBaseProps {
  node: "RichTextEditor";
  toolbar?: "minimal" | "standard" | "full";
}

export interface SliderNode extends InputBaseProps {
  node: "Slider";
  min: number;
  max: number;
  step?: number;
  showValue?: boolean;
  marks?: Array<{ value: number; label: string }>;
}

export interface ColorPickerNode extends InputBaseProps {
  node: "ColorPicker";
  format?: "hex" | "rgb" | "hsl";
  presets?: string[];
  alpha?: boolean;
}

// ---------------------------------------------------------------------------
// Composite Nodes
// ---------------------------------------------------------------------------

export interface ColumnDef {
  field: string;
  header?: string;
  width?: string;
  align?: "left" | "center" | "right";
  sortable?: boolean;
  filterable?: boolean;
  pinned?: "left" | "right";
  visible?: boolean;
  render?: IRNode | string; // node tree or shorthand: "badge", "date:relative", etc.
}

/** Binds a Form to a backend entity for create/edit operations. */
export interface EntityBinding {
  /** Registry entity name (e.g. "Order", "Customer") */
  entity: string;
  /** "create" → POST a new record; "edit" → PUT/PATCH existing record */
  mode: "create" | "edit";
  /** API route for the submit action (e.g. "/api/orders") */
  submitRoute: string;
  /** API route to prefill form data in edit mode (e.g. "/api/orders/:id") */
  prefillRoute?: string;
  /** Action to execute on successful submit */
  onSuccess: ActionDef;
  /** Optionally trigger a workflow after successful submit */
  onSuccessWorkflow?: {
    workflowId: string;
    /** Maps form field names to workflow input keys */
    inputMapping: Record<string, string>;
  };
}

/** Binds a single form field to a specific entity field in the registry. */
export interface FieldBinding {
  /** Registry entity name */
  entity: string;
  /** Field name on the entity */
  field: string;
}

export interface DataTableNode extends BaseNodeProps {
  node: "DataTable";
  data: string;
  rowKey?: string;
  columns: ColumnDef[];
  pagination?: boolean | { pageSize?: number; serverSide?: boolean };
  sorting?: boolean | { default?: { field: string; direction: "asc" | "desc" } };
  filtering?: boolean;
  selection?: "none" | "single" | "multiple";
  density?: "compact" | "default" | "comfortable";
  stickyHeader?: boolean;
  emptyState?: IRNode;
  onRowClick?: ActionDef;
  rowActions?: ActionDef[];
  bulkActions?: ActionDef[];
  expandable?: IRNode;
  /** Bind this table to a registry entity for auto-column inference and type safety */
  entityBinding?: { entity: string; columns?: string[] };
}

export interface FormFieldDef {
  field: string;
  node?: string; // input node type; inferred if omitted
  label: string;
  required?: boolean;
  validation?: ValidationRule[];
  span?: 1 | 2;
  visible?: string;
  /** Bind this field to a specific entity field for type-safe editing */
  fieldBinding?: FieldBinding;
  // Pass-through to the underlying input component
  [key: string]: unknown;
}

export interface FormNode extends BaseNodeProps {
  node: "Form";
  bind: string;
  onSubmit: ActionDef;
  layout?: "auto" | "single-column" | "two-column" | "sectioned";
  sections?: FormSectionDef[];
  fields?: FormFieldDef[];
  resetOnSubmit?: boolean;
  confirmUnsaved?: boolean;
  actions?: IRNode[];
  /** Bind this form to a registry entity for create/edit operations */
  entityBinding?: EntityBinding;
  /** Trigger a workflow on successful form submit (without full entity binding) */
  onSuccessWorkflow?: {
    workflowId: string;
    /** Maps form field names to workflow input keys */
    inputMapping: Record<string, string>;
  };
}

export interface FormSectionDef {
  title: string;
  description?: string;
  collapsible?: boolean;
  fields: FormFieldDef[];
}

export interface CardNode extends BaseNodeProps {
  node: "Card";
  padding?: SpacingToken;
  radius?: RadiusToken;
  shadow?: "none" | "sm" | "md";
  border?: boolean;
  hoverable?: boolean;
  selected?: string | boolean;
  action?: ActionDef;
  header?: IRNode;
  media?: IRNode;
  footer?: IRNode;
  children?: IRNode[];
}

export interface TabDef {
  id: string;
  label: string;
  icon?: string;
  badge?: string | number;
  disabled?: boolean;
  content: IRNode;
  lazy?: boolean;
}

export interface TabsNode extends BaseNodeProps {
  node: "Tabs";
  defaultTab?: string;
  variant?: "underline" | "pills" | "enclosed";
  tabs: TabDef[];
}

export interface ModalTriggerNode extends BaseNodeProps {
  node: "ModalTrigger";
  modal: string;
  children: IRNode[];
}

export interface AccordionItemDef {
  id: string;
  title: string;
  subtitle?: string;
  icon?: string;
  content: IRNode;
  defaultOpen?: boolean;
}

export interface AccordionNode extends BaseNodeProps {
  node: "Accordion";
  type?: "single" | "multiple";
  items: AccordionItemDef[];
}

export interface ChartSeriesDef {
  field: string;
  label?: string;
  color?: ColorToken;
  type?: "bar" | "line" | "area";
}

export interface ChartNode extends BaseNodeProps {
  node: "Chart";
  type: "bar" | "line" | "area" | "pie" | "donut" | "scatter" | "horizontal-bar";
  data: string;
  xAxis?: { field: string; label?: string; format?: string };
  yAxis?: { field: string; label?: string; format?: string };
  series?: ChartSeriesDef[];
  colors?: string[];
  legend?: boolean;
  tooltip?: boolean;
  height?: number | string;
}

// ---------------------------------------------------------------------------
// Control Flow Nodes
// ---------------------------------------------------------------------------

export interface SlotNode extends BaseNodeProps {
  node: "Slot";
  // if/then/else
  switch?: string;
  cases?: Record<string, IRNode>;
  // switch/cases (alternative)
  then?: IRNode;
  else?: IRNode;
}

export interface RepeaterNode extends BaseNodeProps {
  node: "Repeater";
  data: string;
  itemKey?: string;
  emptyState?: IRNode;
  template: IRNode;
  direction?: "vertical" | "horizontal" | "grid";
  gap?: SpacingToken;
  columns?: ResponsiveValue<number>;
  limit?: number;
}

export interface AsyncSlotNode extends BaseNodeProps {
  node: "AsyncSlot";
  data: string;
  params?: Record<string, string>;
  loading?: IRNode;
  error?: IRNode;
  children: IRNode[];
}

// ---------------------------------------------------------------------------
// Escape Hatch
// ---------------------------------------------------------------------------

export interface CustomNode extends BaseNodeProps {
  node: "Custom";
  code: string;
  imports?: string[];
  props?: Record<string, string>;
  /** Internal: remembers what IR node this replaced */
  _sourceIRNode?: string;
}

// ---------------------------------------------------------------------------
// Fragment Reference
// ---------------------------------------------------------------------------

export interface FragmentRefNode extends BaseNodeProps {
  node: "FragmentRef";
  $ref: string;
  [key: string]: unknown; // fragment props
}

// ---------------------------------------------------------------------------
// IR Operations — mutations applied to the IR document
// ---------------------------------------------------------------------------

export type NodePath = number[];

export type IROperation =
  | { type: "setProp"; path: NodePath; prop: string; value: unknown }
  | { type: "addChild"; path: NodePath; index: number; node: IRNode }
  | { type: "removeChild"; path: NodePath; index: number }
  | {
      type: "moveChild";
      from: NodePath;
      fromIndex: number;
      to: NodePath;
      toIndex: number;
    }
  | { type: "wrapWith"; path: NodePath; wrapper: IRNode }
  | { type: "unwrap"; path: NodePath }
  | { type: "duplicate"; path: NodePath }
  | { type: "replace"; path: NodePath; node: IRNode };

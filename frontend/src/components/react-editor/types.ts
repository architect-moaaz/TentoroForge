/** The editor's data contracts — what the backend's react_editor service returns. */

export type PropKind = "string" | "expr" | "true" | "jsx" | "spread";

export interface NodeProp {
  name: string;
  kind: PropKind;
  value: string | null;
  span: [number, number];
  valueSpan: [number, number] | null;
}

export interface ModelNode {
  id: string;
  parent: string | null;
  index: number;
  type: string;
  kind: "element" | "component" | "fragment";
  props: NodeProp[];
  text: string | null;
  textEditable: boolean;
  inner: string | null;
  innerSpan: [number, number] | null;
  selfClosing: boolean;
  span: [number, number];
  wrapperSpan: [number, number] | null;
  line: number;
  endLine: number;
  context: "repeat" | "conditional" | null;
  /** For an element inside `source.map((variable) => …)`: what is repeated and what each row is called. */
  repeat?: { source: string; variable: string | null } | null;
  /** The element's content when it is exactly one expression: `record.fullName`. */
  exprOnly?: string | null;
  /** Object-literal props (`fields={{…}}`, `input={{…}}`) as entries. */
  objects?: Record<string, ObjectEntry[]>;
  children: string[];
}

export interface ObjectEntry {
  key: string;
  code: string;
  kind: "string" | "number" | "boolean" | "object" | "objects" | "strings" | "expr" | "spread" | "method";
  value?: string | number | boolean | string[];
  entries?: ObjectEntry[];
  items?: ObjectEntry[][];
}

/** What a key `load()` returns holds. */
export type LoadShape =
  | { kind: "rows"; entity: string | null }
  | { kind: "page"; entity: string | null }
  | { kind: "record"; entity: string | null }
  | { kind: "query"; entity: string | null }
  | { kind: "widget"; widget: string | null }
  | { kind: "number" } | { kind: "string" } | { kind: "boolean" } | { kind: "list" } | { kind: "series" } | { kind: "user" } | { kind: "context" } | { kind: "unknown" };

export interface PageModel {
  ok: boolean;
  roots: { id: string; owner: string | null }[];
  nodes: Record<string, ModelNode>;
  imports: { source: string; names: string[]; typeOnly: boolean }[];
  loadKeys: string[];
  loadShapes?: Record<string, LoadShape>;
  viewProps: string[];
  viewParam?: { kind: "identifier"; name: string } | { kind: "pattern"; names: string[]; span: [number, number] } | { kind: "none" } | null;
}

export type SettingTarget =
  | { kind: "text" }
  | { kind: "prop"; name: string; expr?: boolean; boolean?: boolean }
  | { kind: "page"; name: string }
  | { kind: "workflow"; name: string }
  | { kind: "classGroup"; group: string };

export interface SettingSpec {
  key: string;
  label: string;
  control: "text" | "select" | "toggle" | "page" | "workflow";
  target: SettingTarget;
  section: "simple" | "layout" | "style" | "data" | "validation" | "events" | "visibility" | "advanced";
  options?: { value: string; label: string }[];
  help?: string;
  default?: string;
}

export interface ComponentDef {
  id: string;
  label: string;
  category: string;
  description: string;
  search: string[];
  match: { types: string[] };
  jsx: string;
  imports: { source: string; names: string[] }[];
  container: boolean;
  settings: SettingSpec[];
  events: { name: string; label: string; prop: string }[];
  guide: "form" | "table" | "workflow-button" | "chart" | "metric" | null;
  status: "ready" | "unsupported";
}

export interface Registry {
  version: string;
  components: ComponentDef[];
}

export interface PageRef {
  id: string;
  key: string | null;
  name: string;
  route: string;
  params: string[];
}

export interface WorkflowInput {
  name: string;
  kind: string;
  type: string;
  required: boolean;
  description: string;
  entity: string | null;
  options: string[];
}

export interface WorkflowRef {
  id: string;
  key: string | null;
  name: string;
  description: string;
  inputs: WorkflowInput[];
  launchedFrom: string[];
}

export interface EntityRef {
  id: string;
  name: string;
  typeName: string;
  table?: string | null;
  fields: { name: string; type: string; required: boolean; label: string; options: string[] }[];
}

export type ChartMark = "bar" | "line" | "area" | "pie" | "donut" | "funnel" | "radar" | "scatter" | "heatmap" | "treemap";

export interface WidgetMeasure { key: string; aggregation: "count" | "count_distinct" | "sum" | "avg" | "min" | "max"; field?: string; label?: string }
export interface WidgetDimension { field: string; bucket?: "day" | "week" | "month" | "quarter" | "year" }

/** A chart or number tile: a Blueprint widget, drawn by `WidgetView` from its `widgets.key` handle. */
export interface WidgetRef {
  id: string;
  key: string | null;
  page: string;
  label: string;
  description: string;
  kind: "metric" | "chart" | "list" | "table" | "feed" | "gauge" | "text";
  unit: "number" | "currency" | "percent" | "duration" | "date" | "text";
  size: "sm" | "md" | "lg" | "full" | null;
  chart: { mark: ChartMark; stacked?: boolean; horizontal?: boolean } | null;
  order: number | null;
  source: { op: "query"; entity: string; measures: WidgetMeasure[]; dimensions: WidgetDimension[]; filter: Record<string, unknown>; timeField?: string; sort?: { by: string; order?: "asc" | "desc" }; limit?: number }
        | { op: string; entity: string; [k: string]: unknown };
}

/** What the person chose for a chart — the backend turns it into a widget row. */
export interface WidgetSpec {
  label?: string;
  description?: string;
  kind?: "chart" | "metric" | "gauge";
  unit?: WidgetRef["unit"];
  size?: "sm" | "md" | "lg" | "full";
  entity?: string;
  measures?: WidgetMeasure[];
  dimensions?: WidgetDimension[];
  mark?: ChartMark;
  stacked?: boolean;
  horizontal?: boolean;
  limit?: number | null;
  sort?: { by: string; order?: "asc" | "desc" } | null;
  timeField?: string | null;
  filter?: Record<string, string | string[] | number | boolean>;
}

export interface HistoryEntry {
  revision: string;
  parent: string | null;
  label: string;
  kind: "baseline" | "edit" | "smith" | "restore";
  at: string;
  version: number | null;
}

export interface PageDoc {
  page: { id: string; name: string; route: string; purpose: string; access?: string; file?: string };
  coded: boolean;
  reason?: string;
  revision: string;
  model: PageModel | null;
  source: { view: string; load: string } | null;
  registry: Registry;
  pages: PageRef[];
  workflows: WorkflowRef[];
  entities: EntityRef[];
  widgets?: WidgetRef[];
  /** Example rows per entity — what the instant canvas shows. */
  samples?: Record<string, Record<string, unknown>[]>;
  theme: Record<string, unknown>;
  history: HistoryEntry[];
  toolchain?: { typecheck: boolean };
}

export interface PageListItem {
  id: string;
  name: string;
  route: string;
  purpose: string;
  pattern: string | null;
  access: string;
  coded: boolean;
  module: string | null;
  navigatesTo: string[];
}

export interface Finding {
  file: string | null;
  line: number | null;
  code: string | null;
  raw: string;
  plain: string;
  severity: "must-fix" | "recommended";
  nodeId?: string;
}

export interface ApplyResult {
  revision: string;
  model: PageModel;
  source: { view: string; load: string };
  checked: boolean;
  unchanged: boolean;
  version: number | null;
  history?: HistoryEntry;
}

export interface Proposal {
  id: string;
  pageId: string;
  baseRevision: string;
  prompt: string;
  annotation: string;
  selection: { type: string; nodeIds: string[] };
  summary: string;
  explanation: string;
  needs: string[];
  questions: { question: string; options: string[] }[];
  replacements: { nodeId: string; type: string; before: string; after: string }[];
  imports: { source: string; names: string[] }[];
  expandsScope: string[];
  refused: { nodeId: string; why: string }[];
  findings: Finding[];
  valid: boolean;
  status: "staged" | "needs-choice" | "nothing" | "needs-more" | "ready" | "invalid" | "applied" | "discarded";
  createdAt: string;
  timing: { generationMs: number; validationMs: number };
  appliedRevision?: string;
}

export type PropValue = { kind: "string"; value: string } | { kind: "expr"; value: string } | { kind: "true" };

/** One editor operation, as the adapter takes it. */
export type Op =
  | { op: "setText"; id: string; text: string }
  | { op: "setProp"; id: string; name: string; value: PropValue | null }
  | { op: "setClasses"; id: string; classes: string }
  | { op: "remove"; ids: string[] }
  | { op: "insert"; parentId?: string; index?: number | null; afterId?: string; beforeId?: string; jsx: string }
  | { op: "move"; id: string; parentId: string; index: number | null }
  | { op: "duplicate"; id: string }
  | { op: "replaceNode"; id: string; jsx: string }
  | { op: "addImport"; source: string; names: string[]; file?: "load" }
  | { op: "ensureProp"; name: string }
  | { op: "setChildren"; id: string; jsx: string }
  | { op: "setObjectProp"; id: string; name: string; entries: ObjectEntry[] }
  | { op: "addReturnKey"; file: "load"; key: string; expr: string }
  | { op: "removeReturnKey"; file: "load"; key: string };

export type Device = "desktop" | "tablet" | "mobile" | "custom";
export type Breakpoint = "" | "sm" | "md" | "lg" | "xl";

export interface Rect { top: number; left: number; width: number; height: number }

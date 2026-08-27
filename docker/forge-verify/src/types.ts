import type { RenderTruthFinding } from "./renderTruth";
/**
 * Mirror of the Python-side Interaction/Evidence/Fault types.
 *
 * Kept in the runner so backend can POST a JSON payload the runner
 * consumes without a schema-generation step. Field names match
 * backend/services/interaction_extractor.py + fault_classifier.py verbatim.
 */

export type InteractionKind = "route" | "button" | "form" | "list" | "detail";

export interface RouteInteraction {
  id: string;
  kind: "route";
  route: string;
  requires_auth: boolean;
}

export interface ButtonAction {
  kind: "workflow" | "navigate" | "compute" | "submit" | "none";
  workflow_target?: string | null;
  navigate_target?: string | null;
  compute_target?: string | null;
  compute_formula?: string | null;
}

export interface ButtonInteraction {
  id: string;
  kind: "button";
  route: string;
  selector: string;
  label: string;
  action: ButtonAction;
}

export interface FieldSpec {
  name: string;
  type: string;
  required?: boolean;
  options?: string[];
  fk_entity?: string | null;
}

export interface WorkflowInput {
  name: string;
  type: string;
  required?: boolean;
  options?: string[];
}

export interface FormSubmit {
  kind: "workflow" | "dataSource" | "none";
  workflow_target?: string | null;
  workflow_inputs?: WorkflowInput[];
  dataSource_target?: string | null;
}

export interface FormInteraction {
  id: string;
  kind: "form";
  route: string;
  selector: string;
  fields: FieldSpec[];
  submit: FormSubmit;
}

export interface ListInteraction {
  id: string;
  kind: "list";
  route: string;
  selector: string;
  dataSource: string;
  entity: string | null;
  seed_min_rows: number;
}

export interface DetailInteraction {
  id: string;
  kind: "detail";
  route: string;
  entity: string | null;
  param_name: string;
}

export type Interaction =
  | RouteInteraction
  | ButtonInteraction
  | FormInteraction
  | ListInteraction
  | DetailInteraction;

// ── Evidence ─────────────────────────────────────────────────────────────

export interface NetworkEntry {
  method: string;
  url: string;
  status: number;
}

export interface LogEntry {
  level: "error" | "warning" | "info" | "log";
  text: string;
}

export interface Evidence {
  status: number | null;
  body_excerpt: string | null;
  console: LogEntry[];
  network_log: NetworkEntry[];
  dom_snapshot: string | null;
  stack_trace: string | null;
  screenshot_uri: string | null;
  url_after_click: string | null;
  computed_value_actual: unknown;
  computed_value_expected: unknown;
  rows_returned: number | null;
  timed_out: boolean;
  rendered_widget_count: number | null;
  /** Widgets that are PRESENT but drew nothing. Empty array = every
   *  data-bound widget on the page actually said something. */
  render_truth: RenderTruthFinding[];
}

export function emptyEvidence(): Evidence {
  return {
    status: null,
    body_excerpt: null,
    console: [],
    network_log: [],
    dom_snapshot: null,
    stack_trace: null,
    screenshot_uri: null,
    url_after_click: null,
    computed_value_actual: null,
    computed_value_expected: null,
    rows_returned: null,
    timed_out: false,
    rendered_widget_count: null,
    render_truth: [],
  };
}

// ── Run request / report ─────────────────────────────────────────────────

export interface RunRequest {
  run_id?: string;
  project_id: string;
  target: "preview" | "deploy";
  base_url: string;
  interactions: Interaction[];
  auth?: { username: string; password: string; login_route?: string };
  parallelism?: number;
  interaction_timeout_ms?: number;
}

export interface FaultRaw {
  /** Raw fault as produced by the runner — Python-side classifier turns
   *  this into a FaultClassification. */
  interaction_id: string;
  interaction: Interaction;
  evidence: Evidence;
  passed: boolean;
  flaky: boolean;
}

export interface RunReport {
  run_id: string;
  project_id: string;
  target: "preview" | "deploy";
  base_url: string;
  started_at: string;
  finished_at: string;
  interactions_run: number;
  interactions_passed: number;
  interactions_flaky: number;
  faults: FaultRaw[];
}

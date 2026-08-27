/** Decision table and decision graph type definitions. */

// ---------------------------------------------------------------------------
// Hit Policies
// ---------------------------------------------------------------------------

/** U=Unique, F=First, A=Any, P=Priority, C=Collect, R=RuleOrder */
export type HitPolicy = "U" | "F" | "A" | "P" | "C" | "R";

export const HIT_POLICY_LABELS: Record<HitPolicy, { label: string; description: string }> = {
  U: { label: "Unique", description: "Exactly one rule must match" },
  F: { label: "First", description: "First matching rule wins" },
  A: { label: "Any", description: "All matching rules must agree on output" },
  P: { label: "Priority", description: "Highest-priority matching rule wins" },
  C: { label: "Collect", description: "All matching rules collected into a list" },
  R: { label: "Rule Order", description: "All matching rules returned in definition order" },
};

// ---------------------------------------------------------------------------
// Decision Table Definition
// ---------------------------------------------------------------------------

export interface DecisionTableInput {
  id: string;
  name: string;
  label?: string;
  type: "string" | "number" | "boolean" | "date" | "any";
  variableBinding?: string;
}

export interface DecisionTableOutput {
  id: string;
  name: string;
  label?: string;
  type: "string" | "number" | "boolean" | "date" | "any";
}

export interface DecisionTableRule {
  id: string;
  inputEntries: string[];
  outputEntries: string[];
  annotation?: string;
}

export interface DecisionTableDefinition {
  id: string;
  name: string;
  hitPolicy: HitPolicy;
  inputs: DecisionTableInput[];
  outputs: DecisionTableOutput[];
  rules: DecisionTableRule[];
}

// ---------------------------------------------------------------------------
// Decision Graph (DRD)
// ---------------------------------------------------------------------------

export type DRDNodeType = "inputData" | "decision" | "knowledgeSource";

export interface DRDNode {
  id: string;
  type: DRDNodeType;
  label: string;
  position: { x: number; y: number };
  /** For decision nodes — links to a decision table */
  decisionTableId?: string;
  /** For inputData nodes — variable name */
  variableName?: string;
  /** For inputData nodes — variable type */
  variableType?: "string" | "number" | "boolean" | "date" | "any";
  /** For knowledgeSource nodes — URL */
  url?: string;
  /** For knowledgeSource nodes — description */
  description?: string;
}

export type DRDEdgeType = "information" | "knowledge";

export interface DRDEdge {
  id: string;
  source: string;
  target: string;
  type: DRDEdgeType;
}

export interface DecisionGraphDefinition {
  id: string;
  name: string;
  nodes: DRDNode[];
  edges: DRDEdge[];
  tables: Record<string, DecisionTableDefinition>;
}

// ---------------------------------------------------------------------------
// Evaluation Results
// ---------------------------------------------------------------------------

export interface DecisionTableResult {
  hitPolicy: HitPolicy;
  matchedRuleIds: string[];
  outputs: Record<string, unknown>[];
  /** Single output for U/F/A/P policies, array for C/R */
  result: Record<string, unknown> | Record<string, unknown>[];
}

export interface DecisionGraphResult {
  decisions: Record<string, DecisionTableResult>;
  finalOutputs: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Rule Templates
// ---------------------------------------------------------------------------

export type RuleTemplateType =
  | "score_card"
  | "eligibility_check"
  | "tier_classification"
  | "routing_matrix"
  | "discount_ladder"
  | "validation_rule_set"
  | "priority_matrix";

export interface RuleTemplate {
  type: RuleTemplateType;
  name: string;
  description: string;
  icon: string;
  table: DecisionTableDefinition;
}

// ---------------------------------------------------------------------------
// Testing & Validation
// ---------------------------------------------------------------------------

export interface DecisionTestCase {
  id: string;
  name: string;
  inputs: Record<string, unknown>;
  expectedOutputs?: Record<string, unknown>;
}

export interface DecisionTestResult {
  testCaseId: string;
  passed: boolean;
  actual: DecisionTableResult;
  expectedMatch: boolean;
  errorMessage?: string;
}

// ---------------------------------------------------------------------------
// Analysis
// ---------------------------------------------------------------------------

export interface DecisionAnalysisResult {
  completeness: {
    complete: boolean;
    missingCombinations: string[];
  };
  overlaps: {
    ruleIdPairs: [string, string][];
  };
  deadRows: string[];
  typeErrors: {
    ruleId: string;
    columnIndex: number;
    message: string;
  }[];
}

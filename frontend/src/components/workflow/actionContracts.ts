/**
 * Declarative input/output contracts per workflow ActionType.
 *
 * This is the successor to actionFieldSpecs.ts. Where actionFieldSpecs
 * describes a flat bag of config fields (`values`, `to`, `subject`, …),
 * this file models the BPMN-style contract that the Properties panel v2
 * uses:
 *
 *   ┌───────── input mapping ─────────┐        ┌─── output mapping ───┐
 *   │ every declared input has a name,│        │ every declared output │
 *   │ type, required flag; the panel  │  node  │ is always available   │
 *   │ auto-populates required inputs  │ ─────► │ downstream as         │
 *   │ and asks the user to bind each  │  runs  │   <nodeId>.output.X   │
 *   │ to a source (variable/literal/  │        │ and may be opt-in     │
 *   │ expression).                    │        │ promoted to a named   │
 *   │                                 │        │ process variable.     │
 *   └─────────────────────────────────┘        └───────────────────────┘
 *
 * See docs/superpowers/specs/2026-07-22-workflow-node-contracts.md.
 */

export type ParamType =
  | "string"
  | "number"
  | "boolean"
  | "email"
  | "uuid"
  | "date"
  | "object"
  | "array"
  | "enum"
  // Semantic types — same runtime representation as the primitives, but
  // the editor renders a picker over real data instead of a free-text
  // field. See InputMappingSection ValueControl.
  | "table"       // → dropdown over appModel.database.tables[].name
  | "user";       // → OrgEntityCombobox (person picker)

export interface ParamContract {
  /** Dot-path name; e.g. "table", "values.email", "inserted.id" */
  name: string;
  type: ParamType;
  /** Inputs only; outputs are always produced. */
  required?: boolean;
  /** For type="enum". */
  options?: readonly string[];
  /** Human-readable label (falls back to name). */
  label?: string;
  /** Subtext under the row. */
  help?: string;
  /**
   * Advanced knob (max tokens, temperature, custom model, headers…):
   * hidden by default behind an "Advanced" disclosure so the panel
   * shows the required + common-optional fields first. Only affects
   * rendering; the mapping shape is unchanged.
   */
  advanced?: boolean;
  /**
   * Schematic source hint:
   *   "column:<table>.<col>"  — for DB actions; resolved against appModel
   *   "static"                — user provides a literal / mapping
   *
   * Not enforced today; feeds later type-check + auto-suggest work.
   */
  source?: string;
}

export interface ActionContract {
  /** Label shown in the action-type dropdown. */
  label: string;
  /** Ordered — the panel renders required first, then optional. */
  inputs: readonly ParamContract[];
  /** Ordered — every one is always visible in the outputs section. */
  outputs: readonly ParamContract[];
  /**
   * For DB actions: expand the specified input from the target-table's
   * columns at render time. The panel reads appModel.database.tables to
   * find the target table (the value of the `tableInputName` input) and
   * synthesizes one input per column named `<into>.<columnName>` with a
   * best-effort type derived from the column's SQL type.
   */
  expandFromTable?: {
    /** Which input holds the table name (usually "table"). */
    tableInputName: string;
    /** The dotted prefix under which synthesized inputs are grouped. */
    into: string;
    /** Whether to include the primary-key column. */
    mode: "all-columns" | "no-primary-key";
  };
}

/**
 * The catalog. Preserve this order — the panel's action-type dropdown
 * uses `Object.keys(ACTION_CONTRACTS)`.
 */
export const ACTION_CONTRACTS: Record<string, ActionContract> = {
  // --- Database ------------------------------------------------------- //
  db_insert: {
    label: "Insert Record",
    inputs: [
      { name: "table", type: "table", required: true, label: "Table", help: "Pick the record type to create." },
    ],
    outputs: [
      { name: "inserted.id", type: "uuid", label: "Inserted row id" },
      { name: "inserted", type: "object", label: "Full inserted row" },
    ],
    expandFromTable: { tableInputName: "table", into: "values", mode: "no-primary-key" },
  },
  db_update: {
    label: "Update Record",
    inputs: [
      { name: "table", type: "table", required: true, label: "Table" },
      { name: "where", type: "object", required: true, label: "Match rows where", help: "Column → value pairs. Only rows matching all of them get updated." },
    ],
    outputs: [
      { name: "updated.count", type: "number", label: "Rows updated" },
      { name: "updated.rows", type: "array", label: "Updated rows" },
    ],
    expandFromTable: { tableInputName: "table", into: "values", mode: "no-primary-key" },
  },
  db_delete: {
    label: "Delete Record",
    inputs: [
      { name: "table", type: "table", required: true, label: "Table" },
      { name: "where", type: "object", required: true, label: "Match rows where", help: "Column → value pairs. Only rows matching all of them get deleted." },
    ],
    outputs: [
      { name: "deleted.count", type: "number", label: "Rows deleted" },
    ],
  },
  db_query: {
    label: "Look up records",
    inputs: [
      { name: "table", type: "table", required: true, label: "Table" },
      { name: "where", type: "object", label: "Match rows where (optional)" },
    ],
    outputs: [
      { name: "rows", type: "array", label: "Result rows" },
      { name: "count", type: "number", label: "Row count" },
    ],
  },

  // --- Comm ----------------------------------------------------------- //
  send_email: {
    label: "Send Email",
    inputs: [
      { name: "to", type: "email", required: true, label: "To" },
      { name: "subject", type: "string", required: true, label: "Subject" },
      { name: "message", type: "string", required: true, label: "Body", help: "Plain text; wrapped in <p> at send time." },
      { name: "from", type: "email", label: "From (optional)" },
    ],
    outputs: [
      { name: "sent", type: "boolean", label: "Sent?" },
      { name: "channel", type: "string", label: "Channel used (smtp / resend / fallback)" },
      { name: "messageId", type: "string", label: "Provider message id" },
    ],
  },
  send_notification: {
    label: "Send Notification (in-app)",
    inputs: [
      { name: "title", type: "string", required: true, label: "Title" },
      { name: "message", type: "string", required: true, label: "Message" },
      { name: "to", type: "user", label: "Recipient (optional)", help: "Pick a person. Leave blank to broadcast by role." },
      { name: "toRole", type: "string", label: "By role (optional)" },
      {
        name: "type",
        type: "enum",
        options: ["info", "success", "warning", "error", "email"],
        label: "Type",
      },
      { name: "entityId", type: "uuid", label: "Related entity id (optional)", advanced: true },
      { name: "channels", type: "array", label: "Channels", help: "in_app (the bell), push (the person's devices — needs push turned on for the app)", advanced: true },
    ],
    outputs: [
      { name: "sent", type: "boolean", label: "Sent?" },
      { name: "notificationId", type: "uuid", label: "Notification id" },
      { name: "pushed", type: "number", label: "Devices reached" },
    ],
  },

  // --- HTTP ----------------------------------------------------------- //
  http_call: {
    label: "HTTP Call",
    inputs: [
      { name: "url", type: "string", required: true, label: "URL" },
      {
        name: "method",
        type: "enum",
        options: ["GET", "POST", "PUT", "PATCH", "DELETE"],
        required: true,
        label: "Method",
      },
      { name: "body", type: "object", label: "Body" },
      { name: "headers", type: "object", label: "Headers", advanced: true },
      { name: "auth", type: "object", label: "Auth (a secret by its name: {secretRef, in, name})", advanced: true },
    ],
    outputs: [
      { name: "status", type: "number", label: "HTTP status" },
      { name: "body", type: "object", label: "Response body" },
      { name: "headers", type: "object", label: "Response headers" },
    ],
  },

  // --- Payments ------------------------------------------------------- //
  create_checkout: {
    label: "Take payment",
    inputs: [
      { name: "amount", type: "number", label: "Amount (major units)" },
      { name: "lineItems", type: "array", label: "Line items [{name, amount, quantity}]" },
      { name: "currency", type: "string", label: "Currency (ISO 4217; the app's by default)" },
      { name: "description", type: "string", label: "What is being paid for" },
      { name: "reference", type: "object", required: true, label: "The record this pays for {entity, id}" },
      { name: "customerEmail", type: "string", label: "Payer's email", advanced: true },
      { name: "successPage", type: "string", label: "Page after paying" },
      { name: "cancelPage", type: "string", label: "Page after cancelling" },
      { name: "transfer", type: "object", label: "Split {destinationAccountRef, applicationFeePercent}", advanced: true },
    ],
    outputs: [
      { name: "url", type: "string", label: "Checkout URL" },
      { name: "sessionId", type: "string", label: "Checkout session" },
      { name: "paymentId", type: "string", label: "Ledger payment id" },
      { name: "provider", type: "string", label: "Provider" },
    ],
  },
  refund_payment: {
    label: "Refund a payment",
    inputs: [
      { name: "paymentId", type: "string", required: true, label: "Ledger payment id" },
      { name: "amount", type: "number", label: "Amount (major units; whole when absent)" },
    ],
    outputs: [
      { name: "refundId", type: "string", label: "Refund id" },
      { name: "status", type: "string", label: "Status" },
    ],
  },
  payment_status: {
    label: "Payment status",
    inputs: [{ name: "paymentId", type: "string", required: true, label: "Ledger payment id" }],
    outputs: [
      { name: "status", type: "string", label: "Status" },
      { name: "amount", type: "number", label: "Amount" },
      { name: "currency", type: "string", label: "Currency" },
    ],
  },
  connect_account: {
    label: "Connect a payee",
    inputs: [
      { name: "reference", type: "object", required: true, label: "The payee record {entity, id}" },
      { name: "returnPage", type: "string", label: "Page after onboarding" },
    ],
    outputs: [
      { name: "onboardingUrl", type: "string", label: "Onboarding URL" },
      { name: "accountRef", type: "string", label: "Payee account" },
    ],
  },

  // --- Compute -------------------------------------------------------- //
  custom: {
    label: "Custom Function",
    inputs: [
      { name: "expression", type: "string", required: true, label: "Expression", help: "FEEL-lite expression evaluated at runtime." },
      { name: "assignTo", type: "string", label: "Assign to variable (optional)" },
    ],
    outputs: [
      { name: "value", type: "object", label: "Return value" },
    ],
  },
  set_variable: {
    label: "Set Variable",
    inputs: [
      { name: "variableName", type: "string", required: true, label: "Variable name" },
      { name: "expression", type: "string", required: true, label: "Value / expression" },
    ],
    outputs: [
      { name: "value", type: "object", label: "Assigned value" },
    ],
  },
  transform: {
    label: "Transform / Map",
    inputs: [
      { name: "expression", type: "string", required: true, label: "Expression" },
    ],
    outputs: [
      { name: "value", type: "object", label: "Transformed value" },
    ],
  },

  // --- Event bus ------------------------------------------------------ //
  emit_event: {
    label: "Emit Event",
    inputs: [
      { name: "event", type: "string", required: true, label: "Event type", help: 'Dot-namespaced, e.g. "order.approved".' },
      { name: "payload", type: "object", label: "Payload", help: "Field \u2192 value map; values may use {{refs}}." },
      { name: "entity", type: "string", label: "Entity slug (optional)" },
      { name: "entityId", type: "string", label: "Entity id (optional)" },
    ],
    outputs: [
      { name: "emitted", type: "boolean", label: "Emitted" },
      { name: "eventId", type: "uuid", label: "Event row id" },
    ],
  },
  wait_for_event: {
    label: "Wait for Event",
    inputs: [
      { name: "event", type: "string", required: true, label: "Event type", help: "Pauses the run until this event is emitted on the bus." },
      { name: "timeoutMs", type: "number", label: "Timeout (ms, optional)" },
    ],
    outputs: [
      { name: "event", type: "string", label: "Received event type" },
    ],
  },

  // --- Documents ------------------------------------------------------ //
  generate_document: {
    label: "Generate Document (PDF)",
    inputs: [
      { name: "title", type: "string", required: true, label: "Title" },
      { name: "subtitle", type: "string", label: "Subtitle (optional)" },
      { name: "footer", type: "string", label: "Footer (optional)" },
      { name: "fields", type: "array", label: "Fields", help: "Array of {label, value} — one row per printed field." },
      { name: "record", type: "object", label: "Record (alt to fields)" },
    ],
    outputs: [
      { name: "fileId", type: "uuid", label: "File id" },
      { name: "url", type: "string", label: "Download URL" },
    ],
  },

  // --- AI ------------------------------------------------------------- //
  ai_generate: {
    label: "AI · Generate",
    inputs: [
      { name: "aiInput", type: "string", required: true, label: "Input" },
      { name: "aiPrompt", type: "string", label: "Extra prompt" },
      { name: "aiSystemPrompt", type: "string", label: "System prompt", advanced: true },
      { name: "aiMaxTokens", type: "number", label: "Max tokens", advanced: true },
      { name: "aiTemperature", type: "number", label: "Temperature", advanced: true },
      { name: "aiModel", type: "string", label: "Model", advanced: true, help: "Leave blank to use the default." },
    ],
    outputs: [
      { name: "text", type: "string", label: "Generated text" },
      // A0-6: `usage` was declared here but NO runtime path produced it —
      // callLLM returns a plain string and never surfaces token counts, so
      // the panel offered a promotable output that always resolved to
      // undefined. Removed rather than faked: returning zeros would report
      // 0 tokens for a real call. Re-add here and in ai.ts together if
      // callLLM ever exposes usage.
    ],
  },
  ai_classify: {
    label: "AI · Classify",
    inputs: [
      { name: "aiInput", type: "string", required: true, label: "Input" },
      { name: "aiLabels", type: "array", required: true, label: "Labels", help: "The choices the AI can pick from." },
      { name: "aiPrompt", type: "string", label: "Extra prompt" },
      { name: "aiConfidenceThreshold", type: "number", label: "Confidence threshold", advanced: true },
    ],
    outputs: [
      { name: "label", type: "string", label: "Chosen label" },
      { name: "confidence", type: "number", label: "Confidence 0..1" },
    ],
  },
  ai_extract: {
    label: "AI · Extract",
    inputs: [
      { name: "aiInput", type: "string", label: "Input (text)" },
      { name: "aiFileRef", type: "uuid", label: "File reference (PDF/image)" },
      { name: "aiExtractFields", type: "array", required: true, label: "Fields to extract" },
      { name: "aiSystemPrompt", type: "string", label: "System prompt", advanced: true },
    ],
    outputs: [
      { name: "data", type: "object", label: "Extracted fields" },
    ],
  },
  for_each: {
    label: "For Each",
    inputs: [
      { name: "items", type: "array", required: true, label: "Items (a list, or {{step.output}})" },
      { name: "as", type: "string", label: "Each item is called (default: item)" },
      { name: "steps", type: "array", required: true, label: "Steps run for each item" },
    ],
    outputs: [
      { name: "count", type: "number", label: "Items processed" },
      { name: "failed", type: "number", label: "Items that failed" },
      { name: "results", type: "array", label: "Each item's step outputs" },
      { name: "errors", type: "array", label: "Where each failed item stopped" },
    ],
  },
  // --- Integrations --------------------------------------------------- //
  mcp_tool_call: {
    label: "MCP · Tool Call",
    inputs: [
      { name: "mcp_server_name", type: "string", required: true, label: "Server name",
        help: "An enabled MCP server (Settings → MCP Servers); matched case-insensitively." },
      { name: "mcp_tool_name", type: "string", required: true, label: "Tool name" },
      { name: "args", type: "object", label: "Arguments ({{var}} bindings allowed)" },
      { name: "mcp_server_id", type: "uuid", label: "Server id (instead of name)", advanced: true },
    ],
    outputs: [
      { name: "result", type: "object", label: "Tool result" },
    ],
  },
  ocr_document: {
    label: "OCR · Document (PaddleOCR)",
    inputs: [
      { name: "ocrFileRef", type: "uuid", required: true, label: "Document (file id / URL / {{binding}})" },
      { name: "ocrPages", type: "array", label: "Pages (1-indexed; omit for all)", advanced: true },
      { name: "ocrLanguage", type: "string", label: "Language (e.g. en, zh, ar; auto-detect if empty)", advanced: true },
    ],
    outputs: [
      { name: "text", type: "string", label: "Recognised text (all pages concatenated)" },
      { name: "blocks", type: "array", label: "Blocks [{text, bbox, confidence, page}]" },
      { name: "pageCount", type: "number", label: "Pages processed" },
      { name: "confidence", type: "number", label: "Mean confidence 0..1" },
    ],
  },
  ai_decide: {
    label: "AI · Decide",
    inputs: [
      { name: "aiContext", type: "string", required: true, label: "Context" },
      { name: "aiOptions", type: "array", required: true, label: "Options" },
      { name: "aiRules", type: "array", label: "Rules" },
      { name: "aiPrompt", type: "string", label: "Extra prompt", advanced: true },
    ],
    outputs: [
      // A18-1: `decision` was declared string/"Chosen option", but the handler
      // returns it as a BOOLEAN (true selects the primary option) — the chosen
      // option string is `option`. Anyone binding `decision` expecting a name
      // got `true`. Both are declared now, each with its real type.
      { name: "decision", type: "boolean", label: "Primary option chosen" },
      { name: "option", type: "string", label: "Chosen option" },
      { name: "confidence", type: "number", label: "Confidence" },
      { name: "rationale", type: "string", label: "Why" },
    ],
  },
  // An app assistant does one step and hands back a structured answer. The
  // properties panel has its own editor for this one (AgentStepProps); this
  // entry is the declared shape: what the step takes and what a later step can
  // read from it (`<step>.result.<answer>` plus the always-present fields).
  // "An assistant OR a brief" cannot be said by one `required` flag, so
  // agentId is not marked required here; lib/agent-step.ts checks the pair.
  agent_step: {
    label: "Assistant step",
    inputs: [
      { name: "agentId", type: "string", label: "Assistant", help: "The assistant that does this step." },
      { name: "task", type: "string", required: true, label: "What to do this time" },
      { name: "input", type: "object", label: "Facts to hand over" },
      { name: "outputFields", type: "array", required: true, label: "Answers it hands back" },
      { name: "autonomy", type: "enum", options: ["suggest", "limited", "full"], label: "How much it may do by itself" },
      { name: "minConfidence", type: "number", label: "How sure it must be (Limited)", advanced: true },
      { name: "allowedWriteTools", type: "array", label: "Changes it may make", advanced: true },
      { name: "maxActions", type: "number", label: "Most changes at one time", advanced: true },
      { name: "maxTurns", type: "number", label: "Most turns", advanced: true },
      { name: "timeoutSec", type: "number", label: "Time limit (seconds)", advanced: true },
      { name: "maxTokens", type: "number", label: "Size limit (tokens)", advanced: true },
      { name: "onFailure", type: "enum", options: ["human", "skip", "fail"], label: "If it cannot finish", advanced: true },
    ],
    outputs: [
      { name: "ok", type: "boolean", label: "Finished properly" },
      { name: "needsHuman", type: "boolean", label: "A person should look" },
      { name: "confidence", type: "number", label: "How sure it is" },
      { name: "summary", type: "string", label: "One sentence about what it did" },
      { name: "result", type: "object", label: "Its answers" },
      { name: "proposals", type: "array", label: "Changes it suggested" },
      { name: "actions", type: "array", label: "Changes it made" },
    ],
  },
};

export const ACTION_CONTRACT_KEYS = Object.keys(ACTION_CONTRACTS);

// ---------------------------------------------------------------------------
// Input Mappings — runtime shape stored on the node
// ---------------------------------------------------------------------------

export type MappingSource = "variable" | "literal" | "expression";

export interface InputMapping {
  /** The contract input name (e.g. "table", "values.email"). */
  name: string;
  /** How the value is resolved at runtime. */
  source: MappingSource;
  /**
   * variable  → the variable path without braces  ("trigger.email", "create_user.output.inserted.id")
   * literal   → the raw value, coerced by contract type at exec time
   * expression → a FEEL-lite expression string
   */
  value: unknown;
}

export interface OutputMapping {
  /** The contract output name (e.g. "inserted.id"). */
  output: string;
  /** The named process variable to promote it to. Blank = not promoted. */
  processVar: string;
}

// ---------------------------------------------------------------------------
// Contract lookup helpers
// ---------------------------------------------------------------------------

/** Returns the contract for a given actionType, or null if unknown. */
export function getContract(actionType: string | undefined): ActionContract | null {
  if (!actionType) return null;
  return ACTION_CONTRACTS[actionType] ?? null;
}

/** SQL-type → ParamType heuristic used by expandFromTable. */
export function sqlTypeToParamType(sqlType: string | undefined): ParamType {
  const t = (sqlType || "").toLowerCase();
  if (t.includes("uuid")) return "uuid";
  if (t.includes("int") || t.includes("numeric") || t.includes("real") || t.includes("double") || t.includes("decimal"))
    return "number";
  if (t.includes("bool")) return "boolean";
  if (t.includes("date") || t.includes("time") || t.includes("timestamp")) return "date";
  if (t.includes("json") || t.includes("object")) return "object";
  if (t.includes("array")) return "array";
  if (t.includes("email")) return "email";
  return "string";
}

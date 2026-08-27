/**
 * Declarative catalog of the fields each workflow action type exposes in
 * the Properties panel. One entry per ActionType known to the runtime.
 *
 * WHY: the previous NodePropertiesPanel hand-coded a per-action-type JSX
 * block, and the two ways it drifted from the runtime were:
 *   1. `db_insert` was added to the palette + type union but nobody added
 *      the matching field block — Properties rendered blank.
 *   2. `send_email` was implemented before the message/body field existed
 *      in the runtime — the UI never grew to show it.
 * A spec-driven approach means adding a new field is a one-line change
 * here; the render loop picks it up automatically.
 *
 * Field `kind` maps to a UI control:
 *   text     — <Input> for a short string (with placeholder support)
 *   textarea — <Textarea> for a multi-line string (email body, expressions)
 *   select   — <Select> populated from `options`
 *   json     — <Textarea> that stores a JSON-encoded object/array; the
 *              renderer parses on blur and shows a diagnostic if invalid.
 *              Used for `values`, `where`, `headers`, `options`, `fields`.
 */

export type FieldKind = "text" | "textarea" | "select" | "json";

export interface FieldSpec {
  key: string;              // the config-object key to read/write
  label: string;            // human-readable label above the control
  kind: FieldKind;
  placeholder?: string;     // shown when value is empty
  options?: readonly string[]; // required for kind='select'
  help?: string;            // small subtext under the control
}

export interface ActionSpec {
  /** Label shown in the dropdown. */
  label: string;
  /** The field list. Renderer iterates in this order. */
  fields: readonly FieldSpec[];
}

/**
 * ORDER MATTERS: the dropdown is rendered in `Object.keys(ACTION_FIELD_SPECS)`
 * order, so put the most common actions near the top.
 */
export const ACTION_FIELD_SPECS: Record<string, ActionSpec> = {
  // --- Database ------------------------------------------------------- //
  db_insert: {
    label: "Insert Record",
    fields: [
      { key: "table",  label: "Table",  kind: "text", placeholder: "users" },
      {
        key: "values",
        label: "Values",
        kind: "json",
        placeholder: '{\n  "email": "{{email}}",\n  "name": "{{name}}"\n}',
        help: "JSON object mapping column → value. Use {{var}} for process variables.",
      },
    ],
  },
  db_update: {
    label: "Update Record",
    fields: [
      { key: "table",  label: "Table",  kind: "text", placeholder: "users" },
      {
        key: "where",
        label: "Where",
        kind: "json",
        placeholder: '{\n  "id": "{{trigger.id}}"\n}',
        help: "JSON object of column → value to match rows.",
      },
      {
        key: "values",
        label: "Values",
        kind: "json",
        placeholder: '{\n  "status": "approved"\n}',
        help: "Columns to update.",
      },
    ],
  },
  db_delete: {
    label: "Delete Record",
    fields: [
      { key: "table",  label: "Table",  kind: "text", placeholder: "users" },
      {
        key: "where",
        label: "Where",
        kind: "json",
        placeholder: '{\n  "id": "{{trigger.id}}"\n}',
      },
    ],
  },
  db_query: {
    label: "DB Query",
    fields: [
      { key: "table",  label: "Table",  kind: "text", placeholder: "users" },
      {
        key: "where",
        label: "Where (optional)",
        kind: "json",
        placeholder: '{\n  "status": "active"\n}',
      },
      { key: "query", label: "Free-form query (optional)", kind: "textarea",
        placeholder: "Describe the query in plain English…" },
    ],
  },

  // --- Comm ----------------------------------------------------------- //
  send_email: {
    label: "Send Email",
    fields: [
      { key: "to",       label: "To",      kind: "text",     placeholder: "{{email}}" },
      { key: "subject",  label: "Subject", kind: "text",     placeholder: "You've been invited…" },
      {
        key: "message",
        label: "Body",
        kind: "textarea",
        placeholder: "Hi {{name}}, …",
        help: "Plain text (wrapped in <p> at send time). Use {{var}} for variables.",
      },
    ],
  },
  send_notification: {
    label: "Send Notification (in-app)",
    fields: [
      { key: "title",    label: "Title",       kind: "text", placeholder: "New application" },
      { key: "message",  label: "Message",     kind: "textarea", placeholder: "…" },
      { key: "to",       label: "User id",     kind: "text", placeholder: "{{user.id}} (optional)" },
      { key: "toRole",   label: "To role",     kind: "text", placeholder: "recruiter (optional)" },
      { key: "type",     label: "Type",        kind: "select", options: ["info", "success", "warning", "error", "email"] },
      { key: "entityId", label: "Entity id",   kind: "text", placeholder: "{{application.id}} (optional)" },
    ],
  },

  // --- HTTP ----------------------------------------------------------- //
  http_call: {
    label: "HTTP Call",
    fields: [
      { key: "url",     label: "URL",     kind: "text",   placeholder: "https://api.example.com/…" },
      { key: "method",  label: "Method",  kind: "select", options: ["GET", "POST", "PUT", "PATCH", "DELETE"] },
      { key: "headers", label: "Headers", kind: "json",   placeholder: '{\n  "Authorization": "Bearer …"\n}' },
      { key: "body",    label: "Body",    kind: "json",   placeholder: '{\n  "key": "value"\n}' },
    ],
  },

  // --- MCP ------------------------------------------------------------ //
  mcp_tool_call: {
    label: "MCP Tool Call",
    fields: [
      { key: "mcp_server_name", label: "Server name", kind: "text",
        placeholder: "Firecrawl",
        help: "Name of an enabled MCP server (Settings → MCP Servers). Resolved case-insensitively." },
      { key: "mcp_tool_name",   label: "Tool name",   kind: "text",
        placeholder: "firecrawl_search",
        help: "Tool advertised by the server." },
      { key: "args",            label: "Arguments",   kind: "json",
        placeholder: '{\n  "query": "{{identify_product.searchQuery}}",\n  "limit": 5\n}',
        help: "JSON object of tool arguments. Use {{var}} for process variables." },
    ],
  },

  // --- Compute -------------------------------------------------------- //
  custom: {
    label: "Custom Function",
    fields: [
      { key: "expression", label: "Expression",  kind: "textarea",
        placeholder: "amount * 1.1", help: "FEEL-lite expression evaluated at runtime." },
      { key: "assignTo",   label: "Assign to variable", kind: "text",
        placeholder: "computedTotal (optional)" },
    ],
  },
  set_variable: {
    label: "Set Variable",
    fields: [
      { key: "variableName", label: "Variable name", kind: "text", placeholder: "isApproved" },
      { key: "expression",   label: "Value / expression", kind: "textarea",
        placeholder: "true  •  {{trigger.amount}} > 100" },
    ],
  },
  transform: {
    label: "Transform / Map",
    fields: [
      { key: "expression", label: "Expression", kind: "textarea",
        placeholder: "Map/transform input data" },
    ],
  },

  // --- Documents ------------------------------------------------------ //
  generate_document: {
    label: "Generate Document (PDF)",
    fields: [
      { key: "title",    label: "Title",    kind: "text",     placeholder: "Invoice #{{invoice.id}}" },
      { key: "subtitle", label: "Subtitle", kind: "text",     placeholder: "(optional)" },
      { key: "footer",   label: "Footer",   kind: "text",     placeholder: "(optional)" },
      {
        key: "fields",
        label: "Fields",
        kind: "json",
        placeholder: '[\n  { "label": "Amount", "value": "{{amount}}" }\n]',
        help: "Array of {label, value} — one row per printed field.",
      },
      { key: "record", label: "Record (alt)", kind: "text", placeholder: "{{application}}",
        help: "Skip 'fields' and pass an object variable; its entries become rows." },
    ],
  },

  // --- AI ------------------------------------------------------------- //
  ai_generate: {
    label: "AI · Generate",
    fields: [
      { key: "aiInput",         label: "Input",         kind: "textarea", placeholder: "{{input}} or a prompt" },
      { key: "aiSystemPrompt",  label: "System prompt", kind: "textarea", placeholder: "You are a helpful…" },
      { key: "aiPrompt",        label: "Extra prompt",  kind: "textarea", placeholder: "(optional)" },
      { key: "aiMaxTokens",     label: "Max tokens",    kind: "text",     placeholder: "1024" },
      { key: "aiTemperature",   label: "Temperature",   kind: "text",     placeholder: "1" },
      { key: "aiModel",         label: "Model override", kind: "text",    placeholder: "(optional — else FORGE_AI_MODEL)" },
    ],
  },
  ai_classify: {
    label: "AI · Classify",
    fields: [
      { key: "aiInput",             label: "Input",            kind: "textarea", placeholder: "{{input}}" },
      { key: "aiLabels",            label: "Labels",           kind: "json",
        placeholder: '["positive","negative","neutral"]', help: "JSON array of allowed labels." },
      { key: "aiConfidenceThreshold", label: "Confidence threshold", kind: "text", placeholder: "0.7" },
      { key: "aiPrompt",            label: "Extra prompt",     kind: "textarea", placeholder: "(optional)" },
    ],
  },
  ai_extract: {
    label: "AI · Extract fields",
    fields: [
      { key: "aiInput",         label: "Input (text)",       kind: "textarea", placeholder: "{{input}}" },
      { key: "aiFileRef",       label: "File reference",     kind: "text",     placeholder: "{{cv.id}} (PDF/image)" },
      {
        key: "aiExtractFields",
        label: "Fields to extract",
        kind: "json",
        placeholder: '[\n  { "name": "email", "type": "string" }\n]',
      },
      { key: "aiSystemPrompt",  label: "System prompt",      kind: "textarea", placeholder: "(optional)" },
    ],
  },
  ai_decide: {
    label: "AI · Decide",
    fields: [
      { key: "aiContext", label: "Context",  kind: "textarea", placeholder: "{{input}}" },
      { key: "aiOptions", label: "Options",  kind: "json", placeholder: '["approve","reject"]' },
      { key: "aiRules",   label: "Rules",    kind: "json", placeholder: '["Approve when amount < 100"]' },
      { key: "aiPrompt",  label: "Extra prompt", kind: "textarea", placeholder: "(optional)" },
    ],
  },
  ocr_document: {
    label: "OCR · Document (PaddleOCR)",
    fields: [
      { key: "ocrFileRef",  label: "Document",  kind: "text",
        placeholder: "{{input}} or {{file.id}} or https://…",
        help: "Stored-file id, http(s) URL, or a {{binding}}. Sidecar fetches URLs directly; ids get uploaded as base64." },
      { key: "ocrPages",    label: "Pages",     kind: "json",
        placeholder: "[1,2,3]",
        help: "1-indexed page numbers. Omit for all pages." },
      { key: "ocrLanguage", label: "Language",  kind: "text",
        placeholder: "en",
        help: "ISO 639-1 code (en, zh, ar, …). Auto-detect when empty." },
    ],
  },
};

/**
 * Convenience list of action-type keys for the dropdown, preserving the
 * insertion order above.
 */
export const ACTION_TYPE_KEYS = Object.keys(ACTION_FIELD_SPECS) as string[];

import type {
  WorkflowDefinition,
  WorkflowNodeSerialized,
  WorkflowEdgeSerialized,
  WorkflowNodeConfig,
  TriggerConfig,
} from "@/types/workflow";

/**
 * Converts a visual workflow definition into a natural-language instruction
 * for the code_editor agent to implement inside the generated application.
 */
export function buildWorkflowInstruction(workflow: WorkflowDefinition): string {
  const { name, description, definition } = workflow;
  const { trigger, nodes, edges } = definition;

  const parts: string[] = [
    `Implement workflow "${name}" in the generated application.`,
    "",
  ];

  if (description) {
    parts.push(`Description: ${description}`, "");
  }

  // ── Trigger ──────────────────────────────────────────
  parts.push(triggerSection(trigger));

  // ── Steps ────────────────────────────────────────────
  parts.push(stepsSection(nodes, edges));

  // ── Implementation requirements ──────────────────────
  parts.push(requirementsSection(nodes));

  return parts.join("\n");
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function triggerSection(trigger: TriggerConfig): string {
  const lines: string[] = ["## Trigger"];

  switch (trigger.type) {
    case "api_event":
      lines.push(`Type: API Event`);
      if (trigger.event) lines.push(`Listen for event: ${trigger.event}`);
      break;
    case "schedule":
      lines.push(`Type: Scheduled (Cron)`);
      if (trigger.cron) lines.push(`Cron expression: ${trigger.cron}`);
      break;
    case "db_change":
      lines.push(`Type: Database Change`);
      if (trigger.model) lines.push(`Model: ${trigger.model}`);
      if (trigger.field) lines.push(`Watch field: ${trigger.field}`);
      if (trigger.condition) lines.push(`Condition: ${trigger.condition}`);
      break;
    case "webhook":
      lines.push(`Type: Webhook`);
      if (trigger.path) lines.push(`Path: ${trigger.path}`);
      break;
    case "manual":
      lines.push(`Type: Manual`);
      if (trigger.name) lines.push(`Button label: ${trigger.name}`);
      break;
  }
  lines.push("");
  return lines.join("\n");
}

function stepsSection(
  nodes: WorkflowNodeSerialized[],
  edges: WorkflowEdgeSerialized[],
): string {
  const lines: string[] = ["## Workflow Steps"];

  for (const node of nodes) {
    const { data } = node;
    const { label, nodeType, config } = data;
    lines.push(`\n### [${nodeType}] ${label} (id: ${node.id})`);
    lines.push(configDescription(nodeType, config));
  }

  // Connections
  if (edges.length > 0) {
    lines.push("\n## Connections");
    for (const edge of edges) {
      const edgeType = edge.data?.edgeType || "default";
      const sourceNode = nodes.find((n) => n.id === edge.source);
      const targetNode = nodes.find((n) => n.id === edge.target);
      const sourceName = sourceNode?.data.label || edge.source;
      const targetName = targetNode?.data.label || edge.target;
      lines.push(`- ${sourceName} → ${targetName} (${edgeType})`);
    }
  }

  lines.push("");
  return lines.join("\n");
}

function configDescription(
  nodeType: string,
  config: WorkflowNodeConfig,
): string {
  const lines: string[] = [];

  switch (nodeType) {
    case "action":
      if (config.actionType) lines.push(`  Action type: ${config.actionType}`);
      if (config.description) lines.push(`  Description: ${config.description}`);
      if (config.actionType === "db_query" && config.query)
        lines.push(`  Query: ${config.query}`);
      if (config.actionType === "http_call") {
        if (config.url) lines.push(`  URL: ${config.method || "GET"} ${config.url}`);
        if (config.body) lines.push(`  Body: ${config.body}`);
      }
      if (config.actionType === "send_email") {
        if (config.to) lines.push(`  To: ${config.to}`);
        if (config.subject) lines.push(`  Subject: ${config.subject}`);
        if (config.template) lines.push(`  Template: ${config.template}`);
      }
      break;

    case "condition":
      if (config.expression) lines.push(`  Expression: ${config.expression}`);
      if (config.conditionMode) lines.push(`  Mode: ${config.conditionMode}`);
      break;

    case "decision": {
      const dt = config.decisionTable;
      if (dt) {
        lines.push(`  Hit Policy: ${dt.hitPolicy}`);
        lines.push(`  Inputs: ${dt.inputs.map((i) => i.name).join(", ")}`);
        lines.push(`  Outputs: ${dt.outputs.map((o) => o.name).join(", ")}`);
        lines.push(`  Rules: ${dt.rules.length} rule(s)`);
        if (config.outputMapping) {
          lines.push("  Output Mapping:");
          for (const [col, variable] of Object.entries(config.outputMapping)) {
            lines.push(`    ${col} -> ${variable}`);
          }
        }
      }
      break;
    }

    case "wait":
      if (config.duration) lines.push(`  Duration: ${config.duration}`);
      break;

    case "assignment":
    case "task_pool":
      if (config.assignType) lines.push(`  Assign to: ${config.assignType}`);
      if (config.assignType === "initiator") {
        lines.push(`  Target: (auto-assigned to workflow initiator)`);
      } else if (config.assignType === "process_variable") {
        if (config.assignVariablePath) lines.push(`  Variable path: ${config.assignVariablePath}`);
      } else if (config.assignTargetName) {
        lines.push(`  Target: ${config.assignTargetName}`);
      } else if (config.assignTarget) {
        lines.push(`  Target: ${config.assignTarget}`);
      }
      if (config.slaHours) lines.push(`  SLA: ${config.slaHours} hours`);
      if (config.description) lines.push(`  Task description: ${config.description}`);
      if (config.pageId) lines.push(`  Linked page: ${config.pageName || config.pageId}`);
      break;

    case "approval":
      if (config.approvalType) lines.push(`  Approval type: ${config.approvalType}`);
      if (config.requiredApprovals)
        lines.push(`  Required approvals: ${config.requiredApprovals}`);
      if (config.assignType) lines.push(`  Assign to: ${config.assignType}`);
      if (config.assignType === "initiator") {
        lines.push(`  Target: (auto-assigned to workflow initiator)`);
      } else if (config.assignType === "process_variable") {
        if (config.assignVariablePath) lines.push(`  Variable path: ${config.assignVariablePath}`);
      } else if (config.assignTargetName) {
        lines.push(`  Target: ${config.assignTargetName}`);
      } else if (config.assignTarget) {
        lines.push(`  Target: ${config.assignTarget}`);
      }
      if (config.slaHours) lines.push(`  SLA: ${config.slaHours} hours`);
      if (config.pageId) lines.push(`  Linked page: ${config.pageName || config.pageId}`);
      break;

    case "escalation":
      if (config.slaHours) lines.push(`  Escalate after: ${config.slaHours} hours`);
      if (config.escalateTo) lines.push(`  Escalate to: ${config.escalateTo}`);
      if (config.description) lines.push(`  Description: ${config.description}`);
      break;

    case "ai_classify":
      if (config.aiInput) lines.push(`  Input: ${config.aiInput}`);
      if (config.aiLabels?.length)
        lines.push(`  Labels: [${config.aiLabels.join(", ")}]`);
      if (config.aiConfidenceThreshold !== undefined)
        lines.push(`  Confidence threshold: ${config.aiConfidenceThreshold}`);
      if (config.aiPrompt) lines.push(`  Prompt: ${config.aiPrompt}`);
      lines.push("  Output: {label, confidence, reasoning}");
      break;

    case "ai_extract":
      if (config.aiInput) lines.push(`  Input: ${config.aiInput}`);
      if (config.aiExtractFields?.length)
        lines.push(
          `  Fields: ${config.aiExtractFields.map((f) => `${f.name}: ${f.type}`).join(", ")}`,
        );
      if (config.aiPrompt) lines.push(`  Prompt: ${config.aiPrompt}`);
      lines.push("  Output: extracted data object");
      break;

    case "ai_decide":
      if (config.aiPrompt) lines.push(`  Decision prompt: ${config.aiPrompt}`);
      if (config.aiContext) lines.push(`  Context: ${config.aiContext}`);
      if (config.aiOptions?.length)
        lines.push(`  Options: [${config.aiOptions.join(", ")}]`);
      if (config.aiRules?.length) {
        lines.push("  Rules:");
        for (const r of config.aiRules) {
          lines.push(`    - ${r}`);
        }
      }
      lines.push("  Output: {decision, confidence, reasoning}");
      break;

    case "ai_generate":
      if (config.aiPrompt) lines.push(`  Prompt: ${config.aiPrompt}`);
      if (config.aiContext) lines.push(`  Context: ${config.aiContext}`);
      if (config.aiTone) lines.push(`  Tone: ${config.aiTone}`);
      if (config.aiMaxLength) lines.push(`  Max length: ${config.aiMaxLength} words`);
      if (config.description) lines.push(`  Description: ${config.description}`);
      lines.push("  Output: {text}");
      break;

    case "end":
      lines.push("  (End of workflow)");
      break;
  }

  return lines.join("\n");
}

function requirementsSection(nodes: WorkflowNodeSerialized[]): string {
  const lines: string[] = ["## Implementation Requirements"];

  lines.push("1. Create a workflow runtime file (src/workflows/runtime.ts) with an executor that walks the node graph");
  lines.push("2. Create trigger registration (src/workflows/triggers.ts) to listen for the trigger event");
  lines.push("3. Create action functions for each action node in src/workflows/actions/");
  lines.push("4. For condition nodes: evaluate the expression and branch accordingly");

  const hasAssignment = nodes.some(
    (n) => n.data.nodeType === "assignment" || n.data.nodeType === "task_pool",
  );
  const hasApproval = nodes.some((n) => n.data.nodeType === "approval");
  const hasEscalation = nodes.some((n) => n.data.nodeType === "escalation");

  if (hasAssignment || hasApproval) {
    lines.push("5. Create a tasks table in the Drizzle schema if it doesn't exist");
    lines.push("6. Add task inbox API routes: GET /api/tasks, POST /api/tasks/:id/claim, POST /api/tasks/:id/approve");

    // Check if any human-in-loop nodes have linked pages
    const linkedPageNodes = nodes.filter(
      (n) =>
        ["assignment", "approval", "task_pool"].includes(n.data.nodeType) &&
        n.data.config.pageId,
    );
    if (linkedPageNodes.length > 0) {
      lines.push("");
      lines.push("### Form-Task Auto-Binding:");
      lines.push("For each human-in-loop node with a linked page:");
      lines.push("- Pre-populate the form with workflow variables from task.input_data");
      lines.push("- On form submit, POST field values to /api/tasks/:id/complete as output_data");
      lines.push("- Fields with data-process-variable bind to that workflow variable name");
      lines.push("- Fields with data-required must be validated before submission");
      lines.push("- Navigate the user to the linked page route when they open/claim a task");
      for (const n of linkedPageNodes) {
        lines.push(`  - Node "${n.data.label}": linked to page "${n.data.config.pageName}" (pageId: ${n.data.config.pageId})`);
      }
    }
  }

  if (hasApproval) {
    lines.push("7. Implement approval logic respecting the approval type (single, sequential, parallel, threshold)");
  }

  if (hasEscalation) {
    lines.push("8. Implement SLA breach detection and escalation logic");
  }

  const hasDecisionNodes = nodes.some((n) => n.data.nodeType === "decision");

  if (hasDecisionNodes) {
    lines.push("5. For decision nodes: use the FEEL-lite expression engine and decision table evaluator from src/lib/workflow-engine/domain/feel-lite/ and decision-evaluator.ts");
    lines.push("6. Decision tables evaluate input variables against rule entries, apply hit policy, and output results");
    lines.push("7. Map decision outputs to workflow variables using the outputMapping configuration");
  }

  const hasAINodes = nodes.some((n) =>
    ["ai_classify", "ai_extract", "ai_decide", "ai_generate"].includes(n.data.nodeType),
  );

  if (hasAINodes) {
    lines.push("9. For AI nodes: use the Anthropic SDK (claude-haiku-4-5-20251001 for classification/extraction, claude-sonnet-4 for complex decisions/generation)");
    lines.push("10. AI Classify: send input text + labels to LLM, parse structured JSON response with {label, confidence, reasoning}");
    lines.push("11. AI Extract: send input text + field definitions to LLM, parse extracted values as JSON object");
    lines.push("12. AI Decide: send context + options + rules to LLM, parse {decision, confidence, reasoning}, route workflow based on decision");
    lines.push("13. AI Generate: send context + prompt to LLM, return generated text");
    lines.push("14. Store AI node results in workflow execution context for use by downstream nodes");
  }

  lines.push(`${hasAINodes ? "15" : "9"}. Store workflow definitions in src/workflows/definitions.ts`);

  return lines.join("\n");
}

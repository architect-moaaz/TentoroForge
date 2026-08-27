import type { Rule, ConditionExpression, ConditionGroup, ConditionNode, StateTransition } from "@/types/rules";

/**
 * Converts a rule definition to natural language instructions
 * for the code_editor agent.
 */
export function buildRuleInstruction(rule: Rule): string {
  switch (rule.rule_type) {
    case "validation":
      return buildValidationInstruction(rule);
    case "access":
      return buildAccessInstruction(rule);
    case "business":
      return buildBusinessInstruction(rule);
    case "computed":
      return buildComputedInstruction(rule);
    case "state_machine":
      return buildStateMachineInstruction(rule);
    case "trigger":
      return buildTriggerInstruction(rule);
    default:
      return `Apply rule "${rule.name}" with config: ${JSON.stringify(rule.config)}`;
  }
}

function buildValidationInstruction(rule: Rule): string {
  const { config, model_name, field_name } = rule;
  const parts: string[] = [];

  parts.push(`Add a validation rule "${rule.name}" on model "${model_name || "the relevant model"}".`);

  if (field_name) {
    parts.push(`Target field: "${field_name}".`);
  }

  if (config.condition) {
    parts.push(`Condition: ${conditionToText(config.condition)}.`);
  }

  if (config.errorMessage) {
    parts.push(`Error message: "${config.errorMessage}".`);
  }

  const enforcement = config.enforcement || ["api"];
  if (enforcement.includes("api")) {
    parts.push("Add server-side validation in the API route handler. Return 400 with the error message if validation fails.");
  }
  if (enforcement.includes("ui")) {
    parts.push("Add client-side validation in the form component. Show inline error message.");
  }
  if (enforcement.includes("db")) {
    parts.push("Add a database-level check constraint in the Drizzle schema.");
  }

  return parts.join(" ");
}

function buildAccessInstruction(rule: Rule): string {
  const { config, model_name } = rule;
  const parts: string[] = [];

  parts.push(`Add access control rule "${rule.name}" on model "${model_name || "the relevant model"}".`);

  const actions = config.actions || {};
  for (const [roleId, perms] of Object.entries(actions)) {
    const allowed = Object.entries(perms)
      .filter(([, v]) => v === "allow")
      .map(([a]) => a);
    const denied = Object.entries(perms)
      .filter(([, v]) => v === "deny")
      .map(([a]) => a);

    if (allowed.length > 0) {
      parts.push(`Role "${roleId}": allow ${allowed.join(", ")}.`);
    }
    if (denied.length > 0) {
      parts.push(`Role "${roleId}": deny ${denied.join(", ")}.`);
    }
  }

  parts.push("Implement middleware or route guards to enforce these access rules.");
  parts.push("Check the current user's role before allowing the operation.");

  return parts.join(" ");
}

function buildBusinessInstruction(rule: Rule): string {
  const { config, model_name } = rule;
  const trigger = config.triggerAction || "create/update";
  const parts: string[] = [];

  parts.push(`Add business rule "${rule.name}" on model "${model_name || "the relevant model"}".`);
  parts.push(`Triggered on: ${trigger}.`);

  if (config.condition) {
    parts.push(`Condition: ${conditionToText(config.condition)}.`);
  }

  if (config.consequence) {
    parts.push(`When the condition is met: ${config.consequence}.`);
  }

  parts.push(`Implement this logic in the API route handler for ${trigger} operations.`);

  return parts.join(" ");
}

function buildComputedInstruction(rule: Rule): string {
  const { config, model_name } = rule;
  const parts: string[] = [];

  parts.push(`Add computed field rule "${rule.name}" on model "${model_name || "the relevant model"}".`);

  if (config.targetField) {
    parts.push(`Computed field: "${config.targetField}".`);
  }

  if (config.expression) {
    parts.push(`Expression: ${config.expression}.`);
  }

  parts.push("Add a getter or computed property that calculates this value.");
  parts.push("Include the computed value in API responses.");
  parts.push("Make sure the field is read-only in forms.");

  return parts.join(" ");
}

function buildStateMachineInstruction(rule: Rule): string {
  const { config, model_name, field_name } = rule;
  const states = config.states || [];
  const transitions = config.transitions || [];
  const stateField = field_name || config.stateField || "status";
  const parts: string[] = [];

  parts.push(`Add state machine rule "${rule.name}" on model "${model_name || "the relevant model"}".`);
  parts.push(`State field: "${stateField}".`);
  parts.push(`Valid states: ${states.map((s) => `"${s}"`).join(", ")}.`);

  if (transitions.length > 0) {
    parts.push("Valid transitions:");
    for (const t of transitions) {
      let line = `  "${t.from}" -> "${t.to}"`;
      if (t.label) line += ` (${t.label})`;
      if (t.condition) line += ` when ${t.condition}`;
      parts.push(line);
    }
  }

  parts.push("Create a state enum type in the Drizzle schema.");
  parts.push("Add transition validation in the API update handler — reject invalid state transitions with a 400 error.");
  parts.push("Add a visual status indicator in the UI.");

  return parts.join("\n");
}

function buildTriggerInstruction(rule: Rule): string {
  const { config, model_name, field_name } = rule;
  const parts: string[] = [];

  parts.push(`Add trigger rule "${rule.name}" on model "${model_name || "the relevant model"}".`);

  const watchField = field_name || config.watchField;
  if (watchField) {
    parts.push(`Watch field: "${watchField}".`);
  } else {
    parts.push("Triggered on any field change.");
  }

  if (config.condition) {
    parts.push(`Condition: ${conditionToText(config.condition)}.`);
  }

  if (config.actionDescription) {
    parts.push(`Action: ${config.actionDescription}.`);
  }

  parts.push("Implement this as a post-save hook or event handler in the API.");
  parts.push("The trigger should execute after the record is successfully saved.");

  return parts.join(" ");
}

// ---------------------------------------------------------------------------
// Condition serialization helpers
// ---------------------------------------------------------------------------

function isGroup(expr: ConditionExpression): expr is ConditionGroup {
  return "logic" in expr;
}

function conditionToText(expr: ConditionExpression): string {
  if (isGroup(expr)) {
    const inner = expr.conditions.map(conditionToText).join(` ${expr.logic} `);
    return `(${inner})`;
  }

  const node = expr as ConditionNode;
  const op = operatorToText(node.operator);
  if (["is_null", "is_not_null"].includes(node.operator)) {
    return `${node.field} ${op}`;
  }
  return `${node.field} ${op} "${node.value}"`;
}

function operatorToText(op: string): string {
  const map: Record<string, string> = {
    equals: "equals",
    not_equals: "does not equal",
    gt: "is greater than",
    gte: "is greater than or equal to",
    lt: "is less than",
    lte: "is less than or equal to",
    in: "is one of",
    not_in: "is not one of",
    is_null: "is null",
    is_not_null: "is not null",
    matches_regex: "matches regex",
    contains: "contains",
    starts_with: "starts with",
    ends_with: "ends with",
  };
  return map[op] || op;
}

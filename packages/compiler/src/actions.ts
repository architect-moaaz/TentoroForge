/**
 * Action Emitter — converts IR action definitions to JavaScript code strings.
 */

import type { ActionDef } from "@tentoroforge/ir";
import { EmitContext } from "./context.js";

/**
 * Emits the JavaScript code for an action.
 * Returns a statement (or multiple statements for sequence).
 */
export function emitAction(
  action: ActionDef,
  ctx: EmitContext,
  argName?: string,
): string {
  switch (action.type) {
    case "navigate": {
      ctx.ensureImport("next/navigation", "useRouter");
      ctx.addHookCall("const router = useRouter();");
      const to = resolveTemplatePath(action.to, argName);
      return `router.push(${to})`;
    }

    case "setState": {
      const stateKey = action.path.split(".")[0];
      const setter = `set${stateKey.charAt(0).toUpperCase()}${stateKey.slice(1)}`;

      if (action.path.includes(".")) {
        // Nested state update
        const parts = action.path.split(".");
        const value = resolveActionValue(action.value, argName);
        return `${setter}((prev) => ({ ...prev, ${parts.slice(1).join(".")}: ${value} }))`;
      }

      const value = resolveActionValue(action.value, argName);
      return `${setter}(${value})`;
    }

    case "mutate": {
      const hookName = `${action.source}Mutate`;
      let code = `${hookName}.mutate(${argName || ""})`;
      if (action.confirm) {
        code = `if (window.confirm(${JSON.stringify(action.confirm)})) { ${code} }`;
      }
      return code;
    }

    case "openModal": {
      const stateName = `${action.modal}Open`;
      const setter = `set${stateName.charAt(0).toUpperCase()}${stateName.slice(1)}`;
      ctx.addState(stateName, "boolean", "false");
      ctx.ensureImport("react", "useState");
      return `${setter}(true)`;
    }

    case "closeModal": {
      const modalName = action.modal || "modal";
      const stateName = `${modalName}Open`;
      const setter = `set${stateName.charAt(0).toUpperCase()}${stateName.slice(1)}`;
      return `${setter}(false)`;
    }

    case "toast": {
      ctx.ensureImport("sonner", "toast");
      const variant = action.variant || "success";
      const message = action.message;
      if (action.id) {
        return `toast.${variant}(${JSON.stringify(message)}, { id: ${JSON.stringify(action.id)} })`;
      }
      return `toast.${variant}(${JSON.stringify(message)})`;
    }

    case "invalidate": {
      ctx.ensureImport("@tanstack/react-query", "useQueryClient");
      ctx.addHookCall("const queryClient = useQueryClient();");
      const keys = action.sources.map((s) => JSON.stringify(s)).join(", ");
      return `queryClient.invalidateQueries({ queryKey: [${keys}] })`;
    }

    case "sequence": {
      const steps = action.steps.map((s) => emitAction(s, ctx, argName));
      return steps.join(";\n");
    }

    case "custom": {
      return `(${action.code})${argName ? `({ ${argName}, state })` : "()"}`;
    }

    default:
      return `/* unknown action type: ${(action as ActionDef).type} */`;
  }
}

/**
 * Wraps an action as an onClick handler string.
 * Returns the full `() => { ... }` expression.
 */
export function emitActionHandler(
  action: ActionDef,
  ctx: EmitContext,
  argName?: string,
): string {
  const body = emitAction(action, ctx, argName);

  // For single statements, use arrow shorthand
  if (!body.includes("\n") && !body.includes(";")) {
    if (argName) {
      return `(${argName}) => ${body}`;
    }
    return `() => ${body}`;
  }

  // Multiple statements
  if (argName) {
    return `(${argName}) => {\n  ${body}\n}`;
  }
  return `() => {\n  ${body}\n}`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveTemplatePath(path: string, argName?: string): string {
  if (path.includes("{{")) {
    // Convert {{row.id}} to template literal
    const resolved = path.replace(/\{\{(.+?)\}\}/g, (_match, inner) => {
      const variable = inner.trim();
      if (variable.startsWith("row.") && argName) {
        return `\${${argName}.${variable.slice(4)}}`;
      }
      if (variable.startsWith("item.") && argName) {
        return `\${${argName}.${variable.slice(5)}}`;
      }
      return `\${${variable}}`;
    });
    return `\`${resolved}\``;
  }
  return JSON.stringify(path);
}

function resolveActionValue(
  value: string | number | boolean | null,
  argName?: string,
): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return String(value);
  if (typeof value === "number") return String(value);

  // String values — check for template expressions
  if (typeof value === "string" && value.includes("{{")) {
    return value.replace(/\{\{(.+?)\}\}/g, (_match, inner) => {
      const variable = inner.trim();
      if (variable.startsWith("row.") && argName) {
        return `${argName}.${variable.slice(4)}`;
      }
      if (variable.startsWith("item.") && argName) {
        return `${argName}.${variable.slice(5)}`;
      }
      return variable;
    });
  }

  return JSON.stringify(value);
}

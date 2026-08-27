/**
 * Button `onClick: {kind: "compute", target, formula}` — the imperative
 * counterpart to `interaction.computed`.
 *
 * Where a computed field recomputes REACTIVELY on any dependency
 * change, a compute action fires WHEN THE BUTTON IS CLICKED. Use for
 * calculator '=' key, "Calculate EMI" button, "Generate password".
 *
 * The library Button component wires `runComputeAction` into its
 * onClick handler when action.kind === "compute": it grabs the form's
 * current values via react-hook-form's `getValues`, evaluates the
 * formula, and calls `setValue(target, result)`. That's it — the
 * dispatcher stays pure so it's trivially testable.
 */

import { evaluateComputed } from "./formInteraction";

export interface ComputeAction {
  kind: "compute";
  target: string;
  formula: string;
}

export interface ComputeActionEnvelope {
  ok: boolean;
  target?: string;
  value?: unknown;
  error?: string;
}

/**
 * Pure kernel — evaluate a formula against a values map and return the
 * next value for the target field. Never throws.
 */
export function runComputeAction(
  action: ComputeAction,
  values: Record<string, unknown>,
): ComputeActionEnvelope {
  if (!action || action.kind !== "compute") {
    return { ok: false, error: "action.kind must be 'compute'" };
  }
  if (!action.target || typeof action.target !== "string") {
    return { ok: false, error: "action.target is required" };
  }
  if (!action.formula || typeof action.formula !== "string") {
    return { ok: false, error: "action.formula is required" };
  }
  try {
    const value = evaluateComputed(action.formula, values);
    return { ok: true, target: action.target, value };
  } catch (err) {
    return {
      ok: false,
      target: action.target,
      error: err instanceof Error ? err.message : "compute failed",
    };
  }
}

/**
 * Convenience: bind a compute action to a form's `getValues`/`setValue`
 * pair so a click handler can call the returned function with no args.
 * The library's Button component uses this shape when the Form ancestor
 * exposes a compute controller via context.
 */
export function bindComputeAction(
  action: ComputeAction,
  ctx: {
    getValues: () => Record<string, unknown>;
    setValue: (name: string, value: unknown) => void;
  },
): () => ComputeActionEnvelope {
  return () => {
    const values = ctx.getValues() ?? {};
    const envelope = runComputeAction(action, values);
    if (envelope.ok && envelope.target !== undefined) {
      ctx.setValue(envelope.target, envelope.value);
    }
    return envelope;
  };
}

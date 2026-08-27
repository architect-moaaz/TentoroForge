/**
 * SUBMIT-AUTHORITY input assembly — Slice A T9 + Slice E FEEL-lite integration.
 *
 * Given a workflow definition with `inputs[].source` declarations, assemble
 * the dispatch payload from the five resolvable source kinds:
 *
 *   form_field   ← the submitting form's field value
 *   route        ← a URL param on the source page
 *   auth         ← a claim on the current auth session
 *   static       ← literal or template ("{{now}}", "{{uuid}}")
 *   computed     ← FEEL-lite expression over already-resolved inputs
 *
 * Any required input with no resolved value returns as an error — the
 * caller refuses dispatch.
 *
 * This is a pure helper — no network, no side effects. The engine (or the
 * generated Form's onSubmit handler) calls this to build the dispatch
 * payload, then hands it to executeWorkflow.
 */

// FEEL-lite lives at src/lib/feel-lite (shipped alongside runtime/workflows
// by runtime_injector.py). Relative import mirrors what the generated app
// sees on disk: workflows/*.ts → ../feel-lite.
import { evaluateExpression } from "../feel-lite";

export type WorkflowInputSource =
  | { kind: "form_field"; field: string }
  | { kind: "route"; param: string }
  | { kind: "auth"; claim: string }
  | { kind: "static"; value: string }
  | { kind: "computed"; expression: string };

export interface WorkflowInputDef {
  name: string;
  type?: string;
  required?: boolean;
  source?: WorkflowInputSource;
}

export interface AssemblyContext {
  form?: Record<string, unknown>;
  route?: Record<string, string | undefined>;
  auth?: {
    user?: { id?: string; email?: string; roles?: string[] };
    tenant?: { id?: string };
    [k: string]: unknown;
  };
}

export interface AssemblyError {
  input: string;
  reason:
    | "missing_source"
    | "form_field_missing"
    | "route_param_missing"
    | "auth_claim_missing"
    | "unknown_source_kind"
    | "computed_unsupported"
    | "computed_failed";
  detail?: string;
}

export interface AssemblyResult {
  inputs: Record<string, unknown>;
  errors: AssemblyError[];
}

/**
 * Assemble the dispatch payload for a workflow given a submission context.
 * Never throws — returns errors as part of the result so the caller can
 * surface them cleanly (toast, chip, log).
 */
export function assembleWorkflowInputs(
  inputs: WorkflowInputDef[] | undefined,
  ctx: AssemblyContext,
): AssemblyResult {
  const result: Record<string, unknown> = {};
  const errors: AssemblyError[] = [];

  if (!Array.isArray(inputs) || inputs.length === 0) {
    return { inputs: result, errors };
  }

  for (const inp of inputs) {
    if (!inp || typeof inp.name !== "string" || !inp.name) continue;
    const required = Boolean(inp.required);
    const src = inp.source;

    if (!src || typeof src !== "object" || typeof (src as any).kind !== "string") {
      if (required) {
        errors.push({
          input: inp.name,
          reason: "missing_source",
          detail: "required input has no source declaration",
        });
      }
      continue;
    }

    switch (src.kind) {
      case "form_field": {
        const value = ctx.form?.[src.field];
        if (value === undefined || value === null || value === "") {
          if (required) {
            errors.push({
              input: inp.name,
              reason: "form_field_missing",
              detail: `form field '${src.field}' has no value`,
            });
          }
        } else {
          result[inp.name] = value;
        }
        break;
      }
      case "route": {
        const value = ctx.route?.[src.param];
        if (value === undefined || value === null || value === "") {
          if (required) {
            errors.push({
              input: inp.name,
              reason: "route_param_missing",
              detail: `route param '${src.param}' not present`,
            });
          }
        } else {
          result[inp.name] = value;
        }
        break;
      }
      case "auth": {
        const value = resolveAuthClaim(ctx.auth, src.claim);
        if (value === undefined || value === null || value === "") {
          if (required) {
            errors.push({
              input: inp.name,
              reason: "auth_claim_missing",
              detail: `auth claim '${src.claim}' not present`,
            });
          }
        } else {
          result[inp.name] = value;
        }
        break;
      }
      case "static": {
        result[inp.name] = expandStatic(src.value);
        break;
      }
      case "computed": {
        // FEEL-lite expression over form/route/auth/static values.
        // Mined from the retired workflow-engine tree; now first-class
        // in the live runtime.
        try {
          const value = evaluateComputedSource(
            (src as any).expression,
            ctx,
            result,   // already-resolved inputs available in expression
          );
          if (value === undefined || value === null || value === "") {
            if (required) {
              errors.push({
                input: inp.name,
                reason: "computed_failed",
                detail: `computed source resolved to empty (expression: ${(src as any).expression})`,
              });
            }
          } else {
            result[inp.name] = value;
          }
        } catch (e) {
          errors.push({
            input: inp.name,
            reason: "computed_failed",
            detail: `computed source failed to evaluate: ${(e as Error).message}`,
          });
        }
        break;
      }
      default: {
        errors.push({
          input: inp.name,
          reason: "unknown_source_kind",
          detail: `source.kind=${(src as any).kind} — must be one of ` +
                  `form_field, route, auth, static`,
        });
      }
    }
  }

  return { inputs: result, errors };
}

/**
 * Dotted-path lookup on the auth context — `user.id`, `tenant.id`,
 * `user.roles`. Returns undefined when the path is missing.
 */
function resolveAuthClaim(auth: AssemblyContext["auth"], claim: string): unknown {
  if (!auth || typeof claim !== "string") return undefined;
  const parts = claim.split(".");
  let cur: any = auth;
  for (const p of parts) {
    if (cur === null || cur === undefined) return undefined;
    cur = cur[p];
  }
  return cur;
}

/**
 * Expand a static-source value's template. Currently supports:
 *   {{now}}   → ISO-8601 timestamp of assembly time
 *   {{uuid}}  → crypto.randomUUID()
 * Anything else is returned verbatim.
 */
function expandStatic(value: string): string {
  if (value === "{{now}}") return new Date().toISOString();
  if (value === "{{uuid}}") {
    try {
      return crypto.randomUUID();
    } catch {
      // Fallback for environments without crypto.randomUUID
      return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === "x" ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      });
    }
  }
  return value;
}

/**
 * Evaluate a FEEL-lite `computed` source. The expression sees:
 *   - form.*                — every submitted form value
 *   - route.*               — every URL param
 *   - auth.*                — every auth claim
 *   - inputs.*              — already-resolved workflow inputs (from
 *                             earlier in the same assembly pass — order-
 *                             dependent; only inputs listed BEFORE this
 *                             one in the workflow's inputs[] are visible)
 *
 * Example expressions:
 *   inputs.rating >= 4                  → true/false
 *   auth.user.roles[0]                  → "recruiter"
 *   form.firstName + " " + form.lastName → "Ada Lovelace"
 */
function evaluateComputedSource(
  expression: string,
  ctx: AssemblyContext,
  resolvedInputs: Record<string, unknown>,
): unknown {
  if (typeof expression !== "string" || !expression.trim()) return null;
  const feelCtx = {
    form:   ctx.form   ?? {},
    route:  ctx.route  ?? {},
    auth:   ctx.auth   ?? {},
    inputs: resolvedInputs,
  };
  return evaluateExpression(expression, feelCtx);
}

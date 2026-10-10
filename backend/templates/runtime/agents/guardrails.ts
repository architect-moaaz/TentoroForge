/**
 * Agent guardrails — input and output validation. Forge runtime — do not remove.
 *
 * Pure functions: no I/O, so what refuses a message is testable on its own.
 */
import type { GuardrailSpec, InputGuardrails, OutputGuardrails, OutputRule } from "./types";

export interface Verdict {
  ok: boolean;
  reason?: string;
}

/** A pattern from the definition, case-insensitive. A pattern that is not a valid
 *  regex is treated as a literal substring — never as "no rule". */
function matcher(source: string): RegExp {
  // Allow the Python-style inline flag the planner tends to write: "(?i)foo".
  const stripped = source.replace(/^\(\?i\)/, "");
  try {
    return new RegExp(stripped, "i");
  } catch {
    return new RegExp(stripped.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
  }
}

export function validateInput(text: string, rules: InputGuardrails, signedIn: boolean): Verdict {
  if (rules.requireAuth && !signedIn) {
    return { ok: false, reason: "Please sign in to use the assistant." };
  }
  if (text.length > rules.maxLength) {
    return { ok: false, reason: `That message is too long (limit ${rules.maxLength} characters).` };
  }
  for (const p of rules.blockPatterns) {
    if (matcher(p).test(text)) {
      return { ok: false, reason: "That message contains something the assistant can't act on." };
    }
  }
  return { ok: true };
}

const STRICT_PATTERNS: RegExp[] = [
  /\b\d{3}-\d{2}-\d{4}\b/, // SSN
  /\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b/, // card number
];

export function validateOutput(text: string, rules: OutputGuardrails): Verdict {
  for (const p of rules.blockPatterns) {
    if (matcher(p).test(text)) {
      return { ok: false, reason: "The answer would have contained something it must not show." };
    }
  }
  if (rules.contentFilter === "strict") {
    for (const re of STRICT_PATTERNS) {
      if (re.test(text)) {
        return { ok: false, reason: "The answer would have contained sensitive data." };
      }
    }
  }
  return { ok: true };
}

/**
 * Output rules read what the tools returned: `identify_product.confidence >= 0.5`.
 * Each tool's latest result is a variable named for the tool. A rule that cannot be
 * evaluated (a tool that never ran, a bad expression) is NOT treated as a pass for
 * an expression that errors — but a rule about a tool that was never called is
 * skipped, because the answer did not rest on it.
 */
export function checkOutputRules(
  rules: OutputRule[],
  results: Record<string, unknown>,
  evalExpression: ((expr: string, scope: Record<string, unknown>) => unknown) | undefined,
): Verdict {
  if (!evalExpression) return { ok: true };
  for (const rule of rules) {
    const root = rule.expression.match(/[A-Za-z_][A-Za-z0-9_]*/)?.[0];
    if (root && !(root in results)) continue;
    let value: unknown;
    try {
      value = evalExpression(rule.expression, results);
    } catch {
      return { ok: false, reason: rule.message ?? `The check "${rule.name}" could not be evaluated.` };
    }
    if (value === false) {
      return { ok: false, reason: rule.message ?? `The check "${rule.name}" did not pass.` };
    }
  }
  return { ok: true };
}

export function defaultGuardrails(): GuardrailSpec {
  return {
    input: { maxLength: 2000, blockPatterns: ["ignore (all )?previous instructions"], requireAuth: true },
    output: { blockPatterns: [], contentFilter: "standard" },
    outputRules: [],
  };
}

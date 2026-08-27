/**
 * Slice B — resolveInputMap
 *
 * Pure resolver that turns a declared `input_map` (from ACTION-AUTHORITY
 * page.actions[].input_map or the equivalent on a Button emitted from
 * that declaration) into the concrete args a workflow dispatch expects.
 *
 * Each entry in the map has shape `{kind, ...}`. The five kinds the plan
 * validator accepts:
 *   - "route"      → route param, looked up in ctx.routeParams
 *   - "auth"       → auth claim, looked up in ctx.authClaims
 *   - "static"     → literal value; supports `{{now}}` / `{{uuid}}` sugar
 *   - "form_field" → form field value, looked up in ctx.formValues
 *   - "computed"   → FEEL-lite expression (v2 — not resolved here yet;
 *                    entry is skipped and reported as unresolved)
 *
 * Unresolved entries are surfaced via the `unresolved` array so callers
 * (Button, the tester harness) can decide whether to bail, warn, or
 * dispatch with partial args. `resolveInputMap` NEVER throws — a bad
 * spec becomes an `unresolved` entry, not an exception.
 */

export type InputSourceSpec =
  | { kind: "route";      param: string }
  | { kind: "auth";       claim: string }
  | { kind: "static";     value: unknown }
  | { kind: "form_field"; field: string }
  | { kind: "computed";   expression: string };

export interface InputMapContext {
  /** URL path params, e.g. `{ id: "abc-123" }` from Next's useParams(). */
  routeParams?: Record<string, unknown>;
  /** Auth session claims, e.g. `{ "user.id": "u_1", role: "admin" }`. */
  authClaims?: Record<string, unknown>;
  /** Form field values from the enclosing form (only set when the
   *  button lives inside a form). */
  formValues?: Record<string, unknown>;
  /** Optional now() override for tests. Defaults to Date.now(). */
  now?: () => string;
  /** Optional uuid() override for tests. */
  uuid?: () => string;
}

export interface ResolvedInputs {
  args: Record<string, unknown>;
  unresolved: Array<{ name: string; reason: string }>;
}

const KNOWN_KINDS = new Set([
  "route", "auth", "static", "form_field", "computed",
]);

/**
 * Resolve one input_map entry. Returns `[value, undefined]` on success
 * or `[undefined, reason]` on failure. Never throws.
 */
function resolveEntry(
  spec: InputSourceSpec | unknown,
  ctx: InputMapContext,
): [unknown, undefined] | [undefined, string] {
  if (!spec || typeof spec !== "object") {
    return [undefined, "spec must be an object"];
  }
  const s = spec as Record<string, unknown>;
  const kind = s.kind as string | undefined;
  if (!kind || !KNOWN_KINDS.has(kind)) {
    return [undefined, `unknown source kind ${JSON.stringify(kind)}`];
  }

  if (kind === "route") {
    const param = s.param as string | undefined;
    if (!param) return [undefined, "route source needs a `param` key"];
    const val = ctx.routeParams?.[param];
    if (val === undefined || val === null || val === "") {
      return [undefined, `route param ${JSON.stringify(param)} not in context`];
    }
    return [val, undefined];
  }

  if (kind === "auth") {
    const claim = s.claim as string | undefined;
    if (!claim) return [undefined, "auth source needs a `claim` key"];
    const val = ctx.authClaims?.[claim];
    if (val === undefined || val === null || val === "") {
      return [undefined, `auth claim ${JSON.stringify(claim)} not in context`];
    }
    return [val, undefined];
  }

  if (kind === "form_field") {
    const field = s.field as string | undefined;
    if (!field) return [undefined, "form_field source needs a `field` key"];
    const val = ctx.formValues?.[field];
    if (val === undefined) {
      // A form field may legitimately be empty string; only truly absent
      // fields count as unresolved.
      return [undefined, `form field ${JSON.stringify(field)} not in context`];
    }
    return [val, undefined];
  }

  if (kind === "static") {
    const raw = s.value;
    if (typeof raw === "string") {
      return [expandStaticSugar(raw, ctx), undefined];
    }
    return [raw, undefined];
  }

  // kind === "computed": v2, not resolved here.
  return [undefined, "computed sources are not resolved yet"];
}

/**
 * Expand the two `{{...}}` templates the plan-prompt sanctions in
 * static values. Everything else passes through unchanged.
 */
function expandStaticSugar(raw: string, ctx: InputMapContext): string {
  if (raw === "{{now}}") {
    return (ctx.now ? ctx.now() : new Date().toISOString());
  }
  if (raw === "{{uuid}}") {
    if (ctx.uuid) return ctx.uuid();
    // Basic RFC4122-ish v4 fallback. Not crypto-random — tests should
    // inject a stub via ctx.uuid. But in the browser we prefer
    // crypto.randomUUID when available.
    if (
      typeof globalThis !== "undefined"
      && typeof (globalThis as { crypto?: { randomUUID?: () => string } }).crypto?.randomUUID === "function"
    ) {
      return (globalThis as { crypto: { randomUUID: () => string } }).crypto.randomUUID();
    }
    // Non-cryptographic fallback for old runtimes / SSR: acceptable
    // because static:{{uuid}} is meant for demo/testing, not identity.
    return "00000000-0000-4000-8000-000000000000";
  }
  return raw;
}

/**
 * Resolve an entire `input_map` against the given context.
 * Contract:
 *   - never throws
 *   - unresolved entries land in `result.unresolved`
 *   - resolved entries land in `result.args`
 *   - iteration order matches the map's key order so a caller can log
 *     unresolved entries in a stable order
 */
export function resolveInputMap(
  inputMap: Record<string, unknown> | null | undefined,
  ctx: InputMapContext,
): ResolvedInputs {
  const args: Record<string, unknown> = {};
  const unresolved: Array<{ name: string; reason: string }> = [];
  if (!inputMap || typeof inputMap !== "object") {
    return { args, unresolved };
  }
  for (const [name, spec] of Object.entries(inputMap)) {
    if (!name) continue;
    const [value, reason] = resolveEntry(spec, ctx);
    if (reason !== undefined) {
      unresolved.push({ name, reason });
      continue;
    }
    args[name] = value;
  }
  return { args, unresolved };
}

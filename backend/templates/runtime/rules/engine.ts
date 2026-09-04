/**
 * Rule Engine — runtime evaluation of project rules.
 *
 * Loads ProjectRule definitions from /rules/*.json and provides:
 * - validateField(model, field, value) — checks validation rules
 * - canAccessField(model, field, action, user) — checks access rules
 * - evaluateBusinessRule(model, ruleName, entity) — runs business expressions
 * - canTransition(model, field, from, to, user) — state machine check
 */

import { evaluateExpression } from "../feel-lite";
import type {
  ProjectRule,
  ValidationRuleConfig,
  AccessRuleConfig,
  BusinessRuleConfig,
  ComputedFieldConfig,
  StateMachineConfig,
  ValidationResult,
  AccessCheckResult,
  ConditionActionConfig,
  RuleAction,
  RuleSetResult,
  FieldHint,
} from "./types";

/**
 * Rule cache loaded from /rules/*.json files.
 */
let ruleCache: ProjectRule[] = [];
let rulesLoaded = false;

/**
 * Load rules from a directory or in-memory array.
 * Generated apps typically read from /rules/index.json at boot.
 */
export function setRules(rules: ProjectRule[]): void {
  ruleCache = rules;
  rulesLoaded = true;
}

/**
 * Is this rule active?
 *
 * ONE definition, used by every filter in this file. `is_active` used to be
 * read two ways: `r.is_active` (truthy) in the validation/access/computed
 * filters, and `r.is_active !== false` in loadRules and the condition_action
 * filters. A rule with `is_active` absent, null or undefined — which is what a
 * hand-edited rules/index.json and several generator paths produce — was
 * therefore ACTIVE for some rule types and INACTIVE for others, in the same
 * process, from the same cache. Absent means active: the cache is already
 * filtered on load, so anything still in it is enabled unless explicitly
 * switched off.
 */
export function isRuleActive(r: { is_active?: unknown }): boolean {
  return r.is_active !== false;
}

export async function loadRules(rulesDir?: string): Promise<ProjectRule[]> {
  if (rulesLoaded) return ruleCache;

  // In Node.js (server-side), try to load from filesystem
  if (typeof process !== "undefined" && process.versions?.node) {
    try {
      const { promises: fs } = await import("fs");
      const path = await import("path");
      // Try both locations — the app-root `rules/` (local `next start`/dev) AND
      // `src/rules/` (bundled into serverless functions on Vercel, where the
      // root `rules/` dir isn't traced). First readable dir wins.
      const candidates = rulesDir
        ? [rulesDir]
        : [path.join(process.cwd(), "rules"), path.join(process.cwd(), "src", "rules")];
      const rules: ProjectRule[] = [];
      let loadedAny = false;
      for (const dir of candidates) {
        let files: string[];
        try {
          files = await fs.readdir(dir);
        } catch {
          continue; // dir missing here — try the next candidate
        }
        for (const file of files) {
          if (!file.endsWith(".json")) continue;
          try {
            const content = await fs.readFile(path.join(dir, file), "utf-8");
            const parsed = JSON.parse(content);
            if (Array.isArray(parsed)) rules.push(...parsed);
            else rules.push(parsed);
            loadedAny = true;
          } catch {
            /* skip an unreadable/malformed rules file rather than disabling all rules */
          }
        }
        if (loadedAny) break;
      }
      ruleCache = rules.filter(isRuleActive);
    } catch {
      ruleCache = [];
    }
  }

  rulesLoaded = true;
  return ruleCache;
}

// ---------------------------------------------------------------------------
// Field Validation
// ---------------------------------------------------------------------------

/**
 * Validate a field value against all matching validation rules.
 *
 * Used in:
 * - API routes (server-side) before DB write
 * - Form components (client-side) before submit
 */
export async function validateField(
  modelName: string,
  fieldName: string,
  value: unknown,
  context: Record<string, unknown> = {},
): Promise<ValidationResult> {
  await loadRules();

  const rules = ruleCache.filter(
    (r) =>
      r.rule_type === "validation" &&
      r.model_name === modelName &&
      r.field_name === fieldName &&
      isRuleActive(r),
  );

  const errors: string[] = [];

  for (const rule of rules) {
    const config = rule.config as ValidationRuleConfig;
    const ruleValid = checkValidation(value, config, { ...context, value });
    if (!ruleValid) {
      errors.push(config.errorMessage || `${rule.name} failed`);
    }
  }

  return { valid: errors.length === 0, errors };
}

/**
 * Validate an entire entity against all field validation rules.
 */
export async function validateEntity(
  modelName: string,
  entity: Record<string, unknown>,
  opts: { onlySubmittedFields?: boolean } = {},
): Promise<ValidationResult> {
  await loadRules();

  const errors: string[] = [];

  // Run field-level validations over the union of SUBMITTED fields and every
  // field this model has a validation rule for.
  //
  // Iterating only `Object.entries(entity)` meant validation was driven by the
  // payload rather than by the rules: a required field the caller OMITTED
  // ENTIRELY was never visited, so `required` was trivially bypassable by
  // leaving the key out. Only a present-but-empty value was caught. Every API
  // route and the data-engine create path go through here, so an omitted
  // required column reached the database unchecked.
  //
  // EXCEPTION: partial UPDATEs must restrict to submitted fields — a
  // `{status: "processing"}` update should not fail because `originalFilename`
  // is required (the DB row already has it). Callers pass `onlySubmittedFields`.
  const ruledFields = new Set<string>();
  if (!opts.onlySubmittedFields) {
    for (const r of ruleCache) {
      if (
        r.rule_type === "validation" &&
        r.model_name === modelName &&
        r.field_name &&
        isRuleActive(r)
      ) {
        ruledFields.add(r.field_name);
      }
    }
  }

  const fields = new Set<string>([...Object.keys(entity), ...ruledFields]);
  for (const field of fields) {
    // `undefined` for an absent key is exactly what `required` must reject.
    const result = await validateField(modelName, field, entity[field], entity);
    errors.push(...result.errors);
  }

  // Run model-level rules (no field_name)
  const modelRules = ruleCache.filter(
    (r) =>
      r.rule_type === "validation" &&
      r.model_name === modelName &&
      !r.field_name &&
      isRuleActive(r),
  );

  for (const rule of modelRules) {
    const config = rule.config as ValidationRuleConfig;
    if (config.expression) {
      try {
        const result = evaluateExpression(config.expression, entity as any);
        if (!result) {
          errors.push(config.errorMessage || `${rule.name} failed`);
        }
      } catch (err) {
        errors.push(`${rule.name}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
  }

  return { valid: errors.length === 0, errors };
}

function checkValidation(
  value: unknown,
  config: ValidationRuleConfig,
  context: Record<string, unknown>,
): boolean {
  // Required check
  if (config.required && (value === null || value === undefined || value === "")) {
    return false;
  }

  // Skip other checks if value is empty and not required
  if (value === null || value === undefined || value === "") {
    return true;
  }

  // Pattern (regex) check
  if (config.pattern) {
    try {
      if (!new RegExp(config.pattern).test(String(value))) return false;
    } catch {
      return false;
    }
  }

  // Min / max for strings (length) and numbers (value).
  //
  // Values often arrive as numeric-looking strings ("0.95", "42") when
  // they're pulled from a workflow variable that flowed through template
  // interpolation. Without coercion, a range check like `min:0, max:1`
  // on "0.95" measures string LENGTH (4) — falsely failing the rule.
  // Coerce when both bounds look numeric and the string parses cleanly;
  // fall back to length-check for genuinely string-typed rules.
  const isNumericRange =
    typeof config.min === "number" && typeof config.max === "number" ||
    (config.min === undefined && typeof config.max === "number") ||
    (config.max === undefined && typeof config.min === "number");
  let cmpValue: unknown = value;
  if (isNumericRange && typeof cmpValue === "string" && cmpValue.trim() !== "") {
    const n = Number(cmpValue);
    if (Number.isFinite(n)) cmpValue = n;
  }
  if (config.min !== undefined) {
    if (typeof cmpValue === "string" && cmpValue.length < config.min) return false;
    if (typeof cmpValue === "number" && cmpValue < config.min) return false;
  }
  if (config.max !== undefined) {
    if (typeof cmpValue === "string" && cmpValue.length > config.max) return false;
    if (typeof cmpValue === "number" && cmpValue > config.max) return false;
  }

  // Custom FEEL-lite expression
  if (config.expression) {
    try {
      const result = evaluateExpression(config.expression, context);
      if (!result) return false;
    } catch {
      return false;
    }
  }

  return true;
}

// ---------------------------------------------------------------------------
// Access Control
// ---------------------------------------------------------------------------

/**
 * The `row_access` rules governing a model, active ones only.
 *
 * Returned rather than evaluated: unlike every other rule type, a row rule is
 * not applied here. It is compiled into a WHERE clause by the data engine, so
 * that a row the actor cannot reach is absent from the query rather than
 * removed from its result — which is the difference between a count that is
 * right and a count that is wrong.
 *
 * `model_name` is matched separator- and case-insensitively, because the
 * caller may hold the entity name, the table or the route slug.
 */
export async function rowAccessRulesFor(modelName: string): Promise<ProjectRule[]> {
  await loadRules();
  const want = canonicalModel(modelName);
  if (!want) return [];
  return ruleCache.filter(
    (r) =>
      r.rule_type === "row_access" &&
      canonicalModel(r.model_name ?? "") === want &&
      isRuleActive(r),
  );
}

/** `Rent_Payment` / `rentPayments` / `rent-payments` -> one comparable key. */
function canonicalModel(name: string): string {
  const c = String(name ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
  return c.endsWith("s") ? c.slice(0, -1) : c;
}

/**
 * Check if a user can perform an action on a field.
 *
 * Used in:
 * - API routes to filter response fields
 * - UI components to show/hide form fields
 */
export async function canAccessField(
  modelName: string,
  fieldName: string,
  action: "view" | "edit" | "delete",
  user: { role?: string; id?: string; [key: string]: unknown } = {},
): Promise<AccessCheckResult> {
  await loadRules();

  // Field-specific rules AND entity-wide rules (field_name null/empty) both
  // govern a field. Entity-wide grants like "organizer has full access to
  // Ticket" were previously invisible here (the filter demanded an exact
  // field_name match), so an organizer was locked out of Ticket.status by
  // the staff-only rule below even though a broader rule granted access.
  const rules = ruleCache.filter(
    (r) =>
      r.rule_type === "access" &&
      r.model_name === modelName &&
      (r.field_name === fieldName || r.field_name == null || r.field_name === "") &&
      isRuleActive(r),
  );

  // No access rules → allow by default
  if (rules.length === 0) {
    return { allowed: true };
  }

  const role = typeof user.role === "string" ? user.role.trim() : "";

  // The app owner (seeded `admin` role) bypasses field ACLs. Generated rules
  // are authored in terms of the app's DOMAIN actors (organizer, staff, …)
  // and never mention the platform-level admin — without this bypass the
  // owner is "not in any list" and every ruled field is redacted for the
  // very account that manages the app.
  if (role === "admin") {
    return { allowed: true };
  }

  // Grant-union semantics: each rule is a GRANT for the roles it names, not
  // a restriction on everyone else. (The old loop AND-ed every rule, so
  // "staff can view/edit status" denied status to ALL other roles — server
  // renders showed null for fields the API happily returned.)
  //
  //   - A rule APPLIES to the caller when its roles list is empty or
  //     contains the caller's role. Absent role matches nothing: fail
  //     CLOSED, an hr-only column stays hidden from unauthenticated
  //     callers.
  //   - An applicable rule that explicitly forbids the action
  //     (can_view/can_edit/can_delete === false) or whose condition fails
  //     DENIES — an explicit deny wins over other grants.
  //   - Otherwise any applicable rule grants access.
  //   - Rules exist but none applies to this caller → deny (fail closed).
  let granted = false;
  for (const rule of rules) {
    const config = rule.config as AccessRuleConfig;

    if (config.roles && config.roles.length > 0) {
      if (!role || !config.roles.includes(role)) continue; // not addressed to this caller
    }

    // Check action-specific permission
    if (action === "view" && config.can_view === false) {
      return { allowed: false, reason: `View not permitted by ${rule.name}` };
    }
    if (action === "edit" && config.can_edit === false) {
      return { allowed: false, reason: `Edit not permitted by ${rule.name}` };
    }
    if (action === "delete" && config.can_delete === false) {
      return { allowed: false, reason: `Delete not permitted by ${rule.name}` };
    }

    // Check FEEL-lite condition
    if (config.condition) {
      try {
        const result = evaluateExpression(config.condition, { user });
        if (!result) {
          return { allowed: false, reason: `Condition failed: ${rule.name}` };
        }
      } catch {
        return { allowed: false, reason: `Invalid condition: ${rule.name}` };
      }
    }

    granted = true;
  }

  if (!granted) {
    return {
      allowed: false,
      reason: role
        ? `Role ${role} is not granted access to ${modelName}.${fieldName} by any rule`
        : `No role presented; ${modelName}.${fieldName} is restricted`,
    };
  }

  return { allowed: true };
}

/**
 * Filter an entity to only fields the user can view.
 * Removes fields where canAccessField returns false.
 */
export async function filterFields(
  modelName: string,
  entity: Record<string, unknown>,
  user: { role?: string; id?: string } = {},
): Promise<Record<string, unknown>> {
  const filtered: Record<string, unknown> = {};

  for (const [field, value] of Object.entries(entity)) {
    const access = await canAccessField(modelName, field, "view", user);
    if (access.allowed) {
      filtered[field] = value;
    }
  }

  return filtered;
}

// ---------------------------------------------------------------------------
// Business Rules
// ---------------------------------------------------------------------------

/**
 * Evaluate a business rule expression against an entity.
 * Returns the rule's computed result (or null if not found / failed).
 */
export async function evaluateBusinessRule(
  modelName: string,
  ruleName: string,
  entity: Record<string, unknown>,
): Promise<unknown> {
  await loadRules();

  const rule = ruleCache.find(
    (r) =>
      r.rule_type === "business" &&
      r.model_name === modelName &&
      r.name === ruleName &&
      isRuleActive(r),
  );

  if (!rule) return null;

  const config = rule.config as unknown as BusinessRuleConfig;
  if (!config.expression) return null;

  try {
    return evaluateExpression(config.expression, entity as any);
  } catch (err) {
    console.error(`[rules] Business rule ${ruleName} failed:`, err);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Computed Fields
// ---------------------------------------------------------------------------

/**
 * Compute all derived (computed) fields for an entity.
 * Returns the entity with computed fields added.
 */
export async function computeFields(
  modelName: string,
  entity: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  await loadRules();

  const rules = ruleCache.filter(
    (r) =>
      r.rule_type === "computed" &&
      r.model_name === modelName &&
      r.field_name &&
      isRuleActive(r),
  );

  const computed: Record<string, unknown> = { ...entity };

  for (const rule of rules) {
    const config = rule.config as unknown as ComputedFieldConfig;
    if (!config.expression || !rule.field_name) continue;

    try {
      computed[rule.field_name] = evaluateExpression(
        config.expression,
        computed as any,
      );
    } catch (err) {
      console.error(`[rules] Computed field ${rule.field_name} failed:`, err);
    }
  }

  return computed;
}

// ---------------------------------------------------------------------------
// State Machine
// ---------------------------------------------------------------------------

/**
 * Check if a state transition is allowed.
 */
export async function canTransition(
  modelName: string,
  fieldName: string,
  fromState: string,
  toState: string,
  user: { role?: string } = {},
  entity?: Record<string, unknown>,
): Promise<AccessCheckResult> {
  await loadRules();

  const rule = ruleCache.find(
    (r) =>
      r.rule_type === "state_machine" &&
      r.model_name === modelName &&
      r.field_name === fieldName &&
      isRuleActive(r),
  );

  if (!rule) {
    // No state machine rule → allow any transition
    return { allowed: true };
  }

  const config = rule.config as unknown as StateMachineConfig;

  // Check target state is valid
  if (!config.states.includes(toState)) {
    return { allowed: false, reason: `Invalid state: ${toState}` };
  }

  // Find matching transition
  const transition = config.transitions.find(
    (t) => (t.from === fromState || t.from === "*") && t.to === toState,
  );

  if (!transition) {
    return {
      allowed: false,
      reason: `No transition from ${fromState} to ${toState}`,
    };
  }

  // Check required role
  if (transition.requires && user.role !== transition.requires) {
    return {
      allowed: false,
      reason: `Requires role: ${transition.requires}`,
    };
  }

  // Check condition expression
  if (transition.condition && entity) {
    try {
      const result = evaluateExpression(transition.condition, {
        ...entity,
        user,
      } as any);
      if (!result) {
        return { allowed: false, reason: "Transition condition failed" };
      }
    } catch {
      return { allowed: false, reason: "Invalid transition condition" };
    }
  }

  return { allowed: true };
}

// ---------------------------------------------------------------------------
// Condition → Action rule sets (Business Rules editor)
//
// A rule = WHEN <whenFeel> THEN <then[]> [ELSE <otherwise[]>]. A model's rules
// are evaluated salience-ordered, single pass; set-value patches accumulate so a
// later rule sees earlier changes. Server-safe actions (set/default/clear/error)
// execute here on the write path; form-only actions (visibility/required/
// readonly/recommendation) are collected as hints for the client; trigger_
// workflow / send_notification are collected as deferred side effects.
// ---------------------------------------------------------------------------

function isEmpty(v: unknown): boolean {
  return v === null || v === undefined || v === "";
}

/** Resolve an action's value per its valueMode against the working entity. */
function resolveActionValue(
  action: RuleAction,
  entity: Record<string, unknown>,
): unknown {
  const raw = action.value ?? "";
  switch (action.valueMode) {
    case "field":
      return entity[raw];
    case "formula":
      try {
        return evaluateExpression(raw, entity as any);
      } catch {
        return null;
      }
    case "literal":
    default: {
      // Auto-coerce simple literals so "true"/"42" land as the right type.
      if (raw === "true") return true;
      if (raw === "false") return false;
      // Only coerce a value that ROUND-TRIPS exactly.
      //
      // `!Number.isNaN(Number(raw))` accepted anything numeric-LOOKING and
      // silently rewrote it (register R-3):
      //   "007"        -> 7          leading zeros lost — invoice/employee ids
      //   "0123456789" -> 123456789  a phone number becomes a number
      //   "1e5"        -> 100000     an SKU or part code
      //   "0x10"       -> 16
      //   " 42 "       -> 42         whitespace silently trimmed
      //   "Infinity"   -> Infinity
      // The rule wrote that back into the entity, so a rule that was supposed
      // to set a reference string corrupted it instead — and the write
      // succeeded, so nothing reported it. Requiring String(Number(x)) === x
      // keeps the intended "42" -> 42 case and rejects every rewrite above.
      if (typeof raw === "string" && raw !== "") {
        const n = Number(raw);
        if (!Number.isNaN(n) && Number.isFinite(n) && String(n) === raw) return n;
      }
      return raw;
    }
  }
}

/**
 * Apply one branch's actions to the working state. Mutates `patches`,
 * `errors`, `hints`, `sideEffects` and returns nothing.
 */
/**
 * Which salience last claimed each field, so a LOWER-salience rule cannot
 * overwrite a decision a HIGHER-salience rule already made.
 *
 * Rules are sorted highest-salience-first and then applied in a single pass
 * that accumulated patches with plain assignment — i.e. LAST WRITE WINS. That
 * is the exact opposite of what the ordering promises: the lowest-salience
 * rule ran last and therefore won every conflict on the same field. Salience
 * looked like it worked (the higher rule really did fire first) while
 * determining nothing.
 */
type FieldClaims = Map<string, number>;

function claim(
  claims: FieldClaims | undefined,
  field: string,
  salience: number,
): boolean {
  if (!claims) return true;                 // form-hint pass — no conflicts
  const held = claims.get(field);
  if (held !== undefined && held > salience) return false;
  claims.set(field, salience);
  return true;
}

function dispatchActions(
  actions: RuleAction[] | undefined,
  working: Record<string, unknown>,
  out: RuleSetResult,
  serverSide: boolean,
  claims?: FieldClaims,
  salience: number = 0,
): void {
  for (const action of actions ?? []) {
    switch (action.type) {
      case "set_field": {
        if (!action.field) break;
        if (!claim(claims, action.field, salience)) break;
        const v = resolveActionValue(action, working);
        working[action.field] = v;
        out.patches[action.field] = v;
        break;
      }
      case "set_default": {
        if (!action.field) break;
        if (isEmpty(working[action.field])) {
          if (!claim(claims, action.field, salience)) break;
          const v = resolveActionValue(action, working);
          working[action.field] = v;
          out.patches[action.field] = v;
        }
        break;
      }
      case "clear_field": {
        if (!action.field) break;
        if (!claim(claims, action.field, salience)) break;
        working[action.field] = null;
        out.patches[action.field] = null;
        break;
      }
      case "show_error": {
        if (action.message) out.errors.push(action.message);
        break;
      }
      // Form-only actions: collected as hints; never applied server-side.
      case "set_visibility":
        if (action.field)
          out.formHints.push({ field: action.field, hidden: action.visible === false });
        break;
      case "set_required":
        if (action.field)
          out.formHints.push({ field: action.field, required: action.required !== false });
        break;
      case "set_readonly":
        if (action.field)
          out.formHints.push({ field: action.field, readonly: action.readonly !== false });
        break;
      case "recommendation":
        if (action.field)
          out.formHints.push({
            field: action.field,
            recommendation: {
              value: resolveActionValue(action, working) as string,
              message: action.message,
            },
          });
        break;
      case "trigger_workflow":
        if (serverSide && action.workflow)
          out.sideEffects.push({ type: "trigger_workflow", workflow: action.workflow });
        break;
      case "send_notification":
        if (serverSide && action.message)
          out.sideEffects.push({ type: "send_notification", message: action.message });
        break;
    }
  }
}

/**
 * Evaluate all condition→action rules for a model on a given event.
 *
 * @param modelName  entity/model the write targets
 * @param event      "create" | "update" | "read"
 * @param entity     the record (merged existing+incoming on update)
 * @param user       optional user context (exposed to conditions as `user`)
 */
/**
 * Run the AI-authored rule types (computed / validation / business) that the
 * generation pipeline emits, merging their effects into `out`.
 *
 * WHY: historically the write-path entrypoints (evaluateRuleSet /
 * evaluateRuleSetForTable / evaluateFormRules) filtered `condition_action`
 * ONLY. But the rules AGENT can only emit validation/access/business/computed/
 * state_machine/trigger — never condition_action — so on any app without
 * hand-authored editor rules EVERY generated rule was a silent no-op. This
 * bridges that gap by executing the data-write types (computed → field patches,
 * validation + failing business guards → rejection errors) through the same
 * single entrypoint, so both the data-engine and the workflow write paths get
 * them uniformly.
 */
// ── Decision tables (rule_type="decision_table") ────────────────────────────
// A DMN-style table: inputs (bound to entity fields) × rules (rows) → outputs
// (field patches). Previously accepted + stored + exported but NEVER evaluated,
// so authored tables did nothing. Each input cell is a DMN unary test
// ("> 1000", "active", "a,b" = OR, "-"/"" = any); each output cell is a literal
// or a FEEL-lite expression over the entity. First-match-wins (correct for the
// common Unique/First/Priority hit policies; Collect/RuleOrder fall back to
// last-write on scalar fields).

function _splitTopLevel(s: string, sep: string): string[] {
  const out: string[] = [];
  let depth = 0, quote = "", cur = "";
  for (const ch of s) {
    if (quote) { cur += ch; if (ch === quote) quote = ""; continue; }
    if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
    if (ch === "(" || ch === "[") depth++;
    if (ch === ")" || ch === "]") depth--;
    if (ch === sep && depth === 0) { out.push(cur); cur = ""; continue; }
    cur += ch;
  }
  if (cur.trim()) out.push(cur);
  return out;
}

function _rhsLiteral(raw: string): string {
  const s = raw.trim();
  if (/^-?\d+(\.\d+)?$/.test(s) || s === "true" || s === "false") return s;
  if (/^["'].*["']$/.test(s)) return s;
  return JSON.stringify(s);
}

function _matchDecisionCell(binding: string, cell: string, ctx: Record<string, unknown>): boolean {
  const c = (cell ?? "").trim();
  if (c === "" || c === "-") return true; // any
  for (const raw of _splitTopLevel(c, ",")) {
    const a = raw.trim();
    if (!a) continue;
    const m = a.match(/^(>=|<=|!=|>|<|=)\s*(.+)$/);
    const expr = m ? `${binding} ${m[1]} ${_rhsLiteral(m[2])}` : `${binding} = ${_rhsLiteral(a)}`;
    try {
      if (evaluateExpression(expr, ctx as any)) return true;
    } catch { /* try next alternative */ }
  }
  return false;
}

function _decisionOutputValue(cell: string, ctx: Record<string, unknown>): unknown {
  const c = (cell ?? "").trim();
  if (c === "" || c === "-") return undefined;
  if (/^["'].*["']$/.test(c)) return c.slice(1, -1);
  if (/^-?\d+(\.\d+)?$/.test(c)) return Number(c);
  if (c === "true") return true;
  if (c === "false") return false;
  try {
    return evaluateExpression(c, ctx as any);
  } catch {
    return c;
  }
}

async function evaluateDecisionTables(
  modelName: string,
  working: Record<string, unknown>,
  out: RuleSetResult,
  claims?: FieldClaims,
): Promise<void> {
  const rules = ruleCache.filter(
    (r) => r.rule_type === "decision_table" && r.model_name === modelName && isRuleActive(r),
  );
  for (const rule of rules) {
    const table = (rule.config as any)?.table;
    if (!table || !Array.isArray(table.inputs) || !Array.isArray(table.outputs) || !Array.isArray(table.rules)) {
      continue;
    }
    const hit = String(table.hitPolicy || "F");
    for (const row of table.rules) {
      const inCells: string[] = row.inputEntries || [];
      let matched = true;
      for (let i = 0; i < table.inputs.length; i++) {
        const inp = table.inputs[i] || {};
        const binding = inp.variableBinding || inp.name;
        if (!binding) continue;
        if (!_matchDecisionCell(binding, inCells[i] ?? "", working)) { matched = false; break; }
      }
      if (!matched) continue;
      const outCells: string[] = row.outputEntries || [];
      for (let j = 0; j < table.outputs.length; j++) {
        const outp = table.outputs[j] || {};
        const field = outp.variableBinding || outp.name;
        if (!field || (claims && claims.has(field))) continue;
        const val = _decisionOutputValue(outCells[j] ?? "", working);
        if (val !== undefined && working[field] !== val) {
          out.patches[field] = val;
          working[field] = val;
        }
      }
      if (hit === "F" || hit === "U" || hit === "P" || hit === "A") break; // first match wins
    }
  }
}

async function applyTypedRules(
  modelName: string,
  event: "create" | "update" | "read",
  working: Record<string, unknown>,
  out: RuleSetResult,
  claims?: FieldClaims,
): Promise<void> {
  // decision tables → output patches (before computed/validation so those see them).
  await evaluateDecisionTables(modelName, working, out, claims);
  // computed → patches (skip a field a condition_action rule already claimed).
  try {
    const computed = await computeFields(modelName, working);
    for (const [k, v] of Object.entries(computed)) {
      if (v === undefined) continue;
      if (claims && claims.has(k)) continue;
      if (working[k] !== v) {
        out.patches[k] = v;
        working[k] = v;
      }
    }
  } catch (err) {
    console.error(`[rules] computed pass failed for ${modelName}:`, err);
  }
  // validation → errors, evaluated over the fully-patched row.
  // On UPDATE, only validate fields present in the payload — a partial update
  // that doesn't touch a required column isn't a violation (the DB row already
  // holds a value). Without this a `{status:"processing"}` db_update raised
  // "Original filename is required" for every other required rule the model
  // had.
  try {
    const vr = await validateEntity(modelName, working, {
      onlySubmittedFields: event === "update",
    });
    for (const e of vr.errors) if (!out.errors.includes(e)) out.errors.push(e);
  } catch (err) {
    console.error(`[rules] validation pass failed for ${modelName}:`, err);
  }
  // business guards whose trigger matches this event → reject when the guard
  // expression is falsy AND an explicit errorMessage is provided (a deliberate
  // hard guard). Without an errorMessage a business rule never rejects, so a
  // vague AI-emitted expression can never block a valid write.
  try {
    const want = event === "create" ? "on_create" : event === "update" ? "on_update" : "on_read";
    for (const rule of ruleCache) {
      if (rule.rule_type !== "business" || rule.model_name !== modelName || !isRuleActive(rule)) continue;
      const config = rule.config as unknown as BusinessRuleConfig & { trigger?: string; errorMessage?: string };
      if (!config.expression || !config.errorMessage) continue;
      if (config.trigger && config.trigger !== want) continue;
      let ok = true;
      try {
        ok = Boolean(evaluateExpression(config.expression, working as any));
      } catch (e) {
        console.error(`[rules] business guard "${rule.name}" failed:`, e);
        continue;
      }
      if (!ok && !out.errors.includes(config.errorMessage)) out.errors.push(config.errorMessage);
    }
  } catch (err) {
    console.error(`[rules] business pass failed for ${modelName}:`, err);
  }
}

export async function evaluateRuleSet(
  modelName: string,
  event: "create" | "update" | "read",
  entity: Record<string, unknown>,
  user?: unknown,
): Promise<RuleSetResult> {
  await loadRules();

  const out: RuleSetResult = { patches: {}, errors: [], formHints: [], sideEffects: [] };

  const rules = ruleCache
    .filter(
      (r) =>
        r.rule_type === "condition_action" &&
        r.model_name === modelName &&
        isRuleActive(r),
    )
    // Server path runs entity- and server-scoped rules; form-only rules are
    // evaluated client-side by the renderer, not here.
    .filter((r) => {
      const scope = (r.config as ConditionActionConfig).scope ?? "entity";
      return scope === "entity" || scope === "server";
    })
    // Higher salience fires first.
    .sort(
      (a, b) =>
        ((b.config as ConditionActionConfig).salience ?? 0) -
        ((a.config as ConditionActionConfig).salience ?? 0),
    );

  // Working copy: set-value patches propagate to later rules' conditions.
  const working: Record<string, unknown> = { ...entity };
  const ctx = { ...working, user };
  // Which salience claimed each field. Rules run highest-first, so a later
  // (lower-salience) rule must not overwrite a field an earlier one set.
  const claims: FieldClaims = new Map();

  for (const rule of rules) {
    const config = rule.config as ConditionActionConfig;
    const whenFeel = (config.whenFeel ?? "true").trim() || "true";
    let matched = false;
    try {
      matched = Boolean(evaluateExpression(whenFeel, { ...working, user } as any));
    } catch (err) {
      // A broken condition must not silently pass — skip the rule, keep going.
      console.error(`[rules] condition of "${rule.name}" failed:`, err);
      continue;
    }
    void ctx;
    dispatchActions(
      matched ? config.then : config.otherwise,
      working, out, true, claims, config.salience ?? 0,
    );
  }

  // Also run the AI-authored rule types (computed/validation/business).
  await applyTypedRules(modelName, event, working, out, claims);

  return out;
}

/**
 * Form-side evaluation: like evaluateRuleSet but returns ONLY the outcomes a
 * client form cares about — field patches (set/default/clear) and form hints
 * (visibility/required/readonly/recommendation) — for entity- and form-scoped
 * rules. Errors/side-effects are the server's job. Pure (no I/O beyond the
 * already-loaded rule cache); safe to call on every form value change.
 */
export async function evaluateFormRules(
  modelName: string,
  entity: Record<string, unknown>,
  user?: unknown,
): Promise<Pick<RuleSetResult, "patches" | "formHints">> {
  await loadRules();
  const out: RuleSetResult = { patches: {}, errors: [], formHints: [], sideEffects: [] };
  const rules = ruleCache
    .filter(
      (r) =>
        r.rule_type === "condition_action" &&
        r.model_name === modelName &&
        isRuleActive(r),
    )
    .filter((r) => {
      const scope = (r.config as ConditionActionConfig).scope ?? "entity";
      return scope === "entity" || scope === "form";
    })
    .sort(
      (a, b) =>
        ((b.config as ConditionActionConfig).salience ?? 0) -
        ((a.config as ConditionActionConfig).salience ?? 0),
    );
  const working: Record<string, unknown> = { ...entity };
  for (const rule of rules) {
    const config = rule.config as ConditionActionConfig;
    const whenFeel = (config.whenFeel ?? "true").trim() || "true";
    let matched = false;
    try {
      matched = Boolean(evaluateExpression(whenFeel, { ...working, user } as any));
    } catch {
      continue;
    }
    dispatchActions(matched ? config.then : config.otherwise, working, out, false);
  }
  // computed fields render live on the form too (e.g. a running total).
  try {
    const computed = await computeFields(modelName, working);
    for (const [k, v] of Object.entries(computed)) {
      if (v !== undefined && working[k] !== v) {
        out.patches[k] = v;
        working[k] = v;
      }
    }
  } catch (err) {
    console.error(`[rules] form computed pass failed for ${modelName}:`, err);
  }
  return { patches: out.patches, formHints: out.formHints };
}

// ---------------------------------------------------------------------------
// Table → entity resolution for the workflow write path
//
// The schema-form path submits through workflow db_insert/db_update, whose
// config carries the TABLE name ("clients"), while rules key on the ENTITY /
// model name ("Client"). This resolves a table name to the model of a matching
// condition_action rule — canonicalised (case/separator/trailing-'s' tolerant),
// and ONLY when such a rule exists. No matching rule ⇒ undefined ⇒ the caller
// no-ops, so tables without business rules are completely unaffected.
// ---------------------------------------------------------------------------

// Normalised name keys for tolerant table↔model matching. The old canonName
// only stripped a single trailing "s", so "addresses"/"categories"/"statuses"/
// "boxes" never matched "Address"/"Category"/"Status"/"Box" and their rules
// silently never fired on the workflow path. We emit a SET of candidate keys
// per name (raw, naive-de-s, -ies→-y, -es→∅) and match if the sets intersect —
// robust in both directions without over-stripping (e.g. "status" stays intact
// because its raw key is always kept).
function nameKeys(s: string): Set<string> {
  const c = s.toLowerCase().replace(/[^a-z0-9]/g, "");
  const keys = new Set<string>([c]);
  if (c.length > 1 && c.endsWith("s") && !c.endsWith("ss")) keys.add(c.slice(0, -1));
  if (/ies$/.test(c)) keys.add(c.replace(/ies$/, "y"));
  if (/(ses|xes|zes|ches|shes)$/.test(c)) keys.add(c.replace(/es$/, ""));
  return keys;
}

function namesMatch(a: string, b: string): boolean {
  const kb = nameKeys(b);
  for (const k of nameKeys(a)) if (kb.has(k)) return true;
  return false;
}

export async function entityNameForTable(tableName: string): Promise<string | undefined> {
  await loadRules();
  // Register models from EVERY executable rule type, not just condition_action —
  // a table whose model has only validation/computed/business rules must still
  // resolve so those rules fire on the workflow write path.
  const models = new Set<string>();
  for (const r of ruleCache) {
    if (r.model_name && isRuleActive(r)) models.add(r.model_name);
  }
  // Prefer an exact (raw) match before a pluralised one.
  for (const m of models) {
    if (m.toLowerCase().replace(/[^a-z0-9]/g, "") === tableName.toLowerCase().replace(/[^a-z0-9]/g, "")) {
      return m;
    }
  }
  for (const m of models) {
    if (namesMatch(m, tableName)) return m;
  }
  return undefined;
}

/**
 * Evaluate a model's condition→action rules given a TABLE name (workflow path).
 * Returns an empty result if no rule targets this table — a true no-op for the
 * overwhelming majority of writes.
 */
export async function evaluateRuleSetForTable(
  tableName: string,
  event: "create" | "update" | "read",
  entity: Record<string, unknown>,
  user?: unknown,
): Promise<RuleSetResult> {
  const model = await entityNameForTable(tableName);
  if (!model) {
    return { patches: {}, errors: [], formHints: [], sideEffects: [] };
  }
  return evaluateRuleSet(model, event, entity, user);
}

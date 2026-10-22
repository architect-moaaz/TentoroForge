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
import { evaluateTable, type DecisionTableDef } from "./decision-table";
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
/** Rules handed in with setRules (tests, in-memory callers) are never replaced from disk. */
let rulesPinned = false;
/** What the rules files looked like when they were read: name, size and mtime of each. */
let rulesStamp = "";
let rulesCheckedAt = 0;
/**
 * A RULE CHANGED IS A RULE IN FORCE. The cache used to be filled once for the
 * life of the server, so a rule added or edited in the Business Rules tab or by
 * Smith — written to rules/*.json while the app ran — did nothing until a
 * restart nobody made. The files are looked at again at most this often; a
 * stat per file is the whole cost.
 */
const RULES_RECHECK_MS = 1000;

/**
 * Load rules from a directory or in-memory array.
 * Generated apps typically read from /rules/index.json at boot.
 */
/** Rules switched off, by id: a workflow step running one carries on (it
 * does not apply), where a step naming a rule the app does not have at all
 * never passes. */
let rulesOff = new Set<string>();
export function isRuleSwitchedOff(id: unknown): boolean {
  return rulesOff.has(String(id));
}

export function setRules(rules: ProjectRule[]): void {
  rulesOff = new Set(rules.filter((r) => !isRuleActive(r)).map((r) => String(r.id)));
  ruleCache = rules;
  rulesLoaded = true;
  rulesPinned = true;
}

async function rulesFilesStamp(dirs: string[]): Promise<string> {
  const { promises: fs } = await import("fs");
  const path = await import("path");
  const parts: string[] = [];
  for (const dir of dirs) {
    let files: string[];
    try {
      files = await fs.readdir(dir);
    } catch {
      continue;
    }
    for (const file of files.sort()) {
      if (!file.endsWith(".json")) continue;
      try {
        const st = await fs.stat(path.join(dir, file));
        parts.push(`${dir}/${file}:${st.size}:${st.mtimeMs}`);
      } catch { /* gone between readdir and stat */ }
    }
  }
  return parts.join("|");
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
  const isNode = typeof process !== "undefined" && !!process.versions?.node;
  if (rulesLoaded && (rulesPinned || !isNode)) return ruleCache;
  let stamp = "";
  if (rulesLoaded) {
    const now = Date.now();
    if (now - rulesCheckedAt < RULES_RECHECK_MS) return ruleCache;
    rulesCheckedAt = now;
    try {
      const path = await import("path");
      stamp = await rulesFilesStamp(rulesDir ? [rulesDir]
        : [path.join(process.cwd(), "rules"), path.join(process.cwd(), "src", "rules")]);
    } catch {
      return ruleCache;
    }
    if (stamp === rulesStamp) return ruleCache;
  }

  // In Node.js (server-side), try to load from filesystem
  if (isNode) {
    try {
      const { promises: fs } = await import("fs");
      const path = await import("path");
      // Try both locations — the app-root `rules/` (local `next start`/dev) AND
      // `src/rules/` (bundled into serverless functions on Vercel, where the
      // root `rules/` dir isn't traced). First readable dir wins.
      const candidates = rulesDir
        ? [rulesDir]
        : [path.join(process.cwd(), "rules"), path.join(process.cwd(), "src", "rules")];
      if (!stamp) stamp = await rulesFilesStamp(candidates);
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
      rulesOff = new Set(rules.filter((r) => !isRuleActive(r)).map((r) => String(r.id)));
      ruleCache = rules.filter(isRuleActive);
      rulesStamp = stamp;
    } catch {
      ruleCache = [];
      rulesOff = new Set();
    }
  }

  rulesLoaded = true;
  rulesCheckedAt = Date.now();
  return ruleCache;
}

// ---------------------------------------------------------------------------
// Which rules govern a write, and where
// ---------------------------------------------------------------------------

/**
 * A rule names its record by the ENTITY ("Task"); the data API hands the
 * engine the URL segment ("tasks") and the workflow path the table name. An
 * exact comparison meant a Blueprint rule never fired through /api/data.
 */
export function ruleGoverns(ruleModel: string | null | undefined, modelName: string): boolean {
  if (!ruleModel || !modelName) return false;
  if (ruleModel === modelName) return true;
  return namesMatch(ruleModel, modelName);
}

/** Actions that refuse a save or change a value — never left to the form alone. */
const DATA_ACTIONS = new Set([
  "show_error", "set_field", "set_default", "clear_field", "set_required",
  "trigger_workflow", "send_notification",
]);

/**
 * Where a condition→action rule runs.
 *
 * `form` was the default scope, and the server skipped every `form` rule
 * while the form route threw their errors and values away — so "a task must
 * have a title" and "new tasks default to todo" ran nowhere. A rule that
 * refuses a save or sets a value is the record's rule: it runs on every save
 * AND live on the form. Only a rule that is purely about how the form looks
 * (show, hide, lock, narrow options, suggest) stays on the form; `server` keeps
 * a rule off the form.
 */
/** Whether a rule only fills in an empty field (`set_default`, nothing else). */
function fillsDefaultsOnly(rule: ProjectRule): boolean {
  const config = rule.config as ConditionActionConfig;
  const acts = config?.then ?? [];
  return acts.length > 0 && acts.every((a) => a?.type === "set_default") && !(config?.otherwise ?? []).length;
}

/**
 * The order rules fire in. A VALUE IS SETTLED BEFORE IT IS JUDGED: a rule
 * that only fills in a default runs before the rest, then higher salience
 * first. "New expenses start as submitted" was written as a default AND a
 * check that a new expense is submitted; in list order the check saw no
 * status yet and refused every new expense the form sent (2026-10-14).
 */
export function byFiringOrder(a: ProjectRule, b: ProjectRule): number {
  const first = Number(fillsDefaultsOnly(b)) - Number(fillsDefaultsOnly(a));
  if (first) return first;
  return ((b.config as ConditionActionConfig).salience ?? 0) - ((a.config as ConditionActionConfig).salience ?? 0);
}

// Where a condition→action rule is enforced. The Business Rules tab shows the
// same decision as a label through `where_it_runs` in
// backend/services/business_rules.py — keep the two in step, or the tab names
// a place a rule runs that this does not.
export function effectiveScope(config: ConditionActionConfig | undefined): "entity" | "form" | "server" {
  const scope = config?.scope;
  if (scope === "server") return "server";
  const acts = [...(config?.then ?? []), ...(config?.otherwise ?? [])];
  if (acts.some((a) => a && DATA_ACTIONS.has(String((a as RuleAction).type)))) return "entity";
  return scope ?? "entity";
}

/**
 * "Is empty" means blank OR absent. A blank field arrives as "" from a form
 * and is dropped before a write, so `title = ""` missed the write and
 * `title = null` missed the form. Each equality test against "" or null is
 * read as the same "empty" test, and its negation as "has a value". Text
 * inside quotes is left alone.
 */
const _blankCache = new Map<string, string>();
export function normalizeBlankChecks(feel: string): string {
  const hit = _blankCache.get(feel);
  if (hit !== undefined) return hit;
  const isStart = (c: string) => /[A-Za-z_]/.test(c);
  const isPart = (c: string) => /[A-Za-z0-9_]/.test(c);
  let out = "";
  let i = 0;
  const n = feel.length;
  while (i < n) {
    const c = feel[i];
    if (c === '"') {                       // a string literal: copied as it stands
      let j = i + 1;
      while (j < n && feel[j] !== '"') j += feel[j] === "\\" ? 2 : 1;
      out += feel.slice(i, Math.min(j + 1, n));
      i = j + 1;
      continue;
    }
    const prev = i > 0 ? feel[i - 1] : "";
    if (isStart(c) && !isPart(prev) && prev !== ".") {
      let j = i;
      while (j < n && (isPart(feel[j]) || (feel[j] === "." && j + 1 < n && isStart(feel[j + 1])))) j++;
      const ident = feel.slice(i, j);
      let k = j;
      while (k < n && feel[k] === " ") k++;
      let op = "";
      if (feel.startsWith("!=", k)) op = "!=";
      else if (feel[k] === "=" && feel[k + 1] !== "=") op = "=";
      if (op && !["null", "true", "false", "not", "and", "or", "in"].includes(ident)) {
        let m = k + op.length;
        while (m < n && feel[m] === " ") m++;
        let blankLen = 0;
        if (feel.startsWith('""', m)) blankLen = 2;
        else if (feel.startsWith("null", m) && !isPart(feel[m + 4] ?? "")) blankLen = 4;
        if (blankLen) {
          out += op === "="
            ? `(${ident} = null or ${ident} = "")`
            : `(${ident} != null and ${ident} != "")`;
          i = m + blankLen;
          continue;
        }
      }
      out += ident;
      i = j;
      continue;
    }
    out += c;
    i++;
  }
  _blankCache.set(feel, out);
  return out;
}

/** A field name as a person reads it: `dueDate` → "Due date". */
function fieldLabel(field: string): string {
  const words = field.replace(/[_-]+/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2").trim().toLowerCase();
  return words ? words[0].toUpperCase() + words.slice(1) : field;
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
        if (action.field) {
          out.formHints.push({ field: action.field, required: action.required !== false,
                               ...(action.required !== false && action.message ? { message: String(action.message) } : {}) });
          // Required is a rule of the record, not only a red asterisk: a save
          // with the field empty while the rule holds is refused.
          if (serverSide && action.required !== false && isEmpty(working[action.field])) {
            const msg = action.message || `${fieldLabel(action.field)} is required.`;
            if (!out.errors.includes(msg)) out.errors.push(msg);
          }
        }
        break;
      case "set_options":
        if (action.field && Array.isArray(action.options))
          out.formHints.push({ field: action.field, options: action.options });
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
// Inputs bound to the record's fields × rows → outputs (field patches). The
// cells, hit policies and analysis are `decision-table.ts`.

/**
 * Does this rule fire on this event? `on` lists "create" and/or "update";
 * absent, it fires on both — every rule written before `on` existed.
 */
export function firesOn(config: { on?: unknown } | undefined, event: string): boolean {
  const on = (config as { on?: unknown } | undefined)?.on;
  if (!Array.isArray(on) || on.length === 0) return true;
  return on.map(String).includes(event);
}

/**
 * Decision tables over a record — `decision-table.ts` is the one evaluator
 * (the editor's tester and workflow steps use it too). Outputs skip a field a
 * condition_action rule of higher standing has already claimed. A broken hit
 * policy (two rows under Unique, disagreeing rows under Any) is logged and the
 * first row used: the table was checked at save, so this is data no row was
 * written for, not a reason to refuse the person's save.
 */
async function evaluateDecisionTables(
  modelName: string,
  working: Record<string, unknown>,
  out: RuleSetResult,
  claims?: FieldClaims,
  event: string = "create",
): Promise<void> {
  const rules = ruleCache.filter(
    (r) => r.rule_type === "decision_table" && ruleGoverns(r.model_name, modelName) && isRuleActive(r),
  );
  for (const rule of rules) {
    const config = (rule.config as any) || {};
    const table = config.table as DecisionTableDef | undefined;
    if (!table || !Array.isArray(table.inputs) || !Array.isArray(table.outputs) || !Array.isArray(table.rules)) {
      continue;
    }
    if (!firesOn(config, event)) continue;
    const result = evaluateTable(table, working);
    if (result.violation) console.warn(`[rules] ${rule.name}: ${result.violation}`);
    for (const [field, val] of Object.entries(result.outputs)) {
      if (claims && claims.has(field)) continue;
      if (val !== undefined && working[field] !== val) {
        out.patches[field] = val;
        working[field] = val;
      }
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
  await evaluateDecisionTables(modelName, working, out, claims, event);
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
      if (rule.rule_type !== "business" || !ruleGoverns(rule.model_name, modelName) || !isRuleActive(rule)) continue;
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
  previous?: Record<string, unknown> | null,
): Promise<RuleSetResult> {
  await loadRules();

  const out: RuleSetResult = { patches: {}, errors: [], formHints: [], sideEffects: [] };

  const rules = ruleCache
    .filter(
      (r) =>
        r.rule_type === "condition_action" &&
        ruleGoverns(r.model_name, modelName) &&
        isRuleActive(r) &&
        firesOn(r.config as ConditionActionConfig, event),
    )
    // Server path runs every rule that refuses or changes data (see
    // effectiveScope); purely visual rules are the form's.
    .filter((r) => {
      const scope = effectiveScope(r.config as ConditionActionConfig);
      return scope === "entity" || scope === "server";
    })
    // Higher salience fires first.
    .sort(byFiringOrder);

  // Working copy: set-value patches propagate to later rules' conditions.
  const working: Record<string, unknown> = { ...entity };
  const ctx = { ...working, user };
  // Which salience claimed each field. Rules run highest-first, so a later
  // (lower-salience) rule must not overwrite a field an earlier one set.
  const claims: FieldClaims = new Map();

  // `previous` is the record as it stood before this update — what a rule
  // about a change reads ("a done task cannot go back to todo"). On a create
  // there is no previous record: every `previous.x` is null.
  const before = previous ?? {};
  void ctx;
  // VALUES FIRST, JUDGEMENT LAST. A refusal used to be decided before a
  // decision table filled in the field it checks ("category must be one of…"
  // refused a record the table had just given a category). Now:
  //   1. condition rules set their values, highest priority first;
  //   2. decision tables, computed fields and typed validations run over that;
  //   3. condition rules refuse, hint and start things — read on the final record.
  const decided = new Map<string, boolean>();
  for (const rule of rules) {
    const config = rule.config as ConditionActionConfig;
    const matched = holds(rule, config, working, user, before);
    if (matched === null) continue;
    const acts = (matched ? config.then : config.otherwise) ?? [];
    if (acts.some(isValueAction)) decided.set(String(rule.id), matched);
    dispatchActions(acts.filter(isValueAction), working, out, true, claims, config.salience ?? 0);
  }

  // Also run the AI-authored rule types (computed/validation/business).
  await applyTypedRules(modelName, event, working, out, claims);

  for (const rule of rules) {
    const config = rule.config as ConditionActionConfig;
    // A rule that set a value keeps the answer it acted on (its own value
    // must not flip it); the others are asked about the record as it now is.
    const matched = decided.has(String(rule.id)) ? decided.get(String(rule.id))! : holds(rule, config, working, user, before);
    if (matched === null) continue;
    const acts = ((matched ? config.then : config.otherwise) ?? []).filter((a) => !isValueAction(a));
    dispatchActions(acts, working, out, true, claims, config.salience ?? 0);
  }

  return out;
}

const VALUE_ACTIONS = new Set(["set_field", "set_default", "clear_field"]);
function isValueAction(a: { type?: string } | null | undefined): boolean {
  return !!a && VALUE_ACTIONS.has(String(a.type));
}

/** Does the rule's condition hold — or null when it cannot be read (logged, the rule skipped). */
function holds(rule: ProjectRule, config: ConditionActionConfig, working: Record<string, unknown>,
               user: unknown, before: Record<string, unknown>): boolean | null {
  const whenFeel = normalizeBlankChecks((config.whenFeel ?? "true").trim() || "true");
  try {
    return Boolean(evaluateExpression(whenFeel, { ...working, user, previous: before } as any));
  } catch (err) {
    // A broken condition must not silently pass — skip the rule, keep going.
    console.error(`[rules] condition of "${rule.name}" failed:`, err);
    return null;
  }
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
  previous?: Record<string, unknown> | null,
): Promise<Pick<RuleSetResult, "patches" | "formHints" | "errors">> {
  await loadRules();
  const out: RuleSetResult = { patches: {}, errors: [], formHints: [], sideEffects: [] };
  // A form for a record that has no id yet is creating one; otherwise it is
  // editing — so a rule that fires only on create never speaks on an edit.
  const event = previous || (entity && (entity as any).id) ? "update" : "create";
  const rules = ruleCache
    .filter(
      (r) =>
        r.rule_type === "condition_action" &&
        ruleGoverns(r.model_name, modelName) &&
        isRuleActive(r) &&
        firesOn(r.config as ConditionActionConfig, event),
    )
    .filter((r) => {
      const scope = effectiveScope(r.config as ConditionActionConfig);
      return scope === "entity" || scope === "form";
    })
    .sort(byFiringOrder);
  const working: Record<string, unknown> = { ...entity };
  const before = previous ?? {};
  // In the save's order (values, then tables, then judgement), so the form
  // shows a table's value as it is typed and says only what the save would refuse.
  const decided = new Map<string, boolean>();
  for (const rule of rules) {
    const config = rule.config as ConditionActionConfig;
    const matched = holds(rule, config, working, user, before);
    if (matched === null) continue;
    const acts = (matched ? config.then : config.otherwise) ?? [];
    if (acts.some(isValueAction)) decided.set(String(rule.id), matched);
    dispatchActions(acts.filter(isValueAction), working, out, false);
  }
  try {
    await evaluateDecisionTables(modelName, working, out, new Map(), event);
  } catch (err) {
    console.error(`[rules] form decision tables failed for ${modelName}:`, err);
  }
  for (const rule of rules) {
    const config = rule.config as ConditionActionConfig;
    const matched = decided.has(String(rule.id)) ? decided.get(String(rule.id))! : holds(rule, config, working, user, before);
    if (matched === null) continue;
    const acts = ((matched ? config.then : config.otherwise) ?? []).filter((a) => !isValueAction(a));
    dispatchActions(acts, working, out, false);
    // The form says, while the person types, what the save would refuse.
    for (const a of acts) {
      if (a?.type === "show_error" && a.message && !out.errors.includes(a.message)) out.errors.push(a.message);
    }
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
  return { patches: out.patches, formHints: out.formHints, errors: out.errors };
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
  previous?: Record<string, unknown> | null,
): Promise<RuleSetResult> {
  const model = await entityNameForTable(tableName);
  if (!model) {
    return { patches: {}, errors: [], formHints: [], sideEffects: [] };
  }
  return evaluateRuleSet(model, event, entity, user, previous);
}

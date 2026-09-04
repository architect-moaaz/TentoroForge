/**
 * Rules runtime — public API for generated apps.
 *
 * Usage in API routes:
 * ```ts
 * import { validateEntity, canAccessField, filterFields } from "@/lib/rules";
 *
 * export async function POST(req: Request) {
 *   const body = await req.json();
 *   const validation = await validateEntity("Survey", body);
 *   if (!validation.valid) {
 *     return Response.json({ errors: validation.errors }, { status: 400 });
 *   }
 *   // ... insert into DB
 * }
 * ```
 *
 * Usage in form components (client-side):
 * ```tsx
 * import { validateField } from "@/lib/rules";
 *
 * const onChange = async (value) => {
 *   const result = await validateField("Survey", "title", value);
 *   if (!result.valid) setError(result.errors[0]);
 * }
 * ```
 */

export {
  setRules,
  loadRules,
  validateField,
  validateEntity,
  canAccessField,
  filterFields,
  rowAccessRulesFor,
  evaluateBusinessRule,
  computeFields,
  canTransition,
  evaluateRuleSet,
  evaluateFormRules,
  evaluateRuleSetForTable,
  entityNameForTable,
} from "./engine";

export type {
  ProjectRule,
  RuleType,
  ValidationRuleConfig,
  AccessRuleConfig,
  RowAccessRuleConfig,
  BusinessRuleConfig,
  ComputedFieldConfig,
  StateMachineConfig,
  ValidationResult,
  AccessCheckResult,
  ConditionActionConfig,
  RuleAction,
  RuleActionType,
  RuleSetResult,
  FieldHint,
  RuleSideEffect,
} from "./types";

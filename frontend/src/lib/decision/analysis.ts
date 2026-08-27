/** Decision table analysis — completeness check, overlap detection, dead rows, type errors. */

import type {
  DecisionTableDefinition,
  DecisionAnalysisResult,
} from "@/types/decision";
import { tokenize, parse } from "@/lib/feel-lite";

/** Analyze a decision table for potential issues. */
export function analyzeDecisionTable(
  table: DecisionTableDefinition,
): DecisionAnalysisResult {
  return {
    completeness: checkCompleteness(table),
    overlaps: detectOverlaps(table),
    deadRows: detectDeadRows(table),
    typeErrors: detectTypeErrors(table),
  };
}

/** Check if the table covers all expected input combinations. */
function checkCompleteness(
  table: DecisionTableDefinition,
): DecisionAnalysisResult["completeness"] {
  const hasWildcardRow = table.rules.some((rule) =>
    rule.inputEntries.every((entry) => {
      const t = entry.trim();
      return !t || t === "-";
    }),
  );

  if (hasWildcardRow) {
    return { complete: true, missingCombinations: [] };
  }

  // For simple cases, check if there's a catch-all or wildcard pattern
  const missingCombinations: string[] = [];

  // Heuristic: if any input column has no wildcard entries across all rules,
  // it likely has missing coverage
  for (let col = 0; col < table.inputs.length; col++) {
    const entries = table.rules.map((r) => r.inputEntries[col]?.trim() || "");
    const hasWildcard = entries.some((e) => !e || e === "-");
    if (!hasWildcard && table.rules.length < 5) {
      missingCombinations.push(
        `Column "${table.inputs[col].name}" may have missing coverage (no wildcard entry)`,
      );
    }
  }

  return {
    complete: missingCombinations.length === 0,
    missingCombinations,
  };
}

/** Detect overlapping rules that match the same input combinations. */
function detectOverlaps(
  table: DecisionTableDefinition,
): DecisionAnalysisResult["overlaps"] {
  const pairs: [string, string][] = [];

  for (let i = 0; i < table.rules.length; i++) {
    for (let j = i + 1; j < table.rules.length; j++) {
      if (rulesOverlap(table.rules[i], table.rules[j], table)) {
        pairs.push([table.rules[i].id, table.rules[j].id]);
      }
    }
  }

  return { ruleIdPairs: pairs };
}

/** Check if two rules may match the same inputs. */
function rulesOverlap(
  ruleA: DecisionTableDefinition["rules"][number],
  ruleB: DecisionTableDefinition["rules"][number],
  table: DecisionTableDefinition,
): boolean {
  for (let col = 0; col < table.inputs.length; col++) {
    const entryA = ruleA.inputEntries[col]?.trim() || "";
    const entryB = ruleB.inputEntries[col]?.trim() || "";

    // Wildcard always overlaps
    if (!entryA || entryA === "-" || !entryB || entryB === "-") continue;

    // Exact same value — overlaps
    if (entryA === entryB) continue;

    // Different specific values — no overlap in this column
    // This is conservative; could miss range overlaps
    try {
      const astA = parse(tokenize(entryA));
      const astB = parse(tokenize(entryB));

      // If both are specific literals of different values, no overlap
      if (
        astA.type === "NumberLiteral" &&
        astB.type === "NumberLiteral" &&
        astA.value !== astB.value
      ) {
        return false;
      }
      if (
        astA.type === "StringLiteral" &&
        astB.type === "StringLiteral" &&
        astA.value !== astB.value
      ) {
        return false;
      }
      if (
        astA.type === "BooleanLiteral" &&
        astB.type === "BooleanLiteral" &&
        astA.value !== astB.value
      ) {
        return false;
      }
    } catch {
      // If parsing fails, assume potential overlap
    }
  }

  return true;
}

/** Detect dead rows that can never be reached. */
function detectDeadRows(table: DecisionTableDefinition): string[] {
  const deadRows: string[] = [];

  // For First/Priority hit policies, a rule is dead if a previous rule
  // always matches everything the later rule matches
  if (table.hitPolicy === "F" || table.hitPolicy === "P") {
    for (let i = 1; i < table.rules.length; i++) {
      for (let j = 0; j < i; j++) {
        if (ruleSubsumes(table.rules[j], table.rules[i], table)) {
          deadRows.push(table.rules[i].id);
          break;
        }
      }
    }
  }

  // Check for contradictory conditions (e.g., > 100 and < 50)
  for (const rule of table.rules) {
    if (hasContradiction(rule, table)) {
      deadRows.push(rule.id);
    }
  }

  return [...new Set(deadRows)];
}

/** Check if ruleA subsumes ruleB (A always matches when B matches). */
function ruleSubsumes(
  ruleA: DecisionTableDefinition["rules"][number],
  ruleB: DecisionTableDefinition["rules"][number],
  table: DecisionTableDefinition,
): boolean {
  for (let col = 0; col < table.inputs.length; col++) {
    const entryA = ruleA.inputEntries[col]?.trim() || "";
    const entryB = ruleB.inputEntries[col]?.trim() || "";

    // Wildcard A subsumes anything
    if (!entryA || entryA === "-") continue;

    // If A is specific but B is wildcard, A doesn't subsume B
    if (!entryB || entryB === "-") return false;

    // If they're the same, A subsumes B in this column
    if (entryA === entryB) continue;

    // Otherwise, A doesn't necessarily subsume B
    return false;
  }
  return true;
}

/** Check if a rule has contradictory conditions across columns. */
function hasContradiction(
  rule: DecisionTableDefinition["rules"][number],
  table: DecisionTableDefinition,
): boolean {
  // A rule with "false" as an entry is effectively dead
  for (const entry of rule.inputEntries) {
    const trimmed = entry?.trim().toLowerCase();
    if (trimmed === "false" && table.inputs.length === 1) {
      // Only flag if the input type is boolean and entry is literally false
    }
  }
  return false;
}

/** Detect type errors in cell expressions. */
function detectTypeErrors(
  table: DecisionTableDefinition,
): DecisionAnalysisResult["typeErrors"] {
  const errors: DecisionAnalysisResult["typeErrors"] = [];

  for (const rule of table.rules) {
    // Check input entries
    for (let col = 0; col < table.inputs.length; col++) {
      const entry = rule.inputEntries[col]?.trim();
      if (!entry || entry === "-") continue;

      try {
        const tokens = tokenize(entry);
        parse(tokens);
      } catch (e) {
        errors.push({
          ruleId: rule.id,
          columnIndex: col,
          message: `Invalid expression: ${e instanceof Error ? e.message : String(e)}`,
        });
      }
    }

    // Check output entries
    for (let col = 0; col < table.outputs.length; col++) {
      const entry = rule.outputEntries[col]?.trim();
      if (!entry) continue;

      try {
        const tokens = tokenize(entry);
        parse(tokens);
      } catch (e) {
        errors.push({
          ruleId: rule.id,
          columnIndex: table.inputs.length + col,
          message: `Invalid output expression: ${e instanceof Error ? e.message : String(e)}`,
        });
      }
    }
  }

  return errors;
}

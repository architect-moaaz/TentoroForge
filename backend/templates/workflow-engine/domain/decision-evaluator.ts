/** Decision table evaluator — evaluates a decision table against inputs. */

import { tokenize, parse, evaluate, matchValue, type Context } from './feel-lite';

export interface DecisionTableDefinition {
  id: string;
  name: string;
  hitPolicy: 'U' | 'F' | 'A' | 'P' | 'C' | 'R';
  inputs: { id: string; name: string; type: string; variableBinding?: string }[];
  outputs: { id: string; name: string; type: string }[];
  rules: { id: string; inputEntries: string[]; outputEntries: string[]; annotation?: string }[];
}

export interface DecisionTableResult {
  hitPolicy: string;
  matchedRuleIds: string[];
  outputs: Record<string, unknown>[];
  result: Record<string, unknown> | Record<string, unknown>[];
}

export function evaluateDecisionTable(table: DecisionTableDefinition, inputs: Record<string, unknown>): DecisionTableResult {
  const matched: { rule: typeof table.rules[number]; index: number }[] = [];

  for (let i = 0; i < table.rules.length; i++) {
    const rule = table.rules[i];
    let match = true;
    for (let c = 0; c < table.inputs.length; c++) {
      const cellExpr = (rule.inputEntries[c] ?? '').trim();
      if (!cellExpr || cellExpr === '-') continue;
      const inputVal = inputs[table.inputs[c].variableBinding || table.inputs[c].name];
      try {
        const ast = parse(tokenize(cellExpr));
        if (!matchValue(inputVal, ast, inputs)) { match = false; break; }
      } catch {
        if (String(inputVal) !== cellExpr) { match = false; break; }
      }
    }
    if (match) matched.push({ rule, index: i });
  }

  const ids = matched.map(m => m.rule.id);
  const outputs = matched.map(m => {
    const out: Record<string, unknown> = {};
    for (let c = 0; c < table.outputs.length; c++) {
      const entry = (m.rule.outputEntries[c] ?? '').trim();
      if (!entry) { out[table.outputs[c].name] = null; continue; }
      try { out[table.outputs[c].name] = evaluate(parse(tokenize(entry)), {}); }
      catch { out[table.outputs[c].name] = entry; }
    }
    return out;
  });

  const result = table.hitPolicy === 'C' || table.hitPolicy === 'R' ? outputs : (outputs[0] ?? {});
  return { hitPolicy: table.hitPolicy, matchedRuleIds: ids, outputs, result };
}

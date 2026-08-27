import type { Page } from "@tentoroforge/schema";
import type { Suggestion, Rule } from "./types";
import { rules as defaultRules } from "./rules";

export function runRules(
  page: Page,
  ctx: { theme?: any; registry?: any },
  rules: Rule[] = defaultRules
): Suggestion[] {
  const out: Suggestion[] = [];

  function walk(node: any) {
    for (const rule of rules) {
      out.push(...rule.check(node, ctx));
    }
    if (Array.isArray(node.children)) {
      for (const c of node.children) walk(c);
    }
  }

  walk((page as any).root);
  return out;
}

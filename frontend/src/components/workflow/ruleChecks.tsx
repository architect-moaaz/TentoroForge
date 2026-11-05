"use client";

// THE BUSINESS RULES A STEP CHECKS. A step that saves a record checks every
// rule of that record — the app does it on its own (services/rule_links.py).
// The canvas shows them on the step; they are read from the server, never
// stored in the workflow, so a save of the workflow cannot write them in.

import { createContext, useContext } from "react";

export interface RuleCheck {
  rule: string;
  name: string;
}

/** Step key → the rules it checks, for the workflow on the canvas. */
export const RuleChecksContext = createContext<Record<string, RuleCheck[]>>({});

export function useRuleChecks(nodeId: string): RuleCheck[] {
  return useContext(RuleChecksContext)[nodeId] ?? [];
}

import type { Mutation } from "../state/types";

export type Suggestion = {
  id: string;
  source: "rule" | "llm";
  ruleId?: string;
  nodeId?: string;
  severity: "info" | "warn";
  title: string;
  description: string;
  fix?: Mutation;
};

export type Rule = {
  id: string;
  check: (node: any, ctx: { theme?: any; registry?: any }) => Suggestion[];
};

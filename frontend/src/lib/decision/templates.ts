/** Pre-built decision table templates. */

import type { RuleTemplate, DecisionTableDefinition } from "@/types/decision";

function genId(): string {
  return `dt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function makeTable(
  name: string,
  hitPolicy: DecisionTableDefinition["hitPolicy"],
  inputs: { name: string; type: DecisionTableDefinition["inputs"][number]["type"] }[],
  outputs: { name: string; type: DecisionTableDefinition["outputs"][number]["type"] }[],
  rules: { inputs: string[]; outputs: string[]; annotation?: string }[],
): DecisionTableDefinition {
  return {
    id: genId(),
    name,
    hitPolicy,
    inputs: inputs.map((inp, i) => ({
      id: `inp_${i}`,
      name: inp.name,
      type: inp.type,
    })),
    outputs: outputs.map((out, i) => ({
      id: `out_${i}`,
      name: out.name,
      type: out.type,
    })),
    rules: rules.map((r, i) => ({
      id: `rule_${i}`,
      inputEntries: r.inputs,
      outputEntries: r.outputs,
      annotation: r.annotation,
    })),
  };
}

export const RULE_TEMPLATES: RuleTemplate[] = [
  {
    type: "score_card",
    name: "Score Card",
    description: "Calculate a score based on multiple input factors with weighted points",
    icon: "Calculator",
    table: makeTable(
      "Score Card",
      "C",
      [
        { name: "creditHistory", type: "string" },
        { name: "income", type: "number" },
      ],
      [{ name: "score", type: "number" }],
      [
        { inputs: ['"excellent"', "> 100000"], outputs: ["100"] },
        { inputs: ['"excellent"', "[50000..100000]"], outputs: ["80"] },
        { inputs: ['"good"', "> 50000"], outputs: ["60"] },
        { inputs: ['"good"', "[30000..50000]"], outputs: ["40"] },
        { inputs: ['"fair"', "-"], outputs: ["20"] },
        { inputs: ['"poor"', "-"], outputs: ["0"] },
      ],
    ),
  },
  {
    type: "eligibility_check",
    name: "Eligibility Check",
    description: "Determine eligibility based on multiple criteria with yes/no output",
    icon: "ShieldCheck",
    table: makeTable(
      "Eligibility Check",
      "U",
      [
        { name: "age", type: "number" },
        { name: "employed", type: "boolean" },
        { name: "residency", type: "string" },
      ],
      [
        { name: "eligible", type: "boolean" },
        { name: "reason", type: "string" },
      ],
      [
        { inputs: ["[18..65]", "true", '"domestic"'], outputs: ["true", '"Approved"'] },
        { inputs: ["[18..65]", "true", '"foreign"'], outputs: ["false", '"Foreign residency"'] },
        { inputs: ["[18..65]", "false", "-"], outputs: ["false", '"Not employed"'] },
        { inputs: ["< 18", "-", "-"], outputs: ["false", '"Under age"'] },
        { inputs: ["> 65", "-", "-"], outputs: ["false", '"Over age limit"'] },
      ],
    ),
  },
  {
    type: "tier_classification",
    name: "Tier / Classification",
    description: "Classify inputs into categories or tiers based on value ranges",
    icon: "Layers",
    table: makeTable(
      "Customer Tier",
      "F",
      [
        { name: "annualSpend", type: "number" },
        { name: "yearsActive", type: "number" },
      ],
      [
        { name: "tier", type: "string" },
        { name: "discount", type: "number" },
      ],
      [
        { inputs: ["> 100000", "> 5"], outputs: ['"Platinum"', "20"] },
        { inputs: ["> 50000", "> 3"], outputs: ['"Gold"', "15"] },
        { inputs: ["> 10000", "> 1"], outputs: ['"Silver"', "10"] },
        { inputs: ["-", "-"], outputs: ['"Bronze"', "5"] },
      ],
    ),
  },
  {
    type: "routing_matrix",
    name: "Routing Matrix",
    description: "Route requests to the correct handler based on category and priority",
    icon: "GitBranch",
    table: makeTable(
      "Routing Matrix",
      "U",
      [
        { name: "category", type: "string" },
        { name: "priority", type: "string" },
      ],
      [
        { name: "team", type: "string" },
        { name: "slaHours", type: "number" },
      ],
      [
        { inputs: ['"billing"', '"high"'], outputs: ['"Finance Senior"', "2"] },
        { inputs: ['"billing"', '"low"'], outputs: ['"Finance Junior"', "24"] },
        { inputs: ['"technical"', '"high"'], outputs: ['"Engineering L3"', "4"] },
        { inputs: ['"technical"', '"low"'], outputs: ['"Engineering L1"', "48"] },
        { inputs: ['"general"', "-"], outputs: ['"Support"', "24"] },
      ],
    ),
  },
  {
    type: "discount_ladder",
    name: "Discount Ladder",
    description: "Calculate discounts based on quantity or value thresholds",
    icon: "TrendingDown",
    table: makeTable(
      "Discount Ladder",
      "F",
      [{ name: "quantity", type: "number" }],
      [
        { name: "discountPercent", type: "number" },
        { name: "label", type: "string" },
      ],
      [
        { inputs: [">= 1000"], outputs: ["25", '"Wholesale"'] },
        { inputs: [">= 500"], outputs: ["20", '"Bulk"'] },
        { inputs: [">= 100"], outputs: ["15", '"Volume"'] },
        { inputs: [">= 50"], outputs: ["10", '"Multi-pack"'] },
        { inputs: [">= 10"], outputs: ["5", '"Bundle"'] },
        { inputs: ["-"], outputs: ["0", '"Standard"'] },
      ],
    ),
  },
  {
    type: "validation_rule_set",
    name: "Validation Rule Set",
    description: "Validate input data with multiple rules and collect all violations",
    icon: "ClipboardCheck",
    table: makeTable(
      "Input Validation",
      "C",
      [
        { name: "amount", type: "number" },
        { name: "currency", type: "string" },
        { name: "country", type: "string" },
      ],
      [
        { name: "valid", type: "boolean" },
        { name: "error", type: "string" },
      ],
      [
        { inputs: ["< 0", "-", "-"], outputs: ["false", '"Amount must be positive"'] },
        { inputs: ["> 1000000", "-", "-"], outputs: ["false", '"Amount exceeds limit"'] },
        { inputs: ["-", 'not("USD","EUR","GBP")', "-"], outputs: ["false", '"Unsupported currency"'] },
        { inputs: ["-", "-", '"sanctioned"'], outputs: ["false", '"Sanctioned country"'] },
      ],
    ),
  },
  {
    type: "priority_matrix",
    name: "Priority Matrix",
    description: "Determine priority based on impact and urgency dimensions",
    icon: "Grid3x3",
    table: makeTable(
      "Priority Matrix",
      "U",
      [
        { name: "impact", type: "string" },
        { name: "urgency", type: "string" },
      ],
      [
        { name: "priority", type: "string" },
        { name: "responseTime", type: "string" },
      ],
      [
        { inputs: ['"high"', '"high"'], outputs: ['"critical"', '"1 hour"'] },
        { inputs: ['"high"', '"medium"'], outputs: ['"high"', '"4 hours"'] },
        { inputs: ['"high"', '"low"'], outputs: ['"medium"', '"8 hours"'] },
        { inputs: ['"medium"', '"high"'], outputs: ['"high"', '"4 hours"'] },
        { inputs: ['"medium"', '"medium"'], outputs: ['"medium"', '"8 hours"'] },
        { inputs: ['"medium"', '"low"'], outputs: ['"low"', '"24 hours"'] },
        { inputs: ['"low"', '"high"'], outputs: ['"medium"', '"8 hours"'] },
        { inputs: ['"low"', '"medium"'], outputs: ['"low"', '"24 hours"'] },
        { inputs: ['"low"', '"low"'], outputs: ['"low"', '"48 hours"'] },
      ],
    ),
  },
];

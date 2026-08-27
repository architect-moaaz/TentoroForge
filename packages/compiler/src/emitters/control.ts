/**
 * Control flow node emitters: Slot, Repeater, AsyncSlot
 */

import type { SlotNode, RepeaterNode, AsyncSlotNode, IRNode } from "@tentoroforge/ir";
import { buildClasses, gapClass } from "@tentoroforge/ir";
import { EmitContext } from "../context.js";
import { emitBinding, emitExpression } from "../bindings.js";
import { emitNode } from "../emit.js";

// ---------------------------------------------------------------------------
// Slot — conditional rendering
// ---------------------------------------------------------------------------

export function emitSlot(node: SlotNode, ctx: EmitContext): string {
  // if/then/else style
  if (node.if) {
    const condition = emitExpression(node.if, ctx);
    const thenBlock = node.then ? emitNode(node.then, ctx) : "null";
    const elseBlock = node.else ? emitNode(node.else, ctx) : "null";
    return `{${condition} ? (\n${thenBlock}\n) : (\n${elseBlock}\n)}`;
  }

  // switch/cases style
  if (node.switch && node.cases) {
    const switchExpr = emitExpression(node.switch, ctx);
    const entries = Object.entries(node.cases);
    const defaultCase = node.cases["default"];
    const specificCases = entries.filter(([key]) => key !== "default");

    if (specificCases.length === 0 && defaultCase) {
      return emitNode(defaultCase, ctx);
    }

    // Build nested ternary
    let code = "";
    for (const [value, caseNode] of specificCases) {
      const rendered = emitNode(caseNode as IRNode, ctx);
      const isNull = value === "null";
      const condition = isNull ? `${switchExpr} == null` : `${switchExpr} === ${JSON.stringify(value)}`;
      code += `${condition} ? (\n${rendered}\n) : `;
    }

    // Default fallback
    const defaultRendered = defaultCase ? emitNode(defaultCase as IRNode, ctx) : "null";
    code += `(\n${defaultRendered}\n)`;

    return `{${code}}`;
  }

  return "null";
}

// ---------------------------------------------------------------------------
// Repeater — loop over data
// ---------------------------------------------------------------------------

export function emitRepeater(node: RepeaterNode, ctx: EmitContext): string {
  const dataExpr = emitBinding(node.data, ctx);
  const keyField = node.itemKey || "id";
  const itemVar = "item";

  const templateCtx = ctx.child({ iteratorVar: itemVar });
  const template = emitNode(node.template, templateCtx);

  const emptyState = node.emptyState ? emitNode(node.emptyState, ctx) : null;

  const containerClasses = buildClasses([
    node.direction === "horizontal"
      ? "flex flex-row"
      : node.direction === "grid"
        ? `grid ${node.columns ? resolveGridCols(node.columns) : "grid-cols-2"}`
        : "flex flex-col",
    node.gap && gapClass(node.gap),
  ]);

  const emptyCheck = emptyState
    ? `{!${dataExpr} || ${dataExpr}.length === 0 ? (\n${emptyState}\n) : (\n`
    : `{${dataExpr} && ${dataExpr}.length > 0 && (\n`;

  const closeCheck = emptyState ? `\n)}` : `\n)}`;

  return `${emptyCheck}<div className="${containerClasses}">
{${dataExpr}.map((${itemVar}: any) => (
<div key={${itemVar}.${keyField}}>
${template}
</div>
))}
</div>${closeCheck}`;
}

function resolveGridCols(columns: RepeaterNode["columns"]): string {
  if (typeof columns === "number") return `grid-cols-${columns}`;
  if (typeof columns === "object" && columns !== null) {
    return Object.entries(columns)
      .map(([bp, val]) => (bp === "default" ? `grid-cols-${val}` : `${bp}:grid-cols-${val}`))
      .join(" ");
  }
  return "grid-cols-2";
}

// ---------------------------------------------------------------------------
// AsyncSlot — renders when data is loaded
// ---------------------------------------------------------------------------

export function emitAsyncSlot(node: AsyncSlotNode, ctx: EmitContext): string {
  const dataExpr = emitBinding(node.data, ctx);
  const loadingBlock = node.loading ? emitNode(node.loading, ctx) : '<div className="animate-pulse">Loading...</div>';
  const errorBlock = node.error
    ? emitNode(node.error, ctx)
    : '<div className="text-destructive">Failed to load data</div>';

  const children = node.children
    .map((child, i) => emitNode(child, ctx.child({ currentPath: [...ctx.currentPath, i] })))
    .join("\n");

  // Derive loading/error state variable names from the data source
  const sourceName = node.data.startsWith("source:") ? node.data.slice(7).split(".")[0] : "data";
  const loadingVar = `${sourceName}IsLoading`;
  const errorVar = `${sourceName}Error`;

  return `{${loadingVar} ? (\n${loadingBlock}\n) : ${errorVar} ? (\n${errorBlock}\n) : (\n${children}\n)}`;
}

/**
 * Layout node emitters: Stack, Row, Grid, Spacer, Divider
 */

import type { StackNode, RowNode, GridNode, SpacerNode, DividerNode, IRNode } from "@tentoroforge/ir";
import {
  buildClasses,
  gapClass,
  paddingClasses,
  marginClasses,
  alignClass,
  justifyClass,
  spacingToTailwind,
  responsiveClasses,
} from "@tentoroforge/ir";
import type { SpacingToken } from "@tentoroforge/ir";
import { EmitContext } from "../context.js";
import { emitNode } from "../emit.js";

export function emitStack(node: StackNode, ctx: EmitContext): string {
  const classes = buildClasses([
    "flex flex-col",
    node.gap && resolveGap(node.gap),
    node.padding && paddingClasses(node.padding),
    node.margin && marginClasses(node.margin),
    node.align && alignClass(node.align),
    node.justify && justifyClass(node.justify),
    node.width && widthClass(node.width),
    node.height && heightClass(node.height),
    node.flex !== undefined && `flex-${node.flex}`,
    node.scroll && "overflow-y-auto",
    node.wrap && "flex-wrap",
  ]);

  const children = emitChildren(node.children, ctx);
  return `<div className="${classes}">\n${children}\n</div>`;
}

export function emitRow(node: RowNode, ctx: EmitContext): string {
  const directionClass = node.direction
    ? resolveDirection(node.direction)
    : "flex-row";

  const classes = buildClasses([
    "flex",
    directionClass,
    node.gap && resolveGap(node.gap),
    node.padding && paddingClasses(node.padding),
    node.margin && marginClasses(node.margin),
    node.align && alignClass(node.align),
    node.justify && justifyClass(node.justify),
    node.width && widthClass(node.width),
    node.height && heightClass(node.height),
    node.flex !== undefined && `flex-${node.flex}`,
    node.scroll && "overflow-x-auto",
    node.wrap && "flex-wrap",
  ]);

  const children = emitChildren(node.children, ctx);
  return `<div className="${classes}">\n${children}\n</div>`;
}

export function emitGrid(node: GridNode, ctx: EmitContext): string {
  const colsClass = resolveColumns(node.columns);
  const classes = buildClasses([
    "grid",
    colsClass,
    node.gap && resolveGap(node.gap),
    node.padding && paddingClasses(node.padding),
    node.margin && marginClasses(node.margin),
    node.width && widthClass(node.width),
    node.height && heightClass(node.height),
  ]);

  const children = emitChildren(node.children, ctx);
  return `<div className="${classes}">\n${children}\n</div>`;
}

export function emitSpacer(node: SpacerNode, _ctx: EmitContext): string {
  const tw = spacingToTailwind(node.size);
  return `<div className="h-${tw}" />`;
}

export function emitDivider(node: DividerNode, _ctx: EmitContext): string {
  if (node.direction === "vertical") {
    return `<div className="w-px self-stretch bg-border" />`;
  }
  if (node.label) {
    return `<div className="relative py-2"><div className="absolute inset-0 flex items-center"><span className="w-full border-t" /></div><div className="relative flex justify-center text-xs uppercase"><span className="bg-background px-2 text-muted-foreground">${node.label}</span></div></div>`;
  }
  return `<hr className="border-border" />`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function emitChildren(children: IRNode[] | undefined, ctx: EmitContext): string {
  if (!children || !Array.isArray(children)) return "";
  return children
    .map((child, i) => {
      if (!child || !child.node) return "";
      const childCtx = ctx.child({ currentPath: [...ctx.currentPath, i] });
      return emitNode(child, childCtx);
    })
    .filter(Boolean)
    .join("\n");
}

function resolveGap(gap: StackNode["gap"]): string {
  if (typeof gap === "string") return gapClass(gap);
  return responsiveClasses(gap!, (val: SpacingToken, prefix: string) => `${prefix}gap-${spacingToTailwind(val)}`);
}

function resolveDirection(direction: RowNode["direction"]): string {
  if (typeof direction === "string") {
    return direction === "col" ? "flex-col" : "flex-row";
  }
  return responsiveClasses(direction!, (val: string, prefix: string) =>
    `${prefix}${val === "col" ? "flex-col" : "flex-row"}`,
  );
}

function resolveColumns(columns: GridNode["columns"]): string {
  if (typeof columns === "number") return `grid-cols-${columns}`;
  return responsiveClasses(columns, (val: number, prefix: string) => `${prefix}grid-cols-${val}`);
}

function widthClass(width: string): string {
  if (width === "full") return "w-full";
  if (width === "auto") return "w-auto";
  if (width === "screen") return "w-screen";
  // Custom width — use inline style or arbitrary value
  return `w-[${width}]`;
}

function heightClass(height: string): string {
  if (height === "full") return "h-full";
  if (height === "auto") return "h-auto";
  if (height === "screen") return "h-screen";
  return `h-[${height}]`;
}

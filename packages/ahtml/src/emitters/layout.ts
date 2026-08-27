/**
 * Layout node → Annotated HTML emitters: Stack, Row, Grid, Spacer, Divider
 *
 * Mirrors packages/compiler/src/emitters/layout.ts but outputs
 * plain HTML with Tailwind classes and data-* annotations.
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
import { emitNodeToHtml, indent } from "../ir-to-html.js";

// ---------------------------------------------------------------------------
// Stack
// ---------------------------------------------------------------------------

export function emitStackHtml(node: StackNode, depth: number): string {
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

  const attrs = [`class="${classes}"`, `data-component="Stack"`];
  if (node.visible) attrs.push(`data-visible="${node.visible}"`);

  const children = emitChildren(node.children, depth + 1);
  const pad = indent(depth);
  return `${pad}<div ${attrs.join(" ")}>\n${children}\n${pad}</div>`;
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

export function emitRowHtml(node: RowNode, depth: number): string {
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

  const attrs = [`class="${classes}"`, `data-component="Row"`];
  if (node.visible) attrs.push(`data-visible="${node.visible}"`);

  const children = emitChildren(node.children, depth + 1);
  const pad = indent(depth);
  return `${pad}<div ${attrs.join(" ")}>\n${children}\n${pad}</div>`;
}

// ---------------------------------------------------------------------------
// Grid
// ---------------------------------------------------------------------------

export function emitGridHtml(node: GridNode, depth: number): string {
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

  const attrs = [`class="${classes}"`, `data-component="Grid"`];
  if (node.visible) attrs.push(`data-visible="${node.visible}"`);

  const children = emitChildren(node.children, depth + 1);
  const pad = indent(depth);
  return `${pad}<div ${attrs.join(" ")}>\n${children}\n${pad}</div>`;
}

// ---------------------------------------------------------------------------
// Spacer
// ---------------------------------------------------------------------------

export function emitSpacerHtml(node: SpacerNode, depth: number): string {
  const tw = spacingToTailwind(node.size);
  const pad = indent(depth);
  return `${pad}<div class="h-${tw}"></div>`;
}

// ---------------------------------------------------------------------------
// Divider
// ---------------------------------------------------------------------------

export function emitDividerHtml(node: DividerNode, depth: number): string {
  const pad = indent(depth);
  if (node.direction === "vertical") {
    return `${pad}<div class="w-px self-stretch bg-border"></div>`;
  }
  if (node.label) {
    return `${pad}<div class="relative py-2"><div class="absolute inset-0 flex items-center"><span class="w-full border-t"></span></div><div class="relative flex justify-center text-xs uppercase"><span class="bg-background px-2 text-muted-foreground">${node.label}</span></div></div>`;
  }
  return `${pad}<hr class="border-border" />`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function emitChildren(children: IRNode[] | undefined, depth: number): string {
  if (!children || !Array.isArray(children)) return "";
  return children
    .map((child) => {
      if (!child || !child.node) return "";
      return emitNodeToHtml(child, depth);
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
  return `w-[${width}]`;
}

function heightClass(height: string): string {
  if (height === "full") return "h-full";
  if (height === "auto") return "h-auto";
  if (height === "screen") return "h-screen";
  return `h-[${height}]`;
}

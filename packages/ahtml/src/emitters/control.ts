/**
 * Control flow node → Annotated HTML emitters: Slot, Repeater, AsyncSlot,
 * PlaceholderSlot
 */

import type {
  SlotNode, RepeaterNode, AsyncSlotNode, PlaceholderSlotNode, IRNode,
} from "@tentoroforge/ir";
import { buildClasses, gapClass } from "@tentoroforge/ir";
import { emitNodeToHtml, indent } from "../ir-to-html.js";

// ---------------------------------------------------------------------------
// Slot — conditional rendering
// ---------------------------------------------------------------------------

export function emitSlotHtml(node: SlotNode, depth: number): string {
  const pad = indent(depth);

  // if/then/else style
  if (node.if) {
    const parts: string[] = [];
    if (node.then) {
      parts.push(`${pad}<div data-visible="${node.if}">\n${emitNodeToHtml(node.then, depth + 1)}\n${pad}</div>`);
    }
    if (node.else) {
      parts.push(`${pad}<div data-visible-not="${node.if}">\n${emitNodeToHtml(node.else, depth + 1)}\n${pad}</div>`);
    }
    return parts.join("\n");
  }

  // switch/cases style
  if (node.switch && node.cases) {
    const entries = Object.entries(node.cases);
    return entries
      .map(([value, caseNode]) => {
        const condition = value === "default"
          ? `${node.switch}:default`
          : `${node.switch} === ${value}`;
        return `${pad}<div data-visible="${condition}">\n${emitNodeToHtml(caseNode as IRNode, depth + 1)}\n${pad}</div>`;
      })
      .join("\n");
  }

  return "";
}

// ---------------------------------------------------------------------------
// Repeater — loop over data
// ---------------------------------------------------------------------------

export function emitRepeaterHtml(node: RepeaterNode, depth: number): string {
  const pad = indent(depth);
  const dataRef = node.data.replace(/^source:/, "");
  const keyField = node.itemKey || "id";

  const containerClasses = buildClasses([
    node.direction === "horizontal"
      ? "flex flex-row"
      : node.direction === "grid"
        ? `grid ${node.columns ? resolveGridCols(node.columns) : "grid-cols-2"}`
        : "flex flex-col",
    node.gap && gapClass(node.gap),
  ]);

  const attrs: string[] = [
    `class="${containerClasses}"`,
    `data-repeat="${dataRef}"`,
    `data-repeat-key="${keyField}"`,
  ];

  const template = emitNodeToHtml(node.template, depth + 1);

  let emptyHtml = "";
  if (node.emptyState) {
    emptyHtml = `\n${pad}<div data-repeat-empty="${dataRef}">\n${emitNodeToHtml(node.emptyState, depth + 1)}\n${pad}</div>`;
  }

  return `${pad}<div ${attrs.join(" ")}>
${template}
${pad}</div>${emptyHtml}`;
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
// AsyncSlot — data-dependent rendering
// ---------------------------------------------------------------------------

export function emitAsyncSlotHtml(node: AsyncSlotNode, depth: number): string {
  const pad = indent(depth);
  const dataRef = node.data.replace(/^source:/, "");

  const children = node.children
    .map((child) => emitNodeToHtml(child, depth + 1))
    .join("\n");

  const loadingHtml = node.loading
    ? emitNodeToHtml(node.loading, depth + 1)
    : `${indent(depth + 1)}<div class="animate-pulse">Loading...</div>`;

  const errorHtml = node.error
    ? emitNodeToHtml(node.error, depth + 1)
    : `${indent(depth + 1)}<div class="text-destructive">Failed to load data</div>`;

  return `${pad}<div data-component="AsyncSlot" data-source="${dataRef}">
${indent(depth + 1)}<div data-async-loading>
${loadingHtml}
${indent(depth + 1)}</div>
${indent(depth + 1)}<div data-async-error>
${errorHtml}
${indent(depth + 1)}</div>
${indent(depth + 1)}<div data-async-content>
${children}
${indent(depth + 1)}</div>
${pad}</div>`;
}

// ---------------------------------------------------------------------------
// PlaceholderSlot — unfilled slot marker
// ---------------------------------------------------------------------------

export function emitPlaceholderSlotHtml(node: PlaceholderSlotNode, depth: number): string {
  const pad = indent(depth);
  const attrs: string[] = [
    `class="min-h-[100px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center"`,
    `data-slot="${node.$slot}"`,
  ];
  if (node.entity) attrs.push(`data-entity="${node.entity}"`);
  if (node.config) attrs.push(`data-slot-config='${JSON.stringify(node.config)}'`);

  const label = node.entity
    ? `${node.$slot} (${node.entity})`
    : node.$slot;

  return `${pad}<div ${attrs.join(" ")}>
${indent(depth + 1)}<span class="text-sm text-muted-foreground">${label}</span>
${pad}</div>`;
}

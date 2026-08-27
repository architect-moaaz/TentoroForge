/**
 * Composite node → Annotated HTML emitters: DataTable, Form, Card, Tabs,
 * Accordion, Chart, ModalTrigger
 */

import type {
  DataTableNode, FormNode, CardNode, TabsNode,
  AccordionNode, ChartNode, ModalTriggerNode, ColumnDef, IRNode,
} from "@tentoroforge/ir";
import { buildClasses, paddingClasses, radiusClass } from "@tentoroforge/ir";
import { emitNodeToHtml, indent } from "../ir-to-html.js";

// ---------------------------------------------------------------------------
// DataTable
// ---------------------------------------------------------------------------

export function emitDataTableHtml(node: DataTableNode, depth: number): string {
  const pad = indent(depth);

  const attrs: string[] = [
    `class="w-full"`,
    `data-component="DataTable"`,
    `data-source="${node.data.replace(/^source:/, "")}"`,
  ];

  const componentProps: Record<string, unknown> = {};
  if (node.pagination) componentProps.pagination = node.pagination;
  if (node.sorting) componentProps.sorting = node.sorting;
  if (node.selection && node.selection !== "none") componentProps.selection = node.selection;
  if (node.density) componentProps.density = node.density;
  if (Object.keys(componentProps).length > 0) {
    attrs.push(`data-component-props='${JSON.stringify(componentProps)}'`);
  }

  if (node.onRowClick) {
    attrs.push(`data-action="${node.onRowClick.type}"`);
    if (node.onRowClick.type === "navigate" && "to" in node.onRowClick) {
      attrs.push(`data-action-to="${node.onRowClick.to}"`);
    }
  }

  // Build table header and sample row
  const headers = node.columns
    .map((col) => `${indent(depth + 3)}<th class="text-left p-2 text-sm font-medium text-muted-foreground">${col.header || capitalize(col.field)}</th>`)
    .join("\n");

  const sampleCells = node.columns
    .map((col) => {
      const render = typeof col.render === "string" ? ` data-field-render="${col.render}"` : "";
      return `${indent(depth + 3)}<td class="p-2 text-sm" data-field="${col.field}"${render}>{{${col.field}}}</td>`;
    })
    .join("\n");

  return `${pad}<div ${attrs.join(" ")}>
${indent(depth + 1)}<table class="w-full border-collapse">
${indent(depth + 2)}<thead>
${indent(depth + 3)}<tr class="border-b">
${headers}
${indent(depth + 3)}</tr>
${indent(depth + 2)}</thead>
${indent(depth + 2)}<tbody>
${indent(depth + 3)}<tr class="border-b" data-repeat="${node.data.replace(/^source:/, "")}">
${sampleCells}
${indent(depth + 3)}</tr>
${indent(depth + 2)}</tbody>
${indent(depth + 1)}</table>
${pad}</div>`;
}

// ---------------------------------------------------------------------------
// Form
// ---------------------------------------------------------------------------

export function emitFormHtml(node: FormNode, depth: number): string {
  const pad = indent(depth);

  const layoutClass =
    node.layout === "two-column"
      ? "grid grid-cols-1 md:grid-cols-2 gap-4"
      : "space-y-4";

  const attrs: string[] = [
    `class="${layoutClass}"`,
    `data-component="Form"`,
    `data-bind="${node.bind}"`,
  ];

  // Encode onSubmit as action
  if (node.onSubmit) {
    attrs.push(`data-action="${node.onSubmit.type}"`);
    if (node.onSubmit.type === "mutate" && "source" in node.onSubmit) {
      attrs.push(`data-action-source="${node.onSubmit.source}"`);
    }
  }

  // Emit form fields as annotated inputs
  const fields = (node.fields || [])
    .map((field) => {
      const inputType = field.node || "TextInput";
      const fieldDepth = depth + 1;
      const p = indent(fieldDepth);

      // Simplified field rendering
      const bind = `${node.bind}.${field.field}`;
      const required = field.required ? " required" : "";

      if (inputType === "Select") {
        return `${p}<div class="space-y-2">
${indent(fieldDepth + 1)}<label class="text-sm font-medium">${field.label}</label>
${indent(fieldDepth + 1)}<select class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" data-bind="${bind}"${required}>
${indent(fieldDepth + 2)}<option value="">Select...</option>
${indent(fieldDepth + 1)}</select>
${p}</div>`;
      }

      if (inputType === "TextArea") {
        return `${p}<div class="space-y-2">
${indent(fieldDepth + 1)}<label class="text-sm font-medium">${field.label}</label>
${indent(fieldDepth + 1)}<textarea class="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm" data-bind="${bind}"${required}></textarea>
${p}</div>`;
      }

      if (inputType === "Checkbox" || inputType === "Toggle") {
        return `${p}<div class="flex items-center gap-2">
${indent(fieldDepth + 1)}<input type="checkbox" data-bind="${bind}" />
${indent(fieldDepth + 1)}<label class="text-sm font-medium">${field.label}</label>
${p}</div>`;
      }

      if (inputType === "DatePicker") {
        return `${p}<div class="space-y-2">
${indent(fieldDepth + 1)}<label class="text-sm font-medium">${field.label}</label>
${indent(fieldDepth + 1)}<input type="date" class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" data-bind="${bind}"${required} />
${p}</div>`;
      }

      // Default: TextInput
      const inputTypeAttr = inputType === "TextInput" ? "text" : "text";
      return `${p}<div class="space-y-2">
${indent(fieldDepth + 1)}<label class="text-sm font-medium">${field.label}</label>
${indent(fieldDepth + 1)}<input type="${inputTypeAttr}" class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder="${(field as any).placeholder || ""}" data-bind="${bind}"${required} />
${p}</div>`;
    })
    .join("\n");

  // Form action buttons
  const actionsHtml = node.actions
    ? node.actions.map((actionNode) => emitNodeToHtml(actionNode, depth + 1)).join("\n")
    : "";

  return `${pad}<form ${attrs.join(" ")}>
${fields}
${actionsHtml}
${pad}</form>`;
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

export function emitCardHtml(node: CardNode, depth: number): string {
  const pad = indent(depth);
  const classes = buildClasses([
    "rounded-lg border bg-card",
    node.radius && radiusClass(node.radius),
    node.shadow && node.shadow !== "none" && `shadow-${node.shadow}`,
    node.hoverable && "hover:shadow-md cursor-pointer transition-shadow",
  ]);

  const attrs: string[] = [`class="${classes}"`, `data-component="Card"`];
  if (node.action) {
    attrs.push(`data-action="${node.action.type}"`);
    if (node.action.type === "navigate" && "to" in node.action) {
      attrs.push(`data-action-to="${node.action.to}"`);
    }
  }
  if (node.visible) attrs.push(`data-visible="${node.visible}"`);

  const contentPadding = node.padding ? paddingClasses(node.padding) : "p-4";
  const parts: string[] = [];

  if (node.media) parts.push(emitNodeToHtml(node.media, depth + 2));
  if (node.header) {
    parts.push(`${indent(depth + 2)}<div class="border-b pb-3 mb-3">${emitNodeToHtml(node.header, 0).trim()}</div>`);
  }
  if (node.children) {
    parts.push(...node.children.map((child) => emitNodeToHtml(child, depth + 2)));
  }
  if (node.footer) {
    parts.push(`${indent(depth + 2)}<div class="border-t pt-3 mt-3">${emitNodeToHtml(node.footer, 0).trim()}</div>`);
  }

  return `${pad}<div ${attrs.join(" ")}>
${indent(depth + 1)}<div class="${contentPadding}">
${parts.join("\n")}
${indent(depth + 1)}</div>
${pad}</div>`;
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

export function emitTabsHtml(node: TabsNode, depth: number): string {
  const pad = indent(depth);
  const defaultTab = node.defaultTab || node.tabs[0]?.id || "";

  const triggers = node.tabs
    .map((tab) => `${indent(depth + 2)}<button class="px-3 py-1.5 text-sm font-medium" data-tab="${tab.id}">${tab.label}</button>`)
    .join("\n");

  const contents = node.tabs
    .map((tab) => {
      const content = emitNodeToHtml(tab.content, depth + 2);
      return `${indent(depth + 1)}<div data-tab-content="${tab.id}">\n${content}\n${indent(depth + 1)}</div>`;
    })
    .join("\n");

  return `${pad}<div data-component="Tabs" data-component-props='${JSON.stringify({ defaultTab })}'>
${indent(depth + 1)}<div class="flex border-b">
${triggers}
${indent(depth + 1)}</div>
${contents}
${pad}</div>`;
}

// ---------------------------------------------------------------------------
// Accordion
// ---------------------------------------------------------------------------

export function emitAccordionHtml(node: AccordionNode, depth: number): string {
  const pad = indent(depth);
  const type = node.type || "single";

  const items = node.items
    .map((item) => {
      const content = emitNodeToHtml(item.content, depth + 2);
      return `${indent(depth + 1)}<div class="border-b" data-accordion-item="${item.id}">
${indent(depth + 2)}<button class="flex w-full items-center justify-between py-4 text-sm font-medium">${item.title}</button>
${indent(depth + 2)}<div class="pb-4">
${content}
${indent(depth + 2)}</div>
${indent(depth + 1)}</div>`;
    })
    .join("\n");

  return `${pad}<div data-component="Accordion" data-component-props='${JSON.stringify({ type })}'>
${items}
${pad}</div>`;
}

// ---------------------------------------------------------------------------
// Chart
// ---------------------------------------------------------------------------

export function emitChartHtml(node: ChartNode, depth: number): string {
  const pad = indent(depth);
  const height = node.height || "300px";
  const props: Record<string, unknown> = {
    type: node.type,
    xAxis: node.xAxis,
    yAxis: node.yAxis,
    series: node.series,
    legend: node.legend,
  };

  return `${pad}<div class="w-full" style="height: ${height}" data-component="Chart" data-source="${node.data.replace(/^source:/, "")}" data-component-props='${JSON.stringify(props)}'>
${indent(depth + 1)}<div class="flex items-center justify-center h-full border rounded-lg bg-muted/20">
${indent(depth + 2)}<span class="text-sm text-muted-foreground">Chart (${node.type})</span>
${indent(depth + 1)}</div>
${pad}</div>`;
}

// ---------------------------------------------------------------------------
// ModalTrigger
// ---------------------------------------------------------------------------

export function emitModalTriggerHtml(node: ModalTriggerNode, depth: number): string {
  const pad = indent(depth);
  const children = node.children
    .map((child) => emitNodeToHtml(child, depth + 1))
    .join("\n");

  return `${pad}<div data-modal-trigger="${node.modal}">
${children}
${pad}</div>`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

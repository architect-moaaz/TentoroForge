/**
 * Composite node emitters: DataTable, Form, Card, Tabs, Accordion, Chart, ModalTrigger
 */

import type {
  DataTableNode, FormNode, CardNode, TabsNode,
  AccordionNode, ChartNode, ModalTriggerNode, ColumnDef, IRNode,
} from "@tentoroforge/ir";
import { buildClasses, paddingClasses, radiusClass } from "@tentoroforge/ir";
import { EmitContext } from "../context.js";
import { emitBinding, emitJSXContent } from "../bindings.js";
import { emitActionHandler } from "../actions.js";
import { emitNode } from "../emit.js";

// ---------------------------------------------------------------------------
// DataTable
// ---------------------------------------------------------------------------

export function emitDataTable(node: DataTableNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/data-table", "DataTable");
  ctx.ensureImport("react", "useMemo");

  const dataExpr = emitBinding(node.data, ctx);
  const columns = node.columns.map((col) => emitColumnDef(col, ctx)).join(",\n");

  // Memoize columns
  const colsVarName = `columns_${Math.random().toString(36).slice(2, 6)}`;
  ctx.addHelper(`const ${colsVarName} = useMemo(() => [\n${columns}\n], []);`);

  const props: string[] = [
    `data={${dataExpr}?.items ?? ${dataExpr} ?? []}`,
    `columns={${colsVarName}}`,
  ];

  if (node.onRowClick) {
    const handler = emitActionHandler(node.onRowClick, ctx, "row.original");
    props.push(`onRowClick={(row) => ${handler.replace(/^\(row\.original\) => /, "")}}`);
  }

  if (node.pagination) {
    props.push(`pagination`);
  }

  if (node.sorting) {
    props.push(`sorting`);
  }

  // Empty state
  let emptyStateEl = "";
  if (node.emptyState) {
    emptyStateEl = `\nemptyState={${wrapInJSX(emitNode(node.emptyState, ctx))}}`;
  }

  return `<DataTable ${props.join(" ")}${emptyStateEl} />`;
}

function emitColumnDef(col: ColumnDef, ctx: EmitContext): string {
  const parts: string[] = [
    `accessorKey: "${col.field}"`,
    `header: ${JSON.stringify(col.header || capitalize(col.field))}`,
  ];

  if (col.width) {
    // Parse width to size
    const size = parseInt(col.width.replace(/[^0-9]/g, ""), 10);
    if (!isNaN(size)) parts.push(`size: ${size}`);
  }

  if (col.sortable === false) {
    parts.push(`enableSorting: false`);
  }

  // Render
  if (col.render) {
    if (typeof col.render === "string") {
      parts.push(`cell: ({ row }) => ${emitColumnRenderShorthand(col.render, col.field, ctx)}`);
    } else {
      // Full node tree render
      const renderCtx = ctx.child({ iteratorVar: "row.original" });
      const rendered = emitNode(col.render as IRNode, renderCtx);
      parts.push(`cell: ({ row }) => (\n${rendered}\n)`);
    }
  }

  return `{\n  ${parts.join(",\n  ")}\n}`;
}

function emitColumnRenderShorthand(shorthand: string, field: string, ctx: EmitContext): string {
  if (shorthand === "badge") {
    ctx.ensureImport("@/components/ui/badge", "Badge");
    return `<Badge>{row.getValue("${field}")}</Badge>`;
  }
  if (shorthand === "date:relative") {
    ctx.ensureImport("@/lib/formatters", "formatRelativeDate");
    return `formatRelativeDate(row.getValue("${field}"))`;
  }
  if (shorthand === "boolean") {
    ctx.ensureImport("lucide-react", "Check");
    return `row.getValue("${field}") ? <Check className="h-4 w-4" /> : <span className="text-muted-foreground">—</span>`;
  }
  if (shorthand.startsWith("truncate:")) {
    const lines = shorthand.split(":")[1];
    return `<span className="line-clamp-${lines}">{row.getValue("${field}")}</span>`;
  }
  return `row.getValue("${field}")`;
}

// ---------------------------------------------------------------------------
// Form
// ---------------------------------------------------------------------------

export function emitForm(node: FormNode, ctx: EmitContext): string {
  // For now, emit a simple form structure
  // Full implementation would generate Zod schemas + react-hook-form
  const fields = (node.fields || [])
    .map((field) => {
      const inputType = field.node || "TextInput";
      // Create a lightweight input node and emit it
      const inputNode = {
        node: inputType,
        bind: `${node.bind}.${field.field}`,
        label: field.label,
        placeholder: (field as Record<string, unknown>).placeholder as string || "",
        required: field.required,
        ...Object.fromEntries(
          Object.entries(field).filter(
            ([k]) => !["field", "label", "required", "validation", "span", "visible", "node"].includes(k),
          ),
        ),
      };
      return emitNode(inputNode as unknown as IRNode, ctx);
    })
    .join("\n");

  // Form actions
  const actionsEl = node.actions
    ? node.actions.map((actionNode) => emitNode(actionNode, ctx)).join("\n")
    : "";

  const handler = emitActionHandler(node.onSubmit, ctx);
  ctx.ensureImport("react", "FormEvent");

  const layoutClass =
    node.layout === "two-column"
      ? "grid grid-cols-1 md:grid-cols-2 gap-4"
      : "space-y-4";

  return `<form onSubmit={(e: FormEvent) => { e.preventDefault(); ${handler.replace(/^\(\) => /, "")}; }} className="${layoutClass}">
${fields}
${actionsEl}
</form>`;
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

export function emitCard(node: CardNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/card", "Card", "CardContent");

  const classes = buildClasses([
    node.radius && radiusClass(node.radius),
    node.shadow && node.shadow !== "none" && `shadow-${node.shadow}`,
    node.hoverable && "hover:shadow-md cursor-pointer transition-shadow",
    node.border !== false && "border",
  ]);

  let actionProps = "";
  if (node.action) {
    const handler = emitActionHandler(node.action, ctx);
    actionProps = ` onClick={${handler}}`;
  }

  if (typeof node.selected === "string" && node.selected.includes("===")) {
    // Dynamic selection class — simplified
    const selectedExpr = node.selected.replace(/\{\{(.+?)\}\}/g, (_m, v) => v.trim());
    actionProps += ` data-selected={${selectedExpr} || undefined}`;
  }

  const contentPadding = node.padding ? paddingClasses(node.padding) : "p-4";

  // Build card body
  const parts: string[] = [];
  if (node.media) parts.push(emitNode(node.media, ctx));
  if (node.header) {
    parts.push(`<div className="border-b pb-3 mb-3">${emitNode(node.header, ctx)}</div>`);
  }
  if (node.children) {
    parts.push(
      ...node.children.map((child, i) =>
        emitNode(child, ctx.child({ currentPath: [...ctx.currentPath, i] })),
      ),
    );
  }
  if (node.footer) {
    parts.push(`<div className="border-t pt-3 mt-3">${emitNode(node.footer, ctx)}</div>`);
  }

  return `<Card className="${classes}"${actionProps}>
<CardContent className="${contentPadding}">
${parts.join("\n")}
</CardContent>
</Card>`;
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

export function emitTabs(node: TabsNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/tabs", "Tabs", "TabsList", "TabsTrigger", "TabsContent");

  const defaultTab = node.defaultTab || node.tabs[0]?.id || "";
  const triggers = node.tabs
    .map((tab) => {
      const badge = tab.badge !== undefined ? ` <span className="ml-1 text-xs">(${tab.badge})</span>` : "";
      return `<TabsTrigger value="${tab.id}">${tab.label}${badge}</TabsTrigger>`;
    })
    .join("\n");

  const contents = node.tabs
    .map((tab) => {
      const content = emitNode(tab.content, ctx);
      return `<TabsContent value="${tab.id}">\n${content}\n</TabsContent>`;
    })
    .join("\n");

  return `<Tabs defaultValue="${defaultTab}">
<TabsList>
${triggers}
</TabsList>
${contents}
</Tabs>`;
}

// ---------------------------------------------------------------------------
// Accordion
// ---------------------------------------------------------------------------

export function emitAccordion(node: AccordionNode, ctx: EmitContext): string {
  ctx.ensureImport("@/components/ui/accordion", "Accordion", "AccordionItem", "AccordionTrigger", "AccordionContent");

  const type = node.type || "single";
  const items = node.items
    .map((item) => {
      const content = emitNode(item.content, ctx);
      return `<AccordionItem value="${item.id}">
<AccordionTrigger>${item.title}</AccordionTrigger>
<AccordionContent>
${content}
</AccordionContent>
</AccordionItem>`;
    })
    .join("\n");

  return `<Accordion type="${type}" collapsible>
${items}
</Accordion>`;
}

// ---------------------------------------------------------------------------
// Chart (simplified — renders placeholder)
// ---------------------------------------------------------------------------

export function emitChart(node: ChartNode, ctx: EmitContext): string {
  const dataExpr = emitBinding(node.data, ctx);
  const height = node.height || "300px";

  return `<div className="w-full" style={{ height: "${height}" }}>
{/* Chart: ${node.type} — data from ${node.data} */}
<div className="flex items-center justify-center h-full border rounded-lg bg-muted/20">
<span className="text-sm text-muted-foreground">Chart (${node.type})</span>
</div>
</div>`;
}

// ---------------------------------------------------------------------------
// ModalTrigger
// ---------------------------------------------------------------------------

export function emitModalTrigger(node: ModalTriggerNode, ctx: EmitContext): string {
  const children = node.children
    .map((child, i) =>
      emitNode(child, ctx.child({ currentPath: [...ctx.currentPath, i] })),
    )
    .join("\n");

  // The modal itself is emitted at the page level
  // The trigger just opens it
  const stateName = `${node.modal}Open`;
  const setter = `set${stateName.charAt(0).toUpperCase()}${stateName.slice(1)}`;
  ctx.addState(stateName, "boolean", "false");
  ctx.ensureImport("react", "useState");

  return `<div onClick={() => ${setter}(true)}>
${children}
</div>`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function wrapInJSX(jsx: string): string {
  return `(<>\n${jsx}\n</>)`;
}

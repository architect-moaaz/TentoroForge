/**
 * JSX the guided flows write (UX-003): a form from a workflow, a table from
 * the page's data, a button that opens a page or runs a workflow. Everything
 * here is composed from the app SDK and the UI kit the page already compiles
 * against, so what a guide inserts is what the compiler accepts.
 */
import type { EntityRef, ModelNode, Op, PageModel, PageRef, WidgetRef, WorkflowInput, WorkflowRef } from "../types";

const q = (s: string) => JSON.stringify(s);

export function humanise(name: string): string {
  const spaced = name.replace(/(?<!^)(?=[A-Z])/g, " ").replace(/[_-]+/g, " ");
  return spaced.split(/\s+/).filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
}

function fieldKind(input: WorkflowInput): string {
  const t = (input.type || "").toLowerCase();
  if (input.options?.length) return "select";
  if (t.includes("text") && !t.includes("string")) return "textarea";
  if (t === "email") return "email";
  if (t === "date") return "date";
  if (t === "timestamp" || t === "datetime") return "datetime";
  if (t === "boolean" || t === "bool") return "checkbox";
  if (["number", "integer", "int", "decimal", "float"].includes(t)) return "number";
  return "text";
}

/** One `fields={{ … }}` entry per input; a record input the page is about is fixed by value. */
export function formFields(workflow: WorkflowRef, fixed: Record<string, string> = {}): string {
  const lines: string[] = [];
  for (const input of workflow.inputs) {
    if (fixed[input.name] !== undefined) {
      lines.push(`    ${input.name}: { value: ${fixed[input.name]} },`);
      continue;
    }
    const kind = fieldKind(input);
    const label = humanise(input.name) + (input.required ? "" : " (optional)");
    const parts = [`label: ${q(label)}`];
    if (kind !== "text") parts.push(`kind: ${q(kind)}`);
    if (kind === "select") parts.push(`options: [${input.options.map((o) => `{ label: ${q(o)}, value: ${q(o)} }`).join(", ")}]`);
    if (input.description) parts.push(`help: ${q(input.description)}`);
    lines.push(`    ${input.name}: { ${parts.join(", ")} },`);
  }
  return lines.join("\n");
}

export function formJsx(workflow: WorkflowRef, opts: { fixed?: Record<string, string>; columns?: 1 | 2 } = {}): string {
  const key = workflow.key ?? "workflow";
  return [
    `<WorkflowForm`,
    `  workflow={workflows.${key}}`,
    `  fields={{`,
    formFields(workflow, opts.fixed),
    `  }}`,
    `  columns={${opts.columns ?? 1}}`,
    `  submitLabel=${q("Save")}`,
    `  successMessage=${q(`${workflow.name} — done.`)}`,
    `/>`,
  ].join("\n");
}

export function formImports(): Op[] {
  return [
    { op: "addImport", source: "@/sdk/client", names: ["WorkflowForm"] },
    { op: "addImport", source: "@/sdk", names: ["workflows"] },
  ];
}

export function workflowButtonJsx(workflow: WorkflowRef, opts: { label?: string; input?: Record<string, string>; confirm?: string } = {}): string {
  const key = workflow.key ?? "workflow";
  const input = Object.entries(opts.input ?? {}).map(([k, v]) => `${k}: ${v}`).join(", ");
  const confirm = opts.confirm ? ` confirm=${q(opts.confirm)}` : "";
  return `<WorkflowButton workflow={workflows.${key}} input={{ ${input} }}${confirm}>${opts.label ?? workflow.name}</WorkflowButton>`;
}

export function workflowButtonImports(): Op[] {
  return [
    { op: "addImport", source: "@/sdk/client", names: ["WorkflowButton"] },
    { op: "addImport", source: "@/sdk", names: ["workflows"] },
  ];
}

/** `href(pages.key)` for a page without parameters, its route otherwise (the id must come from data). */
export function pageHref(page: PageRef): { expr: string; needsParams: boolean } {
  if (page.params.length && page.key) {
    return { expr: `href(pages.${page.key}, { ${page.params.map((p) => `${p}: ""`).join(", ")} })`, needsParams: true };
  }
  if (page.key) return { expr: `href(pages.${page.key})`, needsParams: false };
  return { expr: q(page.route), needsParams: page.params.length > 0 };
}

export function pageButtonJsx(page: PageRef, label: string, variant?: string): string {
  const { expr } = pageHref(page);
  const v = variant && variant !== "default" ? ` variant=${q(variant)}` : "";
  return `<Button asChild${v}>\n  <Link href={${expr}}>${label}</Link>\n</Button>`;
}

export function pageButtonImports(): Op[] {
  return [
    { op: "addImport", source: "@/components/ui/button", names: ["Button"] },
    { op: "addImport", source: "next/link", names: ["default:Link"] },
    { op: "addImport", source: "@/sdk", names: ["pages", "href"] },
  ];
}

export function tableJsx(dataKey: string, columns: { name: string; label: string }[], rowVar = "row"): string {
  const head = columns.map((c) => `        <TableHead>${c.label}</TableHead>`).join("\n");
  const cells = columns.map((c) => `            <TableCell>{String(${rowVar}.${c.name} ?? "")}</TableCell>`).join("\n");
  return [
    `<Table>`,
    `  <TableHeader>`,
    `    <TableRow>`,
    head,
    `    </TableRow>`,
    `  </TableHeader>`,
    `  <TableBody>`,
    `    {${dataKey}.length === 0 ? (`,
    `      <TableRow>`,
    `        <TableCell colSpan={${columns.length}} className="py-8 text-center text-sm text-muted-foreground">Nothing here yet.</TableCell>`,
    `      </TableRow>`,
    `    ) : (`,
    `      ${dataKey}.map((${rowVar}) => (`,
    `        <TableRow key={String(${rowVar}.id)}>`,
    cells,
    `        </TableRow>`,
    `      ))`,
    `    )}`,
    `  </TableBody>`,
    `</Table>`,
  ].join("\n");
}

export function tableImports(): Op[] {
  return [{ op: "addImport", source: "@/components/ui/table",
            names: ["Table", "TableHeader", "TableBody", "TableRow", "TableHead", "TableCell"] }];
}

/** Columns a table can show for an entity: its fields minus the managed ones. */
export function entityColumns(entity: EntityRef): { name: string; label: string }[] {
  const managed = new Set(["id", "createdAt", "updatedAt", "deletedAt", "created_at", "updated_at", "deleted_at", "passwordHash"]);
  return entity.fields.filter((f) => !managed.has(f.name)).map((f) => ({ name: f.name, label: f.label || humanise(f.name) }));
}

/** The text a button shows, for rewriting it into another kind of button. */
export function buttonLabel(node: ModelNode): string {
  return (node.textEditable && node.text) ? node.text : "Button";
}

/** The ops that turn the selected button into one that opens a page / runs a workflow / does nothing. */
export function buttonActionOps(node: ModelNode, choice:
  | { kind: "none" }
  | { kind: "page"; page: PageRef }
  | { kind: "workflow"; workflow: WorkflowRef }
  | { kind: "dialog" }
  | { kind: "message"; text: string }): Op[] {
  const label = buttonLabel(node);
  const variant = node.props.find((p) => p.name === "variant" && p.kind === "string")?.value ?? undefined;
  const v = variant && variant !== "default" ? ` variant=${q(variant)}` : "";
  if (choice.kind === "dialog") {
    return [
      { op: "addImport", source: "@/components/ui/button", names: ["Button"] },
      { op: "addImport", source: "@/components/ui/dialog", names: ["Dialog", "DialogTrigger", "DialogContent", "DialogHeader", "DialogTitle", "DialogDescription"] },
      { op: "replaceNode", id: node.id, jsx: `<Dialog>\n  <DialogTrigger asChild>\n    <Button${v}>${label}</Button>\n  </DialogTrigger>\n  <DialogContent>\n    <DialogHeader>\n      <DialogTitle>${label}</DialogTitle>\n      <DialogDescription>What this dialog is for.</DialogDescription>\n    </DialogHeader>\n  </DialogContent>\n</Dialog>` },
    ];
  }
  if (choice.kind === "message") {
    return [
      { op: "addImport", source: "@/components/ui/button", names: ["Button"] },
      { op: "addImport", source: "sonner", names: ["toast"] },
      { op: "replaceNode", id: node.id, jsx: `<Button${v} onClick={() => toast(${q(choice.text)})}>${label}</Button>` },
    ];
  }
  if (choice.kind === "page") {
    return [...pageButtonImports(), { op: "replaceNode", id: node.id, jsx: pageButtonJsx(choice.page, label, variant) }];
  }
  if (choice.kind === "workflow") {
    return [...workflowButtonImports(),
            { op: "replaceNode", id: node.id, jsx: workflowButtonJsx(choice.workflow, { label }) }];
  }
  return [{ op: "addImport", source: "@/components/ui/button", names: ["Button"] },
          { op: "replaceNode", id: node.id, jsx: `<Button${v}>${label}</Button>` }];
}

/** What a button currently does, read from its shape. */
export function buttonAction(node: ModelNode, model: { nodes: Record<string, ModelNode> }): { kind: "none" | "page" | "workflow" | "dialog" | "message" | "custom"; detail: string } {
  const onClick = node.props.find((p) => p.name === "onClick")?.value ?? "";
  const msg = /^\(\)\s*=>\s*toast\((".*")\)$/.exec(onClick.trim());
  if (msg) return { kind: "message", detail: JSON.parse(msg[1]) };
  const parent = node.parent ? model.nodes[node.parent] : null;
  if (parent?.type === "DialogTrigger") return { kind: "dialog", detail: "Opens a dialog" };
  if (node.type === "WorkflowButton") {
    const wf = node.props.find((p) => p.name === "workflow")?.value ?? "";
    return { kind: "workflow", detail: wf.replace(/^workflows\./, "") };
  }
  const link = node.children.map((c) => model.nodes[c]).find((c) => c && (c.type === "Link" || c.type === "a"));
  const href = (link ?? node).props.find((p) => p.name === "href")?.value;
  if (href) return { kind: "page", detail: href };
  if (node.props.some((p) => p.name === "onClick")) return { kind: "custom", detail: "Runs code on this page" };
  if (node.props.some((p) => p.name === "type" && p.value === "submit")) return { kind: "custom", detail: "Sends the form it is in" };
  return { kind: "none", detail: "Nothing yet" };
}


// ---------------------------------------------------------------------------
// Charts — a widget the page reads in load.ts and draws in view.tsx
// ---------------------------------------------------------------------------

/** How the View reaches a key `load()` returns, and the op that makes it so. */
export function dataAccess(model: PageModel, key: string): { expr: string; ops: Op[] } {
  const p = model.viewParam;
  if (p && p.kind === "identifier") return { expr: `${p.name}.${key}`, ops: [] };
  return { expr: key, ops: [{ op: "ensureProp", name: key }] };
}

/** Everything that puts a widget on the page: the handle read in load, the view's access to it, the card. */
export function widgetOps(model: PageModel, widget: WidgetRef, opts: { parentId?: string; index?: number | null; afterId?: string } = {}): Op[] {
  const key = widget.key ?? "widget";
  const { expr, ops } = dataAccess(model, key);
  const jsx = `<WidgetView widget={widgets.${key}} data={${expr}} />`;
  const insert: Op = opts.afterId ? { op: "insert", afterId: opts.afterId, jsx } : { op: "insert", parentId: opts.parentId, index: opts.index ?? null, jsx };
  return [
    { op: "addImport", file: "load", source: "@/sdk/server", names: ["runWidget"] },
    { op: "addImport", file: "load", source: "@/sdk", names: ["widgets"] },
    { op: "addReturnKey", file: "load", key, expr: `await runWidget(widgets.${key})` },
    { op: "addImport", source: "@/sdk/client", names: ["WidgetView"] },
    { op: "addImport", source: "@/sdk", names: ["widgets"] },
    ...ops,
    insert,
  ];
}

/** The widget a `WidgetView` node draws, from its `widget={widgets.key}` prop. */
export function widgetOfNode(node: ModelNode, widgets: WidgetRef[] | undefined): WidgetRef | null {
  const prop = node.props.find((p) => p.name === "widget");
  const m = prop?.value ? /^widgets\.(\w+)$/.exec(prop.value.trim()) : null;
  if (!m) return null;
  return widgets?.find((w) => w.key === m[1]) ?? null;
}

/** The ops that take a widget off the page: its card and the key load returned. */
export function widgetRemovalOps(node: ModelNode, widget: WidgetRef | null): Op[] {
  const ops: Op[] = [{ op: "remove", ids: [node.id] }];
  if (widget?.key) ops.push({ op: "removeReturnKey", file: "load", key: widget.key });
  return ops;
}

/** Plain words for a measure: "How many records", "Total amount", "Average age". */
export function measureLabel(m: { aggregation: string; field?: string }, entityName: string): string {
  const f = m.field ? humanise(m.field).toLowerCase() : "";
  switch (m.aggregation) {
    case "count": return `How many ${entityName.toLowerCase()} records`;
    case "count_distinct": return `Different ${f}s`;
    case "sum": return `Total ${f}`;
    case "avg": return `Average ${f}`;
    case "min": return `Lowest ${f}`;
    case "max": return `Highest ${f}`;
  }
  return m.aggregation;
}

export const MARKS: { value: WidgetRef["chart"] extends infer C ? (C extends { mark: infer M } ? M : never) : never; label: string; needs: "one" | "two" | "any" }[] = [
  { value: "bar", label: "Bars", needs: "any" },
  { value: "line", label: "Line", needs: "any" },
  { value: "area", label: "Area", needs: "any" },
  { value: "pie", label: "Pie", needs: "one" },
  { value: "donut", label: "Donut", needs: "one" },
  { value: "funnel", label: "Funnel", needs: "one" },
  { value: "radar", label: "Radar", needs: "any" },
  { value: "treemap", label: "Treemap", needs: "one" },
];

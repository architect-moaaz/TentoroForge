import { z } from "zod";
import { starterRegistry } from "../registry/src/starter.ts";
import { PageV2 } from "@tentoroforge/schema";
import { CartPanelProps } from "./src/components/CartPanel/CartPanel.schema.ts";
import { ChartProps } from "./src/components/Chart/Chart.schema.ts";
import { DataGridProps } from "./src/components/DataGrid/DataGrid.schema.ts";
import { EditableLineGridProps } from "./src/components/EditableLineGrid/EditableLineGrid.schema.ts";
import { SparklineProps } from "./src/components/Sparkline/Sparkline.schema.ts";
import { TableProps, TableSortableProps } from "./src/components/Table/Table.schema.ts";
import { TimelineProps } from "./src/components/Timeline/Timeline.schema.ts";

const NUMERIC_LITERAL = /^-?\d+(?:\.\d+)?$/;
function isNumericDomain(d: any) {
  if (d?.type === "number") return true;
  return d?.type === "enum" && Array.isArray(d.options) && d.options.length > 0 &&
    d.options.every((o: any) => typeof o === "number" || (typeof o === "string" && NUMERIC_LITERAL.test(o)));
}
function isUrl(d: any) { return d?.control === "image" && d?.imageShape === "url"; }
function normalizeSeed(d: any, v: unknown) {
  if (v === undefined) return undefined;
  if (v === null) return undefined;
  if (isNumericDomain(d) && typeof v === "string" && NUMERIC_LITERAL.test(v.trim())) return Number(v);
  if (isUrl(d) && v === "") return undefined;
  return v;
}
function defaultPropsFor(name: string) {
  const e = (starterRegistry as any)[name];
  if (!e) return {};
  return Object.fromEntries(Object.entries(e.props as any)
    .map(([n, d]: any) => [n, normalizeSeed(d, d.default)])
    .filter(([, v]) => v !== undefined));
}

// unwrap a zod schema to its ZodObject shape
function shapeOf(s: any): Record<string, any> | null {
  let cur = s;
  for (let i = 0; i < 12 && cur; i++) {
    if (cur._def?.typeName === "ZodObject") return cur.shape;
    if (cur._def?.innerType) { cur = cur._def.innerType; continue; }
    if (cur._def?.schema) { cur = cur._def.schema; continue; }
    if (cur._def?.type) { cur = cur._def.type; continue; }
    return null;
  }
  return null;
}
function isOptional(f: any) { try { return f.isOptional(); } catch { return false; } }
function hasDefault(f: any) {
  let cur = f;
  for (let i = 0; i < 8 && cur; i++) {
    if (cur._def?.typeName === "ZodDefault") return true;
    cur = cur._def?.innerType ?? cur._def?.schema ?? null;
  }
  return false;
}
function typeName(f: any): string {
  const parts: string[] = [];
  let cur = f;
  for (let i = 0; i < 8 && cur; i++) {
    const tn = cur._def?.typeName;
    if (!tn) break;
    parts.push(tn.replace("Zod", ""));
    if (tn === "ZodEnum") { parts.push("[" + cur._def.values.join("|") + "]"); break; }
    cur = cur._def?.innerType ?? cur._def?.schema ?? cur._def?.type ?? null;
    if (!cur || !cur._def) break;
  }
  return parts.join("<");
}

const COMPONENT_SCHEMAS: Record<string, any> = {
  CartPanel: CartPanelProps, Chart: ChartProps, DataGrid: DataGridProps,
  EditableLineGrid: EditableLineGridProps, Sparkline: SparklineProps,
  Table: TableProps, TableSortable: TableSortableProps, Timeline: TimelineProps,
};
const BUILTINS = ["Repeat", "Conditional", "DataBoundary", "Slot"];
const NAMES = ["CartPanel","Chart","Conditional","DataBoundary","DataGrid","EditableLineGrid","Repeat","Slot","Sparkline","Table","TableSortable","Timeline"];

function pageWith(node: any) {
  return { schemaVersion: "2", id: "home", route: "/", meta: {}, dataSources: [],
    root: { id: "root", type: "Container", props: {}, children: [node] } };
}
function buildDropped(name: string) {
  const isContainer = (starterRegistry as any)[name]?.slots?.type !== "leaf";
  const props = defaultPropsFor(name);
  return { id: `${name.toLowerCase()}-abc123`, type: name, props,
    ...(isContainer ? { children: [] as any[] } : {}) };
}

for (const name of NAMES) {
  const entry = (starterRegistry as any)[name];
  console.log("\n============================== " + name);
  if (!entry) { console.log("  NO REGISTRY ENTRY"); continue; }
  const editorProps = Object.keys(entry.props ?? {});
  console.log("  slots:", JSON.stringify(entry.slots));
  console.log("  editor props (" + editorProps.length + "):");
  for (const [pn, d] of Object.entries(entry.props ?? {}) as any) {
    console.log(`    - ${pn}: type=${d.type} control=${d.control} default=${JSON.stringify(d.default)}${d.options ? " options=" + JSON.stringify(d.options) : ""}`);
  }
  const cs = COMPONENT_SCHEMAS[name];
  if (cs) {
    const shape = shapeOf(cs);
    if (shape) {
      const schemaKeys = Object.keys(shape);
      console.log("  component schema props (" + schemaKeys.length + "):");
      for (const k of schemaKeys) {
        const f = shape[k];
        const req = !isOptional(f) && !hasDefault(f);
        console.log(`    - ${k}: ${typeName(f)}${req ? "  [REQUIRED]" : ""}${hasDefault(f) ? "  [zod-default]" : ""}${editorProps.includes(k) ? "" : "   <<< NOT IN EDITOR"}`);
      }
      const dead = editorProps.filter((p) => !schemaKeys.includes(p));
      console.log("  DEAD editor props (not in schema):", JSON.stringify(dead));
      const missing = schemaKeys.filter((k) => !editorProps.includes(k) && k !== "className" && k !== "style");
      console.log("  MISSING from editor:", JSON.stringify(missing));
      // enum truncation
      for (const k of schemaKeys) {
        const d: any = (entry.props ?? {})[k];
        if (!d) continue;
        let cur = shape[k];
        for (let i = 0; i < 8 && cur?._def; i++) {
          if (cur._def.typeName === "ZodEnum") break;
          cur = cur._def.innerType ?? cur._def.schema ?? cur._def.type ?? null;
        }
        if (cur?._def?.typeName === "ZodEnum" && Array.isArray(d.options)) {
          const sv = cur._def.values;
          const miss = sv.filter((v: string) => !d.options.includes(v));
          const extra = d.options.filter((v: string) => !sv.includes(v));
          if (miss.length || extra.length) console.log(`  ENUM MISMATCH ${k}: schema=${JSON.stringify(sv)} editor=${JSON.stringify(d.options)} missingInEditor=${JSON.stringify(miss)} extraInEditor=${JSON.stringify(extra)}`);
        }
      }
      // parse defaults against component schema
      const props = defaultPropsFor(name);
      const r = cs.safeParse(props);
      console.log("  component-schema parse of registry defaults:", r.success ? "PASS" : "FAIL " + JSON.stringify(r.error.issues.map((i: any) => i.path.join(".") + ": " + i.message)));
    } else {
      console.log("  (could not unwrap component schema shape)");
    }
  } else {
    console.log("  (builtin — no library schema)");
  }
  const node = buildDropped(name);
  console.log("  dropped node:", JSON.stringify(node));
  const p = PageV2.safeParse(pageWith(node));
  console.log("  PageV2 (fresh drop):", p.success ? "PASS" : "FAIL");
  if (!p.success) {
    const rel = p.error.issues.filter((i: any) => i.path.join(".").includes("children.0") || i.path.length < 3);
    for (const i of (rel.length ? rel : p.error.issues).slice(0, 8)) console.log("      " + i.path.join(".") + ": " + i.message);
  }
}

import { starterRegistry } from "../registry/src/starter.ts";
import { NodeV2, PageV2 } from "../schema/src/page.ts";
import { Node as NodeV1 } from "../schema/src/nodes/index.ts";

const NUMERIC_LITERAL = /^-?\d+(?:\.\d+)?$/;
function isNumericDomain(d: any): boolean {
  if (d?.type === "number") return true;
  return d?.type === "enum" && Array.isArray(d.options) && d.options.length > 0 &&
    d.options.every((o: unknown) => typeof o === "number" || (typeof o === "string" && NUMERIC_LITERAL.test(o)));
}
function isUrlDescriptor(d: any) { return d?.control === "image" && d?.imageShape === "url"; }
function normalizeSeed(d: any, value: unknown): unknown {
  if (value === undefined) return undefined;
  if (value === null) return undefined;
  if (isNumericDomain(d) && typeof value === "string" && NUMERIC_LITERAL.test(value.trim())) return Number(value);
  if (isUrlDescriptor(d) && value === "") return undefined;
  return value;
}
function defaultPropsFor(name: string): Record<string, unknown> {
  const e: any = (starterRegistry as any)[name];
  if (!e) return {};
  return Object.fromEntries(Object.entries(e.props as Record<string, any>)
    .map(([n, d]) => [n, normalizeSeed(d, (d as any).default)] as [string, unknown])
    .filter(([, v]) => v !== undefined));
}
function buildDroppedNode(name: string) {
  const e: any = (starterRegistry as any)[name];
  const isContainer = e?.slots?.type !== "leaf";
  const id = `${name.toLowerCase()}-zz1234`;
  const props = defaultPropsFor(name);
  if ("name" in (e?.props ?? {}) && !props.name) props.name = id.replace(/-/g, "_");
  const style = { width: "420px", minHeight: "200px" };
  return { id, type: name, props, ...(isContainer ? { children: [] as any[] } : {}), style };
}

const TARGETS = ["CartPanel","Chart","Conditional","DataBoundary","DataGrid","EditableLineGrid","Repeat","Slot","Table","TableSortable","Timeline"];

// component schemas
const compSchemas: Record<string, any> = {};
for (const [name, file] of Object.entries({
  CartPanel: "CartPanel/CartPanel.schema.ts",
  Chart: "Chart/Chart.schema.ts",
  DataGrid: "DataGrid/DataGrid.schema.ts",
  EditableLineGrid: "EditableLineGrid/EditableLineGrid.schema.ts",
  Table: "Table/Table.schema.ts",
  Timeline: "Timeline/Timeline.schema.ts",
})) {
  try {
    const m: any = await import(`./src/components/${file}`);
    for (const k of Object.keys(m)) {
      if (m[k]?._def && /Props|Schema/.test(k)) { compSchemas[name] = compSchemas[name] ?? {}; compSchemas[name][k] = m[k]; }
    }
  } catch (e: any) { compSchemas[name] = { __err: String(e.message).slice(0, 200) }; }
}

function shapeKeys(s: any): string[] | null {
  let cur = s;
  for (let i = 0; i < 12 && cur; i++) {
    if (cur.shape) return Object.keys(cur.shape);
    if (cur._def?.shape) return Object.keys(typeof cur._def.shape === "function" ? cur._def.shape() : cur._def.shape);
    cur = cur._def?.innerType ?? cur._def?.schema ?? cur._def?.type ?? null;
  }
  return null;
}
function describe(s: any, depth = 0): string {
  if (!s?._def) return "?";
  const t = s._def.typeName;
  switch (t) {
    case "ZodOptional": return describe(s._def.innerType, depth) + "?";
    case "ZodNullable": return describe(s._def.innerType, depth) + "|null";
    case "ZodDefault": return describe(s._def.innerType, depth) + `=${JSON.stringify(s._def.defaultValue())}`;
    case "ZodEffects": return "fx(" + describe(s._def.schema, depth) + ")";
    case "ZodString": { const chk = (s._def.checks ?? []).map((c: any) => c.kind).join(","); return "string" + (chk ? `[${chk}]` : ""); }
    case "ZodNumber": return "number";
    case "ZodBoolean": return "boolean";
    case "ZodEnum": return "enum(" + s._def.values.join("|") + ")";
    case "ZodLiteral": return `lit(${JSON.stringify(s._def.value)})`;
    case "ZodArray": return "array<" + describe(s._def.type, depth + 1) + ">" + ((s._def.minLength) ? `.min(${s._def.minLength.value})` : "");
    case "ZodUnion": return "union(" + s._def.options.map((o: any) => describe(o, depth + 1)).join(" | ") + ")";
    case "ZodObject": return depth > 1 ? "object" : "object{" + Object.keys(s._def.shape()).join(",") + "}";
    case "ZodRecord": return "record";
    case "ZodAny": return "any"; case "ZodUnknown": return "unknown";
    default: return t;
  }
}

const out: any[] = [];
for (const name of TARGETS) {
  const entry: any = (starterRegistry as any)[name];
  const node = buildDroppedNode(name);
  const r: any = { name, slots: entry?.slots, registryProps: {}, drop: node };
  for (const [k, d] of Object.entries(entry?.props ?? {}) as any) {
    r.registryProps[k] = { type: d.type, control: d.control, default: d.default, options: d.options, group: d.group };
  }
  // component schema keys
  const cs = compSchemas[name];
  if (cs && !cs.__err) {
    const key = Object.keys(cs)[0];
    const sk = shapeKeys(cs[key]);
    r.componentSchemaName = key;
    r.componentProps = {};
    if (sk) {
      const shp = (cs[key].shape ?? cs[key]._def.shape());
      for (const k of sk) r.componentProps[k] = describe(shp[k]);
    }
  } else if (cs?.__err) r.componentSchemaErr = cs.__err;

  // node-schema parse of the dropped node
  const nv2 = NodeV2.safeParse(node);
  r.nodeV2 = nv2.success ? "PASS" : nv2.error.issues.map((i: any) => `${i.path.join(".")}: ${i.message}`).slice(0, 8);
  const page = { schemaVersion: "2", id: "zzpage", route: "/zz",
    root: { id: "root-zz", type: "Stack", props: {}, children: [node] } };
  const pv2 = PageV2.safeParse(page);
  r.pageV2 = pv2.success ? "PASS" : pv2.error.issues.map((i: any) => `${i.path.join(".")}: ${i.message}`).slice(0, 8);
  const nv1 = NodeV1.safeParse(node);
  r.nodeV1 = nv1.success ? "PASS" : "FAIL";
  out.push(r);
}
console.log(JSON.stringify(out, null, 2));

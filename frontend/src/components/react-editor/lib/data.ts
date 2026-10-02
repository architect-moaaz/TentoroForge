/**
 * The page's data, in a person's words (DATA-001): where a value can come
 * from ("the list of records", "the record this page shows", "how many
 * records"), which part of it ("full name"), and an example of it. Bindings
 * are structured — a source and a field — never typed expressions; the
 * expression is written from the choice.
 */
import type { EntityRef, LoadShape, ModelNode, ObjectEntry, PageDoc, PageModel, WidgetDimension, WidgetMeasure, WidgetRange } from "../types";
import { humanise } from "./templates";

export interface DataSource {
  id: string;
  /** The expression that reaches it in the view: `props.records`, `records`, `row`. */
  expr: string;
  label: string;
  shape: LoadShape | { kind: "row"; entity: string | null };
  entity: EntityRef | null;
  /** True for the row of the repeated element the selection sits in. */
  row?: boolean;
  /** Where the value comes from, in a sentence: read on the server, an API, the address… */
  via?: string;
  /** For a row: the id of the list it is one item of. */
  listId?: string;
}

export interface FieldChoice { name: string; label: string; type: string; sample: unknown }

function plural(name: string): string {
  const n = name.toLowerCase();
  return n.endsWith("s") ? n : n.endsWith("y") ? n.slice(0, -1) + "ies" : n + "s";
}

export function entityByName(doc: PageDoc, name: string | null | undefined): EntityRef | null {
  return name ? doc.entities.find((e) => e.name === name || e.typeName === name) ?? null : null;
}

function accessFor(model: PageModel, key: string): string {
  const p = model.viewParam;
  return p && p.kind === "identifier" ? `${p.name}.${key}` : key;
}

/** Everything the page loads, as a place a value can come from. */
/** Where a loaded value comes from, for a person: the server's database, a
 *  widget's query, the signed-in account, the page's address, an API, or the
 *  page itself. */
export function viaLabel(shape: LoadShape | { kind: "row"; entity: string | null }, entity: EntityRef | null): string | undefined {
  const via = "via" in shape ? shape.via : undefined;
  if (!via) return undefined;
  // A count has no entity of its own on the shape; the read names it.
  const name = entity?.name ?? (via.how === "server" ? via.entity : null);
  const what = name ? plural(name).toLowerCase() : "the database";
  switch (via.how) {
    case "server": return via.call === "listPage" ? `Read on the server from ${what}, a page at a time`
      : via.call === "record" ? `Read on the server from ${what}, the one the page is about`
      : via.call === "count" || via.call === "total" ? `Counted on the server across ${what}`
      : `Read on the server from ${what}`;
    case "widget": return "Worked out on the server by this widget's query";
    case "user": return "The account of the person signed in";
    case "address": return "Taken from the page's address (URL)";
    case "api": return via.url ? `Fetched from ${via.url}` : "Fetched from an API";
    case "fixed": return "A fixed value written into the page";
  }
}

export function pageSources(doc: PageDoc): DataSource[] {
  const model = doc.model;
  if (!model) return [];
  const shapes = model.loadShapes ?? {};
  const out: DataSource[] = [];
  for (const key of model.loadKeys) {
    if (key.startsWith("...")) continue;
    const shape: LoadShape = shapes[key] ?? { kind: "unknown" };
    const entity = "entity" in shape ? entityByName(doc, shape.entity) : null;
    let label = humanise(key);
    if (shape.kind === "rows" || shape.kind === "page") label = entity ? `The list of ${plural(entity.name)}` : `The list “${humanise(key)}”`;
    else if (shape.kind === "record") label = entity ? `The ${entity.name.toLowerCase()} this page shows` : `The record “${humanise(key)}”`;
    else if (shape.kind === "widget") label = doc.widgets?.find((w) => w.key === shape.widget)?.label ?? humanise(key);
    else if (shape.kind === "number") label = `${humanise(key)} (a number)`;
    else if (shape.kind === "user") label = "The signed-in person";
    out.push({ id: key, expr: accessFor(model, key), label, shape, entity, via: viaLabel(shape, entity) });
  }
  return out;
}

/** The row the element sits in, when it is inside a repeated list. */
export function rowContext(doc: PageDoc, nodeId: string): DataSource | null {
  const model = doc.model;
  if (!model) return null;
  let cur: ModelNode | undefined = model.nodes[nodeId];
  while (cur) {
    if (cur.repeat?.variable) {
      const src = cur.repeat.source;
      const sources = pageSources(doc);
      const match = sources.find((s) => src === s.expr || src === `${s.expr}.rows` || src === s.id || src === `${s.id}.rows`);
      const entity = match?.entity ?? null;
      const rowsOf = match?.shape.kind === "widget" ? null : entity;
      return { id: `row:${cur.repeat.variable}`, expr: cur.repeat.variable, row: true, listId: match?.id,
               label: rowsOf ? `Each ${rowsOf.name.toLowerCase()} in the list` : `Each item of ${humanise(src.replace(/^props\./, ""))}`,
               shape: { kind: "row", entity: rowsOf?.name ?? null }, entity: rowsOf };
    }
    cur = cur.parent ? model.nodes[cur.parent] : undefined;
  }
  return null;
}

/** The parts a source has: an entity's fields with an example, or the whole value. */
export function fieldChoices(doc: PageDoc, source: DataSource): FieldChoice[] {
  const entity = source.entity;
  const shape = source.shape;
  if (entity && (shape.kind === "record" || shape.kind === "row")) {
    const sample = doc.samples?.[entity.name]?.[0] ?? {};
    return entity.fields.filter((f) => !/^(id|passwordHash)$/.test(f.name)).map((f) => ({ name: f.name, label: f.label || humanise(f.name), type: f.type, sample: sample[f.name] }));
  }
  if (shape.kind === "rows" || shape.kind === "page" || shape.kind === "list") {
    return [{ name: "length", label: "How many there are", type: "number", sample: doc.samples?.[entity?.name ?? ""]?.length ?? 8 }];
  }
  if (shape.kind === "widget") return [{ name: "value", label: "Its number", type: "number", sample: 8 }];
  if (shape.kind === "user") return [{ name: "name", label: "Name", type: "string", sample: "Sample Admin" }, { name: "email", label: "Email", type: "string", sample: "admin@example.com" }, { name: "role", label: "Role", type: "string", sample: "Admin" }];
  return [{ name: "", label: "Its value", type: shape.kind === "number" ? "number" : "string", sample: shape.kind === "number" ? 42 : "…" }];
}

/** A binding as an expression: `record.fullName`, `props.records.length`, `row.age`. */
export function bindingExpr(source: DataSource, field: string, opts: { text?: boolean; type?: string } = {}): string {
  const base = field ? `${source.expr}.${field}` : source.expr;
  const isRecord = source.shape.kind === "record";
  if (opts.text) {
    // A record may be null on this page; a number must become text. Keep strings bare.
    if (isRecord) return `${source.expr}?.${field} ?? ""`;
    if (opts.type && !/string|text|enum/.test(opts.type)) return `String(${base} ?? "")`;
    return base;
  }
  return base;
}

/** What an element shows now, read from its expression. */
export function readBinding(doc: PageDoc, node: ModelNode): { kind: "text" } | { kind: "field"; source: DataSource; field: string } | { kind: "custom"; code: string } {
  const code = node.exprOnly?.trim();
  if (!code) return { kind: "text" };
  const m = /^(?:String\()?\s*([A-Za-z_$][\w$]*)(?:\??\.([\w$]+))?(?:\??\.([\w$]+))?\s*(?:\?\?\s*"")?\)?$/.exec(code);
  if (m) {
    const [, head, a, b] = m;
    const row = rowContext(doc, node.id);
    const sources = pageSources(doc);
    const param = doc.model?.viewParam;
    if (row && head === row.expr) return { kind: "field", source: row, field: a ?? "" };
    if (param && param.kind === "identifier" && head === param.name && a) {
      const src = sources.find((s) => s.id === a);
      if (src) return { kind: "field", source: src, field: b ?? "" };
    }
    const src = sources.find((s) => s.expr === head || s.id === head);
    if (src) return { kind: "field", source: src, field: a ?? "" };
  }
  return { kind: "custom", code };
}

/** An example of what a binding will show. */
export function sampleOf(doc: PageDoc, source: DataSource, field: string): string {
  const choice = fieldChoices(doc, source).find((f) => f.name === field);
  const v = choice?.sample;
  if (v === undefined || v === null) return "";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return new Date(v).toLocaleDateString();
  return String(v);
}

// ---------------------------------------------------------------------------
// Object props — a form's fields, a button's input — as the person sees them
// ---------------------------------------------------------------------------

export function entry(entries: ObjectEntry[] | undefined, key: string): ObjectEntry | undefined {
  return entries?.find((e) => e.key === key);
}

export function entryString(entries: ObjectEntry[] | undefined, key: string): string {
  const e = entry(entries, key);
  return e && e.kind === "string" ? String(e.value ?? "") : "";
}

/** Set a string entry (removing it when empty), keeping everything else. */
export function withString(entries: ObjectEntry[], key: string, value: string): ObjectEntry[] {
  const rest = entries.filter((e) => e.key !== key);
  return value ? [...rest, { key, kind: "string", value, code: JSON.stringify(value) }] : rest;
}

export function withExpr(entries: ObjectEntry[], key: string, code: string | null): ObjectEntry[] {
  const rest = entries.filter((e) => e.key !== key);
  return code ? [...rest, { key, kind: "expr", code }] : rest;
}

// ---------------------------------------------------------------------------
// Sample queries — a chart preview before it exists
// ---------------------------------------------------------------------------

export function bucketOf(v: unknown, bucket: WidgetDimension["bucket"]): string {
  const d = new Date(String(v));
  if (isNaN(d.getTime())) return String(v ?? "");
  const y = d.getUTCFullYear(), mo = d.getUTCMonth() + 1;
  if (bucket === "year") return String(y);
  if (bucket === "quarter") return `${y}-Q${Math.floor((mo - 1) / 3) + 1}`;
  if (bucket === "month") return `${y}-${String(mo).padStart(2, "0")}`;
  if (bucket === "week") return `${y}-W${String(Math.ceil(((d.getTime() - Date.UTC(y, 0, 1)) / 86400000 + 1) / 7)).padStart(2, "0")}`;
  return d.toISOString().slice(0, 10);
}

export interface SampleQuery {
  measures: WidgetMeasure[];
  dimensions: WidgetDimension[];
  filter?: Record<string, string | string[] | number | boolean>;
  sort?: { by: string; order?: "asc" | "desc" } | null;
  limit?: number | null;
}

/** What a band is called on the axis when it has no label — as the Data Engine names it. */
export function bandLabel(r: WidgetRange): string {
  if (r.label) return r.label;
  if (r.from !== undefined && r.to !== undefined) return `${r.from}–${r.to}`;
  return r.from !== undefined ? `${r.from}+` : `under ${r.to}`;
}

/** The band a number falls in (from ≤ v < to), or undefined when it is in none. */
export function bandOf(v: unknown, ranges: WidgetRange[]): string | undefined {
  const n = Number(v);
  if (v === null || v === undefined || v === "" || Number.isNaN(n)) return undefined;
  const hit = ranges.find((r) => (r.from === undefined || n >= r.from) && (r.to === undefined || n < r.to));
  return hit ? bandLabel(hit) : undefined;
}

/** Measures by dimensions over sample rows — the same rules the canvas's sample server applies. */
export function sampleQuery(rows: Record<string, unknown>[], q: SampleQuery): Record<string, string | number | null>[] {
  let src = rows;
  for (const [k, v] of Object.entries(q.filter ?? {})) {
    const want = Array.isArray(v) ? v.map(String) : [String(v)];
    src = src.filter((r) => want.includes(String(r[k])));
  }
  const groups = new Map<string, { vals: unknown[]; rows: Record<string, unknown>[] }>();
  for (const r of src) {
    const vals = q.dimensions.map((d) => (d.ranges?.length ? bandOf(r[d.field], d.ranges) : d.bucket ? bucketOf(r[d.field], d.bucket) : r[d.field] ?? null));
    if (vals.some((v) => v === undefined)) continue;
    const k = JSON.stringify(vals);
    if (!groups.has(k)) groups.set(k, { vals, rows: [] });
    groups.get(k)!.rows.push(r);
  }
  const agg = (m: WidgetMeasure, grp: Record<string, unknown>[]): number | null => {
    const nums = grp.map((r) => Number(r[m.field ?? ""])).filter((n) => !isNaN(n));
    switch (m.aggregation) {
      case "count": return grp.length;
      case "count_distinct": return new Set(grp.map((r) => String(r[m.field ?? ""]))).size;
      case "sum": return nums.reduce((a, b) => a + b, 0);
      case "avg": return nums.length ? Math.round((nums.reduce((a, b) => a + b, 0) / nums.length) * 100) / 100 : null;
      case "min": return nums.length ? Math.min(...nums) : null;
      case "max": return nums.length ? Math.max(...nums) : null;
    }
    return grp.length;
  };
  let out = [...groups.values()].map(({ vals, rows: grp }) => {
    const row: Record<string, string | number | null> = {};
    q.dimensions.forEach((d, i) => { row[d.field] = vals[i] as string | number | null; });
    for (const m of q.measures) row[m.key] = agg(m, grp);
    return row;
  });
  const bucketed = q.dimensions.find((d) => d.bucket || d.ranges?.length);
  const by = q.sort?.by ?? (bucketed ? bucketed.field : q.measures[0]?.key);
  const order = q.sort?.order ?? (bucketed && !q.sort ? "asc" : "desc");
  const banded = q.dimensions.find((d) => d.field === by && d.ranges?.length);
  if (banded) {
    const rank = Object.fromEntries(banded.ranges!.map((r, i) => [bandLabel(r), i]));
    out.sort((a, b) => (rank[String(a[by!])] - rank[String(b[by!])]) * (order === "desc" ? -1 : 1));
  } else if (by) out.sort((a, b) => ((a[by] ?? "") > (b[by] ?? "") ? 1 : (a[by] ?? "") < (b[by] ?? "") ? -1 : 0) * (order === "desc" ? -1 : 1));
  if (q.limit) out = out.slice(0, q.limit);
  return out;
}

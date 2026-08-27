/**
 * Extract the AUTHORITATIVE per-component prop contracts from the library's zod
 * schemas — the same `propsSchema`s the renderer's validateProps uses — and write
 * dist/component-contracts.json:
 *   { "<Component>": { "<prop>": { "type": "string"|"number"|"enum"|..., "enum"?: [...], "optional"?: true }, ... }, ... }.
 *
 * The Python context-assembler injects this into the page/form prompt so the model
 * can only emit real components with real prop names (no TableSortable, no `text`
 * instead of `content`, no `rows` getting stripped). Sourced from the live schemas
 * so it can never drift from what the renderer accepts.
 *
 * Run via:  npx tsx scripts/extract-contracts.ts   (after the library is built)
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { buildDefaultRegistry } from "../../library/dist/library/src/buildDefaultRegistry.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outPath = resolve(__dirname, "..", "dist", "component-contracts.json");

type PropDesc = { type: string; enum?: unknown[]; optional?: boolean };

/** Reduce a zod prop schema to a compact { type, enum?, optional? } descriptor. */
function describe(schema: any): PropDesc {
  let s = schema;
  let optional = false;
  // Unwrap optional / nullable / default / effects (preprocess + refine) wrappers.
  for (let i = 0; i < 8 && s && s._def; i++) {
    const tn = s._def.typeName;
    if (tn === "ZodOptional" || tn === "ZodNullable") { optional = true; s = s._def.innerType; continue; }
    if (tn === "ZodDefault") { optional = true; s = s._def.innerType; continue; }
    if (tn === "ZodEffects") { s = s._def.schema; continue; }
    break;
  }
  const tn: string | undefined = s?._def?.typeName;
  const base = (type: string): PropDesc => (optional ? { type, optional } : { type });
  const withEnum = (vals: unknown[]): PropDesc =>
    optional ? { type: "enum", enum: vals, optional } : { type: "enum", enum: vals };
  switch (tn) {
    case "ZodString": return base("string");
    case "ZodNumber": return base("number");
    case "ZodBoolean": return base("boolean");
    case "ZodArray": return base("array");
    case "ZodObject":
    case "ZodRecord": return base("object");
    case "ZodAny":
    case "ZodUnknown": return base("any");
    case "ZodEnum": return withEnum(s._def.values);
    case "ZodNativeEnum": return withEnum(Object.values(s._def.values));
    case "ZodLiteral": return withEnum([s._def.value]);
    case "ZodUnion": {
      const opts: any[] = s._def.options || [];
      const lits = opts.map((o) => (o?._def?.typeName === "ZodLiteral" ? o._def.value : undefined));
      if (lits.length && lits.every((v) => v !== undefined)) return withEnum(lits);
      return base("union");
    }
    default: return base(tn ? tn.replace(/^Zod/, "").toLowerCase() : "any");
  }
}

const reg: any = buildDefaultRegistry();
const out: Record<string, Record<string, PropDesc>> = {};
for (const e of reg.list()) {
  const s: any = e.propsSchema;
  let shape: any = {};
  try {
    shape = (typeof s?._def?.shape === "function" ? s._def.shape() : s?.shape) || {};
  } catch {
    /* non-object schema (union/refine) — leave props empty */
  }
  const props: Record<string, PropDesc> = {};
  for (const key of Object.keys(shape).sort()) props[key] = describe(shape[key]);
  out[e.name] = props;
}

mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, JSON.stringify(out, null, 2) + "\n");
console.log(`Wrote ${Object.keys(out).length} component contracts → ${outPath}`);

import { z } from "zod";
import { starterRegistry } from "../registry/src/starter";
import { NodeV2 } from "../schema/src/page";

const NAMES = ["Alert","AutoFocus","Banner","Drawer","EmptyState","EmptyStateRich","FocusRing","FocusTrap","HoverCard","IllustratedEmpty","InspectorPanel","LoadingState","OptimisticProvider","Popover","PresenceIndicator","Progress","Skeleton","Spinner","Tooltip","TourOverlay","UndoManager"];

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
  const entry = (starterRegistry as any)[name];
  if (!entry) return {};
  return Object.fromEntries(Object.entries(entry.props as Record<string, any>)
    .map(([n, d]) => [n, normalizeSeed(d, d.default)] as [string, unknown])
    .filter(([, v]) => v !== undefined));
}

function unwrap(s: any): any {
  let cur = s;
  for (let i = 0; i < 25 && cur; i++) {
    const t = cur?._def?.typeName;
    if (t === "ZodOptional" || t === "ZodNullable" || t === "ZodDefault" || t === "ZodCatch" || t === "ZodBranded" || t === "ZodReadonly") { cur = cur._def.innerType; continue; }
    if (t === "ZodEffects") { cur = cur._def.schema; continue; }
    if (t === "ZodLazy") { try { cur = cur._def.getter(); continue; } catch { return cur; } }
    break;
  }
  return cur;
}
function describe(s: any): string {
  const inner = unwrap(s);
  const t = inner?._def?.typeName;
  const opt = s?.isOptional?.() ? "?" : "";
  let def = "";
  try { const d = s?._def; if (d?.typeName === "ZodDefault") def = " =" + JSON.stringify(d.defaultValue()); } catch {}
  if (t === "ZodEnum") return "enum[" + inner._def.values.join("|") + "]" + opt + def;
  if (t === "ZodNativeEnum") return "nativeEnum" + opt + def;
  if (t === "ZodUnion") return "union(" + inner._def.options.map((o: any) => describe(o)).join(" , ") + ")" + opt + def;
  if (t === "ZodArray") {
    const checks: string[] = [];
    if (inner._def.minLength) checks.push("min" + inner._def.minLength.value);
    return "array<" + describe(inner._def.type) + ">" + (checks.length ? "(" + checks.join(",") + ")" : "") + opt + def;
  }
  if (t === "ZodString") {
    const cks = (inner._def.checks ?? []).map((c: any) => c.kind + (c.value !== undefined ? c.value : "")).join(",");
    return "string" + (cks ? "(" + cks + ")" : "") + opt + def;
  }
  if (t === "ZodNumber") {
    const cks = (inner._def.checks ?? []).map((c: any) => c.kind + (c.value !== undefined ? c.value : "")).join(",");
    return "number" + (cks ? "(" + cks + ")" : "") + opt + def;
  }
  if (t === "ZodObject") return "object{" + Object.keys(inner.shape).join(",") + "}" + opt + def;
  if (t === "ZodLiteral") return "literal(" + JSON.stringify(inner._def.value) + ")" + opt + def;
  return String(t ?? "?").replace("Zod", "").toLowerCase() + opt + def;
}

const out: string[] = [];
const summary: any[] = [];

for (const name of NAMES) {
  const mod = await import("./src/components/" + name + "/" + name + ".schema.ts");
  const propsSchema = (mod as any)[name + "Props"];
  const entry = (starterRegistry as any)[name];
  out.push("\n================ " + name + " ================");
  if (!propsSchema) { out.push("  !! no <Name>Props export"); continue; }
  const inner = unwrap(propsSchema);
  const shape = inner?.shape ?? {};
  const isStrict = inner?._def?.unknownKeys === "strict";
  const zodKeys = Object.keys(shape);
  out.push("  zod (.strict=" + isStrict + "): " + zodKeys.length + " props");
  for (const k of zodKeys) out.push("     " + k.padEnd(22) + " " + describe(shape[k]));
  if (!entry) { out.push("  !! NO REGISTRY ENTRY"); summary.push({name, noEntry:true, zodCount: zodKeys.length, regCount: 0}); continue; }
  const regKeys = Object.keys(entry.props ?? {});
  out.push("  registry: slots=" + JSON.stringify(entry.slots) + " category=" + entry.category + " icon=" + entry.icon);
  out.push("  registry props: " + regKeys.length);
  for (const k of regKeys) {
    const d = entry.props[k];
    out.push("     " + k.padEnd(22) + " type=" + d.type + " control=" + d.control + " group=" + d.group + " default=" + JSON.stringify(d.default) + (d.options ? " options=" + JSON.stringify(d.options) : ""));
  }
  const EXCL = new Set(["className", "style"]);
  const missing = zodKeys.filter(k => !EXCL.has(k) && !regKeys.includes(k));
  const deadStrict = regKeys.filter(k => !zodKeys.includes(k));
  out.push("  MISSING from editor: " + (missing.length ? missing.join(", ") : "(none)"));
  out.push("  DEAD in registry (not in zod): " + (deadStrict.length ? deadStrict.join(", ") : "(none)"));
  const enumIssues: string[] = [];
  for (const k of regKeys) {
    const d = entry.props[k];
    if (d.type !== "enum" || !d.options) continue;
    const zi = unwrap(shape[k]);
    if (zi?._def?.typeName === "ZodEnum") {
      const zv = zi._def.values as string[];
      const miss = zv.filter(v => !d.options.includes(v));
      const extra = d.options.filter((v: string) => !zv.includes(v));
      const orderDiff = JSON.stringify(zv) !== JSON.stringify([...d.options]);
      if (miss.length || extra.length) enumIssues.push(k + ": zod=[" + zv.join("|") + "] reg=[" + d.options.join("|") + "] MISSING=[" + miss.join("|") + "] EXTRA=[" + extra.join("|") + "]");
      else if (orderDiff) enumIssues.push(k + ": order differs zod=[" + zv.join("|") + "] reg=[" + d.options.join("|") + "]");
    } else if (zi?._def?.typeName === "ZodUnion") {
      enumIssues.push(k + ": zod is union, reg enum=[" + d.options.join("|") + "]");
    }
  }
  out.push("  ENUM issues: " + (enumIssues.length ? enumIssues.join(" ;; ") : "(none)"));
  const reqNoDefault = zodKeys.filter(k => {
    if (EXCL.has(k)) return false;
    if (shape[k].isOptional?.()) return false;
    if (shape[k]?._def?.typeName === "ZodDefault") return false;
    const d = entry.props[k];
    return !d || d.default === undefined || d.default === null || d.default === "";
  });
  out.push("  REQUIRED-no-usable-default: " + (reqNoDefault.length ? reqNoDefault.join(", ") : "(none)"));
  const ctrl: string[] = [];
  for (const k of regKeys) {
    const d = entry.props[k]; const zi = unwrap(shape[k]); const zt = zi?._def?.typeName;
    if (!zt) continue;
    const bad =
      (zt === "ZodNumber" && d.type !== "number") ||
      (zt === "ZodBoolean" && d.type !== "boolean") ||
      (zt === "ZodArray" && d.type !== "array") ||
      (zt === "ZodObject" && d.type !== "object") ||
      (zt === "ZodEnum" && d.type !== "enum");
    if (bad) ctrl.push(k + ": zod=" + zt + " regType=" + d.type + " control=" + d.control);
  }
  out.push("  CONTROL mismatch: " + (ctrl.length ? ctrl.join(" ;; ") : "(none)"));
  const nullDefaults = regKeys.filter(k => entry.props[k].default === null);
  out.push("  null defaults: " + (nullDefaults.length ? nullDefaults.join(", ") : "(none)"));
  const dp = defaultPropsFor(name);
  out.push("  defaultPropsFor -> " + JSON.stringify(dp));
  const cp = propsSchema.safeParse(dp);
  out.push("  component Zod parse: " + (cp.success ? "OK -> " + JSON.stringify(cp.data) : "FAIL " + JSON.stringify(cp.error.issues.map((i:any)=>({p:i.path.join("."),m:i.message,c:i.code})))));
  const node: any = { id: name.toLowerCase() + "-qa01", type: name, props: dp };
  const slotType = entry.slots?.type;
  if (slotType === "list" || slotType === "single") node.children = [];
  const np = NodeV2.safeParse(node);
  out.push("  NodeV2 parse (children=" + (node.children ? "[]" : "absent") + "): " + (np.success ? "OK" : "FAIL " + JSON.stringify(np.error.issues.slice(0,8).map((i:any)=>({p:i.path.join("."),m:i.message})))));
  summary.push({ name, missing, dead: deadStrict, enumIssues, reqNoDefault, ctrl, nullDefaults, compParse: cp.success, nodeParse: np.success, regCount: regKeys.length, zodCount: zodKeys.length });
}

out.push("\n\n================ SUMMARY TABLE ================");
out.push(["comp","zod","reg","missing","dead","enum","reqNoDef","ctrl","null","compOK","nodeOK"].join(" | "));
for (const s of summary as any[]) {
  out.push([s.name, s.zodCount, s.regCount, (s.missing||[]).length, (s.dead||[]).length, (s.enumIssues||[]).length, (s.reqNoDefault||[]).length, (s.ctrl||[]).length, (s.nullDefaults||[]).length, s.compParse, s.nodeParse].join(" | "));
}
console.log(out.join("\n"));

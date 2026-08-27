import { z, type ZodSchema } from "zod";
import type { ComponentType } from "react";

// LLM-generated schemas use legacy/v1 prop names that don't match the v2
// contracts (e.g. Button.content / .href instead of Button.label / .navigate,
// validators.minLength instead of validators.min, Tabs.defaultValue instead
// of Tabs.tabs[]+value). Map common patterns here once at the registry
// boundary so the canvas can render existing schemas without forcing the
// (already-on-disk) JSON to be rewritten.
type RemapFn = (props: Record<string, unknown>) => Record<string, unknown>;

// `content`-as-label and `href`-as-navigate are pervasive in LLM output.
function unifyLabelHref(p: Record<string, unknown>): Record<string, unknown> {
  const out = { ...p };
  if (typeof out.label !== "string" && typeof out.content === "string") out.label = out.content;
  if (typeof out.label !== "string" && typeof out.children === "string") out.label = out.children;
  delete out.content;
  delete out.children;
  if (typeof out.navigate !== "string" && typeof out.href === "string") out.navigate = out.href;
  delete out.href;
  return out;
}

// Table / TableSortable: LLM emits column-level `title` instead of `label`,
// extra `sortable`/`type` keys, and sometimes empty-string `label` (which
// fails the v2 ColumnDef.label.min(1) check). Normalise here so the column
// list parses; nested-key stripping handles other extras.
function remapTableLikeColumns(p: Record<string, unknown>): Record<string, unknown> {
  if (!Array.isArray(p.columns)) return p;
  const cols = (p.columns as unknown[]).map((col) => {
    if (!col || typeof col !== "object") return col;
    const c = { ...(col as Record<string, unknown>) };
    if (typeof c.label !== "string" && typeof c.title === "string") c.label = c.title;
    delete c.title;
    if (typeof c.label !== "string" || c.label.length === 0) {
      // Fall back to the column key so the column still renders with SOME label.
      c.label = typeof c.key === "string" && c.key.length > 0 ? c.key : "—";
    }
    return c;
  });
  return { ...p, columns: cols };
}

// Validators: LLM uses minLength / maxLength; v2 schema uses min / max.
function unifyValidators(p: Record<string, unknown>): Record<string, unknown> {
  if (!p.validators || typeof p.validators !== "object" || Array.isArray(p.validators)) return p;
  const v = { ...(p.validators as Record<string, unknown>) };
  if (v.min === undefined && typeof v.minLength === "number") v.min = v.minLength;
  if (v.max === undefined && typeof v.maxLength === "number") v.max = v.maxLength;
  delete v.minLength; delete v.maxLength;
  return { ...p, validators: v };
}

const PROP_REMAP: Record<string, RemapFn> = {
  Button: (p) => {
    const out = unifyLabelHref(p);
    if (out.variant === "outline") out.variant = "secondary";
    if (typeof out.icon !== "string" && typeof out.iconName === "string") {
      out.icon = out.iconName;
    }
    delete out.iconName;
    return out;
  },
  Link: (p) => {
    const out = unifyLabelHref(p);
    delete out.variant;  // Link has no variant in v2
    return out;
  },
  IconButton: unifyLabelHref,
  NavLink: unifyLabelHref,
  Input: unifyValidators,
  Textarea: unifyValidators,
  DatePicker: unifyValidators,
  Select: unifyValidators,
  Tabs: (p) => {
    // LLM emits Tabs as `{ defaultValue, variant }` — completely different
    // from the v2 contract `{ tabs: [{id,label}], value }`. Without enough
    // info to synthesise a real tabs array, fall back to a single placeholder
    // tab so the canvas renders rather than showing an "invalid props"
    // marker. The user can then rebuild Tabs in the editor.
    if (Array.isArray((p as any).tabs)) return p;
    const v = typeof p.defaultValue === "string" ? p.defaultValue : "tab1";
    return { tabs: [{ id: v, label: "Tab" }], value: v };
  },
  Badge: (p) => {
    const out = { ...p };
    // LLM emits `text` or `label` for badge text; v2 schema uses `content`.
    if (typeof out.content !== "string") {
      if (typeof out.text === "string") out.content = out.text;
      else if (typeof out.label === "string") out.content = out.label;
    }
    delete out.text; delete out.label;
    // Empty content fails .min(1); fall back to a single space so the badge
    // still renders rather than disappearing.
    if (typeof out.content === "string" && out.content.length === 0) out.content = " ";
    // Variants outside the v2 enum get folded into the closest match. Most
    // common LLM choices: info → primary, error → danger, secondary → neutral.
    const variantRemap: Record<string, string> = {
      info: "primary", error: "danger", secondary: "neutral",
      pending: "warning", draft: "neutral",
    };
    if (typeof out.variant === "string") {
      const allowed = new Set(["neutral", "primary", "success", "danger", "warning"]);
      if (!allowed.has(out.variant) && variantRemap[out.variant]) {
        out.variant = variantRemap[out.variant];
      } else if (!allowed.has(out.variant)) {
        out.variant = "neutral";
      }
    }
    return out;
  },
  MetricTile: (p) => {
    const out = { ...p };
    // LLM emits format: "text" / "string" — neither in the v2 enum
    // (number|currency|percent|duration). Fall back to "number" since
    // string values render as-is regardless of format.
    const allowedFormats = new Set(["number", "currency", "percent", "duration"]);
    if (typeof out.format === "string" && !allowedFormats.has(out.format)) {
      out.format = "number";
    }
    return out;
  },
  Table: (p) => remapTableLikeColumns(p),
  TableSortable: (p) => remapTableLikeColumns(p),
  Accordion: (p) => {
    const out = { ...p };
    // LLM emits `multiple` — v2 enum is single|multi.
    if (out.mode === "multiple") out.mode = "multi";
    if (out.mode === "single") out.mode = "single";
    if (out.mode !== "single" && out.mode !== "multi") out.mode = "single";
    return out;
  },
  Hero: (p) => {
    const out = { ...p };
    // Layout: LLM occasionally emits "horizontal" / "vertical" / etc.
    const allowedLayouts = new Set(["centered", "split", "stacked"]);
    if (out.layout !== undefined && !allowedLayouts.has(String(out.layout))) {
      out.layout = "centered";
    }
    // CTA variants: v2 Cta enum is primary|secondary|ghost. LLM emits danger,
    // outline, link, info, etc. Fold to the closest match. Strip CTA-level
    // extras (params, conditions, args, ...) too.
    const allowedCta = new Set(["primary", "secondary", "ghost"]);
    const ctaMap: Record<string, string> = {
      danger: "primary", destructive: "primary",
      outline: "secondary", link: "ghost", info: "primary",
    };
    if (Array.isArray(out.ctas)) {
      out.ctas = (out.ctas as unknown[]).map((c) => {
        if (!c || typeof c !== "object") return c;
        const cta = { ...(c as Record<string, unknown>) };
        if (typeof cta.variant === "string" && !allowedCta.has(cta.variant)) {
          cta.variant = ctaMap[cta.variant] ?? "primary";
        }
        // Drop unknown CTA-level keys; valid keys per v2 Cta union are
        // label, variant, action only.
        for (const k of Object.keys(cta)) {
          if (!["label", "variant", "action"].includes(k)) delete cta[k];
        }
        return cta;
      });
    }
    return out;
  },
};

function stripUnknownKeys(schema: ZodSchema<any>, value: unknown): unknown {
  // Walk a ZodObject's shape and keep only known keys; recurse into nested
  // ZodObject and ZodArray shapes so e.g. Table.columns[].type and other
  // nested unknown keys also get dropped. Non-object schemas pass through.
  if (value === null || value === undefined) return value;
  let inner: any = (schema as any)._def;
  while (inner && (inner.typeName === "ZodEffects" || inner.typeName === "ZodOptional" || inner.typeName === "ZodDefault" || inner.typeName === "ZodNullable")) {
    inner = inner.schema?._def ?? inner.innerType?._def ?? null;
  }
  if (!inner) return value;
  if (inner.typeName === "ZodArray" && Array.isArray(value)) {
    const elementSchema = inner.type ?? inner.element ?? null;
    if (!elementSchema) return value;
    return value.map((item) => stripUnknownKeys(elementSchema, item));
  }
  if (inner.typeName === "ZodObject" && typeof value === "object" && !Array.isArray(value)) {
    const shape = typeof inner.shape === "function" ? inner.shape() : inner.shape;
    if (!shape) return value;
    const known = new Set(Object.keys(shape));
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (known.has(k)) {
        out[k] = stripUnknownKeys(shape[k], v);
      }
    }
    return out;
  }
  if (inner.typeName === "ZodDiscriminatedUnion" || inner.typeName === "ZodUnion") {
    // Don't try to strip across union branches — let zod parse pick a branch.
    // If it doesn't fit, the outer safeParse will fail and we'll surface an
    // error like before.
    return value;
  }
  return value;
}

export type LibraryCategory =
  | "interactive"
  | "static"
  | "form"
  | "data"
  | "feedback"
  | "navigation"
  | "layout"
  | "motion"
  | "custom";

/**
 * How a container interprets its positional children, when they are not a
 * homogeneous body.
 *
 * The library composes with `children`, not named slots — `SplitView` renders
 * `children[0]` as the master column and `children[1]` as the detail pane.
 * That rule used to live only in a doc comment, which meant a generated page
 * could put them in the wrong order and still validate. Declaring it makes the
 * rule checkable before anything renders.
 *
 * Omitted for ordinary containers (`Card`, `Section`, `Stack`), whose children
 * are a homogeneous body where order is only order.
 */
export type ChildContract =
  /** Fixed roles, consumed in order. `roles.length` is the child count. */
  | { kind: "roles"; roles: string[] }
  /** One repeated role. `pairedWith` names a props array of equal length. */
  | { kind: "repeat"; role: string; pairedWith?: string };

export type LibraryEntry = {
  name: string;
  component: ComponentType<any>;
  propsSchema: ZodSchema<any>;
  category: LibraryCategory;
  acceptsChildren: boolean;
  childContract?: ChildContract;
  variants?: Record<string, Record<string, unknown>>;
};

// Set a value at a (possibly nested) Zod error path, creating intermediate
// arrays/objects as needed. Used by validateProps' best-effort coercion.
function setAtPath(obj: any, path: Array<string | number>, value: unknown): void {
  let cur = obj;
  for (let i = 0; i < path.length - 1; i++) {
    const k = path[i];
    if (cur[k] == null || typeof cur[k] !== "object") {
      cur[k] = typeof path[i + 1] === "number" ? [] : {};
    }
    cur = cur[k];
  }
  cur[path[path.length - 1]] = value;
}
function getAtPath(obj: any, path: Array<string | number>): unknown {
  let cur = obj;
  for (const k of path) {
    if (cur == null) return undefined;
    cur = (cur as any)[k];
  }
  return cur;
}

export function createRegistry() {
  const map = new Map<string, LibraryEntry>();
  return {
    register(entry: LibraryEntry) {
      if (map.has(entry.name)) {
        throw new Error(`library entry '${entry.name}' already registered`);
      }
      map.set(entry.name, entry);
    },
    get(name: string): LibraryEntry | undefined {
      return map.get(name);
    },
    has(name: string): boolean {
      return map.has(name);
    },
    list(): LibraryEntry[] {
      return Array.from(map.values());
    },
    validateProps(name: string, props: unknown) {
      const e = map.get(name);
      if (!e) throw new Error(`library entry '${name}' not registered`);
      // Always apply per-component LLM-shape remap first so aliases like
      // Button.iconName → icon are resolved before any parse attempt.
      // Previously the remap only ran when the first parse failed (strict schemas
      // rejected unknown keys), but now that schemas are non-strict the first
      // parse would succeed and silently drop the alias. Running remap eagerly
      // is safe — it only adds/renames known fields and is idempotent.
      const inputProps = (props && typeof props === "object" ? { ...(props as Record<string, unknown>) } : {});
      // `className` is a universal styling prop — the Figma mapper puts Tailwind
      // on every node. Set it aside so strict schemas don't reject it, then
      // re-attach it to whatever the schema validates. This preserves the
      // styling instead of stripping it, and stops className from ever causing
      // an "invalid props" failure.
      const passthrough: Record<string, unknown> = {};
      if (typeof inputProps.className === "string") {
        passthrough.className = inputProps.className;
      }
      delete inputProps.className;
      // `data-*` attributes get the same treatment — schemas mark nodes for
      // app-level CSS/JS hooks (e.g. data-dashboard-toolbar) and a strict
      // schema must never strip them.
      for (const k of Object.keys(inputProps)) {
        if (k.startsWith("data-")) {
          passthrough[k] = inputProps[k];
          delete inputProps[k];
        }
      }
      const finish = (data: Record<string, unknown>): Record<string, unknown> =>
        Object.keys(passthrough).length ? { ...data, ...passthrough } : data;
      const remap = PROP_REMAP[name];
      const remapped = remap ? remap(inputProps) : inputProps;
      // Step 1: try parse first — if the schema matches verbatim (possibly after
      // remap), return early.
      let r = e.propsSchema.safeParse(remapped);
      if (r.success) return finish(r.data);
      // Step 2: strip unknown keys (handles nested arrays of objects like
      // Table.columns[]) then try again.
      const stripped = stripUnknownKeys(e.propsSchema, remapped) as Record<string, unknown>;
      r = e.propsSchema.safeParse(stripped);
      if (r.success) return finish(r.data);
      // Step 3: BEST-EFFORT (render-only). validateProps feeds the renderer;
      // generation strictness lives in @forge/patches (validateRegistryClosure,
      // unaffected). The editor/preview should SHOW a component even when its
      // props are partial or bound at runtime — data/columns/series/options that
      // are null, a required label that's empty, options that are strings — rather
      // than "⚠ invalid props". Coerce the common mismatches from the Zod errors,
      // retry, and if it STILL fails (e.g. a .min() on a runtime-bound array)
      // render with the coerced props anyway; the library components are defensive
      // and apply their own defaults, and a genuine render crash is still caught
      // upstream in the dispatch try/catch.
      let coerced: Record<string, unknown>;
      try {
        coerced = structuredClone(stripped);
      } catch {
        coerced = { ...stripped };
      }
      for (const er of r.error.errors) {
        if (!er.path.length) continue;
        const exp = (er as any).expected;
        const rec = (er as any).received;
        if (er.code === "invalid_type" && exp === "array") {
          // Any non-array where an array is expected → [] so components never
          // crash on `.map` (e.g. Select/RadioGroup options, Table columns).
          setAtPath(coerced, er.path, []);
        } else if (er.code === "invalid_type" && exp === "object" && rec === "string") {
          const cur = getAtPath(coerced, er.path);
          setAtPath(coerced, er.path, typeof cur === "string" ? { value: cur, label: cur } : {});
        } else if (er.code === "invalid_type" && exp === "object") {
          setAtPath(coerced, er.path, {});
        } else if (er.code === "invalid_type" && rec === "undefined") {
          setAtPath(
            coerced,
            er.path,
            exp === "array" ? [] : exp === "object" ? {} : exp === "number" ? 0 : exp === "boolean" ? false : "",
          );
        }
      }
      const r2 = e.propsSchema.safeParse(coerced);
      if (r2.success) return finish(r2.data);
      return finish(coerced);
    },
  };
}

export type Registry = ReturnType<typeof createRegistry>;

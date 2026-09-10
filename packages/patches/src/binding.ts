/**
 * The ONE binding format, and the migration off the two that came before it.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * TentoroForge grew three ways to say "this prop comes from data", and only one
 * of them was ever implemented end-to-end:
 *
 *   1. `node.bind` — the format the v2 schema spec designed for. Honoured by
 *      exactly two nodes (Repeat, Text); every input component destructures it
 *      and throws it away. It validates, it persists, it does nothing.
 *   2. `"{{expr}}"` — a Mustache string. Not in the spec, but it is what the
 *      generation pipeline emits, what every project has on disk, and what
 *      `renderer/src/runtime/interpolate.ts` actually resolves at render time.
 *   3. `{ $binding: "expr" }` — invented by the visual editor's Bindings tab.
 *      Implemented by NOTHING. Zero occurrences outside the editor frontend.
 *
 * Format 3 was a live P0. Clicking the "bind" toggle on a prop wrote the object
 * into `node.props`, where it survived `interpolateDeep` (which only transforms
 * strings) and `validateProps` (which cannot coerce it), and landed in React
 * child position — so the node rendered "⚠ render error" the instant you asked
 * to bind it, before you had typed an expression. Worse, autosave persisted it
 * to `src/schemas/<page>.json`, so the broken prop shipped into the generated
 * application. `validateForCommit` never caught it: it checks id-uniqueness and
 * registry-type closure, and says nothing about prop VALUES.
 *
 * So the editor now writes format 2 — the one the renderer resolves. This module
 * is the single owner of that decision, shared by the reducer (`apply.ts`), the
 * commit guard (`validate.ts`) and the load-time migration, so the three can
 * never drift into a fourth format.
 *
 * Deciding what to do about `node.bind` (honour it on inputs, or deprecate it) is
 * deliberately out of scope here — but note that collapsing 3 formats to 2 is the
 * prerequisite for that conversation.
 */

/** Matches a string that carries at least one `{{ … }}` template. */
const MUSTACHE_RE = /\{\{[\s\S]+?\}\}/;

/** The editor's legacy bound-prop object. */
export interface LegacyBindingObject {
  $binding: string;
}

export function isLegacyBinding(v: unknown): v is LegacyBindingObject {
  return !!v && typeof v === "object" && !Array.isArray(v) && "$binding" in (v as object);
}

export function isMustacheBinding(v: unknown): v is string {
  return typeof v === "string" && MUSTACHE_RE.test(v);
}

/** True for EITHER binding form — used where both must still be recognised. */
export function isBinding(v: unknown): boolean {
  return isMustacheBinding(v) || isLegacyBinding(v);
}

/**
 * The inner expression of a bound value, from either form. `"{{user.name}}"` and
 * `{ $binding: "user.name" }` both yield `"user.name"`.
 */
export function bindingExpression(v: unknown): string {
  if (isLegacyBinding(v)) return String(v.$binding ?? "");
  if (typeof v === "string") {
    const m = v.match(/\{\{\s*([\s\S]*?)\s*\}\}/);
    return m ? m[1] : v;
  }
  return "";
}

/**
 * Wrap an expression as the prop value to store.
 *
 * An EMPTY expression must produce `""`, not `"{{}}"`. The Bindings toggle binds
 * before the user has typed anything (`binding: ""`), and `"{{}}"` would be a
 * template that resolves to nothing while still reading as "bound" — trading the
 * old crash for a subtler version of the same bug. An empty string is honestly
 * "no value yet", renders as nothing, and satisfies a required string field.
 */
export function toBindingValue(expr: string): string {
  const trimmed = (expr ?? "").trim();
  return trimmed === "" ? "" : `{{${trimmed}}}`;
}

/**
 * Rewrite every legacy `{$binding}` in a props bag to the Mustache string form.
 * Returns the SAME object when there is nothing to change, so callers can use
 * identity to skip work.
 *
 * Recurses, because a binding can sit inside the responsive breakpoint envelope
 * (`{ default: …, lg: … }`) or any nested prop object.
 */
export function migrateBindingsDeep<T>(value: T): T {
  if (isLegacyBinding(value)) {
    return toBindingValue(String(value.$binding ?? "")) as unknown as T;
  }
  if (Array.isArray(value)) {
    let changed = false;
    const out = value.map((v) => {
      const r = migrateBindingsDeep(v);
      if (r !== v) changed = true;
      return r;
    });
    return (changed ? out : value) as unknown as T;
  }
  if (value && typeof value === "object") {
    let changed = false;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      const r = migrateBindingsDeep(v);
      if (r !== v) changed = true;
      out[k] = r;
    }
    return (changed ? out : value) as unknown as T;
  }
  return value;
}

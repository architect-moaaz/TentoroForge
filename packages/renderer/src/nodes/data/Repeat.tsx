import { cloneElement, isValidElement } from "react";
import { renderNode, type DispatchContext } from "../../runtime/dispatch";
import { resolveBinding } from "../../runtime/bindings";

/**
 * Repeat — iterate over a data source and render `node.children` once per
 * item. The schema can name that source several ways:
 *
 *   v2 / LLM convention:  { type: "Repeat", bind: "users", children: [...] }
 *   v1 / explicit props:  { type: "Repeat", props: { source: "users", path?, as?, keyPath? }, ... }
 *   tolerated aliases:    props.bind, props.dataSource — with or without {{ }}
 *
 * The aliases are not style preferences; they are what producers actually
 * emit. This node has ONE consumer and MANY producers (deterministic page
 * emitters, LLM page authoring, the A2UI binder), and when it accepted only
 * the first two shapes, 81 of 339 Repeat nodes in the output corpus — 24% —
 * silently iterated nothing. No error, no warning, just an empty list.
 *
 * Accepting the aliases here is what makes already-shipped apps work; the
 * producers are being corrected too, and binding_validator still reports a
 * non-canonical shape so the drift stays visible rather than becoming the
 * new contract. If nothing names a source we render nothing, as before.
 */
export function Repeat({ node, ctx }: { node: any; ctx: DispatchContext }) {
  const props = (node.props ?? {}) as Record<string, unknown>;

  // Each slot holds either the NAME of a collection, or — when the producer
  // wrote `{{orders}}` — the collection itself: dispatch interpolates props
  // against ctx.data before we run, so a mustache-wrapped name arrives here
  // already resolved to its array. Both are legitimate; take whichever came.
  // Canonical slots lead, so a node carrying a real `bind` plus a stale alias
  // uses the real one.
  const slots = [node.bind, props.source, props.bind, props.dataSource];
  let source: string | undefined;
  let resolved: unknown[] | undefined;
  for (const slot of slots) {
    if (Array.isArray(slot)) { resolved = slot; break; }
    if (typeof slot === "string" && slot.trim()) {
      // An unresolved `{{name}}` (source absent from ctx.data) still reaches
      // us as a literal — strip the braces so the lookup gets a fair try.
      const name = slot.trim().replace(/^\{\{\s*|\s*\}\}$/g, "").trim();
      if (name) { source = name; break; }
    }
  }

  const items = (() => {
    if (resolved) return resolved;
    if (!source) return [];
    const root = (ctx.data as Record<string, unknown>)[source];
    if (root === undefined || root === null) return [];
    const path = typeof props.path === "string" ? (props.path as string) : undefined;
    if (!path) return Array.isArray(root) ? root : [];
    const v = resolveBinding({ source, path }, ctx);
    return Array.isArray(v) ? v : [];
  })();

  const as = (typeof props.as === "string" ? props.as : "item");
  const keyPath = (typeof props.keyPath === "string" ? props.keyPath : "id");

  return (
    <>
      {items.map((item: any) => {
        const childCtx: DispatchContext = {
          ...ctx,
          data: { ...ctx.data, [as]: item },
        };
        const key = item?.[keyPath] ?? JSON.stringify(item);
        // Tag each rendered child with a stable React key derived from the
        // schema node's id (falls back to index). Mirrors the dispatch.tsx
        // structural-children pattern so React's missing-key warning doesn't
        // fire when Repeat templates contain multiple top-level children.
        const renderedChildren = (node.children ?? []).map((c: any, i: number) => {
          const rendered = renderNode(c, childCtx);
          const childKey = c?.id ?? i;
          return isValidElement(rendered) ? cloneElement(rendered, { key: childKey }) : rendered;
        });
        return (
          <div key={key} data-repeat-item>
            {renderedChildren}
          </div>
        );
      })}
    </>
  );
}

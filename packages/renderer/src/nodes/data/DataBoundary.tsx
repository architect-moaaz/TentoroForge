import { cloneElement, isValidElement } from "react";
import { renderNode, type DispatchContext } from "../../runtime/dispatch";

// Phase 1: thin wrapper that catches sync errors during child render and
// shows a fallback. React Suspense / async errors handled by an upstream
// error boundary in the App Router page wrapper.
//
// Key discipline: each mapped child gets a stable React key derived from
// the schema node's id, falling back to a `<type>-<index>` synthetic when
// LLM-composed schemas omit ids (see backend/services/page_composer.py).
// Without this fallback React logs a "unique key" warning and — when two
// siblings share the same missing-id — an "encountered two children with
// the same key" error.
export function DataBoundary({ node, ctx }: { node: any; ctx: DispatchContext }) {
  try {
    return (
      <>
        {(node.children ?? []).map((c: any, i: number) => {
          const rendered = renderNode(c, ctx);
          const key = c?.id ?? `${c?.type ?? "node"}-${i}`;
          return isValidElement(rendered) ? cloneElement(rendered, { key }) : rendered;
        })}
      </>
    );
  } catch (err) {
    console.warn("[renderer] DataBoundary caught:", err);
    return <div data-error>{node.props?.fallback ?? "Could not load."}</div>;
  }
}

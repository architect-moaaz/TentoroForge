"use client";
import * as React from "react";
import { useDesignTime } from "../client/DesignTime";

/**
 * THE NODES THE EDITOR COULD NOT SEE, SELECT, FILL OR BIND.
 *
 * `renderNode` tags every node it dispatches with `data-node-id` — that
 * attribute is the editor's whole handle on a node: `closest("[data-node-id]")`
 * is how selection resolves, how a drop finds its accepting parent, and how the
 * empty-node hint finds a box to draw on. Four node types were dispatched
 * *before* that tagging and returned a bare fragment or `null`:
 *
 *   Repeat · Conditional · DataBoundary · Slot
 *
 * So a palette drop committed to disk, autosaved, survived reload — and emitted
 * no element at all. The audit measured it precisely: canvas node count 3 before
 * the drop and 3 after, with the node present in the saved JSON. The
 * consequences all follow from the missing element rather than from anything
 * these four components do:
 *
 *   - it cannot be selected, so its Properties panel is unreachable, so
 *     `source` / `when` / `bind` cannot be typed;
 *   - it cannot be a drop target, because `resolveAcceptingParent` walks
 *     `closest("[data-node-id]")`;
 *   - it gets no empty-node hint, because the hint measures a box and there is
 *     none;
 *   - and there is no layers panel to reach it from.
 *
 * The standing excuse — "config-driven builtins correctly render nothing until
 * bound to data" — is what this shell retires: the bound state was **not
 * reachable**, because binding needs a selection and selection needs an element.
 *
 * WHY ONE SHELL AND NOT FOUR PLACEHOLDERS
 * ---------------------------------------
 * Nothing below knows what a Repeat is. The label is `node.type`, read off the
 * node; the "what do I fill in" copy is deliberately NOT here, because the
 * editor already derives that generically from the component's own Zod schema
 * (`empty-hints.ts`), and it could not attach it for want of a box. Giving these
 * nodes a box re-enables that mechanism instead of duplicating it. A fifth
 * structural node added to the dispatcher gets the same treatment by being
 * wrapped, with no new case anywhere.
 *
 * RUNTIME IS UNCHANGED IN SHAPE
 * -----------------------------
 * Outside an authoring surface the wrapper is `display: contents` — it
 * generates no layout box, so no shipped page moves by a pixel — and it carries
 * the `data-node-id` the library path has always emitted. Only inside a
 * `DesignTimeProvider` does it become a visible, outlined, labelled container.
 */
export function StructuralNodeShell({
  node,
  children,
}: {
  node: { id?: string; type?: string };
  children: React.ReactNode;
}) {
  const designTime = useDesignTime();
  const type = node?.type ?? "Node";

  if (!designTime) {
    return (
      <span
        data-node-id={node?.id}
        data-structural-node={type}
        style={{ display: "contents" }}
      >
        {children}
      </span>
    );
  }

  return (
    <div
      data-node-id={node?.id}
      data-structural-node={type}
      // A real box, because the point is to be measurable, clickable and
      // droppable. Minimum height so an unconfigured node is still a target
      // rather than a hairline; the frontend's hint overlay pads out anything
      // smaller than its own minimum, but a drop target has to exist in the
      // layout, which an overlay is not.
      style={{
        display: "block",
        position: "relative",
        minHeight: 44,
        padding: "18px 8px 8px",
        border: "1px dashed var(--border, hsl(0 0% 78%))",
        borderRadius: "var(--radius-sm, 0.25rem)",
        background: "var(--muted, hsl(0 0% 97%))",
        boxSizing: "border-box",
      }}
    >
      <span
        // The chip is inert: `pointer-events: none` so it can never eat the
        // click that selects the node or the drop that fills it.
        aria-hidden="true"
        style={{
          position: "absolute",
          top: 2,
          left: 6,
          pointerEvents: "none",
          fontSize: "0.625rem",
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          color: "var(--muted-foreground, hsl(0 0% 45%))",
        }}
      >
        {type}
      </span>
      {children}
    </div>
  );
}

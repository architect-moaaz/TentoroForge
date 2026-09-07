import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useUrlState } from "../../style/useUrlState";

type Props = {
  syncKey?: string;
  masterWidth?: number;
  emptyText?: string;
  responsive?: boolean;
  requireSelection?: boolean;
  style?: StyleSlotT;
  className?: string;
  children?: React.ReactNode;
};

const RESPONSIVE_BP_PX = 768;

/**
 * SplitView — master-detail split with URL selection sync.
 *
 * children[0] is the master (list) pane, children[1] is the detail pane.
 * Anything beyond the second child joins the detail pane rather than being
 * dropped: `slots` declares `maxChildren: 2` so the editor guides you to two,
 * but SplitView is also written by the LLM pipeline, by JSON edits and by
 * projections, and silently deleting a node no writer was warned about is the
 * worst possible failure mode.
 *
 * WHY THE DETAIL PANE NO LONGER WAITS FOR ?selected= :
 * this was the highest-loss container in the editor (docs/editor-audit/
 * containment.md #2: 117 of 133 parent/child pairs failed). The old code
 * rendered `selected ? detailNode : <p>{emptyText}</p>`, and the editor never
 * puts a `?selected=` on the preview URL, so the second pane and everything
 * inside it were invisible with no warning, no cap and no indicator — the
 * probe `zzprobe-panes` recorded `SplitView2, SplitView2_k0` with `_k1`
 * missing. Content the user placed must be visible where they placed it, so
 * the detail child renders unconditionally and `emptyText` is now the
 * empty-state for having NO detail child at all. Apps that genuinely want the
 * "pick a row first" gate opt back in with `requireSelection`.
 *
 * The selected id is still read from and written to the URL query key, and
 * rows inside the master pane that carry `data-forge-split-id="<id>"` still
 * become clickable and update it — descendants can key off
 * `[data-forge-split-view][data-forge-split-selected]` exactly as before.
 */
export function SplitView({
  syncKey = "selected",
  masterWidth = 320,
  emptyText = "Select an item to see details.",
  responsive = true,
  requireSelection = false,
  style,
  className,
  children,
}: Props): React.ReactElement {
  const styleProps = resolveStyle(style);
  const [selected, setSelected] = useUrlState(syncKey, "");
  const rootRef = React.useRef<HTMLDivElement | null>(null);
  // Scopes the responsive stack rule to this instance — a page may hold more
  // than one SplitView and a bare `[data-forge-split-view]` rule would make the
  // last one's masterWidth win for all of them.
  const id = React.useId().replace(/:/g, "-");

  const kids = React.Children.toArray(children);
  const masterNode = kids[0] ?? null;
  const detailNodes = kids.slice(1);
  const hasDetail = detailNodes.length > 0;
  const showDetail = hasDetail && (!requireSelection || !!selected);

  // Delegate click handling: any descendant carrying
  // data-forge-split-id becomes selectable without wiring per row.
  React.useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target;
      if (!(target instanceof HTMLElement)) return;
      const hit = target.closest<HTMLElement>("[data-forge-split-id]");
      if (!hit) return;
      const id = hit.getAttribute("data-forge-split-id");
      if (id != null) setSelected(id);
    };
    root.addEventListener("click", onClick);
    return () => root.removeEventListener("click", onClick);
  }, [setSelected]);

  return (
    <>
      {/* `responsive` was accepted and then ignored (the prop was destructured
          as `_responsive`), so a 320px master column stayed 320px at 375px wide
          and pushed the detail pane to ~55px. It now does what the registry
          says: below the breakpoint the two panes stack. Setting it false keeps
          the two columns at every width. */}
      <style>{`
        [data-forge-split-id-scope="${id}"] { grid-template-columns: ${masterWidth}px 1fr; }
        ${responsive ? `
        @media (max-width: ${RESPONSIVE_BP_PX - 1}px) {
          [data-forge-split-id-scope="${id}"] { grid-template-columns: 1fr; }
          [data-forge-split-id-scope="${id}"] > [data-forge-split-master] {
            border-right: none;
            border-bottom: 1px solid var(--border, hsl(0 0% 90%));
          }
        }` : ""}
      `}</style>
      <div
        ref={rootRef}
        data-forge-split-view
        data-forge-split-id-scope={id}
        data-forge-split-selected={selected || undefined}
        className={className}
        style={{
          display: "grid",
          gap: 0,
          minHeight: 320,
          border: "1px solid var(--border, hsl(0 0% 90%))",
          borderRadius: "var(--radius-md, 0.5rem)",
          overflow: "hidden",
          background: "var(--card, white)",
          ...styleProps,
        }}
      >
        <aside
          data-forge-split-master
          style={{
            borderRight: "1px solid var(--border, hsl(0 0% 90%))",
            overflow: "auto",
            minWidth: 0,
          }}
        >
          {masterNode}
        </aside>
        <section
          data-forge-split-detail
          aria-live="polite"
          style={{ overflow: "auto", padding: 16, minWidth: 0 }}
        >
          {showDetail ? (
            detailNodes
          ) : (
            <p style={{ color: "var(--muted-foreground, hsl(0 0% 45%))", margin: 0 }}>
              {emptyText}
            </p>
          )}
        </section>
      </div>
    </>
  );
}

import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useUrlState } from "../../style/useUrlState";

type Props = {
  syncKey?: string;
  masterWidth?: number;
  emptyText?: string;
  responsive?: boolean;
  style?: StyleSlotT;
  className?: string;
  children?: React.ReactNode;
};

/**
 * SplitView — master-detail split with URL selection sync.
 *
 * First two children become the master/detail panes. Any additional
 * children are ignored (with a data-attr for debugging). Renders a
 * simple 2-column grid; the master column has a fixed width and the
 * detail pane fills the remainder.
 *
 * The selected id is read from and written to a URL query key so a
 * page reload preserves the selection. Rows inside the master pane
 * that carry `data-forge-split-id="<id>"` become clickable and update
 * the selection when tapped (a lightweight convention that keeps this
 * component agnostic of its list-widget subject).
 */
export function SplitView({
  syncKey = "selected",
  masterWidth = 320,
  emptyText = "Select an item to see details.",
  responsive: _responsive = true,
  style,
  className,
  children,
}: Props): React.ReactElement {
  const styleProps = resolveStyle(style);
  const [selected, setSelected] = useUrlState(syncKey, "");
  const rootRef = React.useRef<HTMLDivElement | null>(null);

  const kids = React.Children.toArray(children);
  const masterNode = kids[0] ?? null;
  const detailNode = kids[1] ?? null;

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
    <div
      ref={rootRef}
      data-forge-split-view
      data-forge-split-selected={selected || undefined}
      className={className}
      style={{
        display: "grid",
        gridTemplateColumns: `${masterWidth}px 1fr`,
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
        {selected ? (
          detailNode
        ) : (
          <p style={{ color: "var(--muted-foreground, hsl(0 0% 45%))", margin: 0 }}>
            {emptyText}
          </p>
        )}
      </section>
    </div>
  );
}

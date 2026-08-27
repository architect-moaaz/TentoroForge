import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { useMotion } from "../../style/useMotion";
import { resolveStyle } from "../../style/resolveStyle";

type View = { id: string; label: string; isDefault?: boolean };
type Props = {
  views: View[];
  activeViewId?: string;
  onSelectWorkflow?: string;
  style?: StyleSlotT;
};

/**
 * SavedViewsPicker — Spec C Slice 7. Segmented control-ish row of
 * view buttons. Emits a data-view-id + fires the onSelectWorkflow
 * when clicked. Kept dependency-free; a proper Combobox variant can
 * ship later when views > 5.
 */
export function SavedViewsPicker({
  views, activeViewId, onSelectWorkflow, style,
}: Props): React.ReactElement {
  const motion = useMotion(style?.motion);
  const styleProps = resolveStyle(style);
  const active = activeViewId ?? views.find((v) => v.isDefault)?.id ?? views[0]?.id;
  return (
    <div
      role="tablist"
      aria-label="Saved views"
      data-forge-saved-views
      {...motion}
      style={{
        display: "inline-flex",
        gap: 0,
        padding: 2,
        border: "1px solid var(--border, hsl(0 0% 90%))",
        borderRadius: "var(--radius-md, 0.375rem)",
        background: "var(--muted, hsl(0 0% 96%))",
        ...styleProps,
      }}
    >
      {views.map((v) => {
        const isActive = v.id === active;
        return (
          <button
            key={v.id}
            role="tab"
            type="button"
            aria-selected={isActive}
            data-view-id={v.id}
            data-forge-workflow={onSelectWorkflow}
            style={{
              padding: "6px 12px",
              borderRadius: "var(--radius-sm, 0.25rem)",
              border: "none",
              cursor: "pointer",
              fontSize: "0.813rem",
              background: isActive ? "var(--background, white)" : "transparent",
              color: isActive
                ? "var(--foreground, hsl(0 0% 15%))"
                : "var(--muted-foreground, hsl(0 0% 45%))",
              boxShadow: isActive ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
              fontWeight: isActive ? 500 : 400,
            }}
          >
            {v.label}
          </button>
        );
      })}
    </div>
  );
}

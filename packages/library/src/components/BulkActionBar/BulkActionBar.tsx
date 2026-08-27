import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { useMotion } from "../../style/useMotion";
import { resolveStyle } from "../../style/resolveStyle";

type Action = {
  label: string;
  workflow: string;
  variant?: "primary" | "secondary" | "ghost" | "destructive";
};

type Props = {
  selectedCount?: number;
  actions: Action[];
  onClear?: string;
  style?: StyleSlotT;
};

const BTN_STYLES: Record<NonNullable<Action["variant"]>, React.CSSProperties> = {
  primary:     { background: "var(--primary, hsl(210 60% 45%))", color: "var(--primary-foreground, white)" },
  secondary:   { background: "var(--secondary, hsl(0 0% 96%))", color: "var(--secondary-foreground, hsl(0 0% 15%))" },
  ghost:       { background: "transparent", color: "var(--foreground, hsl(0 0% 15%))" },
  destructive: { background: "var(--destructive, hsl(0 70% 50%))", color: "var(--destructive-foreground, white)" },
};

/**
 * BulkActionBar — Spec C Slice 7 selection toolbar.
 *
 * Renders nothing when selectedCount === 0. Otherwise, floats a
 * horizontal bar with the count + a row of workflow-triggering buttons.
 * Adopts brand tokens; visible via data-forge-bulk-action-bar for
 * page-level styling if needed.
 */
export function BulkActionBar({
  selectedCount = 0,
  actions,
  onClear,
  style,
}: Props): React.ReactElement | null {
  const motion = useMotion(style?.motion);
  const styleProps = resolveStyle(style);
  if (selectedCount === 0) return null;
  return (
    <div
      data-forge-bulk-action-bar
      role="toolbar"
      aria-label={`${selectedCount} selected`}
      {...motion}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "10px 14px",
        borderRadius: "var(--radius-md, 0.375rem)",
        border: "1px solid var(--border, hsl(0 0% 90%))",
        background: "var(--card, white)",
        color: "var(--card-foreground, hsl(0 0% 15%))",
        boxShadow: "0 4px 6px -1px rgba(0,0,0,0.1)",
        ...styleProps,
      }}
    >
      <span style={{ fontWeight: 500, fontSize: "0.875rem" }}>
        {selectedCount} selected
      </span>
      <span style={{ flex: 1 }} />
      {actions.map((a, i) => (
        <button
          key={`${a.workflow}-${i}`}
          type="button"
          data-forge-workflow={a.workflow}
          style={{
            padding: "6px 12px",
            borderRadius: "var(--radius-sm, 0.25rem)",
            border: "none",
            cursor: "pointer",
            fontSize: "0.813rem",
            ...BTN_STYLES[a.variant ?? "secondary"],
          }}
        >
          {a.label}
        </button>
      ))}
      {onClear ? (
        <button
          type="button"
          data-forge-workflow={onClear}
          aria-label="Clear selection"
          style={{
            padding: "6px 8px",
            border: "none",
            background: "transparent",
            color: "var(--muted-foreground, hsl(0 0% 45%))",
            cursor: "pointer",
            fontSize: "0.813rem",
          }}
        >
          ✕
        </button>
      ) : null}
    </div>
  );
}

"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { UndoManagerPropsType } from "./UndoManager.schema";
import { resolveStyle } from "../../style/resolveStyle";

/**
 * Runtime shape the mutation queue publishes.
 * `id`   — unique per emission (used to dismiss)
 * `label`— human copy ("Task moved", "Row deleted")
 * `undo` — fires the inverse mutation; queue removes on success
 */
export type UndoEntry = {
  id: string;
  label: string;
  undo: () => void | Promise<void>;
  createdAt?: number;
};

/**
 * Module-level bus so the mutation-queue in `@forge/renderer` can push
 * entries without a runtime dependency on this library package.
 * The runtime dispatches a `CustomEvent<UndoEntry>` on the window with
 * type `"forge:undo:push"` (and `"forge:undo:dismiss"` with `{id}`).
 * The UndoManager listens and mirrors into local state.
 */
export interface UndoManagerProps extends UndoManagerPropsType {
  style?: StyleSlotT;
}

const POSITION_STYLES: Record<
  NonNullable<UndoManagerPropsType["position"]>,
  React.CSSProperties
> = {
  "bottom-left":   { bottom: 16, left: 16 },
  "bottom-center": { bottom: 16, left: "50%", transform: "translateX(-50%)" },
  "bottom-right":  { bottom: 16, right: 16 },
  "top-center":    { top: 16,    left: "50%", transform: "translateX(-50%)" },
};

export function UndoManager({
  position = "bottom-center",
  timeoutMs = 6000,
  labelPrefix,
  maxStack = 5,
  style,
  className,
}: UndoManagerProps): React.ReactElement | null {
  const [entries, setEntries] = React.useState<UndoEntry[]>([]);

  React.useEffect(() => {
    if (typeof window === "undefined") return;

    const onPush = (ev: Event) => {
      const e = (ev as CustomEvent<UndoEntry>).detail;
      if (!e || !e.id) return;
      setEntries((prev) => {
        const next = [...prev.filter((x) => x.id !== e.id), { ...e, createdAt: Date.now() }];
        return next.slice(-maxStack);
      });
    };
    const onDismiss = (ev: Event) => {
      const { id } = (ev as CustomEvent<{ id: string }>).detail ?? { id: "" };
      if (!id) return;
      setEntries((prev) => prev.filter((x) => x.id !== id));
    };

    window.addEventListener("forge:undo:push", onPush as EventListener);
    window.addEventListener("forge:undo:dismiss", onDismiss as EventListener);
    return () => {
      window.removeEventListener("forge:undo:push", onPush as EventListener);
      window.removeEventListener("forge:undo:dismiss", onDismiss as EventListener);
    };
  }, [maxStack]);

  React.useEffect(() => {
    if (timeoutMs === 0 || entries.length === 0) return;
    const timers = entries.map((e) => {
      const remaining = Math.max(
        0,
        timeoutMs - (Date.now() - (e.createdAt ?? Date.now())),
      );
      return setTimeout(() => {
        setEntries((prev) => prev.filter((x) => x.id !== e.id));
      }, remaining);
    });
    return () => timers.forEach(clearTimeout);
  }, [entries, timeoutMs]);

  if (entries.length === 0) return null;
  const styleProps = resolveStyle(style);

  return (
    <div
      data-forge-undo-manager
      role="region"
      aria-label="Undo actions"
      style={{
        position: "fixed",
        zIndex: 1000,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        ...POSITION_STYLES[position],
        ...styleProps,
      }}
      className={className}
    >
      {entries.map((e) => (
        <div
          key={e.id}
          role="status"
          aria-live="polite"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "10px 14px",
            borderRadius: "var(--radius-md, 0.375rem)",
            border: "1px solid var(--border, hsl(0 0% 90%))",
            background: "var(--card, white)",
            color: "var(--card-foreground, hsl(0 0% 15%))",
            boxShadow: "0 10px 15px -3px rgba(0,0,0,0.15)",
            minWidth: 260,
            fontSize: "0.875rem",
          }}
        >
          <span style={{ flex: 1 }}>
            {labelPrefix ? `${labelPrefix} ${e.label}` : e.label}
          </span>
          <button
            type="button"
            onClick={() => {
              try {
                void e.undo();
              } finally {
                setEntries((prev) => prev.filter((x) => x.id !== e.id));
              }
            }}
            style={{
              padding: "4px 10px",
              border: "none",
              borderRadius: "var(--radius-sm, 0.25rem)",
              background: "var(--primary, hsl(210 60% 45%))",
              color: "var(--primary-foreground, white)",
              cursor: "pointer",
              fontSize: "0.813rem",
              fontWeight: 500,
            }}
          >
            Undo
          </button>
        </div>
      ))}
    </div>
  );
}

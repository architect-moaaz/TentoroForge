"use client";

import * as React from "react";
import { useUrlState } from "../../style/useUrlState";

interface InspectorPanelProps {
  paramKey?: string;
  title?: string;
  width?: "narrow" | "default" | "wide";
  children?: React.ReactNode;
}

const WIDTH_PX: Record<string, number> = {
  narrow: 320, default: 480, wide: 640,
};

export function InspectorPanel({
  paramKey = "inspector", title, width = "default", children,
}: InspectorPanelProps) {
  const [active, setActive] = useUrlState(paramKey, "");
  if (!active) return null;

  const close = () => setActive("");

  // Esc-to-close
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-foreground/20 transition-opacity"
        onClick={close}
        aria-hidden="true"
      />
      <aside
        className="fixed end-0 top-0 z-50 h-full bg-card border-s border-border shadow-2xl flex flex-col"
        style={{ width: WIDTH_PX[width] }}
        role="complementary"
        aria-modal="true"
      >
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h3 className="text-sm font-semibold">{title ?? `Details (${active})`}</h3>
          <button
            type="button"
            onClick={close}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Close inspector"
          >
            ✕
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-4">
          {children}
        </div>
      </aside>
    </>
  );
}

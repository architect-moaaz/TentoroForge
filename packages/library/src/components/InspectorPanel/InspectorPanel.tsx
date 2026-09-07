"use client";

import * as React from "react";
import { useUrlState } from "../../style/useUrlState";

interface InspectorPanelProps {
  paramKey?: string;
  title?: string;
  width?: "narrow" | "default" | "wide";
  defaultOpen?: boolean;
  children?: React.ReactNode;
}

const WIDTH_PX: Record<string, number> = {
  narrow: 320, default: 480, wide: 640,
};

/**
 * InspectorPanel — a fixed detail drawer driven by a URL search param.
 *
 * `defaultOpen` exists because the panel is otherwise unreachable from the
 * editor: it renders `null` until `?<paramKey>=` is in the URL, which the
 * canvas and the preview never set, so it was one of the components that
 * "render an EMPTY box with default props" and swallow anything dropped into
 * them (docs/editor-audit/containment.md). Turning it on shows the panel with
 * no selection so its contents can be composed; the URL param still opens and
 * closes it at runtime and still wins once it carries a value.
 *
 * The Esc handler is registered BEFORE the early return. It used to sit after
 * it, so the number of hooks this component called changed the moment a
 * selection appeared — React's "rendered more hooks than during the previous
 * render" crash, which the per-node boundary would have turned into an
 * "invalid node" chip on the first click.
 */
export function InspectorPanel({
  paramKey = "inspector", title, width = "default", defaultOpen = false, children,
}: InspectorPanelProps) {
  const [active, setActive] = useUrlState(paramKey, "");

  const close = React.useCallback(() => setActive(""), [setActive]);
  const open = !!active || defaultOpen;

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-foreground/20 transition-opacity"
        onClick={close}
        aria-hidden="true"
      />
      <aside
        data-inspector-panel={paramKey}
        className="fixed end-0 top-0 z-50 h-full bg-card border-s border-border shadow-2xl flex flex-col"
        style={{ width: WIDTH_PX[width] }}
        role="complementary"
        aria-modal="true"
      >
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h3 className="text-sm font-semibold">{title || (active ? `Details (${active})` : "Details")}</h3>
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

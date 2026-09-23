"use client";
/**
 * The office, inside the run panel: a short strip of the floor while a build
 * runs, and a button to watch it full screen.
 *
 * The panel's bar says how far the build is; this says what it is doing —
 * who is at a desk, how many pages the engineer has in hand, the reviewer
 * sending one back, everybody waiting on a busy API, the strike when the
 * credit runs out. The same canvas the Office tab shows, fed by the run's
 * own events (see `officeBridge`).
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Building2, Maximize2, X } from "lucide-react";

import { VirtualOffice, useOfficeStore } from "@/components/virtual-office";

export function OfficeStrip() {
  const [expanded, setExpanded] = useState(false);
  const runActive = useOfficeStore((s) => s.runActive);
  const active = useOfficeStore((s) => s.activeAgents);

  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setExpanded(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);

  return (
    <div className="mb-2 overflow-hidden rounded-md border bg-background" data-testid="office-strip">
      <div className="flex items-center justify-between px-2 py-1 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <Building2 className="h-3 w-3" />
          {active.size > 0
            ? `${active.size} agent${active.size === 1 ? "" : "s"} at work`
            : runActive ? "The office is getting ready" : "The office"}
        </span>
        <button type="button" onClick={() => setExpanded(true)}
                className="flex items-center gap-1 rounded px-1 py-0.5 hover:bg-muted hover:text-foreground"
                aria-label="Watch the office full screen">
          <Maximize2 className="h-3 w-3" /> Watch
        </button>
      </div>
      <div className="h-44">
        {!expanded && <VirtualOffice className="h-full w-full" isGenerating={runActive} />}
      </div>
      {expanded && createPortal(
        <div className="fixed inset-0 z-[100] flex flex-col bg-background">
          <div className="flex items-center justify-between border-b bg-muted/40 px-4 py-2">
            <span className="flex items-center gap-2 text-sm font-medium">
              <Building2 className="h-4 w-4 text-primary" /> The office
            </span>
            <button type="button" onClick={() => setExpanded(false)} aria-label="Close"
                    className="rounded p-1 hover:bg-muted"><X className="h-4 w-4" /></button>
          </div>
          <div className="min-h-0 flex-1">
            <VirtualOffice className="h-full w-full" isGenerating={runActive} />
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}

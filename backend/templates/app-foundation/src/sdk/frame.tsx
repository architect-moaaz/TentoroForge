"use client";
// What every coded page renders inside — the same frame a schema page gets:
// the landmark the skip link jumps to, live refresh when the page's entities
// change elsewhere, and the workflow dispatcher library controls look for.

import type { ReactNode } from "react";
import { LiveRefresh } from "@/lib/LiveRefresh";
import { WorkflowDispatchProvider } from "@/lib/WorkflowDispatchProvider";

export function PageFrame({ entities, children }: { entities: string[]; children: ReactNode }) {
  return (
    <WorkflowDispatchProvider>
      <main id="main" role="main" tabIndex={-1}>
        {entities.length > 0 && <LiveRefresh entities={entities.map((e) => e.toLowerCase())} />}
        {children}
      </main>
    </WorkflowDispatchProvider>
  );
}

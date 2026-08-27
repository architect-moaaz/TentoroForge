"use client";

// Client provider that supplies a REAL workflow dispatch to the renderer's
// WorkflowDispatcherContext. Any schema Form or Button carrying a `workflow`
// action calls this dispatch — most importantly a declarative <Form>, whose
// collected field values become the workflow payload.
//
// The dispatch POSTs to the generated /api/workflows/{name}/execute route and,
// on success, calls router.refresh() so any data the workflow changed is
// re-fetched. Loading / success / error feedback uses the app's existing
// `sonner` toaster (mounted in src/app/providers.tsx).
//
// This replaces the previous server-side console.warn stub that lived inline in
// schema-page.tsx (a server closure could never be a valid client dispatch).

import type { ReactNode } from "react";
import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  WorkflowDispatcherProvider,
  createWorkflowDispatch,
} from "@tentoroforge/renderer";

export function WorkflowDispatchProvider({ children }: { children: ReactNode }) {
  const router = useRouter();

  const dispatch = useMemo(
    () =>
      createWorkflowDispatch({
        onStart: (name) =>
          toast.loading(`Running ${name}…`, { id: `wf:${name}` }),
        onSuccess: (name, result) => {
          // Summarize what actually happened. `steps_ran` / `log.length` /
          // an entity id from the returned row are the three things a user
          // wants to see — "Done" alone left them staring at an unchanged
          // screen. Duration long enough to notice; description carries the
          // detail without stealing focus.
          const r = (result ?? {}) as {
            log?: Array<unknown>;
            status?: string;
            output?: Record<string, unknown>;
          };
          const stepCount = Array.isArray(r.log) ? r.log.length : undefined;
          const output = r.output && typeof r.output === "object" ? r.output : {};
          // Prefer a top-level `id` on any recently-created entity in output.
          const entityId = Object.values(output).find(
            (v) =>
              v && typeof v === "object" && typeof (v as { id?: unknown }).id === "string",
          ) as { id?: string } | undefined;
          const parts: string[] = [];
          if (stepCount !== undefined) parts.push(`${stepCount} step${stepCount === 1 ? "" : "s"}`);
          if (r.status && r.status !== "completed") parts.push(r.status);
          const desc = parts.length ? parts.join(" · ") : undefined;
          toast.success(`${name} complete`, {
            id: `wf:${name}`,
            description: desc,
            duration: 4500,
          });
          void entityId; // reserved for a future "View" action once page routes are stable
          // Re-fetch server components so data the workflow changed shows up.
          router.refresh();
        },
        onError: (name, message) =>
          toast.error(message || "Workflow failed", {
            id: `wf:${name}`,
            duration: 8000,
          }),
      }),
    [router],
  );

  return (
    <WorkflowDispatcherProvider dispatch={dispatch}>
      {children}
    </WorkflowDispatcherProvider>
  );
}

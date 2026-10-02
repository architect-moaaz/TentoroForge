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
  destinationAfterDelete,
} from "@tentoroforge/renderer";

export function WorkflowDispatchProvider({ children }: { children: ReactNode }) {
  const router = useRouter();

  const dispatch = useMemo(
    () =>
      createWorkflowDispatch({
        onStart: (name) =>
          toast.loading(`Running ${name}…`, { id: `wf:${name}` }),
        onSuccess: (name, result, args) => {
          // Summarize what actually happened. `steps_ran` / `log.length` /
          // an entity id from the returned row are the three things a user
          // wants to see — "Done" alone left them staring at an unchanged
          // screen. Duration long enough to notice; description carries the
          // detail without stealing focus.
          const r = (result ?? {}) as {
            log?: Array<unknown>;
            status?: string;
            output?: Record<string, unknown>;
            notices?: string[];
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
          // A RUN THAT DID HALF OF WHAT IT SAYS IS NOT A SUCCESS TOAST. The
          // engine collects a `notice` from any step that could not do what
          // its name claims — an email that became an in-app notification
          // because no email service is connected — and this is the screen
          // the person who pressed the button is already looking at. Showing
          // "complete · 4 steps" over a message that was never sent is how
          // "the confirmation email never came" became a mystery.
          const notices = (r.notices ?? []).filter(
            (n): n is string => typeof n === "string" && n.trim().length > 0,
          );
          if (notices.length) {
            toast.warning(`${name} ran, but not everything happened`, {
              id: `wf:${name}`,
              description: notices.join(" "),
              // Long enough to read a sentence that asks for an action, and
              // dismissible — it is information, not an error to acknowledge.
              duration: 12000,
            });
          } else {
            toast.success(`${name} complete`, {
              id: `wf:${name}`,
              description: desc,
              duration: 4500,
            });
          }
          void entityId; // reserved for a future "View" action once page routes are stable
          // Re-fetch server components so data the workflow changed shows up.
          // A delete of the record this page is standing on is a departure:
          // refreshing re-rendered a page for a record that no longer
          // existed, empty and still armed. Go up to the list instead.
          const away = typeof window !== "undefined"
            ? destinationAfterDelete(args, result, window.location.pathname)
            : null;
          if (away) router.push(away);
          else router.refresh();
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

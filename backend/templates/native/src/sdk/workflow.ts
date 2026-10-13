// The app SDK (native) — running a workflow from a screen. Every change to data
// is a workflow the Blueprint declares, typed by its inputs (`@/sdk/workflows`,
// projected): a form that leaves a required input out, or a button that passes a
// field the workflow does not take, does not compile. Same as the web's
// `useWorkflow`, with the same result:
//
//   const { run, pending, error } = useWorkflow(workflows.approveOrder, { successMessage: "Approved" });
//   const out = await run({ orderId });       // out: { ok, result, error }
//
// WHAT HAPPENS FOR THE SCREEN (unless `silent`):
//   - a success toasts `successMessage` (else "<Name> — done"), buzzes lightly,
//     and tells every mounted read to look again (so the list the person comes
//     back to shows the change);
//   - REFUSED (the rules said no): the workflow's end says why in the person's
//     words; that sentence is the toast. Anything else that broke toasts
//     "<Name> failed" with the message;
//   - `redirectTo` (or the run's own `redirect`, which wins) takes the person
//     on: an outside address opens in the browser, an app route is pushed.
//     Without either the screen stays where it is, showing fresh data.

import * as React from "react";
import { Linking } from "react-native";
import * as Haptics from "expo-haptics";
import { client } from "./api";
import { refreshReads } from "./events";
import { nextStop, runWorkflowRequest, type Json, type RunResult } from "./run";
import { toast } from "./toast";
import { useNav } from "./nav";
import type { Workflow } from "./workflows";

export type { RunResult };

/** A tap's feedback must never be the reason a run fails. */
function buzz(kind: "success" | "error"): void {
  Haptics.notificationAsync(kind === "success" ? Haptics.NotificationFeedbackType.Success : Haptics.NotificationFeedbackType.Error)
    .catch(() => undefined);
}

export function useWorkflow<I extends Json>(
  workflow: Workflow<I>,
  options: { successMessage?: string; redirectTo?: string; silent?: boolean } = {},
) {
  const nav = useNav();
  const navRef = React.useRef(nav);
  navRef.current = nav;
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  // Unmounted while the run was in flight (the redirect left the screen): no state to set.
  const live = React.useRef(true);
  React.useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);

  const run = React.useCallback(async (input: I): Promise<RunResult> => {
    setPending(true);
    setError(null);
    const out = await runWorkflowRequest(client, workflow.id, input);
    if (live.current) setPending(false);
    if (!out.ok) {
      const message = out.error ?? "Something went wrong.";
      if (live.current) setError(message);
      if (!options.silent) {
        // REFUSED is the workflow's rules saying no — its sentence IS the toast.
        if (out.refused) toast.error(message);
        else toast.error(`${workflow.name} failed`, { description: message });
        buzz("error");
      }
      return { ok: false, result: out.result, error: message };
    }
    if (!options.silent) { toast.success(options.successMessage ?? `${workflow.name} — done`); buzz("success"); }
    refreshReads.emit({ workflowId: workflow.id });
    const stop = nextStop(out.result, options.redirectTo);
    if (stop?.kind === "external") void Linking.openURL(stop.to).catch(() => toast.error("That address could not be opened."));
    else if (stop) navRef.current.push(stop.to);
    return { ok: true, result: out.result, error: null };
  }, [workflow.id, workflow.name, options.successMessage, options.redirectTo, options.silent]);

  return { run, pending, error };
}

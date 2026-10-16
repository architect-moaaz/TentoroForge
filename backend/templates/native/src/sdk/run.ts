// The app SDK (native) — running a workflow, without React. `useWorkflow`
// (workflow.ts) is a thin hook over this; the tests call it with a fake client.
//
// THE RESULT IS THE WEB'S. `RunResult` and the failed/refused reading are the
// same as `useWorkflow` in the web SDK (client.tsx), so a page written for one
// is read the same way for the other:
//   - a run FAILED when the call failed, the reply carries an `error`, or its
//     `status` is "failed" (the server answers 422 for that);
//   - it was REFUSED when its rules said no (`result.refused === true`): the
//     workflow's end says why, in the person's words, and that sentence is what
//     is shown. Anything else that broke is shown as "<Name> failed" + message;
//   - what it returned is `result`: its receipt (status, the record it wrote as
//     `id`, `records`) and `reply`, the values its end declared for this page.
//
// PURE — no react-native import.

import type { Client } from "./http";

export type Json = Record<string, unknown>;

export interface RunResult {
  ok: boolean;
  /** What the workflow returned — its receipt: status, the record it wrote if
   *  any, and `reply`, the values its end declared for this page by name. */
  result: Json;
  error: string | null;
}

/** The sentence for a failed reply: the reply's own, else the status. */
export function humanError(result: Json, status: number): string {
  const e = result.error;
  if (typeof e === "string" && e) return e;
  if (e && typeof e === "object" && typeof (e as Json).message === "string") return String((e as Json).message);
  return `Something went wrong (${status}).`;
}

/** The run, read as the web reads it. `status` 0 is no answer at all. */
export function readRun(status: number, ok: boolean, result: Json): { failed: boolean; refused: boolean; message: string | null } {
  const failed = !ok || Boolean(result.error) || result.status === "failed";
  return { failed, refused: failed && result.refused === true, message: failed ? humanError(result, status) : null };
}

export interface RunOutcome extends RunResult {
  /** The workflow's rules said no (see the header). */
  refused: boolean;
}

/** POST /api/workflows/<id>/execute with `{ input }`. Never throws. */
export async function runWorkflowRequest(client: Client, workflowId: string, input: Json): Promise<RunOutcome> {
  const res = await client.json<Json>(`/api/workflows/${encodeURIComponent(workflowId)}/execute`, { body: { input } });
  if (res.networkError) return { ok: false, result: {}, error: res.networkError, refused: false };
  const result = res.body && typeof res.body === "object" && !Array.isArray(res.body) ? res.body : {};
  const read = readRun(res.status, res.ok, result);
  if (read.failed) return { ok: false, result, error: read.message, refused: read.refused };
  return { ok: true, result, error: null, refused: false };
}

/** Where a finished run sends the person: the run's own `redirect` wins (its
 *  end declared where to go next), else the screen's `redirectTo`. An outside
 *  address (a hosted checkout) is opened in the browser, a route of the app is
 *  pushed. */
export function nextStop(result: Json, redirectTo?: string): { kind: "external" | "route"; to: string } | null {
  const go = typeof result.redirect === "string" && result.redirect ? String(result.redirect) : redirectTo;
  if (!go) return null;
  return /^https?:\/\//i.test(go) ? { kind: "external", to: go } : { kind: "route", to: go };
}

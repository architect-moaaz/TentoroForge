// PLACEHOLDER of the generated `src/sdk/workflows.ts` — not copied into apps.
// The real one is `emit_workflows` in services/blueprint/app_sdk.py (identical
// to the web app's): one typed handle per workflow.

/** A workflow a screen can run. `I` is its input — what a form must collect
 *  or a button must pass. The phantom `__input` field only carries the type. */
export interface Workflow<I> {
  id: string;
  name: string;
  /** The inputs it cannot run without — what a form marks required. */
  required?: readonly string[];
  readonly __input?: I;
}

function wf<I>(id: string, name: string, required: readonly string[] = []): Workflow<I> {
  return { id, name, required };
}

export const workflows = {
  /** Create Task — a sample. */
  createTask: wf<{
    title: string;
    amount?: number;
    dueDate?: string;
    status?: "open" | "done";
    place?: { lat: number; lng: number };
    photo?: string;
  }>("WF-001", "Create Task", ["title"]),
  /** Complete Task — a sample. */
  completeTask: wf<{
    /** id of the Task record */
    taskId: string;
  }>("WF-002", "Complete Task", ["taskId"]),
} as const;

export type WorkflowKey = keyof typeof workflows;
/** The input type of a workflow handle. */
export type InputOf<W> = W extends Workflow<infer I> ? I : never;

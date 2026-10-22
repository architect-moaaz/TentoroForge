/**
 * Hand Smith a message from another tab of the project — the Business Rules
 * tab's "Ask Smith to build it into the app", say. The project page shows the
 * chat; Smith's composer is filled with the text, for the person to read and
 * send (it is their request, so it is never sent behind their back).
 */
export const ASK_SMITH_EVENT = "forge:ask-smith";

export interface AskSmithDetail {
  projectId: string;
  text: string;
}

export function askSmith(projectId: string, text: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<AskSmithDetail>(ASK_SMITH_EVENT, { detail: { projectId, text } }));
}

/** Open a workflow of the project in the Workflows tab — from the Business
 *  Rules tab's "used in" list, say. `workflow` is its id in the app's
 *  definition (FLOW-…). */
export const OPEN_WORKFLOW_EVENT = "forge:open-workflow";

export interface OpenWorkflowDetail {
  projectId: string;
  workflow: string;
}

let pendingWorkflow: OpenWorkflowDetail | null = null;

export function openWorkflow(projectId: string, workflow: string): void {
  if (typeof window === "undefined") return;
  // Kept for the Workflows tab to pick up when it mounts after the switch.
  pendingWorkflow = { projectId, workflow };
  window.dispatchEvent(new CustomEvent<OpenWorkflowDetail>(OPEN_WORKFLOW_EVENT, { detail: { projectId, workflow } }));
}

/** The workflow asked for and not yet opened, for this project (taken once). */
export function takeOpenWorkflow(projectId: string): string | null {
  if (!pendingWorkflow || pendingWorkflow.projectId !== projectId) return null;
  const w = pendingWorkflow.workflow;
  pendingWorkflow = null;
  return w;
}

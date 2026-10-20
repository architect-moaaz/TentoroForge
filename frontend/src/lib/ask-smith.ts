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

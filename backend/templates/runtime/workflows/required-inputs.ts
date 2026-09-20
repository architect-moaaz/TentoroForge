/**
 * What a run cannot start without.
 *
 * A workflow declares its `inputs` in the Blueprint, each required unless it
 * says otherwise, and the projection carries the required names into the
 * definition the engine loads. The browser already knew them — the SDK types
 * the call and the form marks the boxes — but the server did not, so a run
 * that arrived without one went ahead: 0l133sp2's "Submit Identity
 * Verification" set `kycStatus: pending` and wrote NULL over the identity
 * photo, and the member was told their document had been submitted.
 *
 * Empty is missing. An image input carries a file id, a text input a string;
 * "" is what an untouched box sends, and writing it over a column is the same
 * mistake as writing null.
 */
import type { WorkflowDefinition } from "./types";

export function missingRequiredInputs(
  workflow: Pick<WorkflowDefinition, "requiredInputs">,
  input: Record<string, unknown>,
): string[] {
  return (workflow.requiredInputs ?? []).filter((name) => {
    const value = input?.[name];
    return value === undefined || value === null || value === "";
  });
}

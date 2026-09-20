/**
 * A record input arrives as an id; the steps read it as a record.
 *
 * A workflow declares `member` as a RECORD input, and a control sends the id
 * it has — that is the contract on both sides. Nothing then loaded the row, so
 * every step that read a field of it read nothing:
 *
 *   - `member.kycStatus = "pending"` was false for a member who WAS pending,
 *     so "Approve verification" answered "this member is not currently
 *     awaiting verification review" and no admin could ever approve anyone;
 *   - `{{member.displayName}} has submitted an identity document` was stored
 *     as " has submitted an identity document".
 *
 * Both measured on 0l133sp2. The id stays reachable — a record's own `id` is
 * the id — so `{{member.id}}` in a WHERE keeps working either way.
 */
import type { WorkflowDefinition } from "./types";

/** `(table, id) -> the row`, so this stays testable without a database. */
export type LoadRecord = (table: string, id: string) => Promise<Record<string, unknown> | null>;

export async function hydrateRecordInputs(
  workflow: Pick<WorkflowDefinition, "recordInputs">,
  input: Record<string, unknown>,
  load: LoadRecord,
): Promise<Record<string, unknown>> {
  const declared = workflow.recordInputs ?? [];
  if (!declared.length) return input;
  const out = { ...input };
  for (const { name, table } of declared) {
    const value = out[name];
    // Already a record (an event payload, a resumed task's variables): left
    // alone. Only an id is a record nobody has read yet.
    if (!table || typeof value !== "string" || !value) continue;
    try {
      const row = await load(table, value);
      if (row) out[name] = row;
    } catch (err) {
      // A row that cannot be read is not a reason to lose the run: the steps
      // see the id they were given, exactly as before.
      console.warn(`[workflow] could not load ${table} ${value}:`, err);
    }
  }
  return out;
}

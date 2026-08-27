/**
 * Audit Log — per-state-transition logger for workflow approvals.
 *
 * Generated apps import this and pass their DB connection.
 * Uses `db: any` because the actual driver (Drizzle / Prisma / raw SQL)
 * depends on the generated app — adapt the insert/select calls to your ORM.
 */

export interface AuditLogEntry {
  id: string;
  workflowId: string;
  recordId: string;
  timestamp: string;        // ISO 8601
  actor: string;            // user ID
  action: "submitted" | "approved" | "rejected" | "reassigned"
        | "escalated" | "reminder-sent" | "delegated";
  fromStage?: string;
  toStage?: string;
  note?: string;
  metadata?: Record<string, any>;
}

const AUDIT_LOG_TABLE = "workflow_audit_log";

/**
 * Append a new audit entry for a workflow state transition.
 *
 * @param db  Your DB connection (Drizzle `db`, Prisma `prisma`, etc.)
 * @param entry  Audit data minus the generated `id`
 */
export async function appendAuditEntry(
  db: any,    // your DB connection
  entry: Omit<AuditLogEntry, "id">,
): Promise<AuditLogEntry> {
  const id = crypto.randomUUID();
  const full: AuditLogEntry = { ...entry, id };
  await db.insert(AUDIT_LOG_TABLE).values(full);
  return full;
}

/**
 * Retrieve the full audit trail for a specific record in a workflow,
 * ordered oldest-first.
 *
 * @param db  Your DB connection
 * @param workflowId  Workflow definition ID
 * @param recordId  The record being processed through the workflow
 */
export async function getAuditTrailForRecord(
  db: any,
  workflowId: string,
  recordId: string,
): Promise<AuditLogEntry[]> {
  return db.select().from(AUDIT_LOG_TABLE)
           .where({ workflowId, recordId })
           .orderBy({ timestamp: "asc" });
}

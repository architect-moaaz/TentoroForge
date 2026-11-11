/**
 * Who may do what on a tracked job — the decisions, with no I/O, so they can be
 * tested alone. The job is a record in the app's own data (an order, a ride, a
 * visit). The person on the move is the one that record names; the app's own
 * read rules decide who may follow (see access.ts).
 *
 * Forge runtime — do not remove.
 */

/** A field that names the person on the move: driverId, courier_id, assignee … */
const MOVER_FIELD = /^(driver|courier|rider|technician|partner|mover|agent|assignee|assigned_?to)(_?id)?$/i;

/** A status that says the job is over. A position is never shared after it. */
const FINISHED = /^(delivered|cancell?ed|completed?|done|closed|finished|arrived|dropped_?off|failed|rejected)$/i;

type Row = Record<string, unknown>;

/** The id of the person on the move, or null when the job names none. */
export function moverId(job: Row | null | undefined): string | null {
  if (!job) return null;
  for (const [key, value] of Object.entries(job)) {
    if (MOVER_FIELD.test(key) && typeof value === "string" && value) return value;
  }
  return null;
}

/** True when the job's status says it is over. A job with no status is not. */
export function finished(job: Row | null | undefined): boolean {
  const status = job?.status;
  return typeof status === "string" && FINISHED.test(status.trim().replace(/[\s-]+/g, "_"));
}

/** Only the person the job names may send a position for it. */
export function mayShare(job: Row | null | undefined, userId: string | null | undefined): boolean {
  const mover = moverId(job);
  return !!mover && !!userId && mover === userId;
}

/** The key one job's mailbox lives under, so two kinds of record never collide. */
export function tripKey(entity: string, id: string): string {
  return `${entity.toLowerCase()}:${id}`;
}

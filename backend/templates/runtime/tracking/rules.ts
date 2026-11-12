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

/* ---------------------------------------------------------------------------
 * A FLEET: many people on the move at once, not tied to one job (drivers who
 * are online and waiting for work). Each is a record of the app's own data —
 * a Driver, a Courier, a Technician. The record says who the person is and
 * whether they are on duty; the app's own read rules say who may watch them.
 * ------------------------------------------------------------------------- */

/** A field that links a mover's record to their sign-in: userId, account_id, owner … */
const SELF_FIELD = /^(user|account|owner|person|login)(_?id)?$/i;

/** A field that says whether the person is on duty. */
const DUTY_FIELD = /^(availability|availabilitystatus|online|isonline|onduty|duty|status)$/;
/** A value that says NOT on duty. */
const OFF_DUTY = /^(offline|off_?duty|unavailable|away|inactive|false|0|no)$/i;
/** A field that says whether the account is cleared to work. */
const CLEARED_FIELD = /^(verification|verificationstatus|approval|approvalstatus|accountstatus)$/;
const NOT_CLEARED = /^(pending|pending_?verification|rejected|suspended|blocked|banned|unverified|disabled|deactivated)$/i;

const norm = (v: unknown) => String(v).trim().replace(/[\s-]+/g, "_");

/** True when this record is the signed-in person's own: their id, or a field that names them. */
export function isSelf(rec: Row | null | undefined, userId: string | null | undefined): boolean {
  if (!rec || !userId) return false;
  if (rec.id === userId) return true;
  for (const [key, value] of Object.entries(rec)) {
    if ((SELF_FIELD.test(key) || MOVER_FIELD.test(key)) && typeof value === "string" && value === userId) return true;
  }
  return false;
}

/**
 * Why this person may NOT be on the map, or null when they may. Not cleared to
 * work (pending, rejected, suspended) or off duty are both a no.
 */
export function whyNotOnDuty(rec: Row | null | undefined): string | null {
  if (!rec) return "No such person.";
  for (const [name, value] of Object.entries(rec)) {
    const key = name.replace(/_/g, "").toLowerCase(); // verification_status and verificationStatus are one field
    if (CLEARED_FIELD.test(key) && typeof value === "string" && NOT_CLEARED.test(norm(value)))
      return "This account is not cleared to go online.";
    if (DUTY_FIELD.test(key) && (typeof value === "string" || typeof value === "boolean")) {
      if (value === false || (typeof value === "string" && (OFF_DUTY.test(norm(value)) || NOT_CLEARED.test(norm(value)))))
        return "Go online first.";
    }
  }
  return null;
}

/** What to call them on the map: name, title, … */
export function fleetLabel(rec: Row | null | undefined): string | undefined {
  if (!rec) return undefined;
  for (const k of ["name", "fullName", "full_name", "title", "label", "displayName"]) {
    const v = rec[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return undefined;
}

/** What kind they are, for the pin: vehicle type, role … */
export function fleetKind(rec: Row | null | undefined): string | undefined {
  if (!rec) return undefined;
  for (const [k, v] of Object.entries(rec)) {
    if (/^(vehicle_?type|vehicle|kind|category|type)$/i.test(k) && typeof v === "string" && v.trim()) return v.trim();
  }
  return undefined;
}

/** The key one kind of record's fleet lives under. */
export function fleetKey(entity: string): string {
  return `fleet:${entity.toLowerCase()}`;
}

/**
 * The database side of sending turns to the platform: marking rows sent, catching up on the ones that were not, and
 * clearing out the ones that were sent long ago. Forge runtime — do not remove.
 *
 * The sending itself (batching, timing, retries, the shape of the events) is agents/insights-shipper.ts, which knows
 * nothing about the app. This file is what connects it to the app's tables, and it is the only place that does.
 *
 * Every function here assumes the tables, or the newest columns, may not be there yet (an app updated but not yet
 * migrated): a failure means "nothing marked, nothing sent", never an error for a chat.
 */
import { db } from "@/db";
import { forgeAgentTurns } from "@/db/schema/_forge_agent_turns";
import { forgeAgentHandoffs } from "@/db/schema/_forge_agent_handoffs";
import { and, asc, eq, gte, inArray, isNull, lt, or, sql } from "drizzle-orm";
import {
  MAX_EVENT_AGE_MS,
  MAX_EVENTS_PER_REQUEST,
  buildRatingEvent,
  createShipper,
  itemForHandoff,
  itemForTurnRow,
  type OutboxItem,
  type OutboxStore,
  type Shipper,
  type TurnOutboxRow,
} from "./insights-shipper";

// ── marking rows ──────────────────────────────────────────────────────────

/** Handoff events already taken by the platform, so the tick does not offer the same ones every minute. */
const sentHandoffEvents = new Set<string>();
const MAX_REMEMBERED = 2000;

const turnIds = (items: OutboxItem[]) => items.filter((i) => i.kind === "turn");

/**
 * Apply `set` to the rows these items stand for. A row that was never rated is matched on that; a rated one only while
 * its rating is still the one the item carried. A newer rating put the row back in the outbox, and marking the older
 * send as done must not take it out again.
 */
async function updateRows(items: OutboxItem[], set: Record<string, unknown>): Promise<void> {
  const turns = turnIds(items);
  const unrated = turns.filter((i) => !i.ratingAt).map((i) => i.rowId);
  if (unrated.length) {
    await db.update(forgeAgentTurns).set(set).where(and(inArray(forgeAgentTurns.id, unrated), isNull(forgeAgentTurns.ratingAt)));
  }
  for (const item of turns.filter((i) => i.ratingAt)) {
    await db
      .update(forgeAgentTurns)
      .set(set)
      .where(and(eq(forgeAgentTurns.id, item.rowId), eq(forgeAgentTurns.ratingAt, new Date(item.ratingAt as number))));
  }
}

export const outbox: OutboxStore = {
  async markShipped(items) {
    for (const item of items) {
      if (item.kind !== "handoff") continue;
      if (sentHandoffEvents.size > MAX_REMEMBERED) sentHandoffEvents.clear();
      for (const e of item.events) sentHandoffEvents.add(e.id);
    }
    await updateRows(items, { shippedAt: new Date(), shipError: null });
  },

  async markRejected(items, reason) {
    // Closed like a sent row, with the reason kept, so it is not tried again and is cleared out with the others.
    await updateRows(items, { shippedAt: new Date(), shipError: reason.slice(0, 200) });
  },

  async markFailed(items, reason) {
    const ids = turnIds(items).map((i) => i.rowId);
    if (!ids.length) return;
    await db
      .update(forgeAgentTurns)
      .set({ shipAttempts: sql`coalesce(${forgeAgentTurns.shipAttempts}, 0) + 1`, shipError: reason.slice(0, 200) })
      .where(and(inArray(forgeAgentTurns.id, ids), isNull(forgeAgentTurns.shippedAt)));
  },
};

// ── the one shipper of this server ────────────────────────────────────────

/** One per server process, however many bundles import this file (the same way the watch feed is kept). */
const g = globalThis as unknown as { __forgeInsightsShipper?: Shipper };

export function insightsShipper(): Shipper {
  return (g.__forgeInsightsShipper ??= createShipper({
    env: process.env,
    fetch: (url, init) => fetch(url, init),
    store: outbox,
  }));
}

/** A rating was given or changed: tell the platform (best-effort; the row is already back in the outbox). */
export function shipRating(r: { turnId: string; rating: number; note: string | null; ratingAt: Date }): void {
  insightsShipper().enqueueFrom((cfg) => {
    const event = buildRatingEvent(r, cfg);
    return event ? { kind: "turn", rowId: r.turnId, ratingAt: r.ratingAt.getTime(), events: [event] } : null;
  });
}

/** A handoff was opened, claimed or resolved: tell the platform (best-effort; the tick repeats it for two days). */
export function shipHandoff(h: Parameters<typeof itemForHandoff>[0]): void {
  insightsShipper().enqueueFrom(() => itemForHandoff(h));
}

// ── catching up, and clearing out ─────────────────────────────────────────

/** Is this the database saying a column is not there (an app that was updated but whose schema was not pushed)? */
export function isMissingColumn(e: unknown): boolean {
  const err = e as { code?: unknown; message?: unknown; cause?: { code?: unknown; message?: unknown } } | null;
  if (err?.code === "42703" || err?.cause?.code === "42703") return true;
  return /column .* does not exist/i.test(`${err?.message ?? ""} ${err?.cause?.message ?? ""}`);
}

/** What the tick reads of a row: only what the events are made of, never the words of a conversation. */
const OUTBOX_COLUMNS = {
  id: forgeAgentTurns.id,
  conversationId: forgeAgentTurns.conversationId,
  agentId: forgeAgentTurns.agentId,
  userId: forgeAgentTurns.userId,
  userRole: forgeAgentTurns.userRole,
  model: forgeAgentTurns.model,
  inputTokens: forgeAgentTurns.inputTokens,
  outputTokens: forgeAgentTurns.outputTokens,
  ms: forgeAgentTurns.ms,
  status: forgeAgentTurns.status,
  error: forgeAgentTurns.error,
  toolCalls: forgeAgentTurns.toolCalls,
  toolErrors: forgeAgentTurns.toolErrors,
  toolStats: forgeAgentTurns.toolStats,
  handedOff: forgeAgentTurns.handedOff,
  turnNumber: forgeAgentTurns.turnNumber,
  rating: forgeAgentTurns.rating,
  ratingNote: forgeAgentTurns.ratingNote,
  ratingAt: forgeAgentTurns.ratingAt,
  problemMessage: forgeAgentTurns.problemMessage,
  createdAt: forgeAgentTurns.createdAt,
};

const DAY_MS = 86_400_000;
const HANDOFF_RESEND_MS = 2 * DAY_MS;
const PRUNE_BATCH = 500;

export interface TickReport {
  /** False when the app has no ingest address, key or salt: nothing was done, nothing was deleted. */
  configured: boolean;
  /** Events the platform took (rows marked sent), including rows closed because it refused them for good. */
  sent: number;
  /** Rows closed here without sending, because they are older than the platform accepts or cannot be told. */
  skipped: number;
  /** Rows still waiting after this tick (when it stopped because of a failure or its limits). */
  waiting: boolean;
  /** Sent rows deleted because they were sent more than the retention days ago. */
  pruned: number;
  /** Set when sending stopped on a failure, or the database could not be read. */
  note?: string;
}

/**
 * The cron tick's part (api-cron-insights route): send the OLDEST rows still waiting, up to `maxBatches` requests of
 * 500, then delete rows that were sent more than `retentionDays` ago, in small batches. A platform outage or a crashed
 * process loses nothing: the rows are still here. An app that is not connected keeps every row and deletes nothing.
 */
export async function runInsightsTick(
  opts: { now?: Date; maxBatches?: number; retentionDays?: number; budgetMs?: number } = {},
): Promise<TickReport> {
  const shipper = insightsShipper();
  const cfg = shipper.config;
  if (!cfg) return { configured: false, sent: 0, skipped: 0, waiting: false, pruned: 0 };
  const now = opts.now ?? new Date();
  const started = Date.now();
  const budget = opts.budgetMs ?? 20_000;
  const maxBatches = Math.max(1, opts.maxBatches ?? (Number(process.env.FORGE_INSIGHTS_TICK_BATCHES) || 10));
  const retentionDays = Math.max(1, opts.retentionDays ?? (Number(process.env.FORGE_INSIGHTS_RETENTION_DAYS) || 7));
  const report: TickReport = { configured: true, sent: 0, skipped: 0, waiting: false, pruned: 0 };
  let healthy = true;

  try {
    for (let batch = 0; batch < maxBatches && Date.now() - started < budget; batch++) {
      const rows = (await db
        .select(OUTBOX_COLUMNS)
        .from(forgeAgentTurns)
        .where(isNull(forgeAgentTurns.shippedAt))
        .orderBy(asc(forgeAgentTurns.createdAt))
        .limit(MAX_EVENTS_PER_REQUEST)) as TurnOutboxRow[];
      if (!rows.length) break;

      const items: OutboxItem[] = [];
      const unusable: string[] = [];
      for (const row of rows) {
        const at = row.createdAt ? new Date(row.createdAt).getTime() : NaN;
        const item = Number.isNaN(at) || now.getTime() - at > MAX_EVENT_AGE_MS ? null : itemForTurnRow(row, cfg);
        if (item) items.push(item);
        else unusable.push(row.id);
      }
      if (unusable.length) {
        await db
          .update(forgeAgentTurns)
          .set({ shippedAt: now, shipError: "not sent: older than the platform keeps, or not complete" })
          .where(inArray(forgeAgentTurns.id, unusable));
        report.skipped += unusable.length;
      }

      const result = await shipper.send(items);
      report.sent += result.done;
      if (result.deferred > 0 || result.backoffMs !== null) {
        report.waiting = true;
        report.note = "the platform could not take the turns right now; they stay here and are sent on a later tick";
        healthy = false;
        break;
      }
      if (rows.length < MAX_EVENTS_PER_REQUEST) break;
      if (batch === maxBatches - 1) report.waiting = true;
    }
  } catch (e) {
    healthy = false;
    report.waiting = true;
    report.note = isMissingColumn(e)
      ? "the database was not updated after the last runtime update (npx drizzle-kit push)"
      : "the waiting turns could not be read";
  }

  // Handoffs that changed in the last two days, offered again until the platform has taken them. (They are few, and the
  // platform ignores a repeat; this is how a change survives a crash or a platform outage.)
  if (healthy) {
    try {
      const since = new Date(now.getTime() - HANDOFF_RESEND_MS);
      const rows = await db
        .select()
        .from(forgeAgentHandoffs)
        .where(or(gte(forgeAgentHandoffs.createdAt, since), gte(forgeAgentHandoffs.claimedAt, since), gte(forgeAgentHandoffs.resolvedAt, since)))
        .orderBy(asc(forgeAgentHandoffs.createdAt))
        .limit(200);
      const items = rows
        .map((r: any) => itemForHandoff(r))
        .filter((i): i is OutboxItem => !!i && !i.events.every((e) => sentHandoffEvents.has(e.id)));
      if (items.length) report.sent += (await shipper.send(items)).done;
    } catch {
      /* no handoff table yet, or nothing to say */
    }
  }

  // Retention: what was sent a while ago has done its job. Small batches, so the table is never locked for long.
  try {
    const cutoff = new Date(now.getTime() - retentionDays * DAY_MS);
    for (let i = 0; i < 20; i++) {
      const old = await db
        .select({ id: forgeAgentTurns.id })
        .from(forgeAgentTurns)
        .where(lt(forgeAgentTurns.shippedAt, cutoff))
        .orderBy(asc(forgeAgentTurns.shippedAt))
        .limit(PRUNE_BATCH);
      if (!old.length) break;
      await db.delete(forgeAgentTurns).where(inArray(forgeAgentTurns.id, old.map((r: any) => r.id)));
      report.pruned += old.length;
      if (old.length < PRUNE_BATCH) break;
    }
  } catch {
    /* the rows stay until the next tick */
  }
  return report;
}

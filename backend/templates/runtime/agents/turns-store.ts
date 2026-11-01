/**
 * What each turn cost and how it went, on the app's own database: one row per assistant turn. Forge runtime — do not remove.
 *
 * Callers treat any failure here (typically: the table does not exist yet in an app that was updated but not
 * migrated) as "nothing recorded", never as a reason to fail or slow a chat. The runtime wraps `record` for exactly
 * that (runtime.ts, recordTurnSafely); the thumbs up/down route reports a failure in a plain sentence.
 *
 * The row is also the OUTBOX of the platform's insights: once it is written, an event for it is handed to the
 * shipper (insights-shipper.ts), which sends it in the background. Handing over never waits and never fails.
 */
import { randomUUID } from "node:crypto";
import { db } from "@/db";
import { forgeAgentTurns } from "@/db/schema/_forge_agent_turns";
import { and, count, eq } from "drizzle-orm";
import { insightsShipper, isMissingColumn, shipRating } from "./insights-outbox";
import { itemForTurnRow, problemOf, type TurnOutboxRow } from "./insights-shipper";
import type { TurnStore } from "./types";

/** At most this many tools are kept per turn (the counts still cover every call). */
const MAX_TOOL_STATS = 20;
const MAX_PROBLEM_CHARS = 200;

let saidColumnsMissing = false;

function sayColumnsMissing() {
  if (saidColumnsMissing) return;
  saidColumnsMissing = true;
  try {
    console.warn("[agent] the turns table lacks the newest columns, so turns are recorded without them and cannot be sent to the platform yet. Run the database push (npx drizzle-kit push); the chat is not affected.");
  } catch {
    /* a broken logger is not the chat's problem either */
  }
}

/** Which message in its conversation this is, when the runtime could not say: one more than the turns already recorded. */
async function turnNumberOf(conversationId: string): Promise<number> {
  if (!conversationId) return 1;
  try {
    const [row] = await db.select({ n: count() }).from(forgeAgentTurns).where(eq(forgeAgentTurns.conversationId, conversationId));
    return Number(row?.n ?? 0) + 1;
  } catch {
    return 1;
  }
}

async function write(t: Parameters<TurnStore["record"]>[0]): Promise<void> {
  const id = randomUUID();
  const createdAt = new Date();
  const turnNumber = t.turnNumber && t.turnNumber > 0 ? Math.round(t.turnNumber) : await turnNumberOf(t.conversationId);
  const row: TurnOutboxRow = {
    id,
    conversationId: t.conversationId,
    agentId: t.agentId,
    userId: t.userId,
    userRole: t.userRole ?? null,
    model: t.model,
    inputTokens: Math.max(0, Math.round(t.inputTokens)),
    outputTokens: Math.max(0, Math.round(t.outputTokens)),
    ms: Math.max(0, Math.round(t.ms)),
    status: t.status,
    error: t.error,
    toolCalls: t.toolCalls,
    toolErrors: t.toolErrors,
    toolStats: t.toolStats.slice(0, MAX_TOOL_STATS),
    handedOff: t.handedOff,
    turnNumber,
    rating: null,
    ratingNote: null,
    ratingAt: null,
    problemMessage: null,
    createdAt,
  };
  // The person's own words are kept only for a turn that went wrong, only when the builder allowed it (the runtime
  // hands them over only then, and this checks again), and not for a message the app refused before it saved it.
  if (t.userMessage && process.env.FORGE_INSIGHTS_INCLUDE_TEXT === "1" && (t.status !== "blocked" || t.assistantMessageId) && problemOf({ ...row, problemMessage: "x" }, true)) {
    row.problemMessage = t.userMessage.replace(/\s+/g, " ").trim().slice(0, MAX_PROBLEM_CHARS) || null;
  }

  try {
    await db.insert(forgeAgentTurns).values({ ...row, createdAt, ratingAt: null, assistantMessageId: t.assistantMessageId });
  } catch (e) {
    if (!isMissingColumn(e)) throw e;
    // An app updated but not yet migrated: the turn is still kept, with the columns it has.
    sayColumnsMissing();
    await db.insert(forgeAgentTurns).values({
      id,
      conversationId: row.conversationId,
      agentId: row.agentId,
      userId: row.userId,
      model: row.model,
      inputTokens: row.inputTokens,
      outputTokens: row.outputTokens,
      ms: row.ms,
      status: row.status,
      error: row.error,
      toolCalls: row.toolCalls,
      toolErrors: row.toolErrors,
      toolStats: row.toolStats,
      handedOff: row.handedOff,
      assistantMessageId: t.assistantMessageId,
      createdAt,
    });
  }
  insightsShipper().enqueueFrom((cfg) => itemForTurnRow(row, cfg));
}

export const turnStore: TurnStore = {
  record(t) {
    const done = write(t);
    // A host that freezes the process right after the reply waits for this write, then for the send (see chat-route).
    insightsShipper().track(done);
    return done;
  },
};

/**
 * The person's thumbs up (1) or down (-1) on one answer. A second rating REPLACES the first (the note too), so
 * pressing it twice, or changing one's mind, leaves a single answer. Returns how many turns were updated: 0 means
 * no turn was recorded for that answer in that conversation.
 *
 * A rating puts the row back in the outbox, so the platform hears of the change (it replaces the earlier rating).
 */
export async function rateTurn(r: { conversationId: string; messageId: string; rating: 1 | -1; note: string | null }): Promise<number> {
  const ratingAt = new Date();
  const where = and(eq(forgeAgentTurns.conversationId, r.conversationId), eq(forgeAgentTurns.assistantMessageId, r.messageId));
  let rows: Array<{ id: string }>;
  try {
    rows = await db
      .update(forgeAgentTurns)
      .set({ rating: r.rating, ratingNote: r.note, ratingAt, shippedAt: null, shipError: null })
      .where(where)
      .returning({ id: forgeAgentTurns.id });
  } catch (e) {
    if (!isMissingColumn(e)) throw e;
    sayColumnsMissing();
    rows = await db.update(forgeAgentTurns).set({ rating: r.rating, ratingNote: r.note }).where(where).returning({ id: forgeAgentTurns.id });
  }
  for (const row of rows) shipRating({ turnId: row.id, rating: r.rating, note: r.note, ratingAt });
  return rows.length;
}

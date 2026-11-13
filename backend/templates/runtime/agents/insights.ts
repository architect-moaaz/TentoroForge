/**
 * What the app's assistants cost and how they are doing, worked out from the turns they recorded. Forge runtime — do not remove.
 *
 * `buildInsights` is pure: rows in, the report out, so the arithmetic is tested with made-up rows. `fetchInsights` is
 * the part that reads the app's database (and loads it on demand, so this file imports nothing that needs the app).
 * It is read through /api/agent/insights, which only the platform may call (api-agent/insights-route.ts).
 *
 * Privacy: the report carries counts and timings. The only words in it are, for the few turns that went wrong, a
 * short piece (200 characters) of what the person wrote. Never an answer, never a tool's result.
 */

export const NO_TURNS_WARNING = "No turns are recorded yet: apply the agent again and push the database changes.";

const DAY_MS = 86_400_000;
export const SLOW_MS = 30_000;
export const MAX_ROWS = 20_000;
const MAX_PROBLEMS = 15;
const MAX_TOOLS = 20;
const MAX_MESSAGE_CHARS = 200;
const NO_MESSAGE = "(message not available)";

/** A recorded turn as read back from the database. */
export interface TurnRow {
  conversationId: string;
  agentId: string;
  userId: string;
  model: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
  ms: number | null;
  status: string;
  error: string | null;
  toolCalls: number | null;
  toolErrors: number | null;
  toolStats: unknown;
  handedOff: boolean | null;
  assistantMessageId: string | null;
  rating: number | null;
  ratingNote: string | null;
  createdAt: Date | string | null;
}

export interface HandoffRow {
  status: string;
  createdAt: Date | string | null;
  resolvedAt: Date | string | null;
}

/** A message the person wrote: the words behind a turn that went wrong. */
export interface UserMessageRow {
  conversationId: string;
  createdAt: Date | string | null;
  content: string;
}

export type ProblemReason = "error" | "blocked" | "thumbs_down" | "tool_failed" | "handed_off" | "slow";

export interface Problem {
  conversationId: string;
  at: string;
  message: string;
  reason: ProblemReason;
  detail: string;
}

export interface Insights {
  generatedAt: string;
  days: number;
  agentId: string | null;
  since: string;
  firstTurnAt: string | null;
  totals: {
    conversations: number;
    turns: number;
    users: number;
    inputTokens: number;
    outputTokens: number;
    toolCalls: number;
    toolErrors: number;
    blocked: number;
    errors: number;
    handedOff: number;
    rated: number;
    up: number;
    down: number;
  };
  latencyMs: { p50: number; p95: number; avg: number };
  byDay: Array<{ day: string; turns: number; inputTokens: number; outputTokens: number; errors: number; up: number; down: number }>;
  byModel: Array<{ model: string; turns: number; inputTokens: number; outputTokens: number }>;
  tools: Array<{ name: string; calls: number; errors: number; avgMs: number }>;
  problems: Problem[];
  handoffs: { total: number; open: number; claimed: number; resolved: number; avgResolveMinutes: number | null };
  /** Only when nothing can be reported because the turns table is missing. */
  warning?: string;
}

/** 1..90, a whole number; anything that is not a number is the default week. */
export function clampDays(value: unknown): number {
  const n = Math.floor(Number(value));
  if (!Number.isFinite(n) || value === null || value === "" || value === undefined) return 7;
  return Math.min(90, Math.max(1, n));
}

const num = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

const toDate = (v: Date | string | null | undefined): Date | null => {
  if (!v) return null;
  const d = v instanceof Date ? v : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
};

const dayKey = (d: Date): string => d.toISOString().slice(0, 10);

/** The first moment of the window: midnight (UTC) of the first of the `days` calendar days that end today. */
export function windowStart(now: Date, days: number): Date {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) - (days - 1) * DAY_MS);
}

/** Nearest-rank percentile of an ascending list; 0 for none. */
function percentile(sorted: number[], p: number): number {
  if (!sorted.length) return 0;
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1))];
}

interface ToolStat {
  name: string;
  ok: boolean;
  ms: number;
}

function toolStatsOf(row: TurnRow): ToolStat[] {
  if (!Array.isArray(row.toolStats)) return [];
  const out: ToolStat[] = [];
  for (const t of row.toolStats as Array<Record<string, unknown>>) {
    if (t && typeof t.name === "string" && t.name) out.push({ name: t.name, ok: t.ok !== false, ms: num(t.ms) });
  }
  return out;
}

const clip = (text: string, max: number): string => {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
};

/** Why a turn is worth a look, in order of how bad it is, or null when it is not. */
export function reasonOf(row: TurnRow): { reason: ProblemReason; detail: string } | null {
  if (row.status === "error") return { reason: "error", detail: clip(row.error || "The turn failed.", MAX_MESSAGE_CHARS) };
  if (row.status === "blocked") return { reason: "blocked", detail: clip(row.error || "The answer was blocked.", MAX_MESSAGE_CHARS) };
  if (row.rating === -1) {
    return { reason: "thumbs_down", detail: clip(row.ratingNote ? `The person marked it as bad: ${row.ratingNote}` : "The person marked the answer as bad.", MAX_MESSAGE_CHARS) };
  }
  if (row.handedOff) return { reason: "handed_off", detail: "Handed over to a person." };
  if (num(row.toolErrors) > 0) {
    const failed = [...new Set(toolStatsOf(row).filter((t) => !t.ok).map((t) => t.name))];
    return { reason: "tool_failed", detail: failed.length ? `A tool failed: ${failed.join(", ")}.` : `${num(row.toolErrors)} tool call(s) failed.` };
  }
  if (num(row.ms) > SLOW_MS) return { reason: "slow", detail: `It took ${Math.round(num(row.ms) / 1000)} seconds.` };
  return null;
}

/** The turns to show as problems, newest first (the rows are expected newest first already; this does not rely on it). */
export function problemTurns(rows: TurnRow[]): Array<{ row: TurnRow; at: Date; reason: ProblemReason; detail: string }> {
  const found: Array<{ row: TurnRow; at: Date; reason: ProblemReason; detail: string }> = [];
  for (const row of rows) {
    const at = toDate(row.createdAt);
    const why = reasonOf(row);
    if (at && why) found.push({ row, at, ...why });
  }
  return found.sort((a, b) => b.at.getTime() - a.at.getTime()).slice(0, MAX_PROBLEMS);
}

/**
 * The words that started a turn: the person's latest message in that conversation written while the turn ran. The
 * turn is recorded when it ends, so its own message lies between (end - duration) and the end. A message the app
 * refused before saving it has none; nothing earlier is borrowed in its place.
 */
function messageOf(row: TurnRow, at: Date, messages: UserMessageRow[]): string {
  if (row.status === "blocked" && !row.assistantMessageId) return NO_MESSAGE;
  const from = at.getTime() - num(row.ms) - 2000;
  let best: { t: number; text: string } | null = null;
  for (const m of messages) {
    if (m.conversationId !== row.conversationId) continue;
    const t = toDate(m.createdAt)?.getTime();
    if (t === undefined || t < from || t > at.getTime() + 1000) continue;
    if (!best || t > best.t) best = { t, text: m.content };
  }
  return best ? clip(best.text, MAX_MESSAGE_CHARS) || NO_MESSAGE : NO_MESSAGE;
}

export function buildInsights(input: {
  rows: TurnRow[];
  handoffs: HandoffRow[];
  /** The person's messages for the conversations of `problemTurns(rows)`. */
  messages: UserMessageRow[];
  days: number;
  agentId: string | null;
  now: Date;
  firstTurnAt: Date | string | null;
}): Insights {
  const { rows, days, agentId, now } = input;
  const since = windowStart(now, days);
  const sinceMs = since.getTime();

  const byDay = new Map<string, Insights["byDay"][number]>();
  for (let i = 0; i < days; i++) {
    const day = dayKey(new Date(sinceMs + i * DAY_MS));
    byDay.set(day, { day, turns: 0, inputTokens: 0, outputTokens: 0, errors: 0, up: 0, down: 0 });
  }

  const totals = { conversations: 0, turns: 0, users: 0, inputTokens: 0, outputTokens: 0, toolCalls: 0, toolErrors: 0, blocked: 0, errors: 0, handedOff: 0, rated: 0, up: 0, down: 0 };
  const conversations = new Set<string>();
  const users = new Set<string>();
  const latencies: number[] = [];
  const models = new Map<string, { model: string; turns: number; inputTokens: number; outputTokens: number }>();
  const tools = new Map<string, { name: string; calls: number; errors: number; ms: number }>();
  const inRange: TurnRow[] = [];

  for (const row of rows) {
    const at = toDate(row.createdAt);
    if (!at || at.getTime() < sinceMs || at.getTime() > now.getTime() + DAY_MS) continue;
    if (agentId && row.agentId !== agentId) continue;
    inRange.push(row);
    const inTok = num(row.inputTokens);
    const outTok = num(row.outputTokens);
    totals.turns++;
    totals.inputTokens += inTok;
    totals.outputTokens += outTok;
    totals.toolCalls += num(row.toolCalls);
    totals.toolErrors += num(row.toolErrors);
    if (row.status === "blocked") totals.blocked++;
    if (row.status === "error") totals.errors++;
    if (row.handedOff) totals.handedOff++;
    if (row.rating === 1 || row.rating === -1) {
      totals.rated++;
      if (row.rating === 1) totals.up++;
      else totals.down++;
    }
    if (row.conversationId) conversations.add(row.conversationId);
    if (row.userId) users.add(row.userId);
    latencies.push(num(row.ms));

    const day = byDay.get(dayKey(at));
    if (day) {
      day.turns++;
      day.inputTokens += inTok;
      day.outputTokens += outTok;
      if (row.status === "error") day.errors++;
      if (row.rating === 1) day.up++;
      if (row.rating === -1) day.down++;
    }

    const modelName = row.model || "unknown";
    const m = models.get(modelName) ?? { model: modelName, turns: 0, inputTokens: 0, outputTokens: 0 };
    m.turns++;
    m.inputTokens += inTok;
    m.outputTokens += outTok;
    models.set(modelName, m);

    for (const t of toolStatsOf(row)) {
      const s = tools.get(t.name) ?? { name: t.name, calls: 0, errors: 0, ms: 0 };
      s.calls++;
      if (!t.ok) s.errors++;
      s.ms += t.ms;
      tools.set(t.name, s);
    }
  }
  totals.conversations = conversations.size;
  totals.users = users.size;

  latencies.sort((a, b) => a - b);
  const avg = latencies.length ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length) : 0;

  const problems: Problem[] = problemTurns(inRange).map(({ row, at, reason, detail }) => ({
    conversationId: row.conversationId,
    at: at.toISOString(),
    message: messageOf(row, at, input.messages),
    reason,
    detail,
  }));

  const hand = { total: 0, open: 0, claimed: 0, resolved: 0, avgResolveMinutes: null as number | null };
  let resolveMs = 0;
  let resolvedWithTimes = 0;
  for (const h of input.handoffs) {
    const made = toDate(h.createdAt);
    if (!made || made.getTime() < sinceMs) continue;
    hand.total++;
    if (h.status === "resolved") {
      hand.resolved++;
      const done = toDate(h.resolvedAt);
      if (done && done.getTime() >= made.getTime()) {
        resolveMs += done.getTime() - made.getTime();
        resolvedWithTimes++;
      }
    } else if (h.status === "claimed") hand.claimed++;
    else hand.open++;
  }
  if (resolvedWithTimes) hand.avgResolveMinutes = Math.round((resolveMs / resolvedWithTimes / 60_000) * 10) / 10;

  return {
    generatedAt: now.toISOString(),
    days,
    agentId,
    since: since.toISOString(),
    firstTurnAt: toDate(input.firstTurnAt)?.toISOString() ?? null,
    totals,
    latencyMs: { p50: percentile(latencies, 50), p95: percentile(latencies, 95), avg },
    byDay: [...byDay.values()],
    byModel: [...models.values()].sort((a, b) => b.turns - a.turns || a.model.localeCompare(b.model)),
    tools: [...tools.values()]
      .sort((a, b) => b.calls - a.calls || a.name.localeCompare(b.name))
      .slice(0, MAX_TOOLS)
      .map((t) => ({ name: t.name, calls: t.calls, errors: t.errors, avgMs: Math.round(t.ms / t.calls) })),
    problems,
    handoffs: hand,
  };
}

/** The same report with nothing in it, and the reason. */
export function emptyInsights(opts: { days: number; agentId: string | null; now: Date; warning?: string }): Insights {
  const out = buildInsights({ rows: [], handoffs: [], messages: [], days: opts.days, agentId: opts.agentId, now: opts.now, firstTurnAt: null });
  return opts.warning ? { ...out, warning: opts.warning } : out;
}

/** Is this the database saying the table is not there (an app that was updated but whose schema was not pushed)? */
export function isMissingTable(e: unknown): boolean {
  const err = e as { code?: unknown; message?: unknown; cause?: { code?: unknown; message?: unknown } } | null;
  const codes = [err?.code, err?.cause?.code];
  if (codes.includes("42P01")) return true;
  const text = `${err?.message ?? ""} ${err?.cause?.message ?? ""}`;
  return /relation .*forge_agent_turns.* does not exist/i.test(text);
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Read the turns (and the handoffs, and the words behind the problems) from the app's database and report on them. */
export async function fetchInsights(opts: { days?: unknown; agentId?: string | null; now?: Date }): Promise<Insights> {
  const days = clampDays(opts.days);
  const agentId = opts.agentId?.trim() ? opts.agentId.trim().slice(0, 64) : null;
  const now = opts.now ?? new Date();
  const since = windowStart(now, days);

  const { db } = await import("@/db");
  const { forgeAgentTurns } = await import("@/db/schema/_forge_agent_turns");
  const { and, desc, eq, gte, inArray, min } = await import("drizzle-orm");

  let rows: TurnRow[];
  let firstTurnAt: Date | string | null = null;
  try {
    const inWindow = agentId ? and(gte(forgeAgentTurns.createdAt, since), eq(forgeAgentTurns.agentId, agentId)) : gte(forgeAgentTurns.createdAt, since);
    // Named columns, not `select()`: the columns the platform's insights added (outbox, role, ...) are not needed here, and
    // an app updated but not yet pushed does not have them, which must not take this view down.
    const t = forgeAgentTurns;
    rows = (await db
      .select({
        conversationId: t.conversationId, agentId: t.agentId, userId: t.userId, model: t.model, inputTokens: t.inputTokens,
        outputTokens: t.outputTokens, ms: t.ms, status: t.status, error: t.error, toolCalls: t.toolCalls, toolErrors: t.toolErrors,
        toolStats: t.toolStats, handedOff: t.handedOff, assistantMessageId: t.assistantMessageId, rating: t.rating,
        ratingNote: t.ratingNote, createdAt: t.createdAt,
      })
      .from(t)
      .where(inWindow)
      .orderBy(desc(t.createdAt))
      .limit(MAX_ROWS)) as TurnRow[];
    const first = await db
      .select({ at: min(forgeAgentTurns.createdAt) })
      .from(forgeAgentTurns)
      .where(agentId ? eq(forgeAgentTurns.agentId, agentId) : undefined);
    firstTurnAt = (first[0]?.at as Date | string | null | undefined) ?? null;
  } catch (e) {
    if (isMissingTable(e)) return emptyInsights({ days, agentId, now, warning: NO_TURNS_WARNING });
    throw e;
  }

  // Handoffs in the range. A missing handoff table (not pushed yet) reads as "none", not as a failure.
  let handoffs: HandoffRow[] = [];
  try {
    const { forgeAgentHandoffs } = await import("@/db/schema/_forge_agent_handoffs");
    const where = agentId ? and(gte(forgeAgentHandoffs.createdAt, since), eq(forgeAgentHandoffs.agentId, agentId)) : gte(forgeAgentHandoffs.createdAt, since);
    handoffs = (await db
      .select({ status: forgeAgentHandoffs.status, createdAt: forgeAgentHandoffs.createdAt, resolvedAt: forgeAgentHandoffs.resolvedAt })
      .from(forgeAgentHandoffs)
      .where(where)
      .limit(MAX_ROWS)) as HandoffRow[];
  } catch {
    /* no handoffs to count */
  }

  // The words behind the turns worth a look: only what the person wrote, only for those conversations.
  let messages: UserMessageRow[] = [];
  const ids = [...new Set(problemTurns(rows.filter((r) => !agentId || r.agentId === agentId)).map((p) => p.row.conversationId).filter((id) => UUID.test(id)))];
  if (ids.length) {
    try {
      const { forgeAgentMessages } = await import("@/db/schema/_forge_agent");
      messages = (await db
        .select({ conversationId: forgeAgentMessages.conversationId, createdAt: forgeAgentMessages.createdAt, content: forgeAgentMessages.content })
        .from(forgeAgentMessages)
        .where(and(inArray(forgeAgentMessages.conversationId, ids), eq(forgeAgentMessages.role, "user"), gte(forgeAgentMessages.createdAt, new Date(since.getTime() - DAY_MS))))
        .limit(5000)) as UserMessageRow[];
    } catch {
      /* the problems are listed without the words */
    }
  }

  return buildInsights({ rows, handoffs, messages, days, agentId, now, firstTurnAt });
}

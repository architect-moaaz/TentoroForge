/**
 * Sending every assistant turn to the TentoroForge platform, so the builder's Insights page can count ALL of the
 * app's people, not a sample. Forge runtime — do not remove.
 *
 * The pieces, in the order a turn meets them:
 *   1. the turn is written to the app's own database first (agents/turns-store.ts: that row is the OUTBOX);
 *   2. an event built from the row waits in a small in-memory queue (`enqueue`);
 *   3. the queue is sent as ONE request when 100 events are waiting or 1 second has passed, whichever is first;
 *   4. the platform answers 202 and the row is marked sent; any other answer leaves the row waiting.
 * Rows that were not sent (the platform was down, the app crashed, the process froze) are sent later by the cron
 * tick (agents/insights-outbox.ts), oldest first. Sending is at-least-once and the platform ignores a repeated event
 * id, so a repeat never counts twice.
 *
 * THE CHAT NEVER WAITS FOR THIS, AND NEVER FAILS BECAUSE OF IT. Nothing here throws to a caller; every outside
 * call (the network, the database) is timed and caught; a slow or silent platform costs the chat nothing.
 *
 * WHAT LEAVES THE APP. Counts, timings, tool NAMES and a salted hash of the person (never their id or email), their
 * role name, and the conversation's id. No message text, no tool inputs or results. The one exception is the
 * first 200 characters of what the person wrote in a turn that went wrong, and only when the builder switched
 * FORGE_INSIGHTS_INCLUDE_TEXT on. The format is fixed by the platform's ingest (POST /api/insights/ingest).
 *
 * Everything outside (the network, the clock, timers, the database) arrives as `ShipperDeps`, so all of this runs in
 * tests against fakes. Nothing here imports the app.
 */
import { createHmac } from "node:crypto";
import { gzip as gzipCallback } from "node:zlib";
import { SLOW_MS } from "./insights";

// ── the limits the platform's ingest sets ─────────────────────────────────

export const SCHEMA_VERSION = 1;
/** One request never carries more than this many events, nor more than this many bytes of JSON. */
export const MAX_EVENTS_PER_REQUEST = 500;
export const MAX_BYTES_PER_REQUEST = 1_000_000;
/** Send when this many events are waiting, or this long after the first one started waiting. */
export const FLUSH_AT_EVENTS = 100;
export const FLUSH_AFTER_MS = 1000;
/** A request that has not finished by now counts as failed. */
export const REQUEST_TIMEOUT_MS = 3000;
/** Bodies larger than this are gzipped. */
export const GZIP_OVER_BYTES = 1024;
/** The queue in memory is bounded. What does not fit is still in the database and is sent by the tick. */
export const QUEUE_LIMIT = 5000;
export const BACKOFF_FIRST_MS = 1000;
export const BACKOFF_MAX_MS = 60_000;
/** A Retry-After longer than this is not believed in full. */
const RETRY_AFTER_MAX_MS = 10 * 60_000;
/** The platform refuses events older than 90 days; one a day short of that is not sent at all. */
export const MAX_EVENT_AGE_MS = 89 * 86_400_000;
/** One bad request is split in halves to find the bad event; at most this many extra requests per send. */
const BISECT_BUDGET = 60;
const MAX_REFUSALS_BEFORE_ACCEPT = 4;

/** What one send has seen so far. */
interface SendTally {
  done: number;
  accepted: boolean;
  refusedAlone: number;
}

const MAX_TOOLS = 20;
const encoder = new TextEncoder();

// ── what is sent ──────────────────────────────────────────────────────────

export type ProblemReason = "error" | "blocked" | "tool_failed" | "handed_off" | "slow" | "thumbs_down";

export interface TurnEvent {
  type: "turn";
  id: string;
  at: string;
  agentId: string;
  conversationId: string;
  userKey: string;
  role: string | null;
  env: "production" | "development";
  model: string | null;
  inputTokens: number;
  outputTokens: number;
  ms: number;
  status: "ok" | "error" | "blocked";
  toolCalls: number;
  toolErrors: number;
  tools: Array<{ name: string; ok: boolean; ms: number }>;
  handedOff: boolean;
  turnNumber: number;
  problem: null | { reason: ProblemReason; message: string | null; detail: string | null };
}

export interface RatingEvent {
  type: "rating";
  id: string;
  at: string;
  turnId: string;
  rating: 1 | -1;
  note: string | null;
}

export interface HandoffEvent {
  type: "handoff";
  id: string;
  at: string;
  agentId: string;
  conversationId: string;
  status: "open" | "claimed" | "resolved";
  resolveMinutes: number | null;
}

export type InsightEvent = TurnEvent | RatingEvent | HandoffEvent;

/** A turn as it sits in forge_agent_turns (the outbox). Every number may be empty on an old row. */
export interface TurnOutboxRow {
  id: string;
  conversationId: string;
  agentId: string;
  userId: string;
  userRole?: string | null;
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
  turnNumber?: number | null;
  rating?: number | null;
  ratingNote?: string | null;
  ratingAt?: Date | string | null;
  problemMessage?: string | null;
  createdAt: Date | string | null;
}

/** A handoff as the handoff store reads it. */
export interface HandoffOutboxRow {
  id: string;
  conversationId: string;
  agentId: string;
  status: string;
  createdAt: Date | string | null;
  claimedAt?: Date | string | null;
  resolvedAt?: Date | string | null;
}

// ── settings, from the environment ────────────────────────────────────────

export interface ShipperConfig {
  /** The platform's ingest address. */
  url: string;
  /** Sent as `Authorization: Bearer <key>`. Never logged. */
  key: string;
  /** Mixed into every person's hash so two apps never produce the same hash for the same person. */
  salt: string;
  /** Whether the first 200 characters of what the person wrote may go with a turn that went wrong. */
  includeText: boolean;
  env: "production" | "development";
}

type Env = Record<string, string | undefined>;

/** The settings, or why shipping is off. `reason` is a short sentence for the one log line. */
export function readConfig(env: Env): { config: ShipperConfig | null; reason: string | null } {
  const url = (env.FORGE_INSIGHTS_URL ?? "").trim();
  const key = (env.FORGE_INSIGHTS_KEY ?? "").trim();
  const salt = (env.FORGE_INSIGHTS_USER_SALT ?? "").trim();
  if (!url || !key) return { config: null, reason: "this app is not connected to the platform's insights (FORGE_INSIGHTS_URL and FORGE_INSIGHTS_KEY are not set)" };
  if (!/^https?:\/\//i.test(url)) return { config: null, reason: "FORGE_INSIGHTS_URL is not a web address" };
  if (!salt) return { config: null, reason: "FORGE_INSIGHTS_USER_SALT is not set, so people cannot be hashed and nothing is sent (apply the agent again to create it)" };
  return {
    config: {
      url,
      key,
      salt,
      includeText: env.FORGE_INSIGHTS_INCLUDE_TEXT === "1",
      env: env.NODE_ENV === "production" ? "production" : "development",
    },
    reason: null,
  };
}

// ── building events (pure) ────────────────────────────────────────────────

const clip = (text: string, max: number): string => (text.length > max ? text.slice(0, max) : text);
const flat = (text: string): string => text.replace(/\s+/g, " ").trim();
const count = (v: unknown): number => {
  const n = Math.round(Number(v));
  return Number.isFinite(n) && n > 0 ? n : 0;
};
function isoOf(v: Date | string | number | null | undefined): string | null {
  if (v === null || v === undefined || v === "") return null;
  const d = v instanceof Date ? v : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/**
 * The person as the platform sees them: the first 24 hex characters of HMAC-SHA256(salt, id). The same person always
 * gets the same key in the same app, nobody can get the id back from it, and the same id in another app (another
 * salt) gives a different key. An anonymous visitor has no id of their own, so each conversation is one visitor.
 */
export function userKeyOf(salt: string, row: { userId: string; conversationId: string }): string {
  const who = row.userId === "anonymous" ? `anonymous:${row.conversationId || "none"}` : row.userId;
  return createHmac("sha256", salt).update(who).digest("hex").slice(0, 24);
}

function toolsOf(stats: unknown): TurnEvent["tools"] {
  if (!Array.isArray(stats)) return [];
  const out: TurnEvent["tools"] = [];
  for (const t of stats as Array<Record<string, unknown>>) {
    if (out.length >= MAX_TOOLS) break;
    if (t && typeof t.name === "string" && t.name) out.push({ name: clip(t.name, 80), ok: t.ok !== false, ms: count(t.ms) });
  }
  return out;
}

/**
 * Why a turn is worth a look, in order of how bad it is, or null. The words are generic sentences unless the builder
 * allowed text: an error's own message can carry a value out of the database, so it is not sent by default.
 */
export function problemOf(row: TurnOutboxRow, includeText: boolean): TurnEvent["problem"] {
  const tools = toolsOf(row.toolStats);
  const say = (reason: ProblemReason, plain: string, withText?: string | null): NonNullable<TurnEvent["problem"]> => ({
    reason,
    message: includeText && row.problemMessage ? clip(flat(row.problemMessage), 200) || null : null,
    detail: clip(includeText && withText ? flat(withText) || plain : plain, 200),
  });
  if (row.status === "error") return say("error", "The turn failed.", row.error);
  if (row.status === "blocked") return say("blocked", "The answer was blocked.", row.error);
  if (row.rating === -1) return say("thumbs_down", "The person marked the answer as bad.", row.ratingNote ? `The person marked it as bad: ${row.ratingNote}` : null);
  if (row.handedOff) return say("handed_off", "Handed over to a person.");
  if (count(row.toolErrors) > 0) {
    const failed = [...new Set(tools.filter((t) => !t.ok).map((t) => t.name))];
    return say("tool_failed", failed.length ? `A tool failed: ${failed.join(", ")}.` : `${count(row.toolErrors)} tool call(s) failed.`);
  }
  if (count(row.ms) > SLOW_MS) return say("slow", `It took ${Math.round(count(row.ms) / 1000)} seconds.`);
  return null;
}

/** The turn as the platform wants it, or null when the row is too broken to say anything true (no id, no time). */
export function buildTurnEvent(row: TurnOutboxRow, cfg: Pick<ShipperConfig, "salt" | "includeText" | "env">): TurnEvent | null {
  const at = isoOf(row.createdAt);
  if (!row.id || !at) return null;
  const status = row.status === "error" || row.status === "blocked" ? row.status : "ok";
  return {
    type: "turn",
    id: row.id,
    at,
    agentId: clip(row.agentId || "unknown", 80),
    conversationId: clip(row.conversationId || "none", 64),
    userKey: userKeyOf(cfg.salt, row),
    role: row.userRole ? clip(String(row.userRole), 60) : null,
    env: cfg.env,
    model: row.model ? clip(row.model, 100) : null,
    inputTokens: count(row.inputTokens),
    outputTokens: count(row.outputTokens),
    ms: count(row.ms),
    status,
    toolCalls: count(row.toolCalls),
    toolErrors: count(row.toolErrors),
    tools: toolsOf(row.toolStats),
    handedOff: !!row.handedOff,
    turnNumber: Math.max(1, count(row.turnNumber)),
    problem: problemOf(row, cfg.includeText),
  };
}

/** One rating. Its id carries the moment it was given, so a changed mind is a NEW event for the same turn. */
export function buildRatingEvent(
  r: { turnId: string; rating: number | null | undefined; note: string | null | undefined; ratingAt: Date | string | null | undefined },
  cfg: Pick<ShipperConfig, "includeText">,
): RatingEvent | null {
  const at = isoOf(r.ratingAt);
  if (!r.turnId || !at || (r.rating !== 1 && r.rating !== -1)) return null;
  // The note is something the person typed, so it follows the same rule as the words of a problem.
  const note = cfg.includeText && r.note ? clip(flat(r.note), 300) || null : null;
  return { type: "rating", id: clip(`rt_${r.turnId}_${new Date(at).getTime()}`, 64), at, turnId: r.turnId, rating: r.rating, note };
}

/** One change of a handoff's status. The id names the status and the moment, so the same change is never counted twice. */
export function buildHandoffEvent(h: HandoffOutboxRow): HandoffEvent | null {
  const status = h.status === "claimed" || h.status === "resolved" ? h.status : "open";
  const made = isoOf(h.createdAt);
  const at = status === "resolved" ? isoOf(h.resolvedAt) : status === "claimed" ? isoOf(h.claimedAt) : made;
  if (!h.id || !at || !made) return null;
  let resolveMinutes: number | null = null;
  if (status === "resolved") {
    const span = new Date(at).getTime() - new Date(made).getTime();
    resolveMinutes = span >= 0 ? Math.round((span / 60_000) * 10) / 10 : null;
  }
  return {
    type: "handoff",
    id: clip(`ho_${h.id}_${status}_${new Date(at).getTime()}`, 64),
    at,
    agentId: clip(h.agentId || "unknown", 80),
    conversationId: clip(h.conversationId || "none", 64),
    status,
    resolveMinutes,
  };
}

// ── the work list ─────────────────────────────────────────────────────────

/**
 * What goes out for one database row. A turn row sends its turn event and, when the person rated it, the rating.
 * `ratingAt` is the row's `rating_at` (ms) as it was when the item was made, empty when it was never rated: marking
 * the row sent only happens if it still has that value, so a rating that arrived meanwhile keeps the row waiting.
 */
export interface OutboxItem {
  kind: "turn" | "handoff";
  rowId: string;
  ratingAt?: number | null;
  events: InsightEvent[];
}

/**
 * The turn row's item: the turn, and its rating if it has one. Null when there is nothing true to send. A rating
 * given before the row had a `rating_at` is sent as given when the turn was.
 */
export function itemForTurnRow(row: TurnOutboxRow, cfg: Pick<ShipperConfig, "salt" | "includeText" | "env">): OutboxItem | null {
  const turn = buildTurnEvent(row, cfg);
  if (!turn) return null;
  const rating = row.rating ? buildRatingEvent({ turnId: row.id, rating: row.rating, note: row.ratingNote, ratingAt: row.ratingAt ?? row.createdAt }, cfg) : null;
  const ratedAt = isoOf(row.ratingAt);
  return { kind: "turn", rowId: row.id, ratingAt: ratedAt ? new Date(ratedAt).getTime() : null, events: rating ? [turn, rating] : [turn] };
}

export function itemForHandoff(h: HandoffOutboxRow): OutboxItem | null {
  const ev = buildHandoffEvent(h);
  return ev ? { kind: "handoff", rowId: h.id, events: [ev] } : null;
}

/** Marks the database rows. Every call may fail (no database, column not there yet): the shipper only notes it. */
export interface OutboxStore {
  markShipped(items: OutboxItem[]): Promise<void>;
  /** The platform will never take these: closed with a reason, not retried. */
  markRejected(items: OutboxItem[], reason: string): Promise<void>;
  /** Sending failed for a reason worth retrying: count it and keep the reason. */
  markFailed(items: OutboxItem[], reason: string): Promise<void>;
}

export interface ShipperDeps {
  env: Env;
  fetch: (url: string, init: any) => Promise<{ status: number; headers: { get(name: string): string | null }; text(): Promise<string> }>;
  store: OutboxStore;
  now?: () => number;
  /** Runs `fn` after `ms`; returns how to cancel it. The real one does not keep the process alive. */
  setTimer?: (fn: () => void, ms: number) => () => void;
  random?: () => number;
  /** One line to the log. */
  log?: (line: string) => void;
  gzip?: (data: Uint8Array) => Promise<Uint8Array>;
}

export interface SendResult {
  /** Items the platform took (or refused for good: those are closed too). */
  done: number;
  /** Items left for later: the platform was not reachable or asked to slow down. */
  deferred: number;
  /** Set when sending stopped on a failure: do not try again before then. */
  backoffMs: number | null;
}

export interface Shipper {
  /** False when the app has no ingest address, key or salt: everything below does nothing. */
  configured(): boolean;
  readonly config: ShipperConfig | null;
  /** Put an item in the queue. Never throws, never waits. */
  enqueue(item: OutboxItem): void;
  /** The same, building the item from the settings; when the app is not set up this only says so (once) and builds nothing. */
  enqueueFrom(make: (cfg: ShipperConfig) => OutboxItem | null): void;
  /** Send what is queued, now. Never throws. */
  flush(): Promise<void>;
  /** Send these items (the cron tick's catch-up). Respects a backoff in force. Never throws. */
  send(items: OutboxItem[]): Promise<SendResult>;
  /** Remember a write that is in flight, so `settle` can wait for it. */
  track(p: Promise<unknown>): void;
  /** Wait for the writes that are in flight, then send the queue. Never throws. */
  settle(): Promise<void>;
  stats(): { queued: number; failures: number; backoffUntil: number };
}

type Outcome =
  | { kind: "ok"; rejected: Map<number, string> }
  | { kind: "retry"; reason: string; retryAfterMs: number | null }
  | { kind: "bad"; reason: string };

const defaultGzip = (data: Uint8Array): Promise<Uint8Array> =>
  new Promise((resolve, reject) => gzipCallback(data, (err, out) => (err ? reject(err) : resolve(out))));

function defaultTimer(fn: () => void, ms: number): () => void {
  const t = setTimeout(fn, ms);
  (t as { unref?: () => void }).unref?.();
  return () => clearTimeout(t);
}

/** Retry-After is a number of seconds or a date. */
function retryAfterMs(value: string | null, now: number): number | null {
  if (!value) return null;
  const secs = Number(value);
  if (Number.isFinite(secs) && secs >= 0) return Math.min(RETRY_AFTER_MAX_MS, secs * 1000);
  const at = Date.parse(value);
  return Number.isNaN(at) ? null : Math.min(RETRY_AFTER_MAX_MS, Math.max(0, at - now));
}

export function createShipper(deps: ShipperDeps): Shipper {
  const now = deps.now ?? Date.now;
  const setTimer = deps.setTimer ?? defaultTimer;
  const random = deps.random ?? Math.random;
  const gzip = deps.gzip ?? defaultGzip;
  const say = (line: string) => {
    try {
      (deps.log ?? ((l: string) => console.warn(l)))(line);
    } catch {
      /* a broken logger is not the chat's problem either */
    }
  };
  const { config, reason: offReason } = readConfig(deps.env);

  const queue: OutboxItem[] = [];
  const inFlight = new Set<Promise<unknown>>();
  let cancelTimer: (() => void) | null = null;
  let running: Promise<void> | null = null;
  let again = false;
  let failures = 0;
  let backoffUntil = 0;
  let toldOff = false;
  let toldDown = false;
  let toldFull = false;
  let toldAuth = false;

  const inBackoff = () => backoffUntil > now();

  // The mark-the-row calls: the database may be down or missing a column, and that is never the chat's problem.
  const mark = async (what: () => Promise<void>) => {
    try {
      await what();
    } catch {
      /* the row simply stays as it was and is sent again by the tick */
    }
  };

  const armTimer = (ms: number) => {
    if (cancelTimer) return;
    cancelTimer = setTimer(() => {
      cancelTimer = null;
      void flush();
    }, Math.max(0, ms));
  };
  const disarmTimer = () => {
    cancelTimer?.();
    cancelTimer = null;
  };

  /** A failed request: wait a little longer each time, with jitter, and never less than the platform asked. */
  function backOff(asked: number | null): number {
    failures++;
    const base = Math.min(BACKOFF_MAX_MS, BACKOFF_FIRST_MS * 2 ** (failures - 1));
    const waited = Math.round(base * (0.5 + random() * 0.5));
    const ms = Math.max(waited, asked ?? 0);
    backoffUntil = now() + ms;
    return ms;
  }
  function recovered() {
    if (toldDown) say("[insights] the platform is reachable again; waiting turns are being sent.");
    failures = 0;
    backoffUntil = 0;
    toldDown = false;
    toldAuth = false;
  }

  // ── one request ─────────────────────────────────────────────────────────

  async function post(events: InsightEvent[]): Promise<Outcome> {
    if (!config) return { kind: "retry", reason: "not configured", retryAfterMs: null };
    let body: Uint8Array = encoder.encode(JSON.stringify({ schema: SCHEMA_VERSION, events }));
    const headers: Record<string, string> = {
      "content-type": "application/json",
      authorization: `Bearer ${config.key}`,
      "user-agent": "forge-app-insights/1",
    };
    try {
      if (body.byteLength > GZIP_OVER_BYTES) {
        body = await gzip(body);
        headers["content-encoding"] = "gzip";
      }
    } catch {
      /* sent as it is */
    }

    const controller = new AbortController();
    let cancel = () => {};
    const timedOut = new Promise<"timeout">((resolve) => {
      cancel = setTimer(() => {
        controller.abort();
        resolve("timeout");
      }, REQUEST_TIMEOUT_MS);
    });
    try {
      const exchange = (async () => {
        const res = await deps.fetch(config.url, { method: "POST", headers, body, signal: controller.signal, redirect: "error" });
        const text = res.status >= 200 && res.status < 300 ? await res.text() : "";
        return { status: res.status, retryAfter: res.headers.get("retry-after"), text };
      })();
      const got = await Promise.race([exchange, timedOut]);
      if (got === "timeout") {
        exchange.catch(() => {});
        return { kind: "retry", reason: "the platform did not answer in time", retryAfterMs: null };
      }
      if (got.status >= 200 && got.status < 300) return { kind: "ok", rejected: rejectedOf(got.text) };
      if (got.status === 429) return { kind: "retry", reason: "the platform asked to slow down (429)", retryAfterMs: retryAfterMs(got.retryAfter, now()) };
      // The key was not accepted, or the address is wrong: nothing about the events themselves, and a builder fixing
      // the setting must find every waiting turn still there. So it is waited out like an outage.
      if (got.status === 401 || got.status === 403 || got.status === 404 || got.status === 408 || got.status >= 500) {
        if ((got.status === 401 || got.status === 403 || got.status === 404) && !toldAuth) {
          toldAuth = true;
          say(`[insights] the platform answered ${got.status}: check FORGE_INSIGHTS_URL and FORGE_INSIGHTS_KEY. Turns are kept in the app's database and sent once it is fixed.`);
        }
        return { kind: "retry", reason: `the platform answered ${got.status}`, retryAfterMs: retryAfterMs(got.retryAfter, now()) };
      }
      return { kind: "bad", reason: `the platform refused the batch (${got.status})` };
    } catch (e) {
      return { kind: "retry", reason: `could not reach the platform (${(e instanceof Error ? e.name : "error").slice(0, 40)})`, retryAfterMs: null };
    } finally {
      cancel();
    }
  }

  /** The 202 answer lists the events it refused: `{ rejected: [{ index, reason }] }`. */
  function rejectedOf(text: string): Map<number, string> {
    const out = new Map<number, string>();
    try {
      const list = (JSON.parse(text) as { rejected?: unknown })?.rejected;
      if (Array.isArray(list)) {
        for (const r of list as Array<{ index?: unknown; reason?: unknown }>) {
          if (typeof r?.index === "number") out.set(r.index, typeof r.reason === "string" ? clip(r.reason, 120) : "refused");
        }
      }
    } catch {
      /* an answer that is not JSON still means "taken" */
    }
    return out;
  }

  // ── a chunk of items: one request, split to find a bad event ────────────

  /** How many of these items fit one request (at least one). */
  function fit(items: OutboxItem[]): number {
    let events = 0;
    let bytes = 64;
    let n = 0;
    for (const item of items) {
      const size = item.events.reduce((a, e) => a + encoder.encode(JSON.stringify(e)).byteLength + 1, 0);
      if (n > 0 && (events + item.events.length > MAX_EVENTS_PER_REQUEST || bytes + size > MAX_BYTES_PER_REQUEST)) break;
      events += item.events.length;
      bytes += size;
      n++;
    }
    return n;
  }

  /** Sends one chunk. Returns the items that must be tried again later (empty when all were settled). */
  async function sendChunk(items: OutboxItem[], budget: { left: number }, out: SendTally): Promise<OutboxItem[]> {
    const events = items.flatMap((i) => i.events);
    const owner = items.flatMap((item, idx) => item.events.map(() => idx));
    const outcome = await post(events);
    if (outcome.kind === "ok") {
      const refused = new Map<number, string>();
      for (const [eventIdx, why] of outcome.rejected) if (owner[eventIdx] !== undefined) refused.set(owner[eventIdx], why);
      const accepted = items.filter((_, idx) => !refused.has(idx));
      const closed = items.filter((_, idx) => refused.has(idx));
      if (accepted.length) await mark(() => deps.store.markShipped(accepted));
      for (const item of closed) await mark(() => deps.store.markRejected([item], `refused: ${refused.get(items.indexOf(item))}`));
      out.done += items.length;
      out.accepted = true;
      recovered();
      return [];
    }
    if (outcome.kind === "retry") {
      await mark(() => deps.store.markFailed(items, outcome.reason));
      if (!toldDown) {
        toldDown = true;
        say(`[insights] ${outcome.reason}; turns stay in the app's database and are sent later. The chat is not affected.`);
      }
      backOff(outcome.retryAfterMs);
      return items;
    }
    // The platform refused this batch. One bad event must not hold up the rest: split it until the bad one is alone.
    if (items.length === 1) {
      // Four refusals in a row with nothing accepted in between is the platform objecting to everything (a setting, a
      // version), not to these events: they wait, instead of being closed one by one.
      if (!out.accepted && ++out.refusedAlone > MAX_REFUSALS_BEFORE_ACCEPT) {
        await mark(() => deps.store.markFailed(items, outcome.reason));
        backOff(null);
        return items;
      }
      await mark(() => deps.store.markRejected(items, outcome.reason));
      out.done += 1;
      return [];
    }
    if (budget.left <= 0) {
      await mark(() => deps.store.markFailed(items, "could not tell which event the platform refused"));
      backOff(null);
      return items;
    }
    budget.left--;
    const mid = items.length >> 1;
    const first = await sendChunk(items.slice(0, mid), budget, out);
    if (first.length || inBackoff()) return [...first, ...items.slice(mid)];
    return sendChunk(items.slice(mid), budget, out);
  }

  /** Sends items in request-sized chunks until all are settled or a failure says to wait. Returns what was left. */
  async function sendAll(items: OutboxItem[], out: SendTally): Promise<OutboxItem[]> {
    const budget = { left: BISECT_BUDGET };
    let rest = items;
    while (rest.length && !inBackoff()) {
      const n = fit(rest);
      const chunk = rest.slice(0, n);
      const left = await sendChunk(chunk, budget, out);
      rest = rest.slice(n);
      if (left.length) return [...left, ...rest];
    }
    return rest;
  }

  // ── the queue ───────────────────────────────────────────────────────────

  async function drain(): Promise<void> {
    while (queue.length && !inBackoff()) {
      const batch = queue.splice(0, queue.length);
      const out: SendTally = { done: 0, accepted: false, refusedAlone: 0 };
      const left = await sendAll(batch, out);
      // What was not settled goes back to the FRONT, ahead of anything that arrived meanwhile.
      if (left.length) queue.unshift(...left);
    }
    if (queue.length) armTimer(backoffUntil - now());
  }

  function flush(): Promise<void> {
    if (!config) return Promise.resolve();
    if (running) {
      again = true;
      return running;
    }
    disarmTimer();
    running = (async () => {
      try {
        do {
          again = false;
          await drain();
        } while (again && queue.length && !inBackoff());
      } catch {
        /* nothing here may throw into a chat */
      } finally {
        running = null;
        if (queue.length && !cancelTimer) armTimer(inBackoff() ? backoffUntil - now() : FLUSH_AFTER_MS);
      }
    })();
    return running;
  }

  function noteOff() {
    if (toldOff) return;
    toldOff = true;
    say(`[insights] not sending turns to the platform: ${offReason}. They are kept in the app's database.`);
  }

  function enqueue(item: OutboxItem) {
    try {
      if (!config) return noteOff();
      if (queue.length >= QUEUE_LIMIT) {
        // Nothing is lost: the row is in the database, and the tick sends it. Memory is what is protected here.
        if (!toldFull) {
          toldFull = true;
          say("[insights] too many turns are waiting to be sent; the rest are kept in the app's database and sent later.");
        }
        return;
      }
      toldFull = false;
      queue.push(item);
      if (queue.length >= FLUSH_AT_EVENTS && !inBackoff()) void flush();
      else if (!cancelTimer) armTimer(inBackoff() ? backoffUntil - now() : FLUSH_AFTER_MS);
    } catch {
      /* never into a chat */
    }
  }

  return {
    configured: () => !!config,
    config,

    enqueue,

    enqueueFrom(make) {
      try {
        if (!config) return noteOff();
        const item = make(config);
        if (item) enqueue(item);
      } catch {
        /* never into a chat */
      }
    },

    flush,

    async send(items) {
      if (!config || !items.length) return { done: 0, deferred: items.length, backoffMs: null };
      try {
        if (inBackoff()) return { done: 0, deferred: items.length, backoffMs: backoffUntil - now() };
        const out: SendTally = { done: 0, accepted: false, refusedAlone: 0 };
        const left = await sendAll(items, out);
        return { done: out.done, deferred: left.length, backoffMs: inBackoff() ? backoffUntil - now() : null };
      } catch {
        return { done: 0, deferred: items.length, backoffMs: null };
      }
    },

    track(p) {
      const guarded = Promise.resolve(p).then(
        () => {},
        () => {},
      );
      inFlight.add(guarded);
      void guarded.then(() => inFlight.delete(guarded));
    },

    async settle() {
      try {
        await Promise.all([...inFlight]);
        await flush();
      } catch {
        /* never into a chat */
      }
    },

    stats: () => ({ queued: queue.length, failures, backoffUntil }),
  };
}

// ── when the process may freeze right after the reply ─────────────────────

/** Hosts that stop the process once the reply is sent: there, the queue is sent at the end of every request. */
export function freezesAfterReply(env: Env): boolean {
  return !!(env.VERCEL || env.AWS_LAMBDA_FUNCTION_NAME || env.NETLIFY || env.FORGE_INSIGHTS_FLUSH_PER_REQUEST === "1");
}

/** The platform's way of saying "keep running until this is done", when it has one. */
async function keepAlive(work: Promise<unknown>): Promise<boolean> {
  try {
    const ctx = (globalThis as any)[Symbol.for("@vercel/request-context")]?.get?.();
    if (typeof ctx?.waitUntil === "function") {
      ctx.waitUntil(work);
      return true;
    }
  } catch {
    /* not on Vercel */
  }
  try {
    const next: any = await import("next/server");
    const after = next.after ?? next.unstable_after;
    if (typeof after === "function") {
      after(() => work);
      return true;
    }
  } catch {
    /* no `after` here, or not inside a request */
  }
  return false;
}

/**
 * Called when the answer has been completely sent and only the stream is left to close. On a host that freezes the
 * process after the reply, the queue is sent now: under the platform's own keep-running hook when there is one (then
 * this returns at once), otherwise for at most `holdMs` before the stream closes. Everywhere else the queue's own timer
 * does it and this returns at once. Never throws.
 */
export async function holdForShipping(
  shipper: Pick<Shipper, "configured" | "settle">,
  env: Env,
  opts: { holdMs?: number; keepAlive?: (work: Promise<unknown>) => Promise<boolean>; setTimer?: ShipperDeps["setTimer"] } = {},
): Promise<void> {
  try {
    if (!shipper.configured() || !freezesAfterReply(env)) return;
    const work = shipper.settle();
    if (await (opts.keepAlive ?? keepAlive)(work)) return;
    const wait = opts.setTimer ?? defaultTimer;
    let cancel = () => {};
    const limit = new Promise<void>((resolve) => {
      cancel = wait(resolve, opts.holdMs ?? 2000);
    });
    await Promise.race([work, limit]);
    cancel();
  } catch {
    /* never into a chat */
  }
}

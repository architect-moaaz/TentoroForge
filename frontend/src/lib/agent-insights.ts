/**
 * Insights: how an agent is doing in the connected development app, what it costs and how good it is. The logic behind the screen.
 * No React, no network.
 *
 * The app records one row per assistant turn; the platform asks the app, checks what came back, and adds cost (an ESTIMATE from list
 * prices), quality (each rate with its counts) and a few tips (backend/services/agent_insights.py). This file is the screen's side:
 * the shape of that answer, a parser that never trusts it, the words and numbers as a person reads them, and the geometry of the
 * daily chart.
 *
 * Two sources feed the same screen. A development app is asked through Watch live (the "v1 snapshot": whole days, the newest rows).
 * A live app pushes every turn to the platform, which keeps minute, hour and day totals; its answer is the same shape plus a few
 * optional extras (`mode: "stream"`, `series`, `users`, `live`, `freshness`, `exact`, `droppedEvents`). Every extra is optional, so a
 * snapshot parses exactly as before.
 */

export type ProblemReason = "error" | "blocked" | "thumbs_down" | "tool_failed" | "handed_off" | "slow" | "other";

/** A share with the counts behind it, so the screen can say "3 of 40". `pct` is 0 to 100, or null when there is nothing to take a share of. */
export interface Rate {
  pct: number | null;
  count: number;
  of: number;
}

export interface Totals {
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
}

export interface DayRow {
  day: string;
  turns: number;
  inputTokens: number;
  outputTokens: number;
  errors: number;
  up: number;
  down: number;
}

export interface ModelCost {
  model: string;
  turns: number;
  inputTokens: number;
  outputTokens: number;
  /** Null when the platform has no price for the model: it is never guessed. */
  usd: number | null;
  priced: boolean;
}

export interface ToolRow {
  name: string;
  calls: number;
  errors: number;
  avgMs: number | null;
  failurePct: number | null;
}

export interface Problem {
  conversationId: string;
  at: string | null;
  message: string;
  reason: ProblemReason;
  detail: string;
}

export interface Tip {
  id: string;
  severity: "info" | "warn";
  text: string;
}

export interface Insights {
  generatedAt: string | null;
  days: number;
  agentId: string | null;
  since: string | null;
  firstTurnAt: string | null;
  warning?: string;
  totals: Totals;
  latencyMs: { p50: number | null; p95: number | null; avg: number | null };
  byDay: DayRow[];
  byModel: Array<Pick<ModelCost, "model" | "turns" | "inputTokens" | "outputTokens">>;
  tools: ToolRow[];
  problems: Problem[];
  handoffs: { total: number; open: number; claimed: number; resolved: number; avgResolveMinutes: number | null };
  cost: {
    estimatedUsd: number | null;
    /** Some model has no price, so the total leaves it out. */
    partial: boolean;
    perChatUsd: number | null;
    perTurnUsd: number | null;
    byModel: ModelCost[];
    byDay: Array<{ day: string; usd: number | null }>;
    unpricedModels: string[];
    note: string;
  };
  quality: {
    answeredWithoutPerson: Rate;
    thumbsUp: Rate;
    errors: Rate;
    blocked: Rate;
    toolFailures: Rate;
    speed: { p50Ms: number | null; p95Ms: number | null; avgMs: number | null; slow: boolean };
  };
  tips: Tip[];

  // ---- only a live app's answer has these (all optional: a development snapshot has none of them) ----
  mode?: "stream";
  range?: RangeChoice;
  granularity?: Granularity;
  until?: string | null;
  freshness?: Freshness;
  /** True when every event counts; false when the platform says the numbers are a sample. */
  exact?: boolean;
  /** Events the platform turned away in this time (rejected or over the rate limit): the numbers are that much low. */
  droppedEvents?: number;
  live?: LiveNow;
  series?: SeriesPoint[];
  users?: People;
}

export type RangeChoice = "1h" | "24h" | "7d" | "30d" | "90d";
export type Granularity = "minute" | "hour" | "day";

export interface SeriesPoint {
  /** The start of the bucket (ISO). */
  t: string;
  turns: number;
  errors: number;
  inputTokens: number;
  outputTokens: number;
  usd: number | null;
  activeUsers: number;
}

export interface Freshness {
  lastEventAt: string | null;
  lagSeconds: number | null;
}

/** The last five minutes, for the strip at the top. */
export interface LiveNow {
  turnsPerMinute: number;
  activeUsers5m: number;
  errorRatePct5m: number | null;
  p95Ms5m: number | null;
}

export interface RoleRow {
  role: string;
  users: number;
  turns: number;
  usd: number | null;
  thumbsDownPct: number | null;
}

export interface TopUser {
  /** An anonymous code (a keyed hash of the person's id), never a name or an email. */
  userKey: string;
  role: string | null;
  turns: number;
  inputTokens: number;
  outputTokens: number;
  usd: number | null;
  errors: number;
  thumbsDown: number;
  lastSeenAt: string | null;
}

export interface People {
  active: number;
  newUsers: number;
  returning: number;
  /** Distinct counts come from a sketch (error under 1%): say "about". */
  approximate: boolean;
  activeByDay: Array<{ day: string; active: number }>;
  byRole: RoleRow[];
  top: TopUser[];
}

export const DAY_CHOICES = [7, 30, 90] as const;

/**
 * The choices for how far back to look. A live app can answer all five. A development app only knows whole days, so it answers the last
 * three; the first two are not offered for it, and a choice of an hour or a day shows 7 days there (see `devRange`).
 */
export const RANGE_CHOICES: ReadonlyArray<{ value: RangeChoice; label: string; words: string; days: number }> = [
  { value: "1h", label: "1 hour", words: "hour", days: 1 },
  { value: "24h", label: "24 hours", words: "24 hours", days: 1 },
  { value: "7d", label: "7 days", words: "7 days", days: 7 },
  { value: "30d", label: "30 days", words: "30 days", days: 30 },
  { value: "90d", label: "90 days", words: "90 days", days: 90 },
];
export const DEV_RANGES: RangeChoice[] = ["7d", "30d", "90d"];

/** What a development app is asked for when the choice was an hour or a day, which it cannot do: the shortest it can show. */
export const devRange = (range: RangeChoice): RangeChoice => (DEV_RANGES.includes(range) ? range : "7d");
export const rangeDays = (range: RangeChoice): number => RANGE_CHOICES.find((r) => r.value === range)?.days ?? 7;

export const COST_NOTE = "Estimated from list prices; your bill may differ.";

// ---------------------------------------------------------------------------
// reading the answer without trusting it
// ---------------------------------------------------------------------------

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const int = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? Math.max(0, Math.round(v)) : 0);
const numOrNull = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? Math.max(0, v) : null);
const str = (v: unknown, max = 400): string => (typeof v === "string" ? v.slice(0, max) : "");
const list = (v: unknown, max: number): Record<string, unknown>[] => (Array.isArray(v) ? v.slice(0, max).filter(isObj) : []);
const isoOrNull = (v: unknown): string | null => {
  const s = str(v, 40);
  return s && Number.isFinite(Date.parse(s)) ? s : null;
};
const RANGES: RangeChoice[] = ["1h", "24h", "7d", "30d", "90d"];
const GRANULARITIES: Granularity[] = ["minute", "hour", "day"];
const pctOrNull = (v: unknown): number | null => {
  const n = numOrNull(v);
  return n === null ? null : Math.min(n, 100);
};
/** A day as the platform writes it (2026-10-21). Anything else is not a day. */
const isDay = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v);
/** The most buckets read from one answer: a minute view of a whole day is 1440, so this leaves room. */
export const MAX_SERIES = 1500;
const REASONS: ProblemReason[] = ["error", "blocked", "thumbs_down", "tool_failed", "handed_off", "slow"];

const rate = (v: unknown): Rate => {
  const r = isObj(v) ? v : {};
  const of = int(r.of);
  const count = Math.min(int(r.count), of);
  const pct = numOrNull(r.pct);
  return { pct: of > 0 && pct !== null ? Math.min(pct, 100) : null, count, of };
};

/**
 * The platform's answer as a complete, safe `Insights`, or null when it is not one at all (no totals). A missing or odd field becomes a
 * zero, an empty list or a null, so the screen can always draw what it was given.
 */
export function asInsights(raw: unknown): Insights | null {
  if (!isObj(raw) || !isObj(raw.totals)) return null;
  const t = raw.totals;
  const totals: Totals = {
    conversations: int(t.conversations), turns: int(t.turns), users: int(t.users), inputTokens: int(t.inputTokens),
    outputTokens: int(t.outputTokens), toolCalls: int(t.toolCalls), toolErrors: int(t.toolErrors), blocked: int(t.blocked),
    errors: int(t.errors), handedOff: int(t.handedOff), rated: int(t.rated), up: int(t.up), down: int(t.down),
  };
  const lat = isObj(raw.latencyMs) ? raw.latencyMs : {};
  const cost = isObj(raw.cost) ? raw.cost : {};
  const q = isObj(raw.quality) ? raw.quality : {};
  const speed = isObj(q.speed) ? q.speed : {};
  const h = isObj(raw.handoffs) ? raw.handoffs : {};
  const p95 = numOrNull(lat.p95);
  const warning = str(raw.warning, 300);
  const range = RANGES.includes(raw.range as RangeChoice) ? (raw.range as RangeChoice) : undefined;
  return {
    generatedAt: str(raw.generatedAt, 40) || null,
    days: int(raw.days) || (range ? rangeDays(range) : 7),
    agentId: str(raw.agentId, 100) || null,
    since: str(raw.since, 40) || null,
    firstTurnAt: str(raw.firstTurnAt, 40) || null,
    ...(warning ? { warning } : {}),
    totals,
    latencyMs: { p50: numOrNull(lat.p50), p95, avg: numOrNull(lat.avg) },
    byDay: list(raw.byDay, 92).map((d) => ({
      day: str(d.day, 10), turns: int(d.turns), inputTokens: int(d.inputTokens), outputTokens: int(d.outputTokens),
      errors: int(d.errors), up: int(d.up), down: int(d.down),
    })),
    byModel: list(raw.byModel, 20).map((m) => ({ model: str(m.model, 100), turns: int(m.turns), inputTokens: int(m.inputTokens), outputTokens: int(m.outputTokens) })),
    tools: list(raw.tools, 50).map((x) => {
      const calls = int(x.calls);
      const errors = Math.min(int(x.errors), calls);
      return { name: str(x.name, 80), calls, errors, avgMs: numOrNull(x.avgMs), failurePct: calls > 0 ? (100 * errors) / calls : null };
    }),
    problems: list(raw.problems, 50).map((p) => ({
      conversationId: str(p.conversationId, 80), at: str(p.at, 40) || null, message: str(p.message, 300),
      reason: REASONS.includes(p.reason as ProblemReason) ? (p.reason as ProblemReason) : "other", detail: str(p.detail, 300),
    })),
    handoffs: { total: int(h.total), open: int(h.open), claimed: int(h.claimed), resolved: int(h.resolved), avgResolveMinutes: numOrNull(h.avgResolveMinutes) },
    cost: {
      estimatedUsd: numOrNull(cost.estimatedUsd),
      partial: cost.partial === true,
      perChatUsd: numOrNull(cost.perChatUsd),
      perTurnUsd: numOrNull(cost.perTurnUsd),
      byModel: list(cost.byModel, 20).map((m) => {
        const usd = numOrNull(m.usd);
        // priced only when there is a number to show: a "priced" model with no dollar figure is shown as unpriced
        return { model: str(m.model, 100), turns: int(m.turns), inputTokens: int(m.inputTokens), outputTokens: int(m.outputTokens), usd, priced: m.priced === true && usd !== null };
      }),
      byDay: list(cost.byDay, 92).map((d) => ({ day: str(d.day, 10), usd: numOrNull(d.usd) })),
      unpricedModels: Array.isArray(cost.unpricedModels) ? cost.unpricedModels.filter((m): m is string => typeof m === "string").slice(0, 20) : [],
      note: str(cost.note, 200) || COST_NOTE,
    },
    quality: {
      answeredWithoutPerson: rate(q.answeredWithoutPerson),
      thumbsUp: rate(q.thumbsUp),
      errors: rate(q.errors),
      blocked: rate(q.blocked),
      toolFailures: rate(q.toolFailures),
      speed: { p50Ms: numOrNull(speed.p50Ms), p95Ms: numOrNull(speed.p95Ms), avgMs: numOrNull(speed.avgMs), slow: speed.slow === true },
    },
    tips: list(raw.tips, 5).map((x) => ({ id: str(x.id, 80), severity: x.severity === "warn" ? "warn" : "info", text: str(x.text, 400) })),
    ...streamExtras(raw, range),
  };
}

/**
 * The extras a live app's answer carries. Each one is left out (not zeroed) when the platform did not send it, so the screen can tell
 * "no figure" from "none". Lists are capped and every row is checked: the platform's JSON is read, never trusted.
 */
function streamExtras(raw: Record<string, unknown>, range: RangeChoice | undefined): Partial<Insights> {
  const out: Partial<Insights> = {};
  if (raw.mode === "stream") out.mode = "stream";
  if (range) out.range = range;
  if (GRANULARITIES.includes(raw.granularity as Granularity)) out.granularity = raw.granularity as Granularity;
  if ("until" in raw) out.until = isoOrNull(raw.until);
  if (isObj(raw.freshness)) out.freshness = { lastEventAt: isoOrNull(raw.freshness.lastEventAt), lagSeconds: numOrNull(raw.freshness.lagSeconds) };
  if (typeof raw.exact === "boolean") out.exact = raw.exact;
  if ("droppedEvents" in raw) out.droppedEvents = int(raw.droppedEvents);
  if (isObj(raw.live)) {
    out.live = {
      turnsPerMinute: numOrNull(raw.live.turnsPerMinute) ?? 0,
      activeUsers5m: int(raw.live.activeUsers5m),
      errorRatePct5m: pctOrNull(raw.live.errorRatePct5m),
      p95Ms5m: numOrNull(raw.live.p95Ms5m),
    };
  }
  if (Array.isArray(raw.series)) {
    out.series = list(raw.series, MAX_SERIES)
      .filter((p) => isoOrNull(p.t) !== null)
      .map((p) => {
        const turns = int(p.turns);
        return {
          t: str(p.t, 40), turns, errors: Math.min(int(p.errors), turns), inputTokens: int(p.inputTokens), outputTokens: int(p.outputTokens),
          usd: numOrNull(p.usd), activeUsers: int(p.activeUsers),
        };
      });
  }
  if (isObj(raw.users)) {
    const u = raw.users;
    out.users = {
      active: int(u.active), newUsers: int(u.newUsers), returning: int(u.returning), approximate: u.approximate === true,
      activeByDay: list(u.activeByDay, 92).filter((d) => isDay(d.day)).map((d) => ({ day: d.day as string, active: int(d.active) })),
      byRole: list(u.byRole, 12).map((r) => ({
        role: str(r.role, 60) || "(no role)", users: int(r.users), turns: int(r.turns), usd: numOrNull(r.usd), thumbsDownPct: pctOrNull(r.thumbsDownPct),
      })),
      top: list(u.top, 20)
        .filter((p) => str(p.userKey, 64) !== "")
        .map((p) => ({
          userKey: str(p.userKey, 64), role: str(p.role, 60) || null, turns: int(p.turns), inputTokens: int(p.inputTokens), outputTokens: int(p.outputTokens),
          usd: numOrNull(p.usd), errors: int(p.errors), thumbsDown: int(p.thumbsDown), lastSeenAt: isoOrNull(p.lastSeenAt),
        })),
    };
  }
  return out;
}

// ---------------------------------------------------------------------------
// words and numbers
// ---------------------------------------------------------------------------

/** Dollars as a person reads them. Null means the price of the model is not known, which is not the same as free. */
export function formatMoney(usd: number | null | undefined): string {
  if (usd === null || usd === undefined || !Number.isFinite(usd)) return "n/a (price unknown)";
  if (usd > 0 && usd < 0.01) return "under $0.01";
  return `$${usd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Tokens: 950, 12.3k, 1.2M. */
export function formatTokens(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "n/a";
  const trim = (x: number) => x.toFixed(1).replace(/\.0$/, "");
  if (n < 1000) return String(Math.round(n));
  if (n < 999_950) return `${trim(n / 1000)}k`;
  if (n < 999_950_000) return `${trim(n / 1_000_000)}M`;
  return `${trim(n / 1_000_000_000)}B`;
}

/** A share: 90%, 2.5%. Null is "n/a", not 0%. */
export function formatPct(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return "n/a";
  const rounded = Math.abs(pct) >= 10 || Number.isInteger(pct) ? Math.round(pct) : Math.round(pct * 10) / 10;
  return `${rounded}%`;
}

/** "3 of 40". */
export const countOf = (r: Rate): string => `${r.count} of ${r.of}`;

/** How long something took: 420 ms, 2.1 s, 45 s, 1 min 5 s. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "n/a";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 10_000) return `${(ms / 1000).toFixed(1).replace(/\.0$/, "")} s`;
  if (ms < 60_000) return `${Math.round(ms / 1000)} s`;
  const total = Math.round(ms / 1000);
  const s = total % 60;
  return `${Math.floor(total / 60)} min${s ? ` ${s} s` : ""}`;
}

/** A longer wait, in minutes: 12 minutes, 1 hour 5 minutes, 2 days. */
export function formatMinutes(min: number | null | undefined): string {
  if (min === null || min === undefined || !Number.isFinite(min)) return "n/a";
  const m = Math.round(min);
  if (m < 1) return "under a minute";
  if (m < 60) return m === 1 ? "1 minute" : `${m} minutes`;
  if (m < 60 * 24) {
    const h = Math.floor(m / 60);
    const r = m % 60;
    return `${h} ${h === 1 ? "hour" : "hours"}${r ? ` ${r} ${r === 1 ? "minute" : "minutes"}` : ""}`;
  }
  const d = Math.round(m / (60 * 24));
  return `${d} ${d === 1 ? "day" : "days"}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10-21" as "Oct 21". Read from the text itself, so no time zone can move it to another day. */
export function dayLabel(day: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!m) return day;
  const month = MONTHS[Number(m[2]) - 1];
  return month ? `${month} ${Number(m[3])}` : day;
}

/** When something happened, for a list: "just now", "5 min ago", "3 h ago", or the date for anything older than a day. */
export function ago(iso: string | null, now: number = Date.now()): string {
  const at = iso ? Date.parse(iso) : NaN;
  if (!Number.isFinite(at)) return "Unknown time";
  const s = Math.max(0, Math.round((now - at) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86_400) return `${Math.floor(s / 3600)} h ago`;
  return dayLabel(new Date(at).toISOString().slice(0, 10));
}

/** Why a chat is on the list, in plain words. */
export const REASON_LABEL: Record<ProblemReason, string> = {
  error: "The chat failed",
  blocked: "Refused by the assistant's rules",
  thumbs_down: "Thumbs down",
  tool_failed: "A tool failed",
  handed_off: "Handed to a person",
  slow: "Slow",
  other: "Something went wrong",
};

/** What a model's cost cell says: a figure, or that its price is not known (never a guess). */
export const modelCost = (m: Pick<ModelCost, "priced" | "usd">): string => (m.priced && m.usd !== null ? formatMoney(m.usd) : "price unknown");

/** Warnings first, then the rest, each group in the order given. */
export const sortTips = (tips: Tip[]): Tip[] => [...tips.filter((t) => t.severity === "warn"), ...tips.filter((t) => t.severity !== "warn")];

// ---------------------------------------------------------------------------
// the daily chart
// ---------------------------------------------------------------------------

/** A tidy top for a scale (1, 2, 5, 10, 20, 50, ...) so the tallest bar does not touch the roof. Never below 1. */
export function niceMax(max: number): number {
  if (!Number.isFinite(max) || max <= 1) return 1;
  const pow = 10 ** Math.floor(Math.log10(max));
  const f = max / pow;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * pow;
}

/** Each value as a height from 0 to 100 (percent of the chart). A value above the top is held at 100; a missing one is 0. */
export function barHeights(values: number[], top: number): number[] {
  return values.map((v) => (top > 0 && Number.isFinite(v) ? Math.max(0, Math.min(100, (v / top) * 100)) : 0));
}

/**
 * A second series drawn over the bars, in the same 0 to 100 box. A day with no figure (a price that is not known) breaks the line, so
 * nothing is drawn through a gap. Returns one "x,y x,y" string per unbroken run; a lone day is drawn as a tiny flat stroke so it shows.
 */
export function linePoints(values: Array<number | null>, top: number): string[] {
  const n = values.length;
  const runs: string[][] = [];
  let current: string[] = [];
  values.forEach((v, i) => {
    if (v === null || !Number.isFinite(v) || top <= 0) {
      if (current.length) runs.push(current);
      current = [];
      return;
    }
    const x = n > 0 ? ((i + 0.5) / n) * 100 : 0;
    const y = 100 - Math.max(0, Math.min(100, (v / top) * 100));
    current.push(`${x.toFixed(2)},${y.toFixed(2)}`);
  });
  if (current.length) runs.push(current);
  return runs.map((r) => (r.length === 1 ? `${r[0]} ${r[0]}` : r.join(" ")));
}

/** Which days get a label under the chart: the first, the last, and about five between, so a long range stays readable. */
export function labelledDays(count: number): number[] {
  if (count <= 0) return [];
  const step = Math.max(1, Math.ceil(count / 6));
  const out: number[] = [];
  for (let i = 0; i < count; i += step) out.push(i);
  if (out[out.length - 1] !== count - 1 && count - 1 - out[out.length - 1] >= Math.ceil(step / 2)) out.push(count - 1);
  return out;
}

// ---------------------------------------------------------------------------
// a live app: freshness, time buckets and who is using it
// ---------------------------------------------------------------------------

/** 50,000, not 50000. */
export const formatCount = (n: number | null | undefined): string => (n === null || n === undefined || !Number.isFinite(n) ? "n/a" : Math.round(n).toLocaleString("en-US"));

/** A rate per minute: 3 chats a minute reads whole, 0.4 keeps its decimal. */
export function formatRate(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "n/a";
  if (n >= 10) return formatCount(n);
  return String(Math.round(n * 10) / 10);
}

/** "4 seconds ago", "3 minutes ago", "2 hours ago", "5 days ago". Under a second is "just now". */
export function secondsAgo(sec: number | null | undefined): string {
  if (sec === null || sec === undefined || !Number.isFinite(sec)) return "a while ago";
  const s = Math.max(0, Math.round(sec));
  const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"} ago`;
  if (s < 1) return "just now";
  if (s < 60) return plural(s, "second");
  if (s < 3600) return plural(Math.floor(s / 60), "minute");
  if (s < 86_400) return plural(Math.floor(s / 3600), "hour");
  return plural(Math.floor(s / 86_400), "day");
}

/** Events newer than this mean the app is sending right now (the pulsing dot). */
export const LIVE_LAG_SECONDS = 15;
/** Up to here the line says "Updated": a chat in the last five minutes is the same window as the strip. */
const RECENT_SECONDS = 300;

export const isLiveNow = (f: Freshness | null | undefined): boolean => !!f && f.lagSeconds !== null && f.lagSeconds < LIVE_LAG_SECONDS;

/**
 * The quiet line under the title: how old the newest event is, and whether every chat is counted. `lagSeconds` is the age of the newest
 * event, so for a quiet app it is hours: it then says "The newest chat arrived 3 hours ago" rather than "Updated 3 hours ago", which would
 * read as if the screen were stale.
 */
export function freshnessText(f: Freshness | null | undefined, exact: boolean | undefined): string {
  const counted = exact === true ? ", every chat counted" : exact === false ? ", the counts are approximate" : "";
  if (!f || f.lagSeconds === null) return `No chats have arrived yet${counted}`;
  return `${f.lagSeconds <= RECENT_SECONDS ? "Updated" : "The newest chat arrived"} ${secondsAgo(f.lagSeconds)}${counted}`;
}

/** Said whenever the platform turned events away, with what it knows of why. Never left out. */
export function droppedText(n: number | null | undefined): string | null {
  if (!n || n <= 0) return null;
  return `${formatCount(n)} ${n === 1 ? "event was" : "events were"} not accepted in this time, so these numbers are a little low. They were turned away as invalid, or because too many arrived at once.`;
}

const pad2 = (n: number) => String(n).padStart(2, "0");

/**
 * A bucket's label on the axis: "10:42" for a minute, "Oct 21, 14:00" for an hour, "Oct 21" for a day. A minute or an hour is shown in
 * the viewer's own time zone (that is how they think of "ten forty-two"); a day is read from the text, as the rollups count days in UTC.
 */
export function bucketLabel(iso: string, granularity: Granularity): string {
  if (granularity === "day") return dayLabel(iso.slice(0, 10));
  const at = new Date(iso);
  if (!Number.isFinite(at.getTime())) return iso;
  const clock = `${pad2(at.getHours())}:${pad2(granularity === "hour" ? 0 : at.getMinutes())}`;
  return granularity === "minute" ? clock : `${MONTHS[at.getMonth()]} ${at.getDate()}, ${clock}`;
}

/** What one column or table row stands for. `day` is only a stable key (the bucket start). */
export interface ChartRow {
  day: string;
  label: string;
  /** A longer name for the tooltip and the table, when one column covers several buckets. */
  title?: string;
  turns: number;
  errors: number;
  usd: number | null;
  activeUsers: number;
}

export function seriesRows(series: SeriesPoint[], granularity: Granularity): ChartRow[] {
  return series.map((p) => ({ day: p.t, label: bucketLabel(p.t, granularity), turns: p.turns, errors: p.errors, usd: p.usd, activeUsers: p.activeUsers }));
}

/** The development app's days as rows, with each day's cost beside it. */
export function dayRows(data: Pick<Insights, "byDay" | "cost">): ChartRow[] {
  const cost = new Map(data.cost.byDay.map((d) => [d.day, d.usd]));
  return data.byDay.map((d) => ({ day: d.day, label: dayLabel(d.day), turns: d.turns, errors: d.errors, usd: cost.get(d.day) ?? null, activeUsers: 0 }));
}

/** How many columns can be drawn before they stop being readable: a minute view is thinner than an hour or a day view. */
export const maxColumns = (granularity: Granularity): number => (granularity === "minute" ? 120 : 180);

/**
 * Fewer rows for DRAWING only: neighbours are added together so no more than `max` remain (turns, failures and cost are sums; the people
 * count is the busiest bucket, since people in two buckets are not two people). The table beside the chart keeps every bucket.
 */
export function downsampleRows(rows: ChartRow[], max: number): ChartRow[] {
  if (max < 1 || rows.length <= max) return rows;
  const size = Math.ceil(rows.length / max);
  const out: ChartRow[] = [];
  for (let i = 0; i < rows.length; i += size) {
    const part = rows.slice(i, i + size);
    const known = part.map((r) => r.usd).filter((v): v is number => v !== null);
    out.push({
      day: part[0].day,
      label: part[0].label,
      title: part.length > 1 ? `${part[0].label} to ${part[part.length - 1].label}` : undefined,
      turns: part.reduce((a, r) => a + r.turns, 0),
      errors: part.reduce((a, r) => a + r.errors, 0),
      usd: known.length ? known.reduce((a, b) => a + b, 0) : null,
      activeUsers: Math.max(...part.map((r) => r.activeUsers)),
    });
  }
  return out;
}

/** The bucket size the platform uses for a range (contract: 1h minutes, 24h and 7d hours, 30d and 90d days), for an answer that did not say. */
export const granularityFor = (range: RangeChoice): Granularity => (range === "1h" ? "minute" : range === "24h" || range === "7d" ? "hour" : "day");

/** A person's anonymous code, short enough for a table: the first 8 and last 4 characters. */
export const shortKey = (key: string): string => (key.length > 14 ? `${key.slice(0, 8)}…${key.slice(-4)}` : key);

/** "about 50,000" when the count comes from a sketch, "50,000" when it is exact. */
export const peopleCount = (n: number, approximate: boolean): string => `${approximate ? "about " : ""}${formatCount(n)}`;

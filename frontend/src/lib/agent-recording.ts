/**
 * Recording chats from Watch live: the logic. No React, no network.
 *
 * The builder says "record the next X chats". Each chat that FINISHES while recording is on is kept with everything Watch live
 * knew about it: who wrote to the assistant, the message, every step (each AI call, each tool with what it was given and what
 * came back, what the tool did in the app), the checks the runtime made, the reply, the timings, and what went wrong. When X are
 * kept (or the builder stops) the recording can be sent to Find problems as saved tests, to the fixer, or downloaded as a file.
 *
 * A chat that began before recording started is not kept (it would be a partial one), and a chat is kept once however many
 * updates arrive for it.
 */
import type { Step, Phase } from "./agent-live";
import type { WatchRun, WatchState } from "./agent-watch";
import type { BlastFix } from "./agent-blast";

export const DEFAULT_WANT = 5;
/** The platform takes at most this many chats in one send (services/agent_recording.py MAX_SENT). */
export const MAX_WANT = 40;
/** A chat slower than this is a problem worth saying (the same line the platform draws). */
export const SLOW_MS = 30_000;

export interface RecordedChat {
  id: string;
  agentId?: string;
  agentName?: string;
  who?: { id?: string; name?: string | null; email?: string | null; role?: string | null };
  message: string;
  reply: string;
  status: "done" | "blocked" | "error";
  blocked?: string;
  error?: string;
  conversationId?: string;
  totals: { ms: number; inputTokens: number; outputTokens: number; modelCalls: number; toolCalls: number };
  phases: Phase[];
  steps: Step[];
  recordedAt: number;
}

export interface Recording {
  /** How many chats to record. */
  want: number;
  /** Recording is on. */
  on: boolean;
  /** When it was turned on: only chats the watcher first heard of after this are kept. */
  startedAt: number;
  chats: RecordedChat[];
}

export const emptyRecording = (): Recording => ({ want: DEFAULT_WANT, on: false, startedAt: 0, chats: [] });

/** A number of chats to record, made sensible: a whole number from 1 to the most a send takes. */
export const clampWant = (n: unknown): number => {
  const v = typeof n === "number" ? n : Number(n);
  return Number.isFinite(v) ? Math.min(MAX_WANT, Math.max(1, Math.round(v))) : DEFAULT_WANT;
};

export function start(rec: Recording, want: unknown, now: number = Date.now()): Recording {
  return { want: clampWant(want), on: true, startedAt: now, chats: [] };
}

export function stop(rec: Recording): Recording {
  return { ...rec, on: false };
}

export function clear(rec: Recording): Recording {
  return { ...emptyRecording(), want: rec.want };
}

/** One finished chat as it is recorded, or null when it is still going, or has no message to record. */
export function chatOf(run: WatchRun, now: number = Date.now()): RecordedChat | null {
  const live = run.live;
  if (!run.finished || !live.message || (live.status !== "done" && live.status !== "blocked" && live.status !== "error")) return null;
  return {
    id: run.id,
    ...(run.agentId ? { agentId: run.agentId } : {}),
    ...(run.agentName ? { agentName: run.agentName } : {}),
    ...(live.user ? { who: { id: live.user.id, name: live.user.name, email: live.user.email, role: live.user.role } } : {}),
    message: live.message,
    reply: live.answer ?? "",
    status: live.status,
    ...(live.blocked ? { blocked: live.blocked } : {}),
    ...(live.error ? { error: live.error } : {}),
    ...(live.conversationId ? { conversationId: live.conversationId } : {}),
    totals: { ...live.totals },
    phases: live.phases,
    steps: live.steps,
    recordedAt: now,
  };
}

/** Take in whatever has finished since the last look. Stops by itself when there are as many as were asked for. */
export function take(rec: Recording, watch: WatchState, now: number = Date.now()): Recording {
  if (!rec.on) return rec;
  const have = new Set(rec.chats.map((c) => c.id));
  // oldest first, so the chats are kept in the order they happened
  const fresh: RecordedChat[] = [];
  for (const id of [...watch.order].reverse()) {
    const run = watch.runs[id];
    if (!run || have.has(id) || run.seenAt < rec.startedAt) continue;
    const chat = chatOf(run, now);
    if (chat) fresh.push(chat);
  }
  if (fresh.length === 0) return rec;
  const chats = [...rec.chats, ...fresh].slice(0, rec.want);
  return { ...rec, chats, on: chats.length < rec.want };
}

/** Plain sentences about what went wrong in a chat, worked out from what was recorded (the platform draws the same lines). */
export function problemsOf(chat: RecordedChat): string[] {
  const out: string[] = [];
  if (chat.status === "error") out.push(`The chat failed: ${chat.error || "with no reason given"}.`);
  if (chat.status === "blocked") out.push(`The assistant's own rules refused the message: ${chat.blocked || "no reason given"}.`);
  for (const p of chat.phases) if (p.ok === false && p.phase === "output_check") out.push(`The assistant's answer was stopped by its output check: ${p.reason || "no reason given"}.`);
  for (const s of chat.steps) {
    if (s.kind === "model" && s.failed) out.push(`A call to the AI failed: ${s.failed}.`);
    if (s.kind === "tool") {
      if (s.status === "failed") out.push(`The tool ${s.tool} failed: ${s.error || "no reason given"}.`);
      for (const p of s.problems) out.push(`The assistant gave ${s.tool} a bad input: ${p.message}`);
    }
  }
  if (chat.status === "done" && !chat.reply) out.push("The chat ended with no reply to the person.");
  if (chat.totals.ms > SLOW_MS) out.push(`It was slow: ${Math.round(chat.totals.ms / 1000)} seconds to answer.`);
  return [...new Set(out)].slice(0, 8);
}

export interface Summary {
  kept: number;
  want: number;
  withProblems: number;
  /** Words for the strip: "Recording: 2 of 5 chats", "Recorded 5 chats, 2 with problems". */
  text: string;
}

export function summarise(rec: Recording): Summary {
  const kept = rec.chats.length;
  const withProblems = rec.chats.filter((c) => problemsOf(c).length > 0).length;
  const noun = (n: number) => `${n} chat${n === 1 ? "" : "s"}`;
  const text = rec.on
    ? `Recording: ${kept} of ${noun(rec.want)}`
    : kept === 0
      ? ""
      : `Recorded ${noun(kept)}${withProblems ? `, ${withProblems} with problems` : ", none with problems"}`;
  return { kept, want: rec.want, withProblems, text };
}

/** The file a builder can keep: every detail of every chat. Nothing is left out but what the app itself never sent. */
export function recordingFile(rec: Recording, projectId: string, now: Date = new Date()): { name: string; json: string } {
  const stamp = now.toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const body = {
    kind: "forge-watch-recording",
    version: 1,
    project: projectId,
    recordedAt: now.toISOString(),
    chats: rec.chats.map((c) => ({ ...c, problems: problemsOf(c) })),
  };
  return { name: `watch-recording-${stamp}.json`, json: JSON.stringify(body, null, 2) };
}

/** What was kept in the browser, made safe to use: anything that is not a recording comes back as an empty one. */
export function readRecording(raw: unknown): Recording {
  try {
    const r = (typeof raw === "string" ? JSON.parse(raw) : raw) as Partial<Recording> | null;
    if (!r || typeof r !== "object" || !Array.isArray(r.chats)) return emptyRecording();
    const chats = r.chats.filter((c): c is RecordedChat => !!c && typeof c === "object" && typeof (c as RecordedChat).id === "string" && typeof (c as RecordedChat).message === "string" && Array.isArray((c as RecordedChat).steps));
    return { want: clampWant(r.want), on: !!r.on && chats.length < clampWant(r.want), startedAt: typeof r.startedAt === "number" ? r.startedAt : 0, chats: chats.slice(0, MAX_WANT) };
  } catch {
    return emptyRecording();
  }
}

// ── sending ─────────────────────────────────────────────────────────────────

/** What the platform says it did with the chats it was sent (POST .../recordings/send; the saved tests themselves are left out here). */
export interface Sent {
  sent: number;
  added: number;
  alreadyThere: number;
  leftOut: number;
  fixes: BlastFix[];
  /** What went wrong in each chat, by the id of its saved test; chats that went well are not listed. */
  problems: Record<string, string[]>;
}

/** A send handed to Find problems, so it can say what arrived and show the fixes. `key` is new for every send: it is consumed once. */
export interface Incoming extends Sent {
  key: number;
  fixRequested: boolean;
}

const many = (n: number, one: string, more: string = `${one}s`) => `${n} ${n === 1 ? one : more}`;

/** Only chats of this assistant can become its tests: a chat of no known assistant is taken as this one's, the rest are counted as skipped. */
export function chatsFor(chats: RecordedChat[], agentId: string): { mine: RecordedChat[]; skipped: number } {
  const mine = chats.filter((c) => !c.agentId || c.agentId === agentId);
  return { mine, skipped: chats.length - mine.length };
}

/** The sentence the Watch live strip shows once chats were sent. `skipped` is how many were held back before sending. */
export function sentence(result: Sent, opts: { fix: boolean; skipped?: number }): string {
  const parts: string[] = [];
  if (result.added === 0) {
    parts.push(result.sent === 1 ? "That chat was already in Find problems as a test." : `Those ${result.sent} chats were already in Find problems as tests.`);
  } else {
    const there = result.alreadyThere > 0 ? ` (${result.alreadyThere} ${result.alreadyThere === 1 ? "was" : "were"} already there)` : "";
    parts.push(`Added ${many(result.added, "chat")} as tests in Find problems${there}.`);
  }
  if (opts.fix) {
    parts.push(result.fixes.length === 0 ? "The fixer found no safe fix." : `The fixer proposed ${many(result.fixes.length, "fix", "fixes")}.`);
  }
  const left = (opts.skipped ?? 0) + result.leftOut;
  if (left > 0) parts.push(`${many(left, "chat")} left out (from another assistant, or not finished).`);
  return parts.join(" ");
}

/** The note at the top of Find problems when chats have just arrived from Watch live. */
export function arrivalNote(incoming: Incoming): string {
  const bad = Object.keys(incoming.problems).length;
  const had = bad > 0 ? ` (${bad} of them had problems)` : " (none had problems)";
  const head =
    incoming.added === 0
      ? `${incoming.sent === 1 ? "That real chat was" : `Those ${incoming.sent} real chats were`} already in My tests${had}.`
      : `Added ${many(incoming.added, "real chat")} from Watch live to My tests${had}.`;
  const left = incoming.leftOut > 0 ? ` ${many(incoming.leftOut, "chat")} left out (from another assistant, or not finished).` : "";
  if (!incoming.fixRequested) return head + left;
  return `${head} ${incoming.fixes.length === 0 ? "The fixer found no safe fix." : `The fixer proposed ${many(incoming.fixes.length, "fix", "fixes")} below.`}${left}`;
}

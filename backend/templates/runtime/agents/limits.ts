/**
 * How much one person may use an assistant — so a loop, a script or a curious tester cannot run up the bill.
 * Forge runtime — do not remove.
 *
 * Three limits, per signed-in person across all of the app's assistants: messages in a minute, messages in an hour
 * and model tokens in a day. 0 means no limit. The counts live in a small table (the conversation itself is
 * trimmed over time, so it cannot be counted). An app without that table is simply not limited: a missing
 * table must never stop the assistant from working.
 */
import type { Limits } from "./types";
import type { Verdict } from "./guardrails";

export const DEFAULT_LIMITS: Limits = { perMinute: 12, perHour: 100, tokensPerDay: 500_000 };

export interface Usage {
  /** Messages sent in the current clock minute / in the last hour; tokens used in the last 24 hours. */
  minute: number;
  hour: number;
  tokensDay: number;
}

export interface UsageStore {
  read(userId: string): Promise<Usage>;
  add(userId: string, delta: { messages?: number; tokens?: number }): Promise<void>;
}

const whole = (v: unknown, fallback: number): number =>
  typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.floor(v) : fallback;

/** What the definition says, with the defaults for anything it leaves out. */
export function limitsOf(spec?: Partial<Limits> | null): Limits {
  return {
    perMinute: whole(spec?.perMinute, DEFAULT_LIMITS.perMinute),
    perHour: whole(spec?.perHour, DEFAULT_LIMITS.perHour),
    tokensPerDay: whole(spec?.tokensPerDay, DEFAULT_LIMITS.tokensPerDay),
  };
}

/** `null` when the person is within their limits, otherwise what they are told. */
export function checkLimits(limits: Limits, used: Usage): Verdict | null {
  if (limits.perMinute > 0 && used.minute >= limits.perMinute) {
    return { ok: false, reason: "You are sending messages very quickly. Please wait a minute and try again." };
  }
  if (limits.perHour > 0 && used.hour >= limits.perHour) {
    return { ok: false, reason: "You have reached the hourly message limit for the assistant. Please try again a little later." };
  }
  if (limits.tokensPerDay > 0 && used.tokensDay >= limits.tokensPerDay) {
    return { ok: false, reason: "You have reached the assistant's daily usage limit. It resets within 24 hours." };
  }
  return null;
}

/** In-memory counts, for tests and the platform's dry run. */
export function memoryUsage(initial: Partial<Usage> = {}): UsageStore & { totals: Usage } {
  const totals: Usage = { minute: 0, hour: 0, tokensDay: 0, ...initial };
  return {
    totals,
    async read() {
      return { ...totals };
    },
    async add(_user, d) {
      totals.minute += d.messages ?? 0;
      totals.hour += d.messages ?? 0;
      totals.tokensDay += d.tokens ?? 0;
    },
  };
}

/**
 * THE SIGN-IN'S GUARD — what stands between a right password and a session.
 *
 *   - SIGN-IN PAUSES after five wrong passwords in a row for one address: for
 *     fifteen minutes no password opens it, the right one included. A right
 *     password (or a password reset) sets the count back to nought.
 *   - TWO-STEP: a person who turned it on gets a six-digit code by email after
 *     the password, and no session exists until it is entered — `auth.ts`
 *     refuses in `authorize`, so there is nothing for a page or the
 *     middleware to forget to check. "Trust this browser" leaves a signed,
 *     httpOnly cookie good for thirty days.
 *   - ONE CODE IN FLIGHT per person for a two-step sign-in, a password reset or
 *     turning two-step on or off; it is kept only as a keyed digest, expires in
 *     ten minutes, takes five wrong tries and is re-sent at most every thirty
 *     seconds. A code asked for one purpose cannot be spent on another.
 *   - EVERY SESSION BY ITS ID on the person's row: "sign out other devices"
 *     drops the others' ids and a session whose id is gone is refused at its
 *     next request. A password reset forgets every session and every trusted
 *     browser (`sessionVersion`).
 *
 * The person's row is the users table's; nothing here is the Blueprint's.
 *
 * Forge runtime — do not remove.
 */
import { createHmac, randomBytes, randomInt, timingSafeEqual } from "node:crypto";
import { eq } from "drizzle-orm";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { isSecure, sessionCookiePrefix } from "@/lib/session-cookie";

export const PAUSE_AFTER = 5;
export const PAUSE_MS = 15 * 60_000;
export const CODE_TTL_MS = 10 * 60_000;
export const RESEND_MS = 30_000;
export const CODE_ATTEMPTS = 5;
export const TRUST_MS = 30 * 24 * 60 * 60_000;
export const DEVICES_KEPT = 20;

/** What a code was asked for: a two-step sign-in, a password reset, turning two-step on or off. */
export type CodeFor = "sign_in" | "reset" | "two_step";
export type Person = Record<string, any> & { id: string; email: string };

/** Where a person's row is read and written: the users table in an app, a map in a test. */
export interface Store {
  read(id: string): Promise<Person | null>;
  write(id: string, patch: Record<string, unknown>): Promise<void>;
}
const tableStore: Store = {
  async read(id) {
    const [row] = await db.select().from(users).where(eq(users.id, id)).limit(1);
    return (row as Person | undefined) ?? null;
  },
  async write(id, patch) {
    await db.update(users).set(patch as any).where(eq(users.id, id));
  },
};
let store: Store = tableStore;
/** Tests only: read and write rows somewhere else. */
export function __setStore(s: Store | null): void { store = s ?? tableStore; }
export function readPerson(id: string): Promise<Person | null> { return store.read(id); }

const secret = () => process.env.NEXTAUTH_SECRET || "dev-secret";
const mac = (text: string) => createHmac("sha256", secret()).update(text).digest("hex");
const at = (v: unknown) => (v ? new Date(v as string).getTime() : 0);
function same(a: string, b: string): boolean {
  const x = Buffer.from(String(a)), y = Buffer.from(String(b));
  return x.length === y.length && timingSafeEqual(x, y);
}

// ── The refusal the sign-in form reads ─────────────────────────────────────

/** Why a sign-in stopped short of a session. It travels as the `error` that
 *  next-auth hands the form, so it is one JSON string. */
export interface Refusal {
  code: "SIGN_IN_PAUSED" | "TWO_STEP_REQUIRED" | "TWO_STEP_WRONG" | "TWO_STEP_EXPIRED" | "TWO_STEP_TOO_MANY";
  /** SIGN_IN_PAUSED: when sign-in opens again (epoch ms). */
  until?: number;
  /** TWO_STEP_*: where the code went. */
  sentTo?: string;
  /** TWO_STEP_REQUIRED: a code was sent moments ago; another in this many seconds. */
  wait?: number;
  /** The code could not be emailed (no email service), in words. */
  notice?: string;
  /** TWO_STEP_WRONG: tries left on this code. */
  left?: number;
}
export class SignInRefused extends Error {
  constructor(r: Refusal) { super(JSON.stringify(r)); this.name = "SignInRefused"; }
}
/** The form's side: the refusal inside next-auth's `error`, or null for any other error. */
export function refusalOf(error: unknown): Refusal | null {
  if (typeof error !== "string" || !error.startsWith("{")) return null;
  try {
    const r = JSON.parse(error);
    return r && typeof r.code === "string" ? (r as Refusal) : null;
  } catch { return null; }
}

// ── Pause ──────────────────────────────────────────────────────────────────

/** When sign-in opens again for this person, or null when it is open. */
export function pausedUntil(p: Person, now = Date.now()): number | null {
  const until = at(p.signInPausedUntil);
  return until > now ? until : null;
}

/** A wrong password: counted; the fifth in a row pauses sign-in. */
export async function passwordFailed(p: Person, now = Date.now()): Promise<{ pausedUntil: number | null; left: number }> {
  const failed = Number(p.failedSignIns ?? 0) + 1;
  if (failed >= PAUSE_AFTER) {
    const until = now + PAUSE_MS;
    // The count starts again once the pause ends: five more tries, not one.
    await store.write(p.id, { failedSignIns: 0, signInPausedUntil: new Date(until) });
    return { pausedUntil: until, left: 0 };
  }
  await store.write(p.id, { failedSignIns: failed });
  return { pausedUntil: null, left: PAUSE_AFTER - failed };
}

/** A right password: the count back to nought. */
export async function passwordPassed(p: Person): Promise<void> {
  if (Number(p.failedSignIns ?? 0) || p.signInPausedUntil) await store.write(p.id, { failedSignIns: 0, signInPausedUntil: null });
}

// ── Codes ──────────────────────────────────────────────────────────────────

/** The stored form of a code: keyed by the app's secret, the person and the
 *  purpose, so a leaked row cannot be turned back into the code by trying a
 *  million, nor a reset code spent on a sign-in. */
export function codeDigest(id: string, purpose: CodeFor, code: string): string {
  return mac(`code:${id}:${purpose}:${code}`);
}

/** A fresh code for `purpose`, its digest on the row — or how long to wait
 *  when one for the same purpose went out under thirty seconds ago. */
export async function issueCode(p: Person, purpose: CodeFor, now = Date.now()): Promise<{ code: string } | { wait: number }> {
  const last = at(p.signInCodeSentAt);
  if (p.signInCodeFor === purpose && now - last < RESEND_MS) return { wait: Math.ceil((RESEND_MS - (now - last)) / 1000) };
  const code = String(randomInt(0, 1_000_000)).padStart(6, "0");
  await store.write(p.id, {
    signInCodeHash: codeDigest(p.id, purpose, code), signInCodeFor: purpose,
    signInCodeExpiresAt: new Date(now + CODE_TTL_MS), signInCodeSentAt: new Date(now), signInCodeAttempts: 0,
  });
  return { code };
}

const MAIL: Record<CodeFor, { subject: (c: string) => string; body: (c: string) => string }> = {
  sign_in: {
    subject: (c) => `${c} is your sign-in code`,
    body: (c) => `Your sign-in code is ${c}. It expires in 10 minutes. If you did not just enter your password, change it now.`,
  },
  reset: {
    subject: (c) => `${c} is your password reset code`,
    body: (c) => `Your password reset code is ${c}. It expires in 10 minutes. If you did not ask to reset your password, ignore this email.`,
  },
  two_step: {
    subject: (c) => `${c} is your verification code`,
    body: (c) => `Your code to change two-step sign-in is ${c}. It expires in 10 minutes.`,
  },
};

/** Issue a code and email it to the person's own address, by the step a
 *  process sends with. `notice` says it was not emailed, when it was not. */
export async function sendCode(p: Person, purpose: CodeFor, now = Date.now()): Promise<{ sentTo: string; wait?: number; notice?: string }> {
  const issued = await issueCode(p, purpose, now);
  if ("wait" in issued) return { sentTo: p.email, wait: issued.wait };
  const wf = await import("@/lib/workflows");
  wf.registerDefaultActions();
  const send = wf.getActionHandler("send_email");
  let notice: string | undefined;
  if (send) {
    const out: any = await send({
      to: p.email, toTheirOwnAddress: true, subject: MAIL[purpose].subject(issued.code), body: MAIL[purpose].body(issued.code),
    }, { input: {}, variables: {}, log: [] } as any);
    if (!out?.sent) notice = String(out?.notice ?? out?.reason ?? "the code could not be sent: no email service is connected");
  } else {
    notice = "the code could not be sent: no email service is connected";
  }
  return { sentTo: p.email, ...(notice ? { notice } : {}) };
}

export type CodeCheck =
  | { ok: true }
  | { ok: false; code: "NO_CODE" | "EXPIRED" | "TOO_MANY" | "WRONG_CODE" | "MALFORMED"; left?: number };

/** The code entered, against the one in flight for `purpose`. A match spends
 *  it; a wrong one costs a try; a malformed one costs nothing. */
export async function checkCode(p: Person, purpose: CodeFor, entered: unknown, now = Date.now()): Promise<CodeCheck> {
  const digits = String(entered ?? "").replace(/\D/g, "");
  if (digits.length !== 6) return { ok: false, code: "MALFORMED" };
  if (!p.signInCodeHash || p.signInCodeFor !== purpose) return { ok: false, code: "NO_CODE" };
  if (at(p.signInCodeExpiresAt) < now) return { ok: false, code: "EXPIRED" };
  const tries = Number(p.signInCodeAttempts ?? 0);
  if (tries >= CODE_ATTEMPTS) return { ok: false, code: "TOO_MANY", left: 0 };
  if (!same(codeDigest(p.id, purpose, digits), String(p.signInCodeHash))) {
    await store.write(p.id, { signInCodeAttempts: tries + 1 });
    const left = CODE_ATTEMPTS - tries - 1;
    return left > 0 ? { ok: false, code: "WRONG_CODE", left } : { ok: false, code: "TOO_MANY", left: 0 };
  }
  await store.write(p.id, { signInCodeHash: null, signInCodeFor: null, signInCodeExpiresAt: null, signInCodeAttempts: 0 });
  return { ok: true };
}

/** A failed check, in words. */
export function codeProblem(c: CodeCheck): string {
  if (c.ok) return "";
  switch (c.code) {
    case "MALFORMED": return "Enter the 6-digit code from the email.";
    case "NO_CODE": return "Ask for a code first.";
    case "EXPIRED": return "That code has expired. Ask for a new one.";
    case "TOO_MANY": return "Too many wrong codes. Ask for a new one.";
    default: return `That code is not right. ${c.left} ${c.left === 1 ? "try" : "tries"} left.`;
  }
}

// ── A trusted browser ──────────────────────────────────────────────────────

/** One cookie per person, so two people sharing a browser each keep theirs. */
export function trustCookieName(p: Person): string {
  return `${sessionCookiePrefix()}.trusted-${mac(`trusted:${p.id}`).slice(0, 12)}`;
}

function trustSignature(p: Person, expires: number): string {
  return mac(`trust:${p.id}:${expires}:${Number(p.sessionVersion ?? 0)}`);
}

/** The cookie that skips the code on this browser for thirty days. Signed
 *  with the app's secret over the person, its expiry and the session
 *  version, so a reset or "sign out other devices" withdraws it. */
export function trustCookie(p: Person, now = Date.now()) {
  const expires = now + TRUST_MS;
  return {
    name: trustCookieName(p),
    value: `${expires}.${trustSignature(p, expires)}`,
    options: { httpOnly: true, sameSite: "lax" as const, path: "/", secure: isSecure(), maxAge: Math.floor(TRUST_MS / 1000) },
  };
}

function cookieValue(header: string, name: string): string | null {
  for (const part of String(header ?? "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i).trim() === name) return decodeURIComponent(part.slice(i + 1).trim());
  }
  return null;
}

/** This browser was trusted by this person, within thirty days, since their last reset. */
export function trusted(p: Person, cookieHeader: string, now = Date.now()): boolean {
  const value = cookieValue(cookieHeader, trustCookieName(p));
  if (!value) return false;
  const [expires, signature] = value.split(".");
  const exp = Number(expires);
  return Number.isFinite(exp) && exp > now && exp - now <= TRUST_MS && same(signature ?? "", trustSignature(p, exp));
}

/** Set the trusted-browser cookie on the response being written (a route
 *  handler, next-auth's own included). */
export async function trustThisBrowser(p: Person, now = Date.now()): Promise<void> {
  const { cookies } = await import("next/headers");
  const c = trustCookie(p, now);
  (await cookies()).set(c.name, c.value, c.options);
}

// ── Sessions ───────────────────────────────────────────────────────────────

export interface Device { id: string; agent: string; at: string; via: string }

/** "Chrome on macOS": enough to recognise a device, nothing more kept. */
export function agentOf(ua: unknown): string {
  const s = String(ua ?? "");
  if (!s) return "";
  const browser = /Edg\//.test(s) ? "Edge" : /OPR\/|Opera/.test(s) ? "Opera" : /Firefox\//.test(s) ? "Firefox"
    : /Chrome\//.test(s) ? "Chrome" : /Safari\//.test(s) ? "Safari" : /node|undici|curl/i.test(s) ? "A script" : "A browser";
  const os = /iPhone|iPad|iOS/.test(s) ? "iOS" : /Android/.test(s) ? "Android" : /Mac OS X|Macintosh/.test(s) ? "macOS"
    : /Windows/.test(s) ? "Windows" : /Linux/.test(s) ? "Linux" : "";
  return os ? `${browser} on ${os}` : browser;
}

export function devicesOf(p: Person | null): Device[] {
  const list = p?.signedInDevices;
  return Array.isArray(list) ? list.filter((d): d is Device => !!d && typeof d.id === "string") : [];
}

/** A new session: its id on the person's row, newest first, the oldest let go past twenty. */
export async function addDevice(p: Person, how: { agent?: unknown; via: string }, now = Date.now()): Promise<string> {
  const id = randomBytes(12).toString("base64url");
  const fresh: Device = { id, agent: agentOf(how.agent), at: new Date(now).toISOString(), via: how.via };
  await store.write(p.id, { signedInDevices: [fresh, ...devicesOf(p)].slice(0, DEVICES_KEPT) });
  return id;
}

/** Signing out: the session's id off the row. */
export async function dropDevice(personId: string, sid: string): Promise<void> {
  const p = await store.read(personId);
  if (!p) return;
  const list = devicesOf(p);
  if (list.some((d) => d.id === sid)) await store.write(personId, { signedInDevices: list.filter((d) => d.id !== sid) });
}

/** Sign out every other session: only `sid` stays, and the version moves on
 *  so a session from before ids and every trusted browser are withdrawn too. */
export async function keepOnly(p: Person, sid: string): Promise<number> {
  const version = Number(p.sessionVersion ?? 0) + 1;
  await store.write(p.id, { signedInDevices: devicesOf(p).filter((d) => d.id === sid), sessionVersion: version });
  return version;
}

/** The session is still one this person holds: its id is on their row — or,
 *  a session from before ids, the version it was issued under is current. */
export function stillSignedIn(p: Person | null, t: { sid?: unknown; sv?: unknown }): boolean {
  if (!p) return false;
  if ("isActive" in p && p.isActive === false) return false;
  if (typeof t.sid === "string" && t.sid) return devicesOf(p).some((d) => d.id === t.sid);
  return Number(t.sv ?? 0) === Number(p.sessionVersion ?? 0);
}

/** A password set by a reset code: the pause lifted, every session and
 *  trusted browser withdrawn, the address proven by the code. */
export function afterReset(p: Person, passwordHash: string): Record<string, unknown> {
  return {
    password: passwordHash, failedSignIns: 0, signInPausedUntil: null,
    signedInDevices: [], sessionVersion: Number(p.sessionVersion ?? 0) + 1,
    ...(p.emailVerification === "pending" ? { emailVerification: "verified" } : {}),
  };
}

/** The columns of the users row that are the sign-in's alone: never in a
 *  session, never answered by the data API. */
export const SIGN_IN_COLUMNS = [
  "password", "passwordHash", "emailCodeHash", "emailCodeExpiresAt", "emailCodeSentAt", "emailCodeAttempts",
  "signInCodeHash", "signInCodeFor", "signInCodeExpiresAt", "signInCodeSentAt", "signInCodeAttempts",
  "failedSignIns", "signInPausedUntil", "signedInDevices", "sessionVersion",
] as const;

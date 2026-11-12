/**
 * The SHIPPED lib/sign-in-guard.ts — what stands between a right password and
 * a session:
 *
 *   - five wrong passwords in a row pause the address for fifteen minutes, the
 *     right one included; a right one sets the count back;
 *   - a code is kept only as a keyed digest, expires in ten minutes, takes five
 *     wrong tries, is re-sent at most every thirty seconds, and a code asked
 *     for one purpose is not spent on another;
 *   - a trusted browser is a signed cookie for thirty days that a reset (the
 *     session version) withdraws, and a forged or foreign one is not trusted;
 *   - a session is held while its id is on the person's row; signing out the
 *     others keeps only this one; a reset forgets them all.
 *
 * The person's row lives in a map here (`__setStore`); the users table is the
 * app's.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

(globalThis as any).__mailed = [] as any[];
(globalThis as any).__cookies = [] as any[];

installHarness({
  stubs: {
    "@/db": "export const db = {};",
    "@/db/schema/user": "export const users = { id: 'id' };",
    "drizzle-orm": "export const eq = () => ({});",
    "@/lib/workflows": `export const registerDefaultActions = () => {};
      export const getActionHandler = (n) => n === "send_email" ? async (c) => { globalThis.__mailed.push(c); return { sent: false, notice: "no email service is connected" }; } : null;`,
    "next/headers": "export const cookies = async () => ({ set: (n, v, o) => globalThis.__cookies.push({ n, v, o }) });",
  },
  redirect: { "@/lib/session-cookie": new URL("../../app-foundation/src/lib/session-cookie.ts", import.meta.url).pathname },
});

process.env.NEXTAUTH_SECRET = "this-app";
const g: any = await import("../../app-foundation/src/lib/sign-in-guard.ts");

const rows = new Map<string, any>();
g.__setStore({
  read: async (id: string) => (rows.has(id) ? { ...rows.get(id) } : null),
  write: async (id: string, patch: any) => { rows.set(id, { ...rows.get(id), ...patch }); },
});
const person = (id: string) => ({ ...rows.get(id) });
rows.set("p1", { id: "p1", email: "ann@acme.test", failedSignIns: 0, signInPausedUntil: null, sessionVersion: 0, signedInDevices: [] });
const T0 = Date.UTC(2026, 10, 12, 9, 0, 0);

// ── the pause ──
for (let i = 1; i <= 4; i++) {
  const f = await g.passwordFailed(person("p1"), T0);
  ok(f.pausedUntil === null && f.left === 5 - i, `wrong password ${i}: not paused, ${5 - i} left`);
}
const fifth = await g.passwordFailed(person("p1"), T0);
eqJson(fifth, { pausedUntil: T0 + 15 * 60_000, left: 0 }, "the fifth wrong password in a row pauses for fifteen minutes");
eqJson(g.pausedUntil(person("p1"), T0 + 60_000), T0 + 15 * 60_000, "a minute later it is still paused, until then");
eqJson(g.pausedUntil(person("p1"), T0 + 15 * 60_000 + 1), null, "after fifteen minutes it is open");
eqJson(person("p1").failedSignIns, 0, "the count starts again after a pause: five more tries, not one");
await g.passwordFailed(person("p1"), T0); await g.passwordFailed(person("p1"), T0);
await g.passwordPassed(person("p1"));
eqJson([person("p1").failedSignIns, person("p1").signInPausedUntil], [0, null], "a right password sets the count back to nought");

// ── codes ──
const issued = await g.issueCode(person("p1"), "sign_in", T0);
ok(/^\d{6}$/.test(issued.code), "a six-digit code");
const stored = person("p1").signInCodeHash;
ok(stored && stored !== issued.code && !String(stored).includes(issued.code), "only a digest is stored, never the code");
ok(stored !== require256(issued.code), "the digest is keyed: a plain sha-256 of the code would be undone by trying a million");
eqJson(await g.issueCode(person("p1"), "sign_in", T0 + 10_000), { wait: 20 }, "a new code for the same purpose waits thirty seconds");
eqJson((await g.checkCode(person("p1"), "reset", issued.code, T0)).code, "NO_CODE", "a sign-in code is not spent on a reset");
eqJson((await g.checkCode(person("p1"), "sign_in", "12a", T0)).code, "MALFORMED", "a malformed code costs no try");
const wrong = issued.code === "000000" ? "111111" : "000000";
eqJson(await g.checkCode(person("p1"), "sign_in", wrong, T0), { ok: false, code: "WRONG_CODE", left: 4 }, "a wrong code costs a try");
eqJson(await g.checkCode(person("p1"), "sign_in", issued.code, T0 + 11 * 60_000), { ok: false, code: "EXPIRED" }, "after ten minutes the code has expired");
eqJson(await g.checkCode(person("p1"), "sign_in", issued.code, T0 + 60_000), { ok: true }, "the right code within ten minutes passes");
eqJson((await g.checkCode(person("p1"), "sign_in", issued.code, T0 + 61_000)).code, "NO_CODE", "and is spent: it does not pass twice");

const again = await g.issueCode(person("p1"), "reset", T0 + 5_000);
ok("code" in again, "a code for another purpose is not held back by the thirty seconds");
for (let i = 0; i < 4; i++) await g.checkCode(person("p1"), "reset", again.code === "000000" ? "111111" : "000000", T0 + 6_000);
eqJson(await g.checkCode(person("p1"), "reset", again.code === "000000" ? "111111" : "000000", T0 + 6_000), { ok: false, code: "TOO_MANY", left: 0 }, "the fifth wrong try uses the code up");
eqJson((await g.checkCode(person("p1"), "reset", again.code, T0 + 7_000)).code, "TOO_MANY", "after five wrong tries even the right code is refused");

(globalThis as any).__mailed.length = 0;
const sent = await g.sendCode(person("p1"), "two_step", T0 + 60_000);
const mail = (globalThis as any).__mailed[0];
ok(mail?.to === "ann@acme.test" && mail?.toTheirOwnAddress === true && /^\d{6} is your verification code$/.test(mail.subject), "the code is emailed to the person's own address");
eqJson([sent.sentTo, sent.notice], ["ann@acme.test", "no email service is connected"], "a code that was not emailed says so");

// ── the refusal the form reads ──
const r = new g.SignInRefused({ code: "SIGN_IN_PAUSED", until: 123 });
eqJson([r.name, g.refusalOf(r.message)], ["SignInRefused", { code: "SIGN_IN_PAUSED", until: 123 }], "a refusal travels as next-auth's error and reads back");
eqJson(g.refusalOf("CredentialsSignin"), null, "a plain wrong password is not a refusal");

// ── a trusted browser ──
const c = g.trustCookie(person("p1"), T0);
ok(c.options.httpOnly && c.options.maxAge === 30 * 24 * 3600 && c.name.includes(".trusted-"), "httpOnly, thirty days, this app's prefix");
const header = `other=1; ${c.name}=${c.value}`;
ok(g.trusted(person("p1"), header, T0 + 29 * 24 * 3600_000), "trusted on day 29");
ok(!g.trusted(person("p1"), header, T0 + 31 * 24 * 3600_000), "not on day 31");
ok(!g.trusted(person("p1"), `${c.name}=${Number(c.value.split(".")[0]) + 1}.${c.value.split(".")[1]}`, T0), "an expiry moved by hand breaks the signature");
rows.set("p2", { id: "p2", email: "bob@acme.test", sessionVersion: 0 });
ok(!g.trusted(person("p2"), `${g.trustCookieName(person("p2"))}=${c.value}`, T0), "one person's trust is not another's");
process.env.NEXTAUTH_SECRET = "another-app";
ok(!g.trusted(person("p1"), `${c.name}=${c.value}`, T0), "another app's secret does not trust it");
process.env.NEXTAUTH_SECRET = "this-app";

// ── sessions ──
const s1 = await g.addDevice(person("p1"), { agent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit Chrome/131.0 Safari/537.36", via: "password" }, T0);
const s2 = await g.addDevice(person("p1"), { agent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1", via: "password" }, T0 + 1);
eqJson(g.devicesOf(person("p1")).map((d: any) => d.agent), ["Safari on iOS", "Chrome on macOS"], "each session listed, newest first, as a device a person recognises");
ok(g.stillSignedIn(person("p1"), { sid: s1 }) && g.stillSignedIn(person("p1"), { sid: s2 }), "both sessions are held");
ok(!g.stillSignedIn(person("p1"), { sid: "made-up" }), "an id that is not on the row is not");
ok(g.stillSignedIn(person("p1"), { sv: 0 }), "a session from before ids holds under the current version");
ok(g.trusted(person("p1"), header, T0 + 1), "(the browser is trusted before signing out the others)");
await g.keepOnly(person("p1"), s2);
ok(g.stillSignedIn(person("p1"), { sid: s2 }) && !g.stillSignedIn(person("p1"), { sid: s1 }), "signing out the others keeps only this one");
ok(!g.stillSignedIn(person("p1"), { sv: 0 }), "and withdraws a session from before ids");
ok(!g.trusted(person("p1"), header, T0 + 1), "and every trusted browser");
await g.dropDevice("p1", s2);
ok(!g.stillSignedIn(person("p1"), { sid: s2 }), "signing out takes the id off the row");
for (let i = 0; i < 25; i++) await g.addDevice(person("p1"), { agent: "", via: "password" }, T0 + i);
eqJson(g.devicesOf(person("p1")).length, 20, "twenty sessions are kept; the oldest goes");
ok(!g.stillSignedIn({ ...person("p1"), isActive: false }, { sid: g.devicesOf(person("p1"))[0].id }), "an account switched off holds no session");

const after = g.afterReset({ ...person("p1"), emailVerification: "pending", signInPausedUntil: new Date() }, "$2a$12$hash");
eqJson([after.failedSignIns, after.signInPausedUntil, after.signedInDevices, after.sessionVersion, after.emailVerification],
       [0, null, [], 2, "verified"], "a reset lifts the pause, forgets every session, moves the version on and proves the address");

ok(["password", "signInCodeHash", "emailCodeHash", "signedInDevices", "sessionVersion", "failedSignIns"].every((c) => g.SIGN_IN_COLUMNS.includes(c)),
   "the sign-in's own columns are named for the session and the data API to leave out");

function require256(code: string): string {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { createHash } = (globalThis as any).process.getBuiltinModule("node:crypto");
  return createHash("sha256").update(code).digest("hex");
}

done("sign-in guard");

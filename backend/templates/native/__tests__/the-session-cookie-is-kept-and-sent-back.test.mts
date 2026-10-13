/**
 * The cookie jar the native SDK keeps beside the platform's: what a response's
 * Set-Cookie headers become, what is sent back to which address, what expires
 * or is deleted, what a restart restores — and the chunked secure-storage layer
 * that holds it (a session token with a profile is several kilobytes).
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();
const { CookieJar, parseSetCookie, splitSetCookie, chunkedStore, GUEST_COOKIE } = await import("../src/sdk/cookies.ts");

console.log("splitting a joined Set-Cookie header");
eqJson(splitSetCookie("a=1; Path=/, b=2; Path=/x"), ["a=1; Path=/", "b=2; Path=/x"], "two cookies in one header");
eqJson(splitSetCookie("a=1; Expires=Wed, 21 Oct 2099 07:28:00 GMT; Path=/, b=2"), ["a=1; Expires=Wed, 21 Oct 2099 07:28:00 GMT; Path=/", "b=2"],
  "the comma inside an Expires date does not split");
eqJson(splitSetCookie(null), [], "no header, no cookies");

console.log("parsing one cookie");
const NOW = Date.parse("2026-01-01T00:00:00Z");
let c = parseSetCookie("sid=abc=; Path=/app; Secure; HttpOnly; Max-Age=60", NOW)!;
eqJson([c.name, c.value, c.path, c.secure, c.expires], ["sid", "abc=", "/app", true, NOW + 60_000], "name, value (with '='), path, secure, max-age");
c = parseSetCookie("sid=1; Expires=Wed, 21 Oct 2099 07:28:00 GMT; Max-Age=10", NOW)!;
eqJson(c.expires, NOW + 10_000, "Max-Age wins over Expires");
ok(parseSetCookie("=novalue", NOW) === null && parseSetCookie("garbage", NOW) === null, "a line that is not a cookie is nothing");

console.log("the jar");
let t = NOW;
const jar = new CookieJar([], () => t);
ok(jar.absorb(["forge-x.session-token=S1; Path=/; HttpOnly", "forge-x.csrf-token=C1; Path=/"]) === true, "a new cookie changes the jar");
ok(jar.absorb("forge-x.session-token=S1; Path=/; HttpOnly") === false, "the same cookie again changes nothing (nothing to persist)");
eqJson(jar.header("http://localhost:3000/api/read/list"), "forge-x.session-token=S1; forge-x.csrf-token=C1", "sent back on any path under /");
jar.absorb("forge-x.session-token=S2; Path=/");
ok(jar.header("http://localhost:3000/").includes("session-token=S2") && !jar.header("http://localhost:3000/").includes("S1"), "a new value replaces the old");

jar.absorb("secure=1; Path=/; Secure");
ok(!jar.header("http://app.test/x").includes("secure=1"), "a Secure cookie is not sent over http");
ok(jar.header("https://app.test/x").includes("secure=1"), "a Secure cookie is sent over https");

jar.absorb("scoped=1; Path=/api/private");
ok(jar.header("https://app.test/api/private/x").includes("scoped=1"), "a path-scoped cookie goes to its path");
ok(!jar.header("https://app.test/api/privateer").includes("scoped=1") && !jar.header("https://app.test/other").includes("scoped=1"), "…and not to a path that merely shares its prefix");

jar.absorb("forge-x.csrf-token=; Path=/; Max-Age=0");
ok(!jar.header("https://app.test/").includes("csrf-token"), "Max-Age=0 deletes the cookie");
jar.absorb("short=1; Path=/; Max-Age=30");
ok(jar.header("https://app.test/").includes("short=1"), "a cookie with a lifetime is sent");
t += 31_000;
ok(!jar.header("https://app.test/").includes("short=1"), "…and is gone when it has expired");

jar.absorb(`${GUEST_COOKIE}=g1; Path=/; Max-Age=7776000`);
jar.clear([GUEST_COOKIE]);
eqJson(jar.header("https://app.test/"), `${GUEST_COOKIE}=g1`, "sign-out clears the account's cookies and keeps the guest token");
jar.clear();
eqJson(jar.size, 0, "clear() forgets everything");

console.log("saving and restoring");
const a = new CookieJar([], () => t);
a.absorb(["s=1; Path=/; Max-Age=3600", "k=2; Path=/"]);
const saved = a.toJSON();
const b = new CookieJar([], () => t);
b.load(saved);
eqJson(b.header("https://app.test/"), a.header("https://app.test/"), "a restart restores the same cookies");
const c2 = new CookieJar([], () => t);
c2.absorb("s=NEW; Path=/");
c2.load(saved);
ok(c2.header("https://app.test/").includes("s=NEW"), "a cookie set while the saved ones were loading is not overwritten by the old value");
const d = new CookieJar([], () => t);
d.load("not json");
d.load('{"a":1}');
eqJson(d.size, 0, "unreadable saved text is an empty jar, not a crash");
const expired = new CookieJar([], () => t);
expired.load(JSON.stringify([{ name: "old", value: "1", path: "/", secure: false, expires: t - 1 }]));
eqJson(expired.size, 0, "a saved cookie that has since expired is dropped");

console.log("chunked secure storage");
const mem = new Map<string, string>();
const kv = {
  get: async (k: string) => mem.get(k) ?? null,
  set: async (k: string, v: string) => { mem.set(k, v); },
  remove: async (k: string) => { mem.delete(k); },
};
const store = chunkedStore(kv, "jar", 10);
const text = "x".repeat(35);
await store.write(text);
eqJson([mem.size, await store.read()], [5, text], "35 characters in pieces of 10: four parts and a count, joined on read");
await store.write("short");
eqJson([await store.read(), mem.has("jar.1")], ["short", false], "a shorter write removes the parts it no longer needs");
mem.delete("jar.0");
eqJson(await store.read(), null, "a torn write reads as nothing, not as half a jar");
await store.write("again");
await store.remove();
eqJson([await store.read(), mem.size], [null, 0], "remove leaves nothing behind");

done("session cookie");

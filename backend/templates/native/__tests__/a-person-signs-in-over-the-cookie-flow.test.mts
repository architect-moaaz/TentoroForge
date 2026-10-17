/**
 * The sign-in the native app does, over an injected fetch standing in for the
 * generated app: csrf -> credentials callback (urlencoded, json=true) -> session
 * read as the proof; the cookies each step sets and the next one carries; a
 * wrong password, a session that was not kept, an app with password sign-in off,
 * no network; sign-out (keeps the guest token); the 401 that means "signed out"
 * and the 401s that do not; choosing an organisation.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { fakeApp, offline } from "./_fake-app.mts";

installHarness();
const { CookieJar } = await import("../src/sdk/cookies.ts");
const { createClient } = await import("../src/sdk/http.ts");
const signin = await import("../src/sdk/signin.ts");

function client(app: { fetch: any }, extra: { onSignedOut?: () => void; onJarChange?: () => void } = {}) {
  return createClient({ baseUrl: "http://app.test:3000", fetch: app.fetch, jar: new CookieJar(), ...extra });
}

console.log("a right password");
{
  const app = fakeApp();
  const c = client(app);
  const out = await signin.signInWithPassword(c, "ada@x.io", "pw");
  ok(out.ok && out.user.email === "ada@x.io" && out.user.role === "Admin", "signed in as the person the session names");
  eqJson(app.seen.map((s) => `${s.method} ${s.path}`), ["GET /api/auth/csrf", "POST /api/auth/callback/credentials", "GET /api/auth/session"],
    "the sequence is csrf, callback, session — nothing else");
  const post = app.seen[1];
  const form = new URLSearchParams(post.body);
  eqJson([form.get("csrfToken"), form.get("email"), form.get("password"), form.get("json")], ["tok123", "ada@x.io", "pw", "true"], "the callback carries csrfToken, email, password and json=true");
  ok(post.cookie.includes("forge-test.csrf-token=tok123"), "the csrf cookie from step one is sent with step two");
  ok(app.seen[2].cookie.includes("forge-test.session-token=ok"), "the session cookie from step two is sent with step three");
  eqJson(app.seen.map((s) => s.credentials), ["include", "omit", "omit"], "once the jar holds cookies the platform's jar is left out of it (one copy)");
}

console.log("a password with characters that must be encoded");
{
  const app = fakeApp();
  await signin.signInWithPassword(client(app), "ada@x.io", "p&w=1 %");
  eqJson(new URLSearchParams(app.seen[1].body).get("password"), "p&w=1 %", "&, = and % survive the form encoding");
}

console.log("a wrong password");
{
  const app = fakeApp();
  const out = await signin.signInWithPassword(client(app), "ada@x.io", "nope");
  ok(!out.ok && out.reason === "wrong" && /do not match/.test(out.message), "says so in words");
  ok(!app.seen.some((s) => s.path === "/api/auth/session"), "does not even ask for a session");
}

console.log("a session the platform did not keep");
{
  const app = fakeApp({ dropCookies: true });
  const out = await signin.signInWithPassword(client(app), "ada@x.io", "pw");
  ok(!out.ok && out.reason === "unconfirmed", "the callback said yes but the session read says nobody: not signed in");
}

console.log("no network");
{
  const out = await signin.signInWithPassword(client({ fetch: offline }), "ada@x.io", "pw");
  ok(!out.ok && out.reason === "network" && /could not be reached/.test(out.message), "a sentence, not a throw");
  let threw = false;
  try { await signin.fetchSession(client({ fetch: offline })); } catch { threw = true; }
  ok(threw, "reading the session offline is 'unknown' (throws), never 'signed out'");
}

console.log("what the app offers");
{
  eqJson((await signin.fetchMethods(client(fakeApp()))).password, true, "password on");
  eqJson((await signin.fetchMethods(client(fakeApp({ password: false })))).password, false, "password off is reported, so the login screen can say so");
  const old = { fetch: async () => new Response("nope", { status: 404 }) };
  eqJson(await signin.fetchMethods(client(old)), { password: true, magicLink: false, sso: [] }, "an app without the route is assumed to have a password form");
}

console.log("a session, signed out, and the 401 rule");
{
  const app = fakeApp();
  let signedOutSignals = 0;
  const c = client(app, { onSignedOut: () => { signedOutSignals++; } });
  eqJson(await signin.fetchSession(c), null, "no cookie, no session");
  eqJson(signedOutSignals, 0, "…and that is not a 'signed-out' event (an /api/auth call)");
  const read = await c.json("/api/read/list", { body: { entity: "Order" } });
  eqJson([read.status, signedOutSignals], [401, 1], "a 401 on a read signals signed-out");
  await signin.signInWithPassword(c, "ada@x.io", "pw");
  const after = await c.json<{ rows: unknown[] }>("/api/read/list", { body: { entity: "Order" } });
  eqJson([after.status, after.body?.rows.length, signedOutSignals], [200, 1, 1], "after sign-in the same read answers and no further signal");
  await signin.signOutRequest(c);
  eqJson(c.jar.size, 0, "sign-out forgets the cookies");
  eqJson(await signin.fetchSession(c), null, "…and there is no session");
}

console.log("the guest token");
{
  const app = fakeApp();
  const c = client(app);
  const first = await c.json("/api/workflows/WF-OK/execute", { body: { input: {} } });
  ok(first.ok && c.jar.get("forge-guest") === "11111111-2222-3333-4444-555555555555", "the first workflow run mints the guest cookie and the jar keeps it");
  await c.json("/api/workflows/WF-OK/execute", { body: { input: {} } });
  ok(app.seen[app.seen.length - 1].cookie.includes("forge-guest="), "the next run sends it back");
  await signin.signInWithPassword(c, "ada@x.io", "pw");
  await signin.signOutRequest(c);
  eqJson(c.jar.get("forge-guest"), "11111111-2222-3333-4444-555555555555", "a sign-out keeps the visitor's guest token");
}

console.log("choosing an organisation");
{
  const app = fakeApp({ orgs: [{ orgId: "o1", orgName: "Acme" }, { orgId: "o2", orgName: "Beta" }] });
  const c = client(app);
  await signin.signInWithPassword(c, "ada@x.io", "pw");
  const list = await signin.fetchOrganisations(c);
  eqJson([list.organisations.map((o) => o.orgId), list.activeOrgId], [["o1", "o2"], null], "the organisations the person may act in, none active yet");
  app.seen.length = 0;
  const out = await signin.switchOrganisation(c, "o2");
  ok(out.ok && out.user?.activeOrgId === "o2", "after choosing, the session says which organisation is active");
  eqJson(app.seen.map((s) => `${s.method} ${s.path}`), ["POST /api/org", "GET /api/auth/csrf", "POST /api/auth/session", "GET /api/auth/session"],
    "POST /api/org, then the session token is refreshed (next-auth's update()), then read");
  eqJson(JSON.parse(app.seen[2].body), { csrfToken: "tok123", data: {} }, "the refresh carries the csrf token");
  const bad = await signin.switchOrganisation(c, "zzz");
  ok(!bad.ok && /do not belong/.test(bad.message), "an organisation the person is not in is refused, with the server's sentence");
  eqJson((await signin.fetchOrganisations(client(fakeApp()))).organisations, [], "an app with one organisation lists none");
}

done("sign-in");

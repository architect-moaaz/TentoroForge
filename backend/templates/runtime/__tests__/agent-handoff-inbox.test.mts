/**
 * Who may open the handoff inbox, and whose handoffs it shows, run from the SHIPPED api-agent/handoffs-route.ts,
 * agents/handoff.ts and agents/handoff-store.ts against an in-memory database (__tests__/_fake-db.mts).
 *
 * What is pinned: with nobody named to handle handoffs, nobody may open the inbox (it used to be every signed-in person,
 * so any customer of an app with open sign-up could read other customers' transcripts and contact details, answer
 * them as "the team" and resolve them); a customer is never let in; and in an app of several organisations a handler
 * lists, reads, claims, replies to, assigns and resolves only the handoffs of the organisation they act in (a platform
 * role reaches all; a person who acts in none reaches none), while an app of one organisation is unchanged.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import { installHarness, ok, eqJson, done } from "./_harness.mts";
import { createFakeDb, fakeDbStubs } from "./_fake-db.mts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const agents = (f: string) => path.resolve(HERE, "../agents", f);

const fake = createFakeDb();
const G = globalThis as any;
G.__fake = fake;
G.__agents = [] as any[];
G.__session = null;
G.__tenancy = { on: true };

const table = (name: string) => `new Proxy({ __table: ${JSON.stringify(name)} }, { get: (t, p) => (p in t ? t[p] : { __col: p, __table: ${JSON.stringify(name)} }) })`;
installHarness({
  redirect: {
    "@/lib/agents/handoff": agents("handoff.ts"),
    "@/lib/agents/handoff-store": agents("handoff-store.ts"),
  },
  stubs: {
    ...fakeDbStubs(),
    "@/db/schema/_forge_agent": `export const forgeAgentConversations = ${table("conversations")}; export const forgeAgentMessages = ${table("messages")};`,
    "@/auth": "export const auth = async () => (globalThis.__session ? { user: globalThis.__session } : null);",
    "@/agents/registry": "export const AGENTS = globalThis.__agents;",
    "@/lib/agents/store": "export const drizzleStore = { getConversation: async () => null };",
    "@/lib/tenancy": "export async function policy() {} export const tenancyOn = () => globalThis.__tenancy.on; export const isPlatformRole = (r) => r === 'Platform Admin';",
  },
});

const { GET, POST } = await import("../api-agent/handoffs-route.ts");
const { handoffStore, listHandoffs, getHandoff, changeHandoff } = await import("../agents/handoff-store.ts");

const spec = (roles: string[], people: Array<{ id: string }> = []): any => ({
  handlers: { roles, people }, assignment: "queue", questions: [], notify: { inApp: true, email: false, emailUrgentOnly: true }, keywords: [],
});
const agent = (handoff: any): any => ({ id: "support", enabled: true, handoff });
const setAgents = (...a: any[]) => { G.__agents.length = 0; G.__agents.push(...a); };
const as = (u: Record<string, unknown> | null) => { G.__session = u; };

const customerA = { id: "cust-a", role: "Customer", email: "ann@a.test", activeOrgId: "org-a" };
const customerB = { id: "cust-b", role: "Customer", email: "bob@b.test", activeOrgId: "org-b" };
const managerA = { id: "man-a", role: "Manager", email: "m@a.test", activeOrgId: "org-a" };
const managerB = { id: "man-b", role: "Manager", email: "m@b.test", activeOrgId: "org-b" };
const platform = { id: "plat", role: "Platform Admin", email: "p@x.test", activeOrgId: "org-a" };

let created = 0;
async function raise(requestedById: string, orgId: string | null, reason: string, contact: string) {
  created++;
  return handoffStore.create({
    conversationId: `conv-${created}`, agentId: "support", requestedById, requestedByName: null, orgId,
    reason, urgency: "normal", status: "open", contact, summary: `Customer: ${reason}`, assignedToId: null, assignedToName: null, resolutionNote: null,
  } as any);
}

const get = async (qs = "") => {
  const r = await GET(new Request(`http://app.test/api/agent/handoffs${qs}`));
  return { status: r.status, body: (await r.json()) as any };
};
const post = async (body: Record<string, unknown>) => {
  const r = await POST(new Request("http://app.test/api/agent/handoffs", { method: "POST", body: JSON.stringify(body) }));
  return { status: r.status, body: (await r.json()) as any };
};
const ownRows = () => fake.rows.handoffs.map((r: any) => [r.reason, r.status]);

const realError = console.error;
console.error = (...a: unknown[]) => { if (!String(a[0]).startsWith("[api/agent")) realError(...a); }; // the route logs the real cause of a failure for the developer

const a1 = await raise("cust-a", "org-a", "Order 12 never arrived", "ann@a.test, 555-0101");
const b1 = await raise("cust-b", "org-b", "Card charged twice", "bob@b.test, 555-0202");
const free = await raise("cust-x", null, "Signed up without an organisation", "x@x.test");

// ── nobody named: nobody may ──────────────────────────────────────────────

console.log("with nobody named to handle handoffs, nobody may open the inbox");
{
  setAgents(agent(spec([], [])));
  for (const [who, u] of [["a customer", customerA], ["another customer", customerB], ["a manager", managerA], ["a platform admin", platform]] as const) {
    as(u);
    const list = await get();
    ok(list.status === 403 && !JSON.stringify(list.body).includes("555-0"), `${who} cannot list the inbox, and no contact details come back`);
    const one = await get(`?id=${b1.id}`);
    ok(one.status === 403 && !JSON.stringify(one.body).includes("Card charged"), `${who} cannot read one handoff or its transcript`);
    const reply = await post({ id: b1.id, action: "reply", text: "Hello from the team" });
    ok(reply.status === 404 || reply.status === 403, `${who} cannot reply as the team (${reply.status})`);
    const resolve = await post({ id: b1.id, action: "resolve" });
    ok(resolve.status === 404 || resolve.status === 403, `${who} cannot resolve it (${resolve.status})`);
  }
  eqJson(ownRows(), [["Order 12 never arrived", "open"], ["Card charged twice", "open"], ["Signed up without an organisation", "open"]], "and nothing was changed");
  eqJson(fake.rows.messages.length, 0, "and nothing was written into anyone's chat");
  as(null);
  eqJson((await get()).status, 401, "signed out is still 401");
}

// ── named handlers, an app of several organisations ───────────────────────

console.log("a customer is never let in, even when handlers are named");
{
  setAgents(agent(spec(["Manager"])));
  as(customerA);
  eqJson([(await get()).status, (await get(`?id=${a1.id}`)).status, (await post({ id: a1.id, action: "resolve" })).status], [403, 403, 404], "not even their own: the inbox is for the team");
}

console.log("a handler lists, reads, replies to and resolves only their own organisation's handoffs");
{
  setAgents(agent(spec(["Manager"])));
  as(managerA);
  const list = await get();
  eqJson(list.body.handoffs.map((h: any) => h.reason), ["Order 12 never arrived"], "the list holds organisation A's handoff only");
  ok(!JSON.stringify(list.body).includes("Card charged") && !JSON.stringify(list.body).includes("bob@b.test"), "no word of organisation B's reason or contact");
  eqJson((await get("?status=all")).body.handoffs.map((h: any) => h.reason), ["Order 12 never arrived"], "nor under every status");
  eqJson((await get(`?id=${b1.id}`)).status, 404, "another organisation's handoff, asked for by id, is not found");
  eqJson((await get(`?id=${free.id}`)).status, 404, "nor is one that belongs to no organisation");
  const own = await get(`?id=${a1.id}`);
  eqJson([own.status, own.body.handoff.ref], [200, a1.ref], "their own is read");

  eqJson((await post({ id: b1.id, action: "reply", text: "I am the team" })).status, 404, "replying to another organisation's customer is refused");
  eqJson((await post({ id: b1.id, action: "claim" })).status, 404, "so is claiming it");
  eqJson((await post({ id: b1.id, action: "assign", assigneeId: "man-a" })).status, 404, "assigning it");
  eqJson((await post({ id: b1.id, action: "resolve", note: "gone" })).status, 404, "and resolving it");
  eqJson(fake.rows.messages.length, 0, "no message reached organisation B's customer");
  eqJson(fake.rows.handoffs.find((r: any) => r.id === b1.id).status, "open", "and its handoff is untouched");

  const mine = await post({ id: a1.id, action: "reply", text: "Looking into order 12" });
  eqJson([mine.status, mine.body.handoff.status, fake.rows.messages.length], [200, "claimed", 1], "their own is answered and claimed");
  eqJson((await post({ id: a1.id, action: "resolve", note: "sent again" })).body.handoff.status, "resolved", "and resolved");

  as(managerB);
  eqJson((await get()).body.handoffs.map((h: any) => h.reason), ["Card charged twice"], "organisation B's manager sees B's only");
  eqJson((await get(`?id=${a1.id}`)).status, 404, "and not A's, resolved or not");
  eqJson((await get("?status=resolved")).body.handoffs, [], "nor A's resolved ones");
}

console.log("a platform role reaches every organisation, and a person who acts in none reaches none");
{
  setAgents(agent(spec(["Manager", "Platform Admin"])));
  as(platform);
  eqJson((await get("?status=all")).body.handoffs.length, 3, "a platform admin sees all of them, including the one with no organisation");
  eqJson((await get(`?id=${b1.id}`)).status, 200, "and may read B's");
  as({ ...managerA, activeOrgId: null });
  eqJson([(await get()).status, (await get()).body.handoffs, (await get(`?id=${a1.id}`)).status], [200, [], 404], "a manager acting in no organisation sees nothing");
}

console.log("an app of one organisation is unchanged: its handlers see every handoff");
{
  G.__tenancy.on = false;
  setAgents(agent(spec(["Manager"])));
  as({ id: "man-1", role: "Manager", email: "m@one.test" });
  eqJson((await get("?status=all")).body.handoffs.length, 3, "all three are listed");
  eqJson((await get(`?id=${b1.id}`)).status, 200, "and any may be read");
  G.__tenancy.on = true;
}

// ── the store on its own: every read and change names whose handoffs it may reach ──

console.log("the store answers only for the reach it is given");
{
  eqJson((await listHandoffs({ orgId: "org-a" }, { status: "all" })).map((h) => h.ref), [a1.ref], "an organisation's list is its own");
  eqJson((await listHandoffs({ all: true }, { status: "all" })).length, 3, "all reaches every one");
  eqJson(await listHandoffs(null, { status: "all" }), [], "null reaches none");
  eqJson([await getHandoff(b1.id, { orgId: "org-a" }), await getHandoff(b1.id, null)], [null, null], "another organisation's, or no reach: not found");
  eqJson((await getHandoff(b1.id, { orgId: "org-b" }))?.ref, b1.ref, "its own organisation: found");
  eqJson(await getHandoff(free.id, { orgId: "org-a" }), null, "a handoff with no organisation is reached by no organisation");
  eqJson(await changeHandoff(b1.id, { action: "resolve" }, { orgId: "org-a" }), null, "another organisation's cannot be changed");
  eqJson(fake.rows.handoffs.find((r: any) => r.id === b1.id).status, "open", "and is not");
  eqJson((await changeHandoff(b1.id, { action: "claim", by: { id: "man-b" } }, { orgId: "org-b" }))?.status, "claimed", "its own can");
}

done("handoff inbox");

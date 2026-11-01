/**
 * A signed-out visitor to a public assistant is counted like anyone else, from the SHIPPED agents/runtime.ts + visitor.ts.
 *
 * What is pinned: a visitor is limited by their guest cookie and by the address their request came from, with the same
 * limits a signed-in person has; either key being over stops them (clearing cookies does not, nor does a new address
 * with the same cookie); the address is the one the app's own proxy added, never a value the client wrote at the start
 * of X-Forwarded-For; the guest cookie is minted once with the app's usual attributes; two visitors are not mistaken for
 * one; a refused message is not counted; a signed-in person is still counted by their account alone; and an app whose
 * usage table is missing limits nobody.
 *
 * Run: __tests__/run-agent-tests.sh
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();

const { runAgent } = await import("../agents/runtime.ts");
const { memoryStore } = await import("../agents/memory.ts");
const { clientIp, guestFromCookie, visitorKeys, visitorOf } = await import("../agents/visitor.ts");

const GUEST_A = "6f1c2b8e-0000-4000-8000-00000000000a";
const GUEST_B = "6f1c2b8e-0000-4000-8000-00000000000b";
const usage = { inputTokens: 10, outputTokens: 5 };

/** Usage counted per key, like the app's table: a minute is a minute for every key. */
function usageByKey(initial: Record<string, { minute?: number; hour?: number; tokensDay?: number }> = {}) {
  const totals = new Map<string, { minute: number; hour: number; tokensDay: number }>();
  for (const [k, v] of Object.entries(initial)) totals.set(k, { minute: 0, hour: 0, tokensDay: 0, ...v });
  const of = (k: string) => totals.get(k) ?? totals.set(k, { minute: 0, hour: 0, tokensDay: 0 }).get(k)!;
  return {
    totals,
    keys: () => [...totals.keys()].sort(),
    async read(k: string) { return { ...of(k) }; },
    async add(k: string, d: { messages?: number; tokens?: number }) {
      const t = of(k);
      t.minute += d.messages ?? 0; t.hour += d.messages ?? 0; t.tokensDay += d.tokens ?? 0;
    },
  };
}

const config = (limits: Record<string, number> = { perMinute: 2, perHour: 0, tokensPerDay: 0 }): any => ({
  id: "app_assistant", name: "Assistant", enabled: true, model: { maxTokens: 256 }, systemPrompt: "You help.",
  tools: [], memory: { type: "conversation", maxMessages: 12, summarizeAfter: 40 },
  // a PUBLIC assistant: nobody has to sign in
  guardrails: { input: { maxLength: 500, blockPatterns: [], requireAuth: false }, output: { blockPatterns: [], contentFilter: "standard" }, outputRules: [], limits },
  maxTurns: 4, ui: { title: "Assistant", position: "bottom-right" },
});

let modelCalls = 0;
const deps = (usageStore: any): any => ({
  store: memoryStore(), usage: usageStore, runTool: async () => 0,
  async callModel(_r: any, onText: (c: string) => void) { modelCalls++; onText("hi"); return { content: [{ type: "text", text: "hi" }], usage }; },
});

async function visit(usageStore: any, who: { guest?: string; ip?: string; cookie?: string; user?: any } = {}, cfg = config()) {
  const events: any[] = [];
  await runAgent(cfg, {
    message: "hello", conversationId: null, user: who.user ?? null,
    visitor: who.guest || who.ip ? { guest: who.guest ?? null, ip: who.ip ?? null } : undefined,
    cookie: who.cookie ?? "", origin: "",
  }, deps(usageStore), (e: any) => events.push(e));
  return events;
}
const stopped = (ev: any[]) => ev.some((e) => e.type === "blocked");
const answered = (ev: any[]) => ev.at(-1)?.type === "done" && !stopped(ev);

console.log("a signed-out visitor is limited, by the cookie");
{
  const u = usageByKey();
  eqJson([answered(await visit(u, { guest: GUEST_A })), answered(await visit(u, { guest: GUEST_A }))], [true, true], "the first two messages are answered");
  const third = await visit(u, { guest: GUEST_A });
  ok(stopped(third) && /very quickly/.test(third.find((e) => e.type === "blocked").reason), "the third in a minute is stopped, with the usual reason");
  eqJson(u.totals.get(`guest:${GUEST_A}`)!.minute, 2, "and a refused message is not counted as used");
  ok(answered(await visit(u, { guest: GUEST_B })), "another visitor is not affected");
}

console.log("clearing cookies does not reset the address");
{
  const u = usageByKey();
  await visit(u, { guest: GUEST_A, ip: "203.0.113.7" });
  await visit(u, { guest: GUEST_B, ip: "203.0.113.7" });
  const fresh = await visit(u, { guest: "6f1c2b8e-0000-4000-8000-00000000000c", ip: "203.0.113.7" });
  ok(stopped(fresh), "a brand-new cookie from the same address is stopped");
  ok(answered(await visit(u, { guest: "6f1c2b8e-0000-4000-8000-00000000000d", ip: "203.0.113.8" })), "a different address with a new cookie is not");
  const sameCookie = await visit(u, { guest: GUEST_A, ip: "198.51.100.1" });
  ok(answered(sameCookie), "one cookie moving between addresses is still within its own limit (it has used 1 of 2)");
  ok(stopped(await visit(u, { guest: GUEST_A, ip: "198.51.100.2" })), "and stopped by the cookie once that is spent");
  eqJson(u.keys().filter((k) => k.startsWith("ip:")).length >= 3 && u.keys().some((k) => k === "ip:203.0.113.7"), true, "both keys are kept for the day's counts");
}

console.log("the same limits a signed-in person has, including tokens");
{
  const u = usageByKey({ [`guest:${GUEST_A}`]: { tokensDay: 100 } });
  const ev = await visit(u, { guest: GUEST_A }, config({ perMinute: 0, perHour: 0, tokensPerDay: 100 }));
  ok(stopped(ev) && /daily/.test(ev.find((e) => e.type === "blocked").reason), "a visitor over the daily tokens is stopped");
  const ok2 = usageByKey();
  await visit(ok2, { guest: GUEST_A, ip: "203.0.113.9" }, config({ perMinute: 0, perHour: 0, tokensPerDay: 100 }));
  eqJson([ok2.totals.get(`guest:${GUEST_A}`)!.tokensDay, ok2.totals.get("ip:203.0.113.9")!.tokensDay], [15, 15], "the tokens a visitor's answer used are counted against both keys");
  const before = modelCalls;
  await visit(usageByKey({ [`ip:203.0.113.9`]: { minute: 9 } }), { guest: GUEST_A, ip: "203.0.113.9" });
  eqJson(modelCalls, before, "a visitor who is stopped costs no model call");
}

console.log("the cookie is read from the request when the chat route passes nothing else");
{
  const u = usageByKey();
  const cookie = `theme=dark; forge-guest=${GUEST_A}; other=1`;
  await visit(u, { cookie });
  await visit(u, { cookie });
  ok(stopped(await visit(u, { cookie })), "a visitor known only by the Cookie header is limited too");
  eqJson(u.keys(), [`guest:${GUEST_A}`], "under their guest key");
}

console.log("a signed-in person is counted by their account, as before");
{
  const u = usageByKey();
  const who = { user: { id: "u1", role: "member" } };
  await visit(u, { ...who, guest: GUEST_A, ip: "203.0.113.7" });
  await visit(u, { ...who, guest: GUEST_A, ip: "203.0.113.7" });
  ok(stopped(await visit(u, { ...who, guest: GUEST_B, ip: "203.0.113.99" })), "stopped by the account, whatever cookie or address they came with");
  eqJson(u.keys(), ["u1"], "and nothing is counted under a cookie or an address");
}

console.log("a visitor nothing identifies, and an app with no usage table");
{
  const u = usageByKey();
  for (let i = 0; i < 4; i++) ok(answered(await visit(u)), `message ${i + 1} from a visitor with no cookie and no address is answered (there is nothing to count it under)`);
  eqJson(u.keys(), [], "and nothing is counted");
  const broken: any = { async read() { throw new Error('relation "forge_agent_usage" does not exist'); }, async add() { throw new Error("nope"); } };
  for (let i = 0; i < 3; i++) ok(answered(await visit(broken, { guest: GUEST_A, ip: "203.0.113.7" })), `message ${i + 1} with no usage table is answered`);
}

console.log("visitor.ts: the address is the one our own proxy added");
{
  const h = (o: Record<string, string>) => ({ get: (k: string) => o[k.toLowerCase()] ?? null });
  eqJson(clientIp(h({ "x-forwarded-for": "198.51.100.1" }), {}), "198.51.100.1", "one proxy, one address");
  eqJson(clientIp(h({ "x-forwarded-for": "1.1.1.1, 2.2.2.2, 203.0.113.7" }), {}), "203.0.113.7", "what the client wrote at the start is not trusted: the last entry is the proxy's");
  eqJson(clientIp(h({ "x-forwarded-for": "1.1.1.1, 203.0.113.7, 10.0.0.2" }), { FORGE_PROXY_HOPS: "2" }), "203.0.113.7", "with two proxies in a row, the one before the last");
  eqJson(clientIp(h({ "x-forwarded-for": "203.0.113.7" }), { FORGE_PROXY_HOPS: "3" }), "203.0.113.7", "more hops than entries: the first entry");
  eqJson(clientIp(h({ "x-real-ip": "203.0.113.7" }), {}), "203.0.113.7", "x-real-ip when there is no forwarded list");
  eqJson(clientIp(h({}), {}), null, "no proxy header: no address (the cookie alone)");
  eqJson(clientIp(h({ "x-forwarded-for": "'; DROP TABLE x;--" }), {}), null, "anything that is not an address is dropped");
  eqJson(clientIp(h({ "x-forwarded-for": "2001:DB8::1" }), {}), "2001:db8::1", "an IPv6 address is lower-cased");
}

console.log("visitor.ts: the guest cookie");
{
  eqJson(guestFromCookie(`a=b; forge-guest=${GUEST_A}`), GUEST_A, "read from a Cookie header");
  eqJson(guestFromCookie("forge-guest=not-an-id"), null, "a value that is not an id is not one");
  eqJson(guestFromCookie(`xforge-guest=${GUEST_A}`), null, "and a cookie of another name is not it");
  eqJson(visitorKeys({ guest: GUEST_A, ip: "203.0.113.7" }), [`guest:${GUEST_A}`, "ip:203.0.113.7"], "keys: cookie then address");
  eqJson(visitorKeys({}), [], "keys: none when nothing identifies them");

  const first = visitorOf(new Request("https://shop.example/api/agent/chat", { headers: { "x-forwarded-for": "203.0.113.7" } }), {});
  ok(/^[0-9a-f-]{36}$/.test(first.guest) && first.ip === "203.0.113.7", "a visitor with no cookie is given one, and their address is read");
  ok(!!first.setCookie && first.setCookie.startsWith(`forge-guest=${first.guest};`), "the response sets it");
  ok(/HttpOnly/.test(first.setCookie!) && /SameSite=Lax/.test(first.setCookie!) && /Path=\//.test(first.setCookie!) && /Secure/.test(first.setCookie!), "httpOnly, sameSite lax, secure on https");
  const local = visitorOf(new Request("http://localhost:3000/api/agent/chat"), {});
  ok(!/Secure/.test(local.setCookie!), "and not secure on plain http, where a browser would drop it");
  const again = visitorOf(new Request("https://shop.example/api/agent/chat", { headers: { cookie: `forge-guest=${GUEST_A}` } }), {});
  eqJson([again.guest, again.setCookie], [GUEST_A, null], "a visitor who has one keeps it, and is not given another");
  ok(visitorOf(new Request("https://a.example/x"), {}).guest !== visitorOf(new Request("https://a.example/x"), {}).guest, "two visitors are never given the same id");
}

done("visitor limits");

/**
 * The Insights view, live app side: the numbers a live app pushes to the platform, read from the project route
 * `.../agent-definitions/insights/summary` (no Watch live needed), and the key that connects the app.
 *
 * Pinned, in what the builder SEES: the summary is asked first and each fallback (a development app, or the setup state) happens only
 * when it says there is nothing live; one source at a time, named; the five ranges; the freshness line and the never-hidden "events were
 * not accepted" warning; polling (the strip every 5 s, the whole report every 30 s, neither while the tab is hidden or after the view is
 * closed); the live strip in each state; the time series at minute, hour and day size (labels, dense data kept readable, a table with
 * every bucket); the people section; and the key card (create, make a new one after a confirm, remove, shown once and cleared, errors in
 * sentences, copy buttons, and nothing secret in storage or in the console).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiDelete = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { get: (u: string) => apiGet(u), post: (u: string, b?: unknown) => apiPost(u, b), put: vi.fn(), delete: (u: string) => apiDelete(u) },
  ApiError: class extends Error {},
}));

import { AgentInsightsPanel } from "../AgentInsightsPanel";
import { REFRESH_MS, STRIP_REFRESH_MS } from "../useAgentInsights";

// ---------------------------------------------------------------------------
// what the platform sends
// ---------------------------------------------------------------------------

const NOW = Date.now();
const iso = (ms: number) => new Date(ms).toISOString();
const minutesAgo = (m: number) => iso(NOW - m * 60_000);
const KEY = "fik_" + "AbCdEfGh12".repeat(4);
const INGEST = "https://forge.example.com/api/insights/ingest";

function mkSeries(n: number, stepMs: number, startMs: number, withUsd = true) {
  return Array.from({ length: n }, (_, i) => ({
    t: iso(startMs + i * stepMs), turns: (i % 7) + 1, errors: i % 11 === 0 ? 1 : 0, inputTokens: 1000, outputTokens: 200,
    usd: withUsd ? 0.01 * ((i % 5) + 1) : null, activeUsers: (i % 9) + 1,
  }));
}
const LOCAL_10_00 = new Date(2026, 9, 21, 10, 0, 0).getTime();
const UTC_DAY0 = Date.UTC(2026, 8, 23);
const SERIES: Record<string, { granularity: string; points: ReturnType<typeof mkSeries> }> = {
  "1h": { granularity: "minute", points: mkSeries(60, 60_000, LOCAL_10_00) },
  "24h": { granularity: "hour", points: mkSeries(24, 3_600_000, LOCAL_10_00) },
  "7d": { granularity: "hour", points: mkSeries(168, 3_600_000, LOCAL_10_00) },
  "30d": { granularity: "day", points: mkSeries(30, 86_400_000, UTC_DAY0) },
  "90d": { granularity: "day", points: mkSeries(90, 86_400_000, UTC_DAY0) },
};

const roles = [
  { role: "Admin", users: 3000, turns: 1200, usd: 4.5, thumbsDownPct: 3.2 },
  { role: "Agent", users: 40000, turns: 800, usd: 6.1, thumbsDownPct: null },
  { role: "(no role)", users: 7000, turns: 100, usd: null, thumbsDownPct: 12 },
];
const topPeople = Array.from({ length: 20 }, (_, i) => ({
  userKey: `a1b2c3d4e5f6${String(i).padStart(2, "0")}0123456789ef${String(i).padStart(2, "0")}`.slice(0, 24),
  role: i % 2 ? "Admin" : null, turns: 90 - i, inputTokens: 1000, outputTokens: 500, usd: i === 3 ? null : 0.5, errors: i === 0 ? 2 : 0, thumbsDown: i === 1 ? 1 : 0,
  lastSeenAt: minutesAgo(5 + i),
}));

/** What the platform sends for a live app: the snapshot shape plus the live extras. */
function summary(range = "7d", over: Record<string, unknown> = {}) {
  const s = SERIES[range];
  return {
    generatedAt: iso(NOW), days: 7, agentId: "support", since: minutesAgo(60), firstTurnAt: null,
    totals: { conversations: 400, turns: 2100, users: 50_000, inputTokens: 4_000_000, outputTokens: 900_000, toolCalls: 30, toolErrors: 3, blocked: 1, errors: 8, handedOff: 4, rated: 10, up: 8, down: 2 },
    latencyMs: { p50: 2100, p95: 9000, avg: 3000 },
    byDay: [], byModel: [{ model: "claude-sonnet-4-5", turns: 2100, inputTokens: 4_000_000, outputTokens: 900_000 }],
    tools: [{ name: "lookup_order", calls: 30, errors: 3, avgMs: 400, failurePct: 10 }],
    problems: [], handoffs: { total: 0, open: 0, claimed: 0, resolved: 0, avgResolveMinutes: null },
    cost: {
      estimatedUsd: 12.5, partial: false, perChatUsd: 0.03, perTurnUsd: 0.006,
      byModel: [{ model: "claude-sonnet-4-5", turns: 2100, inputTokens: 4_000_000, outputTokens: 900_000, usd: 12.5, priced: true }],
      byDay: [], unpricedModels: [], note: "Estimated from list prices; your bill may differ.",
    },
    quality: {
      answeredWithoutPerson: { pct: 99, count: 2096, of: 2100 }, thumbsUp: { pct: 80, count: 8, of: 10 }, errors: { pct: 0.4, count: 8, of: 2100 },
      blocked: { pct: 0, count: 1, of: 2100 }, toolFailures: { pct: 10, count: 3, of: 30 }, speed: { p50Ms: 2100, p95Ms: 9000, avgMs: 3000, slow: false },
    },
    tips: [],
    mode: "stream", range, granularity: s.granularity, since2: undefined, until: iso(NOW),
    freshness: { lastEventAt: iso(NOW - 4000), lagSeconds: 4 }, exact: true, droppedEvents: 0,
    live: { turnsPerMinute: 42, activeUsers5m: 1234, errorRatePct5m: 2.5, p95Ms5m: 8200 },
    series: s.points,
    users: {
      active: 50_000, newUsers: 12_000, returning: 38_000, approximate: true,
      activeByDay: [{ day: "2026-10-19", active: 30_000 }, { day: "2026-10-20", active: 41_000 }, { day: "2026-10-21", active: 50_000 }],
      byRole: roles, top: topPeople,
    },
    ...over,
  };
}
const live = (range = "7d", over: Record<string, unknown> = {}) => ({ ok: true, insights: summary(range, over) });
const NO_LIVE = { ok: false, reason: "No live app has sent chats yet. Make a key and connect your app." };
const NO_KEY = { exists: false, prefix: "", createdAt: null, lastUsedAt: null, eventsLast24h: 0 };
const HAS_KEY = { exists: true, prefix: "fik_ab12", createdAt: minutesAgo(3 * 60), lastUsedAt: minutesAgo(2), eventsLast24h: 12_345 };

/** The development app's snapshot (the v1 shape, none of the live extras). */
const V1 = {
  ok: true,
  insights: {
    generatedAt: iso(NOW), days: 7, agentId: "support", since: minutesAgo(7 * 24 * 60), firstTurnAt: "2026-10-16T08:00:00Z",
    totals: { conversations: 12, turns: 40, users: 5, inputTokens: 400_000, outputTokens: 100_000, toolCalls: 30, toolErrors: 9, blocked: 1, errors: 2, handedOff: 4, rated: 10, up: 8, down: 2 },
    byDay: [{ day: "2026-10-20", turns: 10, inputTokens: 1, outputTokens: 1, errors: 0, up: 0, down: 0 }, { day: "2026-10-21", turns: 30, inputTokens: 1, outputTokens: 1, errors: 2, up: 0, down: 0 }],
    cost: { estimatedUsd: 2.7, partial: false, perChatUsd: 0.2, perTurnUsd: 0.06, byModel: [], byDay: [], unpricedModels: [], note: "Estimated from list prices; your bill may differ." },
  },
};

interface Routes {
  summary?: unknown | ((url: string) => unknown);
  v1?: unknown | ((url: string) => unknown);
  key?: unknown | ((url: string) => unknown);
}
const answerOf = (x: unknown, u: string) => (typeof x === "function" ? (x as (url: string) => unknown)(u) : x);
/** Answers each route as given; a function is called with the URL and may return a promise or throw. */
function serve(r: Routes) {
  apiGet.mockImplementation(async (u: string) => {
    if (u.includes("/insights/summary")) return answerOf(r.summary ?? NO_LIVE, u);
    if (u.includes("/insights/key")) return answerOf(r.key ?? NO_KEY, u);
    return answerOf(r.v1 ?? { ok: false, reason: "The app could not be reached." }, u);
  });
}
const urls = (pick: (u: string) => boolean) => apiGet.mock.calls.map((c) => String(c[0])).filter(pick);
const summaryUrls = () => urls((u) => u.includes("/insights/summary"));
const wholeUrls = (range: string) => summaryUrls().filter((u) => u.includes(`range=${range}`));
const v1Urls = () => urls((u) => u.includes("/insights?"));
const keyGets = () => urls((u) => u.includes("/insights/key"));

// ---------------------------------------------------------------------------
// the harness
// ---------------------------------------------------------------------------

let container: HTMLDivElement;
let root: Root;
const watch = vi.fn();
const writeText = vi.fn();

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiDelete.mockReset();
  watch.mockReset();
  writeText.mockReset();
  writeText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  serve({ summary: live() });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function mount(over: Partial<{ appUrl: string; agentId: string }> = {}) {
  await act(async () => {
    root.render(<AgentInsightsPanel projectId="p1" agentId={over.agentId ?? "support"} agentName="Support Assistant" appUrl={over.appUrl ?? ""} onOpenWatch={watch} />);
  });
}
const q = (id: string) => container.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;
const qa = (id: string) => [...container.querySelectorAll(`[data-testid="${id}"]`)] as HTMLElement[];
const text = () => container.textContent ?? "";
const button = (label: string) => [...container.querySelectorAll("button")].find((b) => (b.textContent ?? "").trim() === label)!;
const click = (e: Element) => act(async () => { (e as HTMLElement).click(); });
const tab = (card: string, label: "Chart" | "Table") => [...q(`insights-section-${card}`)!.querySelectorAll("button")].find((b) => b.textContent === label)!;
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

// ---------------------------------------------------------------------------

describe("the platform is asked first, and only one source is ever shown", () => {
  it("shows a live app's numbers, says so, and never asks the development app even when one is connected", async () => {
    serve({ summary: live(), v1: V1 });
    await mount({ appUrl: "tunnel" });
    expect(summaryUrls()[0]).toBe("/api/projects/p1/agent-definitions/insights/summary?range=7d&agent_id=support");
    expect(v1Urls()).toHaveLength(0);
    expect(q("insights-source")!.textContent).toBe("Live app");
    expect(q("insights-scope")!.textContent).toContain("The last 7 days");
    expect(q("insights-scope")!.textContent).toContain("every chat counted");
    expect(text()).not.toContain("Development app on your computer");
    expect(q("insights-card-cost")!.textContent).toContain("$12.50");
    expect(q("insights-live-strip")).toBeTruthy();
  });

  it("works with no development app connected at all", async () => {
    await mount({ appUrl: "" });
    expect(q("insights-cards")).toBeTruthy();
    expect(q("insights-source")!.textContent).toBe("Live app");
    expect(q("insights-setup")).toBeNull();
  });

  it("when there is nothing live and a development app is connected, it shows that app's snapshot and names it", async () => {
    serve({ summary: NO_LIVE, v1: V1 });
    await mount({ appUrl: "tunnel" });
    expect(summaryUrls()).toHaveLength(1);
    expect(v1Urls()).toHaveLength(1);
    expect(q("insights-source")!.textContent).toBe("Development app on your computer");
    expect(q("insights-live-strip"), "a snapshot has no live strip").toBeNull();
    expect(q("insights-section-people"), "and no people").toBeNull();
    expect(text()).not.toContain("Live app");
    expect(q("insights-card-cost")!.textContent).toContain("$2.70");
    // the way to a live app stays at the bottom, with what the platform said
    await click(button("Connect a live app"));
    expect(q("insights-live-reason")!.textContent).toContain("No live app has sent chats yet");
  });

  it("an older platform without the summary route (it throws) still shows the development app", async () => {
    serve({ summary: () => { throw new Error("Not Found"); }, v1: V1 });
    await mount({ appUrl: "tunnel" });
    expect(v1Urls()).toHaveLength(1);
    expect(q("insights-source")!.textContent).toBe("Development app on your computer");
    expect(q("insights-problem")).toBeNull();
  });

  it("with no development app and nothing live it shows the setup state, and asks nothing of any app", async () => {
    serve({ summary: NO_LIVE });
    await mount({ appUrl: "" });
    expect(q("insights-setup")).toBeTruthy();
    expect(q("insights-live-setup")!.textContent).toContain("See every chat from your live app");
    expect(q("insights-live-reason")!.textContent).toContain("No live app has sent chats yet");
    expect(v1Urls()).toHaveLength(0);
    expect(q("insights-cards")).toBeNull();
    expect(q("insights-problem"), "nothing is wrong: it is just not connected yet").toBeNull();
  });

  it("with nothing live and a development app that cannot be reached, it says why and still offers the live app", async () => {
    serve({ summary: NO_LIVE, v1: { ok: false, reason: "Your computer is not connected right now." } });
    await mount({ appUrl: "tunnel" });
    expect(q("insights-problem")!.textContent).toContain("Your computer is not connected right now.");
    expect(q("insights-live-setup")).toBeTruthy();
  });

  it("with no development app and a platform that cannot be asked, it says so in words and still offers the setup card", async () => {
    serve({ summary: () => { throw new Error("The platform is not answering."); } });
    await mount({ appUrl: "" });
    expect(q("insights-problem")!.textContent).toContain("The platform is not answering.");
    expect(q("insights-live-setup")).toBeTruthy();
  });

  it("an answer that is not a summary at all is said in words and does not crash", async () => {
    serve({ summary: { ok: true, insights: { hello: "world" } } });
    await mount({ appUrl: "tunnel" });
    expect(q("insights-problem")!.textContent).toContain("does not understand");
    expect(q("insights-cards")).toBeNull();
  });

  it("once a live summary has worked, a range with no chats does not swap in the development app", async () => {
    serve({ summary: (u: string) => (u.includes("range=1h") ? NO_LIVE : live()), v1: V1 });
    await mount({ appUrl: "tunnel" });
    expect(q("insights-source")!.textContent).toBe("Live app");
    await click(button("1 hour"));
    expect(v1Urls()).toHaveLength(0);
    expect(q("insights-problem")!.textContent).toContain("No live app has sent chats yet");
    expect(q("insights-source")).toBeNull();
  });

  it("keeps the last live numbers when a later ask fails", async () => {
    await mount();
    serve({ summary: () => { throw new Error("The platform is not answering."); } });
    await click(button("Refresh"));
    expect(q("insights-problem")!.textContent).toContain("The platform is not answering.");
    expect(q("insights-problem")!.textContent).toContain("last ones we got");
    expect(q("insights-card-cost")!.textContent).toContain("$12.50");
  });

  it("holds the previous report, faded, while it asks again", async () => {
    await mount();
    serve({ summary: () => new Promise(() => {}) });
    await click(button("Refresh"));
    const report = q("insights-cards")!.parentElement!;
    expect(report.className).toContain("opacity-60");
    expect(report.getAttribute("aria-busy")).toBe("true");
    expect(q("insights-refreshing")).toBeTruthy();
  });
});

describe("how far back", () => {
  it("offers 1 hour, 24 hours, 7 days, 30 days and 90 days, all usable for a live app, asking the summary with each", async () => {
    await mount();
    const choices = [...container.querySelectorAll('[aria-label="How far back to look"] button')] as HTMLButtonElement[];
    expect(choices.map((b) => b.textContent)).toEqual(["1 hour", "24 hours", "7 days", "30 days", "90 days"]);
    expect(choices.every((b) => !b.disabled)).toBe(true);
    expect(choices[2].getAttribute("aria-pressed")).toBe("true");
    const sentence: Record<string, string> = { "1h": "The last hour", "24h": "The last 24 hours", "7d": "The last 7 days", "30d": "The last 30 days", "90d": "The last 90 days" };
    const label: Record<string, string> = { "1h": "1 hour", "24h": "24 hours", "7d": "7 days", "30d": "30 days", "90d": "90 days" };
    serve({ summary: (u: string) => live(/range=(\w+)/.exec(u)![1]) });
    for (const r of ["1h", "24h", "30d", "90d", "7d"]) {
      await click(button(label[r]));
      expect(summaryUrls().at(-1) ?? "").toContain(`range=${r}`);
      expect(wholeUrls(r).length).toBeGreaterThan(0);
      expect(button(label[r]).getAttribute("aria-pressed")).toBe("true");
      expect(q("insights-scope")!.textContent).toContain(sentence[r]);
    }
  });

  it("does not show the old range's numbers under the new one while it loads", async () => {
    await mount();
    serve({ summary: () => new Promise(() => {}) });
    await click(button("30 days"));
    expect(q("insights-skeleton")).toBeTruthy();
    expect(q("insights-cards")).toBeNull();
  });
});

describe("freshness and honesty", () => {
  it("says how old the newest chat is and that every chat is counted", async () => {
    await mount();
    expect(q("insights-freshness")!.textContent).toBe("Updated 4 seconds ago, every chat counted");
    expect(q("insights-dropped")).toBeNull();
  });

  it("a quiet app says when the newest chat arrived, not that the screen is stale", async () => {
    serve({ summary: live("7d", { freshness: { lastEventAt: iso(NOW - 7_200_000), lagSeconds: 7200 } }) });
    await mount();
    expect(q("insights-freshness")!.textContent).toBe("The newest chat arrived 2 hours ago, every chat counted");
  });

  it("says plainly when counts are approximate, and when no chat has arrived", async () => {
    serve({ summary: live("7d", { exact: false }) });
    await mount();
    expect(q("insights-freshness")!.textContent).toBe("Updated 4 seconds ago, the counts are approximate");
    serve({ summary: live("7d", { freshness: { lastEventAt: null, lagSeconds: null }, exact: true }) });
    await click(button("Refresh"));
    expect(q("insights-freshness")!.textContent).toBe("No chats have arrived yet, every chat counted");
  });

  it("never hides events that were not accepted: how many, why, and that the numbers are a little low", async () => {
    serve({ summary: live("7d", { droppedEvents: 1250 }) });
    await mount();
    const note = q("insights-dropped")!;
    expect(note.textContent).toContain("1,250 events were not accepted in this time, so these numbers are a little low");
    expect(note.textContent).toContain("invalid");
    expect(note.textContent).toContain("too many arrived at once");
    expect(note.getAttribute("role")).toBe("status");
    serve({ summary: live("7d", { droppedEvents: 1 }) });
    await click(button("Refresh"));
    expect(q("insights-dropped")!.textContent).toContain("1 event was not accepted in this time");
  });

  it("says times are in the viewer's time zone for hours and minutes, and not for days", async () => {
    await mount();
    expect(q("insights-scope")!.textContent).toContain("Times are in your time zone");
    serve({ summary: (u: string) => live(/range=(\w+)/.exec(u)![1]) });
    await click(button("30 days"));
    expect(q("insights-scope")!.textContent).not.toContain("time zone");
  });
});

describe("the live strip", () => {
  it("shows replies a minute, people right now, the failure rate in words, and the slowest 1 in 20, with a pulsing dot when events are flowing", async () => {
    await mount();
    const strip = q("insights-live-strip")!;
    expect(strip.getAttribute("data-live")).toBe("true");
    expect(q("insights-live-state")!.textContent).toBe("Live");
    expect(strip.querySelector(".animate-ping, [class*='animate-ping']")).toBeTruthy();
    expect(q("insights-live-rate")!.textContent).toContain("42");
    expect(q("insights-live-rate")!.textContent).toContain("replies a minute");
    expect(q("insights-live-people")!.textContent).toContain("about 1,234");
    expect(q("insights-live-people")!.textContent).toContain("last 5 minutes");
    expect(q("insights-live-failed")!.textContent).toContain("2.5%");
    expect(q("insights-live-failed")!.textContent).toContain("of replies failed in the last 5 minutes");
    expect(q("insights-live-failed")!.getAttribute("data-warn")).toBeNull();
    expect(q("insights-live-slow")!.textContent).toContain("8.2 s");
    expect(q("insights-live-slow")!.textContent).toContain("slowest 1 in 20");
  });

  it("is grey and says Waiting for events when the newest event is not recent, or there is none", async () => {
    serve({ summary: live("7d", { freshness: { lastEventAt: iso(NOW - 60_000), lagSeconds: 40 } }) });
    await mount();
    expect(q("insights-live-strip")!.getAttribute("data-live")).toBe("false");
    expect(q("insights-live-state")!.textContent).toBe("Waiting for events");
    expect(q("insights-live-strip")!.querySelector("[class*='animate-ping']")).toBeNull();
    serve({ summary: live("7d", { freshness: { lastEventAt: null, lagSeconds: null } }) });
    await click(button("Refresh"));
    expect(q("insights-live-state")!.textContent).toBe("Waiting for events");
  });

  it("is live just under 15 seconds and waiting from 15", async () => {
    serve({ summary: live("7d", { freshness: { lastEventAt: iso(NOW), lagSeconds: 14.9 } }) });
    await mount();
    expect(q("insights-live-state")!.textContent).toBe("Live");
    serve({ summary: live("7d", { freshness: { lastEventAt: iso(NOW), lagSeconds: 15 } }) });
    await click(button("Refresh"));
    expect(q("insights-live-state")!.textContent).toBe("Waiting for events");
  });

  it("a high failure rate is said in words as well as in a warm tint and a warning mark", async () => {
    serve({ summary: live("7d", { live: { turnsPerMinute: 3, activeUsers5m: 1, errorRatePct5m: 25, p95Ms5m: null } }) });
    await mount();
    const failed = q("insights-live-failed")!;
    expect(failed.getAttribute("data-warn")).toBe("true");
    expect(failed.textContent).toContain("25%");
    expect(failed.textContent).toContain("more than 1 in 10");
    expect(failed.querySelector("svg")).toBeTruthy();
    expect(q("insights-live-slow")!.textContent).toContain("n/a");
  });

  it("says there were no replies in the last 5 minutes instead of showing 0%", async () => {
    serve({ summary: live("7d", { live: { turnsPerMinute: 0, activeUsers5m: 0, errorRatePct5m: null, p95Ms5m: null } }) });
    await mount();
    expect(q("insights-live-failed")!.textContent).toContain("no replies in the last 5 minutes");
    expect(q("insights-live-failed")!.textContent).not.toContain("0%");
  });

  it("reads small rates with one decimal and exact people without 'about'", async () => {
    serve({ summary: live("7d", { users: { ...summary().users, approximate: false }, live: { turnsPerMinute: 0.4, activeUsers5m: 1, errorRatePct5m: 0, p95Ms5m: 900 } }) });
    await mount();
    expect(q("insights-live-rate")!.textContent).toContain("0.4");
    expect(q("insights-live-people")!.textContent).toContain("person using it");
    expect(q("insights-live-people")!.textContent).not.toContain("people using it");
    expect(q("insights-live-people")!.textContent).not.toContain("about");
    expect(q("insights-live-slow")!.textContent).toContain("900 ms");
  });

  it("is left out when the platform sent no live part, and says so", async () => {
    const { live: _l, ...rest } = summary();
    serve({ summary: { ok: true, insights: rest } });
    await mount();
    expect(q("insights-live-strip")!.textContent).toContain("No numbers for the last 5 minutes yet");
  });
});

describe("keeping fresh", () => {
  it("asks the strip every 5 seconds and the whole report every 30, and the strip carries the newest freshness", async () => {
    vi.useFakeTimers();
    await mount();
    expect(wholeUrls("7d")).toHaveLength(1);
    expect(wholeUrls("1h")).toHaveLength(0);
    await advance(STRIP_REFRESH_MS);
    expect(wholeUrls("1h")).toHaveLength(1);
    expect(wholeUrls("7d")).toHaveLength(1);
    serve({ summary: (u: string) => (u.includes("range=1h") ? live("1h", { freshness: { lastEventAt: iso(NOW), lagSeconds: 2 } }) : live("7d")) });
    await advance(STRIP_REFRESH_MS);
    expect(q("insights-freshness")!.textContent).toBe("Updated 2 seconds ago, every chat counted");
    await advance(REFRESH_MS - 2 * STRIP_REFRESH_MS);
    expect(wholeUrls("7d")).toHaveLength(2);
    expect(wholeUrls("1h")).toHaveLength(REFRESH_MS / STRIP_REFRESH_MS);
  });

  it("asks neither while the browser tab is hidden, and both again when it is shown", async () => {
    vi.useFakeTimers();
    await mount();
    const hidden = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    const before = summaryUrls().length;
    await advance(REFRESH_MS * 2);
    expect(summaryUrls()).toHaveLength(before);
    hidden.mockReturnValue("visible");
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(summaryUrls()).toHaveLength(before + 2);
    expect(wholeUrls("1h").length).toBeGreaterThan(0);
  });

  it("stops asking once the view is closed", async () => {
    vi.useFakeTimers();
    await mount();
    act(() => root.unmount());
    const before = apiGet.mock.calls.length;
    await advance(REFRESH_MS * 3);
    expect(apiGet).toHaveBeenCalledTimes(before);
    root = createRoot(container);
  });

  it("does not ask the strip for a development app", async () => {
    vi.useFakeTimers();
    serve({ summary: NO_LIVE, v1: V1 });
    await mount({ appUrl: "tunnel" });
    await advance(STRIP_REFRESH_MS * 5);
    expect(wholeUrls("1h")).toHaveLength(0);
  });

  it("keeps the last strip but stops calling it live after two failed asks in a row, and recovers", async () => {
    vi.useFakeTimers();
    await mount();
    serve({ summary: (u: string) => { if (u.includes("range=1h")) throw new Error("offline"); return live(); } });
    await advance(STRIP_REFRESH_MS);
    expect(q("insights-live-stale")).toBeNull();
    await advance(STRIP_REFRESH_MS);
    expect(q("insights-live-stale")!.textContent).toContain("could not be refreshed just now");
    expect(q("insights-live-state")!.textContent).toBe("Not updating");
    expect(q("insights-live-rate")!.textContent).toContain("42");
    serve({ summary: live() });
    await advance(STRIP_REFRESH_MS);
    expect(q("insights-live-stale")).toBeNull();
    expect(q("insights-live-state")!.textContent).toBe("Live");
  });

  it("does not stack strip asks: a slow one is waited for", async () => {
    vi.useFakeTimers();
    await mount();
    serve({ summary: (u: string) => (u.includes("range=1h") ? new Promise(() => {}) : live()) });
    await advance(STRIP_REFRESH_MS * 4);
    expect(wholeUrls("1h")).toHaveLength(1);
  });
});

describe("the time series", () => {
  /** The columns of the replies chart only (the people section draws columns too). */
  const qaBars = () => [...q("insights-section-daily")!.querySelectorAll('[data-testid="insights-bar"]')] as HTMLElement[];
  const firstLabelOf = (range: string) => {
    const rows = [...q("insights-day-table")!.querySelectorAll("tbody tr")];
    return { first: rows[rows.length - 1].querySelector("td")!.textContent, last: rows[0].querySelector("td")!.textContent, count: rows.length };
  };
  const pick = (u: string) => live(/range=(\w+)/.exec(u)![1]);

  it("1 hour is a column a minute, labelled like 10:42, with every minute in the table", async () => {
    serve({ summary: pick });
    await mount();
    await click(button("1 hour"));
    expect(q("insights-section-daily")!.querySelector("h4")!.textContent).toBe("Replies each minute");
    expect(qaBars()).toHaveLength(60);
    expect(qaBars()[0].getAttribute("aria-label")).toMatch(/^10:00: 1 reply, 1 failed$/);
    await click(tab("daily", "Table"));
    expect(firstLabelOf("1h")).toEqual({ first: "10:00", last: "10:59", count: 60 });
    expect(q("insights-day-table")!.querySelector("th")!.textContent).toBe("Minute");
  });

  it("24 hours and 7 days are a column an hour, labelled like Oct 21, 14:00", async () => {
    serve({ summary: pick });
    await mount();
    await click(button("24 hours"));
    expect(q("insights-section-daily")!.querySelector("h4")!.textContent).toBe("Replies each hour");
    expect(qaBars()).toHaveLength(24);
    expect(qaBars()[4].getAttribute("aria-label")).toMatch(/^Oct 21, 14:00: /);
    await click(tab("daily", "Table"));
    expect(firstLabelOf("24h").first).toBe("Oct 21, 10:00");
    expect(q("insights-day-table")!.querySelector("th")!.textContent).toBe("Hour");
    await click(tab("daily", "Chart"));
    await click(button("7 days"));
    expect(qaBars()).toHaveLength(168);
    expect(q("insights-section-daily")!.querySelector("h4")!.textContent).toBe("Replies each hour");
  });

  it("30 and 90 days are a column a day, labelled like Oct 21, with the days read from the text", async () => {
    serve({ summary: pick });
    await mount();
    await click(button("30 days"));
    expect(q("insights-section-daily")!.querySelector("h4")!.textContent).toBe("Replies each day");
    expect(qaBars()).toHaveLength(30);
    expect(qaBars()[0].getAttribute("aria-label")).toMatch(/^Sep 23: /);
    await click(button("90 days"));
    expect(qaBars()).toHaveLength(90);
    await click(tab("daily", "Table"));
    expect(firstLabelOf("90d")).toEqual({ first: "Sep 23", last: "Dec 21", count: 90 });
  });

  it("the cost chart is its own measure and uses the series' own cost for each bucket", async () => {
    serve({ summary: pick });
    await mount();
    await click(button("24 hours"));
    expect(q("insights-section-daily-cost")!.querySelector("h4")!.textContent).toBe("Estimated cost each hour");
    const line = q("insights-section-daily-cost")!.querySelector('[data-testid="insights-line"]')!;
    expect(line).toBeTruthy();
    expect(q("insights-chart")!.querySelector('[data-testid="insights-line"]')).toBeNull();
    // the last point of the 24 hour series is 0.01 * ((23 % 5) + 1) = 0.04
    expect(q("insights-end-label")!.textContent).toBe("$0.04");
    await click(tab("daily-cost", "Table"));
    expect(q("insights-day-table")!.textContent).toContain("$0.04");
    expect(q("insights-day-table")!.textContent).toContain("Estimated cost");
  });

  it("buckets with no known price are blank, not zero", async () => {
    serve({ summary: (u: string) => live(/range=(\w+)/.exec(u)![1], { series: mkSeries(24, 3_600_000, LOCAL_10_00, false) }) });
    await mount();
    await click(button("24 hours"));
    expect(q("insights-cost-legend")!.textContent).toContain("Cost each hour is not shown because a price is not known");
    await click(tab("daily", "Table"));
    expect(q("insights-day-table")!.textContent).toContain("price unknown");
  });

  it("a thousand minutes are drawn as at most 120 columns, neighbours added up, while the table keeps every minute", async () => {
    const dense = mkSeries(1440, 60_000, LOCAL_10_00);
    serve({ summary: live("24h", { granularity: "minute", series: dense }) });
    await mount();
    await click(button("24 hours"));
    const bars = qaBars();
    expect(bars.length).toBeLessThanOrEqual(120);
    expect(bars.length).toBeGreaterThan(60);
    expect(bars[0].getAttribute("aria-label")).toMatch(/^10:00 to 10:11: /);
    expect(q("insights-section-daily")!.textContent).toContain("added together to draw it");
    // twelve minutes added together: turns 1..7 repeating, 12 of them
    const turns12 = dense.slice(0, 12).reduce((a, p) => a + p.turns, 0);
    expect(bars[0].getAttribute("aria-label")).toContain(`: ${turns12} replies`);
    // the total drawn is the total there is
    const drawn = bars.reduce((a, b) => a + Number(/: (\d+) repl/.exec(b.getAttribute("aria-label")!)![1]), 0);
    expect(drawn).toBe(dense.reduce((a, p) => a + p.turns, 0));
    await click(tab("daily", "Table"));
    expect(q("insights-day-table")!.querySelectorAll("tbody tr")).toHaveLength(1440);
  });

  it("a week of hours keeps its axis labels apart, whatever their length, and keeps the newest one", async () => {
    serve({ summary: pick });
    await mount();
    const texts = [...q("insights-chart")!.querySelectorAll("svg text")].filter((t) => /^Oct \d+, \d\d:00$/.test(t.textContent ?? ""));
    expect(texts.length).toBeGreaterThan(2);
    // each label as the span it covers on the axis (about 5.6px a character), by where it is anchored
    const spans = texts.map((t) => {
      const x = Number(t.getAttribute("x"));
      const w = (t.textContent ?? "").length * 5.6;
      const a = t.getAttribute("text-anchor");
      const left = a === "end" ? x - w : a === "start" ? x : x - w / 2;
      return [left, left + w];
    }).sort((p, r) => p[0] - r[0]);
    for (let i = 1; i < spans.length; i++) expect(spans[i][0] - spans[i - 1][1], `labels ${i - 1} and ${i}`).toBeGreaterThanOrEqual(8);
    expect(texts.some((t) => t.textContent === "Oct 28, 09:00"), "the newest hour is labelled").toBe(true);
  });

  it("90 days of columns stay thin and have a few evenly spaced labels", async () => {
    serve({ summary: pick });
    await mount();
    await click(button("90 days"));
    const labels = [...q("insights-chart")!.querySelectorAll("svg text")].filter((t) => /^[A-Z][a-z]{2} \d+$/.test(t.textContent ?? ""));
    expect(labels.length).toBeGreaterThan(2);
    expect(labels.length).toBeLessThan(15);
    for (const bar of qaBars()) {
      for (const p of bar.querySelectorAll("path")) {
        const nums = (p.getAttribute("d") ?? "").match(/[\d.]+/g)!.map(Number);
        expect(Math.max(...nums.filter((_, i) => i % 2 === 0)) - Math.min(...nums.filter((_, i) => i % 2 === 0))).toBeLessThanOrEqual(24);
      }
    }
  });

  it("the tooltip names the bucket, and the keyboard moves along the buckets", async () => {
    serve({ summary: pick });
    await mount();
    await click(button("24 hours"));
    const svg = q("insights-chart")!.querySelector("svg")!;
    await act(async () => { svg.dispatchEvent(new FocusEvent("focusin", { bubbles: true })); });
    const title = q("insights-tooltip")!.querySelector("div")!.textContent;
    expect(title).toMatch(/^Oct 2[12], \d\d:00$/);
    await act(async () => { svg.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true, cancelable: true })); });
    expect(q("insights-tooltip")!.querySelector("div")!.textContent).toBe("Oct 21, 10:00");
  });
});

describe("who is using it", () => {
  it("shows how many people, how many are new and returning, with 'about' because the counts come from a sketch", async () => {
    await mount();
    const section = q("insights-section-people")!;
    expect(section.textContent).toContain("Who is using it");
    expect(section.textContent).toContain("People are shown by an anonymous code, not a name or an email.");
    expect(q("insights-card-people-active")!.textContent).toContain("about");
    expect(q("insights-card-people-active")!.textContent).toContain("50,000");
    expect(q("insights-card-people-new")!.textContent).toContain("12,000");
    expect(q("insights-card-people-returning")!.textContent).toContain("38,000");
    expect(q("insights-people-about")!.textContent).toContain("within 1%");
  });

  it("says nothing about 'about' when the counts are exact", async () => {
    serve({ summary: live("7d", { users: { ...summary().users, approximate: false } }) });
    await mount();
    expect(q("insights-card-people-active")!.textContent).not.toContain("about");
    expect(q("insights-people-about")).toBeNull();
    expect(q("insights-live-people")!.textContent).not.toContain("about");
  });

  it("draws new against returning as ONE stacked bar, not a pie, with the numbers and shares written under it", async () => {
    await mount();
    const split = q("insights-share-bar")!;
    const bar = split.querySelector('[role="img"]')!;
    expect(bar.getAttribute("aria-label")).toBe("New and returning people: New about 12,000 (24%), Returning about 38,000 (76%)");
    expect(bar.children).toHaveLength(2);
    expect(bar.className).toContain("gap-0.5");
    expect(split.querySelector("circle, [class*='rounded-full'][style*='conic']")).toBeNull();
    expect(split.textContent).toContain("12,000");
    expect(split.textContent).toContain("24%");
    expect(split.textContent).toContain("76%");
    const fills = [...bar.children].map((c) => (c as HTMLElement).style.background);
    expect(fills).toEqual(["var(--viz-s1)", "var(--viz-s2)"]);
  });

  it("draws the people active each day as columns, with a table of the same numbers", async () => {
    await mount();
    const card = q("insights-section-people-days")!;
    expect(card.querySelector("h4")!.textContent).toBe("People active each day");
    const bars = [...card.querySelectorAll('[data-testid="insights-bar"]')];
    expect(bars.map((b) => b.getAttribute("aria-label"))).toEqual(["Oct 19: 30000 people", "Oct 20: 41000 people", "Oct 21: 50000 people"]);
    await click(tab("people-days", "Table"));
    expect(q("insights-people-days-table")!.textContent).toContain("50,000");
    expect(q("insights-people-days-table")!.textContent).toContain("People (about)");
  });

  it("shows usage by role as bars, busiest first, with people, an estimated cost and the thumbs-down share in words", async () => {
    await mount();
    const bars = qa("insights-role-bar");
    expect(bars.map((b) => b.getAttribute("aria-label")!.split(":")[0])).toEqual(["Admin", "Agent", "(no role)"]);
    expect(bars[0].getAttribute("aria-label")).toBe("Admin: 1,200 replies, about 3,000 people, estimated cost $4.50, 3.2% thumbs down");
    expect(bars[1].textContent).toContain("no ratings yet");
    expect(bars[2].textContent).toContain("estimated cost n/a (price unknown)");
    expect(bars[2].textContent).toContain("12% thumbs down");
    await click(tab("people-roles", "Table"));
    const rows = [...q("insights-role-table")!.querySelectorAll("tbody tr")];
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toContain("about 3,000");
    expect(rows[2].textContent).toContain("price unknown");
  });

  it("lists the most active people by a shortened code with a copy button, role, replies, cost, thumbs down, failures and last seen", async () => {
    await mount();
    const rows = qa("insights-top-row");
    expect(rows).toHaveLength(20);
    const first = rows[0];
    const code = topPeople[0].userKey;
    expect(first.textContent).toContain(`${code.slice(0, 8)}…${code.slice(-4)}`);
    expect(first.textContent, "the whole code is not on the page").not.toContain(code);
    expect(first.textContent).toContain("no role");
    expect(first.textContent).toContain("90");
    expect(first.textContent).toContain("$0.50");
    expect(first.textContent).toContain("5 min ago");
    expect(rows[3].textContent).toContain("price unknown");
    expect(q("insights-section-people-top")!.textContent).toContain("not a name");
    const copy = first.querySelector("button")!;
    expect(copy.getAttribute("aria-label")).toBe(`Copy the person code ${code.slice(0, 8)}…${code.slice(-4)}`);
    await click(copy);
    expect(writeText).toHaveBeenCalledWith(code);
    expect(copy.textContent).toBe("Copied");
  });

  it("says so when the clipboard cannot be used", async () => {
    writeText.mockRejectedValue(new Error("denied"));
    await mount();
    const copy = qa("insights-top-row")[0].querySelector("button")!;
    await click(copy);
    expect(copy.textContent).toBe("Could not copy");
  });

  it("empty cases are plain sentences", async () => {
    serve({ summary: live("7d", { users: { active: 0, newUsers: 0, returning: 0, approximate: false, activeByDay: [], byRole: [], top: [] } }) });
    await mount();
    expect(q("insights-section-people")!.textContent).toContain("Nobody has used the assistant in this time.");
    serve({ summary: live("7d", { users: { active: 3, newUsers: 3, returning: 0, approximate: false, activeByDay: [], byRole: [], top: [] } }) });
    await click(button("Refresh"));
    expect(q("insights-section-people-days")!.textContent).toContain("No days with people in this time.");
    expect(q("insights-section-people-roles")!.textContent).toContain("No roles were recorded in this time.");
    expect(q("insights-section-people-top")!.textContent).toContain("No individual people to list in this time.");
  });

  it("is not on the page without a users part", async () => {
    const { users: _u, ...rest } = summary();
    serve({ summary: { ok: true, insights: rest } });
    await mount();
    expect(q("insights-section-people")).toBeNull();
  });
});

describe("the key: connect a live app", () => {
  let setItem: ReturnType<typeof vi.spyOn>;
  let logs: ReturnType<typeof vi.spyOn>[];

  beforeEach(() => {
    // the test setup gives local and session storage the same plain object, so one spy sees both
    setItem = vi.spyOn(localStorage, "setItem");
    logs = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
  });

  /** The setup card as the first thing a person sees: nothing live, no key yet. */
  async function setup(key: unknown = NO_KEY) {
    serve({ summary: NO_LIVE, key });
    await mount({ appUrl: "" });
  }
  const secretSeenIn = () => [text(), container.innerHTML];
  const nothingSecretKept = () => {
    expect(setItem, "no localStorage or sessionStorage write").not.toHaveBeenCalled();
    expect(localStorage.length, "nothing was stored").toBe(0);
    for (const spy of logs) expect(JSON.stringify(spy.mock.calls)).not.toContain(KEY);
  };

  it("with no key yet, offers to create one and says what a key is for", async () => {
    await setup();
    expect(keyGets()).toEqual(["/api/projects/p1/agent-definitions/insights/key"]);
    expect(q("insights-live-setup")!.textContent).toContain("Create a key");
    expect(q("insights-live-setup")!.textContent).toContain("never a name or an email");
    expect(q("insights-key-status")).toBeNull();
  });

  it("creates a key and shows it ONCE, with the three environment lines, copy buttons and the three steps", async () => {
    await setup();
    apiPost.mockResolvedValue({ key: KEY, prefix: "fik_AbCd", ingestUrl: INGEST });
    await click(button("Create a key"));
    expect(apiPost).toHaveBeenCalledWith("/api/projects/p1/agent-definitions/insights/key", undefined);
    const box = q("insights-key-reveal")!;
    expect(box.textContent).toContain("shown only this once");
    expect(q("insights-key-secret")!.textContent).toBe(KEY);
    expect(q("insights-key-env")!.textContent).toBe(`FORGE_INSIGHTS_URL=${INGEST}\nFORGE_INSIGHTS_KEY=${KEY}\nFORGE_INSIGHTS_INCLUDE_TEXT=0`);
    expect(box.textContent).toContain("keeps message text off");
    expect([...q("insights-key-steps")!.querySelectorAll("li")].map((l) => l.textContent)).toEqual([
      "Paste these into your live app's environment.",
      "Apply the agent again and update the database.",
      "Restart the app.",
    ]);
    await click(button("Copy key"));
    expect(writeText).toHaveBeenLastCalledWith(KEY);
    await click(button("Copy the three lines"));
    expect(writeText).toHaveBeenLastCalledWith(`FORGE_INSIGHTS_URL=${INGEST}\nFORGE_INSIGHTS_KEY=${KEY}\nFORGE_INSIGHTS_INCLUDE_TEXT=0`);
    // after it is made the status shows its first characters, a fresh key and no events yet
    expect(q("insights-key-prefix")!.textContent).toBe("fik_AbCd…");
    nothingSecretKept();
  });

  it("clears the key from the page the moment it is dismissed, and it cannot be got back", async () => {
    await setup();
    apiPost.mockResolvedValue({ key: KEY, prefix: "fik_AbCd", ingestUrl: INGEST });
    await click(button("Create a key"));
    expect(secretSeenIn().every((t) => t.includes(KEY))).toBe(true);
    await click(button("I have copied it, hide it"));
    expect(q("insights-key-reveal")).toBeNull();
    for (const t of secretSeenIn()) expect(t).not.toContain(KEY);
    expect(container.innerHTML).not.toContain(INGEST);
    expect(q("insights-key-prefix")!.textContent).toBe("fik_AbCd…");
    // the platform only ever tells the first characters again: a new key is a different key, and the old text does not come back
    const KEY2 = "fik_" + "Zy9Xw8Vv7U".repeat(4);
    apiPost.mockResolvedValue({ key: KEY2, prefix: "fik_Zy9X", ingestUrl: INGEST });
    await click(button("Make a new key"));
    await click(button("Yes, make a new key"));
    expect(q("insights-key-secret")!.textContent).toBe(KEY2);
    for (const t of secretSeenIn()) expect(t).not.toContain(KEY);
    nothingSecretKept();
  });

  it("a key that is still showing is dropped when the view goes away", async () => {
    await setup();
    apiPost.mockResolvedValue({ key: KEY, prefix: "fik_AbCd", ingestUrl: INGEST });
    await click(button("Create a key"));
    act(() => root.unmount());
    expect(container.innerHTML).not.toContain(KEY);
    root = createRoot(container);
    await mount({ appUrl: "" });
    for (const t of secretSeenIn()) expect(t).not.toContain(KEY);
    nothingSecretKept();
  });

  it("with a key, shows its first characters, when it was made, when it was last used and the chats of the last 24 hours", async () => {
    await setup(HAS_KEY);
    const status = q("insights-key-status")!;
    expect(q("insights-key-prefix")!.textContent).toBe("fik_ab12…");
    expect([...status.querySelectorAll("dt")].map((d) => d.textContent)).toEqual(["Key", "Made", "Last used", "Chats received in the last 24 hours"]);
    expect([...status.querySelectorAll("dd")].map((d) => d.textContent)).toEqual(["fik_ab12…", "3 h ago", "2 min ago", "12,345"]);
    expect(q("insights-live-setup")!.textContent).not.toContain("Create a key");
    expect(button("Make a new key")).toBeTruthy();
    expect(button("Remove key")).toBeTruthy();
  });

  it("says never yet for a key that has not been used", async () => {
    await setup({ ...HAS_KEY, lastUsedAt: null, eventsLast24h: 0 });
    expect([...q("insights-key-status")!.querySelectorAll("dd")].map((d) => d.textContent)[2]).toBe("never yet");
  });

  it("making a new key asks first and says the old one stops working at once; saying no changes nothing", async () => {
    await setup(HAS_KEY);
    await click(button("Make a new key"));
    const ask = q("insights-key-confirm")!;
    expect(ask.textContent).toContain("The old key stops working at once");
    expect(ask.getAttribute("role")).toBe("alertdialog");
    expect(apiPost).not.toHaveBeenCalled();
    await click(button("No, keep the key"));
    expect(q("insights-key-confirm")).toBeNull();
    expect(apiPost).not.toHaveBeenCalled();
    await click(button("Make a new key"));
    apiPost.mockResolvedValue({ key: KEY, prefix: "fik_AbCd", ingestUrl: INGEST });
    await click(button("Yes, make a new key"));
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(q("insights-key-secret")!.textContent).toBe(KEY);
    expect(q("insights-key-confirm")).toBeNull();
    expect(q("insights-key-prefix")!.textContent).toBe("fik_AbCd…");
    nothingSecretKept();
  });

  it("removing the key asks first, then removes it and offers to create one again", async () => {
    await setup(HAS_KEY);
    await click(button("Remove key"));
    expect(q("insights-key-confirm")!.textContent).toContain("your live app can no longer send chats here");
    expect(apiDelete).not.toHaveBeenCalled();
    apiDelete.mockResolvedValue({ removed: true });
    await click(button("Yes, remove it"));
    expect(apiDelete).toHaveBeenCalledWith("/api/projects/p1/agent-definitions/insights/key");
    expect(q("insights-key-status")).toBeNull();
    expect(button("Create a key")).toBeTruthy();
  });

  it("errors are sentences, change nothing and never contain the key", async () => {
    await setup(HAS_KEY);
    apiPost.mockRejectedValue(new Error(`500 internal ${KEY}`));
    await click(button("Make a new key"));
    await click(button("Yes, make a new key"));
    expect(q("insights-key-error")!.textContent).toBe("The key could not be made. Nothing was changed. Try again in a moment.");
    expect(q("insights-key-reveal")).toBeNull();
    expect(q("insights-key-prefix")!.textContent).toBe("fik_ab12…");
    apiDelete.mockRejectedValue(new Error("boom"));
    await click(button("Remove key"));
    await click(button("Yes, remove it"));
    expect(q("insights-key-error")!.textContent).toBe("The key could not be removed. It still works. Try again in a moment.");
    for (const t of secretSeenIn()) expect(t).not.toContain(KEY);
    nothingSecretKept();
  });

  it("a key that cannot be read says so; a reply that is not a key is refused in words and shows nothing", async () => {
    serve({ summary: NO_LIVE, key: () => { throw new Error("offline"); } });
    await mount({ appUrl: "" });
    expect(q("insights-key-error")!.textContent).toContain("could not be loaded");
    expect(q("insights-live-setup")!.textContent).not.toContain("Create a key");
    serve({ summary: NO_LIVE, key: NO_KEY });
    act(() => root.unmount());
    root = createRoot(container);
    await mount({ appUrl: "" });
    apiPost.mockResolvedValue({ key: "short", ingestUrl: "javascript:alert(1)" });
    await click(button("Create a key"));
    expect(q("insights-key-error")!.textContent).toContain("did not send back a usable key");
    expect(q("insights-key-reveal")).toBeNull();
    apiPost.mockResolvedValue({ key: KEY, ingestUrl: "not a web address" });
    await click(button("Create a key"));
    expect(q("insights-key-reveal")).toBeNull();
  });

  it("a status that is not one is refused in words", async () => {
    await setup({ hello: "world" });
    expect(q("insights-key-error")!.textContent).toContain("does not understand");
  });

  it("is under a Connect a live app disclosure at the bottom of a report, closed, and asks nothing until it is opened", async () => {
    serve({ summary: live(), key: HAS_KEY });
    await mount();
    const toggle = button("Connect a live app");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(keyGets()).toHaveLength(0);
    expect(q("insights-live-setup")).toBeNull();
    expect(container.querySelector("#insights-connect-body")!.hasAttribute("hidden")).toBe(true);
    await click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(keyGets()).toHaveLength(1);
    expect(container.querySelector("#insights-connect-body")!.hasAttribute("hidden")).toBe(false);
    expect(q("insights-key-prefix")!.textContent).toBe("fik_ab12…");
    // it is the last thing on the page
    const sections = [...container.querySelectorAll("[data-testid^='insights-section-']")];
    expect(sections[sections.length - 1].getAttribute("data-testid")).toBe("insights-section-connect");
  });

  it("closing the disclosure while a new key is showing does not lose it, and the report refreshing does not either", async () => {
    vi.useFakeTimers();
    serve({ summary: live(), key: NO_KEY });
    await mount();
    await click(button("Connect a live app"));
    apiPost.mockResolvedValue({ key: KEY, prefix: "fik_AbCd", ingestUrl: INGEST });
    await click(button("Create a key"));
    await click(button("Connect a live app"));
    await advance(REFRESH_MS);
    await click(button("Connect a live app"));
    expect(q("insights-key-secret")!.textContent).toBe(KEY);
    nothingSecretKept();
  });
});

describe("plain words", () => {
  it("no button label has a bracket, a brace, an angle bracket or an ampersand, in any state of the live page", async () => {
    apiPost.mockResolvedValue({ key: KEY, prefix: "fik_AbCd", ingestUrl: INGEST });
    serve({ summary: live(), key: HAS_KEY });
    await mount();
    await click(button("Connect a live app"));
    await click(button("Make a new key"));
    const check = () => {
      const labels = [...container.querySelectorAll("button")].map((b) => (b.textContent ?? "").trim());
      expect(labels.length).toBeGreaterThan(5);
      for (const l of labels) expect(l, `button "${l}"`).not.toMatch(/[()\[\]{}<>&]/);
      for (const b of container.querySelectorAll("button, [role=group]")) expect(b.getAttribute("aria-label") ?? "").not.toMatch(/[\[\]{}<>&]/);
    };
    check();
    await click(button("Yes, make a new key"));
    check();
    serve({ summary: NO_LIVE, key: NO_KEY });
    act(() => root.unmount());
    root = createRoot(container);
    await mount();
    check();
  });

  it("uses no jargon on the live page", async () => {
    await mount();
    for (const word of ["p95", "p50", "percentile", "latency", "USD", "HyperLogLog", "rollup", "ingest", "hash", "stream"]) expect(text().toLowerCase()).not.toContain(word.toLowerCase());
  });

  it("every place that shows money says it is an estimate", async () => {
    await mount();
    expect(q("insights-card-cost")!.textContent).toContain("Estimated cost");
    expect(q("insights-section-daily-cost")!.textContent).toContain("From list prices");
    expect(q("insights-section-people-roles")!.textContent).toContain("estimated cost");
    expect(q("insights-note")!.textContent).toBe("Estimated from list prices; your bill may differ.");
  });

  it("stays in one scroll region", async () => {
    await mount();
    expect(container.querySelectorAll(".overflow-y-auto")).toHaveLength(1);
  });
});

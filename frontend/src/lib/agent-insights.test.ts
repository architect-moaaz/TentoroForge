import { describe, it, expect } from "vitest";
import {
  ago, asInsights, bucketLabel, dayRows, devRange, downsampleRows, droppedText, formatCount, formatRate, freshnessText, granularityFor, isLiveNow, maxColumns, peopleCount, rangeDays, RANGE_CHOICES, secondsAgo, seriesRows, shortKey, type ChartRow, barHeights, countOf, dayLabel, formatDuration, formatMinutes, formatMoney, formatPct, formatTokens, labelledDays, linePoints,
  modelCost, niceMax, REASON_LABEL, sortTips,
} from "./agent-insights";

describe("money", () => {
  it("shows dollars and cents", () => {
    expect(formatMoney(0.42)).toBe("$0.42");
    expect(formatMoney(2.7)).toBe("$2.70");
    expect(formatMoney(1234.5)).toBe("$1,234.50");
    expect(formatMoney(0)).toBe("$0.00");
  });
  it("says under a cent for a tiny amount, and that the price is unknown for null (not free)", () => {
    expect(formatMoney(0.004)).toBe("under $0.01");
    expect(formatMoney(null)).toBe("n/a (price unknown)");
    expect(formatMoney(undefined)).toBe("n/a (price unknown)");
    expect(formatMoney(NaN)).toBe("n/a (price unknown)");
  });
  it("a model with no price shows price unknown, never a figure", () => {
    expect(modelCost({ priced: false, usd: null })).toBe("price unknown");
    expect(modelCost({ priced: false, usd: 5 })).toBe("price unknown");
    expect(modelCost({ priced: true, usd: 1.5 })).toBe("$1.50");
  });
});

describe("numbers", () => {
  it("tokens", () => {
    expect(formatTokens(950)).toBe("950");
    expect(formatTokens(12_345)).toBe("12.3k");
    expect(formatTokens(1000)).toBe("1k");
    expect(formatTokens(1_200_000)).toBe("1.2M");
    expect(formatTokens(null)).toBe("n/a");
  });
  it("percentages and counts", () => {
    expect(formatPct(90)).toBe("90%");
    expect(formatPct(2.5)).toBe("2.5%");
    expect(formatPct(33.333)).toBe("33%");
    expect(formatPct(null)).toBe("n/a");
    expect(countOf({ pct: 7.5, count: 3, of: 40 })).toBe("3 of 40");
  });
  it("durations", () => {
    expect(formatDuration(420)).toBe("420 ms");
    expect(formatDuration(2100)).toBe("2.1 s");
    expect(formatDuration(45_000)).toBe("45 s");
    expect(formatDuration(65_000)).toBe("1 min 5 s");
    expect(formatDuration(120_000)).toBe("2 min");
    expect(formatDuration(null)).toBe("n/a");
    expect(formatMinutes(0.2)).toBe("under a minute");
    expect(formatMinutes(12.5)).toBe("13 minutes");
    expect(formatMinutes(65)).toBe("1 hour 5 minutes");
    expect(formatMinutes(3000)).toBe("2 days");
    expect(formatMinutes(null)).toBe("n/a");
  });
  it("day labels are read from the text, not moved by a time zone", () => {
    expect(dayLabel("2026-10-21")).toBe("Oct 21");
    expect(dayLabel("2026-01-05")).toBe("Jan 5");
    expect(dayLabel("nonsense")).toBe("nonsense");
  });
  it("says how long ago, and the date for anything older than a day", () => {
    const now = Date.parse("2026-10-22T12:00:00Z");
    expect(ago("2026-10-22T11:59:40Z", now)).toBe("just now");
    expect(ago("2026-10-22T11:55:00Z", now)).toBe("5 min ago");
    expect(ago("2026-10-22T09:00:00Z", now)).toBe("3 h ago");
    expect(ago("2026-10-20T09:00:00Z", now)).toBe("Oct 20");
    expect(ago(null, now)).toBe("Unknown time");
    expect(ago("garbage", now)).toBe("Unknown time");
  });
  it("every reason has plain words", () => {
    expect(REASON_LABEL.error).toBe("The chat failed");
    expect(REASON_LABEL.blocked).toBe("Refused by the assistant's rules");
    expect(REASON_LABEL.thumbs_down).toBe("Thumbs down");
    expect(REASON_LABEL.tool_failed).toBe("A tool failed");
    expect(REASON_LABEL.handed_off).toBe("Handed to a person");
    expect(REASON_LABEL.slow).toBe("Slow");
  });
  it("tips: warnings first, the order inside each group kept", () => {
    const tips = [
      { id: "a", severity: "info" as const, text: "" }, { id: "b", severity: "warn" as const, text: "" },
      { id: "c", severity: "info" as const, text: "" }, { id: "d", severity: "warn" as const, text: "" },
    ];
    expect(sortTips(tips).map((t) => t.id)).toEqual(["b", "d", "a", "c"]);
  });
});

describe("chart geometry", () => {
  it("a tidy top for the scale", () => {
    expect(niceMax(0)).toBe(1);
    expect(niceMax(7)).toBe(10);
    expect(niceMax(30)).toBe(50);
    expect(niceMax(100)).toBe(100);
    expect(niceMax(101)).toBe(200);
    expect(niceMax(NaN)).toBe(1);
  });
  it("bar heights are a share of the top and stay inside the box", () => {
    expect(barHeights([0, 25, 50, 99], 50)).toEqual([0, 50, 100, 100]);
    expect(barHeights([5, NaN, -3], 10)).toEqual([50, 0, 0]);
    expect(barHeights([5], 0)).toEqual([0]);
  });
  it("the line breaks at a day with no figure and a lone day still shows", () => {
    expect(linePoints([1, 2, null, 2, null, 1], 2)).toEqual(["8.33,50.00 25.00,0.00", "58.33,0.00 58.33,0.00", "91.67,50.00 91.67,50.00"]);
    expect(linePoints([null, null], 2)).toEqual([]);
    expect(linePoints([], 2)).toEqual([]);
  });
  it("labels the first and last day and a few between", () => {
    expect(labelledDays(0)).toEqual([]);
    expect(labelledDays(1)).toEqual([0]);
    expect(labelledDays(7)).toEqual([0, 2, 4, 6]);
    expect(labelledDays(90)).toEqual([0, 15, 30, 45, 60, 75, 89]);
  });
});

describe("asInsights", () => {
  const full = {
    generatedAt: "2026-10-22T10:00:00Z", days: 7, agentId: "support", since: "2026-10-15T10:00:00Z", firstTurnAt: null,
    totals: { conversations: 12, turns: 40, users: 5, inputTokens: 400000, outputTokens: 100000, toolCalls: 30, toolErrors: 1, blocked: 1, errors: 1, handedOff: 4, rated: 10, up: 8, down: 2 },
    latencyMs: { p50: 2100, p95: 9000, avg: 3000 },
    byDay: [{ day: "2026-10-21", turns: 3, inputTokens: 1, outputTokens: 1, errors: 0, up: 0, down: 0 }],
    byModel: [{ model: "claude-sonnet-4-5", turns: 40, inputTokens: 400000, outputTokens: 100000 }],
    tools: [{ name: "lookup", calls: 10, errors: 2, avgMs: 400, failurePct: 20 }],
    problems: [{ conversationId: "c1", at: "2026-10-21T09:00:00Z", message: "Hi", reason: "error", detail: "boom" }],
    handoffs: { total: 4, open: 1, claimed: 1, resolved: 2, avgResolveMinutes: 12.5 },
    cost: { estimatedUsd: 2.7, partial: false, perChatUsd: 0.225, perTurnUsd: 0.0675, byModel: [{ model: "claude-sonnet-4-5", turns: 40, inputTokens: 400000, outputTokens: 100000, usd: 2.7, priced: true }], byDay: [{ day: "2026-10-21", usd: 0.1 }], unpricedModels: [], note: "Estimated from list prices; your bill may differ." },
    quality: { answeredWithoutPerson: { pct: 90, count: 36, of: 40 }, thumbsUp: { pct: 80, count: 8, of: 10 }, errors: { pct: 2.5, count: 1, of: 40 }, blocked: { pct: 2.5, count: 1, of: 40 }, toolFailures: { pct: 3.3, count: 1, of: 30 }, speed: { p50Ms: 2100, p95Ms: 9000, avgMs: 3000, slow: false } },
    tips: [{ id: "x", severity: "warn", text: "Look at it." }],
  };

  it("reads a good answer as it is", () => {
    const got = asInsights(full)!;
    expect(got.totals.turns).toBe(40);
    expect(got.cost.estimatedUsd).toBe(2.7);
    expect(got.cost.byModel[0].priced).toBe(true);
    expect(got.quality.thumbsUp).toEqual({ pct: 80, count: 8, of: 10 });
    expect(got.tools[0].failurePct).toBe(20);
    expect(got.problems[0].reason).toBe("error");
    expect(got.tips[0].severity).toBe("warn");
  });
  it.each([null, undefined, 5, "x", [], {}, { totals: null }, { totals: [] }])("%j is not an insights answer", (raw) => {
    expect(asInsights(raw)).toBeNull();
  });
  it("odd fields become zeros, nulls and empty lists, and nothing throws", () => {
    const got = asInsights({
      totals: { turns: "40", up: NaN, errors: -4 }, latencyMs: "fast", byDay: "no", byModel: [1, null, { model: 7 }], tools: { a: 1 },
      problems: [{ reason: "<b>x</b>", message: 5 }], handoffs: [], cost: { estimatedUsd: "free", byModel: [{ model: "m", priced: true, usd: null }] },
      quality: { thumbsUp: { pct: 50, count: 9, of: 0 } }, tips: "none", warning: 12,
    })!;
    expect(got.totals).toMatchObject({ turns: 0, up: 0, errors: 0 });
    expect(got.latencyMs).toEqual({ p50: null, p95: null, avg: null });
    expect(got.byDay).toEqual([]);
    expect(got.byModel).toEqual([{ model: "", turns: 0, inputTokens: 0, outputTokens: 0 }]);
    expect(got.tools).toEqual([]);
    expect(got.problems[0]).toMatchObject({ reason: "other", message: "" });
    expect(got.cost.estimatedUsd).toBeNull();
    expect(got.cost.byModel[0]).toMatchObject({ priced: false, usd: null });
    expect(got.quality.thumbsUp).toEqual({ pct: null, count: 0, of: 0 });
    expect(got.tips).toEqual([]);
    expect(got.warning).toBeUndefined();
    expect(got.days).toBe(7);
  });
  it("caps the lists and the text", () => {
    const got = asInsights({
      totals: {}, tools: Array.from({ length: 500 }, (_, i) => ({ name: `t${i}`, calls: 1 })), tips: Array.from({ length: 50 }, () => ({ id: "a", text: "x" })),
      problems: [{ message: "m".repeat(5000), detail: "d".repeat(5000) }],
    })!;
    expect(got.tools).toHaveLength(50);
    expect(got.tips).toHaveLength(5);
    expect(got.problems[0].message).toHaveLength(300);
  });
});

describe("a live app's answer: the extras are read, checked and capped", () => {
  const base = { totals: { turns: 10 } };
  const live = {
    ...base, mode: "stream", range: "24h", granularity: "hour", since: "2026-10-21T10:00:00Z", until: "2026-10-22T10:00:00Z",
    freshness: { lastEventAt: "2026-10-22T09:59:56Z", lagSeconds: 4 }, exact: true, droppedEvents: 3,
    live: { turnsPerMinute: 42.5, activeUsers5m: 1234, errorRatePct5m: 2.5, p95Ms5m: 8200 },
    series: [{ t: "2026-10-22T09:00:00Z", turns: 5, errors: 1, inputTokens: 100, outputTokens: 20, usd: 0.05, activeUsers: 3 }],
    users: {
      active: 50000, newUsers: 12000, returning: 38000, approximate: true,
      activeByDay: [{ day: "2026-10-21", active: 40000 }],
      byRole: [{ role: "Admin", users: 3000, turns: 1200, usd: 4.5, thumbsDownPct: 3.2 }],
      top: [{ userKey: "a1b2c3d4e5f60123456789ef", role: "Admin", turns: 90, inputTokens: 1, outputTokens: 2, usd: 0.5, errors: 2, thumbsDown: 1, lastSeenAt: "2026-10-22T09:00:00Z" }],
    },
  };

  it("reads every new field as given", () => {
    const got = asInsights(live)!;
    expect(got).toMatchObject({ mode: "stream", range: "24h", granularity: "hour", exact: true, droppedEvents: 3, until: "2026-10-22T10:00:00Z", days: 1 });
    expect(got.freshness).toEqual({ lastEventAt: "2026-10-22T09:59:56Z", lagSeconds: 4 });
    expect(got.live).toEqual({ turnsPerMinute: 42.5, activeUsers5m: 1234, errorRatePct5m: 2.5, p95Ms5m: 8200 });
    expect(got.series).toEqual([{ t: "2026-10-22T09:00:00Z", turns: 5, errors: 1, inputTokens: 100, outputTokens: 20, usd: 0.05, activeUsers: 3 }]);
    expect(got.users!.active).toBe(50000);
    expect(got.users!.approximate).toBe(true);
    expect(got.users!.byRole[0]).toEqual({ role: "Admin", users: 3000, turns: 1200, usd: 4.5, thumbsDownPct: 3.2 });
    expect(got.users!.top[0].userKey).toBe("a1b2c3d4e5f60123456789ef");
  });

  it("a development snapshot has none of them, and parses exactly as before", () => {
    const got = asInsights(base)!;
    for (const k of ["mode", "range", "granularity", "until", "freshness", "exact", "droppedEvents", "live", "series", "users"]) expect(got, k).not.toHaveProperty(k);
    expect(got.days).toBe(7);
  });

  it("caps the lists: 1500 buckets, 20 people, 12 roles, 92 days", () => {
    const got = asInsights({
      ...base,
      series: Array.from({ length: 5000 }, (_, i) => ({ t: new Date(Date.UTC(2026, 0, 1) + i * 60_000).toISOString(), turns: 1 })),
      users: {
        top: Array.from({ length: 100 }, (_, i) => ({ userKey: `k${i}` })),
        byRole: Array.from({ length: 100 }, (_, i) => ({ role: `r${i}` })),
        activeByDay: Array.from({ length: 400 }, (_, i) => ({ day: `2026-01-${String((i % 28) + 1).padStart(2, "0")}`, active: 1 })),
      },
    })!;
    expect(got.series).toHaveLength(1500);
    expect(got.users!.top).toHaveLength(20);
    expect(got.users!.byRole).toHaveLength(12);
    expect(got.users!.activeByDay).toHaveLength(92);
  });

  it("hostile values become zeros, nulls and nothing, and never throw", () => {
    const got = asInsights({
      ...base, mode: "batch", range: "10y", granularity: "second", until: "yesterday", freshness: { lastEventAt: "soon", lagSeconds: -5 },
      exact: "yes", droppedEvents: "many", live: { turnsPerMinute: "fast", activeUsers5m: -3, errorRatePct5m: 900, p95Ms5m: NaN },
      series: [null, 5, "x", { t: "not a date", turns: 9 }, { t: "2026-10-22T09:00:00Z", turns: 2, errors: 99, usd: "free", activeUsers: -1, inputTokens: 1e400 }, { turns: 1 }],
      users: {
        active: "50", approximate: "true", activeByDay: [{ day: "<b>", active: 1 }, { day: "2026-13-45x", active: 1 }, { day: "2026-10-21", active: -2 }],
        byRole: [{}, { role: "x".repeat(500), users: 1e30, thumbsDownPct: 250 }],
        top: [{ userKey: "" }, { userKey: "z".repeat(500), role: 7, lastSeenAt: "never", usd: -4 }, "no", null],
      },
    })!;
    expect(got.mode).toBeUndefined();
    expect(got.range).toBeUndefined();
    expect(got.granularity).toBeUndefined();
    expect(got.until).toBeNull();
    expect(got.freshness).toEqual({ lastEventAt: null, lagSeconds: 0 });
    expect(got.exact).toBeUndefined();
    expect(got.droppedEvents).toBe(0);
    expect(got.live).toEqual({ turnsPerMinute: 0, activeUsers5m: 0, errorRatePct5m: 100, p95Ms5m: null });
    expect(got.series).toHaveLength(1);
    expect(got.series![0]).toMatchObject({ turns: 2, errors: 2, usd: null, activeUsers: 0, inputTokens: 0 });
    expect(got.users!.active).toBe(0);
    expect(got.users!.approximate).toBe(false);
    expect(got.users!.activeByDay).toEqual([{ day: "2026-10-21", active: 0 }]);
    expect(got.users!.byRole[0]).toMatchObject({ role: "(no role)", users: 0, usd: null });
    expect(got.users!.byRole[1].role).toHaveLength(60);
    expect(got.users!.byRole[1].thumbsDownPct).toBe(100);
    expect(got.users!.top).toHaveLength(1);
    expect(got.users!.top[0]).toMatchObject({ role: null, lastSeenAt: null, usd: 0 });
    expect(got.users!.top[0].userKey).toHaveLength(64);
  });

  it("an answer that is not an object where one is expected is left out, not a crash", () => {
    const got = asInsights({ ...base, live: [], freshness: "now", users: 5, series: "lots" })!;
    for (const k of ["live", "freshness", "users", "series"]) expect(got, k).not.toHaveProperty(k);
  });
});

describe("a live app: ranges, freshness and words", () => {
  it("five ranges; a development app answers the last three and shows 7 days for an hour or a day", () => {
    expect(RANGE_CHOICES.map((r) => r.label)).toEqual(["1 hour", "24 hours", "7 days", "30 days", "90 days"]);
    expect(devRange("1h")).toBe("7d");
    expect(devRange("24h")).toBe("7d");
    expect(devRange("30d")).toBe("30d");
    expect(rangeDays("24h")).toBe(1);
    expect(rangeDays("90d")).toBe(90);
    expect([granularityFor("1h"), granularityFor("24h"), granularityFor("7d"), granularityFor("30d"), granularityFor("90d")]).toEqual(["minute", "hour", "hour", "day", "day"]);
  });
  it("how long ago", () => {
    expect(secondsAgo(0)).toBe("just now");
    expect(secondsAgo(1)).toBe("1 second ago");
    expect(secondsAgo(4)).toBe("4 seconds ago");
    expect(secondsAgo(59.4)).toBe("59 seconds ago");
    expect(secondsAgo(60)).toBe("1 minute ago");
    expect(secondsAgo(150)).toBe("2 minutes ago");
    expect(secondsAgo(7200)).toBe("2 hours ago");
    expect(secondsAgo(3 * 86400)).toBe("3 days ago");
    expect(secondsAgo(null)).toBe("a while ago");
    expect(secondsAgo(NaN)).toBe("a while ago");
  });
  it("the freshness line, with and without every chat counted", () => {
    expect(freshnessText({ lastEventAt: "x", lagSeconds: 4 }, true)).toBe("Updated 4 seconds ago, every chat counted");
    expect(freshnessText({ lastEventAt: "x", lagSeconds: 300 }, undefined)).toBe("Updated 5 minutes ago");
    expect(freshnessText({ lastEventAt: "x", lagSeconds: 301 }, true)).toBe("The newest chat arrived 5 minutes ago, every chat counted");
    expect(freshnessText({ lastEventAt: "x", lagSeconds: 4 }, false)).toBe("Updated 4 seconds ago, the counts are approximate");
    expect(freshnessText({ lastEventAt: null, lagSeconds: null }, true)).toBe("No chats have arrived yet, every chat counted");
    expect(freshnessText(null, undefined)).toBe("No chats have arrived yet");
  });
  it("the strip is live under 15 seconds", () => {
    expect(isLiveNow({ lastEventAt: "x", lagSeconds: 0 })).toBe(true);
    expect(isLiveNow({ lastEventAt: "x", lagSeconds: 14.9 })).toBe(true);
    expect(isLiveNow({ lastEventAt: "x", lagSeconds: 15 })).toBe(false);
    expect(isLiveNow({ lastEventAt: null, lagSeconds: null })).toBe(false);
    expect(isLiveNow(null)).toBe(false);
  });
  it("events that were not accepted are always said, with a reason", () => {
    expect(droppedText(0)).toBeNull();
    expect(droppedText(undefined)).toBeNull();
    expect(droppedText(1)).toMatch(/^1 event was not accepted in this time, so these numbers are a little low\./);
    expect(droppedText(12345)).toMatch(/^12,345 events were not accepted in this time/);
    expect(droppedText(5)).toMatch(/invalid.*too many arrived at once/);
  });
  it("counts and rates", () => {
    expect(formatCount(50000)).toBe("50,000");
    expect(formatCount(1234.6)).toBe("1,235");
    expect(formatCount(null)).toBe("n/a");
    expect(formatRate(0.44)).toBe("0.4");
    expect(formatRate(3)).toBe("3");
    expect(formatRate(1234.5)).toBe("1,235");
    expect(peopleCount(50000, true)).toBe("about 50,000");
    expect(peopleCount(7, false)).toBe("7");
    expect(shortKey("a1b2c3d4e5f60123456789ef")).toBe("a1b2c3d4…89ef");
    expect(shortKey("short")).toBe("short");
  });
});

describe("a live app: buckets on the axis", () => {
  const local = (y: number, mo: number, d: number, h: number, mi: number) => new Date(y, mo, d, h, mi).toISOString();
  it("a minute is 10:42, an hour is Oct 21, 14:00, a day is Oct 21", () => {
    expect(bucketLabel(local(2026, 9, 21, 10, 42), "minute")).toBe("10:42");
    expect(bucketLabel(local(2026, 9, 21, 9, 5), "minute")).toBe("09:05");
    expect(bucketLabel(local(2026, 9, 21, 14, 30), "hour")).toBe("Oct 21, 14:00");
    expect(bucketLabel("2026-10-21T00:00:00Z", "day")).toBe("Oct 21");
    expect(bucketLabel("2026-01-05T23:59:59Z", "day")).toBe("Jan 5");
  });
  it("a bucket that is not a date is shown as it is", () => {
    expect(bucketLabel("garbage", "hour")).toBe("garbage");
  });
  const rows = (n: number, step = 60_000): ChartRow[] =>
    seriesRows(Array.from({ length: n }, (_, i) => ({ t: new Date(Date.UTC(2026, 9, 21) + i * step).toISOString(), turns: i % 5, errors: i % 3 === 0 ? 1 : 0, inputTokens: 0, outputTokens: 0, usd: i % 4 === 0 ? null : 0.01, activeUsers: i % 7 })), "minute");
  it("draws no more columns than the limit and adds neighbours up, keeping every reply and every failure", () => {
    const all = rows(1440);
    const drawn = downsampleRows(all, maxColumns("minute"));
    expect(drawn.length).toBeLessThanOrEqual(120);
    expect(drawn.reduce((a, r) => a + r.turns, 0)).toBe(all.reduce((a, r) => a + r.turns, 0));
    expect(drawn.reduce((a, r) => a + r.errors, 0)).toBe(all.reduce((a, r) => a + r.errors, 0));
    expect(drawn[0].title).toContain(" to ");
    expect(drawn[0].activeUsers).toBe(6);
  });
  it("leaves a series that fits alone, and never loses a price that is known", () => {
    const small = rows(60);
    expect(downsampleRows(small, 120)).toBe(small);
    const mixed = downsampleRows([{ day: "a", label: "a", turns: 1, errors: 0, usd: null, activeUsers: 1 }, { day: "b", label: "b", turns: 1, errors: 0, usd: 0.02, activeUsers: 1 }], 1);
    expect(mixed[0].usd).toBe(0.02);
    const none = downsampleRows([{ day: "a", label: "a", turns: 1, errors: 0, usd: null, activeUsers: 1 }, { day: "b", label: "b", turns: 1, errors: 0, usd: null, activeUsers: 1 }], 1);
    expect(none[0].usd).toBeNull();
    expect(downsampleRows(small, 0)).toBe(small);
    expect(maxColumns("hour")).toBe(180);
  });
  it("a development app's days become rows with their cost", () => {
    const got = dayRows({
      byDay: [{ day: "2026-10-20", turns: 3, inputTokens: 0, outputTokens: 0, errors: 1, up: 0, down: 0 }, { day: "2026-10-21", turns: 4, inputTokens: 0, outputTokens: 0, errors: 0, up: 0, down: 0 }],
      cost: { byDay: [{ day: "2026-10-20", usd: 0.5 }] } as any,
    });
    expect(got.map((r) => [r.label, r.turns, r.errors, r.usd])).toEqual([["Oct 20", 3, 1, 0.5], ["Oct 21", 4, 0, null]]);
  });
});

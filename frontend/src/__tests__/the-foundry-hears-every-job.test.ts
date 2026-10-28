/**
 * The Foundry reads the project's own feed — every job's ledger, narrated on
 * the server — while it is on screen: one stream per project however many
 * Foundries show it, and only `office` frames reach the floor.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const calls: string[] = [];
const aborted: string[] = [];

vi.mock("@/lib/api", () => ({
  authFetch: vi.fn(async (url: string, init: RequestInit) => {
    calls.push(url);
    init.signal?.addEventListener("abort", () => aborted.push(url));
    // A body that never ends, as a live feed does.
    return new Response(new ReadableStream({ start() {} }), { status: 200 });
  }),
}));

import { officeFrames, watchFoundry } from "@/components/virtual-office/feed";

afterEach(() => { calls.length = 0; aborted.length = 0; });

describe("reading the feed", () => {
  it("keeps the office frames, and a half-written one for the next read", () => {
    const body =
      'event: ready\ndata: {}\n\n' +
      'event: office\ndata: {"type":"agent_start","agent":"data_model"}\n\n' +
      'event: ping\ndata: {}\n\n' +
      'event: office\ndata: {"type":"agent_status","agent":"workflow","status":"Wiring the approval"}\n\n' +
      'event: office\ndata: {"type":"agent_comp';
    const { events, rest } = officeFrames(body);
    expect(events).toEqual([
      { type: "agent_start", agent: "data_model" },
      { type: "agent_status", agent: "workflow", status: "Wiring the approval" },
    ]);
    expect(rest).toBe('event: office\ndata: {"type":"agent_comp');
  });
});

describe("watching a project", () => {
  it("opens one stream however many Foundries watch, and closes it with the last", async () => {
    const stopTab = watchFoundry("p1");
    const stopCard = watchFoundry("p1");
    await new Promise((r) => setTimeout(r, 0));
    expect(calls.filter((u) => u.endsWith("/api/projects/p1/office"))).toHaveLength(1);
    stopTab();
    expect(aborted).toHaveLength(0);
    stopCard();
    expect(aborted).toHaveLength(1);
  });
});

/**
 * Unit tests for the orchestrator's grouping + retry logic.
 *
 * These stub out the real Playwright pool + runners so they run in
 * milliseconds without a browser. Live browser-driven acceptance lives in
 * SV-3's live-mode E2E on UAT.
 */
import { describe, expect, it, vi } from "vitest";
import type { BrowserPool } from "../browserPool.js";
import { runBatch } from "../orchestrator.js";
import { Evidence, Interaction, RunRequest, emptyEvidence } from "../types.js";

// A fake BrowserPool that vends the same "context" each acquire — the
// orchestrator only calls .close on release, we can no-op.
function fakePool(): BrowserPool {
  return {
    warm: async () => {},
    acquire: async () => ({
      context: {} as any,
      release: async () => {},
    }),
    close: async () => {},
  } as unknown as BrowserPool;
}

// Stub the runners module so runInteraction returns whatever Evidence we
// programme per interaction id.
function makeRunReq(interactions: Interaction[]): RunRequest {
  return {
    project_id: "test",
    target: "preview",
    base_url: "http://x",
    interactions,
    parallelism: 1,
  };
}

const routeI = (id: string, route = "/x"): Interaction => ({
  id, kind: "route", route, requires_auth: false,
});

describe("runBatch", () => {
  it("groups by route so same-page runs stay serial", async () => {
    // Stub runners.runInteraction to record call order.
    const calls: string[] = [];
    vi.doMock("../runners.js", () => ({
      runInteraction: async (_c: unknown, i: Interaction) => {
        calls.push(i.id);
        const ev = emptyEvidence();
        ev.status = 200;
        return ev;
      },
    }));
    const { runBatch: rb } = await import("../orchestrator.js");
    const rep = await rb(
      makeRunReq([routeI("a", "/foo"), routeI("b", "/foo"), routeI("c", "/bar")]),
      fakePool(),
    );
    expect(rep.interactions_run).toBe(3);
    // Within same group order is preserved.
    const fooIdx = calls.indexOf("a");
    expect(calls.indexOf("b")).toBeGreaterThan(fooIdx);
    vi.resetModules();
  });

  it("marks a flake when interaction passes on retry", async () => {
    let attempt = 0;
    vi.doMock("../runners.js", () => ({
      runInteraction: async () => {
        attempt += 1;
        const ev = emptyEvidence();
        ev.status = attempt === 1 ? 500 : 200; // fail first, pass on retry
        return ev;
      },
    }));
    const { runBatch: rb } = await import("../orchestrator.js");
    const rep = await rb(makeRunReq([routeI("a")]), fakePool());
    expect(rep.interactions_passed).toBe(1);
    expect(rep.interactions_flaky).toBe(1);
    expect(rep.faults).toHaveLength(0);
    vi.resetModules();
  });

  it("records a fault only for failures that persist through retry", async () => {
    vi.doMock("../runners.js", () => ({
      runInteraction: async () => {
        const ev = emptyEvidence();
        ev.status = 500;
        return ev;
      },
    }));
    const { runBatch: rb } = await import("../orchestrator.js");
    const rep = await rb(makeRunReq([routeI("a")]), fakePool());
    expect(rep.interactions_passed).toBe(0);
    expect(rep.faults).toHaveLength(1);
    expect(rep.faults[0].interaction_id).toBe("a");
    expect(rep.faults[0].passed).toBe(false);
    vi.resetModules();
  });

  it("emits verify.started + verify.done events", async () => {
    vi.doMock("../runners.js", () => ({
      runInteraction: async () => {
        const ev = emptyEvidence();
        ev.status = 200;
        return ev;
      },
    }));
    const { runBatch: rb } = await import("../orchestrator.js");
    const events: string[] = [];
    await rb(makeRunReq([routeI("a")]), fakePool(), {
      onEvent: (t) => events.push(t),
    });
    expect(events[0]).toBe("verify.started");
    expect(events.at(-1)).toBe("verify.done");
    vi.resetModules();
  });
});

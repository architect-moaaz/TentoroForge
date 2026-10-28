/**
 * The agents are people in the Foundry: each has a name and a title, says
 * what they are doing when you point at them, and introduces themselves when
 * clicked. The cockpit's agent dashboard calls them the same thing, from the
 * one persona file (`lib/agent-personas.json`).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AGENT_REGISTRY, AGENT_BY_ID } from "@/components/virtual-office/types";
import { doingNow } from "@/components/virtual-office/hud/AgentTooltip";
import { PERSONAS, agentLabel, agentOf } from "@/lib/agentPersonas";
import type { AgentReport } from "@/lib/admin-types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("the Foundry's cast", () => {
  it("every agent at a desk has a name, a title and words of their own", () => {
    for (const a of AGENT_REGISTRY) {
      const p = PERSONAS[a.id];
      expect(p, a.id).toBeTruthy();
      expect(a.name).toBe(p.name);
      expect(a.role).toBe(p.title);
      expect(a.intro).toMatch(new RegExp(`^I'm ${p.name}\\.`));
    }
    expect(AGENT_BY_ID.data_model.name).toBe("Bob");
    expect(AGENT_BY_ID.workflow.name).toBe("Todd");
    expect(AGENT_BY_ID.smith.name).toBe("Smith");
  });

  it("every agent wears a face drawn for them, standing and at the desk", async () => {
    const { existsSync } = await import("node:fs");
    const { join } = await import("node:path");
    for (const a of AGENT_REGISTRY) {
      const key = PERSONAS[a.id].name.toLowerCase();
      expect(a.spriteKey, a.id).toBe(key);
      for (const pose of ["idle", "working"]) {
        expect(existsSync(join(process.cwd(), "public/sprites/characters", pose, `${key}.png`)), `${pose}/${key}`).toBe(true);
      }
    }
  });

  it("no two agents share a name", () => {
    const names = Object.values(PERSONAS).map((p) => p.name);
    expect(new Set(names).size).toBe(names.length);
  });
});

describe("what an agent is called wherever its work is recorded", () => {
  it("reads a build's usage row, a repair, a check and a plain key", () => {
    expect(agentOf("page_code:ui_engineer")).toBe("ui_engineer");
    expect(agentOf("workflow_steps:workflow:edit")).toBe("workflow");
    expect(agentOf("app_check")).toBe("testing");
    expect(agentOf("page_review")).toBe("page_reviewer");
    expect(agentOf("smith")).toBe("smith");
    expect(agentOf("nobody_at_all")).toBeNull();
    expect(agentLabel("page_code:ui_engineer")).toBe("Leo (UI engineer)");
    expect(agentLabel("nobody_at_all")).toBe("nobody_at_all");
  });
});

describe("pointing at an agent", () => {
  it("says what they are doing now, in words", () => {
    expect(doingNow({ state: "working", speechBubble: "Drafting the Orders page" })).toBe("Drafting the Orders page");
    expect(doingNow({ state: "working", node: "page_code", tally: { done: 3, total: 9 } })).toMatch(/\(3 of 9\)$/);
    expect(doingNow({ state: "idle" })).toBe("Not working on anything right now");
    expect(doingNow({ state: "error" })).toBe("Stopped on a problem");
  });
});

const REPORT: AgentReport = {
  period: "month", from: 0, to: 1,
  agents: [
    { agent: "data_model", name: "Bob", title: "Data modeller", room: "data", calls: 40, repair_calls: 4, cost_usd: 12.5,
      input_tokens: 1, output_tokens: 1, busy_hours: 1.2, utilization: 0.01, apps: 3, steps: 20, done: 18, failed: 2,
      retries: 3, repairs: 5, unrepaired: 1, runs_lost: 0, reviews: 0, found: 0, success_rate: 0.9, median_s: 42,
      p90_s: 90, cost_per_step_usd: 0.69,
      top_failures: [{ reason: "BlueprintInvalid: data/entities/#/fields/#/references does not match", count: 2 }] },
    { agent: "workflow", name: "Todd", title: "Workflow engineer", room: "logic", calls: 0, repair_calls: 0, cost_usd: 0,
      input_tokens: 0, output_tokens: 0, busy_hours: 0, utilization: 0, apps: 0, steps: 0, done: 0, failed: 0,
      retries: 0, repairs: 0, unrepaired: 0, runs_lost: 0, reviews: 0, found: 0, success_rate: null, median_s: null,
      p90_s: null, cost_per_step_usd: null, top_failures: [] },
  ],
  totals: { calls: 40, steps: 20, done: 18, failed: 2, retries: 3, repairs: 5, unrepaired: 1, runs_lost: 0, reviews: 0,
            found: 0, cost_usd: 12.5, busy_hours: 1.2, success_rate: 0.9, active_agents: 1 },
  daily: [{ day: "2026-10-27", calls: 40, cost_usd: 12.5, failures: 2 }],
};

vi.mock("@/lib/admin-api", () => ({
  adminKeys: { agents: (p: string) => ["admin", "agents", p] },
  adminApi: { agents: vi.fn(async () => REPORT) },
}));

let root: Root | undefined; let el: HTMLDivElement;
beforeEach(() => { el = document.createElement("div"); document.body.appendChild(el); });
afterEach(() => { if (root) act(() => root!.unmount()); root = undefined; el.remove(); });

describe("the cockpit's agent dashboard", () => {
  it("lists the agents by name and opens one: who they are, and why their work failed", async () => {
    const { default: AgentsPage } = await import("@/app/admin/agents/page");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await act(async () => {
      root = createRoot(el);
      root.render(<QueryClientProvider client={client}><AgentsPage /></QueryClientProvider>);
    });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    const table = el.querySelector('[data-testid="agents-table"]')!;
    expect(table.textContent).toContain("Bob");
    expect(table.textContent).toContain("Todd");
    expect(table.textContent).toContain("90%");
    const bob = Array.from(table.querySelectorAll("tbody tr")).find((r) => r.textContent?.includes("Bob"))!;
    await act(async () => { (bob as HTMLElement).click(); });
    const detail = el.querySelector('[data-testid="agent-detail"]')!;
    expect(detail.textContent).toContain("I'm Bob.");
    expect(detail.textContent).toContain("BlueprintInvalid");
    expect(detail.textContent).toContain("2×");
  });
});

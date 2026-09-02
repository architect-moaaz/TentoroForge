/**
 * The office as a picture of a Blueprint DAG run.
 *
 * The store is where an SSE frame becomes a person moving, so these tests
 * drive it with the exact event stream `services/office_events.py`'s
 * OfficeNarrator produces and assert on what the floor would show. The three
 * outcomes the office could not previously draw — retrying, blocked, skipped —
 * get the most attention, because they are the ones that explain a
 * half-finished app.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { useOfficeStore } from "@/components/virtual-office/OfficeStateManager";
import {
  AGENT_REGISTRY,
  DEPARTMENTS,
  type OfficeEvent,
} from "@/components/virtual-office/types";
import { OFFICE_LAYOUT } from "@/components/virtual-office/layout";

function feed(...events: OfficeEvent[]) {
  const store = useOfficeStore.getState();
  for (const e of events) store.handleEvent(e);
}

function agentState(id: string) {
  const agent = useOfficeStore.getState().agents.get(id);
  if (!agent) throw new Error(`no such agent in the office: ${id}`);
  return agent.getState();
}

/** Run an agent's walk to completion so its arrival callback fires. */
function settle(id: string) {
  const agent = useOfficeStore.getState().agents.get(id);
  if (!agent) return;
  for (let i = 0; i < 400 && agent.getState().state === "walking"; i++) {
    agent.update(0.1, i * 100);
  }
}

const RUN_PLAN: OfficeEvent = {
  type: "run_plan",
  agents: ["data_model", "page_design", "a2ui_pages"],
  levels: [["data_model"], ["page_design"], ["a2ui_pages"]],
};

beforeEach(() => {
  useOfficeStore.getState().reset();
  useOfficeStore.getState().initialize();
});

describe("the office floor", () => {
  it("seats every agent at a desk in a declared department", () => {
    for (const info of AGENT_REGISTRY) {
      const room = OFFICE_LAYOUT.rooms.find((r) => r.id === info.room);
      expect(room, `${info.id} sits in unknown room ${info.room}`).toBeDefined();
      expect(room!.desks.some((d) => d.agentId === info.id)).toBe(true);
    }
  });

  it("has no two agents sharing a desk", () => {
    const seats = OFFICE_LAYOUT.rooms.flatMap((r) =>
      r.desks.map((d) => `${d.x},${d.y}`),
    );
    expect(new Set(seats).size).toBe(seats.length);
  });

  it("draws a room for every department and no others", () => {
    expect(OFFICE_LAYOUT.rooms.map((r) => r.id).sort()).toEqual(
      DEPARTMENTS.map((d) => d.id).sort(),
    );
  });

  it("keeps every desk inside its room's walls", () => {
    for (const room of OFFICE_LAYOUT.rooms) {
      for (const desk of room.desks) {
        expect(desk.x).toBeGreaterThanOrEqual(room.x);
        expect(desk.x).toBeLessThan(room.x + room.w);
        expect(desk.y).toBeGreaterThanOrEqual(room.y);
        expect(desk.y).toBeLessThan(room.y + room.h);
      }
    }
  });
});

describe("a run's roster", () => {
  it("puts everyone not on the plan back at their desk", () => {
    feed({ type: "agent_start", agent: "workflow", room: "logic" });
    settle("workflow");
    expect(agentState("workflow").state).toBe("working");

    feed(RUN_PLAN);
    settle("workflow");
    expect(useOfficeStore.getState().roster.has("workflow")).toBe(false);
    expect(agentState("workflow").state).toBe("idle");
  });

  it("sizes the progress bar from the plan, not from the whole office", () => {
    feed(RUN_PLAN);
    const s = useOfficeStore.getState();
    expect(s.nodesPlanned).toBe(3);
    expect(s.nodesDone).toBe(0);
    expect(s.totalProgress).toBe(0);
  });

  it("advances as nodes finish", () => {
    feed(RUN_PLAN, { type: "agent_complete", agent: "data_model" });
    expect(useOfficeStore.getState().nodesDone).toBe(1);
    expect(useOfficeStore.getState().totalProgress).toBe(33);
  });
});

describe("an agent at work", () => {
  it("walks to its own desk even if the event names a room that isn't there", () => {
    feed({ type: "agent_start", agent: "data_model", room: "nowhere" });
    settle("data_model");
    const desk = OFFICE_LAYOUT.rooms
      .find((r) => r.id === "data")!
      .desks.find((d) => d.agentId === "data_model")!;
    const at = agentState("data_model").position;
    expect(at).toEqual({ x: desk.x, y: desk.y });
  });

  it("reads a fan-out counter out of the status text", () => {
    feed(
      { type: "agent_start", agent: "a2ui_pages", room: "composition" },
      {
        type: "agent_status",
        agent: "a2ui_pages",
        status: "Composing page trees (4/18)",
        subject: "PAGE-009",
        progress: 3 / 18,
      },
    );
    expect(agentState("a2ui_pages").tally).toEqual({ done: 3, total: 18 });
  });

  it("does not show a counter for a node that runs once", () => {
    feed(
      { type: "agent_start", agent: "data_model", room: "data" },
      { type: "agent_status", agent: "data_model", status: "Designing the entities" },
    );
    expect(agentState("data_model").tally).toBeUndefined();
  });

  it("remembers which node it is running", () => {
    feed({ type: "agent_start", agent: "workflow", room: "logic", node: "workflows" });
    expect(agentState("workflow").node).toBe("workflows");
  });
});

describe("the three outcomes the office could not draw before", () => {
  it("shows a retry as a distinct pose, not as an error", () => {
    feed(
      { type: "agent_start", agent: "a2ui_pages", room: "composition" },
      {
        type: "agent_retry",
        agent: "a2ui_pages",
        attempt: 2,
        of: 2,
        reason: "DataTable is not in the catalog",
      },
    );
    const st = agentState("a2ui_pages");
    expect(st.state).toBe("retrying");
    expect(st.attempt).toEqual({ n: 2, of: 2 });
  });

  it("parks a blocked agent and keeps the reason for the panel", () => {
    feed({ type: "agent_blocked", agent: "backend", reason: "not ported yet" });
    expect(agentState("backend").state).toBe("blocked");
    expect(useOfficeStore.getState().blockedReasons.get("backend")).toBe(
      "not ported yet",
    );
    expect(useOfficeStore.getState().activeAgents.has("backend")).toBe(false);
  });

  it("distinguishes skipped from blocked", () => {
    feed({ type: "agent_skipped", agent: "api", reason: "waiting on database" });
    expect(agentState("api").state).toBe("skipped");
    expect(useOfficeStore.getState().skippedReasons.has("api")).toBe(true);
    expect(useOfficeStore.getState().blockedReasons.has("api")).toBe(false);
  });

  it("un-parks an agent that starts working again", () => {
    feed(
      { type: "agent_blocked", agent: "backend", reason: "not ported yet" },
      { type: "agent_start", agent: "backend", room: "data" },
    );
    settle("backend");
    expect(agentState("backend").state).toBe("working");
    expect(useOfficeStore.getState().blockedReasons.has("backend")).toBe(false);
  });

  it("lets a status message pull a retrying agent back to work", () => {
    feed(
      { type: "agent_start", agent: "a2ui_pages", room: "composition" },
      { type: "agent_retry", agent: "a2ui_pages", attempt: 2, of: 2 },
      { type: "agent_status", agent: "a2ui_pages", status: "PAGE-009 ✓" },
    );
    expect(agentState("a2ui_pages").state).toBe("working");
  });
});

describe("artifact deliveries", () => {
  it("queues a parcel between two desks without moving anyone", () => {
    feed({ type: "artifact_delivery", from: "data_model", to: "page_design" });
    const [parcel] = useOfficeStore.getState().deliveries;
    expect(parcel).toBeDefined();
    expect(agentState("data_model").state).not.toBe("walking");
    expect(parcel.from).toEqual(agentState("data_model").position);
    expect(parcel.to).toEqual(agentState("page_design").position);
  });

  it("hands the queue to the renderer exactly once", () => {
    feed(
      { type: "artifact_delivery", from: "data_model", to: "page_design" },
      { type: "artifact_delivery", from: "data_model", to: "workflow" },
    );
    expect(useOfficeStore.getState().takeDeliveries()).toHaveLength(2);
    expect(useOfficeStore.getState().takeDeliveries()).toHaveLength(0);
  });

  it("ignores a delivery naming somebody who does not work here", () => {
    feed({ type: "artifact_delivery", from: "data_model", to: "nobody" });
    expect(useOfficeStore.getState().deliveries).toHaveLength(0);
  });
});

describe("how long the office stays on screen", () => {
  it("is not up before a run starts", () => {
    expect(useOfficeStore.getState().runActive).toBe(false);
  });

  it("goes up on the roster and stays up through the work", () => {
    feed(RUN_PLAN);
    expect(useOfficeStore.getState().runActive).toBe(true);

    feed(
      { type: "agent_start", agent: "data_model", room: "data" },
      { type: "agent_complete", agent: "data_model" },
      { type: "artifact_delivery", from: "data_model", to: "page_design" },
    );
    expect(useOfficeStore.getState().runActive).toBe(true);
  });

  it("comes down on the shipping party", () => {
    feed(RUN_PLAN, { type: "build_success", total_files: 12 });
    expect(useOfficeStore.getState().runActive).toBe(false);
  });

  it("comes down on a run that ends with failures too", () => {
    feed(RUN_PLAN, { type: "run_complete", completed: 1, failed: 1 });
    expect(useOfficeStore.getState().runActive).toBe(false);
  });

  it("comes down when the agents walk out", () => {
    feed(RUN_PLAN, { type: "credits_exhausted", message: "no credits" });
    expect(useOfficeStore.getState().runActive).toBe(false);
  });

  it("can be brought down by a producer that knows nothing more is coming", () => {
    // The request failed mid-run: no terminal frame will ever arrive, and
    // without this the office would wait for one indefinitely.
    feed(RUN_PLAN);
    useOfficeStore.getState().endRun();
    expect(useOfficeStore.getState().runActive).toBe(false);
  });

  it("stays down for the legacy relay, which never sends a roster", () => {
    // That path is governed by its own stream, and this must not change it.
    feed(
      { type: "phase_start", phase: "schema" },
      { type: "agent_start", agent: "data_model", room: "data" },
      { type: "phase_complete", phase: "schema" },
    );
    expect(useOfficeStore.getState().runActive).toBe(false);
  });
});

describe("the end of a run", () => {
  it("stands everyone down but leaves the parked poses alone", () => {
    feed(
      RUN_PLAN,
      { type: "agent_start", agent: "data_model", room: "data" },
      { type: "agent_blocked", agent: "backend", reason: "not ported yet" },
      { type: "agent_skipped", agent: "api", reason: "waiting on database" },
      { type: "run_complete", completed: 1, failed: 1, blocked: 1, skipped: 1 },
    );
    expect(agentState("backend").state).toBe("blocked");
    expect(agentState("api").state).toBe("skipped");
    expect(useOfficeStore.getState().activeAgents.size).toBe(0);
  });

  it("clears the parked poses when the build actually ships", () => {
    feed(
      { type: "agent_blocked", agent: "backend", reason: "not ported yet" },
      { type: "build_success", total_files: 12 },
    );
    expect(useOfficeStore.getState().blockedReasons.size).toBe(0);
  });
});

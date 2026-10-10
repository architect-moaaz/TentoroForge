/**
 * The office as a picture of the whole platform: the pipeline the engineer's
 * journal narrates, Smith at the Front Desk and wherever a step takes it, the
 * engines lighting with the step that runs them, and the Workbench trying
 * statements as the person they are about.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { useOfficeStore } from "@/components/virtual-office/OfficeStateManager";
import { AGENT_REGISTRY, DEPARTMENTS, ENGINES, PIPELINE, type OfficeEvent } from "@/components/virtual-office/types";
import { OFFICE_LAYOUT, benchSpot, visitorSpot, boardSpot, machineRect } from "@/components/virtual-office/layout";

function feed(...events: OfficeEvent[]) {
  const store = useOfficeStore.getState();
  for (const e of events) store.handleEvent(e);
}

function settle(id: string) {
  const agent = useOfficeStore.getState().agents.get(id);
  if (!agent) return;
  for (let i = 0; i < 600 && agent.getState().state === "walking"; i++) agent.update(0.1, i * 100);
}

function at(id: string) {
  return useOfficeStore.getState().agents.get(id)!.getState().position;
}

beforeEach(() => {
  useOfficeStore.getState().reset();
  useOfficeStore.getState().initialize();
});

describe("the floor", () => {
  it("has a room for every department and a desk for everyone, Smith at the front", () => {
    for (const d of DEPARTMENTS) {
      expect(OFFICE_LAYOUT.rooms.find((r) => r.id === d.id), d.id).toBeTruthy();
    }
    const smith = OFFICE_LAYOUT.rooms.find((r) => r.id === "front_desk")!.desks.find((d) => d.agentId === "smith");
    expect(smith).toBeTruthy();
    const engineer = AGENT_REGISTRY.find((a) => a.id === "engineer");
    expect(engineer?.room).toBe("architecture");
    for (const a of AGENT_REGISTRY) {
      const room = OFFICE_LAYOUT.rooms.find((r) => r.id === a.room)!;
      expect(room.desks.some((d) => d.agentId === a.id), `${a.id} has no desk`).toBe(true);
    }
  });

  it("stands every engine in its room, nowhere on a desk or a doorway", () => {
    for (const e of ENGINES) {
      const rect = machineRect(e.id);
      expect(rect, `${e.id} has no machine`).toBeTruthy();
      const room = OFFICE_LAYOUT.rooms.find((r) => r.id === e.room)!;
      expect(rect!.x).toBeGreaterThanOrEqual(room.x);
      expect(rect!.x + rect!.w).toBeLessThanOrEqual(room.x + room.w);
      for (const d of room.desks) {
        const onIt = d.x >= rect!.x && d.x < rect!.x + rect!.w && d.y >= rect!.y && d.y < rect!.y + rect!.h;
        expect(onIt, `${d.agentId}'s desk is under ${e.id}`).toBe(false);
      }
    }
    expect(ENGINES.map((e) => e.room).every((r) => ["engine_room", "workbench"].includes(r))).toBe(true);
  });
});

describe("the pipeline strip", () => {
  it("walks the stages the engineer's journal names, features counted", () => {
    feed({ type: "pipeline_stage", stage: "define", label: "Writing down what the application is for" });
    expect(useOfficeStore.getState().pipeline.stage).toBe("define");
    feed({ type: "pipeline_stage", stage: "build", label: "Building 2 features", features: ["M1", "M2"], done: [] });
    feed({ type: "pipeline_stage", stage: "feature", label: "Building Menu", feature: "M1", name: "Menu", index: 1, total: 2 });
    let p = useOfficeStore.getState().pipeline;
    expect(p.name).toBe("Menu");
    expect(p.total).toBe(2);
    feed({ type: "pipeline_stage", stage: "proof", label: "Menu: 2 of 2 statements hold", feature: "M1", name: "Menu",
           statements: 2, passed: 2, failing: [], done: true });
    p = useOfficeStore.getState().pipeline;
    expect(p.done).toEqual(["M1"]);
    expect(PIPELINE.find((s) => s.stages.includes("proof"))?.id).toBe("features");
    feed({ type: "pipeline_stage", stage: "stopped", label: "Orders is not built: 1 screen has no code", why: "no code" });
    expect(useOfficeStore.getState().pipeline.why).toBe("no code");
    settle("engineer");
    expect(at("engineer")).toEqual(visitorSpot());
    expect(useOfficeStore.getState().agents.get("engineer")!.getState().state).toBe("error");
  });

  it("sends the engineer to the bench for a proof and to the front for the handover", () => {
    feed({ type: "pipeline_stage", stage: "proof", label: "Menu: 1 of 1 statements hold", feature: "M1", name: "Menu",
           statements: 1, passed: 1, failing: [], done: true });
    settle("engineer");
    expect(at("engineer")).toEqual(benchSpot());
    feed({ type: "pipeline_stage", stage: "handover", label: "Built, tried and handed over" });
    settle("engineer");
    expect(at("engineer")).toEqual(visitorSpot());
    expect(useOfficeStore.getState().agents.get("engineer")!.getState().state).toBe("celebrating");
  });
});

describe("Smith at the Front Desk", () => {
  it("reads at the desk, tries at the bench, writes at the author's desk, asks at the counter, pins a fault on the board", () => {
    feed({ type: "smith_turn", status: "start", mode: "conversation", text: "Add to cart does nothing" });
    expect(useOfficeStore.getState().smith.inTurn).toBe(true);
    expect(useOfficeStore.getState().runActive).toBe(true);
    settle("smith");
    const desk = OFFICE_LAYOUT.rooms.find((r) => r.id === "front_desk")!.desks.find((d) => d.agentId === "smith")!;
    expect(at("smith")).toEqual({ x: desk.x, y: desk.y });

    feed({ type: "smith_step", tool: "open_page", kind: "try", status: "read", said: "The button sent nothing" });
    settle("smith");
    expect(at("smith")).toEqual(benchSpot());

    feed({ type: "smith_step", tool: "edit_file", kind: "write", status: "resolved", said: "Wired the button" });
    settle("smith");
    const uiDesk = OFFICE_LAYOUT.rooms.find((r) => r.id === "composition")!.desks.find((d) => d.agentId === "ui_engineer")!;
    expect(Math.abs(at("smith").x - uiDesk.x)).toBe(1);
    expect(at("smith").y).toBe(uiDesk.y);
    expect(useOfficeStore.getState().agents.get("ui_engineer")!.getState().state).toBe("working");

    feed({ type: "smith_step", tool: "report_platform_fault", kind: "report", status: "resolved", said: "the guest cart has no owner" });
    settle("smith");
    expect(at("smith")).toEqual(boardSpot());

    feed({ type: "smith_step", tool: "ask_user", kind: "ask", status: "read", said: "Which currency?" });
    settle("smith");
    expect(at("smith")).toEqual(visitorSpot());
    expect(useOfficeStore.getState().smith.steps).toBe(4);

    feed({ type: "smith_turn", status: "end", mode: "conversation", outcome: "resolved", text: "Fixed and tried as the customer" });
    settle("smith");
    expect(at("smith")).toEqual(visitorSpot());
    expect(useOfficeStore.getState().smith.inTurn).toBe(false);
    expect(useOfficeStore.getState().runActive).toBe(false);
  });

  it("an unattended turn, the engineer's, does not hold the office open", () => {
    feed({ type: "smith_turn", status: "start", mode: "unattended", text: "While building Orders…" });
    expect(useOfficeStore.getState().runActive).toBe(false);
    feed({ type: "smith_turn", status: "end", mode: "unattended", outcome: "resolved", text: "done" });
    settle("smith");
    const desk = OFFICE_LAYOUT.rooms.find((r) => r.id === "front_desk")!.desks.find((d) => d.agentId === "smith")!;
    expect(at("smith")).toEqual({ x: desk.x, y: desk.y });
  });
});

describe("the engines and the Workbench", () => {
  it("light with the step that runs them and go dark when it finishes", () => {
    feed({ type: "agent_start", agent: "build", room: "shipping", action: "Assembling", node: "assemble" });
    const lit = useOfficeStore.getState().engines;
    expect(lit.get("data_engine")?.state).toBe("busy");
    expect(lit.get("workflow_engine")?.state).toBe("busy");
    feed({ type: "agent_complete", agent: "build", node: "assemble" });
    expect(useOfficeStore.getState().engines.get("data_engine")?.state).toBe("off");
  });

  it("take the backend's lights and the bench's words", () => {
    feed({ type: "engine", engine: "apps_db", state: "busy", detail: "preparing" });
    expect(useOfficeStore.getState().engines.get("apps_db")).toMatchObject({ state: "busy", detail: "preparing" });
    feed({ type: "engine", engine: "workbench", state: "on", detail: "served and signed in" });
    expect(useOfficeStore.getState().benchSays?.text).toBe("served and signed in");
    feed({ type: "engine", engine: "nothing", state: "on" });
    expect(useOfficeStore.getState().engines.has("nothing")).toBe(false);
  });

  it("count every statement tried and say what the bench found", () => {
    feed({ type: "trial", statement: "EXP-001", says: "A customer sees the menu", verdict: "trying", who: "Customer" });
    expect(useOfficeStore.getState().benchSays?.text).toBe("Trying as Customer: A customer sees the menu");
    expect(useOfficeStore.getState().engines.get("workbench")?.state).toBe("busy");
    feed({ type: "trial", statement: "EXP-001", says: "A customer sees the menu", verdict: "passed", who: "Customer" });
    feed({ type: "trial", statement: "EXP-002", says: "The baker marks sold out", verdict: "failed", who: "Baker" });
    feed({ type: "trial", statement: "EXP-003", says: "Nobody could sign in", verdict: "not_tried", who: "" });
    const t = useOfficeStore.getState().trials;
    expect(t).toMatchObject({ tried: 3, passed: 1, failed: 1, untried: 1 });
    expect(useOfficeStore.getState().benchSays?.type).toBe("error");
    feed({ type: "pipeline_stage", stage: "build", label: "Building 1 feature", features: ["M1"], done: [] });
    expect(useOfficeStore.getState().trials.tried).toBe(0);
  });
});

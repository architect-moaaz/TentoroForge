import { describe, it, expect, beforeEach } from "vitest";
import { useWorkflowSim, isTimerTask } from "@/stores/workflow-sim";
import type { SimApi } from "@/lib/workflow-sim/sim-api";
import type { InstanceDetailDTO, NodeLogDTO } from "@/lib/workflow-sim/types";

function makeApi(overrides: Partial<SimApi> = {}): SimApi {
  return {
    start: async () => ({ id: "i1", workflow_id: "w", workflow_name: "W", status: "running", current_node_ids: [], variables: {}, error_message: null }),
    getInstance: async () => ({ id: "i1", workflow_id: "w", workflow_name: "W", status: "running", current_node_ids: [], variables: {}, error_message: null, tasks: [] }),
    getLogs: async () => [],
    completeTask: async () => ({}),
    cancel: async () => ({}),
    ...overrides,
  };
}
const inst = (o: Partial<InstanceDetailDTO>): InstanceDetailDTO => ({ id: "i1", workflow_id: "w", workflow_name: "W", status: "running", current_node_ids: [], variables: {}, error_message: null, tasks: [], ...o });
const log = (node_id: string, status: NodeLogDTO["status"]): NodeLogDTO => ({ id: node_id + status, node_id, node_type: "action", node_label: node_id, status, output_snapshot: null, error_message: null, started_at: "2026-01-01T00:00:00.000Z", completed_at: "2026-01-01T00:00:00.000Z", duration_ms: 1 });

describe("useWorkflowSim", () => {
  beforeEach(() => useWorkflowSim.getState().reset());

  it("starts idle", () => {
    expect(useWorkflowSim.getState().phase).toBe("idle");
  });

  it("start() creates an instance and enters running", async () => {
    const api = makeApi();
    await useWorkflowSim.getState().start(api, "w", { days: 3 });
    expect(useWorkflowSim.getState().phase).toBe("running");
    expect(useWorkflowSim.getState().instanceId).toBe("i1");
  });

  it("poll() queues new logs for reveal and reflects completion", async () => {
    const api = makeApi({
      getInstance: async () => inst({ status: "completed" }),
      getLogs: async () => [log("a", "completed"), log("b", "completed")],
    });
    const s = useWorkflowSim.getState();
    await s.start(api, "w", {});
    await useWorkflowSim.getState().poll(api);
    expect(useWorkflowSim.getState().pendingReveal).toEqual(["a", "b"]);
    expect(useWorkflowSim.getState().nodeStatuses).toEqual({});
    useWorkflowSim.getState().revealNext();
    useWorkflowSim.getState().revealNext();
    expect(useWorkflowSim.getState().nodeStatuses).toEqual({ a: "done", b: "done" });
    expect(useWorkflowSim.getState().phase).toBe("completed");
  });

  it("poll() enters awaitingInput when the engine pauses with a task", async () => {
    const api = makeApi({
      getInstance: async () => inst({ status: "waiting", current_node_ids: ["appr"], tasks: [{ id: "t1", node_id: "appr", node_label: "Approve", task_type: "approval", status: "pending", input_data: null, output_data: null }] }),
      getLogs: async () => [log("a", "completed")],
    });
    await useWorkflowSim.getState().start(api, "w", {});
    await useWorkflowSim.getState().poll(api);
    useWorkflowSim.getState().revealNext();
    expect(useWorkflowSim.getState().phase).toBe("awaitingInput");
    expect(useWorkflowSim.getState().activeTask?.id).toBe("t1");
  });

  it("start() failure sets phase failed with an error", async () => {
    const api = makeApi({ start: async () => { throw new Error("boom"); } });
    await useWorkflowSim.getState().start(api, "w", {});
    expect(useWorkflowSim.getState().phase).toBe("failed");
    expect(useWorkflowSim.getState().error).toContain("boom");
  });

  it("poll() tolerates transient failures, then fails after the limit", async () => {
    const api = makeApi({ getInstance: async () => { throw new Error("net down"); } });
    await useWorkflowSim.getState().start(api, "w", {});
    // A single blip must NOT kill a healthy run — it stays running and retries.
    await useWorkflowSim.getState().poll(api);
    expect(useWorkflowSim.getState().phase).toBe("running");
    await useWorkflowSim.getState().poll(api);
    expect(useWorkflowSim.getState().phase).toBe("running");
    // Only after the 3rd consecutive failure does it give up.
    await useWorkflowSim.getState().poll(api);
    expect(useWorkflowSim.getState().phase).toBe("failed");
    expect(useWorkflowSim.getState().error).toContain("net down");
  });

  it("poll() clears the error streak after a good poll", async () => {
    let calls = 0;
    const api = makeApi({
      getInstance: async () => {
        calls += 1;
        if (calls === 1) throw new Error("blip");
        return { id: "i", status: "running", variables: {}, tasks: [], error_message: null } as never;
      },
    });
    await useWorkflowSim.getState().start(api, "w", {});
    await useWorkflowSim.getState().poll(api); // fails (streak=1), stays running
    expect(useWorkflowSim.getState().phase).toBe("running");
    await useWorkflowSim.getState().poll(api); // succeeds → streak reset
    expect(useWorkflowSim.getState().pollErrors).toBe(0);
  });

  it("settles to failed when the instance status is failed", async () => {
    const api = makeApi({
      getInstance: async () => inst({ status: "failed", error_message: "kaboom" }),
      getLogs: async () => [],
    });
    await useWorkflowSim.getState().start(api, "w", {});
    await useWorkflowSim.getState().poll(api);
    expect(useWorkflowSim.getState().phase).toBe("failed");
    expect(useWorkflowSim.getState().error).toBe("kaboom");
  });

  it("submitTask() completes the task and returns to running", async () => {
    let completedWith: any = null;
    const api = makeApi({
      completeTask: async (taskId, output) => { completedWith = { taskId, output }; return {}; },
      getInstance: async () => inst({ status: "running", current_node_ids: [], tasks: [] }),
      getLogs: async () => [log("a", "completed")],
    });
    const s = useWorkflowSim.getState();
    await s.start(api, "w", {});
    useWorkflowSim.setState({ phase: "awaitingInput", activeTask: { id: "t1", node_id: "appr", node_label: "A", task_type: "approval", status: "pending", input_data: null, output_data: null } });
    await useWorkflowSim.getState().submitTask(api, { decision: "approved", comment: "" });
    expect(completedWith.taskId).toBe("t1");
    expect(completedWith.output).toEqual({ decision: "approved", approved: true, comment: "" });
    while (useWorkflowSim.getState().pendingReveal.length) useWorkflowSim.getState().revealNext();
    expect(useWorkflowSim.getState().phase).toBe("running");
  });

  it("cancel() cancels the instance and sets phase cancelled", async () => {
    let cancelled = false;
    const api = makeApi({ cancel: async () => { cancelled = true; return {}; } });
    await useWorkflowSim.getState().start(api, "w", {});
    await useWorkflowSim.getState().cancel(api);
    expect(cancelled).toBe(true);
    expect(useWorkflowSim.getState().phase).toBe("cancelled");
  });

  it("isTimerTask identifies timer/wait task types", () => {
    expect(isTimerTask({ task_type: "timer_event" } as any)).toBe(true);
    expect(isTimerTask({ task_type: "timer" } as any)).toBe(true);
    expect(isTimerTask({ task_type: "wait" } as any)).toBe(true);
    expect(isTimerTask({ task_type: "approval" } as any)).toBe(false);
  });

  it("fastForwardTimer completes the timer task with empty output", async () => {
    let completedWith: any = null;
    const api = makeApi({ completeTask: async (id, o) => { completedWith = { id, o }; return {}; }, getInstance: async () => inst({ status: "completed", tasks: [] }), getLogs: async () => [] });
    await useWorkflowSim.getState().start(api, "w", {});
    useWorkflowSim.setState({ phase: "awaitingInput", activeTask: { id: "tm", node_id: "t", node_label: "Wait", task_type: "timer_event", status: "pending", input_data: null, output_data: null } });
    await useWorkflowSim.getState().fastForwardTimer(api);
    expect(completedWith).toEqual({ id: "tm", o: {} });
  });
});

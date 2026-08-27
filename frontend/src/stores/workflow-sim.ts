import { create } from "zustand";
import type { SimApi } from "@/lib/workflow-sim/sim-api";
import type { InstanceDetailDTO, NodeLogDTO, NodeVisualStatus, RunPhase, TaskDTO } from "@/lib/workflow-sim/types";
import { computeNodeStatuses } from "@/lib/workflow-sim/node-status";

const ACTIVE_TASK_STATUSES = new Set(["pending", "assigned", "active"]);

const TIMER_TASK_TYPES = new Set(["timer_event", "timer", "wait"]);

/** True for timer/wait/SLA tasks the simulator fast-forwards instead of waiting. */
export function isTimerTask(task: Pick<TaskDTO, "task_type">): boolean {
  return TIMER_TASK_TYPES.has(task.task_type);
}

interface SimState {
  phase: RunPhase;
  instanceId: string | null;
  instance: InstanceDetailDTO | null;
  logs: NodeLogDTO[];
  nodeStatuses: Record<string, NodeVisualStatus>;
  pendingReveal: string[]; // node ids queued for staggered reveal
  activeTask: TaskDTO | null;
  variables: Record<string, unknown>;
  error: string | null;

  reset(): void;
  start(api: SimApi, workflowId: string, variables: Record<string, unknown>): Promise<void>;
  poll(api: SimApi): Promise<void>;
  revealNext(): void;
  submitTask(api: SimApi, values: Record<string, unknown>): Promise<void>;
  cancel(api: SimApi): Promise<void>;
  fastForwardTimer(api: SimApi): Promise<void>;
}

const INITIAL = {
  phase: "idle" as RunPhase,
  instanceId: null,
  instance: null,
  logs: [] as NodeLogDTO[],
  nodeStatuses: {} as Record<string, NodeVisualStatus>,
  pendingReveal: [] as string[],
  activeTask: null,
  variables: {} as Record<string, unknown>,
  error: null,
};

/** Once the reveal queue is empty, derive phase/activeTask from the latest instance snapshot. */
function settle(get: () => SimState, set: (p: Partial<SimState>) => void) {
  const { pendingReveal, instance } = get();
  if (pendingReveal.length > 0 || !instance) return;
  const pausedTask = instance.tasks.find((t) => ACTIVE_TASK_STATUSES.has(t.status)) ?? null;
  if (instance.status === "completed") set({ phase: "completed", activeTask: null });
  else if (instance.status === "failed") set({ phase: "failed", activeTask: null, error: instance.error_message ?? "Workflow failed" });
  else if (instance.status === "cancelled") set({ phase: "cancelled", activeTask: null });
  else if (instance.status === "waiting" && pausedTask) set({ phase: "awaitingInput", activeTask: pausedTask });
  else set({ phase: "running", activeTask: null });
}

export const useWorkflowSim = create<SimState>((set, get) => ({
  ...INITIAL,

  reset: () => set({ ...INITIAL }),

  start: async (api, workflowId, variables) => {
    set({ ...INITIAL, phase: "starting" });
    try {
      const inst = await api.start(workflowId, variables);
      set({ phase: "running", instanceId: inst.id, variables: inst.variables ?? {} });
    } catch (e) {
      set({ phase: "failed", error: e instanceof Error ? e.message : String(e) });
    }
  },

  poll: async (api) => {
    const { instanceId, phase } = get();
    if (!instanceId || phase === "completed" || phase === "failed" || phase === "cancelled") return;
    try {
      const [instance, logs] = await Promise.all([api.getInstance(instanceId), api.getLogs(instanceId)]);
      const snap = get();
      const known = new Set(Object.keys(snap.nodeStatuses));
      const queued = new Set(snap.pendingReveal);
      const fresh = Array.from(new Set(logs.map((l) => l.node_id))).filter(
        (id) => !known.has(id) && !queued.has(id),
      );
      set({
        instance,
        logs,
        variables: instance.variables ?? {},
        pendingReveal: [...snap.pendingReveal, ...fresh],
      });
      settle(get, set);
    } catch (e) {
      set({ phase: "failed", error: e instanceof Error ? e.message : String(e) });
    }
  },

  revealNext: () => {
    const { pendingReveal, logs } = get();
    if (pendingReveal.length === 0) return;
    const [head, ...rest] = pendingReveal;
    const headStatus = computeNodeStatuses(
      logs.filter((l) => l.node_id === head),
      get().instance?.current_node_ids ?? [],
    );
    set({ nodeStatuses: { ...get().nodeStatuses, ...headStatus }, pendingReveal: rest });
    settle(get, set);
  },

  submitTask: async (api, values) => {
    const task = get().activeTask;
    if (!task) return;
    const { taskFormSpec, buildTaskOutput } = await import("@/lib/workflow-sim/task-form");
    const spec = taskFormSpec(task);
    const output = buildTaskOutput(spec, values);
    set({ phase: "running", activeTask: null });
    try {
      await api.completeTask(task.id, output);
      await get().poll(api);
    } catch (e) {
      set({ phase: "failed", error: e instanceof Error ? e.message : String(e) });
    }
  },

  cancel: async (api) => {
    const { instanceId } = get();
    if (!instanceId) { set({ phase: "cancelled", activeTask: null }); return; }
    try { await api.cancel(instanceId); } catch { /* best effort */ }
    set({ phase: "cancelled", activeTask: null });
  },

  fastForwardTimer: async (api) => {
    const task = get().activeTask;
    if (!task) return;
    set({ phase: "running", activeTask: null });
    try {
      await api.completeTask(task.id, {});
      await get().poll(api);
    } catch (e) {
      set({ phase: "failed", error: e instanceof Error ? e.message : String(e) });
    }
  },
}));

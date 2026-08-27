// frontend/src/lib/workflow-sim/sim-api.ts
import { api } from "@/lib/api";
import type { InstanceDetailDTO, NodeLogDTO, WorkflowInstanceDTO } from "./types";

/** The set of backend calls the simulator needs. Injectable so the store is testable. */
export interface SimApi {
  start(workflowId: string, variables: Record<string, unknown>): Promise<WorkflowInstanceDTO>;
  getInstance(instanceId: string): Promise<InstanceDetailDTO>;
  getLogs(instanceId: string): Promise<NodeLogDTO[]>;
  completeTask(taskId: string, outputData: Record<string, unknown>): Promise<unknown>;
  cancel(instanceId: string): Promise<unknown>;
}

export function realSimApi(projectId: string): SimApi {
  const base = `/api/projects/${projectId}`;
  return {
    start: (workflowId, variables) =>
      api.post<WorkflowInstanceDTO>(`${base}/workflows/start`, {
        workflow_id: workflowId,
        variables,
      }),
    getInstance: (instanceId) =>
      api.get<InstanceDetailDTO>(`${base}/workflow-instances/${instanceId}`),
    getLogs: (instanceId) =>
      api.get<NodeLogDTO[]>(`${base}/workflow-instances/${instanceId}/logs`),
    completeTask: (taskId, outputData) =>
      api.post(`${base}/tasks/${taskId}/complete`, { output_data: outputData }),
    cancel: (instanceId) =>
      api.post(`${base}/workflow-instances/${instanceId}/cancel`, {}),
  };
}

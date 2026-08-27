/** Barrel export for the workflow engine. */

// Domain
export { VariableResolver } from './domain/variable-resolver';
export { GatewayController } from './domain/gateway-controller';
export type {
  WorkflowInstanceStatus,
  TaskInstanceStatus,
  TaskType,
  NodeExecutionStatus,
  WorkflowDefinition,
  WorkflowNode,
  WorkflowEdge,
  WorkflowNodeConfig,
  WorkflowNodeData,
  WorkflowEdgeData,
  WorkflowDefinitionBody,
  WorkflowInstanceRecord,
  TaskInstanceRecord,
  ExecutionLogRecord,
} from './domain/types';

// Infrastructure
export {
  wfInstances,
  wfTaskInstances,
  wfExecutionLogs,
  wfInstancesRelations,
  wfTaskInstancesRelations,
  wfExecutionLogsRelations,
} from './infrastructure/schema';
export type {
  WfInstance,
  NewWfInstance,
  WfTaskInstance,
  NewWfTaskInstance,
  WfExecutionLog,
  NewWfExecutionLog,
} from './infrastructure/schema';
export { StateManager } from './infrastructure/state-manager';
export { ExecutionLogger } from './infrastructure/execution-logger';

// Engine
export { WorkflowEngine } from './engine/workflow-engine';
export { TaskExecutor } from './engine/task-executor';
export { TimerScheduler, parseDuration } from './engine/timer-scheduler';

// Actions
export { getDispatcher, ActionDispatcher } from './actions';

// AI
export { getAiHandler, AINodeHandler } from './ai';

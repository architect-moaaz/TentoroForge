/**
 * The assistant step (`agent_step`) as the workflow engine registers it, in an app WITH assistants. Forge runtime — do
 * not remove.
 *
 * Installed by `install_agent_runtime` as src/lib/workflows/agent-step.ts, over the stub that workflows/agent-step.ts
 * ships to every app. All it does is point the engine at the real handler in src/lib/agents/workflow-step.ts, so the
 * workflow folder itself never imports the assistant runtime in an app that has none.
 */
export { registerAgentStepAction } from "@/lib/agents/workflow-step";

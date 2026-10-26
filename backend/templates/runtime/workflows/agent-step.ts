/**
 * The assistant step (`agent_step`) as this app's workflow engine registers it. Forge runtime — do not remove.
 *
 * THIS COPY IS THE ONE FOR AN APP WITHOUT ASSISTANTS. It exists so the engine can always import `./agent-step`: the
 * real handler needs the assistant runtime (src/lib/agents), and an app that has none must still compile. A workflow
 * that nevertheless contains an assistant step fails at that step, in words, instead of being skipped.
 *
 * When the project has assistants, `install_agent_runtime` (services/agent_runtime_install.py) OVERWRITES this file
 * with templates/runtime/agents/agent-step-hook.ts, which hands over to src/lib/agents/workflow-step.ts. Re-injecting
 * the runtime puts this stub back and the install puts the hook back again, in that order, every time.
 */
import { registerActionHandler } from "./engine";

export function registerAgentStepAction(): void {
  registerActionHandler("agent_step", async () => {
    throw new Error(
      "This workflow has an assistant step, but this app has no assistants installed. Build the assistant the step names and apply it, then run the workflow again.",
    );
  });
}

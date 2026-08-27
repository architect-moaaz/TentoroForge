/**
 * Runtime action execution.
 *
 * Handles IR action definitions at runtime in the editor context.
 */

import type { ActionDef, RendererContext } from "./types";

export function executeAction(
  action: ActionDef | undefined,
  ctx: RendererContext,
): void {
  if (!action) return;

  switch (action.type) {
    case "navigate":
      console.log(`[IR Renderer] Navigate to: ${action.to}`);
      break;

    case "setState":
      ctx.setState(action.path, action.value);
      break;

    case "mutate":
      if (action.confirm) {
        console.log(`[IR Renderer] Mutate ${action.source} (confirm: ${action.confirm})`);
      } else {
        console.log(`[IR Renderer] Mutate ${action.source}`);
      }
      break;

    case "openModal":
      ctx.toggleModal(action.modal);
      break;

    case "closeModal":
      ctx.toggleModal(action.modal);
      break;

    case "toast":
      console.log(`[IR Renderer] Toast: ${action.message}`);
      break;

    case "invalidate":
      console.log(`[IR Renderer] Invalidate: ${action.sources.join(", ")}`);
      break;

    case "sequence":
      for (const step of action.steps) {
        executeAction(step, ctx);
      }
      break;

    case "custom":
      console.log("[IR Renderer] Custom action (skipped for safety)");
      break;
  }
}

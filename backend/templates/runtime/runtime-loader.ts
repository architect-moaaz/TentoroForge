/**
 * Runtime loader — initializes workflows + rules at app startup.
 *
 * Generated apps should call `initializeRuntime()` once when the API
 * server starts (e.g., in a singleton module imported by API routes).
 */

import { loadWorkflows, registerDefaultActions } from "./workflows";
import { loadRules } from "./rules";

let initialized = false;

export interface RuntimeOptions {
  /** Path to workflows directory (default: process.cwd()/workflows) */
  workflowsDir?: string;
  /** Path to rules directory (default: process.cwd()/rules) */
  rulesDir?: string;
  /** Skip default action handler registration */
  skipDefaultActions?: boolean;
}

/**
 * Initialize the runtime: load workflows and rules from disk,
 * register default action handlers.
 *
 * Idempotent — safe to call multiple times.
 */
export async function initializeRuntime(
  options: RuntimeOptions = {},
): Promise<void> {
  if (initialized) return;

  // Load workflows from /workflows/*.json
  await loadWorkflows(options.workflowsDir);

  // Load rules from /rules/*.json
  await loadRules(options.rulesDir);

  // Register default action handlers (incl. real Claude-backed AI handlers)
  if (!options.skipDefaultActions) {
    registerDefaultActions();
  }

  // Wire ai_extract's file loader to the storage backend so it can read an
  // uploaded file (e.g. a CV PDF) by id. Best-effort — never blocks init.
  try {
    const { registerFileStorage } = await import("./storage");
    registerFileStorage();
  } catch (err) {
    console.warn("[runtime] file storage not wired:", err);
  }

  initialized = true;
}

/**
 * Reset the initialized flag (for testing).
 */
export function resetRuntime(): void {
  initialized = false;
}

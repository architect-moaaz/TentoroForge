/**
 * An assistant made for a workflow step is not one a person talks to. Forge runtime — do not remove.
 *
 * The platform marks it `workflow_only: true` in the agent definition; the compiled config may spell it
 * `workflowOnly`. Either is read here, and only a real `true` counts: anything else (absent, "yes", 1) is a normal
 * assistant, so every chat that existed before this flag behaves exactly as it did.
 *
 * The chat route leaves such an assistant out of its list and answers 404 for it (as for an id that does not exist),
 * and the widget only ever mounts what that list returns, so nothing on a page can open it.
 */
export function isWorkflowOnly(config: { workflowOnly?: unknown; workflow_only?: unknown } | null | undefined): boolean {
  return config?.workflowOnly === true || config?.workflow_only === true;
}

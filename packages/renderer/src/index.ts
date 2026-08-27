export { SchemaRenderer } from "./SchemaRenderer";
export { renderNode } from "./runtime/dispatch";
export type { DispatchContext } from "./runtime/dispatch";
export { interpolate, interpolateDeep } from "./runtime/interpolate";
// Breadcrumb ancestor hrefs arrive parameterised (`/conferences/[id]`) because
// that is the route-tree contract KEY. Only the request knows the concrete id,
// so the host resolves them server-side before render.
export { resolveCrumbHrefs } from "./runtime/crumbHrefs";
export { evalExpression } from "./runtime/bindings";
// Form interaction engine (spec item 5, S1a) — the field-interaction contract
// types + pure formula evaluator. Exported so the library's reactive Form
// controller (S1b) imports the SAME evaluator + ordering the generator/editor use.
export {
  evaluateComputed,
  computedEvalOrder,
  extractFormulaVars,
  evaluatePredicate,
  computeFieldConditionalStates,
  INTERACTION_FUNCTIONS,
} from "./runtime/formInteraction";
export type {
  FieldInteraction,
  ComputedInteraction,
  DynamicOptions,
  OnChangeInteraction,
  FieldConditionalState,
} from "./runtime/formInteraction";
// Slice 5 — imperative compute action for buttons (`onClick: {compute}`).
export {
  runComputeAction,
  bindComputeAction,
} from "./runtime/computeAction";
export type {
  ComputeAction,
  ComputeActionEnvelope,
} from "./runtime/computeAction";
export type { SchemaRendererProps, DataEngine } from "./SchemaRenderer";
export { compileTokens, tokenToCssVar, resolveStyle } from "./runtime/tokens";
export { applyLayout } from "./runtime/layouts";
export { validatePage } from "./runtime/validate";
export { renderToObject } from "./test-harness/renderToObject";
// Primitive components for library composition (referenced in Task 21):
export { Box } from "./nodes/primitive";
export { Text } from "./nodes/primitive";
export { Image } from "./nodes/primitive";
// Client bundle — WorkflowDispatcher context + ClientIsland boundary:
export {
  WorkflowDispatcherProvider,
  WorkflowDispatcherContext,
  createWorkflowDispatch,
  type WorkflowDispatch,
  type WorkflowDispatchOptions,
} from "./client/WorkflowDispatcher";
export { ClientIsland } from "./client/ClientIsland";
// Shell composition — PageOutletContext lets the scaffold wrap a shell schema
// around per-page content without duplicating the nav in every page schema.
export { PageOutletContext } from "./runtime/page-outlet-context";
// Dialog state — open/close map for schema Dialog nodes. Provided by the
// engine, consumed by the library's Dialog component.
export {
  DialogStateContext,
  DialogStateProvider,
  useDialogState,
} from "./client/DialogState";
export type { DialogState } from "./client/DialogState";

// Navigator — the single navigation seam (Button navigate, Table rowHref, Link,
// post-submit redirect). A host supplies a router-backed Navigator to get soft
// nav + routed modals; default is window.location so nothing regresses.
export {
  NavigatorContext,
  NavigatorProvider,
  useNavigator,
} from "./client/Navigator";
export type { Navigator } from "./client/Navigator";

// Shell state — mobile sidebar drawer open/close + delegated click handling.
// Provided by the engine root, consumed by the page-shell heuristic's
// `data-shell-sidebar` / `data-sidebar-backdrop` / `data-sidebar-toggle`
// markers via CSS selectors on `[data-sidebar-open="true"]`.
export {
  ShellStateContext,
  ShellStateProvider,
  useShellState,
} from "./client/ShellState";
export type { ShellState } from "./client/ShellState";

// Spec E Wave 1 — advanced interactions runtime primitives.
export {
  mutationQueue,
  submitMutation,
  useMutationQueue,
} from "./runtime/mutation-queue";
export type {
  Mutation,
  MutationStatus,
} from "./runtime/mutation-queue";
export {
  undoStack,
  useUndoStack,
  applyLastUndo,
} from "./runtime/undo-manager";
export type { UndoStackEntry } from "./runtime/undo-manager";
export {
  subscribePresence,
  usePresence,
} from "./runtime/presence-client";
export type { PresenceUser } from "./runtime/presence-client";

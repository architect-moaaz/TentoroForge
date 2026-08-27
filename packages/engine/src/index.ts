// Public API of @tentoroforge/engine.

export { Engine } from "./Engine";
export { EngineProvider, DesignSpecContext } from "./EngineProvider";
export type { EngineProviderProps } from "./EngineProvider";

export { NavFlowContext, useNavFlow } from "./nav/NavFlowContext";
export { useNavigate } from "./nav/useNavigate";

export type {
  PageSchema, SchemaNode, DataSource, DesignSpec, EngineProps, DataContext,
} from "./types";

export { interpolateString, interpolateDeep } from "./data/interpolate";
export { evalExpression } from "./data/expressions";
export { fetchDataSources } from "./data/loader";

export { useViewport, pickResponsiveValue } from "./responsive/useViewport";
export type { Breakpoint } from "./responsive/useViewport";
export { useEngineViewport, ViewportContext } from "./Engine";

// DialogStateContext now lives in @tentoroforge/renderer so the library
// (which depends on renderer) can consume it without a library→engine
// dependency cycle. Re-export here for convenience so engine consumers
// can keep `import { DialogStateProvider } from "@tentoroforge/engine"`.
export {
  DialogStateContext,
  DialogStateProvider,
  useDialogState,
} from "@tentoroforge/renderer";
export type { DialogState } from "@tentoroforge/renderer";

// Navigator — re-exported so generated apps can `import { NavigatorProvider }
// from "@tentoroforge/engine"` alongside the other providers.
export {
  NavigatorContext,
  NavigatorProvider,
  useNavigator,
} from "@tentoroforge/renderer";
export type { Navigator } from "@tentoroforge/renderer";

export const ENGINE_VERSION = "0.1.0";

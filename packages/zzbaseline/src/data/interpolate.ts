// Re-export the renderer's implementation so the public engine API is
// self-contained without consumers depending on @tentoroforge/renderer.
//
// Note: the renderer's function is named `interpolate` (not `interpolateString`).
// We also expose it as `interpolateString` for the engine's public API so
// callers have a descriptive name that signals "string input required".
export { interpolate as interpolateString, interpolateDeep } from "@tentoroforge/renderer";

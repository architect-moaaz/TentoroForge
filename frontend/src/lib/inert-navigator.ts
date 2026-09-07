import type { Navigator } from "@tentoroforge/renderer";

/**
 * The Navigator the editor canvas mounts.
 *
 * The canvas renders LIVE library components, and schema-driven navigation is
 * one of the things they do. With no NavigatorProvider mounted, useNavigator()
 * fell back to the window.location-backed defaultNavigator
 * (packages/renderer/src/client/Navigator.tsx), so a schema node could drive
 * the editor's own browser tab:
 *
 *   • `Redirect` calls nav.replace(to) in a MOUNT effect and its registry
 *     default is `to: "/"` — dragging it out of the palette hard-navigated the
 *     whole editor SPA to "/" the instant it rendered. Autosave is a 500 ms
 *     debounce (frontend/src/lib/persistence.ts), so the drop that caused it —
 *     and every edit inside that window — was lost.
 *   • Clicking a Button/Link/Table row on the canvas to SELECT it also fired
 *     that component's own navigate handler, for the same reason.
 *
 * The canvas is a design surface: a schema node is content to be arranged, not
 * behaviour to execute. Every navigation is made inert so those components
 * render as the placeholders they are. Deliberately NOT a router-backed
 * navigator — a soft navigation would still lose the user's place.
 */
export const INERT_NAVIGATOR: Navigator = {
  push: () => {},
  replace: () => {},
  back: () => {},
  refresh: () => {},
};

/**
 * @tentoroforge/library a11y — Spec E Wave 2 accessibility primitives.
 *
 * Cross-cutting infrastructure that the shell, workflow dispatchers,
 * and every mutation call into. Not gated per-component; every
 * generated app boots with these primitives active.
 */
export {
  announce,
  subscribe,
  __resetAnnouncerForTests,
} from "./announcer";
export type { LiveUrgency } from "./announcer";
export { LiveRegion } from "./LiveRegion";
export type { LiveRegionProps } from "./LiveRegion";

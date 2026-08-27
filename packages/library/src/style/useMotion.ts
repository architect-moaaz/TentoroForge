// packages/library/src/style/useMotion.ts
import type { MotionT } from "@tentoroforge/schema";

/**
 * Returns props to spread onto the wrapper element. v1 emits a
 * `data-motion` attribute that the runtime stylesheet animates with
 * @keyframes, plus inline `transition` for the duration.
 */
export function useMotion(motion?: MotionT): { "data-motion"?: string } {
  if (!motion || motion === "none") return {};
  return { "data-motion": motion };
}

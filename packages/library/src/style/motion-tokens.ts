import type { Motion } from "../theme/token-types";

/**
 * Motion-level → animation envelope mapping. Components reading the
 * motionLevel token consult this to pick durations, easings, and
 * stagger gaps.
 */
export const MOTION_ENVELOPE: Record<Motion, {
  duration: number;          // ms
  ease: string;
  staggerGap: number;        // ms — for Stagger
  enabled: boolean;
}> = {
  none: {
    duration: 0,
    ease: "linear",
    staggerGap: 0,
    enabled: false,
  },
  subtle: {
    duration: 200,
    ease: "cubic-bezier(0.4, 0, 0.2, 1)",
    staggerGap: 30,
    enabled: true,
  },
  expressive: {
    duration: 400,
    ease: "cubic-bezier(0.34, 1.56, 0.64, 1)",   // overshoot for playful tier
    staggerGap: 80,
    enabled: true,
  },
};

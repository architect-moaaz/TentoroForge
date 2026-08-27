// ── Sprite Animation Timing Utilities ───────────────────────────────────────

import type { Direction } from "../types";

/**
 * Idle animation: 2-frame cycle, 800ms per frame (gentle bob).
 */
export function getIdleFrame(timestamp: number): number {
  return Math.floor((timestamp / 800) % 2);
}

/**
 * Walk animation: 4-frame cycle, 150ms per frame.
 */
export function getWalkFrame(timestamp: number): number {
  return Math.floor((timestamp / 150) % 4);
}

/**
 * Work animation: 4-frame cycle, 300ms per frame.
 */
export function getWorkFrame(timestamp: number): number {
  return Math.floor((timestamp / 300) % 4);
}

/**
 * Returns a Y-pixel offset for the idle bob (sine wave, +/-2px).
 */
export function getBobOffset(timestamp: number): number {
  return Math.sin((timestamp / 800) * Math.PI * 2) * 2;
}

/**
 * Determine facing direction from a movement delta.
 * Prefers horizontal direction when both dx and dy are nonzero.
 */
export function getDirectionFromMovement(dx: number, dy: number): Direction {
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx >= 0 ? "right" : "left";
  }
  return dy >= 0 ? "down" : "up";
}

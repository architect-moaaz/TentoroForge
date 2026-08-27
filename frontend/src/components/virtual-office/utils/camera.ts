// ── Camera Pan / Zoom Utilities ─────────────────────────────────────────────

import type { Camera, OfficeLayout, AgentCharacterState, Position } from "../types";

const LERP_SPEED = 5; // per-second interpolation factor
const MIN_ZOOM = 0.3;
const MAX_ZOOM = 6;

/**
 * Create a camera centred on the office layout.
 */
export function createCamera(layout: OfficeLayout): Camera {
  const cx = (layout.width * layout.tileSize) / 2;
  const cy = (layout.height * layout.tileSize) / 2;
  return {
    x: cx,
    y: cy,
    zoom: 1,
    targetX: cx,
    targetY: cy,
    targetZoom: 1,
  };
}

/**
 * Compute a zoom level that fits the entire office within the given canvas dimensions.
 */
export function fitZoom(layout: OfficeLayout, canvasW: number, canvasH: number): number {
  const worldW = layout.width * layout.tileSize;
  const worldH = layout.height * layout.tileSize;
  const padding = 0.9; // 90% of available space
  const zoom = Math.min(canvasW / worldW, canvasH / worldH) * padding;
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
}

/**
 * Smoothly interpolate camera position/zoom toward target values.
 * @param dt delta time in seconds
 */
export function updateCamera(camera: Camera, dt: number): Camera {
  const t = 1 - Math.exp(-LERP_SPEED * dt); // exponential ease
  return {
    ...camera,
    x: camera.x + (camera.targetX - camera.x) * t,
    y: camera.y + (camera.targetY - camera.y) * t,
    zoom: camera.zoom + (camera.targetZoom - camera.zoom) * t,
  };
}

/**
 * Set the camera target so it centres on the given agent within the canvas.
 */
export function followAgent(
  camera: Camera,
  agent: AgentCharacterState,
  canvasW: number,
  canvasH: number,
): Camera {
  // We don't need canvasW/canvasH for the target position because the
  // renderer already offsets by half-canvas. The camera (x,y) IS the
  // world-space point that appears at screen centre.
  void canvasW;
  void canvasH;
  return {
    ...camera,
    targetX: agent.position.x,
    targetY: agent.position.y,
    following: agent.id,
  };
}

/**
 * Convert screen coordinates to world coordinates.
 */
export function screenToWorld(
  camera: Camera,
  sx: number,
  sy: number,
): Position {
  return {
    x: (sx - camera.x) / camera.zoom + camera.x,
    y: (sy - camera.y) / camera.zoom + camera.y,
  };
}

/**
 * Convert world coordinates to screen coordinates.
 */
export function worldToScreen(
  camera: Camera,
  wx: number,
  wy: number,
): Position {
  return {
    x: (wx - camera.x) * camera.zoom + camera.x,
    y: (wy - camera.y) * camera.zoom + camera.y,
  };
}

/**
 * Zoom toward the mouse position in integer steps, clamped to [1, 6].
 * @param delta scroll delta (positive = zoom in, negative = zoom out)
 * @param sx screen-space mouse X
 * @param sy screen-space mouse Y
 */
export function zoomAt(
  camera: Camera,
  delta: number,
  sx: number,
  sy: number,
): Camera {
  const step = delta > 0 ? 1 : -1;
  const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(camera.targetZoom) + step));

  if (newZoom === camera.targetZoom) return camera;

  // Adjust target position so the world point under the mouse stays fixed
  const worldBefore = screenToWorld(camera, sx, sy);
  const scale = newZoom / camera.targetZoom;

  return {
    ...camera,
    targetZoom: newZoom,
    targetX: sx - (worldBefore.x - camera.targetX) * scale,
    targetY: sy - (worldBefore.y - camera.targetY) * scale,
  };
}

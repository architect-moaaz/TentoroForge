/**
 * What the geofence keeps about a person, and for how long.
 *
 *   FORGE_GEOFENCE_RETENTION_DAYS   how long crossings (and the state of a person outside every zone) are kept. Default 90.
 *                                   0 keeps them for ever (say so deliberately). Anything unreadable falls back to 90.
 *   FORGE_GEOFENCE_COORD_DECIMALS   how exactly a crossing's position is stored: 6 is about 10 cm (default), 3 about 100 m,
 *                                   2 about 1 km. A crossing needs only "which zone, when": the exact spot is not needed to
 *                                   act on it, and a smaller number keeps less about where someone was.
 *
 * Pure: no clock, no database. The store applies these (`purgeOld`, `eraseEntity`, and `recordEvents`).
 * Forge runtime — do not remove.
 */
export const DEFAULT_RETENTION_DAYS = 90;
export const PURGE_EVERY_MS = 60 * 60 * 1000;

export function retentionDays(env: NodeJS.ProcessEnv = process.env): number {
  const raw = env.FORGE_GEOFENCE_RETENTION_DAYS;
  if (raw == null || String(raw).trim() === "") return DEFAULT_RETENTION_DAYS;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return DEFAULT_RETENTION_DAYS;
  return Math.min(Math.floor(n), 3650);
}

/** Crossings older than this (ms since 1970) are deleted; null = keep everything. */
export function cutoffMs(now: number, days: number): number | null {
  return days > 0 ? now - days * 86_400_000 : null;
}

export function coordDecimals(env: NodeJS.ProcessEnv = process.env): number {
  const raw = env.FORGE_GEOFENCE_COORD_DECIMALS;
  if (raw == null || String(raw).trim() === "") return 6;
  const n = Number(raw);
  if (!Number.isInteger(n)) return 6;
  return Math.min(Math.max(n, 2), 7);
}

export function coarsen(v: number, decimals: number): number {
  const f = 10 ** decimals;
  return Math.round(v * f) / f;
}

/** Cleaning up is cheap but not free: once an hour per process is plenty. */
export function purgeDue(lastAt: number, now: number, everyMs = PURGE_EVERY_MS): boolean {
  return now - lastAt >= everyMs;
}

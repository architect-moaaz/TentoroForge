// ── BFS Grid Pathfinding ────────────────────────────────────────────────────

import type { OfficeLayout, Position } from "./types";

let cachedGrid: boolean[][] | null = null;

/**
 * Build a 2D boolean grid where `true` means the tile is walkable.
 * Walkable tiles = room interiors + corridor path tiles.
 * The grid is cached after the first call.
 */
export function buildWalkableGrid(layout: OfficeLayout): boolean[][] {
  if (cachedGrid) return cachedGrid;

  const grid: boolean[][] = [];
  for (let y = 0; y < layout.height; y++) {
    grid[y] = new Array<boolean>(layout.width).fill(false);
  }

  // Mark room interiors as walkable
  for (const room of layout.rooms) {
    for (let dy = 0; dy < room.h; dy++) {
      for (let dx = 0; dx < room.w; dx++) {
        const gx = room.x + dx;
        const gy = room.y + dy;
        if (gx >= 0 && gx < layout.width && gy >= 0 && gy < layout.height) {
          grid[gy][gx] = true;
        }
      }
    }
  }

  // Mark corridor / path tiles as walkable
  for (const p of layout.paths) {
    if (p.x >= 0 && p.x < layout.width && p.y >= 0 && p.y < layout.height) {
      grid[p.y][p.x] = true;
    }
  }

  cachedGrid = grid;
  return grid;
}

/**
 * Clear the cached grid (useful if the layout changes at runtime).
 */
export function clearGridCache(): void {
  cachedGrid = null;
}

// Cardinal directions for neighbor expansion
const DIRS: Position[] = [
  { x: 0, y: -1 },
  { x: 0, y: 1 },
  { x: -1, y: 0 },
  { x: 1, y: 0 },
];

/**
 * BFS shortest-path on the walkable grid.
 * Returns an array of positions from `from` to `to` (inclusive of both ends).
 * Returns an empty array if no path exists.
 */
export function findPath(
  grid: boolean[][],
  from: Position,
  to: Position,
): Position[] {
  const height = grid.length;
  if (height === 0) return [];
  const width = grid[0].length;

  // Clamp to grid bounds
  const sx = Math.round(from.x);
  const sy = Math.round(from.y);
  const ex = Math.round(to.x);
  const ey = Math.round(to.y);

  if (
    sx < 0 || sx >= width || sy < 0 || sy >= height ||
    ex < 0 || ex >= width || ey < 0 || ey >= height
  ) {
    return [];
  }

  // Quick check: start or end not walkable
  if (!grid[sy][sx] || !grid[ey][ex]) return [];

  // Trivial case
  if (sx === ex && sy === ey) return [{ x: sx, y: sy }];

  // BFS
  const visited: boolean[][] = [];
  for (let y = 0; y < height; y++) {
    visited[y] = new Array<boolean>(width).fill(false);
  }

  // Parent map for path reconstruction: encode position as y * width + x
  const parent = new Map<number, number>();
  const encode = (x: number, y: number) => y * width + x;

  const queue: Position[] = [{ x: sx, y: sy }];
  visited[sy][sx] = true;
  let found = false;

  while (queue.length > 0) {
    const cur = queue.shift()!;

    for (const d of DIRS) {
      const nx = cur.x + d.x;
      const ny = cur.y + d.y;

      if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
      if (!grid[ny][nx] || visited[ny][nx]) continue;

      visited[ny][nx] = true;
      parent.set(encode(nx, ny), encode(cur.x, cur.y));
      queue.push({ x: nx, y: ny });

      if (nx === ex && ny === ey) {
        found = true;
        break;
      }
    }
    if (found) break;
  }

  if (!found) return [];

  // Reconstruct path
  const path: Position[] = [];
  let cx = ex;
  let cy = ey;
  while (cx !== sx || cy !== sy) {
    path.push({ x: cx, y: cy });
    const p = parent.get(encode(cx, cy))!;
    cx = p % width;
    cy = Math.floor(p / width);
  }
  path.push({ x: sx, y: sy });
  path.reverse();

  return path;
}

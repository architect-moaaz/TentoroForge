// ── Static Office Layout Definition ─────────────────────────────────────────
//
// 3x3 grid of rooms, each ~8x6 tiles, with corridors connecting them.
// Total grid: 28 wide x 22 tall. Tile size: 48px.
//
// The floor is laid out the way §28's DAG runs, so work moves in one
// direction instead of ping-ponging across the office:
//
//  Row 0:  Discovery (0,0) | Architecture (1,0) | Design Studio (2,0)
//  Row 1:  Data      (0,1) | Composition  (1,1) | Logic         (2,1)
//  Row 2:  Security   (0,2) | Verification (1,2) | Shipping     (2,2)
//  Row 3:                    | Huddle Room  (1,3) |
//
// Discovery feeds Architecture, which forks into Data (down the left wall)
// and Design Studio → Composition (down the right). Security sits under Data
// because permissions guard entities, and everything converges on
// Verification before Shipping.

import type { OfficeLayout, Room, Position, DeskPosition, FurniturePlacement } from "./types";
import { AGENT_REGISTRY, DEPARTMENT_BY_ID } from "./types";

// ── Helpers ────────────────────────────────────────────────────────────────

/** Return agents assigned to a given room id. */
function agentsInRoom(roomId: string) {
  return AGENT_REGISTRY.filter((a) => a.room === roomId);
}

/** Generate desk positions inside a room for its assigned agents. */
function desksForRoom(
  roomX: number,
  roomY: number,
  roomId: string,
): DeskPosition[] {
  const agents = agentsInRoom(roomId);
  const desks: DeskPosition[] = [];
  // Two columns, and every other row. Characters are drawn at 1.5 tiles, so
  // desks one row apart put the person behind on top of the person in front —
  // which is exactly what a full department looked like before.
  const cols = [2, 5];
  const startRow = 1;
  const rowStep = 2;
  agents.forEach((agent, i) => {
    const col = cols[i % cols.length];
    const row = startRow + Math.floor(i / cols.length) * rowStep;
    desks.push({
      x: roomX + col,
      y: roomY + row,
      agentId: agent.id,
      facing: col === 2 ? "right" : "left",
    });
  });
  return desks;
}

// ── Room geometry ──────────────────────────────────────────────────────────

// Each room is 8 wide x 6 tall.
// Corridors are 2 tiles wide between rooms.
// Column x-offsets: 0, 10, 20   (room width 8 + corridor 2)
// Row y-offsets:    0,  8, 16   (room height 6 + corridor 2)

const ROOM_W = 8;
const ROOM_H = 6;
const GAP = 2; // corridor width

function roomOrigin(col: number, row: number): { x: number; y: number } {
  return {
    x: col * (ROOM_W + GAP),
    y: row * (ROOM_H + GAP),
  };
}

// ── Room definitions ───────────────────────────────────────────────────────

// Label, colour and description come from DEPARTMENTS in types.ts — the same
// list the backend seats agents against — so a room can't drift from the
// department it is drawing.
function makeRoom(
  id: string,
  col: number,
  row: number,
  floorTile: string,
  furniture: FurniturePlacement[],
): Room {
  const o = roomOrigin(col, row);
  const dept = DEPARTMENT_BY_ID[id];
  if (!dept) throw new Error(`office layout: no department declared for room "${id}"`);
  return {
    id,
    label: dept.label,
    x: o.x,
    y: o.y,
    w: ROOM_W,
    h: ROOM_H,
    floorTile,
    color: dept.color,
    description: dept.description,
    furniture,
    desks: desksForRoom(o.x, o.y, id),
  };
}

// The department pill is drawn at each room's top centre, so nothing sits at
// x=3 or x=4 on the top wall — furniture there covers the name of the room.
const rooms: Room[] = [
  // Row 0 — what the application is, and how it is shaped
  makeRoom("discovery", 0, 0, "floor_wood", [
    { type: "whiteboard", x: 1, y: 0 },
    { type: "whiteboard", x: 6, y: 0 },
    { type: "plant", x: 0, y: 0 },
    { type: "plant", x: 7, y: 0 },
    { type: "coffee_machine", x: 7, y: 5 },
    { type: "bookshelf", x: 0, y: 5 },
  ]),
  makeRoom("architecture", 1, 0, "floor_tile", [
    { type: "whiteboard", x: 1, y: 0 },
    { type: "whiteboard", x: 6, y: 0 },
    { type: "cork_board", x: 0, y: 0 },
    { type: "plant", x: 7, y: 0 },
    { type: "monitor_large", x: 7, y: 5 },
    { type: "plant", x: 0, y: 5 },
  ]),
  makeRoom("design_studio", 2, 0, "floor_tile", [
    { type: "monitor_large", x: 1, y: 0 },
    { type: "monitor_large", x: 6, y: 0 },
    { type: "bookshelf", x: 0, y: 0 },
    { type: "plant", x: 7, y: 0 },
    { type: "plant", x: 7, y: 5 },
    { type: "whiteboard", x: 0, y: 5 },
  ]),

  // Row 1 — the two branches that build it
  makeRoom("data", 0, 1, "floor_wood", [
    { type: "server_rack", x: 7, y: 0 },
    { type: "server_rack", x: 7, y: 1 },
    { type: "whiteboard", x: 1, y: 0 },
    { type: "monitor_large", x: 6, y: 0 },
    { type: "filing_cabinet", x: 0, y: 0 },
    { type: "coffee_machine", x: 0, y: 5 },
  ]),
  makeRoom("composition", 1, 1, "floor_tile", [
    { type: "monitor_large", x: 1, y: 0 },
    { type: "monitor_large", x: 6, y: 0 },
    { type: "whiteboard", x: 0, y: 0 },
    { type: "plant", x: 7, y: 0 },
    { type: "plant", x: 0, y: 5 },
    { type: "coffee_machine", x: 7, y: 5 },
  ]),
  makeRoom("logic", 2, 1, "floor_wood", [
    { type: "whiteboard", x: 1, y: 0 },
    { type: "whiteboard", x: 6, y: 0 },
    { type: "bookshelf", x: 7, y: 0 },
    { type: "plant", x: 0, y: 0 },
    { type: "coffee_machine", x: 0, y: 5 },
    { type: "monitor_large", x: 7, y: 5 },
  ]),

  // Row 2 — what guards it, what checks it, what ships it
  makeRoom("security", 0, 2, "floor_dark", [
    { type: "server_rack", x: 6, y: 0 },
    { type: "server_rack", x: 7, y: 0 },
    { type: "server_rack", x: 7, y: 1 },
    { type: "monitor_large", x: 0, y: 0 },
    { type: "filing_cabinet", x: 0, y: 5 },
    { type: "plant", x: 6, y: 5 },
  ]),
  makeRoom("qa", 1, 2, "floor_tile", [
    { type: "test_bench", x: 0, y: 0 },
    { type: "test_bench", x: 0, y: 1 },
    { type: "monitor_large", x: 1, y: 0 },
    { type: "monitor_large", x: 6, y: 0 },
    { type: "bookshelf", x: 7, y: 0 },
    { type: "plant", x: 7, y: 5 },
  ]),
  makeRoom("shipping", 2, 2, "floor_dark", [
    { type: "conveyor", x: 2, y: 5 },
    { type: "conveyor", x: 3, y: 5 },
    { type: "crate", x: 5, y: 5 },
    { type: "crate", x: 6, y: 5 },
    { type: "crate", x: 7, y: 5 },
    { type: "monitor_large", x: 0, y: 0 },
    { type: "plant", x: 7, y: 0 },
  ]),

  // Row 3 — where the agents a question touches meet; under Verification,
  // whose observer chairs. The table is in the middle; seats ring it.
  makeRoom("huddle", 1, 3, "floor_wood", [
    { type: "meeting_table", x: 2, y: 2 },
    { type: "meeting_table", x: 3, y: 2 },
    { type: "meeting_table", x: 4, y: 2 },
    { type: "meeting_table", x: 5, y: 2 },
    { type: "meeting_table", x: 2, y: 3 },
    { type: "meeting_table", x: 3, y: 3 },
    { type: "meeting_table", x: 4, y: 3 },
    { type: "meeting_table", x: 5, y: 3 },
    { type: "whiteboard", x: 1, y: 0 },
    { type: "whiteboard", x: 6, y: 0 },
    { type: "plant", x: 0, y: 5 },
    { type: "plant", x: 7, y: 5 },
  ]),
];

// ── Corridor / walkable path tiles ─────────────────────────────────────────

function buildPaths(): Position[] {
  const paths: Position[] = [];

  // Horizontal corridors (between column pairs, spanning the gap)
  for (let row = 0; row < 3; row++) {
    const cy = row * (ROOM_H + GAP) + Math.floor(ROOM_H / 2); // centre-ish of room row
    // corridor between col 0-1
    for (let x = ROOM_W; x < ROOM_W + GAP; x++) {
      paths.push({ x, y: cy });
      paths.push({ x, y: cy - 1 });
    }
    // corridor between col 1-2
    const x2Start = (ROOM_W + GAP) + ROOM_W;
    for (let x = x2Start; x < x2Start + GAP; x++) {
      paths.push({ x, y: cy });
      paths.push({ x, y: cy - 1 });
    }
  }

  // The Huddle Room hangs under Verification: one corridor down to it.
  {
    const hr = rooms.find((r) => r.id === "huddle");
    if (hr) {
      const cx = hr.x + Math.floor(hr.w / 2);
      for (let y = hr.y - GAP; y < hr.y; y++) {
        paths.push({ x: cx, y });
        paths.push({ x: cx - 1, y });
      }
    }
  }

  // Vertical corridors (between row pairs, spanning the gap)
  for (let col = 0; col < 3; col++) {
    const cx = col * (ROOM_W + GAP) + Math.floor(ROOM_W / 2); // centre-ish of room col
    // corridor between row 0-1
    for (let y = ROOM_H; y < ROOM_H + GAP; y++) {
      paths.push({ x: cx, y });
      paths.push({ x: cx - 1, y });
    }
    // corridor between row 1-2
    const y2Start = (ROOM_H + GAP) + ROOM_H;
    for (let y = y2Start; y < y2Start + GAP; y++) {
      paths.push({ x: cx, y });
      paths.push({ x: cx - 1, y });
    }
  }

  // Also include room-interior doorway tiles so agents can enter/leave
  // (the first/last tiles of each room edge near a corridor)
  for (const room of rooms) {
    const midX = room.x + Math.floor(room.w / 2);
    const midY = room.y + Math.floor(room.h / 2);
    // doorway tiles on each edge
    // right edge
    paths.push({ x: room.x + room.w - 1, y: midY });
    paths.push({ x: room.x + room.w - 1, y: midY - 1 });
    // left edge
    paths.push({ x: room.x, y: midY });
    paths.push({ x: room.x, y: midY - 1 });
    // bottom edge
    paths.push({ x: midX, y: room.y + room.h - 1 });
    paths.push({ x: midX - 1, y: room.y + room.h - 1 });
    // top edge
    paths.push({ x: midX, y: room.y });
    paths.push({ x: midX - 1, y: room.y });
  }

  return paths;
}

// ── Lobby position (centre of the grid) ────────────────────────────────────

const GRID_W = 3 * ROOM_W + 2 * GAP; // 28
// Three rows of departments and the Huddle Room under them.
const GRID_H = 4 * ROOM_H + 3 * GAP; // 30

const lobby: Position = {
  x: Math.floor(GRID_W / 2),
  y: Math.floor((3 * ROOM_H + 2 * GAP) / 2),
};

// ── The Huddle Room's seats ────────────────────────────────────────────────

/** Where each person sits at the table: the chair at the head, the others
 *  along the two sides, in the order they arrive. */
export function huddleSeats(): { chair: Position; seats: Position[] } {
  const r = rooms.find((x) => x.id === "huddle")!;
  return {
    chair: { x: r.x + 1, y: r.y + 3 },
    seats: [
      { x: r.x + 3, y: r.y + 1 }, { x: r.x + 3, y: r.y + 4 },
      { x: r.x + 5, y: r.y + 1 }, { x: r.x + 5, y: r.y + 4 },
      { x: r.x + 6, y: r.y + 3 }, { x: r.x + 4, y: r.y + 1 },
    ],
  };
}

// ── Export ──────────────────────────────────────────────────────────────────

export const OFFICE_LAYOUT: OfficeLayout = {
  width: GRID_W,
  height: GRID_H,
  tileSize: 48,
  rooms,
  paths: buildPaths(),
  lobby,
};

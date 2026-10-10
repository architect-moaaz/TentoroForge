// ── Static Office Layout Definition ─────────────────────────────────────────
//
// 3x4 grid of rooms, each 8x6 tiles, with corridors connecting them, and the
// Huddle Room under the middle column. Tile size: 48px.
//
// The floor is laid out the way the platform works, so work moves in one
// direction instead of ping-ponging across the office:
//
//  Row 0:  Front Desk  (0,0) | Discovery    (1,0) | Architecture (2,0)
//  Row 1:  Design Studio(0,1)| Data         (1,1) | Logic        (2,1)
//  Row 2:  Composition (0,2) | Security     (1,2) | Verification (2,2)
//  Row 3:  Engine Room (0,3) | Workbench    (1,3) | Shipping     (2,3)
//  Row 4:                    | Huddle Room  (1,4) |
//
// The person comes in at the Front Desk, where Smith sits. Discovery writes
// what the app is for; Architecture (the Solution Architect and the
// Engineer) shapes it and decides the facts; the Design Studio, Data and
// Logic write it; Composition lays out and codes the screens, Security
// guards them, Verification judges every step and writes what must happen.
// The Engine Room holds the machines the app runs on; the Workbench is where
// it is served and tried; Shipping builds and deploys it.

import type { OfficeLayout, Room, Position, DeskPosition, FurniturePlacement, MachinePlacement } from "./types";
import { AGENT_REGISTRY, DEPARTMENT_BY_ID, ENGINES } from "./types";

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
// Row y-offsets:    0,  8, 16, 24   (room height 6 + corridor 2)

const ROOM_W = 8;
const ROOM_H = 6;
const GAP = 2; // corridor width
const COLS = 3;
/** Rows of departments; the Huddle Room hangs under them. */
const ROWS = 4;

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
  machines: MachinePlacement[] = [],
): Room {
  const o = roomOrigin(col, row);
  const dept = DEPARTMENT_BY_ID[id];
  if (!dept) throw new Error(`office layout: no department declared for room "${id}"`);
  for (const m of machines) {
    if (!ENGINES.some((e) => e.id === m.engine && e.room === id)) {
      throw new Error(`office layout: engine "${m.engine}" is not declared for room "${id}"`);
    }
  }
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
    machines,
    desks: desksForRoom(o.x, o.y, id),
  };
}

// The department pill is drawn at each room's top centre, so nothing sits at
// x=3 or x=4 on the top wall — furniture there covers the name of the room.
const rooms: Room[] = [
  // Row 0 — the door, what the application is, and how it is shaped
  makeRoom("front_desk", 0, 0, "floor_wood", [
    // The counter the person comes to; the board a platform fault is pinned on.
    { type: "meeting_table", x: 4, y: 4 },
    { type: "meeting_table", x: 5, y: 4 },
    { type: "cork_board", x: 6, y: 0 },
    { type: "plant", x: 0, y: 0 },
    { type: "plant", x: 7, y: 5 },
    { type: "coffee_machine", x: 7, y: 0 },
    { type: "bookshelf", x: 0, y: 5 },
  ]),
  makeRoom("discovery", 1, 0, "floor_wood", [
    { type: "whiteboard", x: 1, y: 0 },
    { type: "whiteboard", x: 6, y: 0 },
    { type: "plant", x: 0, y: 0 },
    { type: "plant", x: 7, y: 0 },
    { type: "coffee_machine", x: 7, y: 5 },
    { type: "bookshelf", x: 0, y: 5 },
  ]),
  makeRoom("architecture", 2, 0, "floor_tile", [
    { type: "whiteboard", x: 1, y: 0 },
    { type: "whiteboard", x: 6, y: 0 },
    { type: "cork_board", x: 0, y: 0 },
    { type: "plant", x: 7, y: 0 },
    { type: "monitor_large", x: 7, y: 5 },
    { type: "plant", x: 0, y: 5 },
  ]),

  // Row 1 — the writers
  makeRoom("design_studio", 0, 1, "floor_tile", [
    { type: "monitor_large", x: 1, y: 0 },
    { type: "monitor_large", x: 6, y: 0 },
    { type: "bookshelf", x: 0, y: 0 },
    { type: "plant", x: 7, y: 0 },
    { type: "plant", x: 7, y: 5 },
    { type: "whiteboard", x: 0, y: 5 },
  ]),
  makeRoom("data", 1, 1, "floor_wood", [
    { type: "server_rack", x: 7, y: 0 },
    { type: "server_rack", x: 7, y: 1 },
    { type: "whiteboard", x: 1, y: 0 },
    { type: "monitor_large", x: 6, y: 0 },
    { type: "filing_cabinet", x: 0, y: 0 },
    { type: "coffee_machine", x: 0, y: 5 },
  ]),
  makeRoom("logic", 2, 1, "floor_wood", [
    { type: "whiteboard", x: 1, y: 0 },
    { type: "whiteboard", x: 6, y: 0 },
    { type: "bookshelf", x: 7, y: 0 },
    { type: "plant", x: 0, y: 0 },
    { type: "coffee_machine", x: 0, y: 5 },
    { type: "monitor_large", x: 7, y: 5 },
  ]),

  // Row 2 — the screens, what guards them, what judges and states
  makeRoom("composition", 0, 2, "floor_tile", [
    { type: "monitor_large", x: 1, y: 0 },
    { type: "monitor_large", x: 6, y: 0 },
    { type: "whiteboard", x: 0, y: 0 },
    { type: "plant", x: 7, y: 0 },
    { type: "plant", x: 0, y: 5 },
    { type: "coffee_machine", x: 7, y: 5 },
  ]),
  makeRoom("security", 1, 2, "floor_dark", [
    { type: "server_rack", x: 6, y: 0 },
    { type: "server_rack", x: 7, y: 0 },
    { type: "server_rack", x: 7, y: 1 },
    { type: "monitor_large", x: 0, y: 0 },
    { type: "filing_cabinet", x: 0, y: 5 },
    { type: "plant", x: 6, y: 5 },
  ]),
  makeRoom("qa", 2, 2, "floor_tile", [
    { type: "test_bench", x: 0, y: 0 },
    { type: "test_bench", x: 0, y: 1 },
    { type: "monitor_large", x: 1, y: 0 },
    { type: "monitor_large", x: 6, y: 0 },
    { type: "bookshelf", x: 7, y: 0 },
    { type: "plant", x: 7, y: 5 },
  ]),

  // Row 3 — the machines, the bench, the dock
  makeRoom("engine_room", 0, 3, "floor_dark", [
    { type: "monitor_large", x: 0, y: 0 },
    { type: "plant", x: 7, y: 5 },
  ], [
    { engine: "data_engine", x: 1, y: 1 },
    { engine: "workflow_engine", x: 3, y: 1 },
    { engine: "ui_engine", x: 5, y: 1 },
    { engine: "composer", x: 2, y: 4 },
    { engine: "scaffold", x: 5, y: 4 },
  ]),
  makeRoom("workbench", 1, 3, "floor_dark", [
    { type: "test_bench", x: 0, y: 1 },
    { type: "test_bench", x: 0, y: 2 },
    { type: "monitor_large", x: 1, y: 0 },
    { type: "monitor_large", x: 6, y: 0 },
    { type: "plant", x: 7, y: 5 },
  ], [
    { engine: "workbench", x: 3, y: 2 },
    { engine: "apps_db", x: 6, y: 2 },
  ]),
  makeRoom("shipping", 2, 3, "floor_dark", [
    { type: "conveyor", x: 2, y: 5 },
    { type: "conveyor", x: 3, y: 5 },
    { type: "crate", x: 5, y: 5 },
    { type: "crate", x: 6, y: 5 },
    { type: "crate", x: 7, y: 5 },
    { type: "monitor_large", x: 0, y: 0 },
    { type: "plant", x: 7, y: 0 },
  ]),

  // Row 4 — where the agents a question touches meet; under the Workbench,
  // whose observer chairs. The table is in the middle; seats ring it.
  makeRoom("huddle", 1, 4, "floor_wood", [
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
  for (let row = 0; row < ROWS; row++) {
    const cy = row * (ROOM_H + GAP) + Math.floor(ROOM_H / 2); // centre-ish of room row
    for (let col = 0; col < COLS - 1; col++) {
      const xStart = col * (ROOM_W + GAP) + ROOM_W;
      for (let x = xStart; x < xStart + GAP; x++) {
        paths.push({ x, y: cy });
        paths.push({ x, y: cy - 1 });
      }
    }
  }

  // The Huddle Room hangs under the Workbench: one corridor down to it.
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
  for (let col = 0; col < COLS; col++) {
    const cx = col * (ROOM_W + GAP) + Math.floor(ROOM_W / 2); // centre-ish of room col
    for (let row = 0; row < ROWS - 1; row++) {
      const yStart = row * (ROOM_H + GAP) + ROOM_H;
      for (let y = yStart; y < yStart + GAP; y++) {
        paths.push({ x: cx, y });
        paths.push({ x: cx - 1, y });
      }
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

const GRID_W = COLS * ROOM_W + (COLS - 1) * GAP; // 28
// Four rows of departments and the Huddle Room under them.
const GRID_H = (ROWS + 1) * ROOM_H + ROWS * GAP; // 38

const lobby: Position = {
  x: Math.floor(GRID_W / 2),
  y: Math.floor((ROWS * ROOM_H + (ROWS - 1) * GAP) / 2),
};

// ── Named spots ────────────────────────────────────────────────────────────

function room(id: string): Room {
  const r = rooms.find((x) => x.id === id);
  if (!r) throw new Error(`office layout: no room "${id}"`);
  return r;
}

/** Where each person sits at the Huddle table: the chair at the head, the
 *  others along the two sides, in the order they arrive. */
export function huddleSeats(): { chair: Position; seats: Position[] } {
  const r = room("huddle");
  return {
    chair: { x: r.x + 1, y: r.y + 3 },
    seats: [
      { x: r.x + 3, y: r.y + 1 }, { x: r.x + 3, y: r.y + 4 },
      { x: r.x + 5, y: r.y + 1 }, { x: r.x + 5, y: r.y + 4 },
      { x: r.x + 6, y: r.y + 3 }, { x: r.x + 4, y: r.y + 1 },
    ],
  };
}

/** Where Smith stands to try something: beside the Workbench. */
export function benchSpot(): Position {
  const r = room("workbench");
  return { x: r.x + 2, y: r.y + 4 };
}

/** Where Smith stands to talk to the person: the Front Desk counter. */
export function visitorSpot(): Position {
  const r = room("front_desk");
  return { x: r.x + 4, y: r.y + 3 };
}

/** Where a platform fault is pinned: the Front Desk's cork board. */
export function boardSpot(): Position {
  const r = room("front_desk");
  return { x: r.x + 6, y: r.y + 1 };
}

/** The centre of a room, for the camera. */
export function roomCenter(id: string): Position {
  const r = room(id);
  return { x: r.x + r.w / 2, y: r.y + r.h / 2 };
}

/** An engine's machine on the floor: its tile rectangle (machines stand two
 *  tiles tall; the bench two wide as well), or null when it has none. */
export function machineRect(engineId: string): { x: number; y: number; w: number; h: number } | null {
  for (const r of rooms) {
    const m = r.machines.find((x) => x.engine === engineId);
    if (m) {
      const wide = engineId === "workbench";
      return { x: r.x + m.x, y: r.y + m.y, w: wide ? 2 : 1, h: 2 };
    }
  }
  return null;
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

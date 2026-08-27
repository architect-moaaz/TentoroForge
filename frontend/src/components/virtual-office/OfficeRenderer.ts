// ── Canvas 2D Office Renderer ───────────────────────────────────────────────

import { OFFICE_LAYOUT } from "./layout";
import { getSprite } from "./SpriteLoader";
import {
  createCamera,
  updateCamera,
  followAgent,
  worldToScreen,
  fitZoom,
} from "./utils/camera";
import {
  getIdleFrame,
  getWalkFrame,
  getWorkFrame,
  getBobOffset,
} from "./utils/animation";
import { useOfficeStore, type OfficeStore } from "./OfficeStateManager";
import type { Camera, AgentCharacterState, Position, Room } from "./types";
import { AGENT_REGISTRY } from "./types";

// ── Constants ───────────────────────────────────────────────────────────────

const SPEECH_BUBBLE_DURATION = 5000; // ms before fade
const SPEECH_BUBBLE_FADE = 1000; // ms to fade out
const SPEECH_MAX_WIDTH = 150;
const SPEECH_FONT = "11px sans-serif";
const SPEECH_PADDING = 6;
const SPEECH_RADIUS = 4;
const SPEECH_POINTER_SIZE = 5;

const CHARACTER_SCALE = 1.5; // tiles

// ── Confetti particle ────────────────────────────────────────────────────────

interface Confetti {
  x: number;
  y: number;
  vx: number;
  vy: number;
  color: string;
  size: number;
  rotation: number;
  rotationSpeed: number;
  life: number;
  maxLife: number;
}

const CONFETTI_COLORS = [
  "#FF6B6B", "#FFD93D", "#6BCB77", "#4D96FF",
  "#FF8C94", "#C9B1FF", "#FF6F91", "#67E8F9",
  "#FDE68A", "#A7F3D0", "#DDD6FE", "#FBBF24",
];

// ── Renderer ────────────────────────────────────────────────────────────────

export class OfficeRenderer {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private animationId: number | null = null;
  private lastTimestamp = 0;
  private camera: Camera;
  private speechTimestamps: Map<string, number> = new Map();
  private confetti: Confetti[] = [];
  private confettiSpawned = false;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Failed to get 2D context");
    this.ctx = ctx;
    this.ctx.imageSmoothingEnabled = false;
    this.camera = createCamera(OFFICE_LAYOUT);
  }

  // ── Lifecycle ───────────────────────────────────────────────────────────

  start(): void {
    if (this.animationId !== null) return;
    // Set initial zoom to fit the entire office
    const zoom = fitZoom(OFFICE_LAYOUT, this.canvas.width, this.canvas.height);
    this.camera.zoom = zoom;
    this.camera.targetZoom = zoom;
    this.lastTimestamp = performance.now();
    this.animationId = requestAnimationFrame((ts) => this.loop(ts));
  }

  stop(): void {
    if (this.animationId !== null) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
  }

  private loop(timestamp: number): void {
    const dt = Math.min(timestamp - this.lastTimestamp, 50); // cap at 50ms
    this.lastTimestamp = timestamp;

    this.update(dt, timestamp);
    this.render(timestamp);

    this.animationId = requestAnimationFrame((ts) => this.loop(ts));
  }

  private update(dt: number, timestamp: number): void {
    const store = useOfficeStore.getState();

    // Tick all agents (convert dt from ms to seconds for physics)
    store.tick(dt / 1000, timestamp);

    // Update camera – follow selected agent if any
    if (store.selectedAgent) {
      const agent = store.agents.get(store.selectedAgent);
      if (agent) {
        const state = agent.getState();
        const tileSize = OFFICE_LAYOUT.tileSize;
        const agentScreenState = {
          ...state,
          position: { x: state.position.x * tileSize, y: state.position.y * tileSize },
        };
        this.camera = followAgent(this.camera, agentScreenState, this.canvas.width, this.canvas.height);
      }
    }

    this.camera = updateCamera(this.camera, dt / 1000);
  }

  private render(timestamp: number): void {
    const { ctx, canvas } = this;
    const store = useOfficeStore.getState();

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();

    // Apply camera transform
    ctx.translate(
      canvas.width / 2 - this.camera.x * this.camera.zoom,
      canvas.height / 2 - this.camera.y * this.camera.zoom,
    );
    ctx.scale(this.camera.zoom, this.camera.zoom);

    // Render layers back-to-front
    this.drawFloors();
    this.drawPaths();
    this.drawActiveRoomHighlights(timestamp, store);
    this.drawWalls();
    this.drawFurniture();
    this.drawCharacters(timestamp, store);
    this.drawRoomLabels(store);
    this.drawSpeechBubbles(timestamp, store);
    this.drawEffects(timestamp, store);
    this.updateAndDrawConfetti(store);

    ctx.restore();
  }

  // ── Floor tiles ─────────────────────────────────────────────────────────

  private drawFloors(): void {
    const { ctx } = this;
    const ts = OFFICE_LAYOUT.tileSize;

    for (const room of OFFICE_LAYOUT.rooms) {
      const rx = room.x * ts;
      const ry = room.y * ts;
      const rw = room.w * ts;
      const rh = room.h * ts;

      // Light floor base
      ctx.fillStyle = "#f1f5f9";
      ctx.fillRect(rx, ry, rw, rh);

      // Room-colored carpet overlay
      ctx.fillStyle = this.colorWithAlpha(room.color, 0.12);
      ctx.fillRect(rx, ry, rw, rh);

      // Checkerboard tile pattern for carpet texture
      for (let gx = room.x; gx < room.x + room.w; gx++) {
        for (let gy = room.y; gy < room.y + room.h; gy++) {
          if ((gx + gy) % 2 === 0) {
            ctx.fillStyle = this.colorWithAlpha(room.color, 0.06);
            ctx.fillRect(gx * ts, gy * ts, ts, ts);
          }
        }
      }

      // Grid lines between tiles
      ctx.strokeStyle = this.colorWithAlpha(room.color, 0.12);
      ctx.lineWidth = 0.5;
      for (let gx = room.x; gx <= room.x + room.w; gx++) {
        ctx.beginPath();
        ctx.moveTo(gx * ts, ry);
        ctx.lineTo(gx * ts, ry + rh);
        ctx.stroke();
      }
      for (let gy = room.y; gy <= room.y + room.h; gy++) {
        ctx.beginPath();
        ctx.moveTo(rx, gy * ts);
        ctx.lineTo(rx + rw, gy * ts);
        ctx.stroke();
      }
    }
  }

  // ── Corridor / path tiles ─────────────────────────────────────────────

  private drawPaths(): void {
    const { ctx } = this;
    const ts = OFFICE_LAYOUT.tileSize;

    for (const p of OFFICE_LAYOUT.paths) {
      // Light corridor floor
      ctx.fillStyle = "#e2e8f0";
      ctx.fillRect(p.x * ts, p.y * ts, ts, ts);
      // Subtle path markers
      ctx.fillStyle = "rgba(100, 116, 139, 0.1)";
      ctx.fillRect(p.x * ts + 2, p.y * ts + 2, ts - 4, ts - 4);
    }
  }

  // ── Walls ─────────────────────────────────────────────────────────────

  private drawWalls(): void {
    const { ctx } = this;
    const ts = OFFICE_LAYOUT.tileSize;

    for (const room of OFFICE_LAYOUT.rooms) {
      // Outer glow
      ctx.strokeStyle = this.colorWithAlpha(room.color, 0.3);
      ctx.lineWidth = 4;
      ctx.strokeRect(room.x * ts, room.y * ts, room.w * ts, room.h * ts);
      // Inner wall line
      ctx.strokeStyle = this.colorWithAlpha(room.color, 0.8);
      ctx.lineWidth = 2;
      ctx.strokeRect(room.x * ts, room.y * ts, room.w * ts, room.h * ts);
    }
  }

  // ── Active room highlights ──────────────────────────────────────────

  private drawActiveRoomHighlights(timestamp: number, store: OfficeStore): void {
    const { ctx } = this;
    const ts = OFFICE_LAYOUT.tileSize;

    // Find rooms that have active (working/reading) agents
    const activeRoomIds = new Set<string>();
    for (const agentId of store.activeAgents) {
      const agent = store.agents.get(agentId);
      if (!agent) continue;
      const state = agent.getState();
      if (state.state === "working" || state.state === "reading") {
        // Find which room this agent belongs to
        const info = AGENT_REGISTRY.find((a) => a.id === agentId);
        if (info) activeRoomIds.add(info.room);
      }
    }

    for (const room of OFFICE_LAYOUT.rooms) {
      if (!activeRoomIds.has(room.id)) continue;

      const rx = room.x * ts;
      const ry = room.y * ts;
      const rw = room.w * ts;
      const rh = room.h * ts;

      // Pulsing glow overlay
      const pulse = 0.06 + Math.sin(timestamp * 0.003) * 0.03;
      ctx.fillStyle = this.colorWithAlpha(room.color, pulse);
      ctx.fillRect(rx, ry, rw, rh);

      // Animated border glow
      const borderAlpha = 0.5 + Math.sin(timestamp * 0.004) * 0.2;
      ctx.save();
      ctx.shadowColor = room.color;
      ctx.shadowBlur = 12;
      ctx.strokeStyle = this.colorWithAlpha(room.color, borderAlpha);
      ctx.lineWidth = 3;
      ctx.strokeRect(rx + 1, ry + 1, rw - 2, rh - 2);
      ctx.restore();
    }
  }

  // ── Room labels ───────────────────────────────────────────────────────

  private drawRoomLabels(store: OfficeStore): void {
    if (!store.showLabels) return;

    const { ctx } = this;
    const ts = OFFICE_LAYOUT.tileSize;

    for (const room of OFFICE_LAYOUT.rooms) {
      const cx = (room.x + room.w / 2) * ts;
      // Position label just inside the top of the room
      const top = room.y * ts + 6;

      const text = room.label;
      ctx.font = "bold 13px 'Inter', 'Segoe UI', sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";

      const metrics = ctx.measureText(text);
      const pw = metrics.width + 16;
      const ph = 20;
      const pillX = cx - pw / 2;
      const pillY = top;

      // Shadow
      ctx.save();
      ctx.shadowColor = "rgba(0,0,0,0.25)";
      ctx.shadowBlur = 6;
      ctx.shadowOffsetY = 2;

      // Background pill with room color
      ctx.fillStyle = this.colorWithAlpha(room.color, 0.9);
      this.roundRect(pillX, pillY, pw, ph, 5);
      ctx.fill();

      ctx.restore();

      // White border
      ctx.strokeStyle = "rgba(255,255,255,0.6)";
      ctx.lineWidth = 1;
      this.roundRect(pillX, pillY, pw, ph, 5);
      ctx.stroke();

      // Text
      ctx.fillStyle = "#ffffff";
      ctx.fillText(text, cx, pillY + 3);
    }
  }

  // ── Furniture ─────────────────────────────────────────────────────────

  private drawFurniture(): void {
    const { ctx } = this;
    const ts = OFFICE_LAYOUT.tileSize;

    for (const room of OFFICE_LAYOUT.rooms) {
      for (const furn of room.furniture) {
        const sprite = getSprite(`furniture_${furn.type}`);
        // Furniture coords are local to room — add room origin
        const px = (room.x + furn.x) * ts;
        const py = (room.y + furn.y) * ts;

        if (sprite) {
          ctx.drawImage(sprite, px, py, ts, ts);
        } else {
          // Fallback: draw themed furniture icons
          this.drawFurnitureIcon(furn.type, px, py, ts, room.color);
        }
      }
    }
  }

  // ── Characters ────────────────────────────────────────────────────────

  /** Draw a themed fallback icon for each furniture type. */
  private drawFurnitureIcon(type: string, px: number, py: number, ts: number, roomColor: string): void {
    const { ctx } = this;
    const m = 4; // margin
    const x = px + m;
    const y = py + m;
    const w = ts - m * 2;
    const h = ts - m * 2;

    ctx.save();

    switch (type) {
      case "whiteboard": {
        // White rectangle with border and lines
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(x, y, w, h);
        ctx.strokeStyle = "#94a3b8";
        ctx.lineWidth = 2;
        ctx.strokeRect(x, y, w, h);
        // Drawn lines on the whiteboard
        ctx.strokeStyle = roomColor;
        ctx.lineWidth = 1.5;
        for (let i = 1; i <= 3; i++) {
          const ly = y + (h * i) / 4;
          ctx.beginPath();
          ctx.moveTo(x + 4, ly);
          ctx.lineTo(x + w - 4, ly);
          ctx.stroke();
        }
        // Small marker
        ctx.fillStyle = "#ef4444";
        ctx.fillRect(x + w - 8, y + h - 6, 6, 4);
        break;
      }
      case "plant": {
        // Pot
        ctx.fillStyle = "#a16207";
        const potW = w * 0.5;
        const potH = h * 0.3;
        ctx.fillRect(x + (w - potW) / 2, y + h - potH, potW, potH);
        // Foliage — layered circles
        ctx.fillStyle = "#22c55e";
        ctx.beginPath();
        ctx.arc(x + w / 2, y + h * 0.4, w * 0.35, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#16a34a";
        ctx.beginPath();
        ctx.arc(x + w / 2 - 4, y + h * 0.35, w * 0.22, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.arc(x + w / 2 + 5, y + h * 0.32, w * 0.2, 0, Math.PI * 2);
        ctx.fill();
        break;
      }
      case "bookshelf": {
        // Shelf frame
        ctx.fillStyle = "#78350f";
        ctx.fillRect(x, y, w, h);
        // Shelves (3 rows)
        const shelfH = h / 3;
        for (let i = 0; i < 3; i++) {
          const sy = y + i * shelfH;
          // Books of varying colors
          const bookColors = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899"];
          const bookW = w / 5;
          for (let b = 0; b < 5; b++) {
            ctx.fillStyle = bookColors[(i * 5 + b) % bookColors.length];
            const bh = shelfH * (0.6 + Math.random() * 0.3);
            ctx.fillRect(x + b * bookW + 1, sy + shelfH - bh, bookW - 2, bh);
          }
          // Shelf line
          ctx.fillStyle = "#92400e";
          ctx.fillRect(x, sy + shelfH - 2, w, 2);
        }
        break;
      }
      case "server_rack": {
        // Rack body
        ctx.fillStyle = "#1e293b";
        ctx.fillRect(x, y, w, h);
        ctx.strokeStyle = "#334155";
        ctx.lineWidth = 1;
        ctx.strokeRect(x, y, w, h);
        // Blinking LEDs
        const ledColors = ["#22c55e", "#3b82f6", "#f59e0b", "#22c55e"];
        for (let i = 0; i < 4; i++) {
          const ly = y + 6 + i * (h / 5);
          // Unit panel
          ctx.fillStyle = "#0f172a";
          ctx.fillRect(x + 3, ly, w - 6, h / 6);
          // LED dot
          ctx.fillStyle = ledColors[i];
          ctx.beginPath();
          ctx.arc(x + w - 8, ly + h / 12, 2.5, 0, Math.PI * 2);
          ctx.fill();
        }
        break;
      }
      case "monitor_large": {
        // Screen
        ctx.fillStyle = "#0f172a";
        const screenH = h * 0.65;
        ctx.fillRect(x, y, w, screenH);
        // Screen content glow
        ctx.fillStyle = roomColor;
        ctx.globalAlpha = 0.3;
        ctx.fillRect(x + 3, y + 3, w - 6, screenH - 6);
        ctx.globalAlpha = 1;
        // Code lines on screen
        ctx.fillStyle = "#22c55e";
        for (let i = 0; i < 4; i++) {
          const lw = w * (0.4 + Math.random() * 0.4);
          ctx.fillRect(x + 5, y + 6 + i * 6, lw, 2);
        }
        // Stand
        ctx.fillStyle = "#64748b";
        ctx.fillRect(x + w / 2 - 3, y + screenH, 6, h * 0.15);
        // Base
        ctx.fillRect(x + w * 0.2, y + screenH + h * 0.15, w * 0.6, 3);
        break;
      }
      case "coffee_machine": {
        // Machine body
        ctx.fillStyle = "#78716c";
        ctx.fillRect(x + w * 0.15, y, w * 0.7, h * 0.7);
        ctx.strokeStyle = "#57534e";
        ctx.lineWidth = 1;
        ctx.strokeRect(x + w * 0.15, y, w * 0.7, h * 0.7);
        // Red power light
        ctx.fillStyle = "#ef4444";
        ctx.beginPath();
        ctx.arc(x + w * 0.7, y + 6, 3, 0, Math.PI * 2);
        ctx.fill();
        // Cup below
        ctx.fillStyle = "#fafafa";
        ctx.fillRect(x + w * 0.3, y + h * 0.72, w * 0.4, h * 0.25);
        ctx.strokeStyle = "#d4d4d8";
        ctx.strokeRect(x + w * 0.3, y + h * 0.72, w * 0.4, h * 0.25);
        // Coffee inside cup
        ctx.fillStyle = "#92400e";
        ctx.fillRect(x + w * 0.32, y + h * 0.78, w * 0.36, h * 0.12);
        break;
      }
      case "conveyor": {
        // Belt
        ctx.fillStyle = "#64748b";
        ctx.fillRect(x, y + h * 0.3, w, h * 0.4);
        // Rollers
        ctx.fillStyle = "#94a3b8";
        for (let i = 0; i < 4; i++) {
          ctx.beginPath();
          ctx.arc(x + (w * (i + 0.5)) / 4, y + h * 0.5, 4, 0, Math.PI * 2);
          ctx.fill();
        }
        // Arrow direction
        ctx.fillStyle = "#f59e0b";
        ctx.beginPath();
        ctx.moveTo(x + w - 6, y + h * 0.5);
        ctx.lineTo(x + w - 14, y + h * 0.35);
        ctx.lineTo(x + w - 14, y + h * 0.65);
        ctx.closePath();
        ctx.fill();
        break;
      }
      case "crate": {
        // Wooden crate
        ctx.fillStyle = "#d97706";
        ctx.fillRect(x, y + h * 0.15, w, h * 0.85);
        ctx.strokeStyle = "#92400e";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x, y + h * 0.15, w, h * 0.85);
        // Cross planks
        ctx.beginPath();
        ctx.moveTo(x, y + h * 0.15);
        ctx.lineTo(x + w, y + h);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(x + w, y + h * 0.15);
        ctx.lineTo(x, y + h);
        ctx.stroke();
        break;
      }
      default: {
        // Generic colored rectangle
        ctx.fillStyle = this.colorWithAlpha(roomColor, 0.25);
        ctx.fillRect(x, y, w, h);
        ctx.strokeStyle = this.colorWithAlpha(roomColor, 0.5);
        ctx.lineWidth = 1;
        ctx.strokeRect(x, y, w, h);
      }
    }

    ctx.restore();
  }

  private drawCharacters(timestamp: number, store: OfficeStore): void {
    const { ctx } = this;
    const ts = OFFICE_LAYOUT.tileSize;
    const charSize = ts * CHARACTER_SCALE;

    // Collect agent states and sort by Y for depth ordering
    const agentStates: { state: AgentCharacterState; info: (typeof AGENT_REGISTRY)[0] | undefined }[] = [];
    for (const [, agent] of store.agents) {
      const state = agent.getState();
      const info = AGENT_REGISTRY.find((a) => a.id === state.id);
      agentStates.push({ state, info });
    }
    agentStates.sort((a, b) => a.state.position.y - b.state.position.y);

    for (const { state, info } of agentStates) {
      const px = state.position.x * ts;
      const py = state.position.y * ts;

      // Determine sprite key based on visual state
      let spriteKey = `characters_idle_${state.spriteKey}`;
      let bobY = 0;
      let bobX = 0;

      switch (state.state) {
        case "idle":
        case "waiting":
          spriteKey = `characters_idle_${state.spriteKey}`;
          bobY = getBobOffset(timestamp) * 0.5;
          break;
        case "walking":
        case "handoff":
          spriteKey = `characters_idle_${state.spriteKey}`;
          bobY = getBobOffset(timestamp) * 2;
          break;
        case "working":
        case "reading":
          spriteKey = `characters_working_${state.spriteKey}`;
          break;
        case "celebrating":
          spriteKey = `characters_idle_${state.spriteKey}`;
          // Dance: big bounce + lateral sway
          bobY = Math.abs(Math.sin(timestamp * 0.008)) * -6;
          bobX = Math.sin(timestamp * 0.006 + state.position.x * 3) * 4;
          break;
        case "error":
          spriteKey = `characters_idle_${state.spriteKey}`;
          // Slight shake effect
          bobY = Math.sin(timestamp * 0.02) * 1.5;
          break;
        case "protesting":
          spriteKey = `characters_walk_${state.spriteKey}`;
          // Angry march — fast lateral shake + vertical bounce
          bobY = Math.abs(Math.sin(timestamp * 0.008)) * -4;
          break;
      }

      // Draw active glow/highlight for working/reading agents
      if (
        state.state === "working" ||
        state.state === "reading" ||
        state.state === "celebrating"
      ) {
        const glowColor = info?.color ?? "#3B82F6";
        ctx.fillStyle = this.colorWithAlpha(glowColor, 0.15);
        ctx.beginPath();
        ctx.ellipse(
          px + ts / 2,
          py + ts * 0.8,
          charSize * 0.4,
          charSize * 0.15,
          0,
          0,
          Math.PI * 2,
        );
        ctx.fill();
      }

      // Protesting: red angry glow + exclamation marks
      if (state.state === "protesting") {
        // Pulsing red glow
        const pulseAlpha = 0.15 + Math.sin(timestamp * 0.005) * 0.1;
        ctx.fillStyle = `rgba(239, 68, 68, ${pulseAlpha})`;
        ctx.beginPath();
        ctx.ellipse(
          px + ts / 2,
          py + ts * 0.8,
          charSize * 0.5,
          charSize * 0.2,
          0,
          0,
          Math.PI * 2,
        );
        ctx.fill();

        // Floating angry symbols above head
        const symbolOffset = Math.sin(timestamp * 0.004 + (state.position.x * 7)) * 3;
        ctx.font = "bold 14px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.fillStyle = "#ef4444";
        ctx.fillText(
          "!!",
          px + ts / 2,
          py - 6 + symbolOffset,
        );
      }

      // Selected highlight
      if (store.selectedAgent === state.id) {
        ctx.strokeStyle = "#FFD700";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.ellipse(
          px + ts / 2,
          py + ts * 0.8,
          charSize * 0.45,
          charSize * 0.18,
          0,
          0,
          Math.PI * 2,
        );
        ctx.stroke();
      }

      // Hovered highlight
      if (store.hoveredAgent === state.id) {
        ctx.strokeStyle = "rgba(30, 41, 59, 0.4)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.ellipse(
          px + ts / 2,
          py + ts * 0.8,
          charSize * 0.42,
          charSize * 0.16,
          0,
          0,
          Math.PI * 2,
        );
        ctx.stroke();
      }

      // Draw sprite
      const sprite = getSprite(spriteKey);
      const drawX = px + ts / 2 - charSize / 2 + bobX;
      const drawY = py + ts / 2 - charSize / 2 + bobY;

      if (sprite) {
        ctx.drawImage(sprite, drawX, drawY, charSize, charSize);
      } else {
        // Fallback: draw a colored circle with initial
        const color = info?.color ?? "#888";
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(px + ts / 2 + bobX, py + ts / 2 + bobY, ts * 0.35, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#fff";
        ctx.font = "bold 9px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(
          (state.name?.[0] ?? "?").toUpperCase(),
          px + ts / 2 + bobX,
          py + ts / 2 + bobY,
        );
      }

      // Draw agent name below (if labels on)
      if (store.showLabels) {
        ctx.font = "8px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = "rgba(30, 41, 59, 0.8)";
        ctx.fillText(state.name, px + ts / 2, py + ts + 2);
      }
    }
  }

  // ── Speech bubbles ────────────────────────────────────────────────────

  private drawSpeechBubbles(timestamp: number, store: OfficeStore): void {
    const { ctx } = this;
    const ts = OFFICE_LAYOUT.tileSize;

    for (const [, agent] of store.agents) {
      const state = agent.getState();
      if (!state.speechBubble) continue;

      const agentId = state.id;

      // Track when speech bubble appeared
      if (!this.speechTimestamps.has(agentId)) {
        this.speechTimestamps.set(agentId, timestamp);
      }

      const elapsed = timestamp - this.speechTimestamps.get(agentId)!;

      // Fade out after duration
      let alpha = 1;
      if (elapsed > SPEECH_BUBBLE_DURATION) {
        alpha = 1 - (elapsed - SPEECH_BUBBLE_DURATION) / SPEECH_BUBBLE_FADE;
        if (alpha <= 0) {
          this.speechTimestamps.delete(agentId);
          continue;
        }
      }

      ctx.save();
      ctx.globalAlpha = alpha;

      const px = state.position.x * ts + ts / 2;
      const py = state.position.y * ts - 8;

      // Measure and wrap text
      ctx.font = SPEECH_FONT;
      const lines = this.wrapText(state.speechBubble, SPEECH_MAX_WIDTH);
      const lineHeight = 14;
      const bubbleW = Math.min(
        SPEECH_MAX_WIDTH,
        Math.max(...lines.map((l) => ctx.measureText(l).width)) +
          SPEECH_PADDING * 2,
      );
      const bubbleH = lines.length * lineHeight + SPEECH_PADDING * 2;

      const bx = px - bubbleW / 2;
      const by = py - bubbleH - SPEECH_POINTER_SIZE;

      // Bubble background
      ctx.fillStyle = "#ffffff";
      this.roundRect(bx, by, bubbleW, bubbleH, SPEECH_RADIUS);
      ctx.fill();

      // Border color based on type
      let borderColor = "#d1d5db";
      if (state.speechBubbleType === "error") borderColor = "#ef4444";
      else if (state.speechBubbleType === "success") borderColor = "#22c55e";

      ctx.strokeStyle = borderColor;
      ctx.lineWidth = 1;
      this.roundRect(bx, by, bubbleW, bubbleH, SPEECH_RADIUS);
      ctx.stroke();

      // Pointer triangle
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.moveTo(px - SPEECH_POINTER_SIZE, by + bubbleH);
      ctx.lineTo(px, by + bubbleH + SPEECH_POINTER_SIZE);
      ctx.lineTo(px + SPEECH_POINTER_SIZE, by + bubbleH);
      ctx.closePath();
      ctx.fill();

      ctx.strokeStyle = borderColor;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(px - SPEECH_POINTER_SIZE, by + bubbleH);
      ctx.lineTo(px, by + bubbleH + SPEECH_POINTER_SIZE);
      ctx.lineTo(px + SPEECH_POINTER_SIZE, by + bubbleH);
      ctx.stroke();

      // Text
      ctx.fillStyle =
        state.speechBubbleType === "error" ? "#dc2626" : "#374151";
      ctx.font = SPEECH_FONT;
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      for (let i = 0; i < lines.length; i++) {
        ctx.fillText(
          lines[i],
          bx + SPEECH_PADDING,
          by + SPEECH_PADDING + i * lineHeight,
        );
      }

      ctx.restore();
    }
  }

  // ── Effects (sparkles near working agents) ────────────────────────────

  private drawEffects(timestamp: number, store: OfficeStore): void {
    const { ctx } = this;
    const ts = OFFICE_LAYOUT.tileSize;

    for (const agentId of store.activeAgents) {
      const agent = store.agents.get(agentId);
      if (!agent) continue;
      const state = agent.getState();
      if (state.state !== "working" && state.state !== "reading") continue;

      const px = state.position.x * ts + ts / 2;
      const py = state.position.y * ts;

      // Draw 3 small sparkles orbiting the agent
      const info = AGENT_REGISTRY.find((a) => a.id === agentId);
      const color = info?.color ?? "#FFD700";

      for (let i = 0; i < 3; i++) {
        const angle = (timestamp * 0.002 + (i * Math.PI * 2) / 3) % (Math.PI * 2);
        const radius = ts * 0.6;
        const sx = px + Math.cos(angle) * radius;
        const sy = py + ts * 0.3 + Math.sin(angle) * radius * 0.4;
        const sparkleSize = 2 + Math.sin(timestamp * 0.005 + i) * 1;

        ctx.fillStyle = this.colorWithAlpha(color, 0.6);
        ctx.beginPath();
        ctx.arc(sx, sy, sparkleSize, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  // ── Confetti system ─────────────────────────────────────────────────

  private spawnConfetti(): void {
    const ts = OFFICE_LAYOUT.tileSize;
    const lobby = OFFICE_LAYOUT.lobby;
    const cx = lobby.x * ts + ts / 2;
    const cy = lobby.y * ts + ts / 2;

    for (let i = 0; i < 120; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = 1.5 + Math.random() * 4;
      this.confetti.push({
        x: cx + (Math.random() - 0.5) * ts * 6,
        y: cy - Math.random() * ts * 3,
        vx: Math.cos(angle) * speed,
        vy: -2 - Math.random() * 4,
        color: CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)],
        size: 3 + Math.random() * 4,
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.15,
        life: 0,
        maxLife: 180 + Math.random() * 120, // 3-5 seconds at 60fps
      });
    }
  }

  private updateAndDrawConfetti(store: OfficeStore): void {
    const { ctx } = this;

    // Check if any agent is celebrating — spawn confetti once
    let hasCelebrating = false;
    for (const [, agent] of store.agents) {
      if (agent.getState().state === "celebrating") {
        hasCelebrating = true;
        break;
      }
    }

    if (hasCelebrating && !this.confettiSpawned) {
      this.spawnConfetti();
      this.confettiSpawned = true;
    }
    if (!hasCelebrating) {
      this.confettiSpawned = false;
    }

    // Update and draw confetti
    const alive: Confetti[] = [];
    for (const p of this.confetti) {
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.08; // gravity
      p.vx *= 0.99; // air resistance
      p.rotation += p.rotationSpeed;
      p.life++;

      if (p.life >= p.maxLife) continue;

      const alpha = p.life > p.maxLife - 30
        ? (p.maxLife - p.life) / 30
        : 1;

      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rotation);
      ctx.globalAlpha = alpha;
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
      ctx.restore();

      alive.push(p);
    }
    this.confetti = alive;
  }

  // ── Debug grid ────────────────────────────────────────────────────────

  private drawGrid(): void {
    const { ctx } = this;
    const ts = OFFICE_LAYOUT.tileSize;
    const w = OFFICE_LAYOUT.width;
    const h = OFFICE_LAYOUT.height;

    ctx.strokeStyle = "rgba(100, 116, 139, 0.15)";
    ctx.lineWidth = 0.5;

    for (let x = 0; x <= w; x++) {
      ctx.beginPath();
      ctx.moveTo(x * ts, 0);
      ctx.lineTo(x * ts, h * ts);
      ctx.stroke();
    }
    for (let y = 0; y <= h; y++) {
      ctx.beginPath();
      ctx.moveTo(0, y * ts);
      ctx.lineTo(w * ts, y * ts);
      ctx.stroke();
    }
  }

  // ── Public API ────────────────────────────────────────────────────────

  resize(width: number, height: number): void {
    this.canvas.width = width;
    this.canvas.height = height;
    this.ctx.imageSmoothingEnabled = false;
    // Auto-fit the office into the new canvas size
    const zoom = fitZoom(OFFICE_LAYOUT, width, height);
    this.camera.zoom = zoom;
    this.camera.targetZoom = zoom;
  }

  getCamera(): Camera {
    return this.camera;
  }

  setCameraTarget(x: number, y: number, zoom: number): void {
    this.camera.targetX = x;
    this.camera.targetY = y;
    this.camera.targetZoom = zoom;
    // Clear agent following when user manually pans
    this.camera.following = undefined;
  }

  destroy(): void {
    this.stop();
    this.speechTimestamps.clear();
  }

  // ── Utility helpers ───────────────────────────────────────────────────

  /** Parse a hex/named color and return it with the given alpha. */
  private colorWithAlpha(color: string, alpha: number): string {
    // Handle hex colors
    if (color.startsWith("#")) {
      const r = parseInt(color.slice(1, 3), 16);
      const g = parseInt(color.slice(3, 5), 16);
      const b = parseInt(color.slice(5, 7), 16);
      return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }
    return color;
  }

  /** Draw a rounded rectangle path (does not fill/stroke). */
  private roundRect(
    x: number,
    y: number,
    w: number,
    h: number,
    r: number,
  ): void {
    const { ctx } = this;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  /** Word-wrap text to a max pixel width. */
  private wrapText(text: string, maxWidth: number): string[] {
    const { ctx } = this;
    const words = text.split(" ");
    const lines: string[] = [];
    let currentLine = "";

    for (const word of words) {
      const testLine = currentLine ? `${currentLine} ${word}` : word;
      const testWidth = ctx.measureText(testLine).width;

      if (testWidth > maxWidth && currentLine) {
        lines.push(currentLine);
        currentLine = word;
      } else {
        currentLine = testLine;
      }
    }
    if (currentLine) lines.push(currentLine);

    return lines.length > 0 ? lines : [""];
  }
}

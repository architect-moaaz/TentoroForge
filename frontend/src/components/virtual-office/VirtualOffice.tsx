"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { OfficeEvent } from "./types";
import { useOfficeStore } from "./OfficeStateManager";
import { OfficeRenderer } from "./OfficeRenderer";
import { preloadAll, loadManifest } from "./SpriteLoader";
import { OFFICE_LAYOUT } from "./layout";
import { PipelineProgress } from "./hud/PipelineProgress";
import { PipelineStrip } from "./hud/PipelineStrip";
import { FloorPlanPanel } from "./hud/FloorPlanPanel";
import { EngineTooltip } from "./hud/EngineTooltip";
import { AgentTooltip } from "./hud/AgentTooltip";
import { MiniMap } from "./hud/MiniMap";
import { SpeedControls } from "./hud/SpeedControls";
import { AgentPanel } from "./hud/AgentPanel";
import { Map as MapIcon } from "lucide-react";

/** CSS pixels the pipeline strip and the department bar take at the top. */
const HUD_TOP_PX = 92;

export interface VirtualOfficeProps {
  className?: string;
  onAgentClick?: (agentId: string) => void;
  events?: OfficeEvent[];
  isGenerating?: boolean;
}

export function VirtualOffice({
  className = "",
  onAgentClick,
  events,
  isGenerating,
}: VirtualOfficeProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<OfficeRenderer | null>(null);
  const processedEventsRef = useRef(0);
  const isDraggingRef = useRef(false);
  const lastMouseRef = useRef({ x: 0, y: 0 });
  const [ready, setReady] = useState(false);
  const [showPlan, setShowPlan] = useState(false);

  const initialize = useOfficeStore((s) => s.initialize);
  const handleEvent = useOfficeStore((s) => s.handleEvent);
  const selectAgent = useOfficeStore((s) => s.selectAgent);
  const setHoveredAgent = useOfficeStore((s) => s.setHoveredAgent);
  const setHoveredEngine = useOfficeStore((s) => s.setHoveredEngine);
  const selectedAgent = useOfficeStore((s) => s.selectedAgent);

  // ── Setup / teardown ────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    // Start rendering immediately with fallback graphics
    if (!canvasRef.current) return;

    // Initialize only if not already initialized (store may have been
    // set up by startStreaming in the chat store)
    const store = useOfficeStore.getState();
    if (store.agents.size === 0) {
      initialize();
    }

    // Set initial canvas size from container before starting renderer
    const container = containerRef.current;
    if (container) {
      const { width, height } = container.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvasRef.current.width = width * dpr;
      canvasRef.current.height = height * dpr;
      canvasRef.current.style.width = `${width}px`;
      canvasRef.current.style.height = `${height}px`;
    }

    const renderer = new OfficeRenderer(canvasRef.current);
    rendererRef.current = renderer;
    // The strip and the department bar cover the top of the canvas.
    renderer.setTopInset(HUD_TOP_PX * (window.devicePixelRatio || 1));
    renderer.start();
    setReady(true);

    // Load sprites in the background — renderer will pick them up as they arrive
    loadManifest()
      .then((manifest) => {
        if (cancelled) return;
        return preloadAll(manifest);
      })
      .catch(() => {
        // Sprites not available, fallback rendering continues
      });

    return () => {
      cancelled = true;
      if (rendererRef.current) {
        rendererRef.current.stop();
        rendererRef.current.destroy();
        rendererRef.current = null;
      }
    };
  }, [initialize]);

  // ── Canvas resize ───────────────────────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !rendererRef.current) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (canvasRef.current) {
          canvasRef.current.width = width * window.devicePixelRatio;
          canvasRef.current.height = height * window.devicePixelRatio;
          canvasRef.current.style.width = `${width}px`;
          canvasRef.current.style.height = `${height}px`;
        }
        rendererRef.current?.resize(
          width * window.devicePixelRatio,
          height * window.devicePixelRatio,
        );
      }
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, [ready]);

  // ── Feed SSE events ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!events || !ready) return;
    const newEvents = events.slice(processedEventsRef.current);
    for (const event of newEvents) {
      handleEvent(event);
    }
    processedEventsRef.current = events.length;
  }, [events, ready, handleEvent]);

  // Generation complete is handled by the chat store's SSE handler,
  // so no need to trigger build_success from this component.

  // ── Mouse: wheel zoom ──────────────────────────────────────────────────
  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    const renderer = rendererRef.current;
    if (!renderer) return;
    const camera = renderer.getCamera();
    const delta = e.deltaY > 0 ? -0.15 : 0.15;
    const newZoom = Math.max(0.3, Math.min(6, camera.targetZoom + delta));
    renderer.setCameraTarget(camera.targetX, camera.targetY, newZoom);
  }, []);

  // Bound natively rather than via React's `onWheel`: React registers wheel
  // at the root as a *passive* listener, so preventDefault() there is ignored
  // (logs "Unable to preventDefault inside passive event listener") and the
  // page scrolls while zooming. `passive: false` is only expressible here.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", handleWheel);
  }, [handleWheel]);

  // ── Mouse: drag pan ────────────────────────────────────────────────────
  const dragStartRef = useRef({ x: 0, y: 0 });
  const didDragRef = useRef(false);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    isDraggingRef.current = true;
    didDragRef.current = false;
    lastMouseRef.current = { x: e.clientX, y: e.clientY };
    dragStartRef.current = { x: e.clientX, y: e.clientY };
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    if (isDraggingRef.current) {
      const dx = e.clientX - lastMouseRef.current.x;
      const dy = e.clientY - lastMouseRef.current.y;
      lastMouseRef.current = { x: e.clientX, y: e.clientY };

      // Mark as a real drag if moved more than 3px from start
      const totalDx = e.clientX - dragStartRef.current.x;
      const totalDy = e.clientY - dragStartRef.current.y;
      if (Math.abs(totalDx) > 3 || Math.abs(totalDy) > 3) {
        didDragRef.current = true;
      }

      // Apply drag to camera
      const renderer = rendererRef.current;
      if (renderer) {
        const camera = renderer.getCamera();
        const newX = camera.targetX - dx / camera.zoom;
        const newY = camera.targetY - dy / camera.zoom;
        renderer.setCameraTarget(newX, newY, camera.targetZoom);
      }
      return;
    }

    // Convert screen mouse coords to world coords using camera transform
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    // Mouse position in canvas pixel space
    const canvasX = (e.clientX - rect.left) * dpr;
    const canvasY = (e.clientY - rect.top) * dpr;

    const renderer = rendererRef.current;
    if (!renderer) return;
    const camera = renderer.getCamera();

    // Reverse the camera transform: ctx.translate(cw/2 - cam.x*zoom, ch/2 - cam.y*zoom); ctx.scale(zoom, zoom)
    const cw = canvas.width;
    const ch = canvas.height;
    const worldX = (canvasX - cw / 2 + camera.x * camera.zoom) / camera.zoom;
    const worldY = (canvasY - ch / 2 + camera.y * camera.zoom) / camera.zoom;

    const store = useOfficeStore.getState();
    const agents = store.agents;
    const tileSize = OFFICE_LAYOUT.tileSize;

    // Hit test in world coordinates
    let found: string | null = null;
    for (const [, agentChar] of agents) {
      const agentSt = agentChar.getState();
      const ax = agentSt.position.x * tileSize + tileSize / 2;
      const ay = agentSt.position.y * tileSize + tileSize / 2;
      const dist = Math.sqrt((worldX - ax) ** 2 + (worldY - ay) ** 2);
      if (dist < tileSize * 0.8) {
        found = agentSt.id;
        break;
      }
    }
    setHoveredAgent(found);

    // Then the machines: a cabinet is one tile wide and two tall, the bench two by two.
    let machine: string | null = null;
    if (!found) {
      for (const room of OFFICE_LAYOUT.rooms) {
        for (const m of room.machines) {
          const wide = m.engine === "workbench" ? 2 : 1;
          const mx = (room.x + m.x) * tileSize;
          const my = (room.y + m.y) * tileSize;
          if (worldX >= mx && worldX < mx + wide * tileSize && worldY >= my && worldY < my + 2 * tileSize) {
            machine = m.engine;
          }
        }
      }
    }
    setHoveredEngine(machine);
  }, [setHoveredAgent, setHoveredEngine]);

  const handleMouseUp = useCallback(() => {
    isDraggingRef.current = false;
  }, []);

  // ── Click for agent selection ──────────────────────────────────────────
  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      if (didDragRef.current) return;

      const store = useOfficeStore.getState();
      const hovered = store.hoveredAgent;
      if (hovered) {
        selectAgent(hovered);
        onAgentClick?.(hovered);
      } else {
        selectAgent(null);
      }
    },
    [selectAgent, onAgentClick],
  );

  return (
    <div
      ref={containerRef}
      className={`relative w-full h-full overflow-hidden bg-slate-100 ${className}`}
    >
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full cursor-grab active:cursor-grabbing"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onClick={handleClick}
      />

      {ready && (
        <>
          {/* The pipeline, then the departments */}
          <div className="absolute top-0 left-0 right-0 z-10">
            <PipelineStrip />
            <PipelineProgress />
          </div>

          {/* Agent and engine hover tooltips */}
          <AgentTooltip />
          <EngineTooltip />

          {/* The floor plan: every department, who is in it, what the engines do */}
          <div className={`absolute bottom-3 z-30 transition-[left] ${showPlan ? "left-[492px]" : "left-[150px]"}`}>
            <button
              onClick={() => setShowPlan((v) => !v)}
              className="flex items-center gap-1.5 bg-gray-900/80 backdrop-blur-sm rounded-lg border border-gray-700/50 px-2.5 py-1.5 text-xs text-gray-300 hover:text-white hover:bg-gray-800/80 transition-colors"
              title="The office, explained"
            >
              <MapIcon className="w-3.5 h-3.5" />
              Floor plan
            </button>
          </div>
          {showPlan && <FloorPlanPanel onClose={() => setShowPlan(false)} />}

          {/* Mini map - bottom right */}
          <div className="absolute bottom-3 right-3 z-10">
            <MiniMap />
          </div>

          {/* Speed controls - bottom left, beside the floor plan when it is open */}
          <div className={`absolute bottom-3 z-30 transition-[left] ${showPlan ? "left-[352px]" : "left-3"}`}>
            <SpeedControls />
          </div>

          {/* Agent detail panel - slides from right */}
          {selectedAgent && <AgentPanel />}
        </>
      )}
    </div>
  );
}

export default VirtualOffice;

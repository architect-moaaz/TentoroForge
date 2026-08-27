// ── Office State Manager (Zustand) ──────────────────────────────────────────

import { create } from "zustand";
import { AgentCharacter } from "./AgentCharacter";
import { OFFICE_LAYOUT } from "./layout";
import { findPath, buildWalkableGrid } from "./Pathfinder";
import {
  AGENT_REGISTRY,
  AGENT_PHASE_MAP,
  PHASE_ROOM_MAP,
  type OfficeEvent,
  type AgentStartEvent,
  type AgentStatusEvent,
  type AgentHandoffEvent,
  type AgentErrorEvent,
  type AgentCompleteEvent,
  type ParallelStartEvent,
  type BuildSuccessEvent,
  type PhaseStartEvent,
  type PhaseCompleteEvent,
  type CreditsExhaustedEvent,
  type Position,
} from "./types";

// ── Store Interface ─────────────────────────────────────────────────────────

export interface OfficeStore {
  // State
  agents: Map<string, AgentCharacter>;
  activePhase: string | null;
  activeAgents: Set<string>;
  completedPhases: Set<string>;
  isRunning: boolean;
  speed: number; // 1, 2, or 4
  selectedAgent: string | null;
  hoveredAgent: string | null;
  showLabels: boolean;
  totalProgress: number;
  events: OfficeEvent[];

  // Actions
  initialize: () => void;
  handleEvent: (event: OfficeEvent) => void;
  setSpeed: (speed: number) => void;
  selectAgent: (id: string | null) => void;
  setHoveredAgent: (id: string | null) => void;
  toggleLabels: () => void;
  reset: () => void;
  tick: (dt: number, timestamp: number) => void;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Find the desk position assigned to an agent, or the center of their room. */
function getDeskPosition(agentId: string, roomId: string): Position {
  for (const room of OFFICE_LAYOUT.rooms) {
    if (room.id === roomId) {
      const desk = room.desks.find((d) => d.agentId === agentId);
      if (desk) return { x: desk.x, y: desk.y };
      // Fallback: center of room
      return {
        x: room.x + Math.floor(room.w / 2),
        y: room.y + Math.floor(room.h / 2),
      };
    }
  }
  // Absolute fallback
  return { x: 5, y: 5 };
}

function getRoomCenter(roomId: string): Position {
  const room = OFFICE_LAYOUT.rooms.find((r) => r.id === roomId);
  if (!room) return { x: 5, y: 5 };
  return {
    x: room.x + Math.floor(room.w / 2),
    y: room.y + Math.floor(room.h / 2),
  };
}

function navigateAgent(
  agent: AgentCharacter,
  target: Position,
  onArrival?: () => void,
) {
  const state = agent.getState();
  const grid = buildWalkableGrid(OFFICE_LAYOUT);
  const path = findPath(grid, state.position, target);
  if (onArrival) {
    agent.onArrival = onArrival;
  }
  if (path && path.length > 0) {
    agent.moveTo(target, path);
  } else {
    // Direct move if no path found
    agent.moveTo(target, [state.position, target]);
  }
}

// ── Store ───────────────────────────────────────────────────────────────────

export const useOfficeStore = create<OfficeStore>((set, get) => ({
  // ── Initial state ───────────────────────────────────────────────────────
  agents: new Map(),
  activePhase: null,
  activeAgents: new Set(),
  completedPhases: new Set(),
  isRunning: false,
  speed: 1,
  selectedAgent: null,
  hoveredAgent: null,
  showLabels: true,
  totalProgress: 0,
  events: [],

  // ── Actions ─────────────────────────────────────────────────────────────

  initialize: () => {
    const agents = new Map<string, AgentCharacter>();

    for (const info of AGENT_REGISTRY) {
      const deskPos = getDeskPosition(info.id, info.room);
      const desk: import("./types").DeskPosition = {
        x: deskPos.x,
        y: deskPos.y,
        agentId: info.id,
        facing: "down" as const,
      };
      const agent = new AgentCharacter(info, desk);
      agents.set(info.id, agent);
    }

    set({ agents, isRunning: true });
  },

  handleEvent: (event: OfficeEvent) => {
    const { agents, activeAgents, completedPhases, events } = get();

    // Append to event log (keep last 200)
    const updatedEvents = [...events, event].slice(-200);

    switch (event.type) {
      case "agent_start": {
        const e = event as AgentStartEvent;
        const agent = agents.get(e.agent);
        if (!agent) break;

        const deskPos = getDeskPosition(e.agent, e.room);
        const newActive = new Set(activeAgents);
        newActive.add(e.agent);

        navigateAgent(agent, deskPos, () => {
          agent.startWorking();
          agent.setSpeechBubble(e.action ?? "Working...", "normal");
        });

        set({ activeAgents: newActive, events: updatedEvents });
        break;
      }

      case "agent_status": {
        const e = event as AgentStatusEvent;
        const agent = agents.get(e.agent);
        if (!agent) break;

        agent.setSpeechBubble(e.status, "normal");
        if (e.progress !== undefined) {
          agent.setProgress(e.progress);
        }
        set({ events: updatedEvents });
        break;
      }

      case "agent_handoff": {
        const e = event as AgentHandoffEvent;
        const fromAgent = agents.get(e.from);
        const toAgent = agents.get(e.to);
        if (!fromAgent || !toAgent) break;

        const toInfo = AGENT_REGISTRY.find((a) => a.id === e.to);
        const toRoomId = toInfo?.room ?? "planning";
        const toState = toAgent.getState();
        const targetPos = { ...toState.position };

        // From-agent walks toward to-agent's position
        navigateAgent(fromAgent, targetPos, () => {
          fromAgent.setSpeechBubble(
            `Handing off ${e.artifact ?? "work"}`,
            "normal",
          );

          // To-agent starts working (not just reading)
          toAgent.startWorking();
          toAgent.setSpeechBubble(
            `Reviewing ${e.artifact ?? "handoff"}`,
            "normal",
          );

          // After a brief pause, walk the from-agent back to their own desk
          const fromInfo = AGENT_REGISTRY.find((a) => a.id === e.from);
          const fromRoomId = fromInfo?.room ?? "planning";
          const fromDesk = getDeskPosition(e.from, fromRoomId);

          // Use setTimeout to let the handoff message display before walking back
          setTimeout(() => {
            navigateAgent(fromAgent, fromDesk, () => {
              fromAgent.goIdle();
            });
          }, 1500);
        });

        const newActive = new Set(activeAgents);
        newActive.add(e.to);
        set({ activeAgents: newActive, events: updatedEvents });
        break;
      }

      case "agent_error": {
        const e = event as AgentErrorEvent;
        const agent = agents.get(e.agent);
        if (!agent) break;

        agent.setError(e.message);
        agent.setSpeechBubble(e.message, "error");
        set({ events: updatedEvents });
        break;
      }

      case "agent_complete": {
        const e = event as AgentCompleteEvent;
        const agent = agents.get(e.agent);
        if (!agent) break;

        const doneMessage = e.files_generated
          ? `Done! ${e.files_generated} files`
          : "Done!";

        // Walk the agent back to their home desk, then celebrate with speech bubble
        const completeInfo = AGENT_REGISTRY.find((a) => a.id === e.agent);
        const homeRoomId = completeInfo?.room ?? "planning";
        const homeDesk = getDeskPosition(e.agent, homeRoomId);
        const currentPos = agent.getState().position;

        const onArrival = () => {
          // Celebrate first, then set speech bubble (celebrate clears it)
          agent.celebrate();
          agent.setSpeechBubble(doneMessage, "success");
          // Return to idle after 3 seconds
          setTimeout(() => {
            agent.goIdle();
          }, 3000);
        };

        const atHome = Math.abs(currentPos.x - homeDesk.x) < 1 && Math.abs(currentPos.y - homeDesk.y) < 1;
        if (atHome) {
          onArrival();
        } else {
          navigateAgent(agent, homeDesk, onArrival);
        }

        const newActive = new Set(activeAgents);
        newActive.delete(e.agent);
        set({ activeAgents: newActive, events: updatedEvents });
        break;
      }

      case "parallel_start": {
        const e = event as ParallelStartEvent;
        const newActive = new Set(activeAgents);

        for (const agentId of e.agents) {
          const agent = agents.get(agentId);
          if (!agent) continue;
          newActive.add(agentId);

          const info = AGENT_REGISTRY.find((a) => a.id === agentId);
          const roomId = info?.room ?? "planning";
          const deskPos = getDeskPosition(agentId, roomId);

          navigateAgent(agent, deskPos, () => {
            agent.startWorking();
            agent.setSpeechBubble("Starting...", "normal");
          });
        }

        set({ activeAgents: newActive, events: updatedEvents });
        break;
      }

      case "build_success": {
        const e = event as BuildSuccessEvent;
        const lobby = OFFICE_LAYOUT.lobby;

        // All agents walk to lobby and celebrate
        for (const [, agent] of agents) {
          navigateAgent(agent, lobby, () => {
            agent.celebrate();
            agent.setSpeechBubble(
              e.total_files
                ? `${e.total_files} files shipped!`
                : "Ship it!",
              "success",
            );
          });
        }

        set({
          totalProgress: 100,
          events: updatedEvents,
        });
        break;
      }

      case "phase_start": {
        const e = event as PhaseStartEvent;
        const roomId = PHASE_ROOM_MAP[e.phase] ?? "planning";
        const newActive = new Set(activeAgents);

        // Only activate agents whose phase matches, not all agents in the room
        for (const info of AGENT_REGISTRY) {
          if (AGENT_PHASE_MAP[info.id] === e.phase) {
            const agent = agents.get(info.id);
            if (!agent) continue;
            newActive.add(info.id);

            const deskPos = getDeskPosition(info.id, roomId);
            navigateAgent(agent, deskPos, () => {
              agent.startWorking();
              agent.setSpeechBubble(e.message ?? `Phase: ${e.phase}`, "normal");
            });
          }
        }

        set({
          activePhase: e.phase,
          activeAgents: newActive,
          events: updatedEvents,
        });
        break;
      }

      case "phase_complete": {
        const e = event as PhaseCompleteEvent;
        const newCompleted = new Set(completedPhases);
        newCompleted.add(e.phase);

        // Calculate progress based on completed phases
        const totalPhases = Object.keys(PHASE_ROOM_MAP).length;
        const progress = Math.round((newCompleted.size / totalPhases) * 100);

        // Complete agents that belong to this phase and walk them back to desk
        const newActive = new Set(activeAgents);
        for (const info of AGENT_REGISTRY) {
          if (AGENT_PHASE_MAP[info.id] === e.phase) {
            const agent = agents.get(info.id);
            if (agent) {
              agent.setSpeechBubble("Done!", "success");
              newActive.delete(info.id);

              // Walk back to home desk
              const homeDesk = getDeskPosition(info.id, info.room);
              const currentPos = agent.getState().position;
              const atHome = Math.abs(currentPos.x - homeDesk.x) < 1 && Math.abs(currentPos.y - homeDesk.y) < 1;
              if (atHome) {
                agent.goIdle();
              } else {
                navigateAgent(agent, homeDesk, () => {
                  agent.goIdle();
                });
              }
            }
          }
        }

        set({
          completedPhases: newCompleted,
          totalProgress: progress,
          activeAgents: newActive,
          events: updatedEvents,
        });
        break;
      }

      case "credits_exhausted": {
        const e = event as CreditsExhaustedEvent;
        const lobby = OFFICE_LAYOUT.lobby;

        const protestSigns = [
          "We want credits!",
          "No credits, no code!",
          "Unfair!",
          "Pay us!",
          "On strike!",
          "Need more tokens!",
          "Credits NOW!",
          "We deserve better!",
          "Halt production!",
          "Out of fuel!",
        ];

        // All agents walk to lobby and start protesting
        let signIdx = 0;
        for (const [, agent] of agents) {
          const sign = protestSigns[signIdx % protestSigns.length];
          signIdx++;
          // Scatter them around the lobby so they don't stack
          const offsetX = (Math.random() - 0.5) * 6;
          const offsetY = (Math.random() - 0.5) * 4;
          const target: Position = {
            x: Math.round(lobby.x + offsetX),
            y: Math.round(lobby.y + offsetY),
          };

          navigateAgent(agent, target, () => {
            agent.protest(sign);
          });
        }

        set({
          totalProgress: 0,
          events: updatedEvents,
        });
        break;
      }
    }
  },

  setSpeed: (speed: number) => {
    set({ speed: Math.max(1, Math.min(4, speed)) });
  },

  selectAgent: (id: string | null) => {
    set({ selectedAgent: id });
  },

  setHoveredAgent: (id: string | null) => {
    set({ hoveredAgent: id });
  },

  toggleLabels: () => {
    set((s) => ({ showLabels: !s.showLabels }));
  },

  reset: () => {
    const { agents } = get();
    // Clear existing agents
    for (const [, agent] of agents) {
      agent.goIdle();
    }
    set({
      agents: new Map(),
      activePhase: null,
      activeAgents: new Set(),
      completedPhases: new Set(),
      isRunning: false,
      speed: 1,
      selectedAgent: null,
      hoveredAgent: null,
      totalProgress: 0,
      events: [],
    });
  },

  tick: (dt: number, timestamp: number) => {
    const { agents, speed } = get();
    const scaledDt = dt * speed;
    for (const [, agent] of agents) {
      agent.update(scaledDt, timestamp);
    }
  },
}));

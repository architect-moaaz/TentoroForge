// ── Office State Manager (Zustand) ──────────────────────────────────────────

import { create } from "zustand";
import { AgentCharacter } from "./AgentCharacter";
import { OFFICE_LAYOUT } from "./layout";
import { findPath, buildWalkableGrid } from "./Pathfinder";
import {
  AGENT_REGISTRY,
  AGENT_BY_ID,
  AGENT_PHASE_MAP,
  PHASE_ROOM_MAP,
  type OfficeEvent,
  type AgentStartEvent,
  type AgentStatusEvent,
  type AgentHandoffEvent,
  type ArtifactDeliveryEvent,
  type AgentErrorEvent,
  type AgentBlockedEvent,
  type AgentSkippedEvent,
  type AgentRetryEvent,
  type AgentCompleteEvent,
  type ParallelStartEvent,
  type RunPlanEvent,
  type RunCompleteEvent,
  type BuildSuccessEvent,
  type PhaseStartEvent,
  type PhaseCompleteEvent,
  type CreditsExhaustedEvent,
  type Position,
} from "./types";

/** One artifact in flight between two desks, queued for the renderer.
 *
 *  Kept in the store rather than the renderer because the store is what sees
 *  the event; the renderer drains the queue each frame with `takeDeliveries`
 *  and owns the particle from then on. */
export interface Delivery {
  id: number;
  from: Position;
  to: Position;
  artifact: string;
  color: string;
}

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

  // ── Blueprint DAG run state ──────────────────────────────────────────
  /** Agents on the current run's plan. Empty means "no run declared a
   *  roster" — the legacy relay never sends one — and the office treats
   *  everyone as on duty rather than greying the whole floor out. */
  roster: Set<string>;
  /** The run's concurrency levels, agent ids per wave (§28). */
  levels: string[][];
  /** Nodes finished / nodes planned, for the department progress bar. */
  nodesDone: number;
  nodesPlanned: number;
  /** Why an agent is parked, keyed by agent id. Read by the agent panel. */
  blockedReasons: Map<string, string>;
  skippedReasons: Map<string, string>;
  /** Artifacts in flight, waiting to be picked up by the renderer. */
  deliveries: Delivery[];
  /** Set once when a build ships, cleared when the renderer has thrown the
   *  confetti. Declared rather than inferred from "somebody is celebrating":
   *  every finished DAG node celebrates, and a twenty-node run should not
   *  empty the confetti cannon twenty times. */
  party: Position | null;
  /** True between a run's roster and its last frame.
   *
   *  What keeps the office on screen. A Smith turn is one HTTP request, and
   *  tying the view to that request means it closes the instant the response
   *  lands — which is exactly when the celebration, the failures and the final
   *  poses arrive. The run declares when it is over; the request does not get
   *  to decide.
   *
   *  Stays false for the legacy relay, which never sends a roster, so that
   *  path keeps behaving exactly as it did. */
  runActive: boolean;

  // Actions
  initialize: () => void;
  handleEvent: (event: OfficeEvent) => void;
  /** Hand the renderer every queued delivery and clear the queue. */
  takeDeliveries: () => Delivery[];
  /** Hand the renderer the pending party, if there is one, and clear it. */
  takeParty: () => Position | null;
  /** No more frames are coming — the producer failed, or went away. Only for
   *  a producer that knows; a run that finishes clears this itself. */
  endRun: () => void;
  setSpeed: (speed: number) => void;
  selectAgent: (id: string | null) => void;
  setHoveredAgent: (id: string | null) => void;
  toggleLabels: () => void;
  reset: () => void;
  tick: (dt: number, timestamp: number) => void;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Monotonic id for queued deliveries, so the renderer can key its particles. */
let nextDeliveryId = 1;

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
  roster: new Set(),
  levels: [],
  nodesDone: 0,
  nodesPlanned: 0,
  blockedReasons: new Map(),
  skippedReasons: new Map(),
  deliveries: [],
  party: null,
  runActive: false,

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

        // The registry's room wins over the event's. A producer that names a
        // department this build doesn't have would otherwise send the agent to
        // getDeskPosition's absolute fallback tile, and everyone whose room
        // was unknown would pile onto the same square.
        const roomId = AGENT_BY_ID[e.agent]?.room ?? e.room;
        const deskPos = getDeskPosition(e.agent, roomId);
        const newActive = new Set(activeAgents);
        newActive.add(e.agent);

        // Starting clears whatever parked this agent on a previous run.
        const blockedReasons = new Map(get().blockedReasons);
        const skippedReasons = new Map(get().skippedReasons);
        blockedReasons.delete(e.agent);
        skippedReasons.delete(e.agent);

        agent.setNode(e.node);
        navigateAgent(agent, deskPos, () => {
          agent.startWorking();
          agent.setSpeechBubble(e.action ?? "Working...", "normal");
        });

        set({ activeAgents: newActive, blockedReasons, skippedReasons,
              events: updatedEvents });
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
        if (e.node) agent.setNode(e.node);
        // A status carrying a subject is one step of a fan-out. Parse the
        // "(3/18)" the narrator writes into the tally the desk stamps.
        const fanout = /\((\d+)\/(\d+)\)/.exec(e.status);
        if (fanout) {
          agent.setTally(Number(fanout[1]) - 1, Number(fanout[2]));
        } else if (e.subject && e.progress !== undefined) {
          // The subject-done status has no counter in its text; derive the
          // done-count from the progress fraction the narrator sent.
          const tally = agent.getState().tally;
          if (tally) agent.setTally(Math.round(e.progress * tally.total), tally.total);
        }
        // A status arriving while the agent was parked means it is moving
        // again — an outcome state must not outlive the work it described.
        const st = agent.getState().state;
        if (st === "retrying" || st === "blocked" || st === "skipped") {
          agent.startWorking();
          agent.setSpeechBubble(e.status, "normal");
        }
        set({ events: updatedEvents });
        break;
      }

      case "artifact_delivery": {
        const e = event as ArtifactDeliveryEvent;
        const fromAgent = agents.get(e.from);
        const toAgent = agents.get(e.to);
        if (!fromAgent || !toAgent) break;

        // Nobody walks. The parcel crosses the floor on its own, so a node
        // that feeds five downstream nodes doesn't empty five desks.
        const delivery: Delivery = {
          id: nextDeliveryId++,
          from: { ...fromAgent.getState().position },
          to: { ...toAgent.getState().position },
          artifact: e.artifact ?? "",
          color: AGENT_BY_ID[e.from]?.color ?? "#3B82F6",
        };
        set({ deliveries: [...get().deliveries, delivery], events: updatedEvents });
        break;
      }

      case "agent_retry": {
        const e = event as AgentRetryEvent;
        const agent = agents.get(e.agent);
        if (!agent) break;
        agent.retry(e.attempt, e.of, e.reason);
        set({ events: updatedEvents });
        break;
      }

      case "agent_blocked": {
        const e = event as AgentBlockedEvent;
        const agent = agents.get(e.agent);
        if (!agent) break;
        agent.block(e.reason);
        const blockedReasons = new Map(get().blockedReasons);
        blockedReasons.set(e.agent, e.reason ?? "blocked");
        const newActive = new Set(activeAgents);
        newActive.delete(e.agent);
        set({ blockedReasons, activeAgents: newActive, events: updatedEvents });
        break;
      }

      case "agent_skipped": {
        const e = event as AgentSkippedEvent;
        const agent = agents.get(e.agent);
        if (!agent) break;
        agent.skip(e.reason);
        const skippedReasons = new Map(get().skippedReasons);
        skippedReasons.set(e.agent, e.reason ?? "inputs never arrived");
        const newActive = new Set(activeAgents);
        newActive.delete(e.agent);
        set({ skippedReasons, activeAgents: newActive, events: updatedEvents });
        break;
      }

      case "run_plan": {
        const e = event as RunPlanEvent;
        const roster = new Set(e.agents.filter((id) => agents.has(id)));

        // Everyone not on the plan goes back to their desk and stands down.
        // A run of five nodes should read as five people working, not as
        // eighteen people whose stillness the picture cannot explain.
        for (const [id, agent] of agents) {
          if (roster.has(id)) continue;
          const home = getDeskPosition(id, AGENT_BY_ID[id]?.room ?? "discovery");
          const at = agent.getState().position;
          if (Math.abs(at.x - home.x) < 1 && Math.abs(at.y - home.y) < 1) {
            agent.goIdle();
          } else {
            navigateAgent(agent, home, () => agent.goIdle());
          }
        }

        set({
          roster,
          levels: e.levels ?? [],
          nodesDone: 0,
          nodesPlanned: e.agents.length,
          totalProgress: 0,
          runActive: true,
          blockedReasons: new Map(),
          skippedReasons: new Map(),
          activeAgents: new Set(),
          events: updatedEvents,
        });
        break;
      }

      case "run_complete": {
        const e = event as RunCompleteEvent;
        // Not a shipping party — something failed or is parked. Whoever is
        // blocked or shrugging keeps that pose; everybody else stands down.
        for (const [, agent] of agents) {
          const st = agent.getState().state;
          if (st === "blocked" || st === "skipped" || st === "error") continue;
          agent.goIdle();
        }
        const done = e.completed ?? get().nodesDone;
        set({
          activeAgents: new Set(),
          runActive: false,
          nodesDone: done,
          totalProgress: get().nodesPlanned
            ? Math.round((done / get().nodesPlanned) * 100)
            : 0,
          events: updatedEvents,
        });
        break;
      }

      case "agent_handoff": {
        const e = event as AgentHandoffEvent;
        const fromAgent = agents.get(e.from);
        const toAgent = agents.get(e.to);
        if (!fromAgent || !toAgent) break;

        const toInfo = AGENT_REGISTRY.find((a) => a.id === e.to);
        const toRoomId = toInfo?.room ?? "discovery";
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
          const fromRoomId = fromInfo?.room ?? "discovery";
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
        const homeRoomId = completeInfo?.room ?? "discovery";
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
        const nodesDone = get().nodesDone + 1;
        const nodesPlanned = get().nodesPlanned;
        set({
          activeAgents: newActive,
          nodesDone,
          // Only the DAG declares a plan size. Under the legacy relay the
          // phase_complete branch still owns the bar, so leave it alone.
          ...(nodesPlanned
            ? { totalProgress: Math.min(100, Math.round((nodesDone / nodesPlanned) * 100)) }
            : {}),
          events: updatedEvents,
        });
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
          const roomId = info?.room ?? "discovery";
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
        // Everything shipped, so nobody is parked any more.
        set({
          blockedReasons: new Map(),
          skippedReasons: new Map(),
          party: { ...lobby },
        });

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
          runActive: false,
          events: updatedEvents,
        });
        break;
      }

      case "phase_start": {
        const e = event as PhaseStartEvent;
        const roomId = PHASE_ROOM_MAP[e.phase] ?? "discovery";
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
          runActive: false,
          events: updatedEvents,
        });
        break;
      }
    }
  },

  endRun: () => {
    set({ runActive: false });
  },

  takeDeliveries: () => {
    const queued = get().deliveries;
    if (queued.length === 0) return queued;
    set({ deliveries: [] });
    return queued;
  },

  takeParty: () => {
    const at = get().party;
    if (at) set({ party: null });
    return at;
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
      roster: new Set(),
      levels: [],
      nodesDone: 0,
      nodesPlanned: 0,
      blockedReasons: new Map(),
      skippedReasons: new Map(),
      deliveries: [],
      party: null,
      runActive: false,
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

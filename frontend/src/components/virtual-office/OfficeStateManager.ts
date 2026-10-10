// ── Office State Manager (Zustand) ──────────────────────────────────────────

import { create } from "zustand";
import { AgentCharacter } from "./AgentCharacter";
import { OFFICE_LAYOUT, huddleSeats, benchSpot, visitorSpot, boardSpot, roomCenter } from "./layout";
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
  type HuddleStartEvent,
  type HuddleSayEvent,
  type HuddleEndEvent,
  type PipelineStageEvent,
  type SmithTurnEvent,
  type SmithStepEvent,
  type TrialEvent,
  type EngineEvent,
  type Position,
  NODE_ENGINES,
  ENGINE_BY_ID,
} from "./types";

/** Where the build is, read off the engineer's journal. */
export interface PipelineState {
  stage: string | null;
  label: string;
  feature?: string;
  name?: string;
  index?: number;
  total?: number;
  features: string[];
  /** Features proven so far (ids). */
  done: string[];
  /** What the last stage said about proof: statements held / written. */
  passed?: number;
  statements?: number;
  /** Why it stopped, when it did. */
  why?: string;
  /** The last few stages, newest last. */
  history: PipelineStageEvent[];
}

/** Smith's turn, as the Front Desk shows it. */
export interface SmithState {
  inTurn: boolean;
  mode: "conversation" | "unattended";
  text: string;
  step?: { tool: string; kind: SmithStepEvent["kind"]; said: string; status: string };
  steps: number;
  outcome?: string;
}

export interface EngineState {
  state: "busy" | "on" | "off";
  detail: string;
  since: number;
}

export interface TrialsState {
  tried: number;
  passed: number;
  failed: number;
  untried: number;
  trying?: TrialEvent;
  last?: TrialEvent;
}

/** Which desk a Smith write lands on: the author of what the tool changes.
 *  A tool not named here is Smith's own (a seam write at the Front Desk). */
const WRITE_OWNER: Record<string, string> = {
  edit_file: "ui_engineer",
  write_page_code: "ui_engineer",
  rewrite_pages: "ui_engineer",
  write_frame: "ui_engineer",
  verify_pages: "page_reviewer",
  write_section: "solution_architecture",
  edit_definition: "solution_architecture",
  define_application: "requirement",
  set_field: "data_model",
  add_expectation: "testing",
}

const EMPTY_PIPELINE: PipelineState = { stage: null, label: "", features: [], done: [], history: [] };
const EMPTY_SMITH: SmithState = { inTurn: false, mode: "conversation", text: "", steps: 0 };
const EMPTY_TRIALS: TrialsState = { tried: 0, passed: 0, failed: 0, untried: 0 };

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

export interface OfficeHuddle {
  id: string;
  kind: "review" | "deadlock";
  topic: string;
  chair: string;
  participants: string[];
  status: "open" | "decided" | "deadlock";
  decision: string;
}

/** How long the decision stays above the table before everyone walks back. */
const HUDDLE_LINGER_MS = 4500;

function short(text: string, n = 60): string {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}

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
  /** The huddle at the table now, if any — who is in it, what about, and
   *  once decided, what was decided. */
  huddle: OfficeHuddle | null;
  /** Where the build is: the engineer's journal, stage by stage. */
  pipeline: PipelineState;
  /** Smith's turn at the Front Desk. */
  smith: SmithState;
  /** The engines' lights, by engine id. */
  engines: Map<string, EngineState>;
  /** What the Workbench has tried this run. */
  trials: TrialsState;
  /** What the bench is saying, drawn as its speech bubble. */
  benchSays: { text: string; type: "normal" | "error" | "success"; at: number } | null;
  hoveredEngine: string | null;
  /** A camera request from the HUD (a room clicked on the floor plan). */
  focus: Position | null;

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
  setHoveredEngine: (id: string | null) => void;
  /** Ask the camera to look at a room. */
  focusRoom: (roomId: string) => void;
  /** Hand the renderer the pending camera request, if any. */
  takeFocus: () => Position | null;
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
  huddle: null,
  pipeline: EMPTY_PIPELINE,
  smith: EMPTY_SMITH,
  engines: new Map(),
  trials: EMPTY_TRIALS,
  benchSays: null,
  hoveredEngine: null,
  focus: null,

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

        // The engines this step runs light up with it.
        const engines = new Map(get().engines);
        for (const id of NODE_ENGINES[e.node ?? ""] ?? []) {
          engines.set(id, { state: "busy", detail: e.action ?? `Running ${e.node}`, since: Date.now() });
        }
        set({ activeAgents: newActive, blockedReasons, skippedReasons, engines,
              events: updatedEvents });
        break;
      }

      case "pipeline_stage": {
        const e = event as PipelineStageEvent;
        const prev = get().pipeline;
        const next: PipelineState = {
          ...prev,
          stage: e.stage,
          label: e.label,
          feature: e.feature ?? (e.stage === "feature" || e.stage === "proof" || e.stage === "fix" ? prev.feature : undefined),
          name: e.name ?? (e.stage === "feature" || e.stage === "proof" || e.stage === "fix" ? prev.name : undefined),
          index: e.index ?? prev.index,
          total: e.total ?? prev.total,
          features: Array.isArray(e.features) ? e.features : prev.features,
          done: Array.isArray(e.done) ? e.done : prev.done,
          passed: typeof e.passed === "number" ? e.passed : prev.passed,
          statements: typeof e.statements === "number" ? e.statements : prev.statements,
          why: e.stage === "stopped" ? String(e.why ?? e.label) : undefined,
          history: [...prev.history, e].slice(-30),
        };
        if (e.stage === "proof" && e.done === true && e.feature && !next.done.includes(e.feature)) {
          next.done = [...next.done, e.feature];
        }
        const trials = e.stage === "build" || e.stage === "define" ? EMPTY_TRIALS : get().trials;
        // The engineer says each stage; a feature's start is its walk to the
        // Architecture board, a proof its walk to the bench.
        const engineer = agents.get("engineer");
        if (engineer) {
          if (e.stage === "feature") {
            const desk = getDeskPosition("engineer", AGENT_BY_ID.engineer?.room ?? "architecture");
            navigateAgent(engineer, desk, () => {
              engineer.startWorking();
              engineer.setSpeechBubble(e.label, "normal");
            });
          } else if (e.stage === "proof" || e.stage === "whole") {
            navigateAgent(engineer, benchSpot(), () => {
              engineer.startReading();
              engineer.setSpeechBubble(e.label, e.failing && (e.failing as string[]).length ? "error" : "success");
            });
          } else if (e.stage === "handover") {
            navigateAgent(engineer, visitorSpot(), () => {
              engineer.celebrate();
              engineer.setSpeechBubble(e.label, "success");
            });
          } else if (e.stage === "stopped") {
            navigateAgent(engineer, visitorSpot(), () => {
              engineer.setError(e.label);
            });
          } else {
            engineer.setSpeechBubble(e.label, "normal");
          }
        }
        set({ pipeline: next, trials, events: updatedEvents });
        break;
      }

      case "smith_turn": {
        const e = event as SmithTurnEvent;
        const smith = agents.get("smith");
        if (e.status === "start") {
          if (smith) {
            const desk = getDeskPosition("smith", "front_desk");
            navigateAgent(smith, desk, () => {
              smith.startReading();
              smith.setSpeechBubble(e.text || "Taking a look…", "normal");
            });
          }
          set({
            smith: { inTurn: true, mode: e.mode, text: e.text, steps: 0 },
            // A person's turn keeps the office on screen until it ends.
            ...(e.mode === "conversation" ? { runActive: true } : {}),
            events: updatedEvents,
          });
        } else {
          const outcome = e.outcome ?? "";
          const good = outcome === "resolved" || outcome === "answered" || outcome === "asked";
          if (smith) {
            const where = e.mode === "conversation" ? visitorSpot() : getDeskPosition("smith", "front_desk");
            navigateAgent(smith, where, () => {
              if (good && outcome !== "asked") smith.celebrate();
              else smith.goIdle();
              smith.setSpeechBubble(e.text || outcome || "Done", good ? "success" : "error");
            });
          }
          set({
            smith: { ...get().smith, inTurn: false, outcome, text: e.text },
            ...(e.mode === "conversation" ? { runActive: false } : {}),
            events: updatedEvents,
          });
        }
        break;
      }

      case "smith_step": {
        const e = event as SmithStepEvent;
        const smith = agents.get("smith");
        const said = e.said || e.tool.replace(/_/g, " ");
        const bubbleType = e.status === "error" ? "error" : e.status === "resolved" ? "success" : "normal";
        if (smith) {
          switch (e.kind) {
            case "try": {
              navigateAgent(smith, benchSpot(), () => {
                smith.startWorking();
                smith.setSpeechBubble(said, bubbleType);
              });
              break;
            }
            case "write": {
              const owner = WRITE_OWNER[e.tool];
              const to = owner ? agents.get(owner) : undefined;
              if (owner && to) {
                const theirs = getDeskPosition(owner, AGENT_BY_ID[owner]?.room ?? "discovery");
                navigateAgent(smith, { x: theirs.x + (theirs.x % 2 === 0 ? -1 : 1), y: theirs.y }, () => {
                  smith.startWorking();
                  smith.setSpeechBubble(said, bubbleType);
                  to.startWorking();
                  to.setSpeechBubble(`With Smith: ${e.tool.replace(/_/g, " ")}`, "normal");
                  setTimeout(() => to.goIdle(), 2500);
                });
              } else {
                const desk = getDeskPosition("smith", "front_desk");
                navigateAgent(smith, desk, () => {
                  smith.startWorking();
                  smith.setSpeechBubble(said, bubbleType);
                });
              }
              break;
            }
            case "ask": {
              navigateAgent(smith, visitorSpot(), () => {
                smith.startReading();
                smith.setSpeechBubble(said, "normal");
              });
              break;
            }
            case "report": {
              navigateAgent(smith, boardSpot(), () => {
                smith.startWorking();
                smith.setSpeechBubble(`Platform fault pinned: ${said}`, "error");
              });
              break;
            }
            case "end": {
              smith.setSpeechBubble(said, bubbleType);
              break;
            }
            default: {
              const desk = getDeskPosition("smith", "front_desk");
              navigateAgent(smith, desk, () => {
                smith.startReading();
                smith.setSpeechBubble(said, bubbleType);
              });
            }
          }
        }
        set({
          smith: { ...get().smith, inTurn: true, steps: get().smith.steps + 1,
                   step: { tool: e.tool, kind: e.kind, said: e.said, status: e.status } },
          events: updatedEvents,
        });
        break;
      }

      case "trial": {
        const e = event as TrialEvent;
        const t = { ...get().trials };
        const engines = new Map(get().engines);
        let says: { text: string; type: "normal" | "error" | "success" } | null = null;
        if (e.verdict === "trying") {
          t.trying = e;
          says = { text: `Trying${e.who ? ` as ${e.who}` : ""}: ${e.says}`, type: "normal" };
          engines.set("workbench", { state: "busy", detail: `trying ${e.statement}`, since: Date.now() });
        } else {
          t.tried += 1;
          if (e.verdict === "passed") t.passed += 1;
          else if (e.verdict === "failed") t.failed += 1;
          else t.untried += 1;
          t.trying = undefined;
          t.last = e;
          says = e.verdict === "passed"
            ? { text: `✓ ${e.says}`, type: "success" }
            : e.verdict === "failed"
              ? { text: `✗ ${e.says}`, type: "error" }
              : { text: `Could not try: ${e.says}`, type: "error" };
          engines.set("workbench", { state: "on", detail: `${t.passed} held, ${t.failed} failed`, since: Date.now() });
        }
        set({ trials: t, engines, benchSays: says ? { ...says, at: Date.now() } : get().benchSays,
              events: updatedEvents });
        break;
      }

      case "engine": {
        const e = event as EngineEvent;
        if (!ENGINE_BY_ID[e.engine]) break;
        const engines = new Map(get().engines);
        engines.set(e.engine, { state: e.state, detail: e.detail ?? "", since: Date.now() });
        const bench = e.engine === "workbench" && e.detail
          ? { text: e.detail, type: (e.state === "off" ? "normal" : "normal") as "normal", at: Date.now() }
          : null;
        set({ engines, ...(bench ? { benchSays: bench } : {}), events: updatedEvents });
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

      case "huddle_start": {
        // The agents the question touches walk to the Huddle Room; the
        // observer takes the head of the table and says what it is about.
        const e = event as HuddleStartEvent;
        const { chair, seats } = huddleSeats();
        const people = [e.chair, ...e.participants.filter((p) => p !== e.chair)];
        people.forEach((id, i) => {
          const agent = agents.get(id);
          if (!agent) return;
          const seat = id === e.chair ? chair : seats[(i - 1) % seats.length];
          navigateAgent(agent, seat, () => {
            agent.setSpeechBubble(id === e.chair ? `Huddle: ${short(e.topic)}` : "…", "normal");
          });
        });
        set({
          huddle: { id: e.huddleId, kind: e.kind, topic: e.topic, chair: e.chair,
                    participants: e.participants, status: "open", decision: "" },
          events: updatedEvents,
        });
        break;
      }

      case "huddle_say": {
        const e = event as HuddleSayEvent;
        agents.get(e.agent)?.setSpeechBubble(short(e.text, 90), "normal");
        set({ events: updatedEvents });
        break;
      }

      case "huddle_end": {
        // The chair says the decision — or the question for the person —
        // and after a moment everyone walks back to their desk.
        const e = event as HuddleEndEvent;
        const chairAgent = agents.get(e.chair);
        chairAgent?.setSpeechBubble(
          e.status === "decided" ? `Decided: ${short(e.decision, 90)}` : `To ask: ${short(e.decision, 90)}`,
          e.status === "decided" ? "success" : "error",
        );
        const current = get().huddle;
        set({
          huddle: current && current.id === e.huddleId
            ? { ...current, status: e.status, decision: e.decision } : current,
          events: updatedEvents,
        });
        setTimeout(() => {
          for (const id of [e.chair, ...e.participants]) {
            const agent = get().agents.get(id);
            const info = AGENT_REGISTRY.find((a) => a.id === id);
            if (!agent || !info) continue;
            navigateAgent(agent, getDeskPosition(id, info.room), () => agent.goIdle());
          }
          const now = get().huddle;
          if (now && now.id === e.huddleId) set({ huddle: null });
        }, HUDDLE_LINGER_MS);
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
        const engines = new Map(get().engines);
        for (const id of NODE_ENGINES[e.node ?? ""] ?? []) {
          const cur = engines.get(id);
          if (cur && cur.state === "busy") engines.set(id, { state: "off", detail: "", since: Date.now() });
        }
        set({
          activeAgents: newActive,
          nodesDone,
          engines,
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

  setHoveredEngine: (id: string | null) => {
    set({ hoveredEngine: id });
  },

  focusRoom: (roomId: string) => {
    try {
      set({ focus: roomCenter(roomId) });
    } catch {
      // no such room: nothing to look at
    }
  },

  takeFocus: () => {
    const at = get().focus;
    if (at) set({ focus: null });
    return at;
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
      huddle: null,
      pipeline: EMPTY_PIPELINE,
      smith: EMPTY_SMITH,
      engines: new Map(),
      trials: EMPTY_TRIALS,
      benchSays: null,
      hoveredEngine: null,
      focus: null,
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

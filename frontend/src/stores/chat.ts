import { create } from "zustand";
import { toast } from "sonner";
import type { ChatMessage, SSEEvent } from "@/types/project";
import { detectPhaseIndex, QUEST_PHASES } from "@/lib/quest-phases";
import { useOfficeStore } from "@/components/virtual-office/OfficeStateManager";
import { AGENT_REGISTRY, type OfficeEvent } from "@/components/virtual-office/types";

/** Detect if an error message indicates a budget/credit issue. */
export function isBudgetError(msg: string): boolean {
  const lower = msg.toLowerCase();
  // Only match phrases that specifically indicate billing/credit problems.
  // Avoid generic words like "insufficient", "exceeded", "command failed"
  // which would false-positive on unrelated CLI errors.
  const phrases = [
    "credit balance",
    "billing",
    "quota exceeded",
    "rate limit",
    "credits exhausted",
    "balance is too low",
    "insufficient credits",
    "out of credits",
    "purchase credits",
    "plans & billing",
  ];
  return phrases.some((p) => lower.includes(p));
}

/** Fire office protest if agents exist (or initialize them). */
function triggerOfficeProtest(errorMsg: string) {
  const officeStore = useOfficeStore.getState();
  if (officeStore.agents.size === 0) {
    officeStore.initialize();
  }
  officeStore.handleEvent({
    type: "credits_exhausted",
    message: errorMsg,
  });
}

/** Map quest phase IDs to office PHASE_ROOM_MAP keys */
const QUEST_TO_OFFICE_PHASE: Record<string, string> = {
  contracts: "contract",
  foundation: "schema",
  backend: "auth",
  components: "components",
  pages: "pages",
  seed: "seed",
  qa: "qa",
  validate: "validation",
  index: "indexing",
};

/** Map `[Tag]` prefixes in log messages to office agent IDs.
 *
 *  The office cast is the Blueprint agent registry, so the relay's older tags
 *  land on the agent that does that job today — the same aliasing
 *  `backend/services/office_events.py` applies to the relay's own office
 *  frames, kept here because these tags never went through it. */
const LOG_TAG_TO_AGENT: Record<string, string> = {
  Plan: "product_analysis",
  Discovery: "requirement",
  Refine: "smith",
  Contract: "solution_architecture",
  Nav: "solution_architecture",
  Portal: "integration",
  Schema: "data_model",
  Seed: "backend",
  API: "api",
  Auth: "security",
  Rules: "business_rules",
  BizLogic: "business_rules",
  Workflow: "workflow",
  Component: "a2ui_pages",
  Page: "a2ui_pages",
  Style: "accessibility",
  Design: "accessibility",
  Figma: "figma_intelligence",
  QA: "testing",
  Validate: "verification",
  Index: "memory",
  Agent: "memory",
  Export: "deployment",
  Ship: "deployment",
};

/** A single before→after change entry in a fix proposal / result. Shape is
 * intentionally loose — the backend preview may label fields differently. */
export interface FixChange {
  label?: string;
  description?: string;
  path?: string;
  from?: unknown;
  to?: unknown;
  [key: string]: unknown;
}

/** Diagnosis + preview carried by a `fix_proposal` SSE event. */
export interface FixProposal {
  diagnosis: {
    symptom?: string;
    feature?: string;
    rootCause?: string;
    explanation?: string;
    artifact?: { kind?: string; path?: string };
    locator?: unknown;
    confidence?: number | string;
  };
  changes: FixChange[];
  applyToken: string;
}

/** Outcome carried by a `fix_applied` SSE event. */
export interface FixResult {
  applied: boolean;
  changes: FixChange[];
  verify: { resolved: boolean; remaining?: unknown[] };
  committed: boolean;
  message: string;
}

export type ResourceKind = "data_model" | "workflow" | "page" | "binding";

export interface ResourceCard {
  kind: ResourceKind;
  name: string;
  state: "planning" | "in_progress" | "done";
  index?: number;
  total?: number;
  summary?: string;
}

export interface DesignTemplate {
  id: string;
  name: string;
  vibe?: string;
  provenance?: string;
  palette: { primary: string; accent: string; mode: "light" | "dark"; sidebarBg?: string };
  typography?: { headingFont?: string; bodyFont?: string; scale?: string };
  tokens?: { density?: string; radiusScale?: string; elevation?: string; motionLevel?: string };
  shell?: { frame?: "sidebar" | "topbar" | "rail"; tone?: "light" | "dark" };
}

interface StreamingMessage {
  logs: string[];
  toolCalls: { tool: string; args: string }[];
  filesCreated: string[];
  status: string | null;
  isStreaming: boolean;
  intent: string | null;
  lastMessage: string | null;
  resources: ResourceCard[];
  /** Live tool-call trace from Smith's ReACT loop — rendered as compact
   *  chips above the streaming message so users see WHAT Smith is doing
   *  (read_workflow, list_components, analyze_workflow_values, …) rather
   *  than a blank "Thinking…" indicator. Cleared on startStreaming. */
  smithThoughts: {
    tool: string;
    summary: string;
    /** Event kind. Absent / `"tool"` = normal tool completion chip
     *  (backward-compat with pre-streaming events).
     *  `"reasoning"` = extended-thinking chunk — collapsed italic text.
     *  `"tool_start"` = live chip fired the instant Smith invokes a tool
     *  (present-tense narration; renders before the completion chip).
     *  `"heartbeat"` = ~12s-interval reassurance chip when the turn is
     *  running long — carries `elapsed_s` and `last_tool`. */
    kind?: "reasoning" | "tool" | "tool_start" | "heartbeat";
    /** Full reasoning text when `kind === "reasoning"`. */
    text?: string;
    /** Tool arguments (trimmed by backend) for `kind:"tool_start"` chips. */
    args?: Record<string, unknown>;
    /** Wall-clock seconds since the Smith turn began (heartbeat only). */
    elapsed_s?: number;
    /** Last tool Smith invoked before this heartbeat fired. */
    last_tool?: string;
  }[];
  /** Live planner-v2 + planner-critic events — deterministic validator
   *  hits, per-turn critic verdicts, retries, and best-so-far outcomes.
   *  Rendered as short narrative lines above smithThoughts so the user
   *  sees the Actor-Critic loop happening instead of a silent wait. */
  plannerThoughts: { stage: string; text: string }[];
  /** Journey verifier — post-generation Playwright walk of the planner's
   *  declared journeys. Populated as `journey_result` / `journey_gate`
   *  SSE events arrive. Rendered as a JourneyGateCard chip so the user
   *  sees "app was actually used" instead of just "build succeeded".
   *  Cleared on startStreaming, so a re-run doesn't display stale rows. */
  /** V3 ship verdict — the terminal `ship_report` SSE event emitted by
   *  the pipeline's ship node. One consolidated pass/warn/block verdict
   *  over every verification artifact (delivery gate, security, binding,
   *  quarantine, in-app tests). Rendered as a ShipReportCard. */
  shipReport: {
    verdict: "pass" | "warn" | "block";
    mode: string;
    summary: { criticals: number; errors: number; warnings: number };
    sources: Record<string, {
      present: boolean;
      criticals?: number;
      errors?: number;
      warnings?: number;
      sample?: string[];
    }>;
  } | null;
  journey: {
    results: {
      slug: string;
      name: string;
      status: "passed" | "failed" | "timedOut" | "skipped" | "unknown";
      duration_ms: number;
      failing_step?: string | null;
      failure?: string | null;
    }[];
    summary: {
      mode: "warn" | "strict";
      ok: boolean;
      total: number;
      passed: number;
      failed: number;
      duration_ms: number;
    } | null;
    /** Remediation hints — one per failed journey. Classified by
     *  services/journey_verifier/remediation.py; drives the "what to do
     *  about it" section of the failed-state expansion in JourneyGateCard. */
    hints: {
      journey_slug: string;
      failing_step: string | null;
      likely_cause: string;
      target_seam: string;
      hint: string;
      tags: string[];
    }[];
  };
  /** JV-27 — live signals from the in-flight Verify & Fix run.
   *  Populated from the pubsub events `verify_start`, `verify_progress`,
   *  `verify_fault`, `verify_end`. Consumed by VerifyProgressCard for
   *  the counter, ETA, recent-faults preview, and cancel button. */
  verify: {
    /** Populated by verify_start; needed for POST /verify/{runId}/cancel. */
    runId: string | null;
    /** ms epoch of the first verify_progress event — anchors ETA math. */
    startedAt: number | null;
    progress: { done: number; total: number; currentUrl: string | null } | null;
    /** Bounded ring — keeps the last 5 streaming faults. */
    recentFaults: {
      id: string;
      interaction_id: string;
      classification: string;
      summary: string;
    }[];
    /** Terminal state; drives the chip's grey/green/orange final look. */
    status: "pending" | "running" | "cancelled" | "done" | "failed" | null;
    /** M3 — per-class healed/residual tally emitted by
     *  ``verify_class_progress`` at the end of the V&F 2.0 pass.
     *  ``null`` on runs that predate M3 (or ran without
     *  FORGE_AUTOFIX_V2). The chip renders a per-class strip only
     *  when this is populated. */
    classProgress: {
      healed_by_class: Record<string, number>;
      residual_by_class: Record<string, number>;
    } | null;
    /** SV-STRICT — plain-English narrated payload piggy-backed on the
     *  verify_end event. Populated by the classifier + narrator chain
     *  on the backend (services/verify_narration.py). ``null`` on runs
     *  older than SV-STRICT slices, or when the pipeline couldn't
     *  narrate (empty payload). Rendered by VerifyProgressCard as
     *  sections grouped by W-slot. */
    narrated: {
      narratives: Array<{
        text: string;
        priority: string;
        signature: string;
        w_slot: string;
        component_id: string;
        route: string;
        contract_id?: string | null;
      }>;
      by_w_slot: Record<string, Array<{
        text: string;
        priority: string;
        signature: string;
        w_slot: string;
        component_id: string;
        route: string;
        contract_id?: string | null;
      }>>;
    } | null;
  };
}

export interface CompletionStats {
  totalFiles: number;
  totalTurns: number;
  totalCost: number;
  totalDuration: number;
  totalXp: number;
}

export interface QuestState {
  activePhaseIndex: number;
  completedPhaseIndices: number[];
  totalXp: number;
  isFigma: boolean;
  showCompletionBanner: boolean;
  completionStats: CompletionStats | null;
  /** Wall-clock ms per phaseIndex when that phase became active.
   *  activePhaseIndex=-1 (planning) → key -1. Populated on every
   *  status-transition; consumed by useGenerationProgress for per-
   *  phase partial fill. Reset on startStreaming. */
  phaseStartTimes: Record<number, number>;
  /** Wall-clock ms when startStreaming fired — the overall t=0 for
   *  the generation-progress ring. Cleared to null on reset. */
  streamStartedAt: number | null;
  /** Authoritative progress from the backend `progress` SSE event
   *  (fix for #3/#4/#7). When present, GenerationRing prefers this
   *  over the interpolation baselines. Null until first event. */
  progress: {
    phase: string;
    phaseIndex: number;
    phaseTotal: number;
    phasePercent: number;
    overallPercent: number;
    etaSeconds: number;
    subLabel?: string;
    receivedAt: number;
  } | null;
}

const emptyQuest: QuestState = {
  activePhaseIndex: -1,
  completedPhaseIndices: [],
  totalXp: 0,
  isFigma: false,
  showCompletionBanner: false,
  completionStats: null,
  phaseStartTimes: {},
  streamStartedAt: null,
  progress: null,
};

interface ChatState {
  messages: ChatMessage[];
  streaming: StreamingMessage;
  isGenerating: boolean;
  error: string | null;
  lastCommitHash: string | null;
  lastIntent: string | null;
  planReady: boolean;
  pendingPlan: Record<string, unknown> | null;
  quest: QuestState;
  designTemplates: DesignTemplate[];
  selectedTemplateId: string | null;

  setMessages: (messages: ChatMessage[]) => void;
  addMessage: (message: ChatMessage) => void;
  // SH-1: SelfHeal in-progress → resolved uses the same conversation_id;
  // replace the row in place so the chat swaps the progress card for the
  // terminal card instead of rendering two rows.
  upsertMessage: (message: ChatMessage) => void;
  startStreaming: () => void;
  handleSSEEvent: (event: SSEEvent) => void;
  stopStreaming: () => void;
  setError: (error: string | null) => void;
  reset: () => void;
  dismissCompletionBanner: () => void;
}

const emptyStreaming: StreamingMessage = {
  logs: [],
  toolCalls: [],
  filesCreated: [],
  status: null,
  isStreaming: false,
  intent: null,
  lastMessage: null,
  resources: [],
  smithThoughts: [],
  plannerThoughts: [],
  shipReport: null,
  journey: { results: [], summary: null, hints: [] },
  verify: {
    runId: null,
    startedAt: null,
    progress: null,
    recentFaults: [],
    status: null,
    classProgress: null,
    narrated: null,
  },
};

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  streaming: { ...emptyStreaming },
  isGenerating: false,
  error: null,
  lastCommitHash: null,
  lastIntent: null,
  planReady: false,
  pendingPlan: null,
  quest: { ...emptyQuest },
  designTemplates: [],
  selectedTemplateId: null,

  setMessages: (messages) => set({ messages }),

  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  upsertMessage: (message) =>
    set((state) => {
      const idx = state.messages.findIndex((m) => m.id === message.id);
      if (idx === -1) return { messages: [...state.messages, message] };
      const next = state.messages.slice();
      next[idx] = { ...next[idx], ...message };
      return { messages: next };
    }),

  startStreaming: () => {
    // Initialize office store so agents are ready for incoming events
    useOfficeStore.getState().reset();
    useOfficeStore.getState().initialize();

    const now = Date.now();
    set({
      streaming: { ...emptyStreaming, isStreaming: true },
      isGenerating: true,
      error: null,
      quest: {
        ...emptyQuest,
        streamStartedAt: now,
        // Seed planning phase (activePhaseIndex=-1) start now so the
        // progress ring can compute a partial-fill during planning
        // before the first status transition arrives.
        phaseStartTimes: { [-1]: now },
      },
    });
  },

  handleSSEEvent: (event) =>
    set((state) => {
      const s = { ...state.streaming };
      switch (event.event) {
        case "progress": {
          // Authoritative per-phase progress from the backend
          // (fix for #3/#4/#7 — no more frontend guessing/interpolation).
          const q = { ...state.quest };
          q.progress = {
            phase:          (event.data.phase as string) || "",
            phaseIndex:     Number(event.data.phase_index ?? -1),
            phaseTotal:     Number(event.data.phase_total ?? 0),
            phasePercent:   Number(event.data.phase_percent ?? 0),
            overallPercent: Number(event.data.overall_percent ?? 0),
            etaSeconds:     Number(event.data.eta_seconds ?? 0),
            subLabel:       (event.data.sub_label as string) || undefined,
            receivedAt:     Date.now(),
          };
          return { ...state, streaming: s, quest: q };
        }
        case "status": {
          const statusMsg = (event.data.message as string) || "";
          s.status = statusMsg || null;
          const phaseIdx = detectPhaseIndex(statusMsg);
          const q = { ...state.quest };
          // Task 4 handoff: once a real BUILD phase begins, drop any
          // authoritative planning-progress so the ring hands back to
          // per-phase build interpolation instead of pinning at the last
          // planning value. (The build pipeline emits only `status`, no
          // `progress`, so without this the stale planning `progress` would
          // stay "present" and freeze the ring for the whole build.)
          if (phaseIdx >= 0 && q.progress) {
            q.progress = null;
          }
          if (statusMsg.includes("Generating UI from Figma")) {
            q.isFigma = true;
          }
          if (phaseIdx >= 0 && phaseIdx !== q.activePhaseIndex) {
            // Complete the previous active phase
            if (q.activePhaseIndex >= 0 && !q.completedPhaseIndices.includes(q.activePhaseIndex)) {
              q.completedPhaseIndices = [...q.completedPhaseIndices, q.activePhaseIndex];
              q.totalXp += QUEST_PHASES[q.activePhaseIndex].xp;
            }
            // Record when this new phase became active — the progress
            // ring uses it to compute a real partial fill (not the
            // 50% cold-start heuristic).
            q.phaseStartTimes = { ...q.phaseStartTimes, [phaseIdx]: Date.now() };

            // Bridge: also notify the office store about phase transitions
            const officeStore = useOfficeStore.getState();
            const prevOfficePhase = q.activePhaseIndex >= 0
              ? QUEST_TO_OFFICE_PHASE[QUEST_PHASES[q.activePhaseIndex].id]
              : null;
            const nextOfficePhase = QUEST_TO_OFFICE_PHASE[QUEST_PHASES[phaseIdx].id];
            if (prevOfficePhase) {
              officeStore.handleEvent({
                type: "phase_complete",
                phase: prevOfficePhase,
              });
            }
            if (nextOfficePhase) {
              officeStore.handleEvent({
                type: "phase_start",
                phase: nextOfficePhase,
                message: statusMsg,
              });
            }

            q.activePhaseIndex = phaseIdx;
          }
          return { ...state, streaming: s, quest: q };
        }
        case "log": {
          const logText = event.data.text as string;
          s.logs = [...s.logs, logText];

          // Bridge: detect [Tag] prefix and activate corresponding office agent
          const tagMatch = logText.match(/^\[(\w+)\]/);
          if (tagMatch) {
            const agentId = LOG_TAG_TO_AGENT[tagMatch[1]];
            if (agentId) {
              const officeStore = useOfficeStore.getState();
              const agent = officeStore.agents.get(agentId);
              if (agent) {
                const agentState = agent.getState();
                const bubbleText = logText.slice(tagMatch[0].length).trim().slice(0, 60);
                if (agentState.state === "idle" || agentState.state === "waiting") {
                  const info = AGENT_REGISTRY.find((a) => a.id === agentId);
                  officeStore.handleEvent({
                    type: "agent_start",
                    agent: agentId,
                    room: info?.room ?? "discovery",
                    action: bubbleText || "Working...",
                  });
                } else {
                  officeStore.handleEvent({
                    type: "agent_status",
                    agent: agentId,
                    status: bubbleText || "Working...",
                  });
                }
              }
            }
          }
          break;
        }
        case "tool_call":
          s.toolCalls = [
            ...s.toolCalls,
            {
              tool: event.data.tool as string,
              args: event.data.args as string,
            },
          ];
          break;
        case "file_created":
          s.filesCreated = [...s.filesCreated, event.data.path as string];
          break;
        case "design_templates_ready": {
          const tpls = (event.data.templates as DesignTemplate[]) || [];
          return { ...state, streaming: s, designTemplates: tpls };
        }
        case "design_template_selected": {
          return { ...state, streaming: s, selectedTemplateId: (event.data.id as string) || null };
        }
        case "resource": {
          // Structured deliverable preview (data model / workflow / page / binding).
          const card = event.data as unknown as ResourceCard;
          if (card && card.kind && card.name) {
            // Replace an earlier same-identity card (state advancing), else append.
            const key = `${card.kind}:${card.name}`;
            const existing = s.resources.findIndex(
              (r) => `${r.kind}:${r.name}` === key,
            );
            if (existing >= 0) {
              const next = [...s.resources];
              next[existing] = card;
              s.resources = next;
            } else {
              s.resources = [...s.resources, card];
            }
          }
          break;
        }
        case "intent":
          s.intent = (event.data.intent as string) || null;
          return { ...state, streaming: s, lastIntent: s.intent };
        case "message": {
          // Direct text message from the agent (e.g., clarification, explanation)
          const msgText = (event.data.text as string) || "";
          s.lastMessage = msgText || null;

          // Bridge: detect [Tag] prefix and activate corresponding office agent
          // (same logic as "log" events, since some agents stream as messages)
          const msgTagMatch = msgText.match(/^\[(\w+)\]/);
          if (msgTagMatch) {
            const agentId = LOG_TAG_TO_AGENT[msgTagMatch[1]];
            if (agentId) {
              const officeStore = useOfficeStore.getState();
              const agent = officeStore.agents.get(agentId);
              if (agent) {
                const agentState = agent.getState();
                const bubbleText = msgText.slice(msgTagMatch[0].length).trim().slice(0, 60);
                if (agentState.state === "idle" || agentState.state === "waiting") {
                  const info = AGENT_REGISTRY.find((a) => a.id === agentId);
                  officeStore.handleEvent({
                    type: "agent_start",
                    agent: agentId,
                    room: info?.room ?? "discovery",
                    action: bubbleText || "Working...",
                  });
                } else {
                  officeStore.handleEvent({
                    type: "agent_status",
                    agent: agentId,
                    status: bubbleText || "Working...",
                  });
                }
              }
            }
          }

          return {
            ...state,
            streaming: s,
            messages: [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: msgText,
                message_type: "chat" as const,
                metadata: { intent: s.intent },
                created_at: new Date().toISOString(),
              },
            ],
          };
        }
        case "plan_ready": {
          const plan = (event.data.plan as Record<string, unknown>) || null;
          // Replace the last assistant message (which contains raw plan text)
          // with a plan-type message showing the structured PlanCard
          const updatedMessages = [...state.messages];
          const lastAssistantIdx = updatedMessages.findLastIndex(
            (m) => m.role === "assistant",
          );
          if (lastAssistantIdx >= 0) {
            updatedMessages[lastAssistantIdx] = {
              ...updatedMessages[lastAssistantIdx],
              message_type: "plan" as const,
              metadata: {
                ...updatedMessages[lastAssistantIdx].metadata,
                plan,
                intent: "PLAN",
              },
            };
          } else {
            // Fallback: create a new plan message
            updatedMessages.push({
              id: crypto.randomUUID(),
              project_id: "",
              role: "assistant" as const,
              content: "Here's the plan for your application:",
              message_type: "plan" as const,
              metadata: { plan, intent: "PLAN" },
              created_at: new Date().toISOString(),
            });
          }
          return {
            ...state,
            streaming: s,
            planReady: true,
            pendingPlan: plan,
            messages: updatedMessages,
          };
        }
        case "discovery_started": {
          // Backend started the domain-research agent after plan approval.
          // Just surface a status; the discovery_complete event below brings
          // the dossier and renders the DiscoveryCard.
          s.status = (event.data.message as string) || "Researching your domain…";
          return { ...state, streaming: s };
        }
        case "discovery_complete": {
          // Append a new assistant message of type "discovery" carrying the
          // dossier — ChatMessage renders DiscoveryCard from metadata.discovery.
          const discovery =
            (event.data.discovery as Record<string, unknown>) ||
            (event.data as Record<string, unknown>);
          const newMessage: ChatMessage = {
            id: crypto.randomUUID(),
            project_id: "",
            role: "assistant" as const,
            content:
              "I researched your domain. Review the dossier and tweak anything before I dispatch the build.",
            message_type: "discovery" as const,
            metadata: { discovery, intent: "DISCOVERY" },
            created_at: new Date().toISOString(),
          };
          return {
            ...state,
            streaming: s,
            messages: [...state.messages, newMessage],
          };
        }
        case "discovery_approval_needed": {
          // Marker that backend has saved pending_discovery.json and is
          // awaiting [APPROVE_DISCOVERY]. No UI mutation needed — the
          // DiscoveryCard appended above already exposes the approve button.
          return state;
        }
        case "discovery_approved": {
          // Mark the latest discovery message as approved so the card can
          // dim its CTA buttons. Backend emits this right before dispatching
          // the rest of the pipeline.
          const updated = [...state.messages];
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].message_type === "discovery") {
              updated[i] = {
                ...updated[i],
                metadata: { ...updated[i].metadata, approved: true },
              };
              break;
            }
          }
          return { ...state, streaming: s, messages: updated };
        }
        case "planner_thought": {
          // Live planner-v2 + planner-critic events (structural
          // validation hits, per-turn critic verdicts, retries).
          // Rendered as short narrative lines so the user sees the
          // Actor-Critic loop happening instead of a blank spinner.
          const data = event.data as { stage?: string; text?: string };
          const stage = String(data?.stage || "").trim();
          const text = String(data?.text || "").trim();
          if (!text) return { ...state, streaming: s };
          return {
            ...state,
            streaming: {
              ...s,
              plannerThoughts: [
                ...s.plannerThoughts,
                { stage, text },
              ],
            },
          };
        }
        case "smith_thought": {
          // Live tool-call trace from Smith's ReACT loop. Each read-only
          // tool call ("recall", "read_workflow", "list_components", …)
          // arrives as a compact {tool, summary} pair BEFORE Smith's final
          // message/fix_proposal event. Rendered as chips in SSEStatusBar so
          // the user sees WHAT Smith is doing while thinking, not a blank
          // spinner. Cleared on stopStreaming.
          //
          // Extended-thinking chunks arrive as {kind:"reasoning", text},
          // with no `tool` field — they represent Smith's internal
          // reasoning stream and render as collapsible italic text.
          const data = event.data as {
            tool?: string;
            summary?: string;
            kind?: "reasoning" | "tool" | "tool_start" | "heartbeat";
            text?: string;
            args?: Record<string, unknown>;
            elapsed_s?: number;
            last_tool?: string;
          };
          if (data?.kind === "reasoning") {
            const text = String(data?.text || "");
            if (!text.trim()) return { ...state, streaming: s };
            return {
              ...state,
              streaming: {
                ...s,
                smithThoughts: [
                  ...s.smithThoughts,
                  { tool: "", summary: "", kind: "reasoning", text },
                ],
              },
            };
          }
          if (data?.kind === "tool_start") {
            // Live "about to run" chip so the chat has visible motion
            // BEFORE the tool completes. Present-tense narration ("Reading
            // login.json…"). Rendered via `narrateSmithThought` on the
            // display side using the existing tool→phrase table.
            const tool = String(data?.tool || "").trim();
            if (!tool) return { ...state, streaming: s };
            return {
              ...state,
              streaming: {
                ...s,
                smithThoughts: [
                  ...s.smithThoughts,
                  {
                    tool,
                    summary: "",
                    kind: "tool_start",
                    args: data?.args || {},
                  },
                ],
              },
            };
          }
          if (data?.kind === "heartbeat") {
            // Backend fires this every ~12s of silence so the chat never
            // stalls. Renders as a single reassurance chip; last_tool
            // tells the user WHICH step is slow.
            const elapsed = Math.max(0, Number(data?.elapsed_s) || 0);
            const lastTool = String(data?.last_tool || "").trim();
            return {
              ...state,
              streaming: {
                ...s,
                smithThoughts: [
                  ...s.smithThoughts,
                  {
                    tool: "",
                    summary: "",
                    kind: "heartbeat",
                    elapsed_s: elapsed,
                    last_tool: lastTool,
                  },
                ],
              },
            };
          }
          const tool = String(data?.tool || "").trim();
          if (!tool) return { ...state, streaming: s };
          return {
            ...state,
            streaming: {
              ...s,
              smithThoughts: [
                ...s.smithThoughts,
                { tool, summary: String(data?.summary || "") },
              ],
            },
          };
        }
        case "ship_report": {
          // Terminal consolidated verdict from the pipeline's ship node
          // (services/ship_report.py). One event per build; latest wins.
          const d = event.data as NonNullable<StreamingMessage["shipReport"]>;
          if (!d || !d.verdict) return state;
          return { ...state, streaming: { ...s, shipReport: d } };
        }
        case "journey_result": {
          // Post-generation Playwright walk of a single planner-declared
          // journey. One event per journey; the JourneyGateCard chip
          // renders these as pass/fail rows, and clicking a failed row
          // will (eventually) open the Playwright trace viewer. Emitted
          // by services/journey_gate.py.
          const d = event.data as {
            slug?: string; name?: string; status?: string; duration_ms?: number;
            failing_step?: string | null; failure?: string | null;
          };
          const results = [
            ...s.journey.results,
            {
              slug: String(d?.slug || ""),
              name: String(d?.name || d?.slug || ""),
              status: (d?.status as "passed" | "failed" | "timedOut" | "skipped") || "unknown",
              duration_ms: Number(d?.duration_ms || 0),
              failing_step: d?.failing_step || null,
              failure: d?.failure || null,
            },
          ];
          return { ...state, streaming: { ...s, journey: { ...s.journey, results } } };
        }
        case "journey_gate": {
          // Terminal summary from the journey gate. Locks the JourneyGateCard
          // into its final state (green/red) with counts. If mode was
          // "strict" and any journey failed, an "error" event follows this
          // one — handled by the existing error branch below.
          const d = event.data as {
            mode?: string; ok?: boolean; total?: number; passed?: number;
            failed?: number; duration_ms?: number;
          };
          return {
            ...state,
            streaming: {
              ...s,
              journey: {
                ...s.journey,
                summary: {
                  mode: (d?.mode as "warn" | "strict") || "warn",
                  ok: Boolean(d?.ok),
                  total: Number(d?.total || 0),
                  passed: Number(d?.passed || 0),
                  failed: Number(d?.failed || 0),
                  duration_ms: Number(d?.duration_ms || 0),
                },
              },
            },
          };
        }
        case "journey_remediation": {
          // Structured hint from services/journey_verifier/remediation.py —
          // one event per failed journey with a classified target_seam +
          // human-readable fix suggestion. Appended so the JourneyGateCard
          // can render the fix guidance in its expanded state.
          const d = event.data as {
            journey_slug?: string; failing_step?: string | null;
            likely_cause?: string; target_seam?: string; hint?: string;
            tags?: string[];
          };
          return {
            ...state,
            streaming: {
              ...s,
              journey: {
                ...s.journey,
                hints: [
                  ...s.journey.hints,
                  {
                    journey_slug: String(d?.journey_slug || ""),
                    failing_step: d?.failing_step || null,
                    likely_cause: String(d?.likely_cause || ""),
                    target_seam: String(d?.target_seam || "unknown"),
                    hint: String(d?.hint || ""),
                    tags: Array.isArray(d?.tags) ? d.tags.map(String) : [],
                  },
                ],
              },
            },
          };
        }
        case "verify_start": {
          // JV-27 — a new Verify & Fix run just started. Reset the live
          // verify slice so a previous run's counters/faults don't
          // linger on the chip.
          const d = event.data as { run_id?: string };
          return {
            ...state,
            streaming: {
              ...s,
              verify: {
                runId: d?.run_id ? String(d.run_id) : null,
                startedAt: null,          // stamped on first progress
                progress: null,
                recentFaults: [],
                status: "running",
                classProgress: null,
                narrated: null,
              },
              // Also reset journey state so run N+1 doesn't inherit
              // run N's summary/results (JV-16 comment on verifyActive).
              journey: { results: [], summary: null, hints: [] },
              shipReport: null,
            },
          };
        }
        case "verify_progress": {
          // JV-27/#1 — per-poll counter update from the sidecar.
          const d = event.data as {
            done?: number; total?: number; currentUrl?: string | null;
          };
          const done = Number(d?.done ?? 0);
          const total = Number(d?.total ?? 0);
          const startedAt = s.verify.startedAt ?? Date.now();
          return {
            ...state,
            streaming: {
              ...s,
              verify: {
                ...s.verify,
                startedAt,
                progress: {
                  done,
                  total,
                  currentUrl: d?.currentUrl ? String(d.currentUrl) : null,
                },
                status: s.verify.status ?? "running",
              },
            },
          };
        }
        case "verify_fault": {
          // JV-27/#3 — streaming fault preview, bounded ring of 5.
          const d = event.data as {
            id?: string; interaction_id?: string;
            classification?: string; summary?: string;
          };
          const fault = {
            id: String(d?.id || `${Date.now()}`),
            interaction_id: String(d?.interaction_id || ""),
            classification: String(d?.classification || "unclassified"),
            summary: String(d?.summary || ""),
          };
          if (s.verify.recentFaults.some((f) => f.id === fault.id)) {
            return state;   // de-dup safety net
          }
          const nextRing = [...s.verify.recentFaults, fault].slice(-5);
          return {
            ...state,
            streaming: {
              ...s,
              verify: { ...s.verify, recentFaults: nextRing },
            },
          };
        }
        case "verify_end": {
          // JV-27/#5 — terminal marker. Update status and fire a global
          // toast so users who navigated away still see completion.
          // ChatPanel also synthesizes a journey_gate from this payload
          // for the chip's done-state; we ONLY handle verify-slice
          // status + toast here.
          const d = event.data as {
            run_id?: string; status?: string;
            interactions_passed?: number; interactions_run?: number;
            faults_count?: number;
            narrated?: {
              narratives?: Array<{
                text: string; priority: string; signature: string;
                w_slot: string; component_id: string; route: string;
                contract_id?: string | null;
              }>;
              by_w_slot?: Record<string, Array<{
                text: string; priority: string; signature: string;
                w_slot: string; component_id: string; route: string;
                contract_id?: string | null;
              }>>;
            };
          };
          const status = String(d?.status || "done") as
            | "cancelled" | "done" | "failed";
          const passed = Number(d?.interactions_passed ?? 0);
          const total = Number(
            d?.interactions_run ?? (s.verify.progress?.total ?? 0),
          );
          const faults = Number(d?.faults_count ?? 0);
          // Fire once — de-dupe on runId so a cancel+ eventual bg-task
          // verify_end don't produce two toasts for the same run.
          const alreadyFiredRun = s.verify.runId
            && s.verify.status
            && (s.verify.status === "cancelled"
                || s.verify.status === "done"
                || s.verify.status === "failed");
          if (!alreadyFiredRun) {
            try {
              const label = status === "cancelled"
                ? "Verify cancelled"
                : status === "failed"
                ? "Verify failed"
                : "Verify done";
              const body = status === "cancelled"
                ? "Run stopped."
                : `${passed}/${total} passed · ${faults} fault${faults === 1 ? "" : "s"}`;
              const scrollToChip = () => {
                const el = document.querySelector(
                  "[data-verify-chip]",
                ) as HTMLElement | null;
                if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
              };
              if (status === "done" && faults === 0) {
                toast.success(`${label} · ${body}`, {
                  action: { label: "View", onClick: scrollToChip },
                });
              } else if (status === "cancelled") {
                toast(`${label} · ${body}`, {
                  action: { label: "View", onClick: scrollToChip },
                });
              } else {
                toast.warning(`${label} · ${body}`, {
                  action: { label: "View", onClick: scrollToChip },
                });
              }
            } catch { /* toast unavailable, silent */ }
          }
          return {
            ...state,
            streaming: {
              ...s,
              verify: {
                ...s.verify,
                status,
                // Clamp progress to total on done so the fill bar reads 100%.
                progress: s.verify.progress
                  ? { ...s.verify.progress, done: s.verify.progress.total || s.verify.progress.done }
                  : null,
                // SV-STRICT-3b: piggy-backed narrated payload. Only set
                // when the backend supplied it (non-empty). Older runs
                // simply don't populate it and the NarratedFaults
                // section stays hidden.
                narrated: (d?.narrated
                  && (Array.isArray(d.narrated.narratives)
                      && d.narrated.narratives.length > 0))
                  ? {
                      narratives: d.narrated.narratives!,
                      by_w_slot: d.narrated.by_w_slot || {},
                    }
                  : s.verify.narrated,
              },
            },
          };
        }
        case "verify_class_progress": {
          // V&F 2.0 M3 — per-class healed/residual tally emitted after
          // `_run_faults_through_classifier` completes. Populates the
          // classProgress slice the chip reads for its per-class strip.
          const d = event.data as {
            healed_by_class?: Record<string, number>;
            residual_by_class?: Record<string, number>;
          };
          const healed = (d?.healed_by_class && typeof d.healed_by_class === "object")
            ? d.healed_by_class : {};
          const residual = (d?.residual_by_class && typeof d.residual_by_class === "object")
            ? d.residual_by_class : {};
          return {
            ...state,
            streaming: {
              ...s,
              verify: {
                ...s.verify,
                classProgress: {
                  healed_by_class: healed,
                  residual_by_class: residual,
                },
              },
            },
          };
        }
        case "critic_start":
        case "critic_turn_start":
        case "critic_verdict":
        case "critic_approved":
        case "critic_rejected":
        case "critic_revising":
        case "critic_capped":
        case "critic_retry_error":
        // Streaming progress from the planning-phase LLM calls (see
        // backend/services/streaming_llm.py). Emitted by:
        //   • services/discovery_narrative.expand_prompt_to_narrative
        //   • agents/planner.run_planner_oneshot
        // Each stage sends _started once, _chunk on a throttle (~400ms
        // or 800 chars), and _complete once. Renders as chips in the
        // SSEStatusBar so the ~4 minutes of pre-plan LLM work isn't a
        // silent void.
        case "narrative_expansion_started":
        case "narrative_expansion_chunk":
        case "narrative_expansion_complete":
        case "planner_call_started":
        case "planner_call_chunk":
        case "planner_call_complete":
        // Semantic-progress events layered on top of the raw byte-count
        // stream. Each fires the FIRST time the planner writes a
        // landmark into the streaming JSON (e.g. entering the
        // ``"data_models":`` section, authoring an entity named
        // ``Candidate``). Rendered as their own chip so the user sees
        // "Defining entities…" / "+ Candidate" / "+ Vacancy" instead
        // of a wall of "streaming X chars".
        case "planner_call_semantic":
        // Task 3 — decomposition path signals. When smith-arch routes
        // through skeleton→parallel-units instead of one-shot, the
        // chip stream carries these instead of planner_call_* events:
        // one start + one per-page unit_authored + one complete.
        case "planner_decompose_start":
        case "planner_decompose_complete":
        case "planner_decompose_error":
        case "unit_authored": {
          // Actor-Critic loop progress from the Smith planner (see backend
          // services/smith_agent_adapters.py::orchestrate_planner).
          // Rendered as chips in the SSEStatusBar so the user sees the
          // critic verdict-by-verdict — turn 1 (revise, 3 blockers) →
          // turn 2 (revise, 1) → turn 3 (approve) — instead of a black-box
          // wait during planning.
          const data = event.data as {
            text?: string;
            turn?: number;
            verdict?: string;
            blockers?: number;
            important?: number;
            domain?: string;
          };
          const text = String(data?.text || event.event);
          return {
            ...state,
            streaming: {
              ...s,
              smithThoughts: [
                ...s.smithThoughts,
                {
                  tool: event.event,
                  summary: text,
                },
              ],
            },
          };
        }
        case "smith_narration": {
          // Smith speaks in architect voice bracketing the generator run
          // (see backend services/smith_agent_adapters.py::orchestrate_generation).
          // OPEN: {stage: "generation_handoff", prose: "Kicking off the build…"}
          // CLOSE: {stage: "generation_complete", prose: "…what landed", files_count, error}
          // Render as a regular assistant speech bubble; metadata lets the
          // UI style it distinctly (e.g. italics, small "Smith" affordance).
          const data = event.data as {
            stage?: string;
            prose?: string;
            files_count?: number;
            error?: string | null;
          };
          const prose = String(data?.prose || "").trim();
          if (!prose) return { ...state, streaming: s };
          return {
            ...state,
            streaming: s,
            messages: [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: prose,
                message_type: "chat" as const,
                metadata: {
                  smithNarration: {
                    stage: String(data?.stage || "generation"),
                    filesCount: data?.files_count,
                    error: data?.error ?? null,
                  },
                  intent: "smith_narration",
                },
                created_at: new Date().toISOString(),
              },
            ],
          };
        }
        case "fix_proposal": {
          // Conversational fix-assistant: a diagnosis + change preview + an
          // [APPLY_FIX] chip. Carried on metadata so ChatMessage renders it as
          // a FixProposalCard (mirrors the plan/discovery card pattern).
          const proposal = event.data as unknown as FixProposal;
          const explanation =
            proposal?.diagnosis?.explanation ||
            "I found a likely cause and prepared a fix.";
          return {
            ...state,
            streaming: s,
            messages: [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: explanation,
                message_type: "chat" as const,
                metadata: { fixProposal: proposal, intent: "FIX" },
                created_at: new Date().toISOString(),
              },
            ],
          };
        }
        case "fix_applied": {
          // Result of an [APPLY_FIX]: resolved ✓ or still-needs-attention ✗.
          const result = event.data as unknown as FixResult;
          // Mark the most recent proposal card as applied so its button dims.
          const withAppliedMark = [...state.messages];
          for (let i = withAppliedMark.length - 1; i >= 0; i--) {
            if (withAppliedMark[i].metadata?.fixProposal) {
              withAppliedMark[i] = {
                ...withAppliedMark[i],
                metadata: { ...withAppliedMark[i].metadata, fixApplied: true },
              };
              break;
            }
          }
          return {
            ...state,
            streaming: s,
            messages: [
              ...withAppliedMark,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: result?.message || "Fix applied.",
                message_type: "chat" as const,
                metadata: { fixResult: result, intent: "FIX" },
                created_at: new Date().toISOString(),
              },
            ],
          };
        }
        case "agent_result": {
          // Store aggregated stats from the final agent_result for completion banner
          const ar = event.data as Record<string, unknown>;
          const q = { ...state.quest };
          q.completionStats = {
            totalFiles: (ar.num_files as number) || state.streaming.filesCreated.length,
            totalTurns: (ar.num_turns as number) || 0,
            totalCost: (ar.cost_usd as number) || 0,
            totalDuration: (ar.duration_ms as number) || 0,
            totalXp: 0, // filled on complete
          };
          return { ...state, streaming: s, quest: q };
        }
        case "office": {
          // Forward office events to the virtual office store
          const officeEvent = event.data as unknown as OfficeEvent;
          useOfficeStore.getState().handleEvent(officeEvent);
          break;
        }
        case "page_iter_done": {
          const d = event.data as Record<string, any>;
          const delta = d.score_delta as number | undefined;
          const deltaStr =
            delta !== undefined && delta !== 0
              ? ` ${delta > 0 ? "+" : ""}${delta.toFixed(1)}`
              : "";
          const passStr = d.pass ? " ✓ pass" : "";
          return {
            ...state,
            streaming: s,
            messages: [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: `↳ **${d.page}** — iter ${d.iter} · score **${(d.score as number).toFixed(1)}**${deltaStr}${passStr}`,
                message_type: "chat" as const,
                metadata: { intent: "fidelity_loop" },
                created_at: new Date().toISOString(),
              },
            ],
          };
        }
        case "page_complete":
          // Deduplicated — page_iter_done already covered it
          break;
        case "page_skipped": {
          const d = event.data as Record<string, any>;
          return {
            ...state,
            streaming: s,
            messages: [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: `⚠ **${d.page}** skipped — ${d.reason}`,
                message_type: "chat" as const,
                metadata: { intent: "fidelity_loop" },
                created_at: new Date().toISOString(),
              },
            ],
          };
        }
        case "phase_start":
        case "phase_warning": {
          // Pipeline phase transitions during generation — schema agent,
          // api agent, page agent (per-page), seed, qa, validate, index.
          // Frontend was silently dropping these; render as chips in the
          // SSE status bar so users see component-by-component progress.
          const d = event.data as {
            phase?: string;
            page?: string;
            message?: string;
            text?: string;
          };
          const phase = String(d?.phase || "").trim();
          const page = d?.page ? ` (${d.page})` : "";
          const detail = String(d?.message || d?.text || "").trim();
          const label = phase
            ? `${phase}${page}${detail ? ` — ${detail}` : ""}`
            : detail;
          if (!label) return { ...state, streaming: s };
          return {
            ...state,
            streaming: {
              ...s,
              smithThoughts: [
                ...s.smithThoughts,
                { tool: event.event, summary: label },
              ],
            },
          };
        }
        case "phase_complete": {
          // Full phase-complete chip (all phases, not just fidelity).
          const d = event.data as {
            phase?: string;
            page?: string;
            passed?: number;
            failed?: number;
            skipped?: number;
            avg_score?: number;
            total_cost_usd?: number;
            wall_clock_s?: number;
          };
          const phase = String(d?.phase || "").trim();
          if (phase && phase !== "fidelity_loop") {
            const bits: string[] = [];
            if (d.page) bits.push(String(d.page));
            if (d.wall_clock_s != null) bits.push(`${d.wall_clock_s.toFixed(0)}s`);
            if (d.total_cost_usd != null) bits.push(`$${d.total_cost_usd.toFixed(2)}`);
            const suffix = bits.length ? ` — ${bits.join(" · ")}` : "";
            return {
              ...state,
              streaming: {
                ...s,
                smithThoughts: [
                  ...s.smithThoughts,
                  { tool: "phase_complete", summary: `✓ ${phase}${suffix}` },
                ],
              },
            };
          }
          // Original fidelity_loop path — full inline message.
          if (phase !== "fidelity_loop") break;
          const costStr =
            d.total_cost_usd != null
              ? ` · $${(d.total_cost_usd as number).toFixed(2)}`
              : "";
          const wallStr =
            d.wall_clock_s != null
              ? ` · ${(d.wall_clock_s as number).toFixed(0)}s`
              : "";
          return {
            ...state,
            streaming: s,
            messages: [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: `✓ **Fidelity check complete** — ${d.passed} passed · ${d.failed} flagged · ${d.skipped} skipped (avg ${d.avg_score})${costStr}${wallStr}`,
                message_type: "chat" as const,
                metadata: { intent: "fidelity_loop" },
                created_at: new Date().toISOString(),
              },
            ],
          };
        }
        case "navigate":
          // Navigation intent — handled by UI layer
          break;
        case "undo_complete":
          return {
            ...state,
            streaming: s,
            lastCommitHash: (event.data.commit_hash as string) || null,
            messages: [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: "Reverted the last change.",
                message_type: "chat" as const,
                metadata: {
                  commit_hash: event.data.commit_hash,
                  intent: "UNDO",
                },
                created_at: new Date().toISOString(),
              },
            ],
          };
        case "error": {
          const errorMsg = (event.data.message as string) || "An error occurred";

          // Detect budget/credit errors and trigger office protest
          if (isBudgetError(errorMsg)) {
            triggerOfficeProtest(errorMsg);
          }

          return {
            ...state,
            streaming: { ...s, isStreaming: false },
            isGenerating: false,
            error: errorMsg,
          };
        }
        case "smith_needs_user": {
          // Architect asks the user to pick between options (spec §11):
          // retry / rollback / abandon / etc. Renders as NeedsUserCard.
          const d = event.data as Record<string, unknown>;
          const answer = (d.answer as string) || (d.message as string) || "I need a decision from you.";
          const options = Array.isArray(d.options) ? (d.options as string[]) : [];
          if (options.length === 0) {
            // Malformed event — fall back to a plain assistant message
            // so at least the question surfaces (never silently drop).
            return {
              ...state,
              streaming: s,
              messages: [
                ...state.messages,
                {
                  id: crypto.randomUUID(),
                  project_id: "",
                  role: "assistant" as const,
                  content: answer,
                  message_type: "chat" as const,
                  metadata: { intent: "needs_user_malformed" },
                  created_at: new Date().toISOString(),
                },
              ],
            };
          }
          return {
            ...state,
            streaming: s,
            messages: [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: answer,
                message_type: "chat" as const,
                metadata: {
                  intent: "needs_user",
                  needsUser: {
                    answer,
                    options,
                    diff_summary: d.diff_summary as string | undefined,
                    touched_paths: Array.isArray(d.touched_paths)
                      ? (d.touched_paths as string[])
                      : undefined,
                  },
                },
                created_at: new Date().toISOString(),
              },
            ],
          };
        }
        case "smith_error": {
          // A specific failure from Smith (not the generic `error` event).
          // Render as an assistant chat message with an error intent so
          // it's visually distinct + never dropped silently.
          const d = event.data as Record<string, unknown>;
          const msg = (d.message as string) || (d.error as string) || "Smith reported an error but didn't say what.";
          return {
            ...state,
            streaming: s,
            messages: [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: `⚠️ ${msg}`,
                message_type: "chat" as const,
                metadata: { intent: "smith_error" },
                created_at: new Date().toISOString(),
              },
            ],
          };
        }
        case "answer": {
          // Direct architect answer (no fix / no plan). Was dropped
          // silently before; now renders as an assistant reply.
          const d = event.data as Record<string, unknown>;
          const text = (d.text as string) || (d.answer as string) || "";
          if (!text.trim()) return { ...state, streaming: s };
          return {
            ...state,
            streaming: s,
            messages: [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: text,
                message_type: "chat" as const,
                metadata: { intent: "answer" },
                created_at: new Date().toISOString(),
              },
            ],
          };
        }
        case "question": {
          // Architect wants a follow-up from the user (§5.2 ask_user).
          // Rendered as a normal assistant message; the user's next
          // typed message is the response.
          const d = event.data as Record<string, unknown>;
          const text = (d.text as string) || (d.question as string) || "";
          if (!text.trim()) return { ...state, streaming: s };
          return {
            ...state,
            streaming: s,
            messages: [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: text,
                message_type: "chat" as const,
                metadata: { intent: "question" },
                created_at: new Date().toISOString(),
              },
            ],
          };
        }
        case "handoff": {
          // Architect handed off to another agent (planner/refiner/etc).
          // Was dropped; surface the message + kind so the user sees WHY
          // Smith stepped aside.
          const d = event.data as Record<string, unknown>;
          const kind = (d.kind as string) || "?";
          const msg = (d.message as string) || `Handed off to ${kind}.`;
          return {
            ...state,
            streaming: s,
            messages: [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: `→ Handed to **${kind}**: ${msg}`,
                message_type: "chat" as const,
                metadata: { intent: "handoff" },
                created_at: new Date().toISOString(),
              },
            ],
          };
        }
        case "apply_start": {
          // The apply POST is running. Just update streaming status —
          // FixProposalCard's spinner is driven by its own local
          // `applying` state, so no per-card message needed here.
          s.status = "Applying fix…";
          return { ...state, streaming: s };
        }
        case "apply_end": {
          s.status = null;
          return { ...state, streaming: s };
        }
        case "complete":
        case "refine_complete": {
          // Honesty fix: previous code injected "Done." whenever no
          // assistant reply arrived — indistinguishable from a real
          // success. Now: if the backend reports files touched or a
          // commit hash, surface *what actually happened* using the
          // ground truth data. Otherwise say so plainly.
          const lastMsg = state.messages[state.messages.length - 1];
          const needsFallback = !lastMsg || lastMsg.role === "user";
          // Post-build action chips (Seed demo data · Validate & Repair) ride the
          // complete event's `actions`; attach them to the message ActionButtons reads.
          const postActions = Array.isArray(event.data.actions)
            ? event.data.actions
            : undefined;
          // Ground-truth committed files (M4/D-phase: backend can attach
          // these to `complete` from `git diff-tree` against the commit;
          // falls back to SSE-reported filesCreated when absent).
          const committedFiles = Array.isArray(event.data.committed_files)
            ? (event.data.committed_files as string[])
            : undefined;
          const commitHash = event.data.commit_hash as string | undefined;
          // JV-14: next_steps ride the `complete` SSE now so the synthetic
          // fallback message renders the chip panel (was being dropped
          // because the DB re-fetch happens after this handler mints its
          // own message).
          const nextSteps = Array.isArray(event.data.next_steps)
            ? event.data.next_steps
            : undefined;
          let completedMessages;
          if (needsFallback) {
            // Build an honest summary from real signals, in order of
            // trustworthiness: committed_files > filesCreated > empty.
            let fallbackContent: string;
            if (committedFiles && committedFiles.length > 0) {
              const preview = committedFiles.slice(0, 4).map((p) => `\`${p}\``).join(", ");
              const more = committedFiles.length > 4 ? ` and ${committedFiles.length - 4} more` : "";
              fallbackContent = `Committed ${committedFiles.length} file(s): ${preview}${more}.`;
            } else if (commitHash) {
              fallbackContent = `Committed at \`${commitHash.slice(0, 7)}\`.`;
            } else if (s.filesCreated.length > 0) {
              fallbackContent = `Generation reported ${s.filesCreated.length} file(s) touched, but no commit landed. Check history before assuming.`;
            } else {
              fallbackContent = "Turn ended without producing changes or a response. Nothing to display — try rephrasing your ask.";
            }
            completedMessages = [
              ...state.messages,
              {
                id: crypto.randomUUID(),
                project_id: "",
                role: "assistant" as const,
                content: fallbackContent,
                message_type: "chat" as const,
                metadata: {
                  intent: (event.data.intent as string) || s.intent,
                  commit_hash: commitHash,
                  ...(committedFiles ? { committed_files: committedFiles } : {}),
                  ...(postActions ? { actions: postActions } : {}),
                  ...(nextSteps ? { next_steps: nextSteps } : {}),
                },
                created_at: new Date().toISOString(),
              },
            ];
          } else if (postActions || nextSteps) {
            // Attach the chips to the most recent assistant message.
            let attached = false;
            completedMessages = [...state.messages].reverse().map((m) => {
              if (!attached && m.role === "assistant") {
                attached = true;
                return {
                  ...m,
                  metadata: {
                    ...m.metadata,
                    ...(postActions ? { actions: postActions } : {}),
                    ...(nextSteps ? { next_steps: nextSteps } : {}),
                  },
                };
              }
              return m;
            }).reverse();
          } else {
            completedMessages = state.messages;
          }

          // Bridge: notify office store about build success (only for real builds)
          if (state.streaming.filesCreated.length > 0) {
            useOfficeStore.getState().handleEvent({
              type: "build_success",
              total_files: state.streaming.filesCreated.length,
            });
          }

          // Finalize quest state
          const qComplete = { ...state.quest };
          if (qComplete.activePhaseIndex >= 0) {
            // Mark the last active phase as complete
            if (!qComplete.completedPhaseIndices.includes(qComplete.activePhaseIndex)) {
              qComplete.completedPhaseIndices = [...qComplete.completedPhaseIndices, qComplete.activePhaseIndex];
              qComplete.totalXp += QUEST_PHASES[qComplete.activePhaseIndex].xp;
            }
            // Set completion banner
            qComplete.showCompletionBanner = true;
            if (qComplete.completionStats) {
              qComplete.completionStats = {
                ...qComplete.completionStats,
                totalFiles: qComplete.completionStats.totalFiles || s.filesCreated.length,
                totalXp: qComplete.totalXp,
              };
            } else {
              qComplete.completionStats = {
                totalFiles: s.filesCreated.length,
                totalTurns: 0,
                totalCost: 0,
                totalDuration: 0,
                totalXp: qComplete.totalXp,
              };
            }
          }

          return {
            ...state,
            streaming: { ...s, isStreaming: false },
            isGenerating: false,
            lastCommitHash:
              (event.data.commit_hash as string) || state.lastCommitHash,
            lastIntent: (event.data.intent as string) || state.lastIntent,
            messages: completedMessages,
            quest: qComplete,
          };
        }
      }
      return { ...state, streaming: s };
    }),

  stopStreaming: () =>
    set((state) => ({
      streaming: { ...state.streaming, isStreaming: false },
      isGenerating: false,
    })),

  setError: (error) => {
    if (error && isBudgetError(error)) {
      triggerOfficeProtest(error);
    }
    set({ error });
  },

  dismissCompletionBanner: () =>
    set((state) => ({
      quest: { ...state.quest, showCompletionBanner: false },
    })),

  reset: () => {
    useOfficeStore.getState().reset();
    set({
      messages: [],
      streaming: { ...emptyStreaming },
      isGenerating: false,
      error: null,
      lastCommitHash: null,
      lastIntent: null,
      planReady: false,
      pendingPlan: null,
      quest: { ...emptyQuest },
      designTemplates: [],
      selectedTemplateId: null,
    });
  },
}));

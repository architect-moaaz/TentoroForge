"use client";

import { useEffect, useRef, useState } from "react";
import {
  FileCode2,
  Wrench,
  Brain,
  Minimize2,
  Building2,
  AlertTriangle,
  CheckCircle2,
  X,
} from "lucide-react";
import { createPortal } from "react-dom";
import { ChatMessage } from "./ChatMessage";
import { narrateSmithThought, narrateSmithToolStart, narrateSmithHeartbeat } from "./smithNarration";
import { VirtualOffice } from "@/components/virtual-office";
import type { ChatMessage as ChatMessageType } from "@/types/project";
import type { QuestState, ResourceCard } from "@/stores/chat";
import { useChatStore, isBudgetError } from "@/stores/chat";
import { useFlavorText } from "@/lib/flavor-text";
import { DeliverablesPanel } from "@/components/generation/DeliverablesPanel";
import { TemplateGallery } from "@/components/generation/TemplateGallery";
import { GenerationRing } from "./GenerationRing";
import { computeGenerationProgress, formatElapsed } from "@/lib/generation-progress";
import { JourneyGateCard } from "@/components/verify/JourneyGateCard";
import { ShipReportCard } from "@/components/verify/ShipReportCard";
import { VerifyProgressCard } from "@/components/verify/VerifyProgressCard";

interface ChatHistoryProps {
  messages: ChatMessageType[];
  streaming: {
    logs: string[];
    toolCalls: { tool: string; args: string }[];
    filesCreated: string[];
    status: string | null;
    isStreaming: boolean;
    intent: string | null;
    resources: ResourceCard[];
    smithThoughts: {
      tool: string;
      summary: string;
      kind?: "reasoning" | "tool" | "tool_start" | "heartbeat";
      text?: string;
      args?: Record<string, unknown>;
      elapsed_s?: number;
      last_tool?: string;
    }[];
    plannerThoughts: { stage: string; text: string }[];
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
      hints: {
        journey_slug: string;
        failing_step: string | null;
        likely_cause: string;
        target_seam: string;
        hint: string;
        tags: string[];
      }[];
    };
  };
  quest: QuestState;
  onSend?: (message: string) => void;
  isGenerating?: boolean;
  /** Project id — threaded into PlanCard so its Adjust-strategy panel
   *  can call `/api/projects/{id}/plan/adjust`. Without it Adjust falls
   *  back to legacy free-text chat. */
  projectId?: string;
}

const INTENT_LABELS: Record<string, string> = {
  PLAN: "Planning",
  REFINE: "Refining",
  EXPLAIN: "Explaining",
  SCAFFOLD: "Scaffolding",
  GENERATE: "Generating",
  UNDO: "Undoing",
  NAVIGATE: "Navigating",
  AMBIGUOUS: "Clarifying",
  APPROVE: "Approving",
};

/** Compact SSE status footer — reused in card and fullscreen */
function SSEStatusBar({
  streaming,
  compact,
  verifyActive,
}: {
  streaming: ChatHistoryProps["streaming"];
  compact?: boolean;
  /** Bubbled up from ChatHistory when the last assistant message has the
   *  SMITH_VERIFY_TRIGGER intent — tells the VerifyProgressCard to
   *  render even before the first journey_result event arrives so the
   *  user sees the container-boot phase filling in. */
  verifyActive?: boolean;
}) {
  const gerund = useFlavorText(streaming.isStreaming);
  const quest = useChatStore((s) => s.quest);
  const [ringNow, setRingNow] = useState(() => Date.now());
  useEffect(() => {
    if (!streaming.isStreaming) return;
    const id = setInterval(() => setRingNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [streaming.isStreaming]);
  const ringProgress = streaming.isStreaming
    ? computeGenerationProgress({
        startedAt: quest.streamStartedAt,
        now: ringNow,
        activeQuestIndex: quest.activePhaseIndex,
        completedQuestIndices: quest.completedPhaseIndices,
        phaseStartTimes: quest.phaseStartTimes,
      })
    : null;

  return (
    <div className={`bg-muted/40 px-3 py-2 ${compact ? "text-xs" : ""}`}>
      {/* Row 1: intent + ring + flavor gerund + status */}
      <div className="flex items-center gap-2">
        {streaming.intent && (
          <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-medium text-blue-700">
            <Brain className="h-2.5 w-2.5" />
            {INTENT_LABELS[streaming.intent] || streaming.intent}
          </span>
        )}
        {streaming.isStreaming && (
          <>
            <GenerationRing size={28} stroke={3} compact />
            <span className="flex items-center gap-1.5 text-[11px] font-medium text-foreground">
              {gerund}…
            </span>
            {ringProgress && !ringProgress.isIndeterminate && (
              <span
                className="text-[10px] tabular-nums text-muted-foreground shrink-0"
                title={`Elapsed ${formatElapsed(ringProgress.elapsedSeconds)}`}
              >
                {ringProgress.etaLabel}
              </span>
            )}
          </>
        )}
        {streaming.status && (
          <span className="truncate text-[11px] text-muted-foreground">
            {streaming.status}
          </span>
        )}
      </div>

      {/* Deliverables tracker + live preview cards */}
      <DeliverablesPanel
        resources={streaming.resources}
        isGenerating={streaming.isStreaming}
      />

      {/* Row 2: files + tools */}
      {(streaming.filesCreated.length > 0 || streaming.toolCalls.length > 0) && (
        <div className="flex gap-3 mt-1 text-[11px] text-muted-foreground">
          {streaming.filesCreated.length > 0 && (
            <div className="flex items-center gap-1">
              <FileCode2 className="h-3 w-3 text-green-500 shrink-0" />
              <span className="truncate max-w-[180px]">
                {streaming.filesCreated[streaming.filesCreated.length - 1]}
              </span>
              {streaming.filesCreated.length > 1 && (
                <span className="text-muted-foreground/50">
                  +{streaming.filesCreated.length - 1}
                </span>
              )}
            </div>
          )}
          {streaming.toolCalls.length > 0 && (
            <div className="flex items-center gap-1">
              <Wrench className="h-3 w-3 shrink-0" />
              <span>{streaming.toolCalls[streaming.toolCalls.length - 1].tool}</span>
            </div>
          )}
        </div>
      )}

      {/* Planner thoughts — live planner-v2 + Actor-Critic loop events
          (structural checks, per-turn critic verdicts, retries). Each
          stage gets a tiny colored dot so the user can distinguish
          v2 (deterministic) hits from critic (LLM) verdicts at a glance.
          Cap to the last 5 to keep the compose bar in view. */}
      {streaming.plannerThoughts.length > 0 && (
        <div className="mt-2 space-y-0.5">
          {streaming.plannerThoughts.slice(-5).map((t, i, arr) => {
            const isCritic = t.stage.startsWith("critic");
            const dotClass = isCritic
              ? "bg-violet-500"
              : "bg-emerald-500";
            const fadeClass =
              i === arr.length - 1
                ? "text-foreground/90"
                : i === arr.length - 2
                  ? "text-foreground/60"
                  : "text-foreground/40";
            return (
              <p
                key={`${i}-${t.stage}`}
                className={`flex items-center gap-1.5 text-[11px] leading-snug ${fadeClass}`}
                title={t.stage || undefined}
              >
                <span
                  className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`}
                  aria-hidden
                />
                <span className="truncate">{t.text}</span>
              </p>
            );
          })}
        </div>
      )}

      {/* Smith thoughts — live ReACT trace, rendered as short narrative
          lines instead of raw tool-name chips. Each line reads like
          Smith is thinking out loud, with a subtle icon per tool
          category. Cap to the last 5 so a fast-thinking turn doesn't
          push the compose bar off-screen. Older thoughts fade + shrink.
          UX-1: narrative reasoning stream.
          Extended-thinking chunks (kind:"reasoning") render as a single
          collapsed "Show reasoning" toggle ABOVE the tool chips so the
          layout stays compact by default. */}
      {streaming.smithThoughts.length > 0 && (() => {
        const reasoning = streaming.smithThoughts.filter(t => t.kind === "reasoning");
        const toolChips = streaming.smithThoughts.filter(t => t.kind !== "reasoning");
        const reasoningText = reasoning.map(r => r.text || "").filter(Boolean).join("\n\n");
        // Rough token count — reasoning is prose, ~4 chars/token is standard.
        const approxTokens = reasoningText ? Math.max(1, Math.round(reasoningText.length / 4)) : 0;
        return (
          <div className="mt-2 space-y-0.5">
            {reasoningText && (
              <details className="mb-1 rounded bg-muted/40 px-2 py-1 text-[11px] leading-snug text-foreground/60">
                <summary className="cursor-pointer select-none font-mono text-[10px] uppercase tracking-wide text-foreground/50">
                  Show reasoning ({approxTokens.toLocaleString()} tokens)
                </summary>
                <pre className="mt-1 whitespace-pre-wrap font-mono text-[10.5px] italic text-foreground/70">
                  {reasoningText}
                </pre>
              </details>
            )}
            {toolChips.slice(-5).map((t, i, arr) => {
              // Route each chip through the narrator that matches its kind.
              // - tool_start: present-tense "Reading X…" (fired live before
              //   the tool runs)
              // - heartbeat: "Still on `read_page` — 15s elapsed"
              // - default/tool: past-tense completion summary
              let narration;
              if (t.kind === "tool_start") {
                narration = narrateSmithToolStart(t.tool);
              } else if (t.kind === "heartbeat") {
                narration = narrateSmithHeartbeat(t.elapsed_s || 0, t.last_tool || "");
              } else {
                narration = narrateSmithThought(t.tool, t.summary);
              }
              const fadeClass =
                i === arr.length - 1
                  ? "text-foreground/90"
                  : i === arr.length - 2
                    ? "text-foreground/60"
                    : "text-foreground/40";
              return (
                <p
                  key={`${i}-${t.tool || t.kind}`}
                  className={`flex items-center gap-1.5 text-[11px] leading-snug ${fadeClass}`}
                  title={t.summary || undefined}
                >
                  <span className="shrink-0">{narration.icon}</span>
                  <span className="truncate">{narration.text}</span>
                </p>
              );
            })}
          </div>
        );
      })()}

      {/* Row 3: logs */}
      {streaming.logs.length > 0 && (
        <div className="mt-1.5 max-h-14 overflow-y-auto rounded bg-muted/60 px-2 py-1 text-[10px] text-muted-foreground/60 font-mono leading-relaxed">
          {streaming.logs.slice(-3).map((log, i) => (
            <p key={i} className="truncate">
              {log}
            </p>
          ))}
        </div>
      )}

      {/* Row 4: journey gate chip — the compact per-run tally that stays
       *  after the progress card completes. Complements VerifyProgressCard
       *  (which now lives at the ChatHistory root so it survives the
       *  streaming-off window during a background verify).
       *  Progress card = LIVE fill; gate chip = STATIC post-run tally. */}
      {(streaming.journey.results.length > 0 || streaming.journey.summary) && (
        <div className="mt-1.5">
          <JourneyGateCard
            results={streaming.journey.results}
            summary={streaming.journey.summary}
            hints={streaming.journey.hints}
          />
        </div>
      )}

      {/* Row 5: ship verdict — the terminal consolidated pass/warn/block
       *  answer over every verification artifact (V3). Arrives once, as
       *  the pipeline's last event before completion. */}
      {streaming.shipReport && (
        <div className="mt-1.5">
          <ShipReportCard report={streaming.shipReport} />
        </div>
      )}
    </div>
  );
}

/** Fullscreen office modal rendered via portal */
function ExpandedOfficeModal({
  streaming,
  isProtest,
  verifyActive,
  onClose,
}: {
  streaming: ChatHistoryProps["streaming"];
  isProtest?: boolean;
  verifyActive?: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return createPortal(
    <div className="fixed inset-0 z-[100] flex flex-col bg-background">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b bg-muted/40">
        <div className="flex items-center gap-2">
          <Building2 className={`h-4 w-4 ${isProtest ? "text-red-500" : "text-primary"}`} />
          <span className="text-sm font-semibold">Virtual Office</span>
          {isProtest ? (
            <div className="flex items-center gap-1.5 text-xs text-red-600">
              <AlertTriangle className="h-3 w-3" />
              Agents are on strike!
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
              Generation in progress
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        >
          <Minimize2 className="h-3.5 w-3.5" />
          Close
        </button>
      </div>

      {/* Office fills remaining space */}
      <div className="flex-1 min-h-0">
        <VirtualOffice className="h-full w-full" isGenerating={streaming.isStreaming} />
      </div>

      {/* Footer */}
      <div className="border-t">
        {isProtest ? (
          <div className="bg-red-50 px-4 py-2.5 text-xs text-red-700 flex items-center gap-2">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span>Budget exhausted — agents have stopped work. Please add credits to continue.</span>
          </div>
        ) : (
          <SSEStatusBar streaming={streaming} verifyActive={verifyActive} />
        )}
      </div>
    </div>,
    document.body,
  );
}

export function ChatHistory({
  messages,
  streaming,
  quest,
  onSend,
  isGenerating,
  projectId,
}: ChatHistoryProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [summaryDismissed, setSummaryDismissed] = useState(false);
  const error = useChatStore((s) => s.error);
  const designTemplates = useChatStore((s) => s.designTemplates);
  const selectedTemplateId = useChatStore((s) => s.selectedTemplateId);

  const showProtest = !!error && isBudgetError(error);

  // JV-16 — verify-active: the last assistant message was the router's
  // "Kicking off Self-Verify Pass" reply (intent=SMITH_VERIFY_TRIGGER).
  // Turn off only when the final rich summary lands (SMITH_VERIFY_COMPLETE).
  //
  // Do NOT short-circuit on `streaming.journey.summary` — that value
  // persists across runs (state never resets between clicks), so a stale
  // summary from run #1 would hide the card on run #2. The assistant-
  // message intents are the reliable per-run signal.
  const verifyActive = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role !== "assistant") continue;
      const intent = m.metadata?.intent as string | undefined;
      // JV-27 — either the legacy intent OR the new rich message type
      // counts as "completion" and hides the chip.
      if (
        intent === "SMITH_VERIFY_COMPLETE" ||
        m.message_type === "verify_result" ||
        m.metadata?.verify !== undefined
      ) {
        return false;
      }
      if (intent === "SMITH_VERIFY_TRIGGER") return true;
      // First assistant message that isn't a verify trigger/complete →
      // no in-flight verify.
      return false;
    }
    return false;
  })();

  // Keep the deliverables/preview panel visible after a build finishes; re-show it
  // (undo any dismiss) as soon as a new generation starts streaming.
  useEffect(() => {
    if (streaming.isStreaming) setSummaryDismissed(false);
  }, [streaming.isStreaming]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, streaming.logs.length, streaming.status, streaming.filesCreated.length, error]);

  // Auto-close expanded view when streaming stops (but not during protest)
  useEffect(() => {
    if (!streaming.isStreaming && !showProtest) setExpanded(false);
  }, [streaming.isStreaming, showProtest]);

  // Auto-open the office modal when protest triggers
  useEffect(() => {
    if (showProtest) setExpanded(true);
  }, [showProtest]);

  return (
    <div className="flex-1 overflow-y-auto bg-background">
      {messages.length === 0 && !streaming.isStreaming && (
        <>
          <ChatMessage
            message={{
              id: "__smith_greeting__",
              project_id: "",
              role: "assistant",
              content:
                "Hi, I'm **Smith** — your build partner here.\n\nTell me what you want to build in plain language and I'll design and generate the whole app. Once it's live, if anything breaks or needs a tweak, just describe the symptom — I'll diagnose it, propose a fix, and apply it once you approve.",
              message_type: "chat",
              metadata: null,
              created_at: new Date().toISOString(),
            }}
            onSend={onSend}
            isGenerating={isGenerating}
            isLastAssistantMessage={false}
          />
          <div className="px-4 md:px-6 pb-4">
            <div className="mx-auto max-w-3xl pl-11">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">
                Or start with one of these
              </p>
              <div className="flex flex-wrap gap-2">
                {[
                  "Patient management system for a clinic",
                  "E-commerce store with inventory",
                  "HR leave management system",
                  "Project tracking dashboard",
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => onSend?.(suggestion)}
                    className="rounded-xl border bg-background px-3 py-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
      {(() => {
        // B-007: parse the earliest `[APPROVE_DISCOVERY]` user message
        // once for the whole render. When present, DiscoveryCard collapses
        // its Fast/Complete picker to a "Chosen: Fast" chip. Prevents the
        // picker from lingering in the chat after the choice was made.
        let discoveryProfileChosen: "fast" | "complete" | null = null;
        for (const m of messages) {
          if (m.role !== "user" || typeof m.content !== "string") continue;
          const trimmed = m.content.trim();
          if (!trimmed.startsWith("[APPROVE_DISCOVERY]")) continue;
          const payloadStr = trimmed.slice("[APPROVE_DISCOVERY]".length).trim();
          try {
            const parsed = JSON.parse(payloadStr) as { mode?: string };
            if (parsed?.mode === "fast" || parsed?.mode === "complete") {
              discoveryProfileChosen = parsed.mode;
              break;
            }
          } catch {
            // Malformed — legacy signal without JSON body. Still collapse
            // the picker; default to "fast" since it's the more common
            // pick and the user is only glancing at a historical card.
            discoveryProfileChosen = "fast";
            break;
          }
        }
        return messages.map((msg, idx) => {
          const isLastAssistant =
            msg.role === "assistant" &&
            !messages.slice(idx + 1).some((m) => m.role === "assistant");
          return (
            <ChatMessage
              key={msg.id}
              message={msg}
              onSend={onSend}
              isGenerating={isGenerating}
              isLastAssistantMessage={isLastAssistant}
              discoveryProfileChosen={discoveryProfileChosen}
              projectId={projectId}
            />
          );
        });
      })()}

      {/* Design template gallery — shown while reviewing the plan, up until the
          real build starts producing files. Stays visible during the brief
          select round-trip (buttons disable) so it doesn't flicker away.
          Rendered ABOVE the progress card: you pick a look first, then it
          builds — so the picker should sit above the generation progress. */}
      {designTemplates.length > 0 && streaming.filesCreated.length === 0 && onSend && (
        <TemplateGallery
          templates={designTemplates}
          selectedId={selectedTemplateId}
          onSend={onSend}
          disabled={streaming.isStreaming}
        />
      )}

      {/* Streaming: SSE status + link to open office */}
      {streaming.isStreaming && (
        <div className="px-4 md:px-6 py-3">
          <div className="mx-auto max-w-3xl rounded-xl border bg-background shadow-sm overflow-hidden">
            <SSEStatusBar streaming={streaming} verifyActive={verifyActive} />
            <div className="px-3 py-2 border-t">
              <button
                onClick={() => setExpanded(true)}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary/80 hover:underline transition-colors"
              >
                <Building2 className="h-3.5 w-3.5" />
                See Agents In Action
              </button>
            </div>
          </div>
        </div>
      )}

      {/* JV-20 — VerifyProgressCard at the ChatHistory root.
       *  Must live OUTSIDE the streaming.isStreaming gate above: the initial
       *  "Kicking off Self-Verify Pass" reply completes its stream in ~1s,
       *  but the verify itself runs for 1-5 min in the background AFTER that.
       *  Gated on `verifyActive` alone — that flips to false the moment a
       *  SMITH_VERIFY_COMPLETE (or verify_result) assistant message lands,
       *  which is the point where the SelfHealCard takes over as the durable
       *  completion representation. Keeping the chip visible after that just
       *  double-renders the same result (the bug seen 2026-08-07). */}
      {verifyActive && (
        <div className="px-4 md:px-6 py-2">
          <div className="mx-auto max-w-3xl">
            <VerifyProgressCard
              streaming={streaming}
              isStreaming={streaming.isStreaming}
              verifyActive={verifyActive}
              projectId={projectId}
            />
          </div>
        </div>
      )}

      {/* Persist the deliverables + preview cards after the build completes */}
      {!streaming.isStreaming &&
        streaming.resources.length > 0 &&
        !summaryDismissed && (
          <div className="px-4 md:px-6 py-3">
            <div className="mx-auto max-w-3xl rounded-xl border bg-background shadow-sm overflow-hidden">
              <div className="flex items-center justify-between bg-muted/40 px-3 py-2">
                <span className="flex items-center gap-1.5 text-[11px] font-medium text-foreground">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                  Build complete — {streaming.resources.length} deliverables
                </span>
                <button
                  onClick={() => setSummaryDismissed(true)}
                  aria-label="Dismiss build summary"
                  className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="px-3 pb-3 pt-1">
                <DeliverablesPanel
                  resources={streaming.resources}
                  isGenerating={false}
                  maxCards={12}
                />
              </div>
            </div>
          </div>
        )}

      {/* Budget error: protest card */}
      {showProtest && !streaming.isStreaming && (
        <div className="px-4 py-3">
          <div className="rounded-lg border border-red-300 bg-gradient-to-r from-red-50 to-orange-50 shadow-sm overflow-hidden">
            <div className="px-4 py-3 flex items-start gap-3">
              <div className="rounded-full bg-red-100 p-2 shrink-0">
                <AlertTriangle className="h-4 w-4 text-red-600" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-red-800">Budget Exhausted</p>
                <p className="text-xs text-red-600 mt-0.5">
                  Your AI credit balance is too low. The office agents have gone on strike!
                </p>
              </div>
            </div>
            <div className="px-4 py-2 border-t border-red-200 bg-red-50/50">
              <button
                onClick={() => setExpanded(true)}
                className="inline-flex items-center gap-1.5 text-xs font-semibold text-red-700 hover:text-red-600 hover:underline transition-colors"
              >
                <Building2 className="h-3.5 w-3.5" />
                See Agents Protesting
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Expanded fullscreen modal */}
      {expanded && (streaming.isStreaming || showProtest) && (
        <ExpandedOfficeModal
          streaming={streaming}
          isProtest={showProtest}
          verifyActive={verifyActive}
          onClose={() => setExpanded(false)}
        />
      )}

      <div ref={bottomRef} />
    </div>
  );
}

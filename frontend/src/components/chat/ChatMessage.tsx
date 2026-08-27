"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { User, Bot, Undo2, Brain, CheckCircle2 } from "lucide-react";
import type { ChatMessage as ChatMessageType } from "@/types/project";
import { PlanCard } from "./PlanCard";
import { DiscoveryCard } from "./DiscoveryCard";
import { NextStepsCard, type NextStep } from "./NextStepsCard";
import { DisambiguationCard, type DisambiguationPayload } from "./DisambiguationCard";
import {
  DesignBriefCard,
  type BriefEditPayload,
  type DesignBriefPayload,
} from "./DesignBriefCard";
import { FixProposalCard } from "./FixProposalCard";
import { FixResultCard } from "./FixResultCard";
import { NeedsUserCard, type NeedsUserPayload } from "./NeedsUserCard";
import { SelfHealCard, type SelfHealMetadata } from "./SelfHealCard";
import { VerifyResultCard, type VerifyPayload } from "@/components/verify/VerifyResultCard";
import { ActionButtons, getActionsForMessage } from "./ActionButtons";
import { useChatStore, type FixProposal, type FixResult } from "@/stores/chat";

interface ChatMessageProps {
  message: ChatMessageType;
  onSend?: (message: string) => void;
  isGenerating?: boolean;
  isLastAssistantMessage?: boolean;
  /** B-007: if the user has already picked a generation profile in this
   *  conversation, DiscoveryCard collapses its Fast/Complete picker to
   *  a compact "Chosen: Fast" chip. Computed once in ChatHistory from
   *  the message list and threaded through here. */
  discoveryProfileChosen?: "fast" | "complete" | null;
  isLatestDiscovery?: boolean;
  /** Project id — enables PlanCard's inline Adjust-strategy panel.
   *  Without it the Adjust button falls back to legacy free-text chat. */
  projectId?: string;
}

export function ChatMessage({ message, onSend, isGenerating, isLastAssistantMessage = false, discoveryProfileChosen, isLatestDiscovery, projectId }: ChatMessageProps) {
  // In-place mutation for the Adjust-strategy panel: when a turn lands
  // with a new plan, patch THIS message's metadata so the PlanCard
  // re-renders against the fresh plan without waiting for an SSE event
  // and without appending a duplicate card to the timeline.
  const upsertMessage = useChatStore((s) => s.upsertMessage);
  const handlePlanUpdated = (newPlan: Record<string, unknown>) => {
    upsertMessage({
      ...message,
      metadata: { ...(message.metadata || {}), plan: newPlan },
    });
  };
  const handleDiscoveryUpdated = (newDossier: Record<string, unknown>) => {
    upsertMessage({
      ...message,
      metadata: { ...(message.metadata || {}), discovery: newDossier },
    });
  };
  const isUser = message.role === "user";
  const intent = message.metadata?.intent as string | undefined;
  const commitHash = message.metadata?.commit_hash as string | undefined;
  const plan = message.metadata?.plan as Record<string, unknown> | undefined;
  const isPlan = message.message_type === "plan" && plan;
  const discovery = message.metadata?.discovery as Record<string, unknown> | undefined;
  const nextSteps = message.metadata?.next_steps as NextStep[] | undefined;
  // Smith Auto-Act (S3) — after a targeted edit, Smith attaches the
  // OTHER pages the same label appears on. Clicking a chip fires a new
  // chat message that applies the same change there. Cheaper than the
  // full disambiguation card because Smith already knows what to do —
  // this is just "…and also here?".
  const alsoAppliesTo = message.metadata?.also_applies_to as
    | Array<{ route: string; label?: string }>
    | undefined;
  // Smith Auto-Act (S4) — chip-mode disambiguation. Backend rides
  // metadata.disambiguation on a "chat" message (same pattern as
  // discovery/pending_fix — no DB enum migration).
  const disambiguation = message.metadata?.disambiguation as
    | DisambiguationPayload
    | undefined;
  // PHASE-3: design brief. Two shapes ride on chat metadata:
  //   brief_edit — after Smith calls edit_brief; shows before/after.
  //   brief_snapshot — from get_brief; read-only render.
  const briefEdit = message.metadata?.brief_edit as BriefEditPayload | undefined;
  const briefSnapshot = message.metadata?.brief_snapshot as
    | DesignBriefPayload
    | undefined;
  // Render as DiscoveryCard whenever the dossier is present in metadata.
  // The backend persists discovery messages with message_type="chat" + metadata.discovery
  // (avoids a DB enum migration). The optimistic client-side append uses
  // message_type="discovery" — both paths route here.
  const isDiscovery = discovery !== undefined;

  // Conversational fix-assistant cards, carried on metadata (like discovery).
  //
  // `fixProposal` is set live from the fix_proposal SSE event; on a fresh page
  // load the DB only has `pending_fix` + `applyToken` (the backend persists
  // those, not the full FixProposal envelope), so reconstruct the proposal
  // from them so the Apply-fix button survives a reload / new tab.
  // Skip when the fix has already been applied — then we render nothing.
  const fixResult = message.metadata?.fixResult as FixResult | undefined;
  const fixApplied = message.metadata?.fixApplied === true;
  const streamedProposal = message.metadata?.fixProposal as FixProposal | undefined;
  const persistedDiagnosis = message.metadata?.pending_fix as FixProposal["diagnosis"] | undefined;
  const persistedToken = message.metadata?.applyToken as string | undefined;

  // Fallback: Smith's tool-loop turns land in `metadata.smith_trace` with
  // a `propose_fix` tool call whose args include the full diagnosis, but
  // the persist pipeline currently doesn't lift that diagnosis to
  // top-level `pending_fix`. Without this fallback the user only sees
  // "I have a diagnosis prepared." with no card. Reach INTO the trace
  // ourselves. The card's Apply button already falls back to the
  // `[APPLY_FIX]` sentinel when applyToken is absent (see
  // FixProposalCard:255) so the flow still works end-to-end.
  const smithTrace = message.metadata?.smith_trace as
    | Array<{ tool?: string; args?: Record<string, unknown> }>
    | undefined;
  const traceDiagnosis: FixProposal["diagnosis"] | undefined = (() => {
    if (!Array.isArray(smithTrace)) return undefined;
    // Prefer the LAST propose_fix in the trace — if Smith diagnosed
    // twice in one turn (rare) the newer one wins.
    for (let i = smithTrace.length - 1; i >= 0; i--) {
      const step = smithTrace[i];
      if (step?.tool === "propose_fix") {
        const d = (step.args as Record<string, unknown>)?.diagnosis;
        if (d && typeof d === "object") return d as FixProposal["diagnosis"];
      }
    }
    return undefined;
  })();

  const fixProposal: FixProposal | undefined =
    streamedProposal ??
    (persistedDiagnosis && persistedToken && !fixApplied
      ? { diagnosis: persistedDiagnosis, changes: [], applyToken: persistedToken }
      : traceDiagnosis && !fixApplied
      ? { diagnosis: traceDiagnosis, changes: [], applyToken: persistedToken ?? "" }
      : undefined);

  // needs_user payload — architect asks the user to pick between options
  // (retry / roll back / abandon / etc.). Shape defined in
  // services/smith_session.py TurnResult and rendered by NeedsUserCard.
  const needsUser = message.metadata?.needsUser as NeedsUserPayload | undefined;

  // Self-heal messages (Smith auto-fixing a runtime exception) get a
  // light-blue bubble so the user can distinguish autonomous heals from
  // their own chat exchanges. Backend sets both flags — check either.
  const isSelfHeal =
    message.metadata?.self_heal === true ||
    message.metadata?.intent === "SMITH_SELF_HEAL";
  // SH-1: rich SelfHealCard when metadata carries a status. Older
  // heal messages (pre-SH-1) have `self_heal=true` but no status —
  // they still fall through to the markdown bubble variant below.
  const selfHealMeta: SelfHealMetadata | undefined =
    isSelfHeal &&
    message.metadata &&
    typeof (message.metadata as Record<string, unknown>).status === "string"
      ? (message.metadata as unknown as SelfHealMetadata)
      : undefined;

  // JV-27 — Self-Verify completion card. Backend persists with
  // message_type="chat" + metadata.intent="SMITH_VERIFY_COMPLETE" +
  // metadata.verify (see routers/generate.py._run_verify_then_summarize).
  // Route on metadata.verify presence (same pattern as `discovery`) so a
  // future optimistic client-side message_type="verify_result" also lands
  // here.
  const verifyPayload = message.metadata?.verify as VerifyPayload | undefined;
  const verifyRunId = message.metadata?.run_id as string | undefined;
  const isVerifyResult =
    !!verifyPayload &&
    (message.message_type === "verify_result" ||
      (message.metadata as Record<string, unknown> | null)?.intent === "SMITH_VERIFY_COMPLETE");

  const actions = !isUser && !fixProposal && !fixResult && !needsUser
    ? getActionsForMessage(
        message.content,
        message.metadata,
        message.message_type,
        isLastAssistantMessage,
      )
    : [];

  return (
    <div className={`px-4 md:px-6 py-3 ${isUser ? "" : ""}`}>
      <div className="mx-auto max-w-3xl">
        <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
          <div
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl shadow-sm ${
              isUser
                ? "bg-primary text-primary-foreground"
                : "bg-gradient-to-br from-violet-500 to-purple-600 text-white"
            }`}
          >
            {isUser ? (
              <User className="h-4 w-4" />
            ) : (
              <Bot className="h-4 w-4" />
            )}
          </div>
          <div className={`min-w-0 flex-1 pt-0.5 ${isUser ? "flex flex-col items-end" : ""}`}>
            <div className={`mb-1.5 flex items-center gap-2 ${isUser ? "flex-row-reverse" : ""}`}>
              <p className="text-xs font-semibold">
                {isUser ? "You" : "Smith"}
              </p>
              {message.created_at && (
                <time
                  dateTime={message.created_at}
                  title={new Date(message.created_at).toLocaleString()}
                  className="text-[10px] tabular-nums text-muted-foreground"
                >
                  {new Date(message.created_at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </time>
              )}
              {intent && (
                <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                  {intent === "UNDO" && <Undo2 className="h-2.5 w-2.5" />}
                  {intent === "PLAN" && <Brain className="h-2.5 w-2.5" />}
                  {intent !== "UNDO" && intent !== "PLAN" && (
                    <CheckCircle2 className="h-2.5 w-2.5" />
                  )}
                  {intent}
                </span>
              )}
            </div>
            {isVerifyResult && verifyPayload ? (
              <VerifyResultCard
                verify={verifyPayload}
                runId={verifyRunId}
                onSend={onSend}
              />
            ) : selfHealMeta ? (
              <SelfHealCard
                metadata={selfHealMeta}
                createdAt={message.created_at}
              />
            ) : needsUser ? (
              <NeedsUserCard
                payload={needsUser}
                onSelect={(choice) => onSend?.(choice)}
                disabled={isGenerating}
              />
            ) : fixProposal ? (
              <FixProposalCard
                proposal={fixProposal}
                onApply={(token) => onSend?.(token)}
                applied={fixApplied}
                disabled={isGenerating}
              />
            ) : fixResult ? (
              <FixResultCard result={fixResult} />
            ) : isPlan ? (
              <PlanCard
                plan={plan as any}
                onApprove={() => onSend?.("[APPROVE_PLAN]")}
                onAdjust={() => onSend?.("I'd like to adjust the plan.")}
                projectId={projectId}
                onPlanUpdated={handlePlanUpdated}
                disabled={isGenerating}
              />
            ) : isDiscovery ? (
              <DiscoveryCard
                discovery={discovery as any}
                onApprove={(signal) => onSend?.(signal)}
                onAdjust={() =>
                  onSend?.(
                    "I'd like to adjust the domain context — let's try a different approach.",
                  )
                }
                disabled={isGenerating}
                alreadyChosen={discoveryProfileChosen ?? null}
                projectId={projectId}
                onDiscoveryUpdated={handleDiscoveryUpdated}
              />
            ) : (
              <div className={`text-sm leading-relaxed ${
                isUser
                  ? "rounded-2xl rounded-tr-md bg-primary text-primary-foreground px-4 py-3 max-w-[85%]"
                  : isSelfHeal
                  ? "rounded-2xl bg-sky-50 border border-sky-200 px-4 py-3 prose prose-sm max-w-none [&_pre]:bg-muted [&_pre]:p-3 [&_pre]:rounded-lg [&_pre]:border [&_code]:text-xs [&_code]:bg-white/70 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded-md [&_h2]:text-base [&_h3]:text-sm [&_h2]:mt-4 [&_h2]:mb-2 [&_h3]:mt-3 [&_h3]:mb-1 [&_ul]:my-2 [&_ol]:my-2 [&_li]:my-0.5 [&_p]:my-2 [&_p]:leading-relaxed"
                  : "prose prose-sm dark:prose-invert max-w-none [&_pre]:bg-muted [&_pre]:p-3 [&_pre]:rounded-lg [&_pre]:border [&_code]:text-xs [&_code]:bg-muted [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded-md [&_h2]:text-base [&_h3]:text-sm [&_h2]:mt-4 [&_h2]:mb-2 [&_h3]:mt-3 [&_h3]:mb-1 [&_ul]:my-2 [&_ol]:my-2 [&_li]:my-0.5 [&_p]:my-2 [&_p]:leading-relaxed"
              }`}>
                {isUser ? (
                  message.content
                ) : (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {message.content}
                  </ReactMarkdown>
                )}
              </div>
            )}
            {commitHash && (
              <p className="mt-2 inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                <CheckCircle2 className="h-2.5 w-2.5" />
                Commit: {commitHash.slice(0, 7)}
              </p>
            )}
            {!isUser && nextSteps && nextSteps.length > 0 && onSend && (
              <NextStepsCard
                steps={nextSteps}
                onSend={onSend}
                disabled={isGenerating}
              />
            )}
            {!isUser && disambiguation && onSend && (
              <DisambiguationCard
                payload={disambiguation}
                onSend={onSend}
                disabled={isGenerating}
              />
            )}
            {!isUser && (briefEdit || briefSnapshot) && onSend && (
              <DesignBriefCard
                payload={briefEdit ?? briefSnapshot!}
                edited={Boolean(briefEdit)}
                onSend={onSend}
                disabled={isGenerating}
              />
            )}
            {!isUser && alsoAppliesTo && alsoAppliesTo.length > 0 && onSend && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                <span>Also applies to:</span>
                {alsoAppliesTo.slice(0, 4).map((t) => (
                  <button
                    key={t.route}
                    type="button"
                    disabled={isGenerating}
                    onClick={() =>
                      onSend(
                        `Apply the same change on ${t.route}${t.label ? ` (${t.label})` : ""}`,
                      )
                    }
                    className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 font-medium text-foreground transition hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {t.route}
                  </button>
                ))}
              </div>
            )}
            {!isUser && actions.length > 0 && onSend && (
              <div className="mt-3">
                <ActionButtons
                  actions={actions}
                  onSend={onSend}
                  disabled={isGenerating}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

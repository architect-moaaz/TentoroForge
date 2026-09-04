"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Undo2 } from "lucide-react";
import { ChatHistory } from "./ChatHistory";
import { ChatInput } from "./ChatInput";
import { AchievementBanner } from "./AchievementBanner";
import { OpenDecisionsCard } from "@/components/decisions/OpenDecisionsCard";
import { Button } from "@/components/ui/button";
import { useChatStore, isBudgetError } from "@/stores/chat";
import { useVisualEditorStore } from "@/stores/visual-editor";
import { useSSE } from "@/hooks/useSSE";
import { useSpeechSynthesis, stripForSpeech } from "@/lib/voice";
import { useOfficeStore } from "@/components/virtual-office/OfficeStateManager";
import type { OfficeEvent } from "@/components/virtual-office/types";
import type { Project } from "@/types/project";

/** Which backend a user message belongs to.
 *
 *  `smith-turn`  — a change against a Living Blueprint. Runs the §72
 *                  incremental DAG and animates the virtual office.
 *  `front-door`  — the streaming build lifecycle: discovery, planning,
 *                  generation, and the control signals that drive them.
 */
export type ChatRoute = "smith-turn" | "front-door";

/** Bracketed machine messages — `[APPROVE_PLAN]`, `[SELECT_TEMPLATE:id]`,
 *  `[APPROVE_DISCOVERY] {"mode":"fast"}`. They can carry a trailing JSON
 *  object, so the pattern must allow one; an anchored `…\]$` misses those and
 *  they leak into the transcript as chat bubbles. */
export function isControlSignal(message: string): boolean {
  return /^\[[A-Z_]+(:[^\]]*)?\](\s*\{[\s\S]*\})?$/.test(message.trim());
}

/** Where a message goes.
 *
 *  Two doors because there are two jobs. A project with no Blueprint has not
 *  been discovered, planned or built yet, and a control signal belongs to that
 *  lifecycle whether or not a Blueprint exists — neither is a special case of
 *  the other, so neither is a fallback.
 */
export function routeFor(message: string, hasBlueprint: boolean): ChatRoute {
  if (!hasBlueprint) return "front-door";
  return isControlSignal(message) ? "front-door" : "smith-turn";
}

interface ChatPanelProps {
  projectId: string;
  project: Project | null;
  onGenerationComplete?: () => void;
}

export function ChatPanel({
  projectId,
  project,
  onGenerationComplete,
}: ChatPanelProps) {
  const { messages, streaming, isGenerating, error, lastCommitHash, quest, dismissCompletionBanner } =
    useChatStore();
  const { startStream } = useSSE();

  // Does this project have a Living Blueprint? Answered by the warmup call
  // below, and it decides which conversation the user is having — see
  // `handleSend`. False until we know, which is the pre-Smith behaviour.
  const [hasBlueprint, setHasBlueprint] = useState(false);

  // ── Smith warmup: preload the app-map into the backend cache when the ──
  //   chat panel mounts, so the first turn sees the map already resident
  //   instead of paying its ~50 ms rebuild on the critical path. Fire-and-
  //   forget: warmup failure never blocks chat (the map is only an
  //   optimisation — Smith degrades to on-demand fetch).
  useEffect(() => {
    if (!projectId) return;
    const ctl = new AbortController();
    setHasBlueprint(false);
    fetch(`/api/projects/${projectId}/smith/warmup`, {
      method: "POST",
      signal: ctl.signal,
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => setHasBlueprint(Boolean(body?.blueprint)))
      .catch(() => {
        /* silent — warmup is best-effort, and false means "use the front door",
           which is the behaviour this panel had before Smith had an endpoint */
      });
    return () => ctl.abort();
  }, [projectId]);

  // Persistent SSE stream for real-time push events (self-heal messages,
  // cross-tab chat updates, future generation-phase pushes). One
  // EventSource per project view — opens on mount, closes on unmount or
  // project change. Server sends `ready` on connect and `ping` every
  // ~25s so proxies keep the connection alive.
  //
  // Connect DIRECTLY to the backend, bypassing the Next.js dev rewrite,
  // for the same reason JV-24 does it on the verify-events stream:
  // Next.js 15's dev proxy uses undici fetch, which buffers streaming
  // responses before flushing to the browser. Result: SSE events sit
  // for many seconds (or forever, on a mostly-idle stream) before the
  // browser gets them, so async messages like SMITH_VERIFY_COMPLETE
  // written from a background task never land until a page refresh.
  // Backend CORS already allows localhost:6501; in prod same-origin.
  useEffect(() => {
    if (!projectId) return;
    const apiBase = process.env.NEXT_PUBLIC_API_URL
      || (typeof window !== "undefined"
          && window.location.hostname === "localhost"
          ? "http://localhost:6500"
          : "");
    const es = new EventSource(`${apiBase}/api/projects/${projectId}/events`);

    const onSelfHeal = (ev: MessageEvent) => {
      try {
        const payload = JSON.parse(ev.data) as {
          conversation_id: string;
          role: "user" | "assistant" | "system";
          content: string;
          message_type: "chat" | "plan" | "discovery" | "generation" | "error";
          metadata: Record<string, unknown> | null;
          created_at: string | null;
        };
        // SH-1: heal messages are UPSERTED — the in_progress row is
        // published first, then replaced by the terminal (resolved/failed/
        // asked) row using the same conversation_id. upsertMessage handles
        // both fresh insert and in-place replace.
        useChatStore.getState().upsertMessage({
          id: payload.conversation_id,
          project_id: projectId,
          role: payload.role,
          content: payload.content,
          message_type: payload.message_type,
          metadata: payload.metadata,
          created_at: payload.created_at ?? new Date().toISOString(),
        });
      } catch {
        /* malformed event — ignore */
      }
    };
    // Office events pushed from a Blueprint DAG run. The run is synchronous
    // Python with no request of its own to stream on — Smith kicks it off from
    // a turn — so it narrates onto the project bus
    // (`services/office_bridge.py`) and lands here. Same payload shape the
    // generation stream's `office` frames carry, so it goes straight to the
    // same store.
    const onOffice = (ev: MessageEvent) => {
      try {
        const payload = JSON.parse(ev.data) as { office?: OfficeEvent };
        if (payload?.office?.type) {
          const store = useOfficeStore.getState();
          if (store.agents.size === 0) store.initialize();
          store.handleEvent(payload.office);
        }
      } catch {
        /* malformed event — ignore */
      }
    };
    es.addEventListener("office", onOffice);

    es.addEventListener("self_heal_message", onSelfHeal);
    // Silent error handler — the browser auto-retries EventSource on
    // network drop, so a temporary disconnect doesn't need a user-visible
    // failure. If the endpoint is truly gone (500/404) the retry loop
    // will noisily fail in DevTools but the chat still works via polling.

    return () => {
      es.removeEventListener("office", onOffice);
      es.removeEventListener("self_heal_message", onSelfHeal);
      es.close();
    };
  }, [projectId]);

  // JV-21 — Live SSE for in-flight verify events. Opens on mount, closes
  // on unmount. The chat store's existing handleSSEEvent handlers already
  // know how to fold journey_result / journey_gate / journey_remediation
  // / log / status into streaming state, so the progress card's phase
  // pips advance without any component-level state duplication.
  //
  // JV-24 — connect DIRECTLY to the backend (bypass Next.js dev rewrite).
  // Next.js 15's dev proxy uses undici fetch, which buffers streaming
  // responses before flushing to the browser (verified: curl sees SSE
  // frames instantly, browser fetch sees zero bytes for seconds).
  // Backend CORS already allows localhost:6501, so a direct connection
  // works in dev; in prod the backend is same-origin behind the reverse
  // proxy so this URL still resolves correctly.
  useEffect(() => {
    console.log("[JV-24] verify-events useEffect fired, projectId=", projectId);
    if (!projectId) return;
    const apiBase = process.env.NEXT_PUBLIC_API_URL
      || (typeof window !== "undefined"
          && window.location.hostname === "localhost"
          ? "http://localhost:6500"
          : "");
    const url = `${apiBase}/api/projects/${projectId}/verify/events`;
    console.log("[JV-24] opening EventSource:", url);
    const es = new EventSource(url);
    es.onopen = () => console.log("[JV-24] SSE open");
    es.onerror = () => console.log("[JV-24] SSE error, readyState=", es.readyState);
    const store = useChatStore.getState();

    const forward = (kind: string) => (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data || "{}");
        store.handleSSEEvent({ event: kind, data } as unknown as Parameters<
          typeof store.handleSSEEvent
        >[0]);
      } catch {
        /* malformed — ignore */
      }
    };

    // Every event kind the pubsub can emit → forwarded to the store.
    const kinds = [
      "log",
      "status",
      "journey_result",
      "journey_gate",
      "journey_remediation",
      "office",
      // JV-27 — live counter / streaming faults from the sidecar poll.
      "verify_progress",
      "verify_fault",
      // V&F 2.0 M3 — per-class healed/residual tally the chip renders
      // as its "N healed, M for you" strip once the pass completes.
      "verify_class_progress",
    ];
    const handlers = kinds.map((k) => {
      const h = forward(k);
      es.addEventListener(k, h);
      return [k, h] as const;
    });

    // Lifecycle markers — verify_start seeds a placeholder status line
    // (so the card's activity area isn't blank), verify_end closes the
    // stream so we don't hold a socket open past its useful life.
    const onStart = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data || "{}");
        // JV-27 — fire the new store handler FIRST so run_id + slice
        // reset land before the placeholder status line, then keep the
        // legacy status hint for the card's activity area.
        store.handleSSEEvent({
          event: "verify_start",
          data,
        } as unknown as Parameters<typeof store.handleSSEEvent>[0]);
        store.handleSSEEvent({
          event: "status",
          data: { message: "Verify started…" },
        } as unknown as Parameters<typeof store.handleSSEEvent>[0]);
      } catch {
        /* ignore */
      }
    };
    const onEnd = (ev: MessageEvent) => {
      // JV-25 — synthesize a journey_gate summary so the store's
      // streaming.journey.summary populates. VerifyProgressCard's
      // isDone flag reads that summary and flips the card to its final
      // (green/orange) state, so the pip animation completes even when
      // the SMITH_VERIFY_COMPLETE assistant message hasn't landed yet.
      try {
        const data = JSON.parse(ev.data || "{}");
        const faults = Number(data?.faults_count || 0);
        const passed = Number(data?.interactions_passed || 0);
        const skipped = Boolean(data?.interaction_pass_skipped);
        // JV-27 — fire the new store handler (toast + status) before the
        // legacy journey_gate synth so the toast reads the pre-clamp
        // verify slice and the chip closes with journey_gate.
        store.handleSSEEvent({
          event: "verify_end",
          data,
        } as unknown as Parameters<typeof store.handleSSEEvent>[0]);
        store.handleSSEEvent({
          event: "journey_gate",
          data: {
            mode: "warn",
            ok: !faults && data?.status === "done",
            total: skipped ? 0 : (passed + faults),
            passed,
            failed: faults,
            duration_ms: 0,
          },
        } as unknown as Parameters<typeof store.handleSSEEvent>[0]);
      } catch {
        /* ignore malformed */
      }
      // JV-26 — do NOT close the ES here. It lives for the project-view
      // lifetime (see cleanup below). Closing after run 1's verify_end
      // meant runs 2+ never delivered their verify_end and the chip stayed
      // "Verifying…" forever.
    };
    es.addEventListener("verify_start", onStart);
    es.addEventListener("verify_end", onEnd);

    return () => {
      handlers.forEach(([k, h]) => es.removeEventListener(k, h));
      es.removeEventListener("verify_start", onStart);
      es.removeEventListener("verify_end", onEnd);
      es.close();
    };
  }, [projectId]);

  // ── Voice output: read each completed assistant reply aloud when enabled. ──
  const { supported: ttsSupported, speak, cancel: cancelSpeech } = useSpeechSynthesis();
  const [voiceReply, setVoiceReply] = useState(false);
  const lastSpokenRef = useRef<string | null>(null);

  const toggleVoiceReply = useCallback(() => {
    setVoiceReply((on) => {
      if (on) cancelSpeech(); // turning off stops any in-progress speech
      else if (messages.length) lastSpokenRef.current = messages[messages.length - 1].id; // don't replay history
      return !on;
    });
  }, [cancelSpeech, messages]);

  // Speak the latest assistant reply once it's complete (generation finished).
  useEffect(() => {
    if (!voiceReply || isGenerating) return;
    const last = messages[messages.length - 1];
    if (
      last &&
      last.role === "assistant" &&
      last.message_type !== "generation" &&
      last.id !== lastSpokenRef.current &&
      last.content?.trim()
    ) {
      lastSpokenRef.current = last.id;
      speak(stripForSpeech(last.content));
    }
  }, [messages, isGenerating, voiceReply, speak]);

  /** Upload one attachment and return its record. Raw `fetch` needs the
   *  Bearer token explicitly — omitting it 401s for a logged-in user, the
   *  same trap the usage dashboard hit (6d24d79e). The backend's 400 detail
   *  is written for humans, so it is surfaced verbatim. */
  const uploadAttachment = useCallback(
    async (file: File) => {
      const token = localStorage.getItem("token");
      const body = new FormData();
      body.append("file", file);
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500"}/api/projects/${projectId}/attachments`,
        {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body,
        },
      );
      if (!res.ok) {
        let detail = `Could not attach ${file.name}`;
        try {
          const j = await res.json();
          if (j?.detail) detail = String(j.detail);
        } catch { /* non-JSON error body — keep the generic message */ }
        throw new Error(detail);
      }
      return await res.json();
    },
    [projectId],
  );

  // ── One conversational turn with Smith ────────────────────────────────
  //
  // Not a stream. The turn's *progress* is the virtual office: the backend
  // narrates the incremental DAG onto this project's SSE stream (already open
  // above), so the agents move while this request is in flight. What comes
  // back over HTTP is the record — the reply, the version, what ran.
  //
  // `startStreaming()` is still what opens that window: it resets and seats
  // the office cast, and flips the `isStreaming` flag the office panel and its
  // "See Agents In Action" link key off. Without it the frames would arrive
  // with nobody on the floor to move and no way to watch.
  const sendSmithTurn = useCallback(
    async (text: string) => {
      const store = useChatStore.getState();
      store.startStreaming();
      try {
        const res = await fetch(`/api/projects/${projectId}/smith/turn`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        const body = await res.json().catch(() => null);

        if (!res.ok) {
          useOfficeStore.getState().endRun();
          store.setError(
            body?.detail ?? `Smith could not take that turn (${res.status})`,
          );
          return;
        }

        // `rejected` is a turn Smith declined to act on rather than a failure:
        // §17 says nothing is applied below the clarification line, and the
        // reply explains why. It belongs in the transcript either way.
        const reply: string = body?.reply || body?.rejected || "";
        if (reply) {
          store.addMessage({
            id: crypto.randomUUID(),
            project_id: projectId,
            role: "assistant",
            content: reply,
            message_type: "chat",
            metadata: body?.version ? { version: body.version } : null,
            created_at: new Date().toISOString(),
          });
        }

        // Only a turn that actually wrote something changed the app, so only
        // then is the preview stale.
        if (body?.applied) onGenerationComplete?.();
      } catch (exc) {
        // The producer is gone, so no terminal frame is coming and the office
        // would stay up forever waiting for one. Only the failure path needs
        // this: a run that completes says so itself.
        useOfficeStore.getState().endRun();
        store.setError(
          exc instanceof Error ? exc.message : "Smith could not be reached",
        );
      } finally {
        store.stopStreaming();
      }
    },
    [projectId, onGenerationComplete],
  );

  const handleSend = useCallback(
    (message: string, attachmentIds?: string[]) => {
      const trimmed = message.trim();

      // Post-build action chips run a dedicated app endpoint (boot + seed / crawl +
      // repair), not a chat turn. Stream those through the same SSE plumbing.
      if (trimmed === "[VALIDATE_REPAIR]" || trimmed === "[SEED_DATA]") {
        const path = trimmed === "[VALIDATE_REPAIR]" ? "validate" : "seed";
        useChatStore.getState().addMessage({
          id: crypto.randomUUID(),
          project_id: projectId,
          role: "user",
          content: trimmed === "[VALIDATE_REPAIR]" ? "Test, Validate & Repair" : "Seed demo data",
          message_type: "chat",
          metadata: null,
          created_at: new Date().toISOString(),
        });
        startStream(`/api/projects/${projectId}/app/${path}`, {}, onGenerationComplete);
        return;
      }

      // Control signals are machine messages — don't show them as chat bubbles.
      const isSignal = isControlSignal(message);
      if (!isSignal) {
        useChatStore.getState().addMessage({
          id: crypto.randomUUID(),
          project_id: projectId,
          role: "user",
          content: message,
          message_type: "chat",
          metadata: null,
          created_at: new Date().toISOString(),
        });
      }

      // Once the project has a Living Blueprint, a plain sentence is a change
      // Smith can reason about against the definition it already holds, so it
      // goes to `/smith/turn` — which runs the §72 incremental DAG and narrates
      // it to the virtual office while the request is in flight.
      //
      // Everything else keeps the streaming front door. That is not a fallback:
      // a project with no Blueprint still has to be discovered, planned and
      // built, and the lifecycle signals ([APPROVE_PLAN], [SELECT_TEMPLATE:…])
      // belong to that flow. Two doors because there are two jobs, not because
      // one of them is a special case.
      if (routeFor(message, hasBlueprint) === "smith-turn") {
        void sendSmithTurn(message);
        return;
      }

      // Single front door for the build lifecycle: first prompt, approval
      // signals, and follow-ups on a project Smith has not yet written a
      // Blueprint for. chat_with_project handles fresh projects (no code, no
      // pending plan/discovery) via the architect bootstrap intercept
      // (services.smith_architect_wire.run_bootstrap_stage), which runs
      // discovery → planner → generation through Smith's own orchestrators
      // with architect-voice narration on every stage transition.
      // Smith Auto-Act (S1) — pass the visual-editor's current route so
      // asks like "change the Status field" score +50 on the page the
      // user is actually looking at (see services.smith_decide).
      const currentRoute = useVisualEditorStore.getState().currentRoute;
      startStream(
        `/api/projects/${projectId}/chat`,
        {
          message,
          current_route: currentRoute,
          attachment_ids: attachmentIds ?? [],
        },
        onGenerationComplete,
      );
    },
    [projectId, startStream, onGenerationComplete, hasBlueprint, sendSmithTurn],
  );

  // Auto-reconnect to in-progress generation after login/page load
  useEffect(() => {
    const checkActive = async () => {
      // Don't reconnect if already streaming
      if (useChatStore.getState().isGenerating) return;

      try {
        const token = localStorage.getItem("token");
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500"}/api/projects/${projectId}/generation/active`,
          { headers: token ? { Authorization: `Bearer ${token}` } : {} },
        );
        if (!res.ok) return;
        const data = await res.json();

        if (data.active && data.sessionId) {
          // Found an in-progress generation — reconnect via SSE
          const { startStreaming, handleSSEEvent, stopStreaming } = useChatStore.getState();
          startStreaming();

          try {
            const sseRes = await fetch(
              `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500"}/api/projects/${projectId}/generation/${data.sessionId}/events?since=0`,
              { headers: token ? { Authorization: `Bearer ${token}` } : {} },
            );
            if (!sseRes.ok) { stopStreaming(); return; }
            const reader = sseRes.body?.getReader();
            if (!reader) { stopStreaming(); return; }

            const decoder = new TextDecoder();
            let buffer = "";
            let currentEvent = "";
            // Dedup replayed events by their monotonic _idx — the primary
            // useSSE reader does this (useSSE.ts) but this reconnect reader
            // didn't, so replaying from since=0 re-dispatched message/plan_ready
            // events that were already applied, duplicating the transcript.
            let lastIdx = -1;

            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split("\n");
              buffer = lines.pop() || "";
              for (const line of lines) {
                if (line.startsWith(":")) continue;
                if (line.startsWith("event:")) { currentEvent = line.slice(6).trim(); }
                else if (line.startsWith("data:") && currentEvent) {
                  try {
                    const eventData = JSON.parse(line.slice(5).trim());
                    // Skip events we've already applied on this reconnect.
                    if (typeof eventData._idx === "number") {
                      if (eventData._idx <= lastIdx) { currentEvent = ""; continue; }
                      lastIdx = eventData._idx;
                    }
                    const { _idx, ...cleanData } = eventData;
                    handleSSEEvent({ event: currentEvent, data: cleanData });
                    if (currentEvent === "complete" || currentEvent === "error") {
                      onGenerationComplete?.();
                    }
                  } catch { /* skip */ }
                  currentEvent = "";
                }
              }
            }
            stopStreaming();
            onGenerationComplete?.();
          } catch {
            stopStreaming();
          }
        }
      } catch {
        // Silently fail — not critical
      }
    };
    checkActive();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Auto-trigger Figma generation if params are in sessionStorage
  useEffect(() => {
    const key = `figma_generate_${projectId}`;
    const raw = sessionStorage.getItem(key);
    if (!raw) return;
    sessionStorage.removeItem(key);
    try {
      const { figma_url, figma_token, description } = JSON.parse(raw);
      if (figma_url && figma_token) {
        // Prefer the user-provided app brief (from NewAppDialog's textarea)
        // over the URL-only boilerplate — the planner / discovery / bizlogic
        // agents get real intent instead of "Import from Figma: <url>".
        const desc: string =
          typeof description === "string" && description.trim()
            ? description.trim()
            : `Import from Figma: ${figma_url}`;
        useChatStore.getState().addMessage({
          id: crypto.randomUUID(),
          project_id: projectId,
          role: "user",
          content: desc,
          message_type: "chat",
          metadata: null,
          created_at: new Date().toISOString(),
        });
        startStream(
          `/api/projects/${projectId}/generate`,
          { description: desc, figma_url, figma_token },
          onGenerationComplete,
        );
      }
    } catch {
      // ignore malformed data
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const handleUndo = useCallback(() => {
    useChatStore.getState().addMessage({
      id: crypto.randomUUID(),
      project_id: projectId,
      role: "user",
      content: "Undo the last change",
      message_type: "chat",
      metadata: null,
      created_at: new Date().toISOString(),
    });

    startStream(
      `/api/projects/${projectId}/chat`,
      { message: "undo" },
      onGenerationComplete,
    );
  }, [projectId, startStream, onGenerationComplete]);

  const canUndo =
    !isGenerating && project?.status === "ready" && lastCommitHash;

  return (
    <div className="flex h-full flex-col bg-background">
      {/* Ambiguity ledger — surfaces every below-high-confidence pick the
        pipeline made (button→workflow wiring, form→submit, etc.) so the
        user can confirm or swap. Renders nothing when there are no
        pending decisions. Re-fetches when a generation completes (its
        internal useEffect keys off projectId; child polls the endpoint). */}
      <div className="border-b bg-background/60 px-3 py-2">
        <OpenDecisionsCard projectId={projectId} key={projectId} />
      </div>
      <ChatHistory messages={messages} streaming={streaming} quest={quest} onSend={handleSend} isGenerating={isGenerating} projectId={projectId} />

      {error && !isBudgetError(error) && (
        <div className="border-t bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {quest.showCompletionBanner && quest.completionStats && (
        <AchievementBanner
          stats={quest.completionStats}
          onDismiss={dismissCompletionBanner}
        />
      )}

      <div className="flex items-center gap-2 border-t bg-background px-3 pt-2">
        {canUndo && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleUndo}
            className="h-7 gap-1 text-xs"
          >
            <Undo2 className="h-3 w-3" />
            Undo
          </Button>
        )}
      </div>

      <ChatInput
        onSend={handleSend}
        uploadAttachment={uploadAttachment}
        disabled={isGenerating}
        placeholder={
          project?.status === "draft"
            ? "Describe the app you want to build..."
            : "Ask for changes to your app..."
        }
        voiceReplyOn={voiceReply}
        onToggleVoiceReply={toggleVoiceReply}
        showVoiceReplyToggle={ttsSupported}
      />
    </div>
  );
}

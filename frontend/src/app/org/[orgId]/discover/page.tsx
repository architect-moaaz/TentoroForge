"use client";

import { use, useState, useCallback, useRef, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  Sparkles,
  Send,
  Loader2,
  User,
  Bot,
  CheckCircle2,
  ArrowRight,
  MessageSquare,
  Plus,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { StructuredBriefPreview } from "@/components/discovery/StructuredBriefPreview";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface DiscoverySession {
  id: string;
  org_id: string;
  user_id: string;
  status: "active" | "brief_ready" | "converted" | "abandoned";
  discovery_type: string | null;
  title: string | null;
  messages: { role: string; content: string }[] | null;
  brief: Record<string, unknown> | null;
  project_id: string | null;
  created_at: string;
  updated_at: string;
}

function DiscoverPage({ orgId }: { orgId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [localMessages, setLocalMessages] = useState<
    { role: string; content: string }[]
  >([]);
  const [brief, setBrief] = useState<Record<string, unknown> | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Abort any active stream on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // Fetch existing sessions
  const { data: sessions = [] } = useQuery({
    queryKey: ["org", orgId, "discovery"],
    queryFn: () =>
      api.get<DiscoverySession[]>(`/api/orgs/${orgId}/discovery`),
  });

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [localMessages.length, streamingText]);

  // Load session messages when selecting
  const loadSession = useCallback(
    (session: DiscoverySession) => {
      setActiveSessionId(session.id);
      setLocalMessages(session.messages || []);
      setBrief(session.brief || null);
      setStreamingText("");
    },
    [],
  );

  const handleSend = useCallback(async () => {
    const message = input.trim();
    if (!message || isStreaming) return;
    setInput("");

    // Abort any previous stream
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Add user message locally
    setLocalMessages((prev) => [...prev, { role: "user", content: message }]);
    setIsStreaming(true);
    setStreamingText("");

    try {
      const token = localStorage.getItem("token");
      let url: string;

      if (!activeSessionId) {
        // Start new session — the /start endpoint already stores the message,
        // so we pass skip_append=true to /message to avoid a duplicate.
        const session = await api.post<DiscoverySession>(
          `/api/orgs/${orgId}/discovery/start`,
          { message },
        );
        setActiveSessionId(session.id);
        url = `/api/orgs/${orgId}/discovery/${session.id}/message`;
      } else {
        url = `/api/orgs/${orgId}/discovery/${activeSessionId}/message`;
      }

      // Stream SSE response
      const response = await fetch(`${API_BASE}${url}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => "Request failed");
        throw new Error(errorText);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";
      let fullText = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const dataStr = line.slice(5).trim();
            if (!dataStr || !currentEvent) continue;
            try {
              const data = JSON.parse(dataStr);
              if (currentEvent === "message") {
                fullText += data.text || "";
                setStreamingText(fullText);
              } else if (currentEvent === "brief_ready") {
                setBrief(data.brief);
              } else if (currentEvent === "office") {
                // Forward office events to the virtual office store
                const { useOfficeStore } = await import(
                  "@/components/virtual-office/OfficeStateManager"
                );
                const officeStore = useOfficeStore.getState();
                if (officeStore.agents.size === 0) officeStore.initialize();
                officeStore.handleEvent(data);
              } else if (currentEvent === "error") {
                throw new Error(data.message || "Stream error");
              }
            } catch (parseErr) {
              if (parseErr instanceof Error && parseErr.message === "Stream error") throw parseErr;
              // skip JSON parse errors
            }
          }
        }
      }

      // Finalize: add assistant message
      if (fullText) {
        setLocalMessages((prev) => [
          ...prev,
          { role: "assistant", content: fullText },
        ]);
      }
      setStreamingText("");
      queryClient.invalidateQueries({
        queryKey: ["org", orgId, "discovery"],
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      console.error("Discovery error:", err);
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }, [input, isStreaming, activeSessionId, orgId, queryClient]);

  const handleConvert = useCallback(async () => {
    if (!activeSessionId) return;
    try {
      const project = await api.post<{ id: string }>(
        `/api/orgs/${orgId}/discovery/${activeSessionId}/convert`,
        {},
      );
      router.push(`/org/${orgId}/projects/${project.id}`);
    } catch (err) {
      console.error("Convert error:", err);
    }
  }, [activeSessionId, orgId, router]);

  // JT-T9: before converting, fetch the transformer's structured brief so the
  // user can review actors + journeys before committing. Fetching lazily
  // (only when they hit "Build") keeps the discovery UX quiet until they're
  // ready to move forward.
  const [previewBrief, setPreviewBrief] = useState<{
    is_empty: boolean;
    brief: Record<string, unknown>;
  } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const handleRequestBuild = useCallback(async () => {
    if (!activeSessionId) return;
    setPreviewLoading(true);
    try {
      const preview = await api.post<{
        is_empty: boolean;
        brief: Record<string, unknown>;
      }>(
        `/api/orgs/${orgId}/discovery/${activeSessionId}/preview-brief`,
        {},
      );
      setPreviewBrief(preview);
    } catch (err) {
      console.error("Preview error:", err);
      // If the preview call fails, fall through to convert directly —
      // legacy flow still works.
      await handleConvert();
    } finally {
      setPreviewLoading(false);
    }
  }, [activeSessionId, orgId, handleConvert]);

  const dismissPreview = useCallback(() => {
    setPreviewBrief(null);
  }, []);

  const startNew = useCallback(() => {
    setActiveSessionId(null);
    setLocalMessages([]);
    setBrief(null);
    setStreamingText("");
    setInput("");
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className="flex h-full">
      {/* Session list sidebar */}
      <div className="flex w-64 flex-col border-r">
        <div className="flex items-center justify-between border-b p-3">
          <h2 className="text-sm font-semibold">Discovery</h2>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={startNew}>
            <Plus className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {sessions.map((session) => (
            <button
              key={session.id}
              onClick={() => loadSession(session)}
              className={`flex w-full items-start gap-2 border-b px-3 py-2.5 text-left transition-colors hover:bg-muted/50 ${
                activeSessionId === session.id ? "bg-accent" : ""
              }`}
            >
              <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">
                  {session.title || "New conversation"}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  {session.status === "brief_ready" && "Brief ready"}
                  {session.status === "converted" && "Converted"}
                  {session.status === "active" && "Active"}
                </p>
              </div>
            </button>
          ))}
          {sessions.length === 0 && (
            <p className="p-4 text-center text-xs text-muted-foreground">
              No sessions yet. Start by describing what you need.
            </p>
          )}
        </div>
      </div>

      {/* Chat area */}
      <div className="flex flex-1 flex-col">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4">
          {localMessages.length === 0 && !isStreaming && (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <Sparkles className="mb-3 h-10 w-10 text-muted-foreground/50" />
              <h2 className="mb-1 text-lg font-semibold">
                What do you need?
              </h2>
              <p className="max-w-md text-sm text-muted-foreground">
                Describe a problem you&apos;re facing, a process you want to
                improve, or an app idea — even if it&apos;s vague. We&apos;ll help you
                figure out the details.
              </p>
            </div>
          )}

          {localMessages.map((msg, i) => (
            <div
              key={i}
              className={`mb-3 flex gap-3 ${msg.role === "user" ? "" : ""}`}
            >
              <div
                className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground"
                }`}
              >
                {msg.role === "user" ? (
                  <User className="h-3.5 w-3.5" />
                ) : (
                  <Bot className="h-3.5 w-3.5" />
                )}
              </div>
              <div className="min-w-0 flex-1 pt-0.5">
                <p className="whitespace-pre-wrap text-sm">{msg.content}</p>
              </div>
            </div>
          ))}

          {/* Streaming text */}
          {streamingText && (
            <div className="mb-3 flex gap-3">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <Bot className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0 flex-1 pt-0.5">
                <p className="whitespace-pre-wrap text-sm">{streamingText}</p>
              </div>
            </div>
          )}

          {isStreaming && !streamingText && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Thinking...
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Brief card — legacy summary + the JT-T9 structured preview when
            the user hits "Build This App". The preview reveals what the
            transformer extracted BEFORE we spend a project on it. */}
        {brief && !previewBrief && (
          <div className="border-t bg-green-50 p-4">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="mt-0.5 h-5 w-5 text-green-600" />
              <div className="flex-1">
                <h3 className="text-sm font-semibold text-green-900">
                  Brief Ready: {(brief.app_name as string) || "Your App"}
                </h3>
                <p className="mt-1 text-xs text-green-700">
                  {(brief.description as string) || ""}
                </p>
                <Button
                  size="sm"
                  className="mt-3 gap-1"
                  onClick={handleRequestBuild}
                  disabled={previewLoading}
                >
                  {previewLoading ? "Reading brief..." : "Build This App"}
                  <ArrowRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </div>
        )}
        {previewBrief && (
          <div className="border-t bg-background p-4">
            <StructuredBriefPreview
              brief={previewBrief.brief}
              isEmpty={previewBrief.is_empty}
              onApprove={handleConvert}
              onAdjust={dismissPreview}
            />
          </div>
        )}

        {/* Input */}
        <div className="flex items-end gap-2 border-t bg-background p-3">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe a problem or idea..."
            disabled={isStreaming}
            rows={1}
            className="flex-1 resize-none rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
          />
          <Button
            size="icon"
            onClick={handleSend}
            disabled={isStreaming || !input.trim()}
            className="h-9 w-9 shrink-0"
          >
            {isStreaming ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function DiscoverPageWrapper({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <DiscoverPage orgId={orgId} />;
}

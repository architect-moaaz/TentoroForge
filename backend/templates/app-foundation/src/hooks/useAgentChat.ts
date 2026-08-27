"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

export type AgentToolCall = {
  tool: string;
  ok: boolean;
};

export type AgentReply = {
  message: string;
  data?: Record<string, unknown>;
  toolCalls?: AgentToolCall[];
};

export interface SendAgentChatOptions {
  message: string;
  attachments?: string[];
}

interface RawAgentResponse {
  message?: unknown;
  reply?: unknown;
  data?: unknown;
  result?: unknown;
  toolCalls?: unknown;
  tool_calls?: unknown;
}

/**
 * Reusable hook that lets any generated page call the app-agent with an
 * uploaded image (or plain text). Companion to the CameraCapture + FileUpload
 * library components — both return a `forge_files` id, which is what the
 * `attachments` array here expects.
 *
 * Under the hood: POST /api/agent/chat { message, attachments: [file_id, ...] }
 *
 * The endpoint response is normalised into a stable {@link AgentReply} shape
 * so pages can bind directly to `lastReply.message` / `lastReply.data`.
 */
export function useAgentChat(): {
  send: (opts: SendAgentChatOptions) => Promise<AgentReply>;
  isLoading: boolean;
  lastReply: AgentReply | null;
  error: Error | null;
} {
  const [lastReply, setLastReply] = useState<AgentReply | null>(null);

  const mutation = useMutation<AgentReply, Error, SendAgentChatOptions>({
    mutationFn: async ({ message, attachments }) => {
      const res = await fetch("/api/agent/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          attachments: attachments ?? [],
        }),
      });

      if (!res.ok) {
        throw new Error(await extractErrorMessage(res));
      }

      const raw = (await res.json().catch(() => ({}))) as RawAgentResponse;
      return normalizeReply(raw);
    },
    onSuccess: (reply) => {
      setLastReply(reply);
    },
  });

  return {
    send: (opts) => mutation.mutateAsync(opts),
    isLoading: mutation.isPending,
    lastReply,
    error: mutation.error ?? null,
  };
}

async function extractErrorMessage(res: Response): Promise<string> {
  // Prefer the server's own message; fall back to a status-specific one.
  let serverMessage = "";
  try {
    const body = await res.json();
    serverMessage =
      (body?.error?.message as string | undefined) ??
      (body?.message as string | undefined) ??
      (body?.error as string | undefined) ??
      "";
  } catch {
    // response body wasn't JSON — nothing to extract
  }

  if (serverMessage) return serverMessage;

  switch (res.status) {
    case 404:
      return "No agent is configured for this app.";
    case 429:
      return "Agent rate limit reached — please try again in a moment.";
    case 500:
      return "The agent encountered an error. Please try again.";
    default:
      return `Agent request failed (${res.status})`;
  }
}

function normalizeReply(raw: RawAgentResponse): AgentReply {
  const message =
    (typeof raw.message === "string" && raw.message) ||
    (typeof raw.reply === "string" && raw.reply) ||
    "";

  const data =
    isRecord(raw.data) ? raw.data
      : isRecord(raw.result) ? raw.result
        : undefined;

  const toolCallsRaw = Array.isArray(raw.toolCalls)
    ? raw.toolCalls
    : Array.isArray(raw.tool_calls)
      ? raw.tool_calls
      : undefined;

  const toolCalls = toolCallsRaw
    ?.map(normalizeToolCall)
    .filter((t): t is AgentToolCall => t !== null);

  return {
    message,
    ...(data !== undefined ? { data } : {}),
    ...(toolCalls && toolCalls.length > 0 ? { toolCalls } : {}),
  };
}

function normalizeToolCall(raw: unknown): AgentToolCall | null {
  if (!isRecord(raw)) return null;
  const tool =
    (typeof raw.tool === "string" && raw.tool) ||
    (typeof raw.name === "string" && raw.name) ||
    "";
  if (!tool) return null;
  const ok = raw.ok === undefined ? true : Boolean(raw.ok);
  return { tool, ok };
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

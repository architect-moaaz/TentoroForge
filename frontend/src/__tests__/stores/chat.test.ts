/**
 * Tests for the chat Zustand store.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useChatStore } from "@/stores/chat";

describe("useChatStore", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
  });

  it("starts with empty state", () => {
    const state = useChatStore.getState();
    expect(state.messages).toEqual([]);
    expect(state.isGenerating).toBe(false);
    expect(state.error).toBeNull();
    expect(state.lastCommitHash).toBeNull();
    expect(state.streaming.isStreaming).toBe(false);
  });

  it("setMessages replaces all messages", () => {
    const msgs = [
      {
        id: "1",
        project_id: "p1",
        role: "user" as const,
        content: "Hello",
        message_type: "chat" as const,
        metadata: null,
        created_at: "2024-01-01T00:00:00Z",
      },
    ];
    useChatStore.getState().setMessages(msgs);
    expect(useChatStore.getState().messages).toHaveLength(1);
    expect(useChatStore.getState().messages[0].content).toBe("Hello");
  });

  it("addMessage appends to messages", () => {
    useChatStore.getState().addMessage({
      id: "1",
      project_id: "p1",
      role: "user" as const,
      content: "First",
      message_type: "chat" as const,
      metadata: null,
      created_at: "2024-01-01T00:00:00Z",
    });
    useChatStore.getState().addMessage({
      id: "2",
      project_id: "p1",
      role: "assistant" as const,
      content: "Second",
      message_type: "chat" as const,
      metadata: null,
      created_at: "2024-01-01T00:00:01Z",
    });
    expect(useChatStore.getState().messages).toHaveLength(2);
  });

  it("startStreaming sets generating state", () => {
    useChatStore.getState().startStreaming();
    const state = useChatStore.getState();
    expect(state.isGenerating).toBe(true);
    expect(state.streaming.isStreaming).toBe(true);
    expect(state.error).toBeNull();
  });

  it("handleSSEEvent status updates streaming status", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().handleSSEEvent({
      event: "status",
      data: { message: "Generating code..." },
    });
    expect(useChatStore.getState().streaming.status).toBe("Generating code...");
  });

  it("handleSSEEvent log appends to logs", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().handleSSEEvent({
      event: "log",
      data: { text: "Created file: App.tsx" },
    });
    expect(useChatStore.getState().streaming.logs).toHaveLength(1);
    expect(useChatStore.getState().streaming.logs[0]).toBe("Created file: App.tsx");
  });

  it("handleSSEEvent tool_call appends tool calls", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().handleSSEEvent({
      event: "tool_call",
      data: { tool: "write_file", args: '{"path": "app.tsx"}' },
    });
    expect(useChatStore.getState().streaming.toolCalls).toHaveLength(1);
    expect(useChatStore.getState().streaming.toolCalls[0].tool).toBe("write_file");
  });

  it("handleSSEEvent file_created tracks files", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().handleSSEEvent({
      event: "file_created",
      data: { path: "src/App.tsx" },
    });
    expect(useChatStore.getState().streaming.filesCreated).toContain("src/App.tsx");
  });

  it("handleSSEEvent intent sets lastIntent", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().handleSSEEvent({
      event: "intent",
      data: { intent: "REFINE" },
    });
    expect(useChatStore.getState().lastIntent).toBe("REFINE");
    expect(useChatStore.getState().streaming.intent).toBe("REFINE");
  });

  it("handleSSEEvent message adds assistant message", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().handleSSEEvent({
      event: "message",
      data: { text: "Here is your explanation." },
    });
    const msgs = useChatStore.getState().messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0].role).toBe("assistant");
    expect(msgs[0].content).toBe("Here is your explanation.");
  });

  it("handleSSEEvent complete stops streaming", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().handleSSEEvent({
      event: "complete",
      data: { project_id: "p1", commit_hash: "abc123" },
    });
    const state = useChatStore.getState();
    expect(state.isGenerating).toBe(false);
    expect(state.streaming.isStreaming).toBe(false);
    expect(state.lastCommitHash).toBe("abc123");
  });

  it("handleSSEEvent error sets error state", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().handleSSEEvent({
      event: "error",
      data: { message: "Something failed" },
    });
    const state = useChatStore.getState();
    expect(state.isGenerating).toBe(false);
    expect(state.error).toBe("Something failed");
  });

  it("handleSSEEvent undo_complete adds revert message", () => {
    useChatStore.getState().startStreaming();
    useChatStore.getState().handleSSEEvent({
      event: "undo_complete",
      data: { commit_hash: "revert123" },
    });
    const state = useChatStore.getState();
    expect(state.lastCommitHash).toBe("revert123");
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].content).toBe("Reverted the last change.");
  });

  it("stopStreaming stops without clearing messages", () => {
    useChatStore.getState().addMessage({
      id: "1",
      project_id: "p1",
      role: "user" as const,
      content: "test",
      message_type: "chat" as const,
      metadata: null,
      created_at: "2024-01-01T00:00:00Z",
    });
    useChatStore.getState().startStreaming();
    useChatStore.getState().stopStreaming();
    expect(useChatStore.getState().isGenerating).toBe(false);
    expect(useChatStore.getState().messages).toHaveLength(1);
  });

  it("reset clears everything", () => {
    useChatStore.getState().addMessage({
      id: "1",
      project_id: "p1",
      role: "user" as const,
      content: "test",
      message_type: "chat" as const,
      metadata: null,
      created_at: "2024-01-01T00:00:00Z",
    });
    useChatStore.getState().startStreaming();
    useChatStore.getState().reset();
    const state = useChatStore.getState();
    expect(state.messages).toEqual([]);
    expect(state.isGenerating).toBe(false);
    expect(state.lastCommitHash).toBeNull();
    expect(state.lastIntent).toBeNull();
  });
});

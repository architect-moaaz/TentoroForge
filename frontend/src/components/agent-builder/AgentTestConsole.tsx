"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { Send, RotateCcw, Loader2, CheckCircle, XCircle, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type {
  AgentNodeSerialized,
  AgentTestMessage,
  AgentTestResult,
  NodeTraceEntry,
} from "@/types/agent-builder";

interface AgentTestConsoleProps {
  projectId: string;
  agentId: string;
  agentName: string;
  nodes: AgentNodeSerialized[];
}

const NODE_TYPE_COLORS: Record<string, string> = {
  system_prompt: "bg-purple-100 text-purple-700",
  tool: "bg-blue-100 text-blue-700",
  guardrail: "bg-orange-100 text-orange-700",
  memory: "bg-green-100 text-green-700",
  human_handoff: "bg-yellow-100 text-yellow-700",
  router: "bg-teal-100 text-teal-700",
};

export function AgentTestConsole({
  projectId,
  agentId,
  agentName,
  nodes,
}: AgentTestConsoleProps) {
  const [messages, setMessages] = useState<AgentTestMessage[]>([]);
  const [trace, setTrace] = useState<NodeTraceEntry[]>([]);
  const [input, setInput] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [totalTokens, setTotalTokens] = useState(0);
  const [totalDuration, setTotalDuration] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = useCallback(async () => {
    if (!input.trim() || isRunning) return;

    const userMessage: AgentTestMessage = {
      id: `msg_${Date.now()}`,
      role: "user",
      content: input.trim(),
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsRunning(true);
    setTrace([]);

    try {
      const result = await api.post<AgentTestResult>(
        `/api/projects/${projectId}/agent-definitions/${agentId}/test`,
        {
          message: userMessage.content,
          conversation_history: messages.map((m) => ({
            role: m.role,
            content: m.content,
          })),
        },
      );

      const assistantMessage: AgentTestMessage = {
        id: `msg_${Date.now()}_resp`,
        role: "assistant",
        content: result.response,
        timestamp: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setTrace(result.trace || []);
      setTotalTokens((prev) => prev + (result.total_tokens || 0));
      setTotalDuration((prev) => prev + (result.total_duration_ms || 0));
    } catch {
      const errorMessage: AgentTestMessage = {
        id: `msg_${Date.now()}_err`,
        role: "assistant",
        content: "Error: Failed to get a response. Make sure the agent definition is saved.",
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsRunning(false);
    }
  }, [input, isRunning, messages, projectId, agentId]);

  const resetConversation = useCallback(() => {
    setMessages([]);
    setTrace([]);
    setTotalTokens(0);
    setTotalDuration(0);
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex h-full">
      {/* Left: Chat interface */}
      <div className="flex flex-1 flex-col border-r">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="text-xs font-semibold">Test Console — {agentName}</span>
          <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={resetConversation}>
            <RotateCcw className="h-3 w-3 mr-1" />
            Reset
          </Button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              <p className="text-xs">Send a message to test your agent</p>
            </div>
          )}
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-lg px-3 py-2 text-xs ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted"
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))}
          {isRunning && (
            <div className="flex justify-start">
              <div className="bg-muted rounded-lg px-3 py-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="border-t p-3">
          <div className="flex gap-2">
            <Input
              className="h-8 text-xs flex-1"
              placeholder="Type a message..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isRunning}
            />
            <Button
              size="sm"
              className="h-8"
              onClick={sendMessage}
              disabled={isRunning || !input.trim()}
            >
              <Send className="h-3.5 w-3.5" />
            </Button>
          </div>
          {(totalTokens > 0 || totalDuration > 0) && (
            <div className="flex gap-3 mt-1.5 text-[10px] text-muted-foreground">
              {totalTokens > 0 && <span>Tokens: {totalTokens}</span>}
              {totalDuration > 0 && <span>Duration: {totalDuration}ms</span>}
            </div>
          )}
        </div>
      </div>

      {/* Right: Execution trace */}
      <div className="flex w-[260px] shrink-0 flex-col bg-muted/10">
        <div className="border-b px-3 py-2">
          <span className="text-xs font-semibold">Execution Trace</span>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {trace.length === 0 ? (
            <p className="text-[10px] text-muted-foreground">
              Send a message to see the execution trace
            </p>
          ) : (
            trace.map((entry, i) => (
              <div
                key={`${entry.node_id}_${i}`}
                className="rounded border bg-white p-2 space-y-1"
              >
                <div className="flex items-center gap-1.5">
                  {entry.status === "completed" ? (
                    <CheckCircle className="h-3 w-3 text-green-500" />
                  ) : entry.status === "failed" ? (
                    <XCircle className="h-3 w-3 text-red-500" />
                  ) : (
                    <Clock className="h-3 w-3 text-blue-500" />
                  )}
                  <span className="text-[10px] font-semibold truncate flex-1">
                    {entry.label}
                  </span>
                  <Badge
                    variant="secondary"
                    className={`text-[8px] px-1 py-0 ${NODE_TYPE_COLORS[entry.node_type] || ""}`}
                  >
                    {entry.node_type}
                  </Badge>
                </div>
                <div className="flex gap-2 text-[9px] text-muted-foreground">
                  {entry.duration_ms !== undefined && (
                    <span>{entry.duration_ms}ms</span>
                  )}
                  {entry.tokens_used !== undefined && entry.tokens_used > 0 && (
                    <span>{entry.tokens_used} tokens</span>
                  )}
                </div>
                {entry.error && (
                  <p className="text-[9px] text-red-500 truncate">{entry.error}</p>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

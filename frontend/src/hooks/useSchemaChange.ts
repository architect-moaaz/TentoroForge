import { useState, useCallback, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface SchemaChangeProgress {
  status: string | null;
  logs: string[];
  filesChanged: string[];
  toolCalls: { tool: string; args: string }[];
}

interface UseSchemaChangeReturn {
  applyChange: (projectId: string, instruction: string, onComplete?: () => void) => Promise<void>;
  isApplying: boolean;
  progress: SchemaChangeProgress;
  error: string | null;
  abort: () => void;
}

const emptyProgress: SchemaChangeProgress = {
  status: null,
  logs: [],
  filesChanged: [],
  toolCalls: [],
};

export function useSchemaChange(): UseSchemaChangeReturn {
  const [isApplying, setIsApplying] = useState(false);
  const [progress, setProgress] = useState<SchemaChangeProgress>({ ...emptyProgress });
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const queryClient = useQueryClient();

  const applyChange = useCallback(
    async (projectId: string, instruction: string, onComplete?: () => void) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setIsApplying(true);
      setProgress({ ...emptyProgress });
      setError(null);

      try {
        const token =
          typeof window !== "undefined"
            ? localStorage.getItem("token")
            : null;

        const response = await fetch(
          `${API_BASE}/api/projects/${projectId}/schema/apply`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ instruction }),
            signal: controller.signal,
          },
        );

        if (!response.ok) {
          const err = await response.json().catch(() => ({
            detail: response.statusText,
          }));
          throw new Error(err.detail || err.message || "Request failed");
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error("No response body");

        const decoder = new TextDecoder();
        let buffer = "";

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
              if (dataStr && currentEvent) {
                try {
                  const data = JSON.parse(dataStr);
                  setProgress((prev) => {
                    const next = { ...prev };
                    switch (currentEvent) {
                      case "status":
                        next.status = data.message || null;
                        break;
                      case "log":
                        next.logs = [...prev.logs, data.text];
                        break;
                      case "file_created":
                        next.filesChanged = [...prev.filesChanged, data.path];
                        break;
                      case "tool_call":
                        next.toolCalls = [
                          ...prev.toolCalls,
                          { tool: data.tool, args: data.args },
                        ];
                        break;
                      case "complete":
                        // Invalidate app-model query
                        queryClient.invalidateQueries({
                          queryKey: ["project", projectId, "app-model"],
                        });
                        onComplete?.();
                        break;
                      case "error":
                        setError(data.message || "Schema change failed");
                        break;
                    }
                    return next;
                  });
                } catch {
                  // Skip malformed JSON
                }
              }
            }
          }
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setError((err as Error).message);
        }
      } finally {
        setIsApplying(false);
      }
    },
    [queryClient],
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
    setIsApplying(false);
  }, []);

  return { applyChange, isApplying, progress, error, abort };
}

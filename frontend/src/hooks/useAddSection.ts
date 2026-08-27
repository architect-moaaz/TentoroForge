import { useState, useCallback, useRef } from "react";
import { useVisualEditorStore } from "@/stores/visual-editor";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface AddSectionRequest {
  route: string;
  template_id?: string;
  custom_prompt?: string;
  insert_position?: string;
}

interface AddSectionProgress {
  status: string | null;
  logs: string[];
  filesChanged: string[];
}

export function useAddSection(projectId: string) {
  const [isGenerating, setIsGenerating] = useState(false);
  const [progress, setProgress] = useState<AddSectionProgress>({
    status: null,
    logs: [],
    filesChanged: [],
  });
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const onCompleteRef = useRef<(() => void) | null>(null);

  const setOnComplete = useCallback((fn: (() => void) | null) => {
    onCompleteRef.current = fn;
  }, []);

  const addSection = useCallback(
    async (body: AddSectionRequest) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setIsGenerating(true);
      setError(null);
      setProgress({ status: null, logs: [], filesChanged: [] });

      try {
        const token =
          typeof window !== "undefined"
            ? localStorage.getItem("token")
            : null;

        const response = await fetch(
          `${API_BASE}/api/projects/${projectId}/visual-edit/add-section`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify(body),
            signal: controller.signal,
          },
        );

        if (!response.ok) {
          const err = await response.json().catch(() => ({
            detail: response.statusText,
          }));
          throw new Error(err.detail || "Section generation failed");
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
                  if (currentEvent === "status") {
                    setProgress((p) => ({ ...p, status: data.message }));
                  } else if (currentEvent === "log") {
                    setProgress((p) => ({
                      ...p,
                      logs: [...p.logs, data.text],
                    }));
                  } else if (currentEvent === "file_created") {
                    setProgress((p) => ({
                      ...p,
                      filesChanged: [...p.filesChanged, data.path],
                    }));
                  } else if (currentEvent === "complete") {
                    // Clear selection and notify
                    useVisualEditorStore.getState().setSelectedElement(null);
                    onCompleteRef.current?.();
                  } else if (currentEvent === "error") {
                    setError(data.message);
                  }
                } catch {
                  // skip malformed JSON
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
        setIsGenerating(false);
      }
    },
    [projectId],
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
    setIsGenerating(false);
  }, []);

  return {
    addSection,
    isGenerating,
    progress,
    error,
    abort,
    setOnComplete,
  };
}

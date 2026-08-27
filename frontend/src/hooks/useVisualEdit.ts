import { useState, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { useVisualEditorStore } from "@/stores/visual-editor";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface EditProgress {
  status: string | null;
  logs: string[];
  filesChanged: string[];
}

export function useVisualEdit(projectId: string) {
  const [isEditing, setIsEditing] = useState(false);
  const [progress, setProgress] = useState<EditProgress>({
    status: null,
    logs: [],
    filesChanged: [],
  });
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Registered callback for after edits complete (e.g., to reload iframe)
  const onCompleteRef = useRef<(() => void) | null>(null);

  const setOnEditComplete = useCallback((fn: (() => void) | null) => {
    onCompleteRef.current = fn;
  }, []);

  /** Clear stale selection and notify listeners after an edit */
  const _afterEdit = useCallback(() => {
    // Clear stale element selection — line numbers are now invalid
    useVisualEditorStore.getState().setSelectedElement(null);
    useVisualEditorStore.getState().setShowActionPopover(false);
    // Notify (e.g., iframe reload)
    onCompleteRef.current?.();
  }, []);

  const directEdit = useCallback(
    async (body: {
      tailwind_edits?: Array<{
        file: string;
        line: number;
        action: "add" | "remove" | "replace";
        class_name: string;
        replace_with?: string;
      }>;
      text_edits?: Array<{
        file: string;
        line: number;
        old_text: string;
        new_text: string;
      }>;
    }) => {
      try {
        const result = await api.post<{ modified: string[] }>(
          `/api/projects/${projectId}/visual-edit`,
          body,
        );
        if (result.modified.length > 0) {
          _afterEdit();
        }
        return result.modified;
      } catch (err) {
        setError((err as Error).message);
        return [];
      }
    },
    [projectId, _afterEdit],
  );

  const aiEdit = useCallback(
    async (body: {
      instruction: string;
      file?: string;
      line?: number;
      context_element?: string;
    }) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setIsEditing(true);
      setError(null);
      setProgress({ status: null, logs: [], filesChanged: [] });

      try {
        const token =
          typeof window !== "undefined"
            ? localStorage.getItem("token")
            : null;

        const response = await fetch(
          `${API_BASE}/api/projects/${projectId}/visual-edit/ai`,
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
          throw new Error(err.detail || "AI edit failed");
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
                    // Edit finished — clear stale state and reload
                    _afterEdit();
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
        setIsEditing(false);
      }
    },
    [projectId, _afterEdit],
  );

  const undo = useCallback(async () => {
    try {
      setError(null);
      const result = await api.post<{ commit_hash: string }>(
        `/api/projects/${projectId}/visual-edit/undo`,
      );
      _afterEdit();
      return result;
    } catch (err) {
      setError((err as Error).message);
      return null;
    }
  }, [projectId, _afterEdit]);

  const reorderSection = useCallback(
    async (body: {
      route: string;
      source_file: string;
      source_line: number;
      target_file: string;
      target_line: number;
      position: "before" | "after";
    }) => {
      try {
        setError(null);
        await api.post(
          `/api/projects/${projectId}/visual-edit/reorder-section`,
          body,
        );
        _afterEdit();
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [projectId, _afterEdit],
  );

  const abort = useCallback(() => {
    abortRef.current?.abort();
    setIsEditing(false);
  }, []);

  return {
    directEdit,
    aiEdit,
    undo,
    reorderSection,
    isEditing,
    progress,
    error,
    abort,
    setOnEditComplete,
  };
}

import { useState, useCallback } from "react";
import { api } from "@/lib/api";

interface PreviewState {
  port: number | null;
  isStarting: boolean;
  error: string | null;
}

export function usePreview(projectId: string) {
  const [state, setState] = useState<PreviewState>({
    port: null,
    isStarting: false,
    error: null,
  });

  const startPreview = useCallback(async () => {
    setState((s) => ({ ...s, isStarting: true, error: null }));
    try {
      const result = await api.post<{ port: number }>(
        `/api/projects/${projectId}/preview/start`,
      );
      setState({ port: result.port, isStarting: false, error: null });
      return result.port;
    } catch (err) {
      setState((s) => ({
        ...s,
        isStarting: false,
        error: (err as Error).message,
      }));
      return null;
    }
  }, [projectId]);

  const stopPreview = useCallback(async () => {
    try {
      await api.post(`/api/projects/${projectId}/preview/stop`);
      setState({ port: null, isStarting: false, error: null });
    } catch {
      // ignore
    }
  }, [projectId]);

  const checkStatus = useCallback(async () => {
    try {
      const result = await api.get<{ running: boolean; port: number | null }>(
        `/api/projects/${projectId}/preview/status`,
      );
      if (result.running && result.port) {
        setState({ port: result.port, isStarting: false, error: null });
      }
    } catch {
      // ignore
    }
  }, [projectId]);

  return {
    ...state,
    startPreview,
    stopPreview,
    checkStatus,
  };
}

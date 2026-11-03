import { useState, useCallback } from "react";
import { api } from "@/lib/api";

interface PreviewState {
  port: number | null;
  // The backend proxy path (/api/projects/{short_id}/preview/serve), not the
  // dev server's internal port, which a hosted browser cannot reach
  // (DEFECT-E-01). The backend returns it from start/status: it is keyed by
  // short_id while the client only holds the project UUID.
  servePath: string | null;
  // The same path at the preview's own origin, which is what a frame loads:
  // the app's code is never run at the platform's (services/preview_origin.py).
  serveUrl: string | null;
  isStarting: boolean;
  error: string | null;
}

export function usePreview(projectId: string) {
  const [state, setState] = useState<PreviewState>({
    port: null,
    servePath: null,
    serveUrl: null,
    isStarting: false,
    error: null,
  });

  const startPreview = useCallback(async () => {
    setState((s) => ({ ...s, isStarting: true, error: null }));
    try {
      const result = await api.post<{ port: number; servePath?: string; serveUrl?: string }>(
        `/api/projects/${projectId}/preview/start`,
      );
      setState({ port: result.port, servePath: result.servePath ?? null, serveUrl: result.serveUrl ?? null,
                 isStarting: false, error: null });
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
      setState({ port: null, servePath: null, serveUrl: null, isStarting: false, error: null });
    } catch {
      // ignore
    }
  }, [projectId]);

  const checkStatus = useCallback(async () => {
    try {
      const result = await api.get<{ running: boolean; port: number | null; servePath?: string; serveUrl?: string }>(
        `/api/projects/${projectId}/preview/status`,
      );
      if (result.running && result.port) {
        setState({ port: result.port, servePath: result.servePath ?? null, serveUrl: result.serveUrl ?? null,
                   isStarting: false, error: null });
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

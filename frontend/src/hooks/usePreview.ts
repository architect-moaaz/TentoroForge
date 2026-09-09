import { useState, useCallback } from "react";
import { api } from "@/lib/api";

interface PreviewState {
  port: number | null;
  // The RELATIVE backend proxy path (/api/projects/{short_id}/preview/serve)
  // the iframe must load. `http://localhost:{port}` is the backend's internal
  // port — unreachable from a hosted client browser, so the Preview tab went
  // blank (DEFECT-E-01). The proxy path is reachable on both localhost and
  // hosted (next.config rewrites it to the backend) and is auth-free. The
  // backend returns it from start/status; the client cannot rebuild it because
  // it is keyed by short_id while the client only holds the project UUID.
  servePath: string | null;
  isStarting: boolean;
  error: string | null;
}

export function usePreview(projectId: string) {
  const [state, setState] = useState<PreviewState>({
    port: null,
    servePath: null,
    isStarting: false,
    error: null,
  });

  const startPreview = useCallback(async () => {
    setState((s) => ({ ...s, isStarting: true, error: null }));
    try {
      const result = await api.post<{ port: number; servePath?: string }>(
        `/api/projects/${projectId}/preview/start`,
      );
      setState({ port: result.port, servePath: result.servePath ?? null, isStarting: false, error: null });
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
      setState({ port: null, servePath: null, isStarting: false, error: null });
    } catch {
      // ignore
    }
  }, [projectId]);

  const checkStatus = useCallback(async () => {
    try {
      const result = await api.get<{ running: boolean; port: number | null; servePath?: string }>(
        `/api/projects/${projectId}/preview/status`,
      );
      if (result.running && result.port) {
        setState({ port: result.port, servePath: result.servePath ?? null, isStarting: false, error: null });
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

import { useEffect, useRef } from "react";
import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import { selectCurrentPage } from "../../state/selectors";
import { getSuggestions } from "../../save/api";

const DEBOUNCE_MS = 5000;

export function useAmbientSuggestions(
  store: EditorStoreApi,
  apiBaseUrl: string,
  enabled: boolean
) {
  const schemaVersion = useStore(store, (s) => selectCurrentPage(s)?.schemaVersion ?? 0);
  const path = useStore(store, (s) => s.currentPath);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!enabled || !path) return;
    if (timer.current) clearTimeout(timer.current);

    timer.current = setTimeout(async () => {
      const page = selectCurrentPage(store.getState());
      if (!page || page.schemaPath !== path) return;
      try {
        const r = await getSuggestions(page.schema, "ambient", apiBaseUrl);
        const suggestions = (r.suggestions ?? []).map((s: any) => ({
          id: `llm:${s.title.replace(/\W+/g, "-").toLowerCase()}-${path}`,
          source: "llm" as const,
          nodeId: s.nodeId,
          severity: (s.severity ?? "info") as "info" | "warn",
          title: s.title,
          description: s.description,
        }));
        store.getState().appendLlmSuggestions(path, suggestions);
      } catch {
        // Silently ignore network errors — ambient suggestions are best-effort
      }
    }, DEBOUNCE_MS);

    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [schemaVersion, path, enabled, store, apiBaseUrl]);
}

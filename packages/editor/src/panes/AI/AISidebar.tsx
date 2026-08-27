import { useStore } from "zustand";
import { useShallow } from "zustand/react/shallow";
import { useCallback } from "react";
import type { EditorStoreApi } from "../../state/store";
import { selectSuggestions } from "../../state/selectors";
import { SuggestionCard } from "./SuggestionCard";

export type AISidebarProps = {
  store: EditorStoreApi;
};

export function AISidebar({ store }: AISidebarProps) {
  const suggestions = useStore(store, useShallow(selectSuggestions));

  const dismissSuggestion = useCallback(
    (id: string) => store.getState().dismissSuggestion(id),
    [store]
  );
  const applySuggestion = useCallback(
    (id: string) => store.getState().applySuggestion(id),
    [store]
  );

  const ruleSuggestions = suggestions.filter((s) => s.source === "rule");
  const llmSuggestions = suggestions.filter((s) => s.source === "llm");

  const hasAnything = suggestions.length > 0;

  return (
    <div
      style={{
        width: 280,
        borderLeft: "1px solid #e5e7eb",
        background: "#f9fafb",
        display: "flex",
        flexDirection: "column",
        overflowY: "auto",
        padding: "12px 10px",
        fontSize: 13,
      }}
    >
      <h2
        style={{
          fontSize: 13,
          fontWeight: 700,
          color: "#111827",
          margin: "0 0 12px 0",
          letterSpacing: "0.02em",
          textTransform: "uppercase",
        }}
      >
        Suggestions
      </h2>

      {!hasAnything && (
        <p style={{ fontSize: 12, color: "#9ca3af", textAlign: "center", marginTop: 24 }}>
          No suggestions — looking good!
        </p>
      )}

      {ruleSuggestions.length > 0 && (
        <section>
          <h3
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: "#6b7280",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              margin: "0 0 6px 0",
            }}
          >
            Rules
          </h3>
          {ruleSuggestions.map((s) => (
            <SuggestionCard
              key={s.id}
              suggestion={s}
              onDismiss={dismissSuggestion}
              onApply={applySuggestion}
            />
          ))}
        </section>
      )}

      {llmSuggestions.length > 0 && (
        <section style={{ marginTop: ruleSuggestions.length > 0 ? 12 : 0 }}>
          <h3
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: "#6b7280",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              margin: "0 0 6px 0",
            }}
          >
            AI
          </h3>
          {llmSuggestions.map((s) => (
            <SuggestionCard
              key={s.id}
              suggestion={s}
              onDismiss={dismissSuggestion}
              onApply={applySuggestion}
            />
          ))}
        </section>
      )}
    </div>
  );
}

import type { Suggestion } from "../../suggestions/types";

export type SuggestionCardProps = {
  suggestion: Suggestion;
  onDismiss: (id: string) => void;
  onApply: (id: string) => void;
};

export function SuggestionCard({ suggestion, onDismiss, onApply }: SuggestionCardProps) {
  const { id, severity, title, description, fix } = suggestion;

  const severityColor = severity === "warn" ? "#f59e0b" : "#3b82f6";
  const severityLabel = severity === "warn" ? "⚠" : "ℹ";

  return (
    <div
      data-suggestion-id={id}
      style={{
        borderLeft: `3px solid ${severityColor}`,
        background: "#ffffff",
        borderRadius: "0 6px 6px 0",
        padding: "10px 12px",
        marginBottom: 8,
        boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 6,
          marginBottom: 4,
        }}
      >
        <span style={{ fontSize: 13, color: severityColor, flexShrink: 0 }}>
          {severityLabel}
        </span>
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "#111827",
            lineHeight: 1.3,
            flex: 1,
          }}
        >
          {title}
        </span>
      </div>
      <p
        style={{
          fontSize: 12,
          color: "#6b7280",
          margin: "0 0 8px 0",
          lineHeight: 1.5,
        }}
      >
        {description}
      </p>
      <div style={{ display: "flex", gap: 6 }}>
        {fix && (
          <button
            aria-label="Apply"
            onClick={() => onApply(id)}
            style={{
              fontSize: 11,
              padding: "3px 10px",
              borderRadius: 4,
              border: "1px solid #3b82f6",
              background: "#eff6ff",
              color: "#3b82f6",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            Apply
          </button>
        )}
        <button
          aria-label="Dismiss"
          onClick={() => onDismiss(id)}
          style={{
            fontSize: 11,
            padding: "3px 10px",
            borderRadius: 4,
            border: "1px solid #e5e7eb",
            background: "#f9fafb",
            color: "#6b7280",
            cursor: "pointer",
          }}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

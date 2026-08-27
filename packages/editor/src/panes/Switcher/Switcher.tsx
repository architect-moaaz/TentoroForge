import { useEffect, useRef, useState } from "react";
import { usePageList } from "../Explorer/usePageList";

export function Switcher({
  open,
  onClose,
  onOpenPage,
  apiBaseUrl,
}: {
  open: boolean;
  onClose: () => void;
  onOpenPage: (path: string) => void;
  apiBaseUrl: string;
}): React.ReactElement | null {
  const paths = usePageList(apiBaseUrl);
  const [filter, setFilter] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) {
      setFilter("");
    } else {
      // Focus the input when opening
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  if (!open) return null;

  const matches =
    filter.trim() === ""
      ? paths
      : paths.filter((p) => p.toLowerCase().includes(filter.toLowerCase()));

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === "Enter" && matches.length > 0) {
      onOpenPage(matches[0]);
      onClose();
    } else if (e.key === "Escape") {
      onClose();
    }
  }

  return (
    <div
      role="dialog"
      aria-label="Jump to page"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        paddingTop: "10vh",
        zIndex: 2000,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 8,
          padding: 16,
          width: 480,
          maxHeight: "60vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 20px 50px rgba(0,0,0,0.2)",
        }}
      >
        <input
          ref={inputRef}
          autoFocus
          placeholder="Jump to page…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          onKeyDown={handleKey}
          style={{
            padding: "8px 12px",
            fontSize: 14,
            border: "1px solid #e5e7eb",
            borderRadius: 4,
            marginBottom: 8,
            outline: "none",
          }}
        />
        <div style={{ overflowY: "auto", flex: 1 }}>
          {matches.map((p) => (
            <div
              key={p}
              role="option"
              aria-selected={false}
              onClick={() => {
                onOpenPage(p);
                onClose();
              }}
              style={{
                padding: "6px 12px",
                cursor: "pointer",
                fontSize: 13,
                borderRadius: 4,
              }}
            >
              {p}
            </div>
          ))}
          {matches.length === 0 && (
            <div style={{ padding: 12, color: "#9ca3af", fontSize: 13 }}>
              No matches
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import { selectCurrentPage } from "../../state/selectors";
import { formatMutation } from "./formatMutation";

export function Diff({ store }: { store: EditorStoreApi }): React.ReactElement | null {
  const page = useStore(store, (s) => selectCurrentPage(s));

  if (!page) return null;

  if (page.saveState === "clean" || page.saveState === "saved") {
    return (
      <div style={{ padding: 16, color: "#6b7280", fontSize: 13 }}>
        No unsaved changes
      </div>
    );
  }

  // Show entire history (most recent first). Phase 2B: saveState gates the display.
  const mutations = page.history.slice().reverse();

  return (
    <div style={{ padding: 12, overflowY: "auto", height: "100%" }}>
      <div
        style={{
          fontSize: 11,
          textTransform: "uppercase",
          color: "#6b7280",
          letterSpacing: "0.05em",
          marginBottom: 8,
        }}
      >
        Changes since last save
      </div>
      {mutations.map((m, i) => (
        <div
          key={i}
          style={{
            padding: "6px 8px",
            borderBottom: "1px solid #f3f4f6",
            fontFamily: "monospace",
            fontSize: 12,
          }}
        >
          {formatMutation(m)}
        </div>
      ))}
    </div>
  );
}

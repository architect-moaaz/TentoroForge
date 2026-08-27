import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import { selectViewport } from "../../state/selectors";
import type { Viewport } from "../../state/types";

const VIEWPORTS: { id: Viewport; label: string; icon: string }[] = [
  { id: "mobile", label: "Mobile", icon: "📱" },
  { id: "tablet", label: "Tablet", icon: "📋" },
  { id: "desktop", label: "Desktop", icon: "🖥️" },
];

export function ViewportToggle({ store }: { store: EditorStoreApi }) {
  const current = useStore(store, selectViewport);
  return (
    <div role="radiogroup" aria-label="viewport size" style={{ display: "flex", gap: 4, padding: "0 8px" }}>
      {VIEWPORTS.map((v) => (
        <button
          key={v.id}
          role="radio"
          aria-checked={current === v.id}
          aria-label={v.label}
          onClick={() => store.getState().setViewport(v.id)}
          style={{
            padding: "4px 8px",
            border: "1px solid #e5e7eb",
            background: current === v.id ? "#dbeafe" : "transparent",
            borderRadius: 4,
            cursor: "pointer",
            fontSize: 14,
          }}
        >
          {v.icon}
        </button>
      ))}
    </div>
  );
}

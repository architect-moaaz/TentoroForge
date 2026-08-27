import { useStore } from "zustand";
import { useShallow } from "zustand/react/shallow";
import type { EditorStoreApi } from "../../state/store";
import { selectOpenPaths } from "../../state/selectors";

export function TabStrip({ store }: { store: EditorStoreApi }): React.ReactElement | null {
  const openPaths = useStore(store, useShallow((s) => selectOpenPaths(s)));
  const currentPath = useStore(store, (s) => s.currentPath);
  const pages = useStore(store, useShallow((s) => s.pages));

  if (openPaths.length === 0) return null;

  return (
    <div
      role="tablist"
      style={{
        display: "flex",
        borderBottom: "1px solid #e5e7eb",
        background: "#f9fafb",
        overflowX: "auto",
      }}
    >
      {openPaths.map((path) => {
        const page = pages[path];
        const active = path === currentPath;
        const dirty = page?.saveState === "dirty";
        return (
          <div
            key={path}
            data-active={String(active)}
            role="tab"
            aria-selected={active}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 12px",
              borderRight: "1px solid #e5e7eb",
              background: active ? "#fff" : "transparent",
              cursor: "pointer",
              fontSize: 13,
              whiteSpace: "nowrap",
            }}
            onClick={() => store.getState().switchPage(path)}
          >
            {dirty && (
              <span aria-label="dirty" style={{ color: "#dc2626" }}>
                ●
              </span>
            )}
            <span>{path}</span>
            <button
              aria-label={`close ${path}`}
              onClick={(e) => {
                e.stopPropagation();
                const pg = store.getState().pages[path];
                if (pg?.saveState === "dirty") {
                  if (!window.confirm("You have unsaved changes. Close anyway?")) return;
                }
                store.getState().closePage(path);
              }}
              style={{
                background: "transparent",
                border: "none",
                cursor: "pointer",
                padding: "0 4px",
                fontSize: 14,
                color: "#6b7280",
              }}
            >
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}

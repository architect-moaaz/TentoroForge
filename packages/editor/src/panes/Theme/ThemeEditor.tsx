import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import { selectTheme, selectThemeDirty } from "../../state/selectors";
import { ColorTokenEditor } from "./ColorTokenEditor";
import { ScalarTokenEditor } from "./ScalarTokenEditor";
import { TokenGroup } from "./TokenGroup";

export function ThemeEditor({ store, onSave }: { store: EditorStoreApi; onSave: () => void }) {
  const theme = useStore(store, selectTheme);
  const dirty = useStore(store, selectThemeDirty);
  if (!theme) return <div style={{ padding: 16 }}>Loading theme…</div>;

  return (
    <div style={{ width: 320, borderLeft: "1px solid #e5e7eb", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ padding: 8, borderBottom: "1px solid #e5e7eb", display: "flex", alignItems: "center", gap: 8 }}>
        <strong style={{ fontSize: 13, flex: 1 }}>Theme</strong>
        <button onClick={onSave} style={{ opacity: dirty ? 1 : 0.5 }}>Save theme</button>
      </div>
      <div style={{ overflowY: "auto", padding: 8 }}>
        {Object.entries(theme).map(([group, tokens]) => (
          <TokenGroup key={group} name={group}>
            {Object.entries(tokens as Record<string, string>).map(([name, value]) => {
              if (group === "colors") {
                return (
                  <ColorTokenEditor
                    key={name}
                    name={name}
                    value={value}
                    onChange={(v) => store.getState().setTokenValue(group, name, v)}
                  />
                );
              }
              return (
                <ScalarTokenEditor
                  key={name}
                  name={name}
                  value={value}
                  onChange={(v) => store.getState().setTokenValue(group, name, v)}
                />
              );
            })}
          </TokenGroup>
        ))}
      </div>
    </div>
  );
}

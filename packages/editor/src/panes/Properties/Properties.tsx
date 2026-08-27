import { useState } from "react";
import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import type { Registry } from "@tentoroforge/library";
import type { TokenGroups } from "@tentoroforge/library";
import type { StyleSlotT } from "@tentoroforge/schema";
import { PropsTab } from "./PropsTab";
import { BindingsTab } from "./BindingsTab";
import { StyleSlotEditor, type DesignSystemKnobs } from "./StyleSlotEditor";
import { selectCurrentPage, selectTheme } from "../../state/selectors";
import { buildSetStyle, findNodeDeep } from "../../state/mutations";

const TAB_BASE =
  "flex-1 inline-flex items-center justify-center gap-1.5 h-9 px-3 text-xs font-medium " +
  "text-muted-foreground hover:text-foreground transition-colors border-b-2 border-transparent " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset";
const TAB_ACTIVE = "text-foreground border-primary";

export function Properties({
  store,
  registry,
  tokens,
}: {
  store: EditorStoreApi;
  registry: Registry;
  tokens: TokenGroups;
}) {
  const [tab, setTab] = useState<"props" | "style" | "bindings">("props");

  const selectedIds = useStore(store, (s) => selectCurrentPage(s)?.selection ?? []);
  const theme = useStore(store, (s) => selectTheme(s));

  const selectedNodeStyle = useStore(store, (s) => {
    const page = selectCurrentPage(s);
    if (!page || page.selection.length !== 1) return undefined;
    const node = findNodeDeep((page.schema as any).root, page.selection[0]);
    return node?.style as StyleSlotT | undefined;
  });

  // Wave 2: read current design-system knob values from the token store.
  const designSystemKnobs: DesignSystemKnobs = {
    density:     (theme as any)?.density   as string | undefined,
    elevation:   (theme as any)?.elevation as string | undefined,
    radiusScale: (theme as any)?.radius?.scale as string | undefined,
  };

  function handleStyleChange(key: keyof StyleSlotT, next: any) {
    const page = selectCurrentPage(store.getState());
    if (!page || selectedIds.length !== 1) return;
    store.getState().apply(buildSetStyle(selectedIds[0], key as any, next, page.schema as any));
  }

  // Wave 2: write design-system knobs to the token store.
  // density + elevation are top-level scalars; radius.scale is nested.
  function handleDesignSystemChange(knob: keyof DesignSystemKnobs, value: string) {
    if (knob === "density")     store.getState().setTokenValue("density",   "", value);
    if (knob === "elevation")   store.getState().setTokenValue("elevation", "", value);
    if (knob === "radiusScale") store.getState().setTokenValue("radius", "scale", value);
  }

  return (
    <div className="w-[320px] shrink-0 flex flex-col border-l border-border bg-background">
      <div
        role="tablist"
        className="flex border-b border-border bg-muted/20"
      >
        {(["props", "style", "bindings"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`${TAB_BASE} ${tab === t ? TAB_ACTIVE : ""} capitalize`}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto">
        {tab === "props" && <PropsTab store={store} registry={registry} />}
        {tab === "style" && (
          selectedIds.length === 1 ? (
            <StyleSlotEditor
              value={selectedNodeStyle}
              onChange={handleStyleChange}
              theme={theme}
              designSystem={designSystemKnobs}
              onDesignSystemChange={handleDesignSystemChange}
            />
          ) : (
            <p className="p-4 text-sm text-muted-foreground">
              Select a single node to edit its style.
            </p>
          )
        )}
        {tab === "bindings" && <BindingsTab store={store} />}
      </div>
    </div>
  );
}

import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import type { TokenGroups } from "@tentoroforge/library";
import { buildSetStyle } from "../../state/mutations";
import { TokenPicker } from "./TokenPicker";
import { selectCurrentPage } from "../../state/selectors";

const STYLE_TO_GROUP: Record<string, string> = {
  color: "colors",
  background: "colors",
  borderColor: "colors",
  padding: "spacing",
  paddingX: "spacing",
  paddingY: "spacing",
  margin: "spacing",
  marginX: "spacing",
  marginY: "spacing",
  gap: "spacing",
  width: "spacing",
  height: "spacing",
  fontSize: "typography",
  fontWeight: "typography",
  lineHeight: "typography",
  letterSpacing: "typography",
  borderRadius: "radii",
  shadow: "shadows",
  borderWidth: "spacing",
};

function findNode(root: any, id: string): any {
  if (root.id === id) return root;
  for (const c of root.children ?? []) {
    const f = findNode(c, id);
    if (f) return f;
  }
  return null;
}

export function StyleTab({
  store,
  tokens,
}: {
  store: EditorStoreApi;
  tokens: TokenGroups;
}) {
  const selectedIds = useStore(store, (s) => selectCurrentPage(s)?.selection ?? []);
  const schema = useStore(store, (s) => selectCurrentPage(s)?.schema);

  if (!schema || selectedIds.length === 0)
    return <p style={{ padding: 12, color: "#6b7280" }}>Nothing selected</p>;

  const selectedNodes = selectedIds.map((id) => findNode((schema as any).root, id)).filter(Boolean);
  if (selectedNodes.length === 0)
    return <p style={{ padding: 12, color: "#6b7280" }}>Nothing selected</p>;

  // Collect all style keys from all selected nodes
  const allStyleKeys = new Set<string>();
  for (const n of selectedNodes) {
    for (const k of Object.keys(n.style ?? {})) {
      if (n.style[k] !== undefined) allStyleKeys.add(k);
    }
  }

  // For single select, maintain existing behaviour
  const primaryNode = selectedNodes[0];
  const style = primaryNode.style ?? {};

  function commonStyleValue(key: string): { value: string | undefined; mixed: boolean } {
    const values = selectedNodes.map((n: any) => n.style?.[key]);
    const first = values[0];
    const allSame = values.every((v: any) => v === first);
    return { value: allSame ? first : undefined, mixed: !allSame };
  }

  function onChange(key: string, value: string | undefined) {
    const currentSchema = selectCurrentPage(store.getState())?.schema;
    if (!currentSchema) return;
    if (selectedIds.length === 1) {
      store.getState().apply(buildSetStyle(selectedIds[0], key as any, value as any, currentSchema));
    } else {
      const subs = selectedIds.map((id) => buildSetStyle(id, key as any, value as any, currentSchema));
      store.getState().apply({ kind: "composite", mutations: subs });
    }
  }

  // Show pickers only for style keys that have a current value set on the primary node.
  // Keys are ordered according to STYLE_TO_GROUP canonical order.
  const canonicalOrder = Object.keys(STYLE_TO_GROUP);
  const populated = Object.keys(style).filter((k) => style[k] !== undefined);
  const displayKeys = [
    ...canonicalOrder.filter((k) => populated.includes(k)),
    ...populated.filter((k) => !canonicalOrder.includes(k)),
  ];

  return (
    <div style={{ padding: 12 }}>
      {displayKeys.map((styleKey) => {
        const { value, mixed } = commonStyleValue(styleKey);
        return (
          <TokenPicker
            key={styleKey}
            groupKey={STYLE_TO_GROUP[styleKey] ?? "colors"}
            label={`${styleKey}${mixed ? " (mixed)" : ""}`}
            value={value}
            onChange={(v) => onChange(styleKey, v)}
            tokens={tokens}
          />
        );
      })}
    </div>
  );
}

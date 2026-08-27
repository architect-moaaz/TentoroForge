import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import { buildSetBind, buildSetVisibleIf, buildSetEvent } from "../../state/mutations";
import { selectCurrentPage } from "../../state/selectors";

function findNode(root: any, id: string): any {
  if (root.id === id) return root;
  for (const c of root.children ?? []) {
    const f = findNode(c, id);
    if (f) return f;
  }
  return null;
}

export function BindingsTab({ store }: { store: EditorStoreApi }) {
  const selectedId = useStore(store, (s) => selectCurrentPage(s)?.selection[0] ?? null);
  const schema = useStore(store, (s) => selectCurrentPage(s)?.schema);
  if (!selectedId)
    return <p style={{ padding: 12, color: "#6b7280" }}>Nothing selected</p>;
  const node = findNode((schema as any).root, selectedId);
  if (!node) return <p>Node not found</p>;

  const sources = (schema as any).dataSources ?? [];
  const bindSource = node.bind?.source ?? "";
  const bindPath = node.bind?.path ?? "";
  const visibleIf = node.visibleIf ?? "";
  const onClickWorkflow = (node.on?.click as any)?.workflow ?? "";

  function getBoundSchema() {
    return selectCurrentPage(store.getState())?.schema;
  }

  function setBind(source: string, path: string) {
    const bind = source && path ? { source, path } : undefined;
    const currentSchema = getBoundSchema();
    if (!currentSchema) return;
    store.getState().apply(buildSetBind(selectedId!, bind, currentSchema));
  }

  function setVisible(expr: string) {
    const currentSchema = getBoundSchema();
    if (!currentSchema) return;
    store.getState().apply(buildSetVisibleIf(selectedId!, expr || undefined, currentSchema));
  }

  function setOnClick(workflow: string) {
    const handler = workflow ? { workflow } : undefined;
    const currentSchema = getBoundSchema();
    if (!currentSchema) return;
    store.getState().apply(buildSetEvent(selectedId!, "click", handler as any, currentSchema));
  }

  return (
    <div style={{ padding: 12 }}>
      <div style={{ marginBottom: 12 }}>
        <label
          htmlFor="bind-source"
          style={{ display: "block", fontSize: 12, marginBottom: 4 }}
        >
          data source
        </label>
        <select
          id="bind-source"
          value={bindSource}
          onChange={(e) => setBind(e.target.value, bindPath)}
          style={{ width: "100%" }}
        >
          <option value="">—</option>
          {sources.map((s: any) => (
            <option key={s.name} value={s.name}>
              {s.name}
            </option>
          ))}
        </select>

        <label
          htmlFor="bind-path"
          style={{ display: "block", fontSize: 12, marginTop: 8, marginBottom: 4 }}
        >
          path
        </label>
        <input
          id="bind-path"
          value={bindPath}
          onChange={(e) => setBind(bindSource, e.target.value)}
          placeholder="items[0].name"
          style={{ width: "100%" }}
        />
      </div>

      <div style={{ marginBottom: 12 }}>
        <label
          htmlFor="bind-visibleIf"
          style={{ display: "block", fontSize: 12, marginBottom: 4 }}
        >
          visibleIf
        </label>
        <input
          id="bind-visibleIf"
          value={visibleIf}
          onChange={(e) => setVisible(e.target.value)}
          placeholder="user.role == 'admin'"
          style={{ width: "100%" }}
        />
      </div>

      <div style={{ marginBottom: 12 }}>
        <label
          htmlFor="bind-onClick"
          style={{ display: "block", fontSize: 12, marginBottom: 4 }}
        >
          onClick workflow
        </label>
        <input
          id="bind-onClick"
          value={onClickWorkflow}
          onChange={(e) => setOnClick(e.target.value)}
          placeholder="deleteProduct"
          style={{ width: "100%" }}
        />
      </div>
    </div>
  );
}

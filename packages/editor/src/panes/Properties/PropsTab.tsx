import { useStore } from "zustand";
import type { EditorStoreApi } from "../../state/store";
import type { Registry } from "@tentoroforge/library";
import { buildSetProp } from "../../state/mutations";
import { selectCurrentPage } from "../../state/selectors";

function findNode(root: any, id: string): any {
  if (root.id === id) return root;
  for (const c of root.children ?? []) {
    const f = findNode(c, id);
    if (f) return f;
  }
  return null;
}

const EMPTY_STATE = "p-4 text-sm text-muted-foreground";
const FIELD_LABEL = "text-xs font-medium leading-none text-foreground";
const FIELD_INPUT =
  "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 " +
  "text-sm shadow-sm transition-colors placeholder:text-muted-foreground " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";
const FIELD_SELECT =
  "flex h-9 w-full items-center justify-between rounded-md border border-input " +
  "bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none " +
  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

export function PropsTab({ store, registry }: { store: EditorStoreApi; registry: Registry }) {
  const selectedIds = useStore(store, (s) => selectCurrentPage(s)?.selection ?? []);
  const schema = useStore(store, (s) => selectCurrentPage(s)?.schema);

  if (!schema || selectedIds.length === 0)
    return <p className={EMPTY_STATE}>Nothing selected</p>;

  const selectedNodes = selectedIds.map((id) => findNode((schema as any).root, id)).filter(Boolean);
  if (selectedNodes.length === 0)
    return <p className={EMPTY_STATE}>Nothing selected</p>;

  const types = new Set(selectedNodes.map((n: any) => n.type));
  if (types.size > 1)
    return <p className={EMPTY_STATE}>Mixed node types — select a single node to edit props.</p>;

  const nodeType = [...types][0]!;
  const entry = registry.get(nodeType);
  if (!entry)
    return <p className={EMPTY_STATE}>No props schema for type &ldquo;{nodeType}&rdquo;</p>;

  const propShape = (entry.propsSchema as any)._def?.shape?.() ?? {};
  const propKeys = Object.keys(propShape);

  function commonValue(key: string): { value: any; mixed: boolean } {
    const values = selectedNodes.map((n: any) => n.props?.[key]);
    const first = values[0];
    const allSame = values.every((v: any) => v === first);
    return { value: allSame ? first : undefined, mixed: !allSame };
  }

  function onChange(key: string, value: unknown) {
    const currentSchema = selectCurrentPage(store.getState())?.schema;
    if (!currentSchema) return;
    if (selectedIds.length === 1) {
      store.getState().apply(buildSetProp(selectedIds[0], key, value, currentSchema));
    } else {
      const subs = selectedIds.map((id) => buildSetProp(id, key, value, currentSchema));
      store.getState().apply({ kind: "composite", mutations: subs });
    }
  }

  const hasMixed = propKeys.some((key) => commonValue(key).mixed);

  return (
    <div className="flex flex-col gap-3 p-3">
      {/* Element header — mirrors the IREditor's "Element" section */}
      <div className="flex flex-col gap-1 pb-2 border-b border-border">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Element
        </span>
        <code className="text-xs text-foreground font-mono">&lt;{nodeType}&gt;</code>
      </div>

      {selectedIds.length > 1 && (
        <p className="text-[11px] rounded bg-muted px-2 py-1 text-muted-foreground">
          {selectedIds.length} nodes selected
          {hasMixed && <span className="text-destructive"> — some values are mixed</span>}
        </p>
      )}

      {propKeys.length === 0 ? (
        <p className="text-xs text-muted-foreground">No editable props.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {propKeys.map((key) => {
            const { value, mixed } = commonValue(key);
            const def = propShape[key];
            const isEnum =
              def?._def?.typeName === "ZodEnum" ||
              def?._def?.innerType?._def?.typeName === "ZodEnum";
            // Object / array values can't be edited as a single-line input —
            // toString() turns them into "[object Object]". Render as JSON in
            // a textarea so the user sees and can edit the real shape.
            const isComplex = !mixed && value !== null && value !== undefined && typeof value === "object";
            return (
              <div key={key} className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2">
                  <label htmlFor={`prop-${key}`} className={FIELD_LABEL}>{key}</label>
                  {mixed && (
                    <span className="text-[10px] text-destructive">(mixed)</span>
                  )}
                  {isComplex && (
                    <span className="text-[10px] text-muted-foreground/70">json</span>
                  )}
                </div>
                {isEnum ? (
                  <select
                    id={`prop-${key}`}
                    className={FIELD_SELECT}
                    value={value ?? ""}
                    onChange={(e) => onChange(key, e.target.value)}
                  >
                    {mixed && <option value="">—</option>}
                    {(def?._def?.values ?? def?._def?.innerType?._def?.values ?? []).map(
                      (v: string) => (
                        <option key={v} value={v}>{v}</option>
                      )
                    )}
                  </select>
                ) : isComplex ? (
                  <textarea
                    id={`prop-${key}`}
                    className={FIELD_INPUT + " min-h-[72px] font-mono text-[11px] leading-5 py-1.5 resize-y"}
                    rows={4}
                    defaultValue={(() => { try { return JSON.stringify(value, null, 2); } catch { return ""; } })()}
                    onBlur={(e) => {
                      const txt = e.target.value;
                      try {
                        onChange(key, JSON.parse(txt));
                      } catch {
                        // Leave existing value if the user typed invalid JSON;
                        // we don't want to drop their data on a typo.
                      }
                    }}
                    spellCheck={false}
                  />
                ) : (
                  <input
                    id={`prop-${key}`}
                    className={FIELD_INPUT}
                    value={(value === null || value === undefined) ? "" : String(value)}
                    placeholder={mixed ? "—" : ""}
                    onChange={(e) => onChange(key, e.target.value)}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

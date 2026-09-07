"use client";
import * as React from "react";
import { useState } from "react";
import { useEditorStore } from "@/lib/editor-store";
import { starterRegistry } from "@forge/registry";
import type { PropDescriptor } from "@forge/registry";
import { CONTROL_BY_TYPE, TextControl } from "./PropControls";
import { BindingControl } from "./PropControls/BindingControl";
import { DataKeyControl } from "./PropControls/DataKeyControl";
import { BindToggle } from "./BindToggle";
import { isRequiredProp } from "./required-props";
import { isBinding, bindingExpression } from "@forge/patches";
import { normalizeSeed } from "@/components/canvas/hooks/useDrop";
import { BreakpointSwitcher, type EditorBreakpoint } from "./BreakpointSwitcher";
import { gridStructureActions } from "@/lib/grid-actions";

const BP_KEYS = new Set(["default", "sm", "md", "lg", "xl"]);

function isResponsiveShape(v: unknown): boolean {
  if (!v || typeof v !== "object" || Array.isArray(v)) return false;
  const keys = Object.keys(v as object);
  return keys.length > 0 && keys.every(k => BP_KEYS.has(k));
}

function readPropAtBp(
  node: any,
  propName: string,
  bp: EditorBreakpoint,
  fallbackDefault: any,
): any {
  const raw = (node.props ?? {})[propName];
  if (bp === "default") {
    if (isResponsiveShape(raw)) {
      return (raw as any).default ?? fallbackDefault;
    }
    return raw ?? fallbackDefault;
  }
  // Reading a specific breakpoint
  if (isResponsiveShape(raw) && bp in (raw as any)) {
    return (raw as any)[bp];
  }
  // No override at this bp — return undefined so the control shows empty
  return undefined;
}

function writePropAtBp(
  currentRaw: any,
  bp: EditorBreakpoint,
  newValue: any,
  /** The registry descriptor's default — the base to seed when the prop is unset. */
  descriptorDefault?: any,
): any {
  if (bp === "default") {
    if (isResponsiveShape(currentRaw)) {
      return { ...(currentRaw as object), default: newValue };
    }
    return newValue; // plain literal
  }
  // Writing to a specific bp — wrap in responsive shape if not already
  if (isResponsiveShape(currentRaw)) {
    return { ...(currentRaw as object), [bp]: newValue };
  }
  // Plain literal → wrap it. The base MUST be a real value: when the prop had
  // never been set, `currentRaw` is undefined, `{ default: undefined, lg: x }`
  // loses the `default` key on JSON.stringify, and the schema is left holding
  // the base-less envelope `{ lg: x }`. pickResponsiveValue used to hand that
  // whole object back below lg, so the page printed {"lg":"ONLYLGHEADING"} to
  // the end user (audit probe probe_props_4). The resolver now returns
  // undefined instead of the envelope, and this side stops emitting a base-less
  // envelope at all: fall back to the registry default, and failing that to the
  // value being written, so the prop always has a mobile-first base.
  const base =
    currentRaw !== undefined
      ? currentRaw
      : descriptorDefault !== undefined && descriptorDefault !== null
        ? descriptorDefault
        : newValue;
  return { default: base, [bp]: newValue };
}

/** Re-parse an edited JSON string back to its typed value (number/array/object/
 * bool), falling back to the raw string when it isn't valid JSON. Keeps the
 * generic prop editor from stringifying typed props. */
function reparseProp(v: string): unknown {
  const t = v.trim();
  if (t === "") return v;
  try { return JSON.parse(t); } catch { return v; }
}

const GROUP_ORDER = ["content", "style", "state", "behavior", "data"] as const;

/**
 * Mirror of the renderer's syntheticNodeId from packages/renderer/src/runtime/dispatch.tsx.
 * Schemas from the legacy pipeline omit the id field; the renderer generates a stable
 * id from type + props at render time. We reproduce that here so the panel can locate
 * nodes even when the raw schema has no explicit ids.
 */
function syntheticNodeId(node: any): string {
  const key = node.type + JSON.stringify(node.props ?? {});
  let h = 0;
  for (let i = 0; i < key.length; i++) {
    h = ((h << 5) - h + key.charCodeAt(i)) | 0;
  }
  return `${node.type}_${(h >>> 0).toString(16)}`;
}

function resolveNodeId(node: any): string {
  return node.id ?? syntheticNodeId(node);
}

function findNodeInArtifacts(artifacts: any, nodeId: string):
  { pageId: string; node: any } | null {
  for (const [pageId, page] of Object.entries(artifacts?.pageSchemas ?? {})) {
    // Support both schema formats:
    //   - "new" format: { root: SchemaNode }
    //   - "legacy" format: { children: SchemaNode[] } — engine wraps in a synthetic Stack root
    const rootNode: any = (page as any).root
      ?? (Array.isArray((page as any).children)
        ? { type: "Stack", id: "_synthetic_root", children: (page as any).children }
        : null);

    const stack: any[] = [rootNode];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      const id = resolveNodeId(n);
      if (id === nodeId) return { pageId, node: { ...n, id } };
      if (Array.isArray(n.children)) stack.push(...n.children);
      if (n.slots && typeof n.slots === "object") {
        for (const arr of Object.values(n.slots) as any[]) {
          if (Array.isArray(arr)) stack.push(...arr);
        }
      }
    }
  }
  return null;
}

/**
 * Binding predicates come from @forge/patches, which is also what the reducer
 * and the commit guard use. They were duplicated here, which is how the editor
 * ended up able to WRITE a format it could also READ but nothing could RENDER.
 * One owner for the format now.
 *
 * `isBindingValue` still recognises the legacy {$binding} object as bound, so a
 * page that has not yet been through the load-time migration displays correctly
 * rather than showing the user a raw object in a text field.
 */
const isBindingValue = isBinding;
const bindingExpr = bindingExpression;

/** Props that hold row/record DATA and are almost always bound to a data source
 *  (Chart.data, Table.rows, list options/items, ActivityFeed.entries). For these
 *  we show the binding dropdown DIRECTLY — no "bind" toggle to hunt for — so a
 *  freshly-dropped component offers its data-source picker on sight. */
const DATA_SOURCE_PROPS = new Set(["data", "rows", "options", "items", "entries", "records"]);
/**
 * Prop types the panel can AUTHOR in place. Compared as strings on purpose:
 * "object" is being added to PropDescriptor["type"] in the registry package and
 * a literal comparison would not compile until that lands.
 */
const AUTHORABLE_TYPES = new Set<string>(["array", "object"]);
/**
 * `rows` is overloaded across the registry: Table/DataGrid mean "the array of
 * row objects" (bind it), while Textarea and Grid mean "how many rows" (type a
 * number into it). Matching on the NAME alone put a data-source dropdown on
 * Textarea.rows — and would have put one on Grid.rows, hiding the row-count
 * field this feature is built around. The registry already says which is which,
 * so ask it: a numeric prop is never a data source.
 *
 * The same question decides the array/object case, and it is not cosmetic. The
 * data-source branch below is an EITHER/OR: it renders BindingControl *instead
 * of* the registry's control and suppresses the bind toggle. So converting
 * `Select.options` / `RadioGroup.options` to `type:"array", control:"json"` was
 * correct in the registry and completely invisible in the editor — the user
 * still could not edit an option list (docs/editor-audit/input-components-2.md
 * D1), and the ~26 array props being converted alongside them would have been
 * shadowed the same way. A prop the panel can author gets its control AND the
 * bind toggle, like every other prop; only props with no authoring UI
 * (Chart.data and the rest still typed `action`/`binding`) surface the data
 * picker directly, so those keep exactly the affordance they had.
 */
function isDataSourcePropFor(propName: string, descriptor: PropDescriptor): boolean {
  return (
    DATA_SOURCE_PROPS.has(propName) &&
    descriptor.type !== "number" &&
    !AUTHORABLE_TYPES.has(descriptor.type)
  );
}
// Props that name a FIELD KEY in the bound data (chart axis / series keys). These
// get a data-aware dropdown of the source's keys instead of a free-text field.
const DATA_KEY_PROPS = new Set(["xKey", "yKey", "dataKey", "categoryKey", "nameKey", "valueKey", "angleKey"]);

/**
 * PropertiesPanelInner — all the logic/content without any outer chrome.
 * Consumed by PropertiesPanel (wrapped in <aside>) and PropsTokensSidebar
 * (used directly inside a tab container).
 */
export function PropertiesPanelInner() {
  const artifacts = useEditorStore(s => s.artifacts);
  const selectedIds = useEditorStore(s => s.selectedNodeIds);
  const dispatch = useEditorStore(s => s.dispatch);
  const dispatchBatch = useEditorStore(s => s.dispatchBatch);
  const projectId = useEditorStore(s => s.projectId);
  const [activeBp, setActiveBp] = useState<EditorBreakpoint>("default");
  /**
   * Props the user has switched into BIND MODE but not yet given an expression.
   *
   * Bound-ness used to be readable straight off the value, because an empty bind
   * was the object `{ $binding: "" }`. That object is exactly what broke the
   * node, so an empty bind is now `""` — and `""` is indistinguishable from an
   * ordinary empty literal. Without this set, clicking "bind" and pausing before
   * typing dropped you back to a plain text box.
   *
   * Bind-mode is an editor affordance, not document data, so it lives here and
   * never reaches the schema. Keyed by `nodeId::propName` so selecting a
   * different node does not inherit the previous one's pending binds.
   */
  const [pendingBinds, setPendingBinds] = useState<ReadonlySet<string>>(new Set());
  const bindKey = (propName: string) => `${selectedNodeId}::${propName}`;
  const markBinding = (propName: string, on: boolean) =>
    setPendingBinds((prev) => {
      const nextSet = new Set(prev);
      if (on) nextSet.add(bindKey(propName)); else nextSet.delete(bindKey(propName));
      return nextSet;
    });

  if (selectedIds.length === 0) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        Select a node on the canvas to edit its props.
      </div>
    );
  }

  if (selectedIds.length > 1) {
    return (
      <div className="p-3">
        <header className="pb-2 mb-3 border-b">
          <h3 className="font-semibold text-sm">{selectedIds.length} nodes selected</h3>
          <p className="text-xs text-muted-foreground break-all">
            {selectedIds.slice(0, 5).join(", ")}{selectedIds.length > 5 ? "…" : ""}
          </p>
        </header>
        <p className="text-xs text-muted-foreground">
          Multi-node prop editing is not supported yet. Select a single node to edit
          its props, or use Delete to remove all selected.
        </p>
      </div>
    );
  }

  // Single selection — use first id
  const selectedNodeId = selectedIds[0];

  if (!artifacts) {
    return <div className="p-4 text-sm">Loading…</div>;
  }

  const hit = findNodeInArtifacts(artifacts, selectedNodeId);
  if (!hit) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        Node {selectedNodeId} not found in artifacts (may be a synthetic id from a
        schema without explicit ids — edit the page schema JSON directly to add
        stable ids).
      </div>
    );
  }

  const { pageId, node } = hit;
  const entry = (starterRegistry as any)[node.type];

  return (
    <div className="p-3">
      <header className="pb-2 mb-3 border-b">
        <h3 className="font-semibold text-sm">{node.type}</h3>
        <p className="text-xs text-muted-foreground break-all">{node.id}</p>
        <div className="mt-2">
          <BreakpointSwitcher value={activeBp} onChange={setActiveBp} />
        </div>
      </header>

      {entry ? (
        // Registry-driven — group by content/style/state/behavior/data
        GROUP_ORDER.map((group) => {
          const inGroup = Object.entries(entry.props as Record<string, PropDescriptor>)
            .filter(([, d]) => d.group === group);
          if (inGroup.length === 0) return null;
          return (
            <fieldset key={group} className="mb-4 space-y-2.5">
              <legend className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {group}
              </legend>
              {inGroup.map(([propName, descriptor]) => {
                const rawValue = (node.props ?? {})[propName];
                const currentValue = readPropAtBp(node, propName, activeBp, descriptor.default);
                // For bind checks, inspect the raw value (not the bp-resolved one)
                const isBound = isBindingValue(rawValue) || pendingBinds.has(bindKey(propName));
                // Data-source props always surface the binding dropdown (bound or not),
                // so a just-dropped Chart/Table shows its picker without hunting a toggle.
                const isDataSourceProp = isDataSourcePropFor(propName, descriptor);
                const showBinding = isBound || isDataSourceProp;
                const Control = (CONTROL_BY_TYPE as any)[descriptor.control] ?? TextControl;
                const required = isRequiredProp(node.type, propName);
                return (
                  <div key={propName} className="space-y-1">
                    <div className="flex items-center justify-end gap-1">
                      {required && (
                        // Visible text, not a coloured asterisk: the failure this
                        // fixes is a node that renders BLANK with no explanation,
                        // and a glyph the user has to decode is barely better.
                        <span
                          className="mr-auto text-[10px] font-medium uppercase tracking-wide text-destructive"
                          title={`${propName} is required — the component renders blank without it`}
                        >
                          required
                        </span>
                      )}
                      {!isDataSourceProp && (
                        <BindToggle
                          propName={propName}
                          isBound={isBound}
                          onToggle={() => {
                            if (isBound) {
                              markBinding(propName, false);
                              dispatch({
                                type: "unbindProp",
                                pageId,
                                nodeId: selectedNodeId,
                                propName,
                                literalValue: descriptor.default ?? "",
                              });
                            } else {
                              // Remember the INTENT. The dispatch writes "" (an
                              // empty bind must not become the template "{{}}"),
                              // which is indistinguishable from an empty literal,
                              // so the panel has to hold the mode itself.
                              markBinding(propName, true);
                              dispatch({
                                type: "bindProp",
                                pageId,
                                nodeId: selectedNodeId,
                                propName,
                                binding: "",
                              });
                            }
                          }}
                        />
                      )}
                    </div>
                    {showBinding ? (
                      <BindingControl
                        label={propName}
                        pageId={pageId}
                        value={isBound ? bindingExpr(rawValue) : (typeof rawValue === "string" ? rawValue : "")}
                        onChange={(v) => {
                          // ONE FORMAT. This used to fork: data-source props and
                          // already-mustache values wrote a "{{…}}" string, while
                          // everything else went through bindProp and got the
                          // {$binding} object that no renderer understands. Both
                          // paths now produce the same string, so bindProp is the
                          // single entry point and the fork is gone.
                          dispatch({
                            type: "bindProp", pageId, nodeId: selectedNodeId,
                            propName, binding: v,
                          });
                          // Binding a Chart's `data` to a series source is useless
                          // without an axis + series mapping. A series resolves to
                          // [{label,value}], so auto-set xKey/series/chartType (only
                          // when unset) so the chart renders in one step instead of
                          // leaving the user to hand-edit the series array.
                          if (node.type === "Chart" && propName === "data" && typeof v === "string" && v) {
                            const srcName = v.replace(/[{}]/g, "").trim().split(/[.[]/)[0];
                            const fresh = useEditorStore.getState().artifacts as any;
                            const src = fresh?.pageSchemas?.[pageId]?.dataSources?.find(
                              (s: any) => s?.name === srcName,
                            );
                            if (src?.op === "series") {
                              const p = node.props ?? {};
                              if (!p.xKey || p.xKey === "date") {
                                dispatch({ type: "updateProp", pageId, nodeId: selectedNodeId, propName: "xKey", value: "label" });
                              }
                              if (!Array.isArray(p.series) || p.series.length === 0) {
                                dispatch({ type: "updateProp", pageId, nodeId: selectedNodeId, propName: "series", value: [{ name: src.name, dataKey: "value" }] });
                              }
                              if (!p.chartType) {
                                dispatch({ type: "updateProp", pageId, nodeId: selectedNodeId, propName: "chartType", value: "bar" });
                              }
                            }
                          }
                        }}
                        placeholder="pick a data source, or form.field / state.x"
                      />
                    ) : DATA_KEY_PROPS.has(propName) ? (
                      <DataKeyControl
                        label={propName}
                        value={currentValue}
                        pageId={pageId}
                        node={node}
                        onChange={(v: any) => dispatch({
                          type: "updateProp", pageId, nodeId: selectedNodeId,
                          propName,
                          // NORMALISE AT THIS BOUNDARY TOO.
                          //
                          // `buildDroppedNode` already runs `normalizeSeed` so a
                          // freshly dropped node is schema-valid, but this panel is
                          // the OTHER prop-write boundary and passed the control's
                          // raw output straight through. A `<select>` yields a
                          // string, so choosing LEVEL 3 on a Heading wrote
                          // `level: "3"` against `z.number()` — the drop was valid
                          // and the first edit invalidated it. Same descriptor-keyed
                          // rule, one shared function, both boundaries.
                          value: writePropAtBp(
                            rawValue, activeBp, normalizeSeed(descriptor, v), descriptor.default,
                          ),
                        })}
                      />
                    ) : (
                      <Control
                        label={propName}
                        value={currentValue}
                        options={descriptor.options}
                        // Context for controls that need to know what they are
                        // editing, not just its value. ImageControl uses all
                        // four; every other control ignores them.
                        imageShape={descriptor.imageShape}
                        nodeType={node.type}
                        nodeProps={node.props ?? {}}
                        projectId={projectId}
                        onChange={(v: any) => {
                          const next = writePropAtBp(rawValue, activeBp, v, descriptor.default);
                          // Changing a Grid's rows/columns has to move CELLS,
                          // not just write a number — otherwise the prop says
                          // 3x3 and the canvas still shows four boxes. Only at
                          // the default breakpoint: a per-breakpoint override
                          // writes a { default, lg } object, and there is one
                          // set of cells in the schema, not one per viewport.
                          const batch =
                            activeBp === "default"
                              ? gridStructureActions(pageId, node, propName, next, artifacts)
                              : null;
                          if (batch) dispatchBatch(batch);
                          else dispatch({
                            type: "updateProp", pageId, nodeId: selectedNodeId,
                            propName, value: next,
                          });
                        }}
                      />
                    )}
                  </div>
                );
              })}
            </fieldset>
          );
        })
      ) : (
        // Generic fallback — list whatever props the node currently has
        <fieldset className="space-y-2.5">
          <legend className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            props (no registry entry — generic editor)
          </legend>
          {Object.keys(node.props ?? {}).length === 0 && (
            <p className="text-xs text-muted-foreground italic">No props on this node.</p>
          )}
          {Object.entries(node.props ?? {}).map(([propName, value]) => (
            <TextControl
              key={propName}
              label={propName}
              value={typeof value === "string" ? value : JSON.stringify(value)}
              onChange={(v) => dispatch({
                type: "updateProp", pageId, nodeId: selectedNodeId,
                // Preserve the value's TYPE. A non-string prop (number/array/
                // object/bool) was edited as JSON text — re-parse it so we don't
                // silently coerce e.g. `count: 5` into the string "5". Falls back
                // to the raw string when it isn't valid JSON (a plain string).
                propName,
                value: typeof value === "string" ? v : reparseProp(v),
              })}
            />
          ))}
        </fieldset>
      )}
    </div>
  );
}

/**
 * PropertiesPanel — backwards-compatible export with full <aside> chrome.
 * Used standalone (e.g. when PropsTokensSidebar is not available yet).
 */
export function PropertiesPanel() {
  return (
    <aside className="w-72 border-l p-3 bg-muted/20 overflow-y-auto h-full">
      <PropertiesPanelInner />
    </aside>
  );
}

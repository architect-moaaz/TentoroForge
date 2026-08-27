"use client";
import * as React from "react";
import { useEditorStore } from "@/lib/editor-store";
import { BindingControl } from "./PropControls/BindingControl";

const sectionLabelCls =
  "block px-3 py-2 text-[10px] font-semibold tracking-wider text-muted-foreground uppercase";

const MUSTACHE_RE = /\{\{[\s\S]+?\}\}/;
const isMustache = (v: unknown): boolean => typeof v === "string" && MUSTACHE_RE.test(v);
/** Inner expression from either binding form, for the BindingControl value. */
function innerExpr(v: unknown): string {
  if (v && typeof v === "object" && "$binding" in (v as any)) return String((v as any).$binding ?? "");
  if (typeof v === "string") {
    const m = v.match(/\{\{\s*([\s\S]*?)\s*\}\}/);
    return m ? m[1] : v;
  }
  return "";
}

function findNodeAndPage(
  artifacts: any,
  nodeId: string | null,
): { pageId: string; node: any } | null {
  if (!nodeId || !artifacts) return null;
  for (const [pageId, page] of Object.entries(artifacts.pageSchemas ?? {})) {
    const stack: any[] = [(page as any).root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      if (n.id === nodeId) return { pageId, node: n };
      if (Array.isArray(n.children)) stack.push(...n.children);
      // Traverse named slots too — otherwise a slot-resident node (editable in
      // Props/Style) shows "Node not in artifacts" here.
      if (n.slots && typeof n.slots === "object") {
        for (const arr of Object.values(n.slots) as any[]) {
          if (Array.isArray(arr)) stack.push(...arr);
        }
      }
    }
  }
  return null;
}

function collectBindings(node: any): Array<{ propPath: string; binding: string }> {
  const out: Array<{ propPath: string; binding: string }> = [];
  const walk = (obj: any, prefix: string) => {
    if (!obj || typeof obj !== "object") return;
    // Detect the $binding KEY presence (not truthiness) so a freshly-toggled
    // bind — which starts as { $binding: "" } — is listed instead of silently
    // hidden. An empty binding renders with an "unset" hint below.
    if ("$binding" in (obj as any)) {
      out.push({ propPath: prefix, binding: String((obj as any).$binding ?? "") });
      return;
    }
    if (typeof obj === "string" && obj.includes("{{") && obj.includes("}}")) {
      out.push({ propPath: prefix, binding: obj });
      return;
    }
    for (const [k, v] of Object.entries(obj)) {
      if (typeof v === "string" && v.includes("{{")) {
        out.push({ propPath: `${prefix}.${k}`, binding: v });
      } else if (v && typeof v === "object" && !Array.isArray(v)) {
        walk(v, prefix ? `${prefix}.${k}` : k);
      }
    }
  };
  walk(node.props ?? {}, "");
  return out;
}

export function BindingsPanel() {
  const artifacts = useEditorStore((s) => s.artifacts);
  const selectedNodeId = useEditorStore((s) => s.selectedNodeId);
  const selectedCount = useEditorStore((s) => s.selectedNodeIds.length);
  const dispatch = useEditorStore((s) => s.dispatch);
  const hit = findNodeAndPage(artifacts, selectedNodeId);

  if (selectedCount > 1) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        {selectedCount} nodes selected — select a single node to edit its bindings.
      </div>
    );
  }

  if (!selectedNodeId) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        Select a node to see its bindings.
      </div>
    );
  }
  if (!hit) {
    return (
      <div className="p-4 text-sm text-muted-foreground">Node not in artifacts.</div>
    );
  }

  const bindings = collectBindings(hit.node);
  if (bindings.length === 0) {
    return (
      <div className="p-4 text-sm text-muted-foreground space-y-2">
        <p>No bindings on this node.</p>
        <p className="text-xs">
          Use the bind toggle in the Props tab to wrap a value in{" "}
          <code>{"{{ ... }}"}</code>.
        </p>
      </div>
    );
  }

  return (
    <div className="py-2">
      <span className={sectionLabelCls}>Active bindings</span>
      <ul className="px-3 space-y-3">
        {bindings.map((b, i) => {
          // collectBindings prefixes top-level {{…}} string props with a leading
          // dot (".value"); strip it. Top-level props (no remaining dot) are
          // editable via the grouped dropdown; nested paths (delta.value) stay
          // read-only — updateProp targets a top-level prop name.
          const path = b.propPath.replace(/^\./, "");
          const topLevel = !!path && !path.includes(".");
          const rawValue = topLevel ? (hit.node.props ?? {})[path] : undefined;

          if (!topLevel) {
            return (
              <li key={i} className="rounded border bg-muted/30 px-2.5 py-1.5 text-xs">
                <div className="font-mono text-muted-foreground">{path || "<root>"}</div>
                <div className="font-mono text-blue-700 dark:text-blue-300 truncate" title={b.binding}>
                  {b.binding}
                </div>
              </li>
            );
          }

          return (
            <li key={i}>
              <BindingControl
                label={path}
                pageId={hit.pageId}
                value={innerExpr(rawValue)}
                onChange={(v) => {
                  if (isMustache(rawValue) || typeof rawValue === "string") {
                    dispatch({
                      type: "updateProp",
                      pageId: hit.pageId,
                      nodeId: selectedNodeId,
                      propName: path,
                      value: v ? `{{${v}}}` : "",
                    });
                  } else {
                    dispatch({
                      type: "bindProp",
                      pageId: hit.pageId,
                      nodeId: selectedNodeId,
                      propName: path,
                      binding: v,
                    });
                  }
                }}
              />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

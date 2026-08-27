"use client";

import { useState } from "react";
import type { NodeRendererProps, ActionDef, IRNode } from "../types";
import { NodeWrapper } from "../NodeWrapper";
import { RenderNode } from "../RenderNode";
import { useRendererContext } from "../RendererContext";
import { resolveBinding } from "../bindings";
import { executeAction } from "../actions";
import { buildClasses, paddingClasses, radiusClass } from "../tokens";

export function DataTableRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const columns = (node.columns as Array<{ key: string; label?: string; width?: string; render?: IRNode }>) ?? [];
  const rawData = resolveBinding(node.data, ctx);
  const data = Array.isArray(rawData) ? rawData : [];

  // Use placeholder data if no real data
  const displayData = data.length > 0 ? data : Array.from({ length: 3 }, (_, i) => {
    const row: Record<string, string> = {};
    for (const col of columns) row[col.key] = `Sample ${col.key} ${i + 1}`;
    return row;
  });

  return (
    <NodeWrapper node={node} path={path}>
      <div className="w-full overflow-auto border border-gray-200 rounded-lg">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {columns.map((col, i) => (
                <th key={i} className="text-left px-4 py-3 font-medium text-gray-600" style={col.width ? { width: col.width } : undefined}>
                  {col.label ?? col.key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {displayData.map((row, ri) => (
              <tr
                key={ri}
                className={buildClasses("hover:bg-gray-50", node.onRowClick ? "cursor-pointer" : undefined)}
                onClick={() => node.onRowClick && executeAction(node.onRowClick as ActionDef, ctx)}
              >
                {columns.map((col, ci) => (
                  <td key={ci} className="px-4 py-3 text-gray-900">
                    {col.render ? (
                      <RenderNode node={col.render} path={[...path, ri, ci]} />
                    ) : (
                      String((row as Record<string, unknown>)[col.key] ?? "")
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {node.pagination ? (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 bg-gray-50">
            <span className="text-sm text-gray-500">{displayData.length} items</span>
            <div className="flex gap-1">
              <button className="px-3 py-1 text-sm border rounded hover:bg-gray-100">Previous</button>
              <button className="px-3 py-1 text-sm border rounded hover:bg-gray-100">Next</button>
            </div>
          </div>
        ) : null}
      </div>
    </NodeWrapper>
  );
}

export function FormRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const fields = (node.fields as Array<IRNode & { field?: string }>) ?? [];
  const actions = (node.actions as IRNode[]) ?? [];

  return (
    <NodeWrapper node={node} path={path}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (node.onSubmit) executeAction(node.onSubmit as ActionDef, ctx);
        }}
      >
        {/* Render form fields — each has a node type (TextInput, Select, etc.) */}
        {fields.map((field, i) => {
          const fieldNode: IRNode = {
            ...field,
            // Map field-level bind to form state path
            bind: field.bind ?? (node.bind ? `${String(node.bind)}.${field.field ?? field.name ?? `field_${i}`}` : undefined),
          };
          return <RenderNode key={i} node={fieldNode} path={[...path, i]} />;
        })}

        {/* Render explicit children (if any) */}
        {(node.children ?? []).map((child, i) => (
          <RenderNode key={`c${i}`} node={child} path={[...path, fields.length + i]} />
        ))}

        {/* Render form actions (submit buttons, etc.) */}
        {actions.map((action, i) => (
          <RenderNode key={`a${i}`} node={action} path={[...path, fields.length + (node.children?.length ?? 0) + i]} />
        ))}
      </form>
    </NodeWrapper>
  );
}

export function CardRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const cls = buildClasses(
    "bg-white border border-gray-200 overflow-hidden",
    radiusClass((node.radius as string) ?? "md"),
    node.shadow === "sm" && "shadow-sm",
    node.shadow === "md" && "shadow-md",
    node.hoverable ? "hover:shadow-md transition-shadow cursor-pointer" : undefined,
    node.selected ? "ring-2 ring-blue-500" : undefined,
  );

  const header = node.header as IRNode | undefined;
  const media = node.media as IRNode | undefined;
  const footer = node.footer as IRNode | undefined;

  return (
    <NodeWrapper node={node} path={path}>
      <div
        className={cls}
        onClick={() => node.action && executeAction(node.action as ActionDef, ctx)}
      >
        {header && (
          <div className="px-4 py-3 border-b border-gray-100">
            <RenderNode node={header} path={[...path, -1]} />
          </div>
        )}
        {media && (
          <div>
            <RenderNode node={media} path={[...path, -2]} />
          </div>
        )}
        <div className={paddingClasses((node.padding as string) ?? "md")}>
          {(node.children ?? []).map((child, i) => (
            <RenderNode key={i} node={child} path={[...path, i]} />
          ))}
        </div>
        {footer && (
          <div className="px-4 py-3 border-t border-gray-100 bg-gray-50">
            <RenderNode node={footer} path={[...path, -3]} />
          </div>
        )}
      </div>
    </NodeWrapper>
  );
}

export function TabsRenderer({ node, path }: NodeRendererProps) {
  const tabs = (node.tabs as Array<{ id: string; label: string; content: IRNode }>) ?? [];
  const [activeTab, setActiveTab] = useState((node.defaultTab as string) ?? tabs[0]?.id ?? "");
  const variant = (node.variant as string) ?? "underline";

  return (
    <NodeWrapper node={node} path={path}>
      <div>
        <div className={buildClasses("flex gap-0", variant === "underline" && "border-b border-gray-200")}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={buildClasses(
                "px-4 py-2 text-sm font-medium transition-colors",
                variant === "underline" && (
                  activeTab === tab.id
                    ? "border-b-2 border-blue-600 text-blue-600"
                    : "text-gray-500 hover:text-gray-700"
                ),
                variant === "pills" && (
                  activeTab === tab.id
                    ? "bg-blue-100 text-blue-700 rounded-md"
                    : "text-gray-500 hover:bg-gray-100 rounded-md"
                ),
                variant === "enclosed" && (
                  activeTab === tab.id
                    ? "bg-white border border-gray-200 border-b-white rounded-t-md -mb-px"
                    : "text-gray-500 hover:text-gray-700"
                ),
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="pt-4">
          {tabs.map((tab) =>
            activeTab === tab.id ? (
              <RenderNode key={tab.id} node={tab.content} path={[...path, tabs.indexOf(tab)]} />
            ) : null,
          )}
        </div>
      </div>
    </NodeWrapper>
  );
}

export function AccordionRenderer({ node, path }: NodeRendererProps) {
  const items = (node.items as Array<{ id: string; label: string; content: IRNode }>) ?? [];
  const [openItems, setOpenItems] = useState<Set<string>>(new Set());
  const multiple = node.type === "multiple";

  const toggle = (id: string) => {
    setOpenItems((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        if (!multiple) next.clear();
        next.add(id);
      }
      return next;
    });
  };

  return (
    <NodeWrapper node={node} path={path}>
      <div className="divide-y divide-gray-200 border border-gray-200 rounded-lg">
        {items.map((item, i) => (
          <div key={item.id}>
            <button onClick={() => toggle(item.id)} className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-left hover:bg-gray-50">
              {item.label}
              <span className={buildClasses("transition-transform", openItems.has(item.id) && "rotate-180")}>&#9662;</span>
            </button>
            {openItems.has(item.id) && (
              <div className="px-4 pb-3">
                <RenderNode node={item.content} path={[...path, i]} />
              </div>
            )}
          </div>
        ))}
      </div>
    </NodeWrapper>
  );
}

export function ModalTriggerRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const modalName = node.modal as string;

  return (
    <NodeWrapper node={node} path={path}>
      <div onClick={() => modalName && ctx.toggleModal(modalName)} className="cursor-pointer">
        {(node.children ?? []).map((child, i) => (
          <RenderNode key={i} node={child} path={[...path, i]} />
        ))}
      </div>
    </NodeWrapper>
  );
}

export function ChartRenderer({ node, path }: NodeRendererProps) {
  const chartType = (node.type as string) ?? "bar";
  const height = (node.height as string) ?? "300px";

  return (
    <NodeWrapper node={node} path={path}>
      <div
        className="flex items-center justify-center border border-gray-200 rounded-lg bg-gray-50 text-gray-400 text-sm"
        style={{ height }}
      >
        {chartType.charAt(0).toUpperCase() + chartType.slice(1)} Chart
      </div>
    </NodeWrapper>
  );
}

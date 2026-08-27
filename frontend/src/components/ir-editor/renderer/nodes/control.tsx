"use client";

import { useMemo } from "react";
import type { NodeRendererProps, IRNode, RendererContext } from "../types";
import { NodeWrapper } from "../NodeWrapper";
import { RenderNode } from "../RenderNode";
import { useRendererContext } from "../RendererContext";
import { resolveBinding, resolveExpression } from "../bindings";

export function SlotRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();

  // if/then/else mode
  if (node.if != null) {
    const condition = resolveExpression(String(node.if), ctx);
    const branch = condition ? (node.then as IRNode) : (node.else as IRNode | undefined);

    if (ctx.editable) {
      // Show both branches in edit mode
      return (
        <NodeWrapper node={node} path={path}>
          <div className="space-y-1">
            <div className={condition ? "opacity-100" : "opacity-30"}>
              <div className="text-[10px] text-green-600 font-mono">{"if: "}{String(node.if)}</div>
              {Boolean(node.then) && <RenderNode node={node.then as IRNode} path={[...path, 0]} />}
            </div>
            {Boolean(node.else) && (
              <div className={!condition ? "opacity-100" : "opacity-30"}>
                <div className="text-[10px] text-orange-600 font-mono">else</div>
                <RenderNode node={node.else as IRNode} path={[...path, 1]} />
              </div>
            )}
          </div>
        </NodeWrapper>
      );
    }

    if (!branch) return null;
    return (
      <NodeWrapper node={node} path={path}>
        <RenderNode node={branch} path={[...path, condition ? 0 : 1]} />
      </NodeWrapper>
    );
  }

  // switch/cases mode
  if (node.switch != null) {
    const switchValue = String(resolveBinding(node.switch, ctx) ?? "");
    const cases = (node.cases as Record<string, IRNode>) ?? {};
    const matchedCase = cases[switchValue] ?? cases["default"];

    if (ctx.editable) {
      return (
        <NodeWrapper node={node} path={path}>
          <div className="space-y-1">
            <div className="text-[10px] text-purple-600 font-mono">switch: {String(node.switch)} = &quot;{switchValue}&quot;</div>
            {Object.entries(cases).map(([key, caseNode], i) => (
              <div key={key} className={key === switchValue || (key === "default" && !cases[switchValue]) ? "opacity-100" : "opacity-30"}>
                <div className="text-[10px] text-gray-500 font-mono">case: {key}</div>
                <RenderNode node={caseNode} path={[...path, i]} />
              </div>
            ))}
          </div>
        </NodeWrapper>
      );
    }

    if (!matchedCase) return null;
    return (
      <NodeWrapper node={node} path={path}>
        <RenderNode node={matchedCase} path={[...path, Object.keys(cases).indexOf(switchValue)]} />
      </NodeWrapper>
    );
  }

  return null;
}

export function RepeaterRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const rawData = resolveBinding(node.data, ctx);
  const data = Array.isArray(rawData) ? rawData : [];
  const template = node.template as IRNode | undefined;
  const emptyState = node.emptyState as IRNode | undefined;
  const variable = (node.variable as string) ?? "item";
  const limit = node.limit as number | undefined;
  const direction = (node.direction as string) ?? "col";
  const gap = (node.gap as string) ?? "md";

  const displayData = limit ? data.slice(0, limit) : data;

  // Show placeholder data in edit mode if empty
  const showPlaceholder = displayData.length === 0 && ctx.editable;
  const placeholderData = showPlaceholder
    ? [{ __placeholder: true, __index: 0 }, { __placeholder: true, __index: 1 }]
    : [];

  const items = showPlaceholder ? placeholderData : displayData;

  if (items.length === 0 && emptyState) {
    return (
      <NodeWrapper node={node} path={path}>
        <RenderNode node={emptyState} path={[...path, 0]} />
      </NodeWrapper>
    );
  }

  if (!template) return null;

  const GAP_MAP: Record<string, string> = { xs: "gap-1", sm: "gap-2", md: "gap-4", lg: "gap-6", xl: "gap-8" };

  return (
    <NodeWrapper node={node} path={path}>
      <div className={`flex ${direction === "row" ? "flex-row flex-wrap" : "flex-col"} ${GAP_MAP[gap] ?? "gap-4"}`}>
        {items.map((item, i) => (
          <RepeaterItem key={i} item={item} index={i} variable={variable} template={template} path={path} parentCtx={ctx} />
        ))}
      </div>
    </NodeWrapper>
  );
}

function RepeaterItem({
  item,
  index,
  variable,
  template,
  path,
  parentCtx,
}: {
  item: unknown;
  index: number;
  variable: string;
  template: IRNode;
  path: NodeRendererProps["path"];
  parentCtx: RendererContext;
}) {
  // Create a child context with the iterator scope
  const childCtx: RendererContext = useMemo(
    () => ({
      ...parentCtx,
      iteratorScope: { variable, index, value: item },
    }),
    [parentCtx, variable, index, item],
  );

  // We need to provide this context — but since we use useRendererContext() inside RenderNode,
  // we wrap with a mini-provider that overrides just the iterator scope.
  return (
    <IteratorProvider ctx={childCtx}>
      <RenderNode node={template} path={[...path, index]} />
    </IteratorProvider>
  );
}

// Mini context override for iterator scope
import { createContext, useContext } from "react";

const IteratorOverrideCtx = createContext<RendererContext | null>(null);

function IteratorProvider({ ctx, children }: { ctx: RendererContext; children: React.ReactNode }) {
  return <IteratorOverrideCtx.Provider value={ctx}>{children}</IteratorOverrideCtx.Provider>;
}

// Export for use in RendererContext — nodes inside a Repeater should check this first
export function useIteratorContext(): RendererContext | null {
  return useContext(IteratorOverrideCtx);
}

export function AsyncSlotRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const sourceName = node.data as string;
  const source = sourceName ? ctx.dataSources[sourceName.replace("source:", "")] : undefined;

  // Loading state
  if (source?.isLoading) {
    const loadingNode = node.loading as IRNode | undefined;
    if (loadingNode) return <RenderNode node={loadingNode} path={[...path, 0]} />;
    return (
      <NodeWrapper node={node} path={path}>
        <div className="animate-pulse space-y-2">
          <div className="h-4 bg-gray-200 rounded w-3/4" />
          <div className="h-4 bg-gray-200 rounded w-1/2" />
        </div>
      </NodeWrapper>
    );
  }

  // Error state
  if (source?.error) {
    const errorNode = node.error as IRNode | undefined;
    if (errorNode) return <RenderNode node={errorNode} path={[...path, 1]} />;
    return (
      <NodeWrapper node={node} path={path}>
        <div className="text-sm text-red-500">Error loading data</div>
      </NodeWrapper>
    );
  }

  // Success — render children
  return (
    <NodeWrapper node={node} path={path}>
      {(node.children ?? []).map((child, i) => (
        <RenderNode key={i} node={child} path={[...path, i]} />
      ))}
    </NodeWrapper>
  );
}

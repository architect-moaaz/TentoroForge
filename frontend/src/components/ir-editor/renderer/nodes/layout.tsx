"use client";

import type { NodeRendererProps } from "../types";
import { NodeWrapper } from "../NodeWrapper";
import { RenderNode } from "../RenderNode";
import { buildClasses, gapClass, paddingClasses, alignClass, justifyClass, widthClass, heightClass } from "../tokens";

/**
 * Resolve the `style` property from an IR node.
 * Figma-converted nodes carry inline styles (background, gradients, colors).
 */
function resolveStyle(node: NodeRendererProps["node"]): React.CSSProperties {
  const s: React.CSSProperties = {};
  const nodeStyle = node.style as Record<string, unknown> | undefined;

  if (nodeStyle) {
    if (nodeStyle.background) s.background = String(nodeStyle.background);
    if (nodeStyle.color) s.color = String(nodeStyle.color);
    if (nodeStyle.fontSize) s.fontSize = Number(nodeStyle.fontSize);
    if (nodeStyle.fontWeight) s.fontWeight = Number(nodeStyle.fontWeight) || String(nodeStyle.fontWeight);
    if (nodeStyle.borderRadius) s.borderRadius = String(nodeStyle.borderRadius);
    if (nodeStyle.border) s.border = String(nodeStyle.border);
    if (nodeStyle.boxShadow) s.boxShadow = String(nodeStyle.boxShadow);
    if (nodeStyle.opacity != null) s.opacity = Number(nodeStyle.opacity);
    if (nodeStyle.minHeight) s.minHeight = String(nodeStyle.minHeight);
    if (nodeStyle.maxWidth) s.maxWidth = String(nodeStyle.maxWidth);
    if (nodeStyle.overflow) s.overflow = nodeStyle.overflow as React.CSSProperties["overflow"];
  }

  // Width/height as inline styles for percentage/pixel values
  const w = node.width as string;
  if (w && (w.includes("%") || w.includes("px") || w.includes("rem"))) {
    s.width = w;
  }
  const h = node.height as string;
  if (h && (h.includes("%") || h.includes("px") || h.includes("rem"))) {
    s.height = h;
  }
  if (h === "screen") s.minHeight = "100vh";

  return s;
}

export function StackRenderer({ node, path }: NodeRendererProps) {
  const cls = buildClasses(
    "flex flex-col",
    gapClass(node.gap as string),
    paddingClasses(node.padding as string),
    alignClass(node.align as string),
    justifyClass(node.justify as string),
    widthClass(node.width as string),
    heightClass(node.height as string),
    node.scroll ? "overflow-auto" : undefined,
    node.wrap ? "flex-wrap" : undefined,
    node.flex ? `flex-${node.flex}` : undefined,
  );

  const style = resolveStyle(node);

  return (
    <NodeWrapper node={node} path={path}>
      <div className={cls} style={Object.keys(style).length > 0 ? style : undefined}>
        {(node.children ?? []).map((child, i) => (
          <RenderNode key={i} node={child} path={[...path, i]} />
        ))}
      </div>
    </NodeWrapper>
  );
}

export function RowRenderer({ node, path }: NodeRendererProps) {
  const cls = buildClasses(
    "flex flex-row",
    gapClass(node.gap as string),
    paddingClasses(node.padding as string),
    alignClass(node.align as string),
    justifyClass(node.justify as string),
    node.scroll ? "overflow-auto" : undefined,
    node.wrap ? "flex-wrap" : undefined,
    node.flex ? `flex-${node.flex}` : undefined,
  );

  // Don't use Tailwind width/height classes for Row — use inline style
  // so percentage widths on children work correctly
  const style = resolveStyle(node);

  return (
    <NodeWrapper node={node} path={path}>
      <div className={cls} style={Object.keys(style).length > 0 ? style : undefined}>
        {(node.children ?? []).map((child, i) => (
          <RenderNode key={i} node={child} path={[...path, i]} />
        ))}
      </div>
    </NodeWrapper>
  );
}

export function GridRenderer({ node, path }: NodeRendererProps) {
  const cols = node.columns ?? 2;
  const cls = buildClasses(
    "grid",
    `grid-cols-${cols}`,
    gapClass(node.gap as string),
    paddingClasses(node.padding as string),
    widthClass(node.width as string),
  );

  const style = resolveStyle(node);

  return (
    <NodeWrapper node={node} path={path}>
      <div className={cls} style={Object.keys(style).length > 0 ? style : undefined}>
        {(node.children ?? []).map((child, i) => (
          <RenderNode key={i} node={child} path={[...path, i]} />
        ))}
      </div>
    </NodeWrapper>
  );
}

export function SpacerRenderer({ node, path }: NodeRendererProps) {
  const SPACING_PX: Record<string, number> = {
    xs: 4, sm: 8, md: 16, lg: 24, xl: 32, "2xl": 48,
  };
  const size = node.size as string ?? "md";
  const px = SPACING_PX[size] ?? 16;

  return (
    <NodeWrapper node={node} path={path}>
      <div style={{ height: px }} />
    </NodeWrapper>
  );
}

export function DividerRenderer({ node, path }: NodeRendererProps) {
  const isVertical = node.direction === "vertical";

  return (
    <NodeWrapper node={node} path={path}>
      {isVertical ? (
        <div className="w-px bg-gray-200 self-stretch" />
      ) : Boolean(node.label) ? (
        <div className="flex items-center gap-3 w-full">
          <div className="flex-1 h-px bg-gray-200" />
          <span className="text-xs text-gray-500">{String(node.label)}</span>
          <div className="flex-1 h-px bg-gray-200" />
        </div>
      ) : (
        <hr className="border-gray-200 w-full" />
      )}
    </NodeWrapper>
  );
}

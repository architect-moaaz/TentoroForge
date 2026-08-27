"use client";

import type { NodeRendererProps, ActionDef } from "../types";
import { NodeWrapper } from "../NodeWrapper";
import { useRendererContext } from "../RendererContext";
import { resolveBinding } from "../bindings";
import { executeAction } from "../actions";
import { buildClasses, resolveTypography, textColorClass, iconSizeClass, avatarSizeClass, radiusClass } from "../tokens";
import { useIREditorStore } from "@/stores/ir-editor";

export function TextRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const { element: Tag, classes: typoClasses } = resolveTypography(node.typography as string);
  const content = resolveBinding(node.content, ctx);

  const cls = buildClasses(
    typoClasses,
    node.weight ? `font-${node.weight}` : undefined,
    textColorClass(node.color as string),
    node.align ? `text-${node.align}` : undefined,
    node.truncate ? "truncate" : undefined,
    node.monospace ? "font-mono" : undefined,
  );

  // Apply inline style from Figma-converted nodes
  const nodeStyle = node.style as Record<string, unknown> | undefined;
  const inlineStyle: React.CSSProperties = {};
  if (nodeStyle?.color) inlineStyle.color = String(nodeStyle.color);
  if (nodeStyle?.fontSize) inlineStyle.fontSize = Number(nodeStyle.fontSize);
  if (nodeStyle?.fontWeight) inlineStyle.fontWeight = Number(nodeStyle.fontWeight) || String(nodeStyle.fontWeight);

  const Element = Tag as React.ElementType;
  return (
    <NodeWrapper node={node} path={path}>
      <Element className={cls} style={Object.keys(inlineStyle).length > 0 ? inlineStyle : undefined}>{content != null ? String(content) : ""}</Element>
    </NodeWrapper>
  );
}

export function IconRenderer({ node, path }: NodeRendererProps) {
  const name = (node.name as string) ?? "circle";
  const sizeClass = iconSizeClass(node.size as string);
  const colorClass = textColorClass(node.color as string);

  return (
    <NodeWrapper node={node} path={path}>
      <span className={buildClasses("inline-flex items-center justify-center", sizeClass, colorClass)} title={name}>
        {/* Placeholder icon — actual Lucide integration would use dynamic imports */}
        <svg className={sizeClass} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
        </svg>
      </span>
    </NodeWrapper>
  );
}

export function ImageRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const rawSrc = resolveBinding(node.src, ctx);
  const alt = (node.alt as string) ?? "";
  const fit = (node.fit as string) ?? "contain";

  // Resolve image paths: /images/... → backend asset endpoint
  let src = rawSrc ? String(rawSrc) : "";
  if (src.startsWith("/images/") && typeof window !== "undefined") {
    const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
    // Use the IR editor store's projectId (output dir name)
    const irStore = useIREditorStore.getState();
    const outputDirId = irStore.projectId || "";
    if (outputDirId) {
      src = `${API_BASE}/api/projects/${outputDirId}/asset?path=public${src}`;
    }
  }

  const nodeStyle = node.style as Record<string, unknown> | undefined;
  const inlineStyle: React.CSSProperties = {};
  if (nodeStyle?.width) inlineStyle.width = String(nodeStyle.width);
  if (nodeStyle?.height) inlineStyle.height = String(nodeStyle.height);
  if (node.width) inlineStyle.width = String(node.width);
  if (node.height) inlineStyle.height = String(node.height);

  const cls = buildClasses(
    radiusClass(node.radius as string),
    `object-${fit}`,
  );

  return (
    <NodeWrapper node={node} path={path}>
      {src ? (
        <img src={src} alt={alt} className={cls} style={Object.keys(inlineStyle).length > 0 ? inlineStyle : undefined} />
      ) : (
        <div className={buildClasses("bg-gray-100 flex items-center justify-center text-gray-400 text-xs")} style={{ minHeight: 40, minWidth: 40, ...inlineStyle }}>
          {alt || "Image"}
        </div>
      )}
    </NodeWrapper>
  );
}

export function AvatarRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const src = resolveBinding(node.src, ctx);
  const name = (node.name as string) ?? "";
  const sizeClass = avatarSizeClass(node.size as string);
  const shape = node.shape === "rounded" ? "rounded-lg" : "rounded-full";
  const initials = name.split(" ").map((w: string) => w[0]).join("").slice(0, 2).toUpperCase();

  return (
    <NodeWrapper node={node} path={path}>
      <div className={buildClasses("relative inline-flex items-center justify-center bg-gray-200 text-gray-600 font-medium overflow-hidden", sizeClass, shape)}>
        {src ? (
          <img src={String(src)} alt={name} className="w-full h-full object-cover" />
        ) : (
          <span className="text-xs">{initials || "?"}</span>
        )}
      </div>
    </NodeWrapper>
  );
}

export function BadgeRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const content = resolveBinding(node.content, ctx);
  const variant = (node.variant as string) ?? "default";
  const variantClasses: Record<string, string> = {
    default: "bg-gray-100 text-gray-800",
    primary: "bg-blue-100 text-blue-800",
    secondary: "bg-gray-100 text-gray-600",
    success: "bg-green-100 text-green-800",
    warning: "bg-amber-100 text-amber-800",
    danger: "bg-red-100 text-red-800",
  };

  return (
    <NodeWrapper node={node} path={path}>
      <span className={buildClasses("inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium", variantClasses[variant] ?? variantClasses.default)}>
        {node.dot ? <span className="w-1.5 h-1.5 rounded-full bg-current" /> : null}
        {content != null ? String(content) : ""}
      </span>
    </NodeWrapper>
  );
}

export function TagRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const content = resolveBinding(node.content, ctx);

  return (
    <NodeWrapper node={node} path={path}>
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-gray-200 text-xs">
        {content != null ? String(content) : ""}
        {Boolean(node.removable) && (
          <button className="text-gray-400 hover:text-gray-600" onClick={() => node.onRemove && executeAction(node.onRemove as ActionDef, ctx)}>
            &times;
          </button>
        )}
      </span>
    </NodeWrapper>
  );
}

export function ButtonRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const label = resolveBinding(node.label, ctx);
  const variant = (node.variant as string) ?? "primary";
  const size = (node.size as string) ?? "md";
  const disabled = Boolean(node.disabled);

  const variantClasses: Record<string, string> = {
    primary: "bg-blue-600 text-white hover:bg-blue-700",
    secondary: "bg-gray-100 text-gray-900 hover:bg-gray-200",
    ghost: "text-gray-700 hover:bg-gray-100",
    outline: "border border-gray-300 text-gray-700 hover:bg-gray-50",
    danger: "bg-red-600 text-white hover:bg-red-700",
    link: "text-blue-600 hover:underline",
  };

  const sizeClasses: Record<string, string> = {
    sm: "px-3 py-1 text-sm",
    md: "px-4 py-2 text-sm",
    lg: "px-6 py-3 text-base",
  };

  return (
    <NodeWrapper node={node} path={path}>
      <button
        className={buildClasses(
          "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors",
          variantClasses[variant] ?? variantClasses.primary,
          sizeClasses[size] ?? sizeClasses.md,
          node.width === "full" && "w-full",
          disabled && "opacity-50 cursor-not-allowed",
        )}
        disabled={disabled}
        onClick={() => node.action && executeAction(node.action as ActionDef, ctx)}
      >
        {node.loading ? <span className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full" /> : null}
        {label != null ? String(label) : "Button"}
      </button>
    </NodeWrapper>
  );
}

export function StatCardRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const label = resolveBinding(node.label, ctx);
  const value = resolveBinding(node.value, ctx);
  const trend = node.trend as string | undefined;

  return (
    <NodeWrapper node={node} path={path}>
      <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-1">
        <p className="text-sm text-gray-500">{label != null ? String(label) : "Stat"}</p>
        <p className="text-2xl font-semibold">{value != null ? String(value) : "—"}</p>
        {trend && (
          <p className={buildClasses("text-xs", node.trendDirection === "down" ? "text-red-500" : "text-green-500")}>
            {trend}
          </p>
        )}
      </div>
    </NodeWrapper>
  );
}

export function EmptyStateRenderer({ node, path }: NodeRendererProps) {
  const ctx = useRendererContext();
  const action = node.action as { label?: string; action?: ActionDef } | undefined;

  return (
    <NodeWrapper node={node} path={path}>
      <div className="flex flex-col items-center justify-center py-12 text-center">
        {Boolean(node.icon) && <span className="text-gray-300 text-4xl mb-4">&#9679;</span>}
        {Boolean(node.title) && <p className="text-lg font-medium text-gray-900">{String(node.title)}</p>}
        {Boolean(node.message) && <p className="text-sm text-gray-500 mt-1">{String(node.message)}</p>}
        {action?.label && (
          <button
            className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md text-sm"
            onClick={() => action.action && executeAction(action.action, ctx)}
          >
            {action.label}
          </button>
        )}
      </div>
    </NodeWrapper>
  );
}

export function SkeletonRenderer({ node, path }: NodeRendererProps) {
  const variant = (node.variant as string) ?? "text";
  const lines = (node.lines as number) ?? 3;

  return (
    <NodeWrapper node={node} path={path}>
      <div className="animate-pulse space-y-2">
        {variant === "text" && Array.from({ length: lines }).map((_, i) => (
          <div key={i} className={buildClasses("h-4 bg-gray-200 rounded", i === lines - 1 && "w-3/4")} />
        ))}
        {variant === "card" && <div className="h-32 bg-gray-200 rounded-lg" />}
        {variant === "avatar" && <div className="h-10 w-10 bg-gray-200 rounded-full" />}
        {variant === "table" && Array.from({ length: lines }).map((_, i) => (
          <div key={i} className="h-8 bg-gray-200 rounded" />
        ))}
      </div>
    </NodeWrapper>
  );
}

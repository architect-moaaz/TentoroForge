"use client";

import { useState, useCallback, useMemo } from "react";
import { useIREditorStore, getNodeAtPath } from "@/stores/ir-editor";

/**
 * IR Canvas — renders a preview of the IR as styled HTML.
 *
 * Instead of compiling to TSX and running in an iframe, we render a
 * lightweight visual representation directly in React. This gives us
 * instant feedback without the compilation step.
 *
 * For production, this would be replaced with an iframe running the
 * compiled output via a web worker.
 */

import type { IRNode, NodePath } from "@/stores/ir-editor";

// ---------------------------------------------------------------------------
// Style maps
// ---------------------------------------------------------------------------

const SPACING_PX: Record<string, string> = {
  xs: "4px", sm: "8px", md: "16px", lg: "24px", xl: "32px", "2xl": "48px",
};

const TYPOGRAPHY: Record<string, React.CSSProperties> = {
  "heading-1": { fontSize: "24px", fontWeight: 700, letterSpacing: "-0.02em" },
  "heading-2": { fontSize: "20px", fontWeight: 600, letterSpacing: "-0.02em" },
  "heading-3": { fontSize: "18px", fontWeight: 600 },
  body: { fontSize: "14px" },
  "body-sm": { fontSize: "14px", color: "#6b7280" },
  caption: { fontSize: "12px", color: "#9ca3af" },
  overline: { fontSize: "11px", fontWeight: 500, textTransform: "uppercase" as const, letterSpacing: "0.05em", color: "#9ca3af" },
};

const COLOR_MAP: Record<string, string> = {
  primary: "#2563eb",
  muted: "#6b7280",
  danger: "#dc2626",
  warning: "#d97706",
  success: "#16a34a",
  default: "#171717",
};

// ---------------------------------------------------------------------------
// Node renderer
// ---------------------------------------------------------------------------

/** Container node types that accept children drops */
const CONTAINER_TYPES = new Set([
  "Stack", "Row", "Grid", "Card", "AsyncSlot", "ModalTrigger", "Form",
]);

interface RenderNodeProps {
  node: IRNode;
  path: NodePath;
  selectedPath: NodePath | null;
  hoveredPath: NodePath | null;
  onSelect: (path: NodePath) => void;
  onHover: (path: NodePath | null) => void;
  onDrop: (targetPath: NodePath, index: number, data: any) => void;
}

function RenderNode({ node, path, selectedPath, hoveredPath, onSelect, onHover, onDrop }: RenderNodeProps) {
  const isSelected = selectedPath?.join(",") === path.join(",");
  const isHovered = hoveredPath?.join(",") === path.join(",");
  const [dropIndicator, setDropIndicator] = useState<"before" | "inside" | "after" | null>(null);

  const isContainer = CONTAINER_TYPES.has(node.node);

  const outline = isSelected
    ? "2px solid #2563eb"
    : isHovered
      ? "1px dashed #93c5fd"
      : dropIndicator === "inside"
        ? "2px dashed #22c55e"
        : "none";

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onSelect(path);
  };

  const handleMouseEnter = (e: React.MouseEvent) => {
    e.stopPropagation();
    onHover(path);
  };

  const handleMouseLeave = (e: React.MouseEvent) => {
    e.stopPropagation();
    onHover(null);
  };

  // --- Drag source (existing node reorder) ---
  const handleDragStart = useCallback((e: React.DragEvent) => {
    e.stopPropagation();
    const data = JSON.stringify({ source: "tree", fromPath: path });
    e.dataTransfer.setData("text/plain", data);
    e.dataTransfer.setData("application/ir-node", data);
    e.dataTransfer.effectAllowed = "copyMove";
  }, [path]);

  // --- Drop target ---
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();

    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const y = e.clientY - rect.top;
    const height = rect.height;

    if (isContainer) {
      if (y < height * 0.2) {
        setDropIndicator("before");
      } else if (y > height * 0.8) {
        setDropIndicator("after");
      } else {
        setDropIndicator("inside");
      }
    } else {
      if (y < height * 0.5) {
        setDropIndicator("before");
      } else {
        setDropIndicator("after");
      }
    }

    e.dataTransfer.dropEffect = "copy";
  }, [isContainer]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.stopPropagation();
    setDropIndicator(null);
  }, []);

  const handleDropEvent = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDropIndicator(null);

    let raw = e.dataTransfer.getData("application/ir-node");
    if (!raw) raw = e.dataTransfer.getData("text/plain");
    if (!raw) return;

    let data: any;
    try {
      data = JSON.parse(raw);
    } catch {
      return;
    }
    if (!data || !data.source) return;

    if (dropIndicator === "inside" && isContainer) {
      // Drop as last child of this container
      const childCount = Array.isArray(node.children) ? node.children.length : 0;
      onDrop(path, childCount, data);
    } else if (dropIndicator === "before") {
      // Drop as sibling before this node
      if (path.length > 0) {
        const parentPath = path.slice(0, -1);
        const index = path[path.length - 1];
        onDrop(parentPath, index, data);
      }
    } else if (dropIndicator === "after") {
      // Drop as sibling after this node
      if (path.length > 0) {
        const parentPath = path.slice(0, -1);
        const index = path[path.length - 1] + 1;
        onDrop(parentPath, index, data);
      }
    }
  }, [dropIndicator, isContainer, node.children, path, onDrop]);

  // Drop indicator line
  const dropLineStyle: React.CSSProperties | null =
    dropIndicator === "before" ? { position: "absolute", top: -1, left: 0, right: 0, height: 2, background: "#22c55e", zIndex: 50 } :
    dropIndicator === "after" ? { position: "absolute", bottom: -1, left: 0, right: 0, height: 2, background: "#22c55e", zIndex: 50 } :
    null;

  const commonProps = {
    onClick: handleClick,
    onMouseEnter: handleMouseEnter,
    onMouseLeave: handleMouseLeave,
    draggable: path.length > 0, // root is not draggable
    onDragStart: handleDragStart,
    onDragOver: handleDragOver,
    onDragLeave: handleDragLeave,
    onDrop: handleDropEvent,
    style: { outline, outlineOffset: "-1px", position: "relative" as const, cursor: "pointer" },
    "data-ir-path": path.join("."),
  };

  const dropLine = dropLineStyle ? <div style={dropLineStyle} /> : null;

  const renderChildren = (children?: IRNode[]) => {
    if (!Array.isArray(children)) return null;
    return children.map((child, i) => (
      <RenderNode
        key={`${path.join("-")}-${i}`}
        node={child}
        path={[...path, i]}
        selectedPath={selectedPath}
        hoveredPath={hoveredPath}
        onSelect={onSelect}
        onHover={onHover}
        onDrop={onDrop}
      />
    ));
  };

  const sp = (token?: string) => token ? SPACING_PX[token] || token : undefined;

  switch (node.node) {
    case "Stack":
      return (
        <div {...commonProps} style={{
          ...commonProps.style,
          display: "flex", flexDirection: "column",
          gap: sp(node.gap as string),
          padding: sp(node.padding as string),
          width: node.width as string,
          height: node.height === "screen" ? "100%" : node.height as string,
          flex: node.flex ? Number(node.flex) : undefined,
          alignItems: node.align === "center" ? "center" : node.align === "end" ? "flex-end" : undefined,
          justifyContent: node.justify === "center" ? "center" : node.justify === "between" ? "space-between" : node.justify === "end" ? "flex-end" : undefined,
          overflow: node.scroll ? "auto" : undefined,
          minHeight: (!node.children || (node.children as IRNode[]).length === 0) ? "40px" : undefined,
        }}>
          {dropLine}
          {renderChildren(node.children)}
          {(!node.children || (node.children as IRNode[]).length === 0) && dropIndicator === "inside" && (
            <div style={{ padding: "8px", textAlign: "center", fontSize: "11px", color: "#22c55e" }}>Drop here</div>
          )}
        </div>
      );

    case "Row":
      return (
        <div {...commonProps} style={{
          ...commonProps.style,
          display: "flex", flexDirection: "row",
          gap: sp(node.gap as string),
          padding: sp(node.padding as string),
          width: node.width as string,
          height: node.height === "screen" ? "100%" : node.height as string,
          flex: node.flex ? Number(node.flex) : undefined,
          alignItems: node.align === "center" ? "center" : node.align === "end" ? "flex-end" : "stretch",
          justifyContent: node.justify === "center" ? "center" : node.justify === "between" ? "space-between" : node.justify === "end" ? "flex-end" : undefined,
          flexWrap: node.wrap ? "wrap" : undefined,
          minHeight: (!node.children || (node.children as IRNode[]).length === 0) ? "40px" : undefined,
        }}>
          {dropLine}
          {renderChildren(node.children)}
        </div>
      );

    case "Grid":
      return (
        <div {...commonProps} style={{
          ...commonProps.style,
          display: "grid",
          gridTemplateColumns: `repeat(${typeof node.columns === "number" ? node.columns : 2}, 1fr)`,
          gap: sp(node.gap as string),
          padding: sp(node.padding as string),
          minHeight: (!node.children || (node.children as IRNode[]).length === 0) ? "40px" : undefined,
        }}>
          {dropLine}
          {renderChildren(node.children)}
        </div>
      );

    case "Text": {
      const typo = TYPOGRAPHY[(node.typography as string) || "body"] || TYPOGRAPHY.body;
      const displayText = resolveDisplay(node.content as string);
      const textStyle: React.CSSProperties = {
        ...commonProps.style,
        ...typo,
        fontWeight: node.weight ? fontWeightMap(node.weight as string) : typo.fontWeight,
        color: node.color ? COLOR_MAP[node.color as string] || (node.color as string) : typo.color,
        textAlign: (node.align as React.CSSProperties["textAlign"]),
        margin: 0,
      };
      const isHeading = typo === TYPOGRAPHY["heading-1"] || typo === TYPOGRAPHY["heading-2"] || typo === TYPOGRAPHY["heading-3"];
      if (isHeading) {
        return <div {...commonProps} style={textStyle}>{displayText}</div>;
      }
      return <p {...commonProps} style={textStyle}>{displayText}</p>;
    }

    case "Button":
      return (
        <button {...commonProps} style={{
          ...commonProps.style,
          display: "inline-flex", alignItems: "center", gap: "6px",
          padding: node.size === "sm" ? "4px 10px" : "8px 16px",
          fontSize: node.size === "sm" ? "12px" : "14px",
          fontWeight: 500,
          borderRadius: "6px",
          border: node.variant === "outline" || node.variant === "ghost" ? "1px solid #e5e7eb" : "none",
          background: node.variant === "ghost" || node.variant === "outline" || node.variant === "link" ? "transparent"
            : node.variant === "danger" ? "#dc2626" : "#171717",
          color: node.variant === "ghost" || node.variant === "outline" ? "#171717"
            : node.variant === "link" ? "#2563eb" : "#fff",
          width: node.width === "full" ? "100%" : undefined,
        }}>
          {String(node.label)}
        </button>
      );

    case "Badge":
      return (
        <span {...commonProps} style={{
          ...commonProps.style,
          display: "inline-flex", alignItems: "center",
          padding: "2px 8px", borderRadius: "9999px",
          fontSize: "12px", fontWeight: 500,
          background: node.variant === "outline" ? "transparent" : "#f3f4f6",
          border: node.variant === "outline" ? "1px solid currentColor" : "1px solid transparent",
        }}>
          {resolveDisplay(node.content as string)}
        </span>
      );

    case "Card":
      return (
        <div {...commonProps} style={{
          ...commonProps.style,
          border: "1px solid #e5e7eb",
          borderRadius: "8px",
          padding: sp(node.padding as string) || "16px",
          background: "#fff",
          minHeight: (!node.children || (node.children as IRNode[]).length === 0) ? "40px" : undefined,
        }}>
          {dropLine}
          {renderChildren(node.children)}
        </div>
      );

    case "Divider":
      return node.direction === "vertical"
        ? <div {...commonProps} style={{ ...commonProps.style, width: "1px", alignSelf: "stretch", background: "#e5e7eb" }} />
        : <hr {...commonProps} style={{ ...commonProps.style, border: "none", borderTop: "1px solid #e5e7eb", margin: "4px 0" }} />;

    case "Spacer":
      return <div {...commonProps} style={{ ...commonProps.style, height: sp(node.size as string) || "16px" }} />;

    case "TextInput":
      return (
        <div {...commonProps} style={{ ...commonProps.style }}>
          {node.label ? <label style={{ display: "block", fontSize: "13px", fontWeight: 500, marginBottom: "4px" }}>{String(node.label)}</label> : null}
          <input
            style={{
              width: "100%", padding: "6px 10px", fontSize: "13px",
              border: "1px solid #d1d5db", borderRadius: "6px", outline: "none",
            }}
            placeholder={node.placeholder as string}
            readOnly
          />
        </div>
      );

    case "TextArea":
      return (
        <div {...commonProps} style={{ ...commonProps.style }}>
          {node.label ? <label style={{ display: "block", fontSize: "13px", fontWeight: 500, marginBottom: "4px" }}>{String(node.label)}</label> : null}
          <textarea
            style={{
              width: "100%", padding: "6px 10px", fontSize: "13px",
              border: "1px solid #d1d5db", borderRadius: "6px", outline: "none",
              resize: "vertical",
            }}
            rows={(node.rows as number) || 3}
            placeholder={node.placeholder as string}
            readOnly
          />
        </div>
      );

    case "Select":
      return (
        <div {...commonProps} style={{ ...commonProps.style }}>
          {node.label ? <label style={{ display: "block", fontSize: "13px", fontWeight: 500, marginBottom: "4px" }}>{String(node.label)}</label> : null}
          <div style={{
            padding: "6px 10px", fontSize: "13px",
            border: "1px solid #d1d5db", borderRadius: "6px",
            color: "#9ca3af",
          }}>
            {(node.placeholder as string) || "Select..."}
          </div>
        </div>
      );

    case "DataTable":
      return (
        <div {...commonProps} style={{ ...commonProps.style, border: "1px solid #e5e7eb", borderRadius: "8px", overflow: "hidden" }}>
          <table style={{ width: "100%", fontSize: "13px", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#f9fafb" }}>
                {(Array.isArray(node.columns) ? node.columns : []).map((col: any, i: number) => (
                  <th key={i} style={{ padding: "8px 12px", textAlign: "left", fontWeight: 500, borderBottom: "1px solid #e5e7eb" }}>
                    {col.header || col.field}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[1, 2, 3].map((row) => (
                <tr key={row}>
                  {(Array.isArray(node.columns) ? node.columns : []).map((_: any, i: number) => (
                    <td key={i} style={{ padding: "8px 12px", borderBottom: "1px solid #f3f4f6", color: "#6b7280" }}>
                      ···
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "EmptyState":
      return (
        <div {...commonProps} style={{
          ...commonProps.style,
          display: "flex", flexDirection: "column", alignItems: "center",
          padding: "48px 16px", textAlign: "center", gap: "8px",
        }}>
          <div style={{ width: "40px", height: "40px", background: "#f3f4f6", borderRadius: "50%" }} />
          {node.title ? <div style={{ fontSize: "16px", fontWeight: 500 }}>{String(node.title)}</div> : null}
          <div style={{ fontSize: "14px", color: "#6b7280" }}>{String(node.message)}</div>
        </div>
      );

    case "StatCard":
      return (
        <div {...commonProps} style={{
          ...commonProps.style,
          border: "1px solid #e5e7eb", borderRadius: "8px", padding: "16px",
        }}>
          <div style={{ fontSize: "13px", color: "#6b7280" }}>{String(node.label)}</div>
          <div style={{ fontSize: "24px", fontWeight: 700, marginTop: "4px" }}>{resolveDisplay(node.value as string)}</div>
        </div>
      );

    case "Avatar":
      return (
        <div {...commonProps} style={{
          ...commonProps.style,
          width: node.size === "xl" ? "56px" : node.size === "lg" ? "40px" : node.size === "sm" ? "24px" : "32px",
          height: node.size === "xl" ? "56px" : node.size === "lg" ? "40px" : node.size === "sm" ? "24px" : "32px",
          borderRadius: "50%", background: "#e5e7eb",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: "12px", fontWeight: 500, color: "#6b7280",
        }}>
          {((node.name as string) || "?").charAt(0).toUpperCase()}
        </div>
      );

    case "Repeater":
      return (
        <div {...commonProps} style={{ ...commonProps.style, display: "flex", flexDirection: "column", gap: sp(node.gap as string) || "8px" }}>
          <div style={{ fontSize: "10px", color: "#9ca3af", fontStyle: "italic" }}>
            Repeater: {resolveDisplay(node.data as string)}
          </div>
          {(node.template && typeof node.template === "object" && "node" in (node.template as object)) ? (
            <RenderNode node={node.template as unknown as IRNode} path={[...path, 0]} selectedPath={selectedPath} hoveredPath={hoveredPath} onSelect={onSelect} onHover={onHover} onDrop={onDrop} />
          ) : null}
        </div>
      );

    case "Slot":
      return (
        <div {...commonProps} style={{ ...commonProps.style, borderLeft: "2px solid #93c5fd", paddingLeft: "8px" }}>
          <div style={{ fontSize: "10px", color: "#6b7280", fontStyle: "italic" }}>
            Conditional: {node.switch ? `switch(${node.switch})` : node.if ? `if(${node.if})` : "?"}
          </div>
          {(node.then && typeof node.then === "object" && "node" in (node.then as object)) ? <RenderNode node={node.then as unknown as IRNode} path={[...path, 0]} selectedPath={selectedPath} hoveredPath={hoveredPath} onSelect={onSelect} onHover={onHover} onDrop={onDrop} /> : null}
          {(node.cases && typeof node.cases === "object") ? Object.entries(node.cases as Record<string, unknown>).map(([key, caseNode], i) => {
            if (!caseNode || typeof caseNode !== "object" || !("node" in (caseNode as object))) return null;
            return (
              <div key={key}>
                <div style={{ fontSize: "10px", color: "#9ca3af" }}>case: {key}</div>
                <RenderNode node={caseNode as IRNode} path={[...path, i]} selectedPath={selectedPath} hoveredPath={hoveredPath} onSelect={onSelect} onHover={onHover} onDrop={onDrop} />
              </div>
            );
          }) : null}
        </div>
      );

    case "Toggle":
    case "Checkbox":
      return (
        <div {...commonProps} style={{ ...commonProps.style, display: "flex", alignItems: "center", gap: "8px" }}>
          <div style={{ width: "16px", height: "16px", border: "1px solid #d1d5db", borderRadius: node.node === "Toggle" ? "10px" : "3px" }} />
          <span style={{ fontSize: "13px" }}>{String(node.label)}</span>
        </div>
      );

    case "Form":
      return (
        <div {...commonProps} style={{ ...commonProps.style, display: "flex", flexDirection: "column", gap: "12px" }}>
          {dropLine}
          <div style={{ fontSize: "10px", color: "#6b7280", fontStyle: "italic" }}>Form</div>
          {renderChildren(node.children)}
        </div>
      );

    case "Skeleton":
      return (
        <div {...commonProps} style={{ ...commonProps.style, display: "flex", flexDirection: "column", gap: "8px" }}>
          {Array.from({ length: (node.lines as number) || 3 }, (_, i) => (
            <div key={i} style={{ height: "16px", borderRadius: "4px", background: "#f3f4f6", width: i === ((node.lines as number) || 3) - 1 ? "75%" : "100%" }} />
          ))}
        </div>
      );

    default:
      return (
        <div {...commonProps} style={{
          ...commonProps.style,
          padding: "8px", border: "1px dashed #d1d5db", borderRadius: "4px",
          fontSize: "11px", color: "#9ca3af",
        }}>
          {dropLine}
          {node.node}
          {renderChildren(node.children)}
        </div>
      );
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveDisplay(value: string): string {
  if (!value) return "";
  if (value.startsWith("{{")) return value.replace(/\{\{(.+?)\}\}/g, "[$1]");
  if (value.startsWith("source:")) return `[${value}]`;
  if (value.startsWith("state:")) return `[${value}]`;
  return value;
}

function fontWeightMap(w: string): number {
  const map: Record<string, number> = { normal: 400, medium: 500, semibold: 600, bold: 700 };
  return map[w] || 400;
}

// ---------------------------------------------------------------------------
// Main canvas
// ---------------------------------------------------------------------------

export function IRCanvas() {
  const page = useIREditorStore((s) => s.getActivePage());
  const selectedPath = useIREditorStore((s) => s.selectedPath);
  const hoveredPath = useIREditorStore((s) => s.hoveredPath);
  const selectNode = useIREditorStore((s) => s.selectNode);
  const hoverNode = useIREditorStore((s) => s.hoverNode);
  const applyOps = useIREditorStore((s) => s.applyOps);
  const devicePreview = useIREditorStore((s) => s.devicePreview);

  const maxWidth = devicePreview === "mobile" ? "375px" : devicePreview === "tablet" ? "768px" : "100%";

  // Handle drops from palette or tree reorder
  const handleDrop = useCallback((targetPath: NodePath, index: number, data: any) => {
    if (data.source === "palette") {
      // New component from palette
      applyOps([{
        type: "addChild",
        path: targetPath,
        index,
        node: structuredClone(data.template),
      }]);
    } else if (data.source === "tree") {
      // Reorder existing node
      const fromPath = data.fromPath as NodePath;
      if (fromPath.length === 0) return; // can't move root

      const fromParent = fromPath.slice(0, -1);
      const fromIndex = fromPath[fromPath.length - 1];

      // Don't drop onto self
      if (fromParent.join(",") === targetPath.join(",") && fromIndex === index) return;

      applyOps([{
        type: "moveChild",
        path: [],
        from: fromParent,
        fromIndex,
        to: targetPath,
        toIndex: index,
      }]);
    }
  }, [applyOps]);

  // Handle drop on the canvas background (drop as last child of root)
  const handleCanvasDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    let raw = e.dataTransfer.getData("application/ir-node");
    if (!raw) raw = e.dataTransfer.getData("text/plain");
    if (!raw) return;
    let data: any;
    try { data = JSON.parse(raw); } catch { return; }
    if (data?.source === "palette" && page) {
      const childCount = Array.isArray(page.root.children) ? page.root.children.length : 0;
      applyOps([{
        type: "addChild",
        path: [],
        index: childCount,
        node: structuredClone(data.template),
      }]);
    }
  }, [applyOps, page]);

  const handleCanvasDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  if (!page) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        No page selected
      </div>
    );
  }

  return (
    <div
      className="h-full overflow-auto bg-muted/30 p-4"
      onClick={() => selectNode(null)}
      onDrop={handleCanvasDrop}
      onDragOver={handleCanvasDragOver}
    >
      <div
        className="mx-auto bg-white rounded-lg shadow-sm border min-h-[400px]"
        style={{ maxWidth }}
      >
        <RenderNode
          node={page.root}
          path={[]}
          selectedPath={selectedPath}
          hoveredPath={hoveredPath}
          onSelect={selectNode}
          onHover={hoverNode}
          onDrop={handleDrop}
        />
      </div>
    </div>
  );
}

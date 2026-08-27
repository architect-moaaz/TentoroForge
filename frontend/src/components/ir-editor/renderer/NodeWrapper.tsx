"use client";

import { useCallback, useRef, useState } from "react";
import type { NodePath, IRNode } from "./types";
import { useRendererContext } from "./RendererContext";
import { resolveExpression } from "./bindings";
import { useIREditorStore } from "@/stores/ir-editor";
import { ResizeHandles } from "./ResizeHandles";

const CONTAINER_NODES = new Set([
  "Stack", "Row", "Grid", "Card", "AsyncSlot", "ModalTrigger", "Form",
]);

interface NodeWrapperProps {
  node: IRNode;
  path: NodePath;
  children: React.ReactNode;
  className?: string;
}

export function NodeWrapper({ node, path, children, className }: NodeWrapperProps) {
  const ctx = useRendererContext();
  const [dropIndicator, setDropIndicator] = useState<"before" | "after" | "inside" | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Check visibility
  if (node.visible != null) {
    const isVisible = resolveExpression(String(node.visible), ctx);
    if (!isVisible) {
      if (ctx.editable) {
        return (
          <div
            data-ir-path={path.join(".")}
            className="opacity-30 border border-dashed border-gray-300 rounded p-1 text-xs text-gray-400"
            onClick={(e) => { e.stopPropagation(); ctx.onSelect(path); }}
          >
            Hidden: {node.node}
          </div>
        );
      }
      return null;
    }
  }

  const isSelected = ctx.selectedPath?.join(".") === path.join(".");
  const isHovered = ctx.hoveredPath?.join(".") === path.join(".");
  const isContainer = CONTAINER_NODES.has(node.node) || Array.isArray(node.children);

  // --- Click / Hover ---
  const handleClick = useCallback((e: React.MouseEvent) => {
    if (!ctx.editable) return;
    e.stopPropagation();
    ctx.onSelect(path);
  }, [ctx, path]);

  const handleMouseEnter = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (ctx.editable) ctx.onHover(path);
  }, [ctx, path]);

  const handleMouseLeave = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (ctx.editable) ctx.onHover(null);
  }, [ctx]);

  // --- Drag source (reorder existing nodes) ---
  const handleDragStart = useCallback((e: React.DragEvent) => {
    if (!ctx.editable) return;
    e.stopPropagation();
    const data = JSON.stringify({ source: "tree", fromPath: path });
    e.dataTransfer.setData("text/plain", data);
    e.dataTransfer.setData("application/ir-node", data);
    e.dataTransfer.effectAllowed = "copyMove";
  }, [ctx.editable, path]);

  // --- Drop target ---
  const handleDragOver = useCallback((e: React.DragEvent) => {
    if (!ctx.editable) return;
    e.preventDefault();
    e.stopPropagation();

    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const y = e.clientY - rect.top;
    const height = rect.height;

    if (isContainer) {
      if (y < height * 0.2) setDropIndicator("before");
      else if (y > height * 0.8) setDropIndicator("after");
      else setDropIndicator("inside");
    } else {
      if (y < height * 0.5) setDropIndicator("before");
      else setDropIndicator("after");
    }

    e.dataTransfer.dropEffect = "copy";
  }, [ctx.editable, isContainer]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.stopPropagation();
    setDropIndicator(null);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    if (!ctx.editable) return;
    e.preventDefault();
    e.stopPropagation();
    setDropIndicator(null);

    let raw = e.dataTransfer.getData("application/ir-node");
    if (!raw) raw = e.dataTransfer.getData("text/plain");
    if (!raw) return;

    let data: { source: string; fromPath?: number[]; template?: IRNode; nodeType?: string };
    try {
      data = JSON.parse(raw);
    } catch {
      return;
    }
    if (!data || !data.source) return;

    const applyOps = useIREditorStore.getState().applyOps;

    if (data.source === "palette" && data.template) {
      // Drop from palette — add new node
      const newNode = structuredClone(data.template);
      if (dropIndicator === "inside" && isContainer) {
        const childCount = Array.isArray(node.children) ? node.children.length : 0;
        applyOps([{ type: "addChild", path, index: childCount, node: newNode }]);
      } else if (dropIndicator === "before" && path.length > 0) {
        const parentPath = path.slice(0, -1);
        applyOps([{ type: "addChild", path: parentPath, index: path[path.length - 1], node: newNode }]);
      } else if (dropIndicator === "after" && path.length > 0) {
        const parentPath = path.slice(0, -1);
        applyOps([{ type: "addChild", path: parentPath, index: path[path.length - 1] + 1, node: newNode }]);
      }
    } else if (data.source === "tree" && data.fromPath) {
      // Drop from tree — move existing node
      const fromPath = data.fromPath;
      if (dropIndicator === "inside" && isContainer) {
        const childCount = Array.isArray(node.children) ? node.children.length : 0;
        applyOps([{ type: "moveChild", path: [], from: fromPath.slice(0, -1), fromIndex: fromPath[fromPath.length - 1], to: path, toIndex: childCount }]);
      } else if (dropIndicator === "before" && path.length > 0) {
        const parentPath = path.slice(0, -1);
        applyOps([{ type: "moveChild", path: [], from: fromPath.slice(0, -1), fromIndex: fromPath[fromPath.length - 1], to: parentPath, toIndex: path[path.length - 1] }]);
      } else if (dropIndicator === "after" && path.length > 0) {
        const parentPath = path.slice(0, -1);
        applyOps([{ type: "moveChild", path: [], from: fromPath.slice(0, -1), fromIndex: fromPath[fromPath.length - 1], to: parentPath, toIndex: path[path.length - 1] + 1 }]);
      }
    }
  }, [ctx.editable, dropIndicator, isContainer, node.children, path]);

  // --- Styles ---
  const outlineClass = isSelected
    ? "outline outline-2 outline-blue-500 outline-offset-1"
    : isHovered
      ? "outline outline-1 outline-dashed outline-blue-400 outline-offset-1"
      : "";

  const dropBorderClass =
    dropIndicator === "inside" ? "ring-2 ring-green-500 ring-inset" :
    "";

  if (!ctx.editable) return <>{children}</>;

  // Apply explicit width/height from IR node
  const inlineStyle: React.CSSProperties = {};
  if (node.width && typeof node.width === "string" && node.width.endsWith("px")) {
    inlineStyle.width = node.width;
  }
  if (node.height && typeof node.height === "string" && node.height.endsWith("px")) {
    inlineStyle.height = node.height;
  }

  return (
    <div
      ref={wrapperRef}
      data-ir-path={path.join(".")}
      className={[className, outlineClass, dropBorderClass, "relative"].filter(Boolean).join(" ")}
      style={Object.keys(inlineStyle).length > 0 ? inlineStyle : undefined}
      draggable
      onClick={handleClick}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Drop indicator lines */}
      {dropIndicator === "before" && (
        <div className="absolute -top-px left-0 right-0 h-0.5 bg-green-500 z-50" />
      )}
      {dropIndicator === "after" && (
        <div className="absolute -bottom-px left-0 right-0 h-0.5 bg-green-500 z-50" />
      )}
      {children}
      {/* Resize handles — shown only when selected */}
      {isSelected && <ResizeHandles path={path} containerRef={wrapperRef} />}
    </div>
  );
}

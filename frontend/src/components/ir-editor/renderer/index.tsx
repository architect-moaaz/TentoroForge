"use client";

import type { IRNode, NodePath, TokenMap, FragmentDef } from "./types";
import { RendererProvider } from "./RendererContext";
import { RenderNode } from "./RenderNode";

export interface IRRendererProps {
  /** The page IR to render */
  page: {
    $id: string;
    route: string;
    title?: string;
    state?: Record<string, { default?: unknown }>;
    root: IRNode;
    modals?: Record<string, { title?: string; size?: string; root: IRNode }>;
  };
  /** Full AppIR (for tokens, fragments, navigation) */
  appIR?: {
    tokens?: TokenMap;
    fragments?: Record<string, FragmentDef>;
  };
  /** Enable editor interactions (selection, hover, drag) */
  editable?: boolean;
  /** Currently selected node path */
  selectedPath?: NodePath | null;
  /** Currently hovered node path */
  hoveredPath?: NodePath | null;
  /** Callback when a node is selected */
  onSelect?: (path: NodePath) => void;
  /** Callback when a node is hovered */
  onHover?: (path: NodePath | null) => void;
  /** Additional class name for the root container */
  className?: string;
}

/**
 * Runtime IR Renderer.
 *
 * Interprets IR metadata JSON and renders it as React components.
 * Used in the IR editor for instant preview — no compilation step needed.
 *
 * Usage:
 * ```tsx
 * <IRRenderer
 *   page={activePage}
 *   appIR={ir}
 *   editable
 *   selectedPath={selectedPath}
 *   onSelect={selectNode}
 *   onHover={hoverNode}
 * />
 * ```
 */
export function IRRenderer({
  page,
  appIR,
  editable = false,
  selectedPath = null,
  hoveredPath = null,
  onSelect = () => {},
  onHover = () => {},
  className,
}: IRRendererProps) {
  return (
    <RendererProvider
      page={page}
      tokens={appIR?.tokens}
      fragments={appIR?.fragments as Record<string, FragmentDef> | undefined}
      selectedPath={selectedPath}
      hoveredPath={hoveredPath}
      onSelect={onSelect}
      onHover={onHover}
      editable={editable}
    >
      <div
        className={className}
        onClick={() => editable && onSelect([])}
      >
        <RenderNode node={page.root} path={[]} />

        {/* Render modals */}
        {page.modals &&
          Object.entries(page.modals).map(([name, modal]) => (
            <ModalOverlay key={name} name={name} modal={modal} />
          ))}
      </div>
    </RendererProvider>
  );
}

function ModalOverlay({
  name,
  modal,
}: {
  name: string;
  modal: { title?: string; size?: string; root: IRNode };
}) {
  // Modal visibility is managed by RendererContext
  // The actual open/close state is in the context's modals map
  // For now, render nothing — modals are triggered by ModalTrigger/openModal actions
  // A full implementation would check ctx.modals[name] here
  return null;
}

// Re-export key types and components
export { RenderNode } from "./RenderNode";
export type { IRNode, NodePath, NodeRendererProps } from "./types";
